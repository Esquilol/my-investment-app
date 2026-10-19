"""
proventos.py
------------
Importação de proventos (dividendos, JCP, rendimentos, amortizações) a partir
de um extrato em **CSV ou XLSX**.

As notas de corretagem não trazem proventos, então eles vêm de um arquivo
exportado pela corretora ou pela Área do Investidor da B3. O layout varia
bastante entre as fontes, por isso as colunas são localizadas por **sinônimos**
(``Data``, ``Data do pagamento``, ``Ativo``, ``Código``, ``Valor líquido``...)
em vez de por posição.

Regra fiscal aplicada: o **JCP** é tributado exclusivamente na fonte a **15%**
(:func:`irrf_jcp`). Esse valor é definitivo — não entra no DARF 6015 da renda
variável e é informado à parte na declaração.

Uso:
    from proventos import ler_planilha, irrf_jcp

    tabela, ignoradas = ler_planilha("proventos.csv")   # colunas padronizadas
    tabela, ignoradas = ler_planilha(arquivo_uploader)  # arquivo do Streamlit
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd

#: Alíquota do IRRF retido na fonte sobre o JCP.
ALIQUOTA_JCP = 0.15

#: Colunas devolvidas por :func:`ler_planilha`.
COLUNAS = ("data", "ticker", "tipo", "quantidade", "valor")

#: Tipos usados no lançamento manual.
TIPOS = ["Dividendo", "JCP", "Rendimento", "Amortização", "Bonificação",
         "Aluguel", "Sobras"]

#: Sinônimos aceitos para cada coluna do extrato (comparados já sem acento,
#: em minúsculas e sem pontuação).
SINONIMOS: dict[str, set[str]] = {
    "data": {
        "data", "data do pagamento", "data de pagamento", "data pagamento",
        "data do credito", "data de credito", "data credito", "pagamento",
        "data do provento", "data provento",
    },
    "ticker": {
        "ticker", "ativo", "codigo", "codigo do ativo", "codigo de negociacao",
        "papel", "produto", "ativo codigo",
    },
    "tipo": {
        "tipo", "tipo de provento", "tipo do provento", "tipo de evento",
        "tipo do evento", "evento", "provento",
    },
    "quantidade": {
        "quantidade", "qtd", "qtde", "quantity", "quantidade de acoes",
        "quantidade de cotas",
    },
    "valor": {
        "valor", "valor liquido", "valor bruto", "valor total", "valor recebido",
        "valor do provento", "valor creditado", "credito", "liquido", "total",
        "rendimento",
    },
}

#: Texto normalizado -> rótulo canônico do tipo de provento.
TIPOS_CANONICOS: dict[str, str] = {
    "dividendo": "Dividendo",
    "dividendos": "Dividendo",
    "jcp": "JCP",
    "juros sobre capital proprio": "JCP",
    "juros sobre o capital proprio": "JCP",
    "juros sobre capital": "JCP",
    "rendimento": "Rendimento",
    "rendimentos": "Rendimento",
    "amortizacao": "Amortização",
    "amortizacao de fii": "Amortização",
    "amortizacao de cotas": "Amortização",
    "bonificacao": "Bonificação",
    "aluguel": "Aluguel",
    "aluguel de acoes": "Aluguel",
    "sobra": "Sobras",
    "sobras": "Sobras",
}


def irrf_jcp(valor: float) -> float:
    """
    IRRF retido na fonte sobre o JCP (15%).

    É tributação **exclusiva**: o valor é definitivo e não se compensa com o IR
    apurado na renda variável.
    """
    return round(float(valor or 0.0) * ALIQUOTA_JCP, 2)


# ---------------------------------------------------------------------------
# Normalização de texto e números
# ---------------------------------------------------------------------------

def _normalizar(texto: object) -> str:
    """Minúsculas, sem acento e sem pontuação — para comparar cabeçalhos."""
    sem_acento = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"[^a-zA-Z0-9]+", " ", sem_acento).strip().lower()


def _converter_numero(bruto: object) -> float:
    """
    Converte um número em texto para ``float``.

    Aceita ``1.234,56``, ``1,234.56``, ``1234,56`` e ``R$ 1.234,56``. Quando há
    um único separador, ``.`` com exatamente três dígitos depois é tratado como
    separador de milhar.
    """
    if isinstance(bruto, bool):
        return 0.0
    if isinstance(bruto, (int, float)):
        return 0.0 if pd.isna(bruto) else float(bruto)

    texto = re.sub(r"[^0-9,.\-]", "", str(bruto)).strip()
    if not texto or texto in {"-", ".", ","}:
        return 0.0

    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", ".")
    elif texto.count(".") == 1 and len(texto.split(".")[1]) == 3:
        texto = texto.replace(".", "")          # 1.234 -> mil duzentos e trinta e quatro

    try:
        return float(texto)
    except ValueError:
        return 0.0


def _converter_data(bruto: object) -> str | None:
    """Converte a data para ``AAAA-MM-DD``; devolve ``None`` se não reconhecer."""
    if bruto is None:
        return None
    if hasattr(bruto, "strftime"):
        try:
            return bruto.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            return None

    texto = str(bruto).strip()[:10]
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y",
                    "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(texto, formato).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _classificar_tipo(bruto: object) -> str:
    """Mapeia o texto do extrato para um rótulo canônico de tipo de provento."""
    original = "" if bruto is None else str(bruto).strip()
    if not original or original.lower() == "nan":
        return "Outro"
    return TIPOS_CANONICOS.get(_normalizar(original), original.title())


def _localizar_colunas(colunas) -> dict[str, str]:
    """
    Descobre qual coluna do arquivo corresponde a cada coluna padrão.

    Primeiro tenta igualdade exata com os sinônimos; depois aceita prefixo
    (``Valor (R$)`` casa com ``valor``).
    """
    limpas = [(coluna, _normalizar(coluna)) for coluna in colunas]
    mapa: dict[str, str] = {}
    for exato in (True, False):
        for coluna, chave in limpas:
            for campo, sinonimos in SINONIMOS.items():
                if campo in mapa:
                    continue
                bate = chave in sinonimos if exato else chave.startswith(tuple(sinonimos))
                if bate:
                    mapa[campo] = coluna
    return mapa


def _ler_tabela(arquivo) -> pd.DataFrame:
    """Lê o arquivo como texto, sem deixar o pandas adivinhar tipos."""
    nome = getattr(arquivo, "name", None) or str(arquivo)
    if Path(nome).suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(arquivo, dtype=str)
    return pd.read_csv(arquivo, sep=None, engine="python", dtype=str)


def ler_planilha(arquivo) -> tuple[pd.DataFrame, int]:
    """
    Lê um extrato de proventos e devolve ``(tabela, linhas_ignoradas)``.

    ``arquivo`` pode ser um caminho ou o objeto do ``st.file_uploader``. A
    tabela sai com as colunas :data:`COLUNAS`; linhas sem ticker ou sem data
    reconhecível (rodapés de total, por exemplo) são descartadas e contadas em
    ``linhas_ignoradas``.

    Levanta ``ValueError`` se as colunas essenciais (data, ticker e valor) não
    existirem no arquivo.
    """
    if hasattr(arquivo, "seek"):
        arquivo.seek(0)

    bruto = _ler_tabela(arquivo)
    mapa = _localizar_colunas(bruto.columns)

    faltando = [campo for campo in ("data", "ticker", "valor") if campo not in mapa]
    if faltando:
        encontradas = ", ".join(str(c) for c in bruto.columns)
        raise ValueError(
            "não encontrei a(s) coluna(s) "
            + ", ".join(faltando)
            + f" no arquivo. Colunas encontradas: {encontradas}"
        )

    def celula(linha, campo):
        coluna = mapa.get(campo)
        return None if coluna is None else linha[coluna]

    linhas = []
    ignoradas = 0
    for _, linha in bruto.iterrows():
        ticker = str(celula(linha, "ticker") or "").strip().upper()
        data = _converter_data(celula(linha, "data"))
        if not ticker or ticker == "NAN" or data is None:
            ignoradas += 1
            continue
        linhas.append({
            "data": data,
            "ticker": ticker,
            "tipo": _classificar_tipo(celula(linha, "tipo")),
            "quantidade": _converter_numero(celula(linha, "quantidade")),
            "valor": _converter_numero(celula(linha, "valor")),
        })

    return pd.DataFrame(linhas, columns=list(COLUNAS)), ignoradas


__all__ = [
    "ALIQUOTA_JCP", "COLUNAS", "TIPOS", "irrf_jcp", "ler_planilha",
]
