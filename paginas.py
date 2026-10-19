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
import tema
from parser import extract_notas
from persistencia import (
    adicionar_provento,
    assinatura_ativa,
    cancelar_assinatura,
    carregar_darf_pagamentos,
    carregar_notas,
    carregar_operacoes,
    carregar_parametros_fiscais,
    carregar_proventos,
    conectar,
    garantir_esquema,
    gravar_darf_pagamento,
    gravar_prejuizos,
    ler_prejuizos,
    limpar_dados,
    listar_notas_fiscais,
    listar_pagamentos,
    listar_planos,
    obter_plano,
    obter_usuario,
    remover_notas,
    remover_provento,
    resumo_importacao,
    salvar_notas,
    salvar_proventos,
)
from proventos import TIPOS, irrf_jcp, ler_planilha
from regras import (
    PARAMETROS,
    aplicar_parametros,
    apurar_mensal,
    classificar_grupo,
    codigo_receita_darf,
    meses_ate_vencimento,
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

# Rótulos legíveis das colunas de :data:`DETALHE_MERCADO` (ST = swing trade).
ROTULO_DETALHE = {
    "ResultsStockSwingTrade": "Ações (ST)",
    "ResultsStockDayTrade": "Ações (DT)",
    "ResultsGoldSwingTrade": "Ouro (ST)",
    "ResultsGoldDayTrade": "Ouro (DT)",
    "ResultsOptionSwingTrade": "Opções (ST)",
    "ResultsOptionDayTrade": "Opções (DT)",
    "ResultsFutureIDXSwingTrade": "Índice futuro (ST)",
    "ResultsFutureIDXDayTrade": "Índice futuro (DT)",
    "ResultsFutureFeeSwingTrade": "Juros futuros (ST)",
    "ResultsFutureFeeDayTrade": "Juros futuros (DT)",
    "ResultsFutureUSDSwingTrade": "Dólar futuro (ST)",
    "ResultsFutureUSDDayTrade": "Dólar futuro (DT)",
    "ResultsFutureOtherSwingTrade": "Futuros outros (ST)",
    "ResultsFutureOtherDayTrade": "Futuros outros (DT)",
    "ResultsTermSwingTrade": "Termo (ST)",
    "ResultsTermDayTrade": "Termo (DT)",
}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

@st.cache_resource
def _conexao():
    """Conexão SQLite única por processo (o Streamlit reexecuta o script)."""
    return conectar()


def obter_conexao():
    """Conexão com o banco, compartilhada por todas as páginas do app."""
    return garantir_esquema(_conexao())


def _moeda(valor: float) -> str:
    """Formata um número no padrão brasileiro: R$ 1.234,56."""
    return f"R$ {float(valor or 0.0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _moeda_txt(valor) -> str:
    """
    Valor em reais no padrão brasileiro (``R$ 1.234,56``); zero vira ``—``.

    Usado nas tabelas: além de eliminar os artefatos de ponto flutuante
    (``1291.5300000000002``), o traço deixa a leitura bem mais limpa do que
    uma fileira de ``0,00``.
    """
    if valor is None:
        return "—"
    try:
        numero = round(float(valor), 2)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(numero) or numero == 0:
        return "—"
    texto = f"{abs(numero):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if numero < 0 else ''}R$ {texto}"


def _tabela_moeda(df: pd.DataFrame, colunas: list[str]) -> pd.DataFrame:
    """Converte as colunas indicadas em texto de moeda brasileira."""
    visao = df.copy()
    for coluna in colunas:
        visao[coluna] = visao[coluna].map(_moeda_txt)
    return visao


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
    numero_mes += meses_ate_vencimento()
    while numero_mes > 12:
        numero_mes -= 12
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


def _colorir(df: pd.DataFrame, colunas: list[str]):
    """
    Aplica verde/vermelho às colunas indicadas (negativo = vermelho).

    Aceita tanto números quanto o texto de moeda de :func:`_moeda_txt`
    (``R$ 1.234,56`` / ``-R$ 5,00``); o traço de zero fica sem cor.
    """
    def pintar(valor):
        texto = "" if valor is None else str(valor).strip()
        if texto.startswith("-"):
            return f"color: {tema.VERMELHO}; font-weight: 600"
        if texto in ("", "—", "nan"):
            return ""
        if isinstance(valor, (int, float)):
            numero = float(valor)
        elif texto.startswith("R$"):
            numero = 1.0
        else:
            return ""
        if numero < 0:
            return f"color: {tema.VERMELHO}; font-weight: 600"
        if numero > 0:
            return f"color: {tema.VERDE}; font-weight: 600"
        return ""

    estilizador = df.style
    aplicador = getattr(estilizador, "map", None) or estilizador.applymap
    return aplicador(pintar, subset=colunas)


def _status_darf(competencia: str, recolher: float, pagamento: dict | None) -> str:
    """Situação da competência: Isento, Pago, Vencido ou Em aberto."""
    if recolher <= 0:
        return "Isento"
    if pagamento and pagamento["pago"]:
        return "Pago"
    if date.today() > _vencimento_darf(competencia):
        return "Vencido"
    return "Em aberto"


def _data_armazenada(texto: str | None) -> date:
    """Converte a data ISO guardada no banco (ou devolve hoje, se não houver)."""
    if texto:
        try:
            return date.fromisoformat(str(texto)[:10])
        except ValueError:
            pass
    return date.today()




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
darf_pagamentos = None
tem_dados = False

#: Página de DARF registrada em ``app.py``; preenchida após a navegação existir
#: e usada pelo atalho de emissão da página de upload.
PAGINA_DARF = None


def carregar(identificador: int) -> None:
    """Lê o banco SQLite do usuário e recalcula os agregados das páginas."""
    global conexao, usuario_id, operacoes, notas, proventos, prejuizos
    global resultados, tabela_ir, saldos_finais, posicao, darf_pagamentos, tem_dados

    usuario_id = int(identificador)
    conexao = obter_conexao()

    # Parâmetros fiscais vigentes (alíquotas, isenções, código do DARF),
    # editáveis no painel administrativo.
    aplicar_parametros(carregar_parametros_fiscais(conexao))

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
    darf_pagamentos = carregar_darf_pagamentos(conexao, usuario_id)

    tem_dados = not operacoes.empty


# ---------------------------------------------------------------------------
# Página 1 — Upload
# ---------------------------------------------------------------------------

def _texto_progresso(indice: int, total: int) -> str:
    """Texto da barra de progresso: ``2 de 5 notas — 40%``."""
    return f"{indice} de {total} nota(s) processada(s) — {round(indice / total * 100)}%"


def _dias_sem_nota(df: pd.DataFrame) -> list[date]:
    """Dias úteis sem nota entre a primeira e a última nota importada.

    Serve de alerta: um dia sem nota no meio do histórico pode ser um
    feriado, um dia sem negócios — ou uma nota que ficou de fora do envio,
    o que distorce a apuração (posições e prejuízos atravessam o mês).
    """
    if df is None or df.empty or "data" not in df.columns:
        return []

    datas = pd.to_datetime(df["data"], errors="coerce").dropna()
    if datas.empty:
        return []

    com_nota = set(datas.dt.date)
    faltando: list[date] = []
    dia = min(com_nota)
    ultimo = max(com_nota)
    while dia <= ultimo:
        if dia.weekday() < 5 and dia not in com_nota:   # sábado = 5, domingo = 6
            faltando.append(dia)
        dia += timedelta(days=1)
    return faltando


def _botao_darf(rotulo: str = "Emitir DARF", chave: str = "btn_darf") -> None:
    """Botão que leva direto à página de emissão do DARF."""
    if st.button(rotulo, type="primary", icon=":material/receipt_long:",
                 width="stretch", key=chave, disabled=PAGINA_DARF is None):
        st.switch_page(PAGINA_DARF)


def _secao_darf() -> None:
    """Atalho para emitir o DARF da competência mais recente apurada."""
    tema.secao("Emitir DARF")
    if tabela_ir.empty:
        st.caption(
            "Envie a primeira nota e o valor do DARF da competência aparece "
            "aqui — com vencimento e código de receita prontos para o Sicalc."
        )
        return

    competencia = str(tabela_ir["mes"].iloc[-1])
    linha = tabela_ir[tabela_ir["mes"] == competencia].iloc[0]
    recolher = float(linha["DARFFinal"])

    esquerda, direita = st.columns([2, 1])
    with esquerda:
        if recolher > 0:
            st.markdown(
                f"**{_nome_mes(competencia)}** — recolher {_moeda(recolher)} até "
                f"{_vencimento_darf(competencia):%d/%m/%Y} "
                f"(código {codigo_receita_darf()})."
            )
        else:
            st.markdown(f"**{_nome_mes(competencia)}** — {linha['ExemptionMessage']}.")
    with direita:
        _botao_darf()


def _cartao_conclusao(resultado: dict) -> None:
    """Retorno do processamento: o que foi importado, o que falhou e o próximo passo."""
    for aviso in resultado["avisos"]:
        st.warning(aviso)
    for erro in resultado["erros"]:
        st.error(erro)

    if resultado["repetidas"]:
        st.info(
            f"{resultado['repetidas']} nota(s) já importada(s) foram ignoradas "
            "automaticamente — nada foi somado em dobro."
        )

    if not resultado["arquivos"]:
        st.info("Nenhuma nota nova importada neste envio.")
        return

    st.success(
        f"**Concluído** — {resultado['arquivos']} arquivo(s) processado(s), "
        f"{resultado['notas']} nota(s) e {resultado['operacoes']} operação(ões)."
    )

    faltando = _dias_sem_nota(notas)
    if faltando:
        amostra = ", ".join(dia.strftime("%d/%m") for dia in faltando[:8])
        resto = f" e mais {len(faltando) - 8}" if len(faltando) > 8 else ""
        st.warning(
            f"{len(faltando)} dia(s) útil(eis) sem nota entre "
            f"{faltando[0]:%d/%m/%Y} e {faltando[-1]:%d/%m/%Y}: {amostra}{resto}. "
            "Confira se não ficou nenhuma nota de fora — feriados e dias sem "
            "negócios aparecem aqui também."
        )

    esquerda, direita = st.columns([2, 1])
    with esquerda:
        st.markdown("Sua apuração está pronta. Emita o DARF em um clique.")
    with direita:
        _botao_darf("Emitir DARF agora", "btn_darf_conclusao")


def pagina_upload() -> None:
    tema.hero(
        "Bem-vindo ao seu Gestor de Investimentos",
        "Importe as notas de corretagem em PDF e o app calcula posição, proventos e "
        "Imposto de Renda automaticamente — com isenção de R$ 20 mil e compensação "
        "de prejuízo mês a mês.",
        "\U0001F4C8",
    )

    resultado = st.session_state.pop("resultado_upload", None)
    if resultado is not None:
        _cartao_conclusao(resultado)

    contagem = resumo_importacao(conexao, usuario_id)
    tema.kpis([
        {"rotulo": "Notas importadas", "valor": contagem["notas"], "icone": "\U0001F4C4"},
        {"rotulo": "Operações", "valor": contagem["operacoes"], "icone": "\U0001F501"},
        {"rotulo": "Arquivos processados", "valor": contagem["arquivos"],
         "icone": "\U0001F5C2\uFE0F"},
    ])

    tema.secao("Enviar notas de corretagem")
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

    if st.button("Processar notas", type="primary", icon=":material/bolt:",
                 disabled=not arquivos):
        total = len(arquivos)
        barra = st.progress(0.0, text=f"0 de {total} nota(s) processada(s) — 0%")
        resultado = {"notas": 0, "operacoes": 0, "arquivos": 0, "repetidas": 0,
                     "erros": [], "avisos": []}
        interrompido = False
        ja_importadas = (
            set(zip(notas["corretora"].astype(str), notas["numero"].astype(str)))
            if not notas.empty else set()
        )

        for indice, arquivo in enumerate(arquivos, start=1):
            try:
                lidas = extract_notas(arquivo, corretora=corretora, arquivo=arquivo.name)
            except Exception as erro:  # noqa: BLE001
                resultado["erros"].append(f"Falha ao ler {arquivo.name}: {erro}")
                barra.progress(indice / total, text=_texto_progresso(indice, total))
                continue

            if not lidas:
                resultado["avisos"].append(f"Nenhuma operação reconhecida em {arquivo.name}.")
                barra.progress(indice / total, text=_texto_progresso(indice, total))
                continue

            ineditas = []
            for nota in lidas:
                chave = (str(nota.corretora), str(nota.numero))
                if chave in ja_importadas:
                    resultado["repetidas"] += 1
                    continue
                ja_importadas.add(chave)
                ineditas.append(nota)

            if not ineditas:
                resultado["avisos"].append(
                    f"{arquivo.name}: nota(s) já importada(s) — ignorado(s) sem erro."
                )
                barra.progress(indice / total, text=_texto_progresso(indice, total))
                continue

            permitido, aviso = saas.pode_importar(conexao, usuario_id, len(ineditas))
            if not permitido:
                resultado["erros"].append(aviso)
                interrompido = True
                break

            novas, ops = salvar_notas(conexao, ineditas, usuario_id)
            resultado["notas"] += novas
            resultado["operacoes"] += ops
            resultado["arquivos"] += 1
            barra.progress(indice / total, text=_texto_progresso(indice, total))

        if interrompido:
            barra.empty()
        else:
            barra.progress(1.0, text=f"Concluído — {total} nota(s) processada(s) — 100%")

        st.session_state["resultado_upload"] = resultado
        st.rerun()

    _secao_darf()

    with st.expander(":material/delete: Limpar dados importados"):
        st.caption(
            "Remove as notas, operações e proventos deste usuário. Os saldos de "
            "prejuízo a compensar informados na apuração são mantidos."
        )
        if st.button("Limpar operações importadas"):
            limpar_dados(conexao, usuario_id)
            st.rerun()

    if notas.empty:
        tema.vazio("Nenhuma nota importada ainda. Envie um PDF para começar.")
        return

    tema.secao("Notas importadas")

    mensagem = st.session_state.pop("aviso_notas", None)
    if mensagem:
        st.success(mensagem)

    visao_notas = notas.reset_index(drop=True)
    visao_notas["data"] = visao_notas["data"].dt.strftime("%d/%m/%Y")
    visao_notas = visao_notas.rename(columns={
        "numero": "Nota", "corretora": "Corretora", "data": "Data",
        "arquivo": "Arquivo", "despesas": "Despesas", "irrf": "IRRF",
        "categoria_irrf": "Categoria IRRF",
    })

    esquerda, direita = st.columns(2)
    with esquerda:
        if st.button("Selecionar todas", icon=":material/select_all:", width="stretch"):
            st.session_state["sel_notas"] = {
                "selection": {"rows": list(range(len(visao_notas))), "columns": []},
            }
    with direita:
        if st.button("Limpar seleção", icon=":material/deselect:", width="stretch"):
            st.session_state["sel_notas"] = {
                "selection": {"rows": [], "columns": []},
            }

    evento = st.dataframe(
        visao_notas,
        width="stretch",
        hide_index=True,
        key="sel_notas",
        on_select="rerun",
        selection_mode="multi-row",
    )
    selecionadas = list(evento.selection.rows)
    st.caption(f"{len(selecionadas)} de {len(visao_notas)} nota(s) selecionada(s).")

    if st.button("Apagar selecionadas", icon=":material/delete:", type="primary",
                 width="stretch", disabled=not selecionadas):
        chaves = [
            (str(visao_notas.at[i, "Corretora"]), str(visao_notas.at[i, "Nota"]))
            for i in selecionadas
        ]
        removidas = remover_notas(conexao, usuario_id, chaves)
        st.session_state["sel_notas"] = {"selection": {"rows": [], "columns": []}}
        st.session_state["aviso_notas"] = (
            f"{removidas} nota(s) apagada(s) — as operações delas saíram do cálculo."
        )
        st.rerun()


# ---------------------------------------------------------------------------
# Página 2 — Visão Geral
# ---------------------------------------------------------------------------

def pagina_visao() -> None:
    tema.cabecalho(
        "Visão geral",
        "Um panorama da sua carteira, dos resultados e dos impostos do período.",
        "\U0001F4CA",
    )

    if not tem_dados:
        tema.vazio("Sem dados ainda. Importe notas na página **Upload de Notas**.")
    else:
        custo_total = float(posicao["Custo Total"].sum()) if not posicao.empty else 0.0
        ir_total = float(tabela_ir["IRRFFinal"].sum()) if not tabela_ir.empty else 0.0
        total_proventos = float(proventos["valor"].sum()) if not proventos.empty else 0.0

        tema.kpis([
            {"rotulo": "Patrimônio (custo)", "valor": _moeda(custo_total),
             "icone": "\U0001F4BC"},
            {"rotulo": "Ativos em carteira", "valor": len(posicao), "icone": "\U0001F4C8"},
            {"rotulo": "IR apurado no período", "valor": _moeda(ir_total),
             "icone": "\U0001F4B0"},
            {"rotulo": "Proventos recebidos", "valor": _moeda(total_proventos),
             "icone": "\U0001F4B5"},
        ])

        tema.secao("Resultado realizado por mês")
        if resultados.empty:
            tema.vazio("Nenhum resultado realizado no período.")
        else:
            por_mes = resultados.pivot_table(
                index="mes", columns="categoria", values="resultado",
                aggfunc="sum", fill_value=0.0,
            )
            st.bar_chart(por_mes, height=320)

        tema.secao("Últimos negócios")
        ultimos = operacoes.sort_values("data", ascending=False).head(15)
        st.dataframe(
            ultimos[["data", "ticker", "tipo", "quantidade", "preco", "mercado", "nota"]],
            width="stretch", hide_index=True,
        )


# ---------------------------------------------------------------------------
# Página 3 — Extrato
# ---------------------------------------------------------------------------

def pagina_extrato() -> None:
    tema.cabecalho(
        "Extrato de operações",
        "Todas as operações importadas, com filtros por período, ativo e mercado.",
        "\U0001F9FE",
    )

    if not tem_dados:
        tema.vazio("Sem operações ainda. Importe notas na página **Upload de Notas**.")
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

        tema.kpis([
            {"rotulo": "Operações", "valor": len(filtro), "icone": "\U0001F501"},
            {"rotulo": "Compras",
             "valor": _moeda(filtro.loc[filtro["tipo"] == "C", "valor_total"].sum()),
             "icone": "\U0001F7E2"},
            {"rotulo": "Vendas",
             "valor": _moeda(filtro.loc[filtro["tipo"] == "V", "valor_total"].sum()),
             "icone": "\U0001F534"},
        ])

        colunas = ["data", "tipo", "ticker", "grupo", "mercado", "quantidade",
                   "preco", "valor_total", "taxas", "resultado", "nota", "corretora"]
        colunas_moeda = ["preco", "valor_total", "taxas", "resultado"]
        st.dataframe(
            _colorir(_tabela_moeda(filtro[colunas], colunas_moeda), colunas_moeda),
            width="stretch", hide_index=True,
        )

        st.download_button(
            "Baixar extrato filtrado (CSV)",
            data=_to_csv(filtro[colunas]),
            file_name=f"extrato_{date.today():%Y%m%d}.csv",
            mime="text/csv",
            icon=":material/download:",
        )


# ---------------------------------------------------------------------------
# Página 4 — Meu Patrimônio
# ---------------------------------------------------------------------------

def pagina_patrimonio() -> None:
    tema.cabecalho(
        "Posição em custódia",
        "O que você tem hoje, com preço médio já ajustado pelas taxas de corretagem.",
        "\U0001F4BC",
    )

    if posicao.empty:
        tema.vazio("Sem posição calculada ainda. Importe notas na página **Upload de Notas**.")
    else:
        tema.kpis([
            {"rotulo": "Ativos em carteira", "valor": len(posicao), "icone": "\U0001F4CA"},
            {"rotulo": "Custo total", "valor": _moeda(posicao["Custo Total"].sum()),
             "icone": "\U0001F4B0"},
            {"rotulo": "Grupos distintos", "valor": posicao["Grupo"].nunique(),
             "icone": "\U0001F5C3\uFE0F"},
        ])

        st.dataframe(
            _tabela_moeda(posicao, ["Preço Médio", "Custo Total"]),
            width="stretch", hide_index=True,
        )

        tema.secao("Custo por grupo de ativos")
        st.bar_chart(posicao.groupby("Grupo")["Custo Total"].sum(), height=320)

        st.caption(
            "Preço médio ponderado com as taxas de corretagem somadas ao custo "
            "(item 3 do checklist de reconstrução)."
        )


# ---------------------------------------------------------------------------
# Página 5 — Apuração de IR
# ---------------------------------------------------------------------------

def pagina_ir() -> None:
    tema.cabecalho(
        "Apuração de Imposto de Renda",
        "Projeção mensal de IR sobre renda variável, com isenção e compensação de prejuízos.",
        "\U0001F4B0",
    )

    with st.expander(":material/settings: Saldos iniciais a compensar", expanded=False):
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

        if st.button("Salvar saldos", type="primary", icon=":material/save:"):
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
        tema.vazio("Nenhuma operação com resultado realizada. "
                   "A apuração aparece após importar notas.")
    else:
        ir_total = float(tabela_ir["IRRFFinal"].sum())
        irrf_total = float(
            tabela_ir["IRRFMonthlyDayTrade"].sum() + tabela_ir["IRRFMonthlySwingTrade"].sum()
        )
        tema.kpis([
            {"rotulo": "IR apurado", "valor": _moeda(tabela_ir["IRRFBase"].sum()),
             "icone": "\U0001F4B0"},
            {"rotulo": "IRRF retido", "valor": _moeda(irrf_total), "icone": "\U0001F9FE"},
            {"rotulo": "IR a pagar", "valor": _moeda(ir_total), "icone": "\U0001F4C5"},
        ])

        visao = tabela_ir[list(RESUMO_IR)].rename(columns=RESUMO_IR).copy()
        visao["Mês"] = visao["Mês"].map(_nome_mes)
        # Colunas zeradas em todas as competências só poluem a leitura.
        for coluna in [c for c in visao.columns if c not in ("Mês", "Situação")]:
            if pd.to_numeric(visao[coluna], errors="coerce").fillna(0.0).abs().sum() == 0:
                visao = visao.drop(columns=coluna)
        coloriveis = [c for c in visao.columns if c not in ("Mês", "Situação")]
        visao = _tabela_moeda(visao, coloriveis)
        st.dataframe(_colorir(visao, coloriveis), width="stretch", hide_index=True)

        tema.secao("Resultados por mercado")
        detalhe = tabela_ir[["mes"] + DETALHE_MERCADO].copy()
        detalhe["Mês"] = detalhe["mes"].map(_nome_mes)
        # Mercados sem resultado em nenhuma competência só poluem a leitura.
        ativos = [c for c in DETALHE_MERCADO
                  if pd.to_numeric(detalhe[c], errors="coerce").fillna(0.0).abs().sum() > 0]
        if not ativos:
            st.caption("Sem resultados por mercado no período.")
        else:
            rotulos = [ROTULO_DETALHE[c] for c in ativos]
            visao_mercado = detalhe[["Mês"] + ativos].rename(columns=ROTULO_DETALHE)
            st.dataframe(
                _colorir(_tabela_moeda(visao_mercado, rotulos), rotulos),
                width="stretch", hide_index=True,
            )

        st.caption(
            f"Day Trade: {float(PARAMETROS['aliquota_day_trade']):.0%} sem isenção. "
            f"Swing Trade: {float(PARAMETROS['aliquota_swing_trade']):.0%} "
            f"(FII/FIAGRO: {float(PARAMETROS['aliquota_fii']):.0%}), com isenção "
            f"quando as vendas do grupo no mês ficam dentro de "
            f"{_moeda(PARAMETROS['isencao_acoes'])} (ações/BDR/ouro) ou "
            f"{_moeda(PARAMETROS['isencao_eua'])} (ativos dos EUA). "
            "Prejuízos e IRRF retido são compensados por categoria, mês a mês — "
            "o que não for usado fica acumulado para as competências seguintes."
        )


# ---------------------------------------------------------------------------
# Página 6 — DARF
# ---------------------------------------------------------------------------

def pagina_darf() -> None:
    tema.cabecalho(
        "DARF — ganhos líquidos em renda variável",
        "O valor a recolher por competência, com o código de receita e o vencimento.",
        "\U0001F9EE",
    )

    if tabela_ir.empty:
        tema.vazio("Sem competências apuradas. Importe notas na página **Upload de Notas**.")
        return

    competencias = list(tabela_ir["mes"])

    # -- Painel de competências, com a situação de pagamento ---------------
    tema.secao("Competências")
    colunas_moeda = ["Base de cálculo", "IR apurado", "IRRF retido", "Valor a recolher"]
    resumo = pd.DataFrame([
        {
            "Competência": _nome_mes(mes),
            "Base de cálculo": float(linha["BaseCalcSwingTrade"]) + float(linha["BaseCalcDayTrade"]),
            "IR apurado": float(linha["IRRFBase"]),
            "IRRF retido": float(linha["IRRFMonthlyDayTrade"]) + float(linha["IRRFMonthlySwingTrade"]),
            "Valor a recolher": float(linha["DARFFinal"]),
            "Vencimento": _vencimento_darf(mes).strftime("%d/%m/%Y"),
            "Situação": _status_darf(mes, float(linha["DARFFinal"]), darf_pagamentos.get(mes)),
        }
        for mes, linha in zip(competencias, tabela_ir.to_dict("records"))
    ])
    resumo = _tabela_moeda(resumo, colunas_moeda)
    st.dataframe(
        _colorir(resumo, colunas_moeda),
        width="stretch", hide_index=True,
    )

    st.divider()
    competencia = st.selectbox(
        "Competência", competencias,
        index=len(competencias) - 1,
        format_func=_nome_mes,
    )
    linha = tabela_ir[tabela_ir["mes"] == competencia].iloc[0]
    pagamento = darf_pagamentos.get(competencia)
    recolher = float(linha["DARFFinal"])
    situacao = _status_darf(competencia, recolher, pagamento)

    tema.kpis([
        {"rotulo": "Base de cálculo",
         "valor": _moeda(linha["BaseCalcSwingTrade"] + linha["BaseCalcDayTrade"]),
         "icone": "\U0001F4CA"},
        {"rotulo": "IR apurado", "valor": _moeda(linha["IRRFBase"]), "icone": "\U0001F4B0"},
        {"rotulo": "IRRF retido",
         "valor": _moeda(linha["IRRFMonthlyDayTrade"] + linha["IRRFMonthlySwingTrade"]),
         "icone": "\U0001F9FE"},
        {"rotulo": "Valor a recolher", "valor": _moeda(recolher),
         "icone": "\U0001F4C5", "tom": "neg" if recolher > 0 else "pos"},
        {"rotulo": "Situação", "valor": situacao,
         "icone": "\u2705" if situacao == "Pago" else "\u23F3",
         "tom": "pos" if situacao in ("Pago", "Isento") else "neg"},
    ])

    if recolher <= 0:
        st.success(f"{_nome_mes(competencia)}: {linha['ExemptionMessage']}.")
    elif situacao == "Pago":
        st.success(
            f"{_nome_mes(competencia)}: DARF de {_moeda(pagamento['valor_pago'])} pago em "
            f"{_data_armazenada(pagamento['data_pagamento']):%d/%m/%Y}."
        )
    elif situacao == "Vencido":
        st.error(
            f"**{_nome_mes(competencia)}** — recolher {_moeda(recolher)} "
            f"(vencido em {_vencimento_darf(competencia):%d/%m/%Y})."
        )
    else:
        st.warning(
            f"**{_nome_mes(competencia)}** — recolher {_moeda(recolher)} "
            f"até {_vencimento_darf(competencia):%d/%m/%Y}."
        )

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        tema.secao("Dados para emissão no Sicalc / internet banking")
        st.code(
            f"Código de receita: {codigo_receita_darf()}\n"
            f"Período de apuração: {competencia}\n"
            f"Vencimento: {_vencimento_darf(competencia):%d/%m/%Y}\n"
            f"Valor: {_moeda(linha['DARFFinal'])}",
            language="text",
        )
    with col2:
        tema.secao("Composição")
        composicao = pd.DataFrame([
            {"Item": "Base de cálculo Day Trade", "Valor": linha["BaseCalcDayTrade"]},
            {"Item": "Base de cálculo Swing Trade", "Valor": linha["BaseCalcSwingTrade"]},
            {"Item": "Base de cálculo FII", "Valor": linha["BaseCalcFII"]},
            {"Item": "IR apurado", "Valor": linha["IRRFBase"]},
            {"Item": "(-) IRRF retido", "Valor": -(
                linha["IRRFMonthlyDayTrade"] + linha["IRRFMonthlySwingTrade"])},
            {"Item": "IR a recolher", "Valor": linha["DARFFinal"]},
        ])
        st.dataframe(
            _colorir(_tabela_moeda(composicao, ["Valor"]), ["Valor"]),
            width="stretch", hide_index=True,
        )

    # -- Controle de pagamento --------------------------------------------
    tema.secao("Pagamento")
    if recolher <= 0:
        st.caption("Competência isenta: não há DARF a recolher.")
    else:
        with st.form(f"form_darf_{competencia}"):
            col1, col2 = st.columns(2)
            with col1:
                pago = st.checkbox(
                    "DARF pago",
                    value=bool(pagamento and pagamento["pago"]),
                    key=f"pago_{competencia}",
                )
            with col2:
                valor_pago = st.number_input(
                    "Valor pago",
                    value=float(pagamento["valor_pago"]) if pagamento and pagamento["valor_pago"]
                    else recolher,
                    step=1.0, format="%.2f", key=f"valor_{competencia}",
                )
            data_pagamento = st.date_input(
                "Data do pagamento",
                value=_data_armazenada(pagamento["data_pagamento"] if pagamento else None),
                key=f"data_{competencia}",
            )
            if st.form_submit_button("Salvar pagamento", type="primary",
                                     icon=":material/save:"):
                gravar_darf_pagamento(
                    conexao, usuario_id, competencia, pago, valor_pago,
                    data_pagamento.isoformat() if pago else None,
                )
                st.success("Controle de pagamento atualizado.")
                st.rerun()

    st.download_button(
        "Baixar apuração do período (CSV)",
        data=_to_csv(tabela_ir),
        file_name=f"apuracao_{date.today():%Y%m%d}.csv",
        mime="text/csv",
        icon=":material/download:",
    )
    st.caption(
        f"Código de receita {codigo_receita_darf()} — ganhos líquidos em operações "
        "realizadas em bolsas de valores, de mercadorias, de futuros e "
        "assemelhadas (pessoa física)."
    )


# ---------------------------------------------------------------------------
# Página 7 — Proventos
# ---------------------------------------------------------------------------

def pagina_proventos() -> None:
    tema.cabecalho(
        "Proventos recebidos",
        "Dividendos, JCP, rendimentos de FII e demais bonificações — com o "
        "IRRF do JCP calculado automaticamente.",
        "\U0001F4B5",
    )

    # -- Importação do extrato ---------------------------------------------
    with st.expander(":material/upload_file: Importar extrato de proventos (CSV ou XLSX)",
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
                    if st.button(f"Importar {len(tabela)} provento(s)", type="primary",
                                 icon=":material/check_circle:"):
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
    with st.expander(":material/add_circle: Lançar provento manualmente"):
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
                valor_provento = st.number_input("Valor (R$)", value=0.0, step=0.01,
                                                 format="%.2f")

            if st.form_submit_button("Adicionar provento", type="primary",
                                     icon=":material/add:"):
                if not ticker_provento.strip():
                    st.error("Informe o ticker do provento.")
                else:
                    adicionar_provento(conexao, usuario_id, data_provento.isoformat(),
                                       ticker_provento.strip(), tipo_provento,
                                       quantidade_provento, valor_provento)
                    st.rerun()

    if proventos.empty:
        tema.vazio("Nenhum provento registrado ainda. Importe um extrato ou "
                   "lance manualmente.")
        return

    # -- Resumo ------------------------------------------------------------
    detalhe = proventos.assign(irrf=[
        irrf_jcp(valor) if tipo == "JCP" else 0.0
        for tipo, valor in zip(proventos["tipo"], proventos["valor"])
    ])
    irrf_total_jcp = detalhe["irrf"].sum()

    tema.kpis([
        {"rotulo": "Total recebido", "valor": _moeda(proventos["valor"].sum()),
         "icone": "\U0001F4B0"},
        {"rotulo": "Lançamentos", "valor": len(proventos), "icone": "\U0001F4C4"},
        {"rotulo": "Ativos distintos", "valor": proventos["ticker"].nunique(),
         "icone": "\U0001F3E6"},
        {"rotulo": "IRRF de JCP (15%)", "valor": _moeda(irrf_total_jcp),
         "icone": "\U0001F9FE"},
    ])
    st.caption(
        "O IRRF do JCP é retido na fonte com tributação **exclusiva**: é definitivo "
        "e não entra no DARF 6015 do IR mensal da renda variável — serve para "
        "informar o rendimento na declaração anual. O cálculo considera o valor "
        "lançado como bruto; se o extrato trouxer o valor já líquido, informe o bruto."
    )

    tema.secao("Por tipo de provento")
    por_tipo = proventos.groupby("tipo")["valor"].agg(
        Lancamentos="count", Valor="sum"
    ).reset_index()
    por_tipo["irrf"] = [
        irrf_jcp(valor) if tipo == "JCP" else 0.0
        for tipo, valor in zip(por_tipo["tipo"], por_tipo["Valor"])
    ]
    st.dataframe(por_tipo.rename(columns=ROTULOS_PROVENTO), width="stretch", hide_index=True)

    tema.secao("Proventos por mês")
    por_mes_prov = proventos.copy()
    por_mes_prov["mes"] = pd.to_datetime(por_mes_prov["data"]).dt.strftime("%Y-%m")
    st.bar_chart(por_mes_prov.groupby("mes")["valor"].sum(), height=320)

    tema.secao("Detalhamento")
    st.dataframe(detalhe.drop(columns=["id"]).rename(columns=ROTULOS_PROVENTO),
                 width="stretch", hide_index=True)

    with st.expander(":material/delete: Remover lançamento"):
        remover = st.selectbox(
            "Remover lançamento",
            options=list(proventos["id"]),
            format_func=lambda i: (
                f"{proventos.loc[proventos['id'] == i, 'data'].iloc[0]} — "
                f"{proventos.loc[proventos['id'] == i, 'ticker'].iloc[0]} — "
                f"{_moeda(proventos.loc[proventos['id'] == i, 'valor'].iloc[0])}"
            ),
        )
        if st.button("Remover selecionado", icon=":material/delete:"):
            remover_provento(conexao, usuario_id, remover)
            st.rerun()


# ---------------------------------------------------------------------------
# Página 8 — Relatórios
# ---------------------------------------------------------------------------

def pagina_relatorios() -> None:
    tema.cabecalho(
        "Exportar dados",
        "Baixe suas operações, posição e apuração para conferência, planilha "
        "ou backup pessoal.",
        "\U0001F4E5",
    )

    if not tem_dados:
        tema.vazio("Nada para exportar ainda. Importe notas na página "
                   "**Upload de Notas**.")
    else:
        colunas_extrato = ["data", "tipo", "ticker", "grupo", "mercado", "quantidade",
                           "preco", "valor_total", "taxas", "resultado", "nota", "corretora"]

        tema.kpis([
            {"rotulo": "Operações", "valor": len(operacoes), "icone": "\U0001F501"},
            {"rotulo": "Notas", "valor": len(notas), "icone": "\U0001F4C4"},
            {"rotulo": "Competências apuradas", "valor": len(tabela_ir),
             "icone": "\U0001F4C5"},
        ])

        tema.secao("Baixar arquivos")
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "Operações (CSV)",
                data=_to_csv(operacoes[colunas_extrato]),
                file_name=f"operacoes_{date.today():%Y%m%d}.csv",
                mime="text/csv",
                width="stretch",
                icon=":material/table_view:",
            )
        with col2:
            if saas.pode_exportar_excel(conexao, usuario_id):
                st.download_button(
                    "Consolidado (Excel)",
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
                    icon=":material/grid_on:",
                )
            else:
                st.info(
                    "A exportação consolidada em **Excel** faz parte do plano "
                    "PRO. Assine em **Planos e Assinatura** para liberar."
                )

        tema.secao("Prévia — Apuração de IR")
        if tabela_ir.empty:
            st.caption("Sem apuração no período.")
        else:
            st.dataframe(tabela_ir, width="stretch", hide_index=True)

        tema.secao("Prévia — Operações")
        st.dataframe(operacoes[colunas_extrato], width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Página 9 — Planos e Assinatura (checkout)
# ---------------------------------------------------------------------------

def pagina_planos() -> None:
    tema.cabecalho(
        "Planos e assinatura",
        "Compare os planos e libere os recursos avançados quando precisar.",
        "\U0001F4B3",
    )

    if saas.eh_pro(conexao, usuario_id):
        st.success(f"Você é assinante do plano **{saas.rotulo_plano(conexao, usuario_id)}**.")
    else:
        st.info(f"Você está no plano **{saas.rotulo_plano(conexao, usuario_id)}**.")

    tema.secao("Planos disponíveis")
    planos = listar_planos(conexao)
    if planos.empty:
        st.warning("Nenhum plano configurado.")
        return

    colunas = st.columns(len(planos))
    for coluna, (_, plano) in zip(colunas, planos.iterrows()):
        with coluna, st.container(border=True):
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

    pro = obter_plano(conexao, "pro")
    if pro is None:
        st.warning("Plano PRO não configurado.")
    elif not saas.eh_pro(conexao, usuario_id):
        tema.secao("Assinar o PRO")
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

        if st.button("Confirmar assinatura", type="primary",
                     icon=":material/workspace_premium:"):
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
        tema.secao("Assinatura vigente")
        tema.kpis([
            {"rotulo": "Plano",
             "valor": assinatura["plano_nome"] or assinatura["plano_codigo"],
             "icone": "\U0001F31F"},
            {"rotulo": "Início", "valor": assinatura["inicio"], "icone": "\U0001F4C6"},
            {"rotulo": "Renova até", "valor": assinatura["fim"], "icone": "\U0001F501"},
            {"rotulo": "Valor", "valor": _moeda(assinatura["valor_pago"]),
             "icone": "\U0001F4B0"},
        ])
        if st.button("Cancelar assinatura", icon=":material/cancel:"):
            cancelar_assinatura(conexao, usuario_id)
            st.success("Assinatura cancelada. Você voltou ao plano Gratuito.")
            st.rerun()

    tema.secao("Meus pagamentos e notas fiscais")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Pagamentos**")
        pagamentos = listar_pagamentos(conexao, usuario_id)
        if pagamentos.empty:
            st.caption("Nenhum pagamento registrado.")
        else:
            st.dataframe(pagamentos, width="stretch", hide_index=True)
    with col2:
        st.markdown("**Notas fiscais**")
        notas_fiscais = listar_notas_fiscais(conexao, usuario_id)
        if notas_fiscais.empty:
            st.caption("Nenhuma nota fiscal emitida.")
        else:
            st.dataframe(notas_fiscais, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Página 10 — Minha Conta
# ---------------------------------------------------------------------------

def pagina_conta() -> None:
    tema.cabecalho(
        "Minha conta",
        "Seus dados de acesso, o plano vigente e a troca de senha.",
        "\U0001F464",
    )

    usuario = obter_usuario(conexao, usuario_id)
    if usuario is None:
        st.error("Conta não encontrada.")
        return

    tema.kpis([
        {"rotulo": "Usuário", "valor": usuario["usuario"], "icone": "\U0001F464"},
        {"rotulo": "Plano", "valor": saas.rotulo_plano(conexao, usuario_id),
         "icone": "\U0001F4B3"},
        {"rotulo": "Perfil", "valor": "Administrador" if usuario["is_admin"] else "Investidor",
         "icone": "\U0001F6E1\uFE0F"},
        {"rotulo": "Cadastro em", "valor": (usuario["criado_em"] or "")[:10],
         "icone": "\U0001F4C6"},
    ])
    st.caption(f"E-mail: {usuario['email']}")

    tema.secao("Alterar senha")
    with st.form("form_alterar_senha"):
        senha_atual = st.text_input("Senha atual", type="password", key="ct_atual")
        nova = st.text_input("Nova senha", type="password", key="ct_nova")
        confirmacao = st.text_input("Confirme a nova senha", type="password",
                                    key="ct_confirmacao")
        if st.form_submit_button("Alterar senha", type="primary",
                                 icon=":material/lock_reset:"):
            if len(nova) < auth.TAMANHO_MINIMO:
                st.error(f"A senha deve ter ao menos {auth.TAMANHO_MINIMO} caracteres.")
            elif nova != confirmacao:
                st.error("As senhas não conferem.")
            elif auth.alterar_senha(conexao, usuario_id, senha_atual, nova):
                st.success("Senha alterada com sucesso.")
            else:
                st.error("Senha atual incorreta.")
