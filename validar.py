"""
validar.py
----------
Verificação automática do motor fiscal (``regras.py``), da persistência
(``persistencia.py``), da importação de proventos (``proventos.py``) e do
login local (``auth.py``).

Não depende de ``pytest`` — basta executar:

    python validar.py

Os valores esperados vêm dos dados de referência de Setembro/2026,
documentados em ``ANALISE_REFERENCIA.md``.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

from auth import definir_senha, gerar_hash, tem_usuario, verificar_senha
from parser import extract_notas
from persistencia import (
    carregar_notas,
    carregar_operacoes,
    carregar_proventos,
    conectar,
    salvar_notas,
    salvar_proventos,
)
from proventos import irrf_jcp, ler_planilha
from regras import (
    ROTULO_MERCADO,
    apurar_mensal,
    bucket_tributario,
    classificar_grupo,
    resultados_realizados,
)

_falhas: list[str] = []


def _checar(descricao: str, obtido, esperado, tolerancia: float = 0.011) -> None:
    if isinstance(esperado, (int, float)) and isinstance(obtido, (int, float)):
        ok = abs(float(obtido) - float(esperado)) <= tolerancia
    else:
        ok = obtido == esperado
    marca = "OK  " if ok else "FALHA"
    print(f"  [{marca}] {descricao:<52} obtido={obtido!r:<14} esperado={esperado!r}")
    if not ok:
        _falhas.append(descricao)


def _frame_resultados(linhas, mes: str = "2026-09") -> pd.DataFrame:
    """Monta um DataFrame no formato de ``resultados_realizados``."""
    registros = []
    for grupo, categoria, resultado, vendas in linhas:
        registros.append({
            "data": pd.Timestamp(f"{mes}-15"),
            "mes": mes,
            "ticker": "TESTE",
            "grupo": grupo,
            "rotulo": ROTULO_MERCADO[grupo],
            "categoria": categoria,
            "bucket": bucket_tributario(grupo, categoria == "Day Trade"),
            "quantidade": 1.0,
            "vendas": vendas,
            "resultado": resultado,
        })
    return pd.DataFrame(registros)


def _notas(irrf_day: float, irrf_swing: float, mes: str = "2026-09") -> pd.DataFrame:
    return pd.DataFrame([
        {"numero": "1", "corretora": "Genial", "data": f"{mes}-02", "arquivo": "a",
         "despesas": 0.0, "irrf": irrf_day, "categoria_irrf": "DayTrade"},
        {"numero": "2", "corretora": "Genial", "data": f"{mes}-02", "arquivo": "a",
         "despesas": 0.0, "irrf": irrf_swing, "categoria_irrf": "SwingTrade"},
    ])


# ---------------------------------------------------------------------------
# 1. Classificação de ativos
# ---------------------------------------------------------------------------

def teste_classificacao() -> None:
    print("\n1. Classificação de ativos (GroupsFee)")
    _checar("PETR4 (vista) -> STOCK", classificar_grupo("PETR4", "VISTA"), "STOCK")
    _checar("MXRF11 (vista) -> FII", classificar_grupo("MXRF11", "VISTA"), "FII")
    _checar("BOVA11 (vista) -> ETF", classificar_grupo("BOVA11", "VISTA"), "ETF")
    _checar("AAPL34 (vista) -> BDR", classificar_grupo("AAPL34", "VISTA"), "BDR")
    _checar("PETRI439 (opcao) -> OPTION", classificar_grupo("PETRI439", "OPCAO"), "OPTION")
    _checar("WIN V26 (futuro) -> FUTIDX", classificar_grupo("WIN V26", "FUTURO"), "FUTIDX")
    _checar("WDO V26 (futuro) -> FUTUSD", classificar_grupo("WDO V26", "FUTURO"), "FUTUSD")
    _checar("DI1F27 (futuro) -> FUTFEE", classificar_grupo("DI1F27", "FUTURO"), "FUTFEE")


# ---------------------------------------------------------------------------
# 2. Reconciliação com os dados de referência — Setembro/2026
# ---------------------------------------------------------------------------

def teste_reconciliacao_referencia() -> None:
    """
    Alimenta o motor com os resultados apurados em Set/2026 e
    confere se as fórmulas de isenção, compensação e alíquota reproduzem a
    apuração oficial.
    """
    print("\n2. Reconciliação com os dados de referência (Set/2026)")
    resultados = _frame_resultados([
        ("FUTIDX", "Day Trade", 384.87, 0.0),
        ("FUTUSD", "Day Trade", -50.57, 0.0),
        ("OPTION", "Day Trade", -1.75, 0.0),
        ("OPTION", "Swing Trade", 1050.37, 50000.0),
    ])
    tabela, _ = apurar_mensal(
        resultados,
        _notas(irrf_day=12.98, irrf_swing=0.16),
        {"DayTrade": -91.38, "SwingTrade": 0.0, "FII": 0.0},
    )
    linha = tabela.iloc[0]

    _checar("ResultsDayTrade", linha["ResultsDayTrade"], 332.55)
    _checar("ResultsSwingTrade", linha["ResultsSwingTrade"], 1050.37)
    _checar("ResultsFutureIDXDayTrade", linha["ResultsFutureIDXDayTrade"], 384.87)
    _checar("ResultsFutureUSDDayTrade", linha["ResultsFutureUSDDayTrade"], -50.57)
    _checar("PreviousAcumulatedLossDayTrade", linha["PreviousAcumulatedLossDayTrade"], -91.38)
    _checar("BaseCalcDayTrade (332,55 - 91,38)", linha["BaseCalcDayTrade"], 241.17)
    _checar("BaseCalcSwingTrade", linha["BaseCalcSwingTrade"], 1050.37)
    _checar("IRRFBaseDayTrade (20%)", linha["IRRFBaseDayTrade"], 48.23)
    _checar("IRRFBaseSwingTrade (15%)", linha["IRRFBaseSwingTrade"], 157.56)
    _checar("IRRFBase", linha["IRRFBase"], 205.79)
    _checar("IRRFMonthlyDayTrade", linha["IRRFMonthlyDayTrade"], 12.98)
    _checar("IRRFMonthlySwingTrade", linha["IRRFMonthlySwingTrade"], 0.16)
    _checar("IRRFFinal (192,65)", linha["IRRFFinal"], 192.65)
    _checar("DARFFinal", linha["DARFFinal"], 192.65)
    _checar("ExemptionMessage", linha["ExemptionMessage"], "DARF a pagar")


# ---------------------------------------------------------------------------
# 3. Isenção de R$ 20.000,00 nas vendas de ações
# ---------------------------------------------------------------------------

def teste_isencao() -> None:
    print("\n3. Isenção por limite de vendas (STOCK / ExemptionValue 20.000)")

    dentro, _ = apurar_mensal(
        _frame_resultados([("STOCK", "Swing Trade", 1500.0, 19000.0)]), None, None)
    _checar("vendas 19.000 -> isento (base 0)", dentro.iloc[0]["BaseCalcSwingTrade"], 0.0)
    _checar("vendas 19.000 -> IR 0", dentro.iloc[0]["IRRFFinal"], 0.0)

    fora, _ = apurar_mensal(
        _frame_resultados([("STOCK", "Swing Trade", 1500.0, 25000.0)]), None, None)
    _checar("vendas 25.000 -> base 1.500", fora.iloc[0]["BaseCalcSwingTrade"], 1500.0)
    _checar("vendas 25.000 -> IR 225 (15%)", fora.iloc[0]["IRRFFinal"], 225.0)

    opcao, _ = apurar_mensal(
        _frame_resultados([("OPTION", "Swing Trade", 1500.0, 19000.0)]), None, None)
    _checar("OPTION sem isenção -> IR 225", opcao.iloc[0]["IRRFFinal"], 225.0)

    fii, _ = apurar_mensal(
        _frame_resultados([("FII", "Swing Trade", 1000.0, 19000.0)]), None, None)
    _checar("FII alíquota 20% -> IR 200", fii.iloc[0]["IRRFFinal"], 200.0)
    _checar("FII em bucket próprio", fii.iloc[0]["ResultsSwingTrade"], 0.0)


# ---------------------------------------------------------------------------
# 4. Compensação de prejuízo entre meses
# ---------------------------------------------------------------------------

def teste_compensacao() -> None:
    print("\n4. Compensação de prejuízo entre meses")
    resultados = pd.concat([
        _frame_resultados([("OPTION", "Swing Trade", -1000.0, 50000.0)], mes="2026-08"),
        _frame_resultados([("OPTION", "Swing Trade", 1500.0, 50000.0)], mes="2026-09"),
    ], ignore_index=True)

    tabela, saldos = apurar_mensal(resultados, None, None)
    agosto, setembro = tabela.iloc[0], tabela.iloc[1]

    _checar("ago: prejuízo acumulado -1.000", agosto["BaseCalcSwingTrade"], -1000.0)
    _checar("ago: IR 0", agosto["IRRFFinal"], 0.0)
    _checar("set: prejuízo anterior -1.000", setembro["PreviousAcumulatedLossSwingTrade"], -1000.0)
    _checar("set: base 500 (1.500 - 1.000)", setembro["BaseCalcSwingTrade"], 500.0)
    _checar("set: IR 75 (15% de 500)", setembro["IRRFFinal"], 75.0)
    _checar("saldo final zerado", saldos["SwingTrade"], 0.0)


# ---------------------------------------------------------------------------
# 5. IRRF retido: compensação e transporte entre meses
# ---------------------------------------------------------------------------

def teste_irrf_compensacao() -> None:
    """
    O IRRF retido que excede o IR apurado não pode ser descartado: ele fica
    acumulado e abate o IR das competências seguintes (campos ``IRRFNextMonth*``
    e ``IRRFPrevious*`` do relatório de referência).
    """
    print("\n5. IRRF retido: compensação entre meses")
    resultados = pd.concat([
        _frame_resultados([("OPTION", "Swing Trade", 1000.0, 50000.0)], mes="2026-08"),
        _frame_resultados([("OPTION", "Swing Trade", 1000.0, 50000.0)], mes="2026-09"),
    ], ignore_index=True)
    # ago: IRRF retido de 200 sobre um IR de 150 -> sobram 50 para setembro
    notas = pd.concat([
        _notas(irrf_day=0.0, irrf_swing=200.0, mes="2026-08"),
        _notas(irrf_day=0.0, irrf_swing=0.0, mes="2026-09"),
    ], ignore_index=True)

    tabela, saldos = apurar_mensal(resultados, notas, None)
    agosto, setembro = tabela.iloc[0], tabela.iloc[1]

    _checar("ago: IR apurado 150 (15%)", agosto["IRRFBaseSwingTrade"], 150.0)
    _checar("ago: IRRF retido 200", agosto["IRRFMonthlySwingTrade"], 200.0)
    _checar("ago: nada a pagar", agosto["IRRFFinal"], 0.0)
    _checar("ago: IRRF a transportar 50", agosto["IRRFNextMonthSwingTrade"], 50.0)
    _checar("set: IRRF anterior 50", setembro["IRRFPreviousSwingTrade"], 50.0)
    _checar("set: IRRF compensado 50", setembro["IRRFUsedSwingTrade"], 50.0)
    _checar("set: IR a pagar 100 (150 - 50)", setembro["IRRFFinal"], 100.0)
    _checar("saldo de IRRF final zerado", saldos["ir_swing"], 0.0)

    # saldo inicial de IRRF informado manualmente também é usado
    _, saldos_iniciais = apurar_mensal(
        _frame_resultados([("OPTION", "Swing Trade", 1000.0, 50000.0)], mes="2026-09"),
        None,
        {"ir_swing": 60.0},
    )
    _checar("IRRF inicial 60 transportado", saldos_iniciais["ir_swing"], 0.0)


# ---------------------------------------------------------------------------
# 6. Deduplicação por número de nota
# ---------------------------------------------------------------------------

def teste_deduplicacao(pdfs: list[Path]) -> None:
    print("\n6. Deduplicação de notas repetidas")
    if not pdfs:
        print("  [-----] PDFs de exemplo não encontrados — teste ignorado")
        return

    with tempfile.TemporaryDirectory() as pasta:
        banco = Path(pasta) / "teste.db"
        conexao = conectar(banco)

        for arquivo in pdfs:
            salvar_notas(conexao, extract_notas(str(arquivo), arquivo=arquivo.name))
        total_notas = len(carregar_notas(conexao))
        total_ops = len(carregar_operacoes(conexao))

        # reimporta tudo: nada deve ser somado de novo
        for arquivo in pdfs:
            salvar_notas(conexao, extract_notas(str(arquivo), arquivo=arquivo.name))
        _checar("notas após reimportação", len(carregar_notas(conexao)), total_notas)
        _checar("operações após reimportação", len(carregar_operacoes(conexao)), total_ops)

        _checar("operações sem data (parser)", int(carregar_operacoes(conexao)["data"].isna().sum()), 0)

        operacoes = carregar_operacoes(conexao)
        resultados = resultados_realizados(operacoes)
        _checar("resultados realizados gerados", len(resultados) > 0, True)
        _checar("nenhum resultado nulo", int(resultados["resultado"].isna().sum()), 0)

        conexao.close()          # libera o arquivo para o Windows remover a pasta


# ---------------------------------------------------------------------------
# 7. Futuros — ajuste do dia líquido das despesas
# ---------------------------------------------------------------------------

_REF_RESULTADOS = (Path(__file__).with_name("ref_exemplo")
                   / "network" / "api" / "0097_GET_api_results.json")


def teste_futuros_referencia(pdfs: list[Path]) -> None:
    """
    Confere os futuros de Set/2026 contra os dados de referência.

    Regra validada: o resultado do futuro é o **ajuste do dia menos as
    despesas da nota** (corretagem, emolumentos e I.S.S.). O "Total das
    despesas" impresso na nota BM&F deixa o I.S.S. de fora, por isso ele é
    somado em ``parser._extrair_despesas``.
    """
    print("\n7. Futuros: ajuste do dia líquido de despesas (Set/2026)")
    if not pdfs or not _REF_RESULTADOS.exists():
        print("  [-----] PDFs ou dados de referência ausentes — teste ignorado")
        return

    corpo = json.loads(_REF_RESULTADOS.read_text(encoding="utf-8"))
    referencias: dict[str, float] = {}
    for item in corpo["response"]["body"]["Results"]:
        if item["MonthYear"] == "set/2026":
            ticker = item["Ticker"]
            referencias[ticker] = referencias.get(ticker, 0.0) + float(item["TotalProfit"] or 0)

    with tempfile.TemporaryDirectory() as pasta:
        conexao = conectar(Path(pasta) / "futuros.db")
        for arquivo in pdfs:
            salvar_notas(conexao, extract_notas(str(arquivo), arquivo=arquivo.name))
        operacoes = carregar_operacoes(conexao)
        conexao.close()

    futuros = operacoes[operacoes["mercado"] == "FUTURO"]
    resultados = resultados_realizados(operacoes)
    conferidos = 0
    for ticker in sorted(futuros["ticker"].unique()):
        if ticker not in referencias:
            continue
        conferidos += 1
        obtido = float(resultados.loc[resultados["ticker"] == ticker, "resultado"].sum())
        _checar(f"{ticker} (Set/2026) líquido de despesas", round(obtido, 2),
                round(referencias[ticker], 2), tolerancia=0.05)

    _checar("tickers de futuro conferidos", conferidos > 0, True)


def teste_proventos() -> None:
    print("\n8. Proventos: importação do extrato e IRRF de JCP")
    with tempfile.TemporaryDirectory() as pasta:
        destino = Path(pasta)

        # CSV no layout de uma corretora: cabeçalhos por sinônimo, número no
        # padrão brasileiro e um rodapé de total, que deve ser descartado.
        csv = destino / "proventos.csv"
        csv.write_text(
            "Data;Ativo;Tipo de Evento;Quantidade;Valor Líquido\n"
            "15/09/2026;MXRF11;RENDIMENTO;100;1.234,56\n"
            "20/09/2026;PETR4;Juros sobre Capital Próprio;1000;1.000,00\n"
            "Total;;;1100;2.234,56\n",
            encoding="utf-8",
        )
        tabela, ignoradas = ler_planilha(csv)
        _checar("linhas válidas do CSV", len(tabela), 2)
        _checar("rodapé de total descartado", ignoradas, 1)
        _checar("data convertida para AAAA-MM-DD", tabela.loc[0, "data"], "2026-09-15")
        _checar("ticker em maiúsculas", tabela.loc[0, "ticker"], "MXRF11")
        _checar("número no padrão brasileiro", round(float(tabela.loc[0, "valor"]), 2), 1234.56)
        _checar("tipo reconhecido pelo sinônimo", tabela.loc[1, "tipo"], "JCP")

        # XLSX: outra extensão, outros rótulos de coluna e valor com "R$".
        xlsx = destino / "proventos.xlsx"
        pd.DataFrame({
            "Data do Pagamento": ["01/10/2026"],
            "Código": ["BBAS3"],
            "Tipo": ["Dividendo"],
            "Valor (R$)": ["R$ 500,00"],
        }).to_excel(xlsx, index=False)
        tabela_xlsx, _ = ler_planilha(xlsx)
        _checar("linhas válidas do XLSX", len(tabela_xlsx), 1)
        _checar("valor com símbolo de moeda", round(float(tabela_xlsx.loc[0, "valor"]), 2), 500.0)
        _checar("quantidade ausente vira zero", float(tabela_xlsx.loc[0, "quantidade"]), 0.0)

        # JCP: 15% retidos na fonte, com tributação exclusiva.
        _checar("IRRF de JCP (15% de 1.000)", irrf_jcp(1000.0), 150.0)
        _checar("IRRF de JCP sem valor", irrf_jcp(0.0), 0.0)

        # Deduplicação: reimportar o mesmo extrato não duplica.
        conexao = conectar(destino / "teste.db")
        try:
            _checar("proventos gravados",
                    salvar_proventos(conexao, tabela.to_dict("records")), 2)
            _checar("reimportação não duplica",
                    salvar_proventos(conexao, tabela.to_dict("records")), 0)
            _checar("proventos no banco", len(carregar_proventos(conexao)), 2)
        finally:
            conexao.close()


def teste_login() -> None:
    print("\n9. Login local: hash da senha e sessão")
    with tempfile.TemporaryDirectory() as pasta:
        conexao = conectar(Path(pasta) / "teste.db")
        try:
            _checar("sem usuário no início", tem_usuario(conexao), False)

            definir_senha(conexao, "investidor", "segredo123")
            _checar("usuário criado", tem_usuario(conexao), True)
            _checar("senha correta aceita",
                    verificar_senha(conexao, "investidor", "segredo123"), True)
            _checar("senha errada recusada",
                    verificar_senha(conexao, "investidor", "segredo124"), False)
            _checar("usuário errado recusado",
                    verificar_senha(conexao, "outro", "segredo123"), False)

            registro = conexao.execute(
                "SELECT hash FROM usuarios WHERE id = 1").fetchone()["hash"]
            _checar("senha não gravada em claro", "segredo123" in registro, False)
            _checar("hash reconhecido pelo formato",
                    registro.split("$")[0], "pbkdf2_sha256")

            mesmo = gerar_hash("segredo123", sal=b"0123456789abcdef")
            _checar("hash determinístico com o mesmo sal", mesmo,
                    gerar_hash("segredo123", sal=b"0123456789abcdef"))
            _checar("sal diferente gera hash diferente",
                    gerar_hash("segredo123", sal=b"0123456789abcdef")
                    != gerar_hash("segredo123", sal=b"fedcba9876543210"), True)

            definir_senha(conexao, "investidor", "novaSenha456")
            _checar("senha antiga invalidada",
                    verificar_senha(conexao, "investidor", "segredo123"), False)
            _checar("nova senha aceita",
                    verificar_senha(conexao, "investidor", "novaSenha456"), True)
        finally:
            conexao.close()


def main() -> int:
    print("=" * 78)
    print("VALIDAÇÃO DO MOTOR FISCAL — Gestor de Investimentos B3")
    print("=" * 78)

    teste_classificacao()
    teste_reconciliacao_referencia()
    teste_isencao()
    teste_compensacao()
    teste_irrf_compensacao()
    teste_proventos()
    teste_login()

    pdfs = sorted(Path(r"C:\Users\Esquilo\Downloads").glob("NotaCorretagem_01-09-26_30-09-26*.pdf"))
    teste_deduplicacao(pdfs)
    teste_futuros_referencia(pdfs)

    print("\n" + "=" * 78)
    if _falhas:
        print(f"RESULTADO: {len(_falhas)} verificação(ões) falharam")
        for falha in _falhas:
            print(f"  - {falha}")
        return 1
    print("RESULTADO: todas as verificações passaram")
    return 0


if __name__ == "__main__":
    sys.exit(main())
