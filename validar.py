"""
validar.py
----------
Verificação automática do motor fiscal (``regras.py``), da persistência
(``persistencia.py``), da importação de proventos (``proventos.py``), da
autenticação (``auth.py``), das regras SaaS (``saas.py``) e do monitor de
legislação (``monitor.py``).

Não depende de ``pytest`` — basta executar:

    python validar.py

Os valores esperados vêm dos dados de referência de Setembro/2026,
documentados em ``ANALISE_REFERENCIA.md``.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

import auth
import monitor
import persistencia as bd
import saas
from auth import gerar_hash
from parser import extract_notas
from persistencia import (
    carregar_monitor_legislacao,
    carregar_notas,
    carregar_operacoes,
    carregar_parametros_fiscais,
    carregar_proventos,
    conectar,
    gravar_monitor_legislacao,
    gravar_parametros_fiscais,
    salvar_notas,
    salvar_proventos,
)
from proventos import irrf_jcp, ler_planilha
from regras import (
    PARAMETROS_PADRAO,
    ROTULO_MERCADO,
    aliquota,
    aplicar_parametros,
    apurar_mensal,
    bucket_tributario,
    classificar_grupo,
    limite_isencao,
    resultados_realizados,
)

_falhas: list[str] = []


def _primeiro_usuario(conexao) -> int:
    """Id do usuário semeado automaticamente por :func:`conectar` (admin)."""
    return int(conexao.execute("SELECT MIN(id) FROM usuarios").fetchone()[0])



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
        dono = _primeiro_usuario(conexao)

        for arquivo in pdfs:
            salvar_notas(conexao, extract_notas(str(arquivo), arquivo=arquivo.name), dono)
        total_notas = len(carregar_notas(conexao, dono))
        total_ops = len(carregar_operacoes(conexao, dono))

        # reimporta tudo: nada deve ser somado de novo
        for arquivo in pdfs:
            salvar_notas(conexao, extract_notas(str(arquivo), arquivo=arquivo.name), dono)
        _checar("notas após reimportação", len(carregar_notas(conexao, dono)), total_notas)
        _checar("operações após reimportação", len(carregar_operacoes(conexao, dono)), total_ops)

        _checar("operações sem data (parser)",
                int(carregar_operacoes(conexao, dono)["data"].isna().sum()), 0)

        operacoes = carregar_operacoes(conexao, dono)
        resultados = resultados_realizados(operacoes)
        _checar("resultados realizados gerados", len(resultados) > 0, True)
        _checar("nenhum resultado nulo", int(resultados["resultado"].isna().sum()), 0)

        conexao.close()          # libera o arquivo para o Windows remover a pasta


# ---------------------------------------------------------------------------
# 7. Futuros — ajuste do dia líquido das despesas
# ---------------------------------------------------------------------------

_REF_RESULTADOS = (Path(__file__).with_name("ref_exemplo")
                   / "network" / "api" / "0097_GET_api_results.json")

# Pasta com as notas de corretagem reais. Fora do repositório: só serve para
# os testes de integração que dependem de PDFs (ignorados se ela não existir).
# Sobrescreva com a variável de ambiente ``NOTAS_DIR`` se as notas estiverem
# em outro lugar.
_NOTAS_DIR = Path(os.environ.get("NOTAS_DIR", Path.home() / "Downloads" / "Notas"))


def teste_futuros_referencia(pdfs: list[Path]) -> None:
    """
    Confere os futuros de Set/2026 contra os dados de referência.

    Regra validada: o resultado do futuro é o **ajuste do dia menos as
    despesas da nota** (corretagem, emolumentos e I.S.S.). O "Total das
    despesas" impresso na nota BM&F deixa o I.S.S. de fora, por isso ele é
    somado em ``parser._extrair_despesas``.

    O teste importa **todo** o histórico disponível (e depois filtra Set/2026):
    as posições de futuro atravessam o mês, então apurar setembro só com as
    notas de setembro distorce o resultado.
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
        dono = _primeiro_usuario(conexao)
        for arquivo in pdfs:
            salvar_notas(conexao, extract_notas(str(arquivo), arquivo=arquivo.name), dono)
        operacoes = carregar_operacoes(conexao, dono)
        conexao.close()

    resultados = resultados_realizados(operacoes)
    setembro = resultados[resultados["mes"] == "2026-09"]
    conferidos = 0
    for ticker in sorted(setembro["ticker"].unique()):
        if ticker not in referencias:
            continue
        conferidos += 1
        obtido = float(setembro.loc[setembro["ticker"] == ticker, "resultado"].sum())
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
        dono = _primeiro_usuario(conexao)
        try:
            _checar("proventos gravados",
                    salvar_proventos(conexao, dono, tabela.to_dict("records")), 2)
            _checar("reimportação não duplica",
                    salvar_proventos(conexao, dono, tabela.to_dict("records")), 0)
            _checar("proventos no banco", len(carregar_proventos(conexao, dono)), 2)
        finally:
            conexao.close()


def teste_login() -> None:
    print("\n9. Autenticação: cadastro, login, senha e recuperação")
    with tempfile.TemporaryDirectory() as pasta:
        conexao = conectar(Path(pasta) / "teste.db")
        try:
            administrador = conexao.execute(
                "SELECT usuario, hash FROM usuarios WHERE is_admin = 1").fetchone()
            if auth.ADMIN_PADRAO_USUARIO and auth.ADMIN_PADRAO_SENHA:
                _checar("admin dos segredos semeado", administrador["usuario"],
                        auth.ADMIN_PADRAO_USUARIO)
                _checar("senha não gravada em claro",
                        auth.ADMIN_PADRAO_SENHA in administrador["hash"], False)
                _checar("hash no formato PBKDF2", administrador["hash"].split("$")[0],
                        "pbkdf2_sha256")
                _checar("login do admin pelo usuário",
                        auth.autenticar(conexao, auth.ADMIN_PADRAO_USUARIO,
                                        auth.ADMIN_PADRAO_SENHA) is not None, True)
                _checar("login do admin pelo e-mail",
                        auth.autenticar(conexao, auth.ADMIN_PADRAO_EMAIL,
                                        auth.ADMIN_PADRAO_SENHA) is not None, True)
                _checar("senha errada recusada",
                        auth.autenticar(conexao, auth.ADMIN_PADRAO_USUARIO, "errada"), None)
            else:
                _checar("sem segredos, nenhum admin semeado", administrador, None)
                print("  [-----] segredos do admin ausentes — login do admin ignorado")

            _checar("validação recusa e-mail inválido",
                    auth.validar_cadastro("Maria Silva", "invalido", "12345678909",
                                          "segredo1", "segredo1"),
                    "Informe um e-mail válido.")
            _checar("validação recusa nome sem sobrenome",
                    auth.validar_cadastro("Maria", "m@x.com", "12345678909",
                                          "segredo1", "segredo1"),
                    "Informe o nome completo (nome e sobrenome).")
            _checar("validação recusa CPF inválido",
                    auth.validar_cadastro("Maria Silva", "m@x.com", "11111111111",
                                          "segredo1", "segredo1"),
                    "Informe um CPF válido (11 dígitos).")
            _checar("validação recusa senhas diferentes",
                    auth.validar_cadastro("Maria Silva", "m@x.com", "12345678909",
                                          "segredo1", "segredo2"),
                    "As senhas não conferem.")
            _checar("validação aceita cadastro válido",
                    auth.validar_cadastro("Maria Silva", "m@x.com", "12345678909",
                                          "segredo1", "segredo1"),
                    None)

            novo_id = auth.criar_conta(conexao, "Maria Silva", "maria@x.com",
                                       "12345678909", "segredo1", origem="Instagram")
            _checar("conta criada no plano gratuito",
                    bd.obter_usuario(conexao, novo_id)["plano_codigo"], "free")
            _checar("nome completo gravado",
                    bd.obter_usuario(conexao, novo_id)["nome"], "Maria Silva")
            _checar("origem gravada",
                    bd.obter_usuario(conexao, novo_id)["origem"], "Instagram")
            _checar("login pelo apelido derivado do e-mail",
                    auth.autenticar(conexao, "maria", "segredo1") is not None, True)
            _checar("login pelo e-mail",
                    auth.autenticar(conexao, "maria@x.com", "segredo1") is not None, True)
            _checar("login pelo CPF",
                    auth.autenticar(conexao, "123.456.789-09", "segredo1") is not None, True)

            try:
                auth.criar_conta(conexao, "Maria Silva", "maria@x.com",
                                 "11144477735", "segredo1")
                duplicou = True
            except ValueError:
                duplicou = False
            _checar("e-mail duplicado recusado", duplicou, False)

            try:
                auth.criar_conta(conexao, "Joana Souza", "joana@x.com",
                                 "12345678909", "segredo1")
                cpf_duplicado = True
            except ValueError:
                cpf_duplicado = False
            _checar("CPF duplicado recusado", cpf_duplicado, False)

            _checar("determinismo do hash com o mesmo sal",
                    gerar_hash("segredo1", sal=b"0123456789abcdef"),
                    gerar_hash("segredo1", sal=b"0123456789abcdef"))
            _checar("sais diferentes geram hashes diferentes",
                    gerar_hash("segredo1", sal=b"0123456789abcdef")
                    != gerar_hash("segredo1", sal=b"fedcba9876543210"), True)

            _checar("troca de senha com senha atual correta",
                    auth.alterar_senha(conexao, novo_id, "segredo1", "novaSenha456"), True)
            _checar("senha antiga invalidada",
                    auth.autenticar(conexao, "maria", "segredo1"), None)
            _checar("nova senha aceita",
                    auth.autenticar(conexao, "maria", "novaSenha456") is not None, True)
            _checar("troca com senha atual errada recusada",
                    auth.alterar_senha(conexao, novo_id, "errada", "outra123"), False)

            _checar("e-mail desconhecido não gera token",
                    auth.gerar_token_recuperacao(conexao, "ninguem@x.com"), None)
            token = auth.gerar_token_recuperacao(conexao, "maria@x.com")
            _checar("token de recuperação gerado", bool(token), True)
            _checar("token errado recusado",
                    auth.redefinir_senha(conexao, "maria@x.com", "000000", "zerada12"), False)
            _checar("redefinição com token válido",
                    auth.redefinir_senha(conexao, "maria@x.com", token, "final123"), True)
            _checar("senha redefinida aceita",
                    auth.autenticar(conexao, "maria", "final123") is not None, True)
        finally:
            conexao.close()


# ---------------------------------------------------------------------------
# 10. SaaS: planos, limites, cupons e checkout
# ---------------------------------------------------------------------------

def teste_saas() -> None:
    print("\n10. SaaS: planos, limites, cupons e checkout")
    with tempfile.TemporaryDirectory() as pasta:
        conexao = conectar(Path(pasta) / "teste.db")
        try:
            admin = _primeiro_usuario(conexao)
            _checar("admin semeado no plano PRO", saas.eh_pro(conexao, admin), True)
            _checar("PRO tem notas ilimitadas", saas.limite_notas(conexao, admin), -1)
            _checar("PRO exporta Excel", saas.pode_exportar_excel(conexao, admin), True)

            uid = auth.criar_conta(conexao, "Joao Pereira", "joao@x.com",
                                   "12345678909", "segredo1")
            _checar("free tem limite de 20 notas", saas.limite_notas(conexao, uid), 20)
            _checar("free pode importar até o limite",
                    saas.pode_importar(conexao, uid, 20)[0], True)
            _checar("free bloqueado acima do limite",
                    saas.pode_importar(conexao, uid, 21)[0], False)
            _checar("free não exporta Excel", saas.pode_exportar_excel(conexao, uid), False)

            bd.criar_cupom(conexao, "bemvindo10", 10.0)
            ok, cupom, _ = saas.validar_cupom(conexao, "BEMVINDO10")
            _checar("cupom válido reconhecido", ok, True)
            _checar("percentual do cupom", float(cupom["desconto_pct"]), 10.0)
            _checar("cupom inexistente recusado",
                    saas.validar_cupom(conexao, "NAOEXISTE")[0], False)

            bd.definir_cupom_ativo(conexao, int(cupom["id"]), False)
            _checar("cupom desativado recusado",
                    saas.validar_cupom(conexao, "BEMVINDO10")[0], False)
            bd.definir_cupom_ativo(conexao, int(cupom["id"]), True)

            pro = bd.obter_plano(conexao, "pro")
            valores = saas.calcular_preco(pro, cupom)
            _checar("preço cheio do PRO", valores["original"], 29.90)
            _checar("desconto de 10%", valores["desconto"], 2.99)
            _checar("preço final com cupom", valores["final"], 26.91)

            resultado = saas.assinar(conexao, uid, "pro", forma="Pix",
                                     codigo_cupom="BEMVINDO10")
            _checar("assinatura ativada", saas.eh_pro(conexao, uid), True)
            _checar("nota fiscal emitida", resultado["nota_fiscal"].startswith("NF-"), True)
            _checar("limite ilimitado após assinar", saas.limite_notas(conexao, uid), -1)
            _checar("uso do cupom registrado",
                    conexao.execute("SELECT usos FROM cupons WHERE codigo = 'BEMVINDO10'")
                    .fetchone()[0], 1)

            try:
                saas.assinar(conexao, uid, "free")
                recusou = False
            except ValueError:
                recusou = True
            _checar("checkout do plano gratuito recusado", recusou, True)

            bd.cancelar_assinatura(conexao, uid)
            _checar("cancelamento devolve ao gratuito", saas.eh_pro(conexao, uid), False)

            # Cupom de meses grátis do PRO
            bd.criar_cupom(conexao, "freepro3", tipo="meses", meses_gratis=3)
            ok_meses, cupom_meses, _ = saas.validar_cupom(conexao, "FREEPRO3")
            _checar("cupom de meses reconhecido", ok_meses, True)
            _checar("cupom de meses descrito",
                    saas.descrever_cupom(cupom_meses), "3 meses grátis")
            v_meses = saas.calcular_preco(pro, cupom_meses)
            _checar("cupom de meses zera o valor", v_meses["final"], 0.0)
            _checar("cupom de meses concede 3 meses", v_meses["meses"], 3)
            _checar("economia do cupom de meses", v_meses["desconto"], 89.70)

            bd.criar_cupom(conexao, "vazio", tipo="meses", meses_gratis=0)
            _checar("cupom de meses sem quantidade recusado",
                    saas.validar_cupom(conexao, "VAZIO")[0], False)

            # Parceiro e indicação
            parceiro_id = bd.criar_parceiro(
                conexao, "Ana Afiliada", "ANA10", comissao_pct=30.0,
                beneficio_tipo="meses", beneficio_valor=1)
            indicado = auth.criar_conta(
                conexao, "Pedro Lima", "pedro@x.com", "11144477735", "segredo1",
                origem="ANA10", parceiro_id=parceiro_id)
            beneficio = saas.beneficio_indicacao(conexao, indicado)
            _checar("benefício de indicação disponível", bool(beneficio), True)
            _checar("benefício do indicado é 1 mês grátis",
                    (beneficio["tipo"], beneficio["meses_gratis"]), ("meses", 1))
            _checar("checkout do indicado fica grátis",
                    saas.calcular_preco(pro, beneficio)["final"], 0.0)

            resultado_ind = saas.assinar(conexao, indicado, "pro")
            _checar("indicado virou PRO", saas.eh_pro(conexao, indicado), True)
            _checar("benefício usado uma única vez",
                    saas.beneficio_indicacao(conexao, indicado), None)
            _checar("origem do benefício registrada",
                    resultado_ind["origem_beneficio"], "indicacao")

            linha_parceiro = bd.listar_parceiros(conexao).iloc[0]
            _checar("parceiro com 1 indicado", int(linha_parceiro["indicados"]), 1)
            _checar("comissão de 30% calculada",
                    saas.comissao_parceiro(100.0, 30.0), 30.0)

            m = saas.metricas(conexao)
            _checar("métricas: total de usuários", m["usuarios_total"], 3)
            _checar("métricas: pagos/free",
                    (m["usuarios_pagos"], m["usuarios_free"]), (2, 1))
            _checar("faturamento contabilizado", round(m["faturamento"], 2), 26.91)
        finally:
            conexao.close()


# ---------------------------------------------------------------------------
# 11. Parâmetros fiscais editáveis e monitor de legislação
# ---------------------------------------------------------------------------

def teste_parametros_monitor() -> None:
    """
    Os parâmetros do motor (alíquotas, isenções, código do DARF) são editáveis
    no painel administrativo e ficam gravados no banco; o monitor guarda o
    hash das fontes oficiais para avisar quando o texto mudar.
    """
    print("\n11. Parâmetros fiscais editáveis e monitor de legislação")

    try:
        aplicar_parametros(PARAMETROS_PADRAO)
        _checar("alíquota de day trade padrão (20%)", aliquota("STOCK", True), 0.20)
        _checar("alíquota de swing trade padrão (15%)", aliquota("STOCK", False), 0.15)
        _checar("alíquota de FII padrão (20%)", aliquota("FII", False), 0.20)
        _checar("isenção de ações padrão (20.000)", limite_isencao("STOCK"), 20000.0)
        _checar("isenção de ativos EUA padrão (35.000)", limite_isencao("STOCK_USA"), 35000.0)
        _checar("ETF não tem isenção", limite_isencao("ETF"), 0.0)

        # Alíquota editada recai sobre a apuração.
        aplicar_parametros({"aliquota_swing_trade": "0.10"})
        _checar("alíquota editada reflete no motor", aliquota("STOCK", False), 0.10)
        tabela, _ = apurar_mensal(
            _frame_resultados([("OPTION", "Swing Trade", 1000.0, 50000.0)]), None, None)
        _checar("IR apurado com alíquota editada (10%)", tabela.iloc[0]["IRRFFinal"], 100.0)

        # Isenção editada recai sobre a apuração.
        aplicar_parametros({"isencao_acoes": "5000"})
        _checar("isenção editada reflete no motor", limite_isencao("STOCK"), 5000.0)
        fora, _ = apurar_mensal(
            _frame_resultados([("STOCK", "Swing Trade", 1000.0, 6000.0)]), None, None)
        _checar("vendas acima da isenção editada tributam", fora.iloc[0]["IRRFFinal"], 100.0)
        dentro, _ = apurar_mensal(
            _frame_resultados([("STOCK", "Swing Trade", 1000.0, 4000.0)]), None, None)
        _checar("vendas dentro da isenção editada são isentas",
                dentro.iloc[0]["IRRFFinal"], 0.0)

        # Parâmetro inválido é ignorado em vez de derrubar a apuração.
        aplicar_parametros({"aliquota_day_trade": "abc", "chave_inexistente": "1"})
        _checar("valor inválido ignorado", aliquota("STOCK", True), 0.20)
    finally:
        aplicar_parametros(PARAMETROS_PADRAO)
    _checar("motor restaurado aos padrões", aliquota("STOCK", False), 0.15)

    with tempfile.TemporaryDirectory() as pasta:
        conexao = conectar(Path(pasta) / "teste.db")
        try:
            _checar("parâmetros semeados no banco",
                    carregar_parametros_fiscais(conexao).get("codigo_receita_darf"), "6015")
            gravar_parametros_fiscais(conexao, {"aliquota_swing_trade": "0.10"})
            _checar("parâmetro gravado e relido",
                    carregar_parametros_fiscais(conexao)["aliquota_swing_trade"], "0.10")

            _checar("nenhuma verificação registrada ainda",
                    monitor.ultima_verificacao(conexao), None)
            gravar_monitor_legislacao(conexao, "http://fonte", "Fonte teste", "abc",
                                      mudou=True)
            registro = carregar_monitor_legislacao(conexao)["http://fonte"]
            _checar("fonte registrada com o hash", registro["hash"], "abc")
            _checar("mudança datada", bool(registro["mudou_em"]), True)
            _checar("última verificação devolvida",
                    monitor.ultima_verificacao(conexao) is not None, True)

            gravar_monitor_legislacao(conexao, "http://fonte", "Fonte teste", "def",
                                      mudou=False)
            registro = carregar_monitor_legislacao(conexao)["http://fonte"]
            _checar("hash atualizado", registro["hash"], "def")
            _checar("sem mudança preserva a data da última alteração",
                    bool(registro["mudou_em"]), True)
        finally:
            conexao.close()


def main() -> int:
    print("=" * 78)
    print("VALIDAÇÃO DO MOTOR FISCAL — FiscoTrade")
    print("=" * 78)

    teste_classificacao()
    teste_reconciliacao_referencia()
    teste_isencao()
    teste_compensacao()
    teste_irrf_compensacao()
    teste_proventos()
    teste_login()
    teste_saas()
    teste_parametros_monitor()

    pdfs = sorted(_NOTAS_DIR.glob("NotaCorretagem_01-09-26_30-09-26*.pdf"))
    teste_deduplicacao(pdfs)
    teste_futuros_referencia(sorted(_NOTAS_DIR.glob("*.pdf")))

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
