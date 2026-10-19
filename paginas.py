"""
paginas.py
----------
Conteúdo das páginas navegáveis do painel (``st.navigation``), mais as
utilidades e o carregamento dos dados compartilhados entre elas.

Cada ``pagina_*`` é uma função sem argumentos, registrada em ``app.py`` com
``st.Page``. O estado lido do banco fica nos módulos-globais preenchidos por
:func:`carregar`.

As regras fiscais estão em ``regras.py`` e a persistência em
``persistencia.py``.
"""

from __future__ import annotations

import calendar
import io
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

import auth
import saas
from parser import extract_notas
from persistencia import (
    adicionar_provento,
    assinatura_ativa,
    cancelar_assinatura,
    carregar_notas,
    carregar_operacoes,
    carregar_proventos,
    conectar,
    gravar_prejuizos,
    ler_prejuizos,
    limpar_dados,
    listar_notas_fiscais,
    listar_pagamentos,
    listar_planos,
    obter_plano,
    obter_usuario,
    remover_provento,
    resumo_importacao,
    salvar_notas,
    salvar_proventos,
)
from proventos import TIPOS, irrf_jcp, ler_planilha
from regras import (
    CODIGO_RECEITA_DARF,
    apurar_mensal,
    classificar_grupo,
    posicao_atual,
    resultados_realizados,
)


CORRETORAS = ["Genial", "XP", "Clear", "Genérico"]

#: Rótulos das colunas da página de proventos.
ROTULOS_PROVENTO = {
    "data": "Data", "ticker": "Ticker", "tipo": "Tipo",
    "quantidade": "Quantidade", "valor": "Valor", "irrf": "IRRF na fonte",
}

# Rótulos da tabela mensal de apuração
RESUMO_IR = {
    "mes": "Mês",
    "ResultsDayTrade": "Resultado Day Trade",
    "ResultsSwingTrade": "Resultado Swing Trade",
    "ResultsFII": "Resultado FII",
    "PreviousAcumulatedLossDayTrade": "Prejuízo anterior (DT)",
    "PreviousAcumulatedLossSwingTrade": "Prejuízo anterior (ST)",
    "BaseCalcDayTrade": "Base de cálculo (DT)",
    "BaseCalcSwingTrade": "Base de cálculo (ST)",
    "IRRFBase": "IR apurado",
    "IRRFMonthlyDayTrade": "IRRF retido (DT)",
    "IRRFPreviousDayTrade": "IRRF anterior (DT)",
    "IRRFUsedDayTrade": "IRRF compensado (DT)",
    "IRRFNextMonthDayTrade": "IRRF a transportar (DT)",
    "IRRFMonthlySwingTrade": "IRRF retido (ST)",
    "IRRFPreviousSwingTrade": "IRRF anterior (ST)",
    "IRRFUsedSwingTrade": "IRRF compensado (ST)",
    "IRRFNextMonthSwingTrade": "IRRF a transportar (ST)",
    "IRRFFinal": "IR a pagar",
    "ExemptionMessage": "Situação",
}

# Detalhamento por mercado (campos ``Results*`` do relatório)
DETALHE_MERCADO = [
    "ResultsStockSwingTrade", "ResultsStockDayTrade",
    "ResultsGoldSwingTrade", "ResultsGoldDayTrade",
    "ResultsOptionSwingTrade", "ResultsOptionDayTrade",
    "ResultsFutureIDXSwingTrade", "ResultsFutureIDXDayTrade",
    "ResultsFutureFeeSwingTrade", "ResultsFutureFeeDayTrade",
    "ResultsFutureUSDSwingTrade", "ResultsFutureUSDDayTrade",
    "ResultsFutureOtherSwingTrade", "ResultsFutureOtherDayTrade",
    "ResultsTermSwingTrade", "ResultsTermDayTrade",
]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

@st.cache_resource
def _conexao():
    """Conexão SQLite única por processo (o Streamlit reexecuta o script)."""
    return conectar()


def obter_conexao():
    """Conexão com o banco, compartilhada por todas as páginas do app."""
    return _conexao()


def _moeda(valor: float) -> str:
    """Formata um número no padrão brasileiro: R$ 1.234,56."""
    return f"R$ {float(valor or 0.0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _to_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")


def _to_excel(abas: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for nome, df in abas.items():
            conteudo = df if not df.empty else pd.DataFrame({"info": ["sem dados"]})
            conteudo.to_excel(writer, sheet_name=nome[:31], index=False)
    return buffer.getvalue()


def _vencimento_darf(mes: str) -> date:
    """DARF de renda variável vence no último dia útil do mês seguinte."""
    ano, numero_mes = (int(parte) for parte in mes.split("-"))
    numero_mes += 1
    if numero_mes > 12:
        numero_mes = 1
        ano += 1
    dia = date(ano, numero_mes, calendar.monthrange(ano, numero_mes)[1])
    while dia.weekday() >= 5:          # sábado = 5, domingo = 6
        dia -= timedelta(days=1)
    return dia


def _nome_mes(mes: str) -> str:
    """'2026-09' -> 'Setembro/2026'."""
    nomes = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
             "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    ano, numero_mes = (int(parte) for parte in mes.split("-"))
    return f"{nomes[numero_mes]}/{ano}"




# ---------------------------------------------------------------------------
# Estado compartilhado (preenchido por :func:`carregar`)
# ---------------------------------------------------------------------------

conexao = None
usuario_id = None
operacoes = None
notas = None
proventos = None
prejuizos = None
resultados = None
tabela_ir = None
saldos_finais = None
posicao = None
tem_dados = False


def carregar(identificador: int) -> None:
    """Lê o banco SQLite do usuário e recalcula os agregados das páginas."""
    global conexao, usuario_id, operacoes, notas, proventos, prejuizos
    global resultados, tabela_ir, saldos_finais, posicao, tem_dados

    usuario_id = int(identificador)
    conexao = _conexao()

    operacoes = carregar_operacoes(conexao, usuario_id)
    notas = carregar_notas(conexao, usuario_id)
    proventos = carregar_proventos(conexao, usuario_id)

    if not operacoes.empty:
        operacoes["data"] = pd.to_datetime(operacoes["data"], errors="coerce")
        operacoes["nota"] = operacoes["nota"].astype(str)
        operacoes["day_trade"] = operacoes["day_trade"].astype(bool)
        operacoes["grupo"] = [
            classificar_grupo(t, m)
            for t, m in zip(operacoes["ticker"], operacoes["mercado"])
        ]

    if not notas.empty:
        notas["data"] = pd.to_datetime(notas["data"], errors="coerce")

    prejuizos = ler_prejuizos(conexao, usuario_id)
    resultados = resultados_realizados(operacoes)
    tabela_ir, saldos_finais = apurar_mensal(resultados, notas, prejuizos)
    posicao = posicao_atual(operacoes)

    tem_dados = not operacoes.empty


# ---------------------------------------------------------------------------
# Página 1 — Upload
# ---------------------------------------------------------------------------

def pagina_upload() -> None:
    st.subheader("Enviar notas de corretagem")

    if saas.limite_notas(conexao, usuario_id) >= 0:
        st.caption(
            f"Plano **{saas.rotulo_plano(conexao, usuario_id)}** — limite de "
            f"{saas.limite_notas(conexao, usuario_id)} notas importadas."
        )

    col1, col2 = st.columns([1, 2])
    with col1:
        corretora = st.selectbox("Corretora", CORRETORAS, index=0)
    with col2:
        arquivos = st.file_uploader(
            "Selecione um ou mais arquivos PDF",
            type=["pdf"],
            accept_multiple_files=True,
        )

    if st.button("Processar notas", type="primary", disabled=not arquivos):
        notas_novas = operacoes_novas = arquivos_novos = 0
        for arquivo in arquivos:
            try:
                lidas = extract_notas(arquivo, corretora=corretora, arquivo=arquivo.name)
            except Exception as erro:  # noqa: BLE001
                st.error(f"Falha ao ler {arquivo.name}: {erro}")
                continue

            if not lidas:
                st.warning(f"Nenhuma operação reconhecida em {arquivo.name}.")
                continue

            permitido, aviso = saas.pode_importar(conexao, usuario_id, len(lidas))
            if not permitido:
                st.error(aviso)
                break

            novas, ops = salvar_notas(conexao, lidas, usuario_id)
            notas_novas += novas
            operacoes_novas += ops
            arquivos_novos += 1

            if novas:
                st.success(f"{arquivo.name}: {novas} nota(s) e {ops} operação(ões) importada(s).")
            else:
                st.info(f"{arquivo.name}: notas já importadas anteriormente (nada duplicado).")

        if arquivos_novos:
            st.rerun()

    st.divider()

    contagem = resumo_importacao(conexao, usuario_id)
    m1, m2, m3 = st.columns(3)
    m1.metric("Notas importadas", contagem["notas"])
    m2.metric("Operações", contagem["operacoes"])
    m3.metric("Arquivos processados", contagem["arquivos"])

    if st.button("🗑️ Limpar operações importadas"):
        limpar_dados(conexao, usuario_id)
        st.rerun()

    if notas.empty:
        st.info("Nenhuma nota importada ainda. Envie um PDF para começar.")
    else:
        st.markdown("**Notas importadas**")
        visao_notas = notas.copy()
        visao_notas["data"] = visao_notas["data"].dt.strftime("%d/%m/%Y")
        visao_notas.columns = ["Nota", "Corretora", "Data", "Arquivo",
                              "Despesas", "IRRF", "Categoria IRRF"]
        st.dataframe(visao_notas, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Página 2 — Visão Geral
# ---------------------------------------------------------------------------

def pagina_visao() -> None:
    st.subheader("Visão geral")

    if not tem_dados:
        st.info("Sem dados. Importe notas na página **Upload de Notas**.")
    else:
        custo_total = float(posicao["Custo Total"].sum()) if not posicao.empty else 0.0
        ir_total = float(tabela_ir["IRRFFinal"].sum()) if not tabela_ir.empty else 0.0
        total_proventos = float(proventos["valor"].sum()) if not proventos.empty else 0.0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Patrimônio (custo)", _moeda(custo_total))
        c2.metric("Ativos em carteira", len(posicao))
        c3.metric("IR apurado no período", _moeda(ir_total))
        c4.metric("Proventos recebidos", _moeda(total_proventos))

        st.divider()
        st.markdown("**Resultado realizado por mês**")
        if resultados.empty:
            st.info("Nenhum resultado realizado no período.")
        else:
            por_mes = resultados.pivot_table(
                index="mes", columns="categoria", values="resultado",
                aggfunc="sum", fill_value=0.0,
            )
            st.bar_chart(por_mes)

        st.markdown("**Últimos negócios**")
        ultimos = operacoes.sort_values("data", ascending=False).head(15)
        st.dataframe(
            ultimos[["data", "ticker", "tipo", "quantidade", "preco", "mercado", "nota"]],
            width="stretch", hide_index=True,
        )


# ---------------------------------------------------------------------------
# Página 3 — Extrato
# ---------------------------------------------------------------------------

def pagina_extrato() -> None:
    st.subheader("Extrato de operações")

    if not tem_dados:
        st.info("Sem operações. Importe notas na página **Upload de Notas**.")
    else:
        col1, col2, col3 = st.columns(3)
        with col1:
            periodo = st.date_input(
                "Período",
                value=(operacoes["data"].min().date(), operacoes["data"].max().date()),
            )
        with col2:
            tickers = st.multiselect(
                "Tickers", sorted(operacoes["ticker"].unique()),
            )
        with col3:
            mercados = st.multiselect(
                "Mercados", sorted(operacoes["mercado"].dropna().unique()),
            )

        filtro = operacoes.copy()
        if isinstance(periodo, tuple) and len(periodo) == 2:
            inicio, fim = periodo
            filtro = filtro[
                (filtro["data"].dt.date >= inicio) & (filtro["data"].dt.date <= fim)
            ]
        if tickers:
            filtro = filtro[filtro["ticker"].isin(tickers)]
        if mercados:
            filtro = filtro[filtro["mercado"].isin(mercados)]

        e1, e2, e3 = st.columns(3)
        e1.metric("Operações", len(filtro))
        e2.metric("Compras", _moeda(filtro.loc[filtro["tipo"] == "C", "valor_total"].sum()))
        e3.metric("Vendas", _moeda(filtro.loc[filtro["tipo"] == "V", "valor_total"].sum()))

        colunas = ["data", "tipo", "ticker", "grupo", "mercado", "quantidade",
                   "preco", "valor_total", "taxas", "resultado", "nota", "corretora"]
        st.dataframe(filtro[colunas], width="stretch", hide_index=True)

        st.download_button(
            "⬇️ Baixar extrato filtrado (CSV)",
            data=_to_csv(filtro[colunas]),
            file_name=f"extrato_{date.today():%Y%m%d}.csv",
            mime="text/csv",
        )


# ---------------------------------------------------------------------------
# Página 4 — Meu Patrimônio
# ---------------------------------------------------------------------------

def pagina_patrimonio() -> None:
    st.subheader("Posição em custódia")

    if posicao.empty:
        st.info("Sem posição calculada. Importe notas na página **Upload de Notas**.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Ativos em carteira", len(posicao))
        c2.metric("Custo total", _moeda(posicao["Custo Total"].sum()))
        c3.metric("Grupos distintos", posicao["Grupo"].nunique())

        st.dataframe(posicao, width="stretch", hide_index=True)

        st.markdown("**Custo por grupo de ativos**")
        st.bar_chart(posicao.groupby("Grupo")["Custo Total"].sum())

        st.caption(
            "Preço médio ponderado com as taxas de corretagem somadas ao custo "
            "(item 3 do checklist de reconstrução)."
        )


# ---------------------------------------------------------------------------
# Página 5 — Apuração de IR
# ---------------------------------------------------------------------------

def pagina_ir() -> None:
    st.subheader("Apuração de Imposto de Renda")

    with st.expander("⚙️ Saldos iniciais a compensar", expanded=False):
        st.caption(
            "Informe o saldo acumulado de prejuízo (valores negativos) e o IRRF "
            "retido em meses anteriores que ainda não foi compensado. É o ponto "
            "de partida da apuração: daí em diante o prejuízo e o IRRF são "
            "transportados mês a mês automaticamente."
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            prej_day = st.number_input("Prejuízo Day Trade", value=float(prejuizos["DayTrade"]),
                                       step=100.0, format="%.2f")
        with col2:
            prej_swing = st.number_input("Prejuízo Swing Trade", value=float(prejuizos["SwingTrade"]),
                                         step=100.0, format="%.2f")
        with col3:
            prej_fii = st.number_input("Prejuízo FII", value=float(prejuizos["FII"]),
                                       step=100.0, format="%.2f")

        col4, col5 = st.columns(2)
        with col4:
            irrf_day = st.number_input("IRRF a compensar — Day Trade",
                                       value=float(prejuizos.get("ir_day") or 0.0),
                                       step=10.0, format="%.2f")
        with col5:
            irrf_swing = st.number_input("IRRF a compensar — Swing Trade",
                                         value=float(prejuizos.get("ir_swing") or 0.0),
                                         step=10.0, format="%.2f")

        if st.button("Salvar saldos"):
            gravar_prejuizos(conexao, usuario_id, {
                "data": prejuizos.get("data"),
                "DayTrade": prej_day,
                "SwingTrade": prej_swing,
                "FII": prej_fii,
                "ir_day": irrf_day,
                "ir_swing": irrf_swing,
            })
            st.success("Saldos atualizados.")
            st.rerun()

        st.caption(
            "Transporte para o mês seguinte (calculado): "
            f"prejuízo DT {_moeda(saldos_finais.get('DayTrade', 0.0))} · "
            f"prejuízo ST {_moeda(saldos_finais.get('SwingTrade', 0.0))} · "
            f"prejuízo FII {_moeda(saldos_finais.get('FII', 0.0))} · "
            f"IRRF DT {_moeda(saldos_finais.get('ir_day', 0.0))} · "
            f"IRRF ST {_moeda(saldos_finais.get('ir_swing', 0.0))}"
        )

    if tabela_ir.empty:
        st.info("Nenhuma operação com resultado realizada. A apuração aparece após importar notas.")
    else:
        ir_total = float(tabela_ir["IRRFFinal"].sum())
        irrf_total = float(
            tabela_ir["IRRFMonthlyDayTrade"].sum() + tabela_ir["IRRFMonthlySwingTrade"].sum()
        )
        a1, a2, a3 = st.columns(3)
        a1.metric("IR apurado", _moeda(tabela_ir["IRRFBase"].sum()))
        a2.metric("IRRF retido", _moeda(irrf_total))
        a3.metric("IR a pagar", _moeda(ir_total))

        visao = tabela_ir[list(RESUMO_IR)].rename(columns=RESUMO_IR).copy()
        visao["Mês"] = visao["Mês"].map(_nome_mes)
        st.dataframe(visao, width="stretch", hide_index=True)

        st.markdown("**Resultados por mercado (campos `Results*`)**")
        detalhe = tabela_ir[tabela_ir["mes"].isin(
            [m for m in tabela_ir["mes"] if any(tabela_ir.loc[tabela_ir["mes"] == m, c].iloc[0]
                                                for c in DETALHE_MERCADO)]
        )]
        if detalhe.empty:
            st.caption("Sem resultados por mercado no período.")
        else:
            st.dataframe(
                detalhe[["mes"] + DETALHE_MERCADO],
                width="stretch", hide_index=True,
            )

        st.caption(
            "Day Trade: 20% sem isenção. Swing Trade: 15% (FII/FIAGRO: 20%), com "
            "isenção quando as vendas do grupo no mês ficam dentro do limite de "
            "R$ 20.000,00 (ações/BDR/ouro) ou R$ 35.000,00 (ativos dos EUA). "
            "Prejuízos e IRRF retido são compensados por categoria, mês a mês — "
            "o que não for usado fica acumulado para as competências seguintes."
        )


# ---------------------------------------------------------------------------
# Página 6 — DARF
# ---------------------------------------------------------------------------

def pagina_darf() -> None:
    st.subheader("DARF — ganhos líquidos em renda variável")

    if tabela_ir.empty:
        st.info("Sem competências apuradas. Importe notas na página **Upload de Notas**.")
    else:
        competencias = list(tabela_ir["mes"])
        competencia = st.selectbox(
            "Competência", competencias,
            index=len(competencias) - 1,
            format_func=_nome_mes,
        )
        linha = tabela_ir[tabela_ir["mes"] == competencia].iloc[0]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Base de cálculo", _moeda(linha["BaseCalcSwingTrade"] + linha["BaseCalcDayTrade"]))
        c2.metric("IR apurado", _moeda(linha["IRRFBase"]))
        c3.metric("IRRF retido", _moeda(
            linha["IRRFMonthlyDayTrade"] + linha["IRRFMonthlySwingTrade"]))
        c4.metric("Valor a recolher", _moeda(linha["DARFFinal"]))

        if float(linha["DARFFinal"]) <= 0:
            st.success(f"{_nome_mes(competencia)}: {linha['ExemptionMessage']}.")
        else:
            st.warning(
                f"**{_nome_mes(competencia)}** — recolher {_moeda(linha['DARFFinal'])} "
                f"até {_vencimento_darf(competencia):%d/%m/%Y}."
            )

        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Dados para emissão no Sicalc / internet banking**")
            st.code(
                f"Código de receita: {CODIGO_RECEITA_DARF}\n"
                f"Período de apuração: {competencia}\n"
                f"Vencimento: {_vencimento_darf(competencia):%d/%m/%Y}\n"
                f"Valor: {_moeda(linha['DARFFinal'])}",
                language="text",
            )
        with col2:
            st.markdown("**Composição**")
            composicao = pd.DataFrame([
                {"Item": "Base de cálculo Day Trade", "Valor": linha["BaseCalcDayTrade"]},
                {"Item": "Base de cálculo Swing Trade", "Valor": linha["BaseCalcSwingTrade"]},
                {"Item": "Base de cálculo FII", "Valor": linha["BaseCalcFII"]},
                {"Item": "IR apurado", "Valor": linha["IRRFBase"]},
                {"Item": "(-) IRRF retido", "Valor": -(
                    linha["IRRFMonthlyDayTrade"] + linha["IRRFMonthlySwingTrade"])},
                {"Item": "IR a recolher", "Valor": linha["DARFFinal"]},
            ])
            st.dataframe(composicao, width="stretch", hide_index=True)

        st.download_button(
            "⬇️ Baixar apuração do período (CSV)",
            data=_to_csv(tabela_ir),
            file_name=f"apuracao_{date.today():%Y%m%d}.csv",
            mime="text/csv",
        )
        st.caption(
            f"Código de receita {CODIGO_RECEITA_DARF} — ganhos líquidos em operações "
            "realizadas em bolsas de valores, de mercadorias, de futuros e "
            "assemelhadas (pessoa física)."
        )


# ---------------------------------------------------------------------------
# Página 7 — Proventos
# ---------------------------------------------------------------------------

def pagina_proventos() -> None:
    st.subheader("Proventos recebidos")

    # -- Importação do extrato ---------------------------------------------
    with st.expander("Importar extrato de proventos (CSV ou XLSX)",
                     expanded=proventos.empty):
        st.caption(
            "As notas de corretagem não trazem proventos. Baixe o extrato de "
            "proventos na corretora ou na Área do Investidor da B3 e carregue aqui: "
            "as colunas de data, ativo, tipo, quantidade e valor são identificadas "
            "automaticamente, e reimportar o mesmo extrato não duplica os lançamentos."
        )
        arquivo = st.file_uploader("Extrato de proventos", type=["csv", "xlsx", "xls"],
                                   key="arquivo_proventos")
        if arquivo is not None:
            try:
                tabela, ignoradas = ler_planilha(arquivo)
            except Exception as erro:  # noqa: BLE001
                st.error(f"Falha ao ler {arquivo.name}: {erro}")
            else:
                if tabela.empty:
                    st.warning("Nenhum provento válido encontrado no arquivo.")
                else:
                    st.dataframe(tabela.rename(columns=ROTULOS_PROVENTO),
                                 width="stretch", hide_index=True)
                    if ignoradas:
                        st.caption(f"{ignoradas} linha(s) ignorada(s) por falta de "
                                   "ticker ou de data reconhecível.")
                    if st.button(f"Importar {len(tabela)} provento(s)", type="primary"):
                        novas = salvar_proventos(conexao, usuario_id, tabela.to_dict("records"))
                        st.session_state["proventos_importados"] = (novas, len(tabela) - novas)
                        st.rerun()

    if st.session_state.get("proventos_importados"):
        novas, repetidas = st.session_state.pop("proventos_importados")
        aviso = f"{novas} provento(s) importado(s)."
        if repetidas:
            aviso += f" {repetidas} já constavam no banco e foram ignorados."
        st.success(aviso)

    # -- Lançamento manual -------------------------------------------------
    with st.form("form_provento", clear_on_submit=True):
        col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 1])
        with col1:
            data_provento = st.date_input("Data", value=date.today())
        with col2:
            ticker_provento = st.text_input("Ticker", placeholder="MXRF11")
        with col3:
            tipo_provento = st.selectbox("Tipo", TIPOS)
        with col4:
            quantidade_provento = st.number_input("Quantidade", value=0.0, step=1.0)
        with col5:
            valor_provento = st.number_input("Valor (R$)", value=0.0, step=0.01, format="%.2f")

        if st.form_submit_button("Adicionar provento", type="primary"):
            if not ticker_provento.strip():
                st.error("Informe o ticker do provento.")
            else:
                adicionar_provento(conexao, usuario_id, data_provento.isoformat(),
                                   ticker_provento.strip(), tipo_provento,
                                   quantidade_provento, valor_provento)
                st.rerun()

    if proventos.empty:
        st.info("Nenhum provento registrado ainda.")
        return

    # -- Resumo ------------------------------------------------------------
    detalhe = proventos.assign(irrf=[
        irrf_jcp(valor) if tipo == "JCP" else 0.0
        for tipo, valor in zip(proventos["tipo"], proventos["valor"])
    ])
    irrf_total_jcp = detalhe["irrf"].sum()

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Total recebido", _moeda(proventos["valor"].sum()))
    p2.metric("Lançamentos", len(proventos))
    p3.metric("Ativos distintos", proventos["ticker"].nunique())
    p4.metric("IRRF de JCP (15%)", _moeda(irrf_total_jcp))
    st.caption(
        "O IRRF do JCP é retido na fonte com tributação **exclusiva**: é definitivo "
        "e não entra no DARF 6015 do IR mensal da renda variável — serve para "
        "informar o rendimento na declaração anual. O cálculo considera o valor "
        "lançado como bruto; se o extrato trouxer o valor já líquido, informe o bruto."
    )

    st.markdown("**Por tipo de provento**")
    por_tipo = proventos.groupby("tipo")["valor"].agg(
        Lancamentos="count", Valor="sum"
    ).reset_index()
    por_tipo["irrf"] = [
        irrf_jcp(valor) if tipo == "JCP" else 0.0
        for tipo, valor in zip(por_tipo["tipo"], por_tipo["Valor"])
    ]
    st.dataframe(por_tipo.rename(columns=ROTULOS_PROVENTO), width="stretch", hide_index=True)

    st.markdown("**Proventos por mês**")
    por_mes_prov = proventos.copy()
    por_mes_prov["mes"] = pd.to_datetime(por_mes_prov["data"]).dt.strftime("%Y-%m")
    st.bar_chart(por_mes_prov.groupby("mes")["valor"].sum())

    st.markdown("**Detalhamento**")
    st.dataframe(detalhe.drop(columns=["id"]).rename(columns=ROTULOS_PROVENTO),
                 width="stretch", hide_index=True)

    remover = st.selectbox(
        "Remover lançamento",
        options=list(proventos["id"]),
        format_func=lambda i: (
            f"{proventos.loc[proventos['id'] == i, 'data'].iloc[0]} — "
            f"{proventos.loc[proventos['id'] == i, 'ticker'].iloc[0]} — "
            f"{_moeda(proventos.loc[proventos['id'] == i, 'valor'].iloc[0])}"
        ),
    )
    if st.button("Remover selecionado"):
        remover_provento(conexao, usuario_id, remover)
        st.rerun()


# ---------------------------------------------------------------------------
# Página 8 — Relatórios
# ---------------------------------------------------------------------------

def pagina_relatorios() -> None:
    st.subheader("Exportar dados")

    if not tem_dados:
        st.info("Nada para exportar ainda.")
    else:
        colunas_extrato = ["data", "tipo", "ticker", "grupo", "mercado", "quantidade",
                           "preco", "valor_total", "taxas", "resultado", "nota", "corretora"]

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "⬇️ Operações (CSV)",
                data=_to_csv(operacoes[colunas_extrato]),
                file_name=f"operacoes_{date.today():%Y%m%d}.csv",
                mime="text/csv",
                width="stretch",
            )
        with col2:
            if saas.pode_exportar_excel(conexao, usuario_id):
                st.download_button(
                    "⬇️ Consolidado (Excel)",
                    data=_to_excel({
                        "operacoes": operacoes[colunas_extrato],
                        "posicao": posicao,
                        "apuracao_ir": tabela_ir,
                        "resultados": resultados,
                        "notas": notas,
                        "proventos": proventos,
                    }),
                    file_name=f"relatorio_{date.today():%Y%m%d}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                )
            else:
                st.info(
                    "A exportação consolidada em **Excel** faz parte do plano "
                    "PRO. Assine em **Planos e Assinatura** para liberar."
                )

        st.divider()
        st.markdown("**Prévia — Apuração de IR**")
        if tabela_ir.empty:
            st.caption("Sem apuração no período.")
        else:
            st.dataframe(tabela_ir, width="stretch", hide_index=True)

        st.markdown("**Prévia — Operações**")
        st.dataframe(operacoes[colunas_extrato], width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Página 9 — Planos e Assinatura (checkout)
# ---------------------------------------------------------------------------

def pagina_planos() -> None:
    st.subheader("\U0001F4B3 Planos e assinatura")

    if saas.eh_pro(conexao, usuario_id):
        st.success(f"Você é assinante do plano **{saas.rotulo_plano(conexao, usuario_id)}**.")
    else:
        st.info(f"Você está no plano **{saas.rotulo_plano(conexao, usuario_id)}**.")

    st.markdown("**Planos disponíveis**")
    planos = listar_planos(conexao)
    if planos.empty:
        st.warning("Nenhum plano configurado.")
        return

    colunas = st.columns(len(planos))
    for coluna, (_, plano) in zip(colunas, planos.iterrows()):
        with coluna:
            st.markdown(f"#### {plano['nome']}")
            preco = ("Grátis" if float(plano["preco_mensal"]) <= 0
                     else f"{_moeda(plano['preco_mensal'])}/mês")
            st.metric("Mensalidade", preco)
            limite = ("ilimitadas" if int(plano["limite_notas"]) < 0
                      else str(int(plano["limite_notas"])))
            st.caption(f"Notas: **{limite}**")
            st.caption("Exportação em Excel: "
                       + ("**sim**" if plano["exporta_excel"] else "não"))
            if plano["descricao"]:
                st.caption(plano["descricao"])

    st.divider()

    pro = obter_plano(conexao, "pro")
    if pro is None:
        st.warning("Plano PRO não configurado.")
    elif not saas.eh_pro(conexao, usuario_id):
        st.markdown("**Assinar o PRO**")
        st.caption("Checkout **simulado** — nenhuma cobrança real é efetuada.")
        col1, col2, col3 = st.columns(3)
        with col1:
            forma = st.selectbox("Forma de pagamento", saas.FORMAS_PAGAMENTO,
                                 key="ck_forma")
        with col2:
            meses = st.number_input("Meses", min_value=1, max_value=24, value=1,
                                    step=1, key="ck_meses")
        with col3:
            codigo_cupom = st.text_input("Cupom de desconto (opcional)",
                                         key="ck_cupom").strip().upper()

        cupom = None
        if codigo_cupom:
            ok, cupom, mensagem = saas.validar_cupom(conexao, codigo_cupom)
            (st.success if ok else st.error)(mensagem)

        valores = saas.calcular_preco(pro, cupom)
        total = valores["final"] * int(meses)
        st.caption(
            f"Plano {_moeda(valores['original'])}/mês · desconto "
            f"{valores['percentual']:.0f}% ({_moeda(valores['desconto'])}) · "
            f"por mês **{_moeda(valores['final'])}** · total ({int(meses)} mês(es)) "
            f"**{_moeda(total)}**"
        )

        if st.button("Confirmar assinatura", type="primary"):
            try:
                resultado = saas.assinar(conexao, usuario_id, "pro", forma=forma,
                                         codigo_cupom=codigo_cupom or None,
                                         meses=int(meses))
            except ValueError as erro:
                st.error(str(erro))
            else:
                st.success(
                    f"Assinatura confirmada! Plano **{resultado['plano']}**, "
                    f"valor {_moeda(resultado['final'])}, forma {resultado['forma']}, "
                    f"nota fiscal **{resultado['nota_fiscal']}**. "
                    f"Referência do pagamento: {resultado['referencia']}."
                )
                st.rerun()

    assinatura = assinatura_ativa(conexao, usuario_id)
    if assinatura is not None:
        st.divider()
        st.markdown("**Assinatura vigente**")
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Plano", assinatura["plano_nome"] or assinatura["plano_codigo"])
        a2.metric("Início", assinatura["inicio"])
        a3.metric("Renova até", assinatura["fim"])
        a4.metric("Valor", _moeda(assinatura["valor_pago"]))
        if st.button("Cancelar assinatura"):
            cancelar_assinatura(conexao, usuario_id)
            st.success("Assinatura cancelada. Você voltou ao plano Gratuito.")
            st.rerun()

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Meus pagamentos**")
        pagamentos = listar_pagamentos(conexao, usuario_id)
        if pagamentos.empty:
            st.caption("Nenhum pagamento registrado.")
        else:
            st.dataframe(pagamentos, width="stretch", hide_index=True)
    with col2:
        st.markdown("**Minhas notas fiscais**")
        notas_fiscais = listar_notas_fiscais(conexao, usuario_id)
        if notas_fiscais.empty:
            st.caption("Nenhuma nota fiscal emitida.")
        else:
            st.dataframe(notas_fiscais, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Página 10 — Minha Conta
# ---------------------------------------------------------------------------

def pagina_conta() -> None:
    st.subheader("\U0001F464 Minha conta")

    usuario = obter_usuario(conexao, usuario_id)
    if usuario is None:
        st.error("Conta não encontrada.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Usuário", usuario["usuario"])
    c2.metric("Plano", saas.rotulo_plano(conexao, usuario_id))
    c3.metric("Perfil", "Administrador" if usuario["is_admin"] else "Investidor")
    st.caption(f"E-mail: {usuario['email']} · Cadastro em {(usuario['criado_em'] or '')[:10]}")

    st.divider()
    st.markdown("**Alterar senha**")
    with st.form("form_alterar_senha"):
        senha_atual = st.text_input("Senha atual", type="password", key="ct_atual")
        nova = st.text_input("Nova senha", type="password", key="ct_nova")
        confirmacao = st.text_input("Confirme a nova senha", type="password",
                                    key="ct_confirmacao")
        if st.form_submit_button("Alterar senha", type="primary"):
            if len(nova) < auth.TAMANHO_MINIMO:
                st.error(f"A senha deve ter ao menos {auth.TAMANHO_MINIMO} caracteres.")
            elif nova != confirmacao:
                st.error("As senhas não conferem.")
            elif auth.alterar_senha(conexao, usuario_id, senha_atual, nova):
                st.success("Senha alterada com sucesso.")
            else:
                st.error("Senha atual incorreta.")
