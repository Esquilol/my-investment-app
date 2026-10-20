"""
compatibilidade_notas.py
------------------------
Diagnóstico de compatibilidade do `parser.py` com o layout de notas de
corretagem de diferentes corretoras brasileiras.

Como funciona
-------------
O `parser.py` foi construído a partir de duas famílias de layout:

1. **Genial BM&F**  -> linha de futuro ``C WIN V26 ...``
2. **Genial B3 RV** -> linha ``B3 RV LISTADO<C|V> ...``
3. **Genérico**     -> ``<nº> <C|V> <mercado> <ticker> <qtd> <preço> <total>``
   (pensado para XP / Clear, mas nunca validado contra uma nota real).

Este módulo alimenta o pipeline real do parser (`extract_notas`) com
**amostras textuais sintéticas** que reproduzem o layout documentado das
principais corretoras (SINACOR/B3) e mede, por corretora:

- quantas notas foram reconhecidas;
- quantas operações foram extraídas (e o que deveria ser extraído);
- despesas e IRRF apurados;
- quais âncoras literais do parser casaram/falharam.

As amostras são **100% sintéticas** (tickers públicos, números inventados);
nenhum dado pessoal ou de nota real é usado.

Uso::

    python compatibilidade_notas.py
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass

import parser as P


# ---------------------------------------------------------------------------
# Amostras sintéticas (layout documentado de cada corretora)
# ---------------------------------------------------------------------------

# Layout SINACOR/B3 (XP, Rico, Clear, BTG, Santander, Monte Bravo ...):
# cabeçalho padrão, coluna "Q" = "1-BOVESPA", "Obs" com "D" de day trade e
# resumo financeiro com Clearing / Corretagem / ISS / I.R.R.F.
SINACOR_XP = textwrap.dedent("""\
    NOTA DE CORRETAGEM
    Nr. nota      Folha      Data pregão
      123456        1        05/09/2026

    Q           C/V  Tipo mercado   Prazo  Especificação do título                         Obs  Quantidade  Preço/Ajuste  Valor/Ajuste  D/C
    1-BOVESPA   C    VISTA                 PETROLEO BRASILEIRO S/A - PETROBRAS        PETR4            100        28,50          2.850,00      D
    1-BOVESPA   V    VISTA                 VALE S/A                                   VALE3            100        62,00          6.200,00      C

    Resumo dos Negócios
    Vendas à vista                                                                                                   6.200,00
    Compras à vista                                                                                                  2.850,00
    Valor das operações                                                                                              9.050,00

    Resumo Financeiro
    Valor líquido das operações                                                                                      3.350,00 C
    Taxa de liquidação                                                                                                   1,55 D
    Taxa de registro                                                                                                     0,00 D
    Total CBLC                                                                                                           1,55 D
    Taxa de termo/opções                                                                                                 0,00
    Taxa A.N.A                                                                                                           0,00
    Emolumentos                                                                                                          0,31 D
    Total Bovespa/Soma                                                                                                   0,31 D
    Clearing                                                                                                             2,97 D
    Corretagem                                                                                                          18,90 D
    ISS ( SÃO PAULO )                                                                                                    0,95
    I.R.R.F s/ operações, base R$ 6.200,00                                                                               0,31
    Total custos/despesas                                                                                               23,13 D
    Líquido para 09/09/2026                                                                                          3.326,87 C
""")

SINACOR_CLEAR = textwrap.dedent("""\
    NOTA DE CORRETAGEM
    Nr. nota      Folha      Data pregão
      654321        1        12/09/2026

    Q           C/V  Tipo mercado   Prazo  Especificação do título                         Obs  Quantidade  Preço/Ajuste  Valor/Ajuste  D/C
    1-BOVESPA   C    FRACIONARIO           MAGAZINE LUIZA S/A                         MGLU3             50         9,80            490,00      D
    1-BOVESPA   V    FRACIONARIO           MAGAZINE LUIZA S/A                         MGLU3             50         9,95            497,50      C

    Resumo dos Negócios
    Vendas à vista                                                                                                     497,50
    Compras à vista                                                                                                    490,00
    Valor das operações                                                                                                987,50

    Resumo Financeiro
    Valor líquido das operações                                                                                          7,50 C
    Taxa de liquidação                                                                                                   0,12 D
    Taxa de registro                                                                                                     0,00 D
    Total CBLC                                                                                                           0,12 D
    Emolumentos                                                                                                          0,02 D
    Total Bovespa/Soma                                                                                                   0,02 D
    Clearing                                                                                                             0,60 D
    Corretagem                                                                                                           0,00 D
    ISS ( SÃO PAULO )                                                                                                    0,00
    I.R.R.F s/ operações, base R$ 497,50                                                                                 0,02
    Total Custos Operacionais                                                                                            0,62 D
    Líquido para 16/09/2026                                                                                              7,36 C
""")

SINACOR_RICO = textwrap.dedent("""\
    NOTA DE CORRETAGEM
    Nr. nota      Folha      Data pregão
      778899        1        16/09/2026

    Q           C/V  Tipo mercado   Prazo  Especificação do título                         Obs  Quantidade  Preço/Ajuste  Valor/Ajuste  D/C
    1-BOVESPA   V    VISTA                 ITAU UNIBANCO HOLDING S/A - ITAUSA           ITUB4           200        35,50          7.100,00      C

    Resumo dos Negócios
    Vendas à vista                                                                                                   7.100,00
    Valor das operações                                                                                              7.100,00

    Resumo Financeiro
    Valor líquido das operações                                                                                      7.100,00 C
    Taxa de liquidação                                                                                                   1,77 D
    Taxa de registro                                                                                                     0,00 D
    Total CBLC                                                                                                           1,77 D
    Emolumentos                                                                                                          0,94 D
    Total Bovespa/Soma                                                                                                   0,94 D
    Clearing                                                                                                             2,97 D
    Corretagem                                                                                                           0,00 D
    I.R.R.F s/ operações, base R$ 7.100,00                                                                               1,06
    Total Custos Operacionais                                                                                            5,68 D
    Líquido para 19/09/2026                                                                                          7.094,32 C
""")

# BTG / Santander / demais SINACOR: idênticos em estrutura, mudam os rótulos
# do resumo financeiro (ex.: "Total Custos" em vez de "Total custos/despesas").
SINACOR_BTG = textwrap.dedent("""\
    NOTA DE CORRETAGEM
    Nr. nota      Folha      Data pregão
      990011        1        18/09/2026

    Q           C/V  Tipo mercado   Prazo  Especificação do título                         Obs  Quantidade  Preço/Ajuste  Valor/Ajuste  D/C
    1-BOVESPA   C    OPCAO DE COMPRA       PETROBRAS PN - PETR4                           PETRG28          100         1,20            120,00      D

    Resumo dos Negócios
    Compras à vista                                                                                                    120,00
    Valor das operações                                                                                                120,00

    Resumo Financeiro
    Valor líquido das operações                                                                                        120,00 D
    Taxa de liquidação                                                                                                   0,03 D
    Total CBLC                                                                                                           0,03 D
    Emolumentos                                                                                                          0,01 D
    Total Bovespa/Soma                                                                                                   0,01 D
    Clearing                                                                                                             0,45 D
    Corretagem                                                                                                           4,50 D
    I.R.R.F s/ operações, base R$ 0,00                                                                                   0,00
    Total Custos                                                                                                         4,99 D
    Líquido para 22/09/2026                                                                                            125,04 D
""")

# Controle: amostra no layout Genial B3 RV (deve continuar funcionando).
GENIAL_CONTROLE = textwrap.dedent("""\
    NOTA DE CORRETAGEM
    Nr.Nota      Folha      Data pregão
      11966         1        31/08/2026

    B3 RV LISTADOV VISTA PETROBRAS PN PETR4 100 28,50 2.850,00 C
    B3 RV LISTADOC VISTA VALE ON NM VALE3 100 62,00 6.200,00 D

    Resumo dos Negócios
    Vendas à vista 2.850,00
    Compras à vista 6.200,00

    Resumo Financeiro
    Total corretagem / Despesas 7,75
    Taxa de liquidação/CCP 0,70
    Taxa de Registro 1,77
    Emolumentos 0,94
    I.R.R.F s/ operações, base R$ 2.850,00 0,01
""")

# Controle: amostra no layout Genial BM&F (futuros).
GENIAL_BMF = textwrap.dedent("""\
    NOTA DE CORRETAGEM
    Nr.Nota      Folha      Data pregão
      122982        1        09/09/2026

    C WIN V26 14/10/2026 1 183.855,0000 DAY TRADE 819,20 C 0,00
    V WDO V26 02/10/2026 1 5.412,5000 DAY TRADE 310,00 D 0,00

    Resumo Financeiro
    Total das despesas 1,00 1,22 0,00 0,00 0,00
    IRRF  IRRF Day Trade ( Projeção )  Taxa operacional
    0,00 0,00
""")


@dataclass
class Caso:
    nome: str
    texto: str
    esperado_ops: int


CASOS = [
    Caso("Genial B3 RV (controle)", GENIAL_CONTROLE, 2),
    Caso("Genial BM&F (controle)", GENIAL_BMF, 2),
    Caso("XP", SINACOR_XP, 2),
    Caso("Clear", SINACOR_CLEAR, 2),
    Caso("Rico", SINACOR_RICO, 2),
    Caso("BTG Pactual", SINACOR_BTG, 1),
]


# ---------------------------------------------------------------------------
# Âncoras literais que o parser procura (todas Genial-específicas ou SINACOR)
# ---------------------------------------------------------------------------

ANCORAS = [
    ("Cabeçalho da nota", P.NOTA_HEADER_RE.pattern),
    ("Despesa BM&F", r"Total das despesas"),
    ("Despesa B3 RV", r"Total corretagem\s*/\s*Despesas"),
    ("Taxa de liquidação", r"Taxa de liquida[çc][ãa]o\s*/?\s*CCP"),
    ("Emolumentos", r"Emolumentos"),
    ("IRRF B3", r"I\.?\s*R\.?\s*R\.?\s*F\s*s/\s*opera[çc][õo]es"),
    ("IRRF BM&F", r"IRRF\s+Day\s*Trade\s*\(\s*Proje[çc][ãa]o\s*\)"),
    ("Linha Genial B3 RV", r"B3\s+[A-Z]{2}\s+LISTADO[CV]"),
]


def _analisar(caso: Caso) -> dict:
    """Roda o pipeline real do parser sobre o texto sintético (sem PDF)."""
    original = P.extract_text
    P.extract_text = lambda *a, **k: caso.texto  # monkeypatch: texto no lugar do PDF
    try:
        notas = P.extract_notas(None, corretora=caso.nome, arquivo="sintetico.txt")
    finally:
        P.extract_text = original

    ops = [op for n in notas for op in n.operacoes]
    return {
        "caso": caso,
        "notas": notas,
        "num_notas": len(notas),
        "num_ops": len(ops),
        "ops": ops,
        "despesas": sum(n.despesas for n in notas),
        "irrf": sum(n.irrf for n in notas),
    }


def _ancoras_ok(texto: str) -> dict:
    import re
    return {
        nome: bool(re.search(padrao, texto, re.IGNORECASE))
        for nome, padrao in ANCORAS
    }


def main() -> int:
    print("=" * 78)
    print("DIAGNOSTICO DE COMPATIBILIDADE DE NOTAS DE CORRETAGEM")
    print("=" * 78)

    falhas = 0
    for caso in CASOS:
        r = _analisar(caso)
        esperado = caso.esperado_ops
        status = "OK " if r["num_ops"] == esperado else "FALHA"
        if r["num_ops"] != esperado:
            falhas += 1

        print(f"\n[{status}] {caso.nome}")
        print(f"  notas reconhecidas : {r['num_notas']}")
        print(f"  operacoes extraidas: {r['num_ops']} (esperado: {esperado})")
        print(f"  despesas apuradas  : {r['despesas']:.2f}")
        print(f"  IRRF apurado       : {r['irrf']:.2f}")

        for op in r["ops"]:
            print(f"    - {op.data} {op.tipo} {op.ticker} "
                  f"qtd={op.quantidade:g} preco={op.preco} "
                  f"total={op.valor_total} mercado={op.mercado}")

        ancoras = _ancoras_ok(caso.texto)
        presentes = [n for n, ok in ancoras.items() if ok]
        ausentes = [n for n, ok in ancoras.items() if not ok]
        print(f"  ancoras presentes  : {', '.join(presentes) or '-'}")
        print(f"  ancoras ausentes   : {', '.join(ausentes) or '-'}")

    print("\n" + "=" * 78)
    print(f"RESULTADO: {len(CASOS) - falhas}/{len(CASOS)} amostras compativeis; "
          f"{falhas} falha(s).")
    print("=" * 78)
    return 0 if falhas == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
