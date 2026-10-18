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

from parser import extract_notas
from persistencia import (
    adicionar_provento,
    carregar_notas,
    carregar_operacoes,
    carregar_proventos,
    conectar,
    gravar_prejuizos,
    ler_prejuizos,
    limpar_dados,
    remover_provento,
    resumo_importacao,
    salvar_notas,
)
from regras import (
    CODIGO_RECEITA_DARF,
    apurar_mensal,
    classificar_grupo,
    posicao_atual,
    resultados_realizados,
)


CORRETORAS = ["Genial", "XP", "Clear", "Genérico"]

TIPOS_PROVENTO = ["Dividendo", "JCP", "Rendimento", "Amortização", "Bonificação"]

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
operacoes = None
notas = None
proventos = None
prejuizos = None
resultados = None
tabela_ir = None
saldos_finais = None
posicao = None
tem_dados = False


def carregar() -> None:
    """Lê o banco SQLite e recalcula os agregados usados por todas as páginas."""
    global conexao, operacoes, notas, proventos, prejuizos
    global resultados, tabela_ir, saldos_finais, posicao, tem_dados

    conexao = _conexao()

    operacoes = carregar_operacoes(conexao)
    notas = carregar_notas(conexao)
    proventos = carregar_proventos(conexao)

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

    prejuizos = ler_prejuizos(conexao)
    resultados = resultados_realizados(operacoes)
    tabela_ir, saldos_finais = apurar_mensal(resultados, notas, prejuizos)
    posicao = posicao_atual(operacoes)

    tem_dados = not operacoes.empty


# ---------------------------------------------------------------------------
# Página 1 — Upload
# ---------------------------------------------------------------------------

def pagina_upload() -> None:
    st.subheader("Enviar notas de corretagem")

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

            novas, ops = salvar_notas(conexao, lidas)
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

    contagem = resumo_importacao(conexao)
    m1, m2, m3 = st.columns(3)
    m1.metric("Notas importadas", contagem["notas"])
    m2.metric("Operações", contagem["operacoes"])
    m3.metric("Arquivos processados", contagem["arquivos"])

    if st.button("🗑️ Limpar operações importadas"):
        limpar_dados(conexao)
        st.rerun()

    if notas.empty:
        st.info("Nenhuma nota importada ainda. Envie um PDF para começar.")
    else:
        st.markdown("**Notas importadas**")
        visao_notas = notas.copy()
        visao_notas["data"] = visao_notas["data"].dt.strftime("%d/%m/%Y")
        visao_notas.columns = ["Nota", "Corretora", "Data", "Arquivo",
                              "Despesas", "IRRF", "Categoria IRRF"]
        st.dataframe(visao_notas, use_container_width=True, hide_index=True)


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
            use_container_width=True, hide_index=True,
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
        st.dataframe(filtro[colunas], use_container_width=True, hide_index=True)

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

        st.dataframe(posicao, use_container_width=True, hide_index=True)

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
            gravar_prejuizos(conexao, {
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
        st.dataframe(visao, use_container_width=True, hide_index=True)

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
                use_container_width=True, hide_index=True,
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
            st.dataframe(composicao, use_container_width=True, hide_index=True)

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

    with st.form("form_provento", clear_on_submit=True):
        col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 1])
        with col1:
            data_provento = st.date_input("Data", value=date.today())
        with col2:
            ticker_provento = st.text_input("Ticker", placeholder="MXRF11")
        with col3:
            tipo_provento = st.selectbox("Tipo", TIPOS_PROVENTO)
        with col4:
            quantidade_provento = st.number_input("Quantidade", value=0.0, step=1.0)
        with col5:
            valor_provento = st.number_input("Valor (R$)", value=0.0, step=0.01, format="%.2f")

        if st.form_submit_button("Adicionar provento", type="primary"):
            if not ticker_provento.strip():
                st.error("Informe o ticker do provento.")
            else:
                adicionar_provento(conexao, data_provento.isoformat(),
                                   ticker_provento.strip(), tipo_provento,
                                   quantidade_provento, valor_provento)
                st.rerun()

    if proventos.empty:
        st.info(
            "Nenhum provento registrado. As notas de corretagem não trazem "
            "proventos — informe-os manualmente acima."
        )
    else:
        p1, p2, p3 = st.columns(3)
        p1.metric("Total recebido", _moeda(proventos["valor"].sum()))
        p2.metric("Lançamentos", len(proventos))
        p3.metric("Ativos distintos", proventos["ticker"].nunique())

        st.markdown("**Proventos por mês**")
        por_mes_prov = proventos.copy()
        por_mes_prov["mes"] = pd.to_datetime(por_mes_prov["data"]).dt.strftime("%Y-%m")
        st.bar_chart(por_mes_prov.groupby("mes")["valor"].sum())

        st.markdown("**Detalhamento**")
        st.dataframe(proventos.rename(columns={
            "data": "Data", "ticker": "Ticker", "tipo": "Tipo",
            "quantidade": "Quantidade", "valor": "Valor",
        }), use_container_width=True, hide_index=True)

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
            remover_provento(conexao, remover)
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
                use_container_width=True,
            )
        with col2:
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
                use_container_width=True,
            )

        st.divider()
        st.markdown("**Prévia — Apuração de IR**")
        if tabela_ir.empty:
            st.caption("Sem apuração no período.")
        else:
            st.dataframe(tabela_ir, use_container_width=True, hide_index=True)

        st.markdown("**Prévia — Operações**")
        st.dataframe(operacoes[colunas_extrato], use_container_width=True, hide_index=True)
