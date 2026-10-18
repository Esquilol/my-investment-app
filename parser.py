"""
parser.py
---------
Extrator de operações de notas de corretagem da B3 / BM&F (PDF).

Layouts suportados
------------------
1. **Genial — BM&F (futuros)**   ``C WIN V26 14/10/2026 1 183.855,0000 DAY TRADE 819,20 C 0,00``
2. **Genial — B3 RV (à vista/opções)** ``B3 RV LISTADOV OPCAO DE COMPRA 09/26 PETRI439 PN 41,67 PETR /EDJ 100 5,50 550,00 C``
3. **Genérico (XP / Clear)** — layout ``<nº> <C|V> <mercado> <ticker> <qtd> <preço> <total>``.

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


# ---------------------------------------------------------------------------
# Expressões regulares
# ---------------------------------------------------------------------------

# Ticker B3: 4 letras + (1-2 dígitos [+ letra de fracionário] | letra de série + 1-3 dígitos)
TICKER_RE = re.compile(r"\b([A-Z]{4}(?:\d{1,2}[A-Z]?|[A-Z]\d{1,3}))\b")

# Data no formato brasileiro (dd/mm/aaaa)
DATE_RE = re.compile(r"(\d{2}/\d{2}/\d{4})")

# Cabeçalho do bloco: "Nr. nota Folha Data pregão \n 76638 1 02/09/2026"
NOTA_HEADER_RE = re.compile(
    r"Nr\.?\s*nota\s+Folha\s+Data\s*preg[ãa]o\s+(?P<num>\d+)\s+\d+\s+(?P<data>\d{2}/\d{2}/\d{4})",
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

# Bloco 3 — Genérico (XP / Clear):
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

# Mercados reconhecidos (aparecem entre C/V e o ticker no layout genérico)
MERCADOS = {
    "VISTA": "VISTA",
    "FRACIONARIO": "FRACIONARIO",
    "FRACIONÁRIO": "FRACIONARIO",
    "OPCAO": "OPCAO",
    "OPÇÃO": "OPCAO",
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
    for chave, nome in MERCADOS.items():
        if chave in upper:
            return nome
    return ""


def _last_valor_dc(linha: str) -> Optional[float]:
    """Extrai o último par "<valor> C|D" de uma linha (ex.: '0,00 C 650,00 C 0,50 D')."""
    pares = re.findall(r"([\d.]+,\d{2})\s*([CD])\b", linha)
    if not pares:
        return None
    return _parse_br_number(pares[-1][0])


def _extrair_despesas(bloco: str) -> float:
    """Total de despesas/corretagem da nota."""
    # BM&F: "Total das despesas" seguido da linha de valores
    m = re.search(r"Total das despesas\s*\n?\s*(?P<linha>[^\n]*)", bloco)
    if m:
        # Linha: + Outros Custos | I.S.S | Ajuste de posição |
        #        Ajuste day trade | Total das despesas
        valores = re.findall(r"([\d.]+,\d{2})", m.group("linha"))
        if valores:
            total = _parse_br_number(valores[-1])
            if total is not None:
                # O I.S.S. fica fora do "Total das despesas" impresso, mas
                # integra o custo da operação (conferido contra os dados de
                # referência: nota 122982/09-09-2026, I.S.S. de 1,22).
                iss = _parse_br_number(valores[1]) if len(valores) >= 2 else 0.0
                return total + (iss or 0.0)

    # B3 RV: "Total corretagem / Despesas 3,25"
    m = re.search(r"Total corretagem\s*/\s*Despesas\s+([\d.]+,\d{2})", bloco)
    if m:
        return _parse_br_number(m.group(1)) or 0.0

    return 0.0


def _extrair_irrf(bloco: str) -> float:
    """IRRF retido na nota (B3: 0,005% das vendas | BM&F: 1% do day trade positivo)."""
    # B3 RV: "I.R.R.F s/ operações, base R$ 576,00	0,02"
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
    )


def _parse_generico(linha: str, meta: dict) -> Optional[Operacao]:
    """Layout genérico (XP / Clear)."""
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
    )


def _parse_line(linha: str, meta: dict) -> Optional[Operacao]:
    """Tenta converter uma linha em Operacao, testando os layouts suportados."""
    linha = linha.rstrip()
    if not linha:
        return None
    for parser in (_parse_futuro, _parse_genial_b3, _parse_generico):
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
        op.taxas = round(despesas * peso / total, 2)


def extract_notas(pdf_file: Union[str, BinaryIO],
                  corretora: str = "Genial",
                  arquivo: Optional[str] = None) -> list[Nota]:
    """
    Extrai as notas de corretagem de um PDF, preservando o agrupamento original.

    Parâmetros
    ----------
    pdf_file : caminho ou arquivo binário do PDF.
    corretora : rótulo da corretora de origem (usado nos relatórios).
    arquivo : nome do arquivo (metadado). Se None, tenta inferir do caminho.

    Retorna
    -------
    list[Nota]
    """
    texto = extract_text(pdf_file)
    nome_arquivo = arquivo or (pdf_file if isinstance(pdf_file, str) else "")

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

        despesas = _extrair_despesas(bloco)
        irrf = _extrair_irrf(bloco)

        meta = {
            "data": data_nota,
            "corretora": corretora,
            "arquivo": nome_arquivo,
            "nota": numero,
            "irrf": irrf,
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
            corretora=corretora,
            arquivo=nome_arquivo,
            despesas=despesas,
            irrf=irrf,
            operacoes=operacoes,
        ))

    return notas


def extract_operations(pdf_file: Union[str, BinaryIO],
                       corretora: str = "Genial",
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
]
