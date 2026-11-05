"""
parser.py
---------
Extrator de operações de notas de corretagem da B3 / BM&F (PDF).

Layouts suportados
------------------
1. **Genial — BM&F (futuros)**   ``C WIN V26 14/10/2026 1 183.855,0000 DAY TRADE 819,20 C 0,00``
2. **Genial — B3 RV (à vista/opções)** ``B3 RV LISTADOV OPCAO DE COMPRA 09/26 PETRI439 PN 41,67 PETR /EDJ 100 5,50 550,00 C``
3. **SINACOR/B3 (XP, Clear, Rico, BTG, Inter, Nubank e demais)** — colunas
   ``Q  C/V  Tipo mercado  Prazo  Especificação do título  Obs  Quantidade  Preço  Valor  D/C``
   onde Q começa com ``1-BOVESPA`` (ou similar prefixo de ambiente).
4. **Genérico** — fallback para outros layouts não identificados.

Um PDF pode conter **várias notas** (um bloco ``NOTA DE CORRETAGEM`` cada). O
parser divide o texto em blocos para que cada operação receba a **data do seu
próprio pregão**, as **despesas** e o **IRRF retido** da sua nota — em vez de
usar a data da primeira nota do arquivo.

Uso:
    from parser import extract_notas, extract_operations

    notas = extract_notas("nota.pdf")          # agrupado por nota (data/despesas/IRRF)
    operacoes = extract_operations("nota.pdf") # lista achatada de Operacao
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from datetime import date, datetime
from typing import BinaryIO, Iterable, Optional, Union

import pdfplumber


# ---------------------------------------------------------------------------
# Tipos de dados
# ---------------------------------------------------------------------------

@dataclass
class Operacao:
    """Uma linha de negociação de uma nota de corretagem."""

    data: Optional[date]          # Data do pregão
    tipo: str                     # "C" = Compra, "V" = Venda
    ticker: str                   # PETR4, MXRF11, PETRI439, "WIN V26" (futuro)
    quantidade: float
    preco: float
    valor_total: float            # BR: qtd * preço | Futuro: |ajuste| do dia
    mercado: str = ""             # VISTA, FRACIONARIO, OPCAO, OURO, FUTURO, TERMO
    corretora: str = ""
    arquivo: str = ""
    nota: str = ""                # número da nota de origem
    day_trade: bool = False       # marcado na apuração
    taxas: float = 0.0            # despesas da nota rateadas nesta operação
    irrf: float = 0.0             # IRRF retido na nota (rateado não se aplica)
    resultado: Optional[float] = None  # futuros: ajuste com sinal (C=+ / D=-)
    obs: str = ""                 # observações da linha (ex.: "DAY TRADE")
    folha: str = ""               # folha (página) da nota de origem

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Nota:
    """Uma nota de corretagem (bloco) extraída do PDF."""

    numero: str
    data: Optional[date]
    corretora: str
    arquivo: str
    despesas: float = 0.0
    irrf: float = 0.0
    operacoes: list["Operacao"] = field(default_factory=list)
    folha: str = ""               # folha (página) da nota no PDF


# ---------------------------------------------------------------------------
# Expressões regulares
# ---------------------------------------------------------------------------

# Ticker B3: 4 letras + (1-2 dígitos [+ letra de fracionário] | letra de série + 1-3 dígitos)
TICKER_RE = re.compile(r"\b([A-Z]{4}(?:\d{1,2}[A-Z]?|[A-Z]\d{1,3}))\b")

# Data no formato brasileiro (dd/mm/aaaa)
DATE_RE = re.compile(r"(\d{2}/\d{2}/\d{4})")

# Cabeçalho do bloco: "Nr. nota Folha Data pregão \n 76638 1 02/09/2026"
# A folha identifica cada página de uma nota (algumas notas ocupam 2+ páginas);
# sem ela a segunda folha colidiria com a primeira na chave única do banco.
NOTA_HEADER_RE = re.compile(
    r"Nr\.?\s*nota\s+Folha\s+Data\s*preg[ãa]o\s+(?P<num>\d+)\s+(?P<folha>\d+)\s+"
    r"(?P<data>\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)

# Bloco 1 — Genial BM&F (futuros)
#   C WIN V26 14/10/2026 1 183.855,0000 DAY TRADE 819,20 C 0,00
FUTURO_LINE_RE = re.compile(
    r"^(?P<cv>[CV])\s+"
    r"(?P<merc>[A-Z]{3,4})\s+"
    r"(?P<venc>[A-Z]\d{2})\s+"
    r"(?P<venc_data>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<qtd>\d+)\s+"
    r"(?P<preco>[\d.]+,\d+)\s+"
    r"(?P<obs>.*?)\s+"
    r"(?P<ajuste>[\d.]+,\d{2})\s+"
    r"(?P<dc>[CD])\s+"
    r"(?P<taxa>[\d.]+,\d{2})\s*$"
)

# Bloco 2 — Genial B3 RV (à vista, fracionário, opções)
#   B3 RV LISTADOV OPCAO DE COMPRA 09/26 PETRI439 PN 41,67 PETR /EDJ 100 5,50 550,00 C
GENIAL_B3_LINE_RE = re.compile(
    r"^(?P<head>B3\s+[A-Z]{2}\s+LISTADO(?P<cv>[CV])\b.*?)\s+"
    r"(?P<qtd>[\d.]+)\s+"
    r"(?P<preco>[\d.]+,\d+)\s+"
    r"(?P<valor>[\d.]+,\d{2})\s+"
    r"(?P<dc>[CD])\s*$"
)

# Bloco 3 — SINACOR/B3 (XP, Clear, Rico, BTG, Inter, Nubank e demais)
# Linha: "1-BOVESPA   C    VISTA   PETROLEO BRASILEIRO   PETR4   100   28,50   2.850,00   D"
# A coluna Q (ambiente de negociação) começa com dígito + hífen + letras (ex: "1-BOVESPA").
# Usamos \s{2,} como delimitador entre colunas (colunas sempre separadas por 2+ espaços),
# o que permite que "OPCAO DE COMPRA" (espaço simples interno) seja capturado corretamente.
_NUM_BR = r"[\d.]+,\d{2,4}"
SINACOR_LINE_RE = re.compile(
    r"^\s*(?P<q>\d+-[A-Z]+)\s{2,}"          # Q: "1-BOVESPA" (seguido de 2+ espaços)
    r"(?P<cv>[CV])\s{2,}"                    # C ou V
    r"(?P<mercado>[A-Z][A-Z ]*?)\s{2,}"      # Tipo de mercado (VISTA / FRACIONARIO / OPCAO DE COMPRA)
    r"(?P<especificacao>.*?)\s{2,}"          # Especificação do título (nome da empresa)
    r"(?P<ticker>[A-Z]{4}(?:\d{1,2}[A-Z]?|[A-Z]\d{1,2}))\s{2,}"  # Código do ativo (PETR4, PETRG28)
    r"(?P<qtd>[\d.]+)\s+"
    r"(?P<preco>" + _NUM_BR + r")\s+"
    r"(?P<valor>" + _NUM_BR + r")\s+"
    r"(?P<dc>[CD])\s*$"
)

# Bloco 4 — Genérico (fallback):
#   <nº> <C|V> <mercado?> <...especificação...> <TICKER> <qtd> <preço> <total>
OP_RE = re.compile(
    r"^\s*(?P<num>\d*)\s*"
    r"(?P<cv>[CV])\s+"
    r"(?P<meio>.*?)"
    r"(?P<ticker>[A-Z]{4}\d{1,2}[A-Z]?)\s+"
    r"(?P<qtd>[\d.]+)\s+"
    r"(?P<preco>[\d.]+,\d{2})\s+"
    r"(?P<total>[\d.]+,\d{2})"
)

# Mercados reconhecidos (aparecem entre C/V e o ticker no layout genérico / SINACOR)
MERCADOS = {
    "VISTA": "VISTA",
    "FRACIONARIO": "FRACIONARIO",
    "FRACIONÁRIO": "FRACIONARIO",
    "OPCAO": "OPCAO",
    "OPÇÃO": "OPCAO",
    "OPCAO DE COMPRA": "OPCAO",
    "OPCAO DE VENDA": "OPCAO",
    "OPÇÃO DE COMPRA": "OPCAO",
    "OPÇÃO DE VENDA": "OPCAO",
    "OURO": "OURO",
    "TERMO": "TERMO",
    "FUTURO": "FUTURO",
    "BALCAO": "BALCAO",
    "BALCÃO": "BALCAO",
    "BM": "BM",
}


# ---------------------------------------------------------------------------
# Conversores auxiliares
# ---------------------------------------------------------------------------

def _parse_br_number(value: Union[str, int, float, None]) -> Optional[float]:
    """Converte números no formato brasileiro ("1.234,56") para float."""
    if value is None:
        return None

    s = str(value).strip()
    if not s or s in {"-", "D", "C"}:
        return None

    s = s.replace("R$", "").replace(" ", "")

    if "," in s:
        # "1.234,56" -> 1234.56
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        # "1.234" (separador de milhar) -> 1234
        s = s.replace(".", "")

    try:
        return float(s)
    except ValueError:
        return None


def _parse_br_date(value: Optional[str]) -> Optional[date]:
    """Converte "dd/mm/aaaa" para datetime.date."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _detect_mercado(texto: str) -> str:
    """Identifica o mercado a partir de um trecho de texto da linha."""
    if not texto:
        return ""
    upper = texto.upper()
    # Testa do mais específico para o mais genérico
    for chave in sorted(MERCADOS, key=len, reverse=True):
        if chave in upper:
            return MERCADOS[chave]
    return ""


def _last_valor_dc(linha: str) -> Optional[float]:
    """Extrai o último par "<valor> C|D" de uma linha (ex.: '0,00 C 650,00 C 0,50 D')."""
    pares = re.findall(r"([\d.]+,\d{2})\s*([CD])\b", linha)
    if not pares:
        return None
    return _parse_br_number(pares[-1][0])


def _extrair_despesas(bloco: str) -> float:
    """Total de despesas/corretagem da nota. Suporta layouts Genial e SINACOR."""

    # ------------------------------------------------------------------ #
    # Layout Genial BM&F: "Total das despesas" seguido da linha de valores
    # ------------------------------------------------------------------ #
    m = re.search(r"Total das despesas\s*\n?\s*(?P<linha>[^\n]*)", bloco)
    if m:
        valores = re.findall(r"([\d.]+,\d{2})", m.group("linha"))
        if valores:
            total = _parse_br_number(valores[-1])
            if total is not None:
                # O I.S.S. fica fora do "Total das despesas" impresso, mas
                # integra o custo da operação.
                iss = _parse_br_number(valores[1]) if len(valores) >= 2 else 0.0
                return total + (iss or 0.0)

    # ------------------------------------------------------------------ #
    # Layout Genial B3 RV: "Total corretagem / Despesas" + taxas avulsas
    # ------------------------------------------------------------------ #
    m = re.search(r"Total corretagem\s*/\s*Despesas\s+([\d.]+,\d{2})", bloco)
    if m:
        total = _parse_br_number(m.group(1)) or 0.0
        for padrao in (
            r"Taxa de liquida[çc][ãa]o\s*/?(?:\s*CCP)?\s+([\d.]+,\d{2})",
            r"Taxa de Registro\s+([\d.]+,\d{2})",
            r"Emolumentos\s+([\d.]+,\d{2})",
        ):
            for valor in re.findall(padrao, bloco, re.IGNORECASE):
                total += _parse_br_number(valor) or 0.0
        return total

    # ------------------------------------------------------------------ #
    # Layout SINACOR (XP, Clear, Rico, BTG, Inter e demais):
    # Soma das linhas discriminadas: Clearing, Corretagem, ISS,
    # Taxa de liquidação, Emolumentos.
    # Âncora final: "Total custos/despesas", "Total Custos Operacionais"
    # ou "Total Custos" (BTG).
    # ------------------------------------------------------------------ #

    # Tenta usar o total final impresso na nota para validação/primário
    for padrao_total in (
        r"Total\s+custos/despesas\s+([\d.]+,\d{2})",
        r"Total\s+Custos\s+Operacionais\s+([\d.]+,\d{2})",
        r"Total\s+Custos\s+([\d.]+,\d{2})",
    ):
        m = re.search(padrao_total, bloco, re.IGNORECASE)
        if m:
            return _parse_br_number(m.group(1)) or 0.0

    # Fallback: soma os componentes individualmente
    total_sinacor = 0.0
    padroes_componentes = [
        r"Taxa de liquida[çc][ãa]o\s+([\d.]+,\d{2})",
        r"Taxa de Registro\s+([\d.]+,\d{2})",
        r"Emolumentos\s+([\d.]+,\d{2})",
        r"Clearing\s+([\d.]+,\d{2})",
        r"Corretagem\s+([\d.]+,\d{2})",
        r"ISS\s*(?:\([^)]*\))?\s+([\d.]+,\d{2})",
    ]
    encontrou = False
    for padrao in padroes_componentes:
        for valor in re.findall(padrao, bloco, re.IGNORECASE):
            v = _parse_br_number(valor)
            if v is not None:
                total_sinacor += v
                encontrou = True
    if encontrou:
        return round(total_sinacor, 2)

    return 0.0


def _extrair_irrf(bloco: str) -> float:
    """IRRF retido na nota (B3: 0,005% das vendas | BM&F: 1% do day trade positivo)."""
    # B3 RV e SINACOR: "I.R.R.F s/ operações, base R$ 576,00\t0,02"
    m = re.search(r"I\.?\s*R\.?\s*R\.?\s*F\s*s/\s*opera[çc][õo]es[^\n]*?([\d.]+,\d{2})\s*$",
                  bloco, re.IGNORECASE | re.MULTILINE)
    if m:
        return _parse_br_number(m.group(1)) or 0.0

    # BM&F: "IRRF  IRRF Day Trade ( Projeção )  Taxa operacional ..." + linha de valores
    m = re.search(r"IRRF\s+Day\s*Trade\s*\(\s*Proje[çc][ãa]o\s*\)[^\n]*\n(?P<linha>[^\n]+)",
                  bloco, re.IGNORECASE)
    if m:
        valores = re.findall(r"([\d.]+,\d{2})", m.group("linha"))
        if len(valores) >= 2:
            return _parse_br_number(valores[1]) or 0.0

    return 0.0


# ---------------------------------------------------------------------------
# Leitura do PDF
# ---------------------------------------------------------------------------

def extract_text(pdf_file: Union[str, BinaryIO]) -> str:
    """Extrai o texto bruto de todas as páginas de um PDF."""
    partes: list[str] = []
    with pdfplumber.open(pdf_file) as pdf:
        for pagina in pdf.pages:
            partes.append(pagina.extract_text() or "")
    return "\n".join(partes)


# ---------------------------------------------------------------------------
# Extração das operações
# ---------------------------------------------------------------------------

def _parse_futuro(linha: str, meta: dict) -> Optional[Operacao]:
    """Layout Genial BM&F: o campo de ajuste já é o resultado do dia."""
    m = FUTURO_LINE_RE.match(linha)
    if not m:
        return None

    ajuste = _parse_br_number(m.group("ajuste"))
    if ajuste is None:
        return None

    sinal = 1.0 if m.group("dc").upper() == "C" else -1.0
    resultado = sinal * ajuste
    obs = (m.group("obs") or "").strip()

    return Operacao(
        data=meta["data"],
        tipo=m.group("cv").upper(),
        ticker=f"{m.group('merc').upper()} {m.group('venc').upper()}",
        quantidade=_parse_br_number(m.group("qtd")) or 0.0,
        preco=_parse_br_number(m.group("preco")) or 0.0,
        valor_total=abs(resultado),
        mercado="FUTURO",
        corretora=meta["corretora"],
        arquivo=meta["arquivo"],
        nota=meta["nota"],
        day_trade="DAY TRADE" in obs.upper(),
        irrf=meta["irrf"],
        resultado=resultado,
        obs=obs,
        folha=meta.get("folha", ""),
    )


def _parse_genial_b3(linha: str, meta: dict) -> Optional[Operacao]:
    """Layout Genial B3 RV (à vista, fracionário e opções)."""
    m = GENIAL_B3_LINE_RE.match(linha)
    if not m:
        return None

    head = m.group("head")
    tm = TICKER_RE.search(head)
    if not tm:
        return None

    quantidade = _parse_br_number(m.group("qtd"))
    preco = _parse_br_number(m.group("preco"))
    valor = _parse_br_number(m.group("valor"))
    if quantidade is None or preco is None or valor is None:
        return None

    return Operacao(
        data=meta["data"],
        tipo=m.group("cv").upper(),
        ticker=tm.group(1),
        quantidade=quantidade,
        preco=preco,
        valor_total=valor,
        mercado=_detect_mercado(head) or "VISTA",
        corretora=meta["corretora"],
        arquivo=meta["arquivo"],
        nota=meta["nota"],
        irrf=meta["irrf"],
        obs=head,
        folha=meta.get("folha", ""),
    )


def _parse_sinacor(linha: str, meta: dict) -> Optional[Operacao]:
    """Layout SINACOR/B3 (XP, Clear, Rico, BTG, Inter, Nubank e demais).

    Linha: "1-BOVESPA   C    VISTA   PETROLEO BRASILEIRO   PETR4   100   28,50   2.850,00   D"
    A coluna Q (ambiente de negociação) começa com dígito-hífen-letras maiúsculas.
    """
    m = SINACOR_LINE_RE.match(linha)
    if not m:
        return None

    quantidade = _parse_br_number(m.group("qtd"))
    preco = _parse_br_number(m.group("preco"))
    valor = _parse_br_number(m.group("valor"))
    if quantidade is None or preco is None or valor is None:
        return None

    mercado_raw = m.group("mercado").strip()
    mercado = _detect_mercado(mercado_raw) or "VISTA"

    return Operacao(
        data=meta["data"],
        tipo=m.group("cv").upper(),
        ticker=m.group("ticker").upper(),
        quantidade=quantidade,
        preco=preco,
        valor_total=valor,
        mercado=mercado,
        corretora=meta["corretora"],
        arquivo=meta["arquivo"],
        nota=meta["nota"],
        irrf=meta["irrf"],
        obs=m.group("especificacao").strip(),
        folha=meta.get("folha", ""),
    )


def _parse_generico(linha: str, meta: dict) -> Optional[Operacao]:
    """Layout genérico (fallback para outros modelos)."""
    m = OP_RE.match(linha)
    if not m:
        return None

    quantidade = _parse_br_number(m.group("qtd"))
    preco = _parse_br_number(m.group("preco"))
    total = _parse_br_number(m.group("total"))
    if quantidade is None or preco is None or total is None:
        return None

    return Operacao(
        data=meta["data"],
        tipo=m.group("cv").upper(),
        ticker=m.group("ticker").upper(),
        quantidade=quantidade,
        preco=preco,
        valor_total=total,
        mercado=_detect_mercado(m.group("meio")) or "VISTA",
        corretora=meta["corretora"],
        arquivo=meta["arquivo"],
        nota=meta["nota"],
        irrf=meta["irrf"],
        obs=m.group("meio").strip(),
        folha=meta.get("folha", ""),
    )


def _parse_line(linha: str, meta: dict) -> Optional[Operacao]:
    """Tenta converter uma linha em Operacao, testando os layouts suportados."""
    linha = linha.rstrip()
    if not linha:
        return None
    for parser in (_parse_futuro, _parse_genial_b3, _parse_sinacor, _parse_generico):
        op = parser(linha, meta)
        if op is not None:
            return op
    return None


def _ratear_despesas(operacoes: list[Operacao], despesas: float) -> None:
    """Distribui as despesas da nota entre as operações, proporcionalmente ao valor."""
    if not operacoes or despesas <= 0:
        return
    pesos = [
        abs(op.resultado) if op.resultado is not None else abs(op.valor_total)
        for op in operacoes
    ]
    total = sum(pesos)
    if total <= 0:
        return
    for op, peso in zip(operacoes, pesos):
        op.taxas = round(despesas * peso / total, 4)


#: Padrões regex para identificação automática da corretora pelo cabeçalho da nota
PADROES_CORRETORAS: list[tuple[str, list[str]]] = [
    ("Genial", [
        r"GENIAL\s+CCTVM",
        r"GENIAL\s+INVESTIMENTOS",
        r"05\.816\.451/0001-15",
        r"05816451000115",
        r"ouvidoria@genial\.com\.vc",
        r"genialinvestimentos\.com\.br",
    ]),
    ("XP Investimentos", [
        r"XP\s+INVESTIMENTOS\s+CCTVM",
        r"XP\s+INVESTIMENTOS",
        r"02\.332\.886/0001-04",
        r"02332886000104",
        r"xpi\.com\.br",
    ]),
    ("Clear", [
        r"CLEAR\s+CORRETORA",
        r"CLEAR\s+DISTRIBUIDORA",
        r"02\.332\.886/0011-78",
        r"clear\.com\.br",
    ]),
    ("Rico", [
        r"RICO\s+INVESTIMENTOS",
        r"RICO\s+CORRETORA",
        r"02\.332\.886/0010-97",
        r"rico\.com\.vc",
    ]),
    ("BTG Pactual", [
        r"BTG\s+PACTUAL",
        r"30\.306\.294/0002-26",
        r"07\.472\.932/0001-29",
        r"btgpactual\.com",
    ]),
    ("Inter", [
        r"INTER\s+DTVM",
        r"BANCO\s+INTER",
        r"18\.945\.670/0001-46",
        r"inter\.co",
    ]),
    ("Nubank", [
        r"NU\s+INVEST",
        r"EASYNVEST",
        r"NUBANK",
        r"62\.169\.875/0001-79",
        r"nuinvest\.com\.br",
    ]),
    ("Santander", [
        r"SANTANDER\s+C[C|T]VM",
        r"BANCO\s+SANTANDER",
        r"51\.014\.223/0001-70",
    ]),
    ("Ágora", [
        r"AGORA\s+C[T|C]VM",
        r"AGORA\s+CORRETORA",
        r"74\.014\.747/0001-35",
        r"agorainvestimentos\.com\.br",
    ]),
    ("Toro", [
        r"TORO\s+C[T|C]VM",
        r"TORO\s+INVESTIMENTOS",
        r"29\.162\.769/0001-98",
        r"toroinvestimentos\.com\.br",
    ]),
    ("Mirae", [
        r"MIRAE\s+ASSET",
        r"12\.392\.983/0001-38",
    ]),
]


def detectar_corretora(texto: str) -> Optional[str]:
    """
    Identifica a corretora emissora a partir do texto ou cabeçalho da nota de corretagem.
    Retorna o nome padronizado da corretora ou None se não reconhecido.
    """
    if not texto:
        return None
    for nome, padroes in PADROES_CORRETORAS:
        for padrao in padroes:
            if re.search(padrao, texto, re.IGNORECASE):
                return nome
    return None


def extract_notas(pdf_file: Union[str, BinaryIO],
                  corretora: str = "Detectar automaticamente (recomendado)",
                  arquivo: Optional[str] = None) -> list[Nota]:
    """
    Extrai as notas de corretagem de um PDF, preservando o agrupamento original.

    Parâmetros
    ----------
    pdf_file : caminho ou arquivo binário do PDF.
    corretora : rótulo da corretora de origem (ou 'Detectar automaticamente').
    arquivo : nome do arquivo (metadado). Se None, tenta inferir do caminho.

    Retorna
    -------
    list[Nota]
    """
    texto = extract_text(pdf_file)
    nome_arquivo = arquivo or (pdf_file if isinstance(pdf_file, str) else "")
    corretora_doc = detectar_corretora(texto)

    be = NOTA_HEADER_RE.search(texto)
    data_fallback = _parse_br_date(be.group("data")) if be else None
    if data_fallback is None:
        m = DATE_RE.search(texto)
        data_fallback = _parse_br_date(m.group(1)) if m else None

    # PDFs sem o cabeçalho "NOTA DE CORRETAGEM" viram um único bloco genérico.
    blocos = [b for b in re.split(r"NOTA DE CORRETAGEM", texto) if b.strip()]

    notas: list[Nota] = []
    for i, bloco in enumerate(blocos, start=1):
        cab = NOTA_HEADER_RE.search(bloco)
        data_nota = _parse_br_date(cab.group("data")) if cab else data_fallback
        numero = cab.group("num") if cab else f"{i}"
        folha = cab.group("folha") if cab else ""

        despesas = _extrair_despesas(bloco)
        irrf = _extrair_irrf(bloco)

        # Resolução da corretora: auto-detecção por bloco ou documento têm prioridade
        # caso detectada, evitando falso rótulo padrão de selectbox.
        corretora_bloco = detectar_corretora(bloco) or corretora_doc
        if corretora_bloco:
            corretora_final = corretora_bloco
        elif corretora and corretora not in ("Detectar automaticamente (recomendado)", "Auto", ""):
            corretora_final = corretora
        else:
            corretora_final = "Genérico (SINACOR)"

        meta = {
            "data": data_nota,
            "corretora": corretora_final,
            "arquivo": nome_arquivo,
            "nota": numero,
            "irrf": irrf,
            "folha": folha,
        }

        operacoes: list[Operacao] = []
        for linha in bloco.splitlines():
            op = _parse_line(linha, meta)
            if op is not None:
                operacoes.append(op)

        if not operacoes:
            continue

        _ratear_despesas(operacoes, despesas)
        notas.append(Nota(
            numero=numero,
            data=data_nota,
            corretora=corretora_final,
            arquivo=nome_arquivo,
            despesas=despesas,
            irrf=irrf,
            operacoes=operacoes,
            folha=folha,
        ))

    return notas


def extract_operations(pdf_file: Union[str, BinaryIO],
                       corretora: str = "Detectar automaticamente (recomendado)",
                       arquivo: Optional[str] = None) -> list[Operacao]:
    """Lista achatada de todas as operações de um PDF (uma linha por negócio)."""
    operacoes: list[Operacao] = []
    for nota in extract_notas(pdf_file, corretora=corretora, arquivo=arquivo):
        operacoes.extend(nota.operacoes)
    return operacoes


def operations_to_dicts(operacoes: Iterable[Operacao]) -> list[dict]:
    """Converte uma lista de Operacao em lista de dicionários (para DataFrame)."""
    return [op.as_dict() for op in operacoes]


__all__ = [
    "Operacao",
    "Nota",
    "extract_text",
    "extract_notas",
    "extract_operations",
    "operations_to_dicts",
    "detectar_corretora",
    "PADROES_CORRETORAS",
]
