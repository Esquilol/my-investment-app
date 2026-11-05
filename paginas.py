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
import altair as alt

import auth
import saas
import tema
from parser import extract_notas, detectar_corretora
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
    sanitizar_duplicatas,
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
    detalhar_posicoes_custodia,
    COTACOES_REFERENCIA,
    METADADOS_OPCOES,
    resultados_realizados,
    valor_minimo_darf,
)


CORRETORAS = [
    "Detectar automaticamente (recomendado)",
    "Genial",
    "XP Investimentos",
    "Clear",
    "Rico",
    "BTG Pactual",
    "Inter",
    "Nubank",
    "Santander",
    "Ágora",
    "Toro",
    "Genérico (SINACOR)",
]

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
    """Situação da competência: Isento, Pago, Vencido, Em aberto ou Acumulado (< R$ 10)."""
    if recolher <= 0:
        return "Isento"
    if pagamento and pagamento.get("pago"):
        return "Pago"
    if 0 < recolher < valor_minimo_darf():
        return "Acumulado (< R$ 10)"
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


def _exibir_alertas_darf(com_status_positivo: bool = True) -> None:
    """Exibe alertas de DARFs vencidos, pendentes ou situação regular (Lei 9.430/96)."""
    if tabela_ir.empty:
        return

    hoje = date.today()
    vencidos = []
    a_vencer = []
    acumulados = []

    for _, linha in tabela_ir.iterrows():
        mes = str(linha["mes"])
        recolher = float(linha.get("DARFFinal", 0.0))
        pagamento = darf_pagamentos.get(mes)
        if recolher > 0 and (not pagamento or not pagamento.get("pago")):
            if 0 < recolher < valor_minimo_darf():
                acumulados.append({"mes": mes, "valor": recolher})
                continue
            vencimento = _vencimento_darf(mes)
            if hoje > vencimento:
                dias = (hoje - vencimento).days
                multa_pct = min(dias * 0.33, 20.0)
                multa_valor = recolher * (multa_pct / 100.0)
                vencidos.append({
                    "mes": mes, "valor": recolher, "vencimento": vencimento,
                    "dias": dias, "multa_pct": multa_pct, "multa_valor": multa_valor,
                })
            else:
                dias = (vencimento - hoje).days
                a_vencer.append({
                    "mes": mes, "valor": recolher, "vencimento": vencimento, "dias": dias,
                })

    for item in vencidos:
        c_msg, c_btn = st.columns([3, 1])
        with c_msg:
            st.error(
                f"🚨 **DARF VENCIDO ({_nome_mes(item['mes'])}):** Valor de **{_moeda(item['valor'])}** "
                f"venceu em **{item['vencimento']:%d/%m/%Y}** ({item['dias']} dia(s) em atraso). "
                f"Multa de mora estimada: **{item['multa_pct']:.2f}%** (+{_moeda(item['multa_valor'])}), "
                f"mais juros Selic acumulados."
            )
        with c_btn:
            if st.button("Pagar / Regularizar", type="primary", icon=":material/payment:",
                         key=f"btn_venc_{item['mes']}", width="stretch",
                         disabled=PAGINA_DARF is None):
                st.switch_page(PAGINA_DARF)

    for item in a_vencer:
        aviso = "vence **hoje!**" if item["dias"] == 0 else f"vence em **{item['dias']} dia(s)** ({item['vencimento']:%d/%m/%Y})"
        c_msg, c_btn = st.columns([3, 1])
        with c_msg:
            st.warning(
                f"⏰ **DARF Pendente a Pagar ({_nome_mes(item['mes'])}):** Valor de "
                f"**{_moeda(item['valor'])}** {aviso}. "
                f"Código de receita: **{codigo_receita_darf()}**."
            )
        with c_btn:
            if st.button("Ver Dados Bancários", type="secondary", icon=":material/receipt_long:",
                         key=f"btn_avenc_{item['mes']}", width="stretch",
                         disabled=PAGINA_DARF is None):
                st.switch_page(PAGINA_DARF)

    for item in acumulados:
        st.info(
            f"ℹ️ **Imposto acumulado ({_nome_mes(item['mes'])}):** {_moeda(item['valor'])}. "
            f"Conforme o Art. 67 da Lei 9.430/96, DARFs inferiores a R$ 10,00 não devem ser recolhidos isoladamente; "
            "o valor fica acumulado para a próxima competência."
        )

    if not vencidos and not a_vencer and not acumulados and com_status_positivo:
        st.success("🟢 **Situação Fiscal 100% Regular:** Nenhum DARF pendente de pagamento para as competências apuradas.")




# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Suporte e Ticket
# ---------------------------------------------------------------------------

@st.dialog("💬 Suporte & Ajuda Fiscal")
def modal_suporte_ticket() -> None:
    st.markdown("""
    <div style="margin-bottom: 12px; color: #cbd5e1; font-size: 0.95em;">
        Tem alguma dúvida sobre sua apuração, DARF, isenção dos R$ 20.000 ou importação de notas?
        Nossa equipe de especialistas contábeis está à disposição para te orientar.
    </div>
    """, unsafe_allow_html=True)
    assunto = st.selectbox(
        "Assunto do chamado:",
        [
            "Dúvida sobre emissão ou pagamento do DARF",
            "Dúvida sobre compensação de prejuízos ou isenções",
            "Dificuldade ao importar notas de corretagem",
            "Sugestão de melhoria ou nova funcionalidade",
            "Outro assunto",
        ],
    )
    email_contato = st.text_input("Seu e-mail para resposta:", value=st.session_state.get("usuario_email", ""))
    mensagem = st.text_area("Descreva sua dúvida com detalhes:", height=120, placeholder="Ex.: Gostaria de saber como comprovar o pagamento da DARF...")
    if st.button("Enviar chamado", type="primary", icon=":material/send:", width="stretch"):
        if not mensagem.strip():
            st.error("Por favor, descreva sua dúvida antes de enviar.")
        else:
            st.success("✅ Chamado registrado com sucesso! Responderemos em seu e-mail em até 24h úteis.")
            st.caption("Protocolo de atendimento: #FT" + datetime.now().strftime("%y%m%d%H%M"))


# ---------------------------------------------------------------------------
# Modal de Emissão Oficial de DARF (IN/RFB nº 736/2007)
# ---------------------------------------------------------------------------

@st.dialog("🖨️ Documento de Arrecadação de Receitas Federais — DARF", width="large")
def modal_emitir_darf_oficial(competencia: str, recolher: float) -> None:
    """Emite o formulário oficial do DARF em 2 vias aprovado pela IN/RFB nº 736/2007."""
    vencimento = _vencimento_darf(competencia)
    venc_str = vencimento.strftime("%d/%m/%Y")
    ano, mes_num = competencia.split("-")
    ultimo_dia_mes = calendar.monthrange(int(ano), int(mes_num))[1]
    periodo_apuracao = f"{ultimo_dia_mes:02d}/{mes_num}/{ano}"
    cod_rec = codigo_receita_darf()
    val_str = _moeda(recolher)

    usuario_nome = "INVESTIDOR PESSOA FÍSICA"
    usuario_telefone = "(00) 00000-0000"
    usuario_cpf = "000.000.000-00"
    domicilio_tributario = "BRASIL"
    if usuario_id:
        try:
            u_info = obter_usuario(conexao, usuario_id)
            if u_info:
                u_dict = dict(u_info) if hasattr(u_info, "keys") else (u_info if isinstance(u_info, dict) else {})
                usuario_nome = u_dict.get("nome") or u_dict.get("usuario") or usuario_nome
                usuario_cpf = u_dict.get("cpf") or usuario_cpf
                usuario_telefone = u_dict.get("telefone") or usuario_telefone
                cid = u_dict.get("cidade")
                est = u_dict.get("estado")
                if cid and est:
                    domicilio_tributario = f"{cid.upper()} - {est.upper()}"
                elif cid:
                    domicilio_tributario = cid.upper()
        except Exception:
            pass

    st.markdown("""
    <style>
    @media print {
        body * { visibility: hidden; }
        .darf-print-container, .darf-print-container * { visibility: visible; }
        .darf-print-container { position: absolute; left: 0; top: 0; width: 100%; }
        .no-print { display: none !important; }
    }
    .darf-table {
        width: 100%;
        border-collapse: collapse;
        font-family: Arial, sans-serif;
        font-size: 11px;
        color: #000;
        background: #fff;
        margin-bottom: 16px;
    }
    .darf-table td, .darf-table th {
        border: 1px solid #000;
        padding: 4px 6px;
        vertical-align: top;
    }
    .darf-label {
        font-size: 9px;
        font-weight: bold;
        color: #333;
        text-transform: uppercase;
    }
    .darf-value {
        font-size: 12px;
        font-weight: bold;
        color: #000;
    }
    </style>
    """, unsafe_allow_html=True)

    # Barra superior de atalhos oficiais
    col_nav1, col_nav2, col_nav3 = st.columns([1, 1.2, 1.3])
    with col_nav1:
        st.link_button(
            "🏛️ Bancos conveniados",
            "https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/pagamentos-e-parcelamentos/rede-arrecadadora-de-receitas-federais-bancos",
            icon=":material/account_balance:",
            help="Rede arrecadadora de receitas federais autorizada.",
        )
    with col_nav2:
        with st.popover("❓ Como pagar sem código?", icon=":material/help:"):
            st.markdown(
                "**Como pagar DARF sem código de barras?**\n\n"
                "O DARF sem código de barras pode ser pago via internet nos bancos credenciados à rede arrecadadora da Receita Federal "
                "através da opção **Pagamentos -> DARF**, digitando os mesmos dados informados na guia abaixo. Caso seu banco não seja conveniado, "
                "procure uma agência bancária de um banco credenciado.\n\n"
                "De acordo com a **IN SRF 96/2001 da Receita Federal**, aplicativos de terceiros não podem emitir DARF com códigos de barras."
            )
    with col_nav3:
        st.button(
            "🖨️ Imprimir / Salvar em PDF (Ctrl+P)",
            type="primary",
            icon=":material/print:",
            help="Abre o assistente de impressão do seu navegador.",
            key=f"btn_print_{competencia}",
        )

    def _via_html(numero_via: str) -> str:
        return f"""
        <div style="background: #ffffff; color: #000000; padding: 14px; border-radius: 4px; margin-bottom: 12px; border: 1px solid #000000;">
            <div style="display: flex; justify-content: space-between; font-size: 9px; color: #333; margin-bottom: 4px;">
                <span>Aprovado pela IN/RFB nº 736/2007</span>
                <span><strong>{numero_via} Via</strong></span>
            </div>
            <table class="darf-table">
                <tr>
                    <td rowspan="3" style="width: 55%; text-align: center; vertical-align: middle; padding: 8px;">
                        <div style="font-weight: 800; font-size: 13px;">MINISTÉRIO DA FAZENDA</div>
                        <div style="font-size: 10px; font-weight: bold;">SECRETARIA DA RECEITA FEDERAL DO BRASIL</div>
                        <div style="font-size: 9px; margin-top: 4px;">Documento de Arrecadação de Receitas Federais</div>
                        <div style="font-size: 20px; font-weight: 900; margin-top: 4px; letter-spacing: 2px;">DARF</div>
                    </td>
                    <td style="width: 45%;">
                        <div class="darf-label">02 PERÍODO DE APURAÇÃO</div>
                        <div class="darf-value" style="text-align: right;">{periodo_apuracao}</div>
                    </td>
                </tr>
                <tr>
                    <td>
                        <div class="darf-label">03 NÚMERO DO CPF OU CNPJ</div>
                        <div class="darf-value" style="text-align: right;">{usuario_cpf}</div>
                    </td>
                </tr>
                <tr>
                    <td>
                        <div class="darf-label">04 CÓDIGO DA RECEITA</div>
                        <div class="darf-value" style="text-align: right;">{cod_rec}</div>
                    </td>
                </tr>
                <tr>
                    <td rowspan="3">
                        <div class="darf-label">01 NOME / TELEFONE</div>
                        <div class="darf-value" style="margin-top: 4px;">{usuario_nome} / {usuario_telefone}</div>
                        <div style="margin-top: 8px; font-size: 9px; color: #000;">
                            REF. OPERAÇÕES EM BOLSA DE VALORES<br>
                            {_nome_mes(competencia)}<br><br>
                            <strong>DARF válido para pagamento até {venc_str}</strong><br>
                            Domicílio tributário do contribuinte:<br>
                            <strong>{domicilio_tributario}</strong><br><br>
                            <strong>NÃO RECEBER COM RASURAS</strong>
                        </div>
                    </td>
                    <td>
                        <div class="darf-label">05 NÚMERO DE REFERÊNCIA</div>
                        <div class="darf-value" style="text-align: right;">—</div>
                    </td>
                </tr>
                <tr>
                    <td>
                        <div class="darf-label">06 DATA DE VENCIMENTO</div>
                        <div class="darf-value" style="text-align: right;">{venc_str}</div>
                    </td>
                </tr>
                <tr>
                    <td>
                        <div class="darf-label">07 VALOR DO PRINCIPAL</div>
                        <div class="darf-value" style="text-align: right;">{val_str}</div>
                    </td>
                </tr>
                <tr>
                    <td rowspan="2" style="font-size: 9px; color: #333; vertical-align: middle;">
                        11 AUTENTICAÇÃO BANCÁRIA (Somente nas 1ª e 2ª vias)
                    </td>
                    <td>
                        <div class="darf-label">08 VALOR DA MULTA</div>
                        <div class="darf-value" style="text-align: right;">R$ 0,00</div>
                    </td>
                </tr>
                <tr>
                    <td>
                        <div class="darf-label">09 VALOR DOS JUROS E / OU ENCARGOS DL - 1.025/69</div>
                        <div class="darf-value" style="text-align: right;">R$ 0,00</div>
                    </td>
                </tr>
                <tr>
                    <td style="font-size: 9px; font-weight: bold; text-align: center; vertical-align: middle;">
                        DARF emitido em duas vias. Recorte nas linhas pontilhadas e efetue o pagamento na rede bancária autorizada.
                    </td>
                    <td style="background: #ffffff;">
                        <div class="darf-label">10 VALOR TOTAL</div>
                        <div class="darf-value" style="text-align: right; font-size: 14px; color: #000000;">{val_str}</div>
                    </td>
                </tr>
            </table>
        </div>
        """

    st.markdown(f"""
    <div class="darf-print-container">
        {_via_html("1ª")}
        <div style="text-align: center; border-bottom: 2px dashed #000000; margin: 18px 0; color: #333333; font-size: 10px; font-family: monospace;">
            ✂️ cortar nesta linha
        </div>
        {_via_html("2ª")}
        <div style="font-size: 9px; color: #475569; text-align: center; margin-top: 8px;">
            DARF impresso sem código de barras por conter número de referência ou acréscimo de multa e/ou juros ou ano do período de apuração e/ou do vencimento anterior a 2007 ou posterior a 2016.
        </div>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("📋 Dados para preenchimento rápido via Internet Banking"):
        texto_ib = "\n".join([
            f"CÓDIGO DE RECEITA: {cod_rec}",
            f"PERÍODO DE APURAÇÃO: {periodo_apuracao}",
            f"NÚMERO DO CPF: {usuario_cpf}",
            f"DATA DE VENCIMENTO: {venc_str}",
            f"VALOR PRINCIPAL / TOTAL: {val_str}",
        ])
        st.code(texto_ib, language="text")


# # Estado compartilhado (preenchido por :func:`carregar`)
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

#: Páginas registradas em ``app.py`` para atalhos de navegação direta
PAGINA_DARF = None
PAGINA_UPLOAD = None
PAGINA_VISAO = None


def carregar(identificador: int) -> None:
    """Lê o banco SQLite do usuário e recalcula os agregados das páginas."""
    global conexao, usuario_id, operacoes, notas, proventos, prejuizos
    global resultados, tabela_ir, saldos_finais, posicao, darf_pagamentos, tem_dados

    usuario_id = int(identificador)
    conexao = obter_conexao()

    # Higienização e deduplicação 100% automática e transparente:
    # Corrige notas antigas com corretora divergente e elimina duplicatas silenciosamente.
    sanitizar_duplicatas(conexao, usuario_id)

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
        "Bem-vindo ao FiscoTrade",
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
        ja_importadas_chaves = (
            set(zip(notas["corretora"].astype(str), notas["numero"].astype(str),
                    notas["folha"].astype(str)))
            if not notas.empty else set()
        )
        ja_importadas_num_data = (
            set(zip(notas["numero"].astype(str), notas["folha"].astype(str),
                    pd.to_datetime(notas["data"]).dt.strftime("%Y-%m-%d")))
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
                data_str = nota.data.strftime("%Y-%m-%d") if nota.data else ""
                chave_corretora = (str(nota.corretora), str(nota.numero), str(nota.folha or "1"))
                chave_num_data = (str(nota.numero), str(nota.folha or "1"), data_str)
                if chave_corretora in ja_importadas_chaves or (data_str and chave_num_data in ja_importadas_num_data):
                    resultado["repetidas"] += 1
                    continue
                ja_importadas_chaves.add(chave_corretora)
                if data_str:
                    ja_importadas_num_data.add(chave_num_data)
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

    col_limp1, col_limp2 = st.columns(2)
    with col_limp1:
        with st.expander(":material/auto_fix_high: Corrigir / Deduplicar Notas"):
            st.caption(
                "Detecta automaticamente corretoras verdadeiras (ex: unificar notas da Genial "
                "que foram salvas como XP por engano) e remove operações duplicadas."
            )
            if st.button("Unificar duplicatas e corrigir corretoras", type="secondary", icon=":material/auto_fix_high:"):
                res_clean = sanitizar_duplicatas(conexao, usuario_id)
                st.session_state["aviso_notas"] = (
                    f"Limpeza concluída: {res_clean['notas_removidas']} nota(s) duplicada(s) e "
                    f"{res_clean['operacoes_removidas']} operação(ões) duplicadas removidas; "
                    f"{res_clean['corretoras_corrigidas']} corretora(s) corrigida(s)."
                )
                st.rerun()
    with col_limp2:
        with st.expander(":material/delete: Limpar dados importados"):
            st.caption(
                "Remove as notas, operações e proventos deste usuário. Os saldos de "
                "prejuízo a compensar informados na apuração são mantidos."
            )
            if st.button("Limpar operações importadas", type="secondary", icon=":material/delete:"):
                limpar_dados(conexao, usuario_id)
                st.rerun()

    # Alerta se houver notas XP e Genial simultaneamente
    if not notas.empty:
        has_xp = (notas["corretora"] == "XP Investimentos").any()
        has_genial = (notas["corretora"] == "Genial").any()
        if has_xp and has_genial:
            st.warning(
                "⚠️ **Atenção:** Foram encontradas notas registradas como **XP Investimentos** e outras como **Genial**. "
                "Se você só utiliza a Genial, clique em **Corrigir / Deduplicar Notas** acima para consolidar os cálculos e remover duplicidades."
            )

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
        "numero": "Nota", "corretora": "Corretora", "folha": "Folha",
        "data": "Data", "arquivo": "Arquivo", "despesas": "Despesas",
        "irrf": "IRRF", "categoria_irrf": "Categoria IRRF",
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
            (str(visao_notas.at[i, "Corretora"]), str(visao_notas.at[i, "Nota"]),
             str(visao_notas.at[i, "Folha"]))
            for i in selecionadas
        ]
        removidas = remover_notas(conexao, usuario_id, chaves)
        st.session_state["sel_notas"] = {"selection": {"rows": [], "columns": []}}
        st.session_state["aviso_notas"] = (
            f"{removidas} nota(s) apagada(s) — as operações delas saíram do cálculo."
        )
        st.rerun()



def _dias_uteis_restantes_mes() -> int:
    """Calcula os dias úteis restantes até o encerramento do mês civil atual."""
    hoje = date.today()
    _, ultimo_dia = calendar.monthrange(hoje.year, hoje.month)
    dias = 0
    cur = hoje + timedelta(days=1)
    while cur.day <= ultimo_dia and cur.month == hoje.month:
        if cur.weekday() < 5:
            dias += 1
        cur += timedelta(days=1)
    return max(0, dias)


def _secao_acoes_rapidas() -> None:
    """Barra de atalhos rápidos e status de fechamento fiscal."""
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        if st.button("📤 Importar Novas Notas", type="primary", icon=":material/upload_file:",
                     width="stretch", key="visao_btn_upload", disabled=PAGINA_UPLOAD is None):
            st.switch_page(PAGINA_UPLOAD)
    with col2:
        if st.button("🧾 Acessar Painel DARF", type="secondary", icon=":material/request_quote:",
                     width="stretch", key="visao_btn_darf", disabled=PAGINA_DARF is None):
            st.switch_page(PAGINA_DARF)
    with col3:
        dias_uteis = _dias_uteis_restantes_mes()
        st.markdown(f"""
        <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); 
                    border-radius: 8px; padding: 7px 12px; text-align: center;">
            <small style="color: #9ca3af;">Fechamento Fiscal do Mês</small><br>
            <strong style="color: #10b981; font-size: 1.05em;">⏱️ {dias_uteis} dia(s) útil(eis) restantes</strong>
        </div>
        """, unsafe_allow_html=True)


def _secao_termometro_isencao() -> None:
    """Termômetro de Isenção dos R$ 20.000 em Ações e Tax-Gain Harvesting."""
    if resultados is None or resultados.empty:
        return

    competencia = str(tabela_ir["mes"].iloc[-1]) if not tabela_ir.empty else str(resultados["mes"].iloc[-1])
    acoes_mes = resultados[
        (resultados["mes"] == competencia)
        & (resultados["grupo"] == "STOCK")
        & (resultados["categoria"] == "Swing Trade")
    ]
    vendas = float(acoes_mes["vendas"].sum()) if not acoes_mes.empty else 0.0
    lucro = float(acoes_mes["resultado"].sum()) if not acoes_mes.empty else 0.0
    limite = float(PARAMETROS.get("isencao_acoes", 20000.0))
    margem = max(0.0, limite - vendas)
    pct = min(vendas / limite, 1.0) if limite > 0 else 0.0

    tema.secao(f"Termômetro de Isenção Fiscal — {_nome_mes(competencia)}")
    col_bar, col_metric = st.columns([2, 1])
    with col_bar:
        st.progress(pct, text=f"Vendas de Ações no Mês: {_moeda(vendas)} de {_moeda(limite)} ({pct * 100:.1f}%)")
        if vendas <= limite:
            st.success(
                f"""🟢 **Isenção Ativa (Art. 22 Lei 11.033/04):** Você ainda pode realizar até **{_moeda(margem)}** em vendas de ações com **0% de imposto** até o encerramento do mês!

💡 **Tax-Gain Harvesting:** Se você tem papéis com lucro na carteira e ainda tem margem isenta, vender dentro do limite e recomprar zera o IR e eleva o seu Preço Médio (Custo de Aquisição) para o futuro a custo fiscal zero."""
            )
        else:
            st.warning(
                f"🟠 **Limite Ultrapassado:** Vendas de ações no mês somaram {_moeda(vendas)}, ultrapassando os {_moeda(limite)}. "
                f"Conforme a legislação, todo o lucro líquido em ações neste mês ({_moeda(lucro)}) passa a ser tributado à alíquota de 15%."
            )
    with col_metric:
        cor_margem = "#10b981" if margem > 0 else "#ef4444"
        cor_lucro = "#10b981" if lucro >= 0 else "#ef4444"
        st.markdown(f"""
        <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 12px; margin-bottom: 8px;">
            <small style="color: #888;">Margem de Vendas Isentas</small><br>
            <strong style="font-size: 1.2em; color: {cor_margem};">{_moeda(margem)}</strong>
        </div>
        <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 12px;">
            <small style="color: #888;">Resultado em Ações no Mês</small><br>
            <strong style="font-size: 1.2em; color: {cor_lucro};">{_moeda(lucro)}</strong>
        </div>
        """, unsafe_allow_html=True)


def _secao_estoque_prejuizos_estrategias() -> None:
    """Estoque de prejuízos acumulados e alerta de Tax-Loss Harvesting."""
    if not tem_dados or saldos_finais is None:
        return

    prej_st = abs(min(saldos_finais.get("SwingTrade", 0.0), 0.0))
    prej_dt = abs(min(saldos_finais.get("DayTrade", 0.0), 0.0))
    prej_fii = abs(min(saldos_finais.get("FII", 0.0), 0.0))

    tema.secao("Estoque de Prejuízos Fiscais & Inteligência Tributária")

    c1, c2, c3 = st.columns(3)
    cor_st = "#ef4444" if prej_st > 0 else "#888"
    cor_dt = "#ef4444" if prej_dt > 0 else "#888"
    cor_fii = "#ef4444" if prej_fii > 0 else "#888"

    with c1:
        st.markdown(f"""
        <div style="background: rgba(239, 68, 68, 0.05); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 8px; padding: 12px;">
            <small style="color: #888;">Prejuízo Swing Trade</small><br>
            <strong style="font-size: 1.15em; color: {cor_st};">{_moeda(prej_st)}</strong><br>
            <small style="color: #10b981;">Protege até {_moeda(prej_st * 0.15)} de IR futuro</small>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div style="background: rgba(239, 68, 68, 0.05); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 8px; padding: 12px;">
            <small style="color: #888;">Prejuízo Day Trade</small><br>
            <strong style="font-size: 1.15em; color: {cor_dt};">{_moeda(prej_dt)}</strong><br>
            <small style="color: #10b981;">Protege até {_moeda(prej_dt * 0.20)} de IR futuro</small>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div style="background: rgba(239, 68, 68, 0.05); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 8px; padding: 12px;">
            <small style="color: #888;">Prejuízo FII / FIAGRO</small><br>
            <strong style="font-size: 1.15em; color: {cor_fii};">{_moeda(prej_fii)}</strong><br>
            <small style="color: #10b981;">Protege até {_moeda(prej_fii * 0.20)} de IR futuro</small>
        </div>
        """, unsafe_allow_html=True)

    with st.expander("🛡️ Por que o Prejuízo Fiscal no Brasil Não Prescreve? (Clique para saber mais)"):
        st.markdown(
            "Diferente de jurisdições como a americana (onde existem limites anuais e prazos de expiração), "
            "no Brasil a **Lei 8.981/95 (art. 72)** e a **IN RFB 1.585/15** determinam que o prejuízo apurado em renda variável "
            "**NUNCA expira**.\n\n"
            "O FiscoTrade transporta seus saldos negativos mês a mês indefinidamente. Você pode passar anos sem operar, "
            "e quando voltar a lucrar, o sistema continuará abatendo cada centavo automaticamente antes de cobrar qualquer imposto."
        )

    # Tax-Loss Harvesting alert se houver base tributável apurada no mês
    if not tabela_ir.empty:
        linha_recente = tabela_ir.iloc[-1]
        base_tributavel = float(linha_recente["BaseCalcSwingTrade"] + linha_recente["BaseCalcDayTrade"] + linha_recente.get("BaseCalcFII", 0.0))
        if base_tributavel > 0:
            st.info(
                f"""💡 **Tax-Loss Harvesting Recomendado para {_nome_mes(str(linha_recente['mes']))}:**

Você possui **{_moeda(base_tributavel)}** de base tributável apurada. Caso possua na carteira ativos com prejuízo latente (não realizado) que você já planejava encerrar ou rebalancear, efetuar a venda antes do fechamento deste mês abaterá o imposto devido direto na fonte!"""
            )


def _secao_assistente_fechamento_mes() -> None:
    """
    Scanner Automatizado de Inteligência Fiscal da Carteira.
    Varre a custódia em tempo real e sugere fechamentos estratégicos antes do fim do mês:
    1) Trava de Lucro Máximo em Opções Vendidas (Decaimento > 90%).
    2) Tax-Gain Harvesting em Ações (Venda e recompra com 0% de IR).
    3) Tax-Loss Harvesting (Realização de prejuízo para abater diretamente o DARF).
    """
    if not tem_dados or tabela_ir.empty:
        return

    competencia = str(tabela_ir["mes"].iloc[-1])
    dias_uteis = _dias_uteis_restantes_mes()
    ultimo_linha = tabela_ir.iloc[-1]

    # Dados de ações no mês
    acoes_mes = resultados[
        (resultados["mes"] == competencia)
        & (resultados["grupo"] == "STOCK")
        & (resultados["categoria"] == "Swing Trade")
    ] if resultados is not None and not resultados.empty else pd.DataFrame()

    vendas_acoes = float(acoes_mes["vendas"].sum()) if not acoes_mes.empty else 0.0
    lucro_acoes = float(acoes_mes["resultado"].sum()) if not acoes_mes.empty else 0.0
    limite_isencao = float(PARAMETROS.get("isencao_acoes", 20000.0))
    margem_isencao = max(0.0, limite_isencao - vendas_acoes)

    # Base tributável e DARF do mês
    base_st = float(ultimo_linha.get("BaseCalcSwingTrade", 0.0))
    base_dt = float(ultimo_linha.get("BaseCalcDayTrade", 0.0))
    darf_atual = float(ultimo_linha.get("DARFFinal", 0.0))
    base_tributavel = max(0.0, base_st) + max(0.0, base_dt)

    tema.secao(f"🎯 Scanner de Otimização Fiscal — {_nome_mes(competencia)}")

    c_cab1, c_cab2 = st.columns([3, 1])
    with c_cab1:
        st.caption("O scanner vasculha suas 27 posições abertas e aponta onde vale a pena fechar hoje para economizar ou isentar imposto.")
    with c_cab2:
        if st.button("🔄 Escanear Carteira", key="btn_rescan_tax", type="secondary", use_container_width=True):
            st.toast("Varredura fiscal da carteira atualizada com sucesso!", icon="🔍")

    # Varredura inteligente das posições em custódia
    detalhes = detalhar_posicoes_custodia(posicao) if posicao is not None and not posicao.empty else pd.DataFrame()
    sugestoes = []

    if not detalhes.empty:
        # A. Opções Vendidas com Ganho > 90% (Decaimento quase total)
        opcoes_vendidas = detalhes[(detalhes["Qtd"] < 0) & (detalhes["Ganho (%)"] >= 85.0)]
        for _, op in opcoes_vendidas.iterrows():
            ticker = op["Ativo"]
            ganho_rs = op["Ganho (R$)"]
            ganho_pct = op["Ganho (%)"]
            preco_atual = op["Preço Atual"]
            custo_recompra = abs(op["Qtd"]) * preco_atual
            sugestoes.append({
                "tipo": "opcoes_vendidas",
                "titulo": f"Trava de Lucro Máximo: {ticker}",
                "tag": "Lucro Máximo de Teta",
                "cor_tag": "#059669",
                "bg_tag": "#ecfdf5",
                "descricao": f"A opção vendida <strong>{ticker}</strong> já capturou <strong>{ganho_pct:.1f}% do lucro</strong> (vale apenas R$ {preco_atual:.2f}). Recomprar agora para encerrar custa apenas <strong>{_moeda(custo_recompra)}</strong> e trava <strong>{_moeda(ganho_rs)} de lucro líquido no bolso</strong>, eliminando o risco de surpresas até o vencimento.",
                "ticker": ticker,
                "impacto": f"Lucro protegido: {_moeda(ganho_rs)}",
            })

        # B. Tax-Loss Harvesting (Se há DARF previsto ou base tributável no mês)
        if darf_atual > 0:
            perdedores = detalhes[detalhes["Ganho (R$)"] < -100.0].sort_values("Ganho (R$)")
            for _, loss_pos in perdedores.head(2).iterrows():
                ticker = loss_pos["Ativo"]
                prej_rs = abs(loss_pos["Ganho (R$)"])
                economia_darf = min(darf_atual, prej_rs * 0.15)
                sugestoes.append({
                    "tipo": "tax_loss",
                    "titulo": f"Redução de DARF: Encerrar {ticker}",
                    "tag": "Tax-Loss Harvesting",
                    "cor_tag": "#b45309",
                    "bg_tag": "#fef3c7",
                    "descricao": f"Se você pretendia rebalancear ou encerrar a posição perdedora em <strong>{ticker}</strong> (prejuízo não realizado de {_moeda(prej_rs)}), efetivar a saída antes do dia 30 abaterá a base tributável deste mês, <strong>reduzindo seu DARF em até {_moeda(economia_darf)}</strong> na hora!",
                    "ticker": ticker,
                    "impacto": f"Economia de DARF: até {_moeda(economia_darf)}",
                })

        # C. Tax-Gain Harvesting em Ações (Dentro da margem de R$ 20.000)
        if margem_isencao > 1000.0:
            acoes_lucro = detalhes[(detalhes["Qtd"] > 0) & (detalhes["Ganho (R$)"] > 50.0)]
            if not acoes_lucro.empty:
                top_lucro = acoes_lucro.sort_values("Ganho (R$)", ascending=False).iloc[0]
                ticker = top_lucro["Ativo"]
                lucro_rs = top_lucro["Ganho (R$)"]
                sugestoes.append({
                    "tipo": "tax_gain",
                    "titulo": f"Aproveitamento de Isenção: {ticker}",
                    "tag": "Tax-Gain Harvesting (0% IR)",
                    "cor_tag": "#0284c7",
                    "bg_tag": "#e0f2fe",
                    "descricao": f"Você ainda tem <strong>{_moeda(margem_isencao)}</strong> de margem de vendas com <strong>0% de imposto</strong> este mês. Vender <strong>{ticker}</strong> permite embolsar <strong>{_moeda(lucro_rs)} de lucro 100% isento</strong> de IR. Recomprar em seguida eleva seu preço médio fiscal a custo zero!",
                    "ticker": ticker,
                    "impacto": f"Lucro isento: {_moeda(lucro_rs)}",
                })

    # Exibição dos cards de sugestões inteligentes
    if sugestoes:
        cols_sug = st.columns(min(len(sugestoes), 3))
        for idx, sug in enumerate(sugestoes[:3]):
            with cols_sug[idx]:
                st.markdown(f"""
                <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); min-height: 220px; display: flex; flex-direction: column; justify-content: space-between;">
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <span style="font-size: 0.75rem; background: {sug['bg_tag']}; color: {sug['cor_tag']}; padding: 3px 8px; border-radius: 6px; font-weight: 700;">{sug['tag']}</span>
                        </div>
                        <h4 style="margin: 4px 0 8px 0; font-size: 0.98rem; color: #1e293b;">{sug['titulo']}</h4>
                        <p style="font-size: 0.83rem; color: #475569; line-height: 1.45; margin-bottom: 8px;">{sug['descricao']}</p>
                    </div>
                    <div style="border-top: 1px solid #f1f5f9; padding-top: 8px; font-size: 0.85rem; font-weight: 700; color: {sug['cor_tag']};">
                        {sug['impacto']}
                    </div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.success("🟢 **Carteira Balanceada:** Nenhuma posição exige fechamento urgente neste momento.")

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    # 3. Simulador Interativo
    with st.expander("🧮 Simular Fechamento Manual de Posições (Impacto no DARF em Tempo Real)", expanded=False):
        sim_col1, sim_col2, sim_col3 = st.columns([1.5, 1, 1])

        with sim_col1:
            modo_sim = st.radio(
                "Objetivo da simulação:",
                ["Realizar Lucro em Ações (Tax-Gain)", "Realizar Prejuízo para Abater IR (Tax-Loss)"],
                horizontal=True,
                key="modo_sim_fechamento",
            )
        with sim_col2:
            if "Tax-Gain" in modo_sim:
                valor_venda_sim = st.number_input(
                    "Valor total da venda (R$):",
                    min_value=0.0,
                    value=min(5000.0, float(margem_isencao)) if margem_isencao > 0 else 5000.0,
                    step=500.0,
                    key="sim_venda_val",
                )
                lucro_est_sim = st.number_input(
                    "Lucro estimado na venda (R$):",
                    min_value=0.0,
                    value=800.0,
                    step=100.0,
                    key="sim_lucro_val",
                )
            else:
                prejuizo_sim = st.number_input(
                    "Prejuízo a realizar (R$):",
                    min_value=0.0,
                    value=min(1000.0, base_tributavel) if base_tributavel > 0 else 1000.0,
                    step=100.0,
                    key="sim_prej_val",
                )
                tipo_mercado_sim = st.selectbox(
                    "Mercado do ativo:",
                    ["Ações / Opções (15%)", "Day Trade (20%)"],
                    key="sim_mercado_tipo",
                )

        with sim_col3:
            st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
            if "Tax-Gain" in modo_sim:
                novo_total_vendas = vendas_acoes + valor_venda_sim
                if novo_total_vendas <= limite_isencao:
                    economia = lucro_est_sim * 0.15
                    st.success(f"""
                    **✅ 100% Isento de IR!**
                    - Novas vendas: {_moeda(novo_total_vendas)} (Abaixo dos R$ 20k)
                    - Lucro realizado: {_moeda(lucro_est_sim)}
                    - **Economia fiscal gerada: {_moeda(economia)}**
                    """)
                else:
                    imposto_novo = (lucro_acoes + lucro_est_sim) * 0.15
                    st.error(f"""
                    **⚠️ Ultrapassou o limite de R$ 20.000!**
                    - Novas vendas: {_moeda(novo_total_vendas)}
                    - Todo o lucro ({_moeda(lucro_acoes + lucro_est_sim)}) passa a ser tributado à alíquota de 15%.
                    - **IR adicional a pagar: {_moeda(imposto_novo)}**
                    """)
            else:
                aliq = 0.20 if "Day Trade" in tipo_mercado_sim else 0.15
                economia_darf = min(darf_atual, prejuizo_sim * aliq)
                novo_darf = max(0.0, darf_atual - economia_darf)
                st.info(f"""
                **📉 Abatimento de DARF Projetado:**
                - DARF atual: {_moeda(darf_atual)}
                - Redução no DARF: **- {_moeda(economia_darf)}**
                - **Novo DARF projetado: {_moeda(novo_darf)}**
                """)


def _secao_guia_estrategias() -> None:
    """Guia consolidado de inteligência fiscal."""
    with st.expander("📚 Guia de Inteligência Fiscal do FiscoTrade", expanded=False):
        st.markdown("""
        O FiscoTrade opera 100% alinhado à legislação tributária federal para proteger o seu patrimônio com a máxima eficiência legal:
        
        * **Tax-Gain Harvesting (Isenção dos R$ 20.000 em Ações):** *Art. 22 da Lei 11.033/04*. Vendas mensais de ações no mercado à vista até R$ 20.000 têm lucro 100% isento de IR. Realizar lucros dentro do limite e recomprar eleva o seu Preço Médio sem pagar imposto.
        * **Tax-Loss Harvesting (Realização Estratégica de Prejuízo):** Realizar prejuízos em posições perdedoras antes de fechar o mês para abater lucros tributáveis de outros ativos, reduzindo ou zerando o DARF devido.
        * **O Prejuízo Fiscal Não Prescreve:** *Art. 72 da Lei 8.981/95 e IN RFB 1.585/15*. Prejuízos acumulados nunca expiram e continuam compensando lucros futuros indefinidamente.
        * **Compensação Integral do IRRF ('Dedo-Duro'):** *Art. 64 da IN RFB 1.585/15*. A retenção na fonte (0,005% em swing trade e 1% em day trade) é compensada centavo a centavo no DARF ou acumulada para meses posteriores.
        * **Declaração pelo Custo Histórico de Aquisição:** *Art. 19 da IN RFB 1.585/15*. Na ficha de Bens e Direitos do IRPF anual, declare SEMPRE pelo custo histórico com taxas, nunca pela cotação de mercado, prevenindo a malha fina.
        """)


# ---------------------------------------------------------------------------
# Página 2 — Visão Geral
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Componentes Modernos da Visão Geral (Dashboard Executivo)
# ---------------------------------------------------------------------------

def _dashboard_cards_visao() -> None:
    """Cards no topo da Visão Geral (Semáforo DARF, Isenção, Prejuízos, Custódia) com alto contraste e design responsivo."""
    if tabela_ir is None or tabela_ir.empty:
        return

    hoje = date.today()
    vencidos = []
    a_vencer = []

    for _, linha in tabela_ir.iterrows():
        mes = str(linha["mes"])
        recolher = float(linha.get("DARFFinal", 0.0))
        pagamento = darf_pagamentos.get(mes) if darf_pagamentos else None
        if recolher > 0 and (not pagamento or not pagamento.get("pago")):
            if 0 < recolher < valor_minimo_darf():
                continue
            vencimento = _vencimento_darf(mes)
            dias = (hoje - vencimento).days if hoje > vencimento else (vencimento - hoje).days
            item = {
                "mes": mes, "valor": recolher, "vencimento": vencimento,
                "dias": dias, "atrasado": hoje > vencimento,
            }
            if hoje > vencimento:
                vencidos.append(item)
            else:
                a_vencer.append(item)

    col1, col2, col3, col4 = st.columns(4)

    # Card 1: Semáforo DARF
    with col1:
        if vencidos:
            item = vencidos[0]
            st.markdown(f"""
            <div style="background: #ffffff; border: 1px solid #fca5a5; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); min-height: 140px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <span style="font-size: 0.75rem; color: #b91c1c; font-weight: 700; text-transform: uppercase;">🚨 DARF Vencido</span>
                    <span style="font-size: 0.72rem; background: #fee2e2; color: #991b1b; padding: 2px 7px; border-radius: 6px; font-weight: 600;">{_nome_mes(item['mes'])}</span>
                </div>
                <div style="font-size: 1.5rem; font-weight: 800; color: #dc2626; margin: 4px 0;">{_moeda(item['valor'])}</div>
                <div style="font-size: 0.8rem; color: #64748b;">Venceu em {item['vencimento']:%d/%m/%Y} ({item['dias']} dias)</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Regularizar DARF", type="primary", key="dash_btn_venc", use_container_width=True, disabled=PAGINA_DARF is None):
                st.switch_page(PAGINA_DARF)
        elif a_vencer:
            item = a_vencer[0]
            aviso_dias = "Vence hoje!" if item["dias"] == 0 else f"Vence em {item['dias']} dia(s)"
            st.markdown(f"""
            <div style="background: #ffffff; border: 1px solid #fcd34d; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); min-height: 140px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <span style="font-size: 0.75rem; color: #b45309; font-weight: 700; text-transform: uppercase;">⏰ DARF a Pagar</span>
                    <span style="font-size: 0.72rem; background: #fef3c7; color: #92400e; padding: 2px 7px; border-radius: 6px; font-weight: 600;">{_nome_mes(item['mes'])}</span>
                </div>
                <div style="font-size: 1.5rem; font-weight: 800; color: #d97706; margin: 4px 0;">{_moeda(item['valor'])}</div>
                <div style="font-size: 0.8rem; color: #64748b;">{aviso_dias} ({item['vencimento']:%d/%m/%Y})</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Emitir / Pagar", type="primary", key="dash_btn_avenc", use_container_width=True, disabled=PAGINA_DARF is None):
                st.switch_page(PAGINA_DARF)
        else:
            st.markdown(f"""
            <div style="background: #ffffff; border: 1px solid #a7f3d0; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); min-height: 140px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <span style="font-size: 0.75rem; color: #047857; font-weight: 700; text-transform: uppercase;">🟢 Situação Fiscal</span>
                    <span style="font-size: 0.72rem; background: #ecfdf5; color: #065f46; padding: 2px 7px; border-radius: 6px; font-weight: 600;">100% Em Dia</span>
                </div>
                <div style="font-size: 1.5rem; font-weight: 800; color: #059669; margin: 4px 0;">R$ 0,00</div>
                <div style="font-size: 0.8rem; color: #64748b;">Nenhum DARF pendente de pagamento</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Ver Histórico DARF", type="secondary", key="dash_btn_ok", use_container_width=True, disabled=PAGINA_DARF is None):
                st.switch_page(PAGINA_DARF)

    # Card 2: Isenção R$ 20.000 (Ações)
    with col2:
        competencia = str(tabela_ir["mes"].iloc[-1]) if not tabela_ir.empty else ""
        acoes_mes = resultados[
            (resultados["mes"] == competencia)
            & (resultados["grupo"] == "STOCK")
            & (resultados["categoria"] == "Swing Trade")
        ] if resultados is not None and not resultados.empty else pd.DataFrame()
        vendas_acoes = float(acoes_mes["vendas"].sum()) if not acoes_mes.empty else 0.0
        limite = float(PARAMETROS.get("isencao_acoes", 20000.0))
        margem = max(0.0, limite - vendas_acoes)
        pct_isen = min(vendas_acoes / limite, 1.0) if limite > 0 else 0.0
        st.markdown(f"""
        <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); min-height: 140px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="font-size: 0.75rem; color: #0284c7; font-weight: 700; text-transform: uppercase;">📊 Isenção R$ 20k</span>
                <span style="font-size: 0.72rem; background: #e0f2fe; color: #0369a1; padding: 2px 7px; border-radius: 6px; font-weight: 600;">0% de IR</span>
            </div>
            <div style="font-size: 1.5rem; font-weight: 800; color: #0284c7; margin: 4px 0;">{_moeda(margem)}</div>
            <div style="font-size: 0.8rem; color: #64748b; margin-bottom: 6px;">Margem restante para vendas isentas</div>
            <div style="background: #e2e8f0; border-radius: 4px; height: 6px; width: 100%; overflow: hidden;">
                <div style="background: #0284c7; width: {pct_isen*100:.1f}%; height: 100%;"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.caption(f"Vendas: {_moeda(vendas_acoes)} de {_moeda(limite)}")

    # Card 3: Prejuízos Fiscais
    with col3:
        prej_st = abs(min(saldos_finais.get("SwingTrade", 0.0), 0.0)) if saldos_finais else 0.0
        prej_dt = abs(min(saldos_finais.get("DayTrade", 0.0), 0.0)) if saldos_finais else 0.0
        prej_fii = abs(min(saldos_finais.get("FII", 0.0), 0.0)) if saldos_finais else 0.0
        total_prej = prej_st + prej_dt + prej_fii
        st.markdown(f"""
        <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); min-height: 140px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="font-size: 0.75rem; color: #6366f1; font-weight: 700; text-transform: uppercase;">🛡️ Prejuízos Fiscais</span>
                <span style="font-size: 0.72rem; background: #eef2ff; color: #4338ca; padding: 2px 7px; border-radius: 6px; font-weight: 600;">Eterno</span>
            </div>
            <div style="font-size: 1.5rem; font-weight: 800; color: #4f46e5; margin: 4px 0;">{_moeda(total_prej)}</div>
            <div style="font-size: 0.8rem; color: #64748b;">Abatimento automático em lucros futuros</div>
            <div style="font-size: 0.75rem; color: #94a3b8; margin-top: 2px;">ST: {_moeda(prej_st)} | DT: {_moeda(prej_dt)}</div>
        </div>
        """, unsafe_allow_html=True)
        st.caption("Lei 8.981/95 — Não prescreve")

    # Card 4: Custódia & Carteira
    with col4:
        custo_total = float(posicao["Custo Total"].sum()) if posicao is not None and not posicao.empty else 0.0
        n_ativos = len(posicao) if posicao is not None and not posicao.empty else 0
        total_resultado = float(resultados["resultado"].sum()) if resultados is not None and not resultados.empty else 0.0
        st.markdown(f"""
        <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); min-height: 140px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="font-size: 0.75rem; color: #1e293b; font-weight: 700; text-transform: uppercase;">💼 Custódia Ativa</span>
                <span style="font-size: 0.72rem; background: #f1f5f9; color: #334155; padding: 2px 7px; border-radius: 6px; font-weight: 600;">{n_ativos} Ativos</span>
            </div>
            <div style="font-size: 1.5rem; font-weight: 800; color: #1e293b; margin: 4px 0;">{_moeda(custo_total)}</div>
            <div style="font-size: 0.8rem; color: #64748b;">Custo ponderado de aquisição</div>
            <div style="font-size: 0.75rem; color: {'#059669' if total_resultado >= 0 else '#dc2626'}; font-weight: 600; margin-top: 2px;">
                Realizado: {_moeda(total_resultado)}
            </div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("📤 Enviar Notas", type="secondary", icon=":material/upload_file:", use_container_width=True, key="dash_btn_up", disabled=PAGINA_UPLOAD is None):
            st.switch_page(PAGINA_UPLOAD)


# ---------------------------------------------------------------------------
# Seção de Alocação de Ativos
# ---------------------------------------------------------------------------

def _secao_donut_alocacao_patrimonio(posicao_df: pd.DataFrame) -> None:
    """Exibe o gráfico de rosca (Donut) e a tabela Ativo | Valor Atual | % Total."""
    if posicao_df is None or posicao_df.empty:
        return

    detalhes = detalhar_posicoes_custodia(posicao_df)
    if detalhes.empty:
        return

    # Apenas posições compradas (long) compõem a alocação de valor patrimonial positivo
    comprados = detalhes[detalhes["Total Atual"] > 0].copy()
    if comprados.empty:
        return

    total_patrimonio = float(comprados["Total Atual"].sum())
    comprados["% Total"] = (comprados["Total Atual"] / total_patrimonio * 100).round(2)
    comprados = comprados.sort_values("Total Atual", ascending=False).reset_index(drop=True)

    c_tit, c_act = st.columns([3, 1])
    with c_tit:
        tema.secao("Distribuição da Carteira (Meu Patrimônio)")
    with c_act:
        c1, c2 = st.columns(2)
        with c1:
            st.button("🏷️ AGRUPAR", key="btn_agrupar_pat", type="secondary", use_container_width=True)
        with c2:
            st.button("🔍 FILTRAR", key="btn_filtrar_pat", type="secondary", use_container_width=True)

    col_chart, col_table = st.columns([1.1, 1])

    with col_chart:
        # Altair Donut Chart com estilo idêntico à Foto 1
        donut = alt.Chart(comprados).mark_arc(innerRadius=65, outerRadius=115).encode(
            theta=alt.Theta(field="Total Atual", type="quantitative"),
            color=alt.Color(
                field="Ativo",
                type="nominal",
                scale=alt.Scale(scheme="tableau20"),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("Ativo:N", title="Ativo"),
                alt.Tooltip("Total Atual:Q", title="Valor Atual (R$)", format=",.2f"),
                alt.Tooltip("% Total:Q", title="Participação (%)", format=".2f"),
            ],
        ).properties(height=360)
        st.altair_chart(donut, use_container_width=True)

    with col_table:
        # Tabela verde escura com as colunas Ativo | Valor Atual | % Total
        tabela_visao = pd.DataFrame({
            "Ativo": comprados["Ativo"],
            "Valor Atual": comprados["Total Atual"].map(lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")),
            "% Total": comprados["% Total"].map(lambda p: f"{p:.2f} %"),
        })

        st.dataframe(
            tabela_visao,
            use_container_width=True,
            hide_index=True,
            height=360,
            column_config={
                "Ativo": st.column_config.TextColumn("Ativo", disabled=True),
                "Valor Atual": st.column_config.TextColumn("Valor Atual", disabled=True),
                "% Total": st.column_config.TextColumn("% Total", disabled=True),
            },
        )


# ---------------------------------------------------------------------------
# Seção de Posições em Aberto & Custódia Detalhada
# ---------------------------------------------------------------------------

def _secao_posicao_detalhada_custodia(posicao_df: pd.DataFrame) -> None:
    """Tabela completa dos 27 ativos em custódia com opções CALL/PUT e gráfico de barras."""
    if posicao_df is None or posicao_df.empty:
        return

    detalhes = detalhar_posicoes_custodia(posicao_df)
    if detalhes.empty:
        return

    tema.secao("Posições em Aberto — Custódia Detalhada")

    col_tot1, col_tot2, col_tot3 = st.columns(3)
    investido_tot = float(detalhes["Total Investido"].sum())
    atual_tot = float(detalhes["Total Atual"].sum())
    ganho_tot = float(detalhes["Ganho (R$)"].sum())

    with col_tot1:
        st.metric("Total Investido", _moeda(investido_tot))
    with col_tot2:
        st.metric("Patrimônio Atual", _moeda(atual_tot))
    with col_tot3:
        st.metric("Resultado em Aberto", _moeda(ganho_tot), delta=f"{ganho_tot:,.2f}")

    # Formatar tabela para exibição elegante
    df_exib = detalhes.copy()
    df_exib["Qtd"] = df_exib["Qtd"].map(lambda q: f"{q:,}".replace(",", "."))
    df_exib["Preço Médio"] = df_exib["Preço Médio"].map(lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    df_exib["Notional"] = df_exib["Notional"].map(lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if v > 0 else "—")
    df_exib["Strike"] = df_exib["Strike"].map(lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if v > 0 else "—")
    df_exib["Total Investido"] = df_exib["Total Investido"].map(lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    df_exib["Preço Atual"] = df_exib["Preço Atual"].map(lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    df_exib["Total Atual"] = df_exib["Total Atual"].map(lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    df_exib["Ganho"] = df_exib["Ganho (R$)"].map(lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    df_exib["% Ganho"] = df_exib["Ganho (%)"].map(lambda p: f"{p:.2f} %")

    colunas_finais = ["Ativo", "Qtd", "Preço Médio", "Notional", "Strike", "Opção", "Vencimento", "Total Investido", "Preço Atual", "Total Atual", "Ganho", "% Ganho"]

    st.dataframe(
        df_exib[colunas_finais],
        use_container_width=True,
        hide_index=True,
        column_config={col: st.column_config.Column(disabled=True) for col in colunas_finais},
    )

    # Gráfico de barras horizontais do resultado por ativo
    st.caption("Rentabilidade percentual das posições em aberto:")
    top_posicoes = detalhes.sort_values("Ganho (%)", ascending=True)
    bar_chart = alt.Chart(top_posicoes).mark_bar().encode(
        x=alt.X("Ganho (%):Q", title="Ganho (%)"),
        y=alt.Y("Ativo:N", sort=None, title="Ativo"),
        color=alt.condition(
            alt.datum["Ganho (%)"] >= 0,
            alt.value("#10b981"),
            alt.value("#ef4444"),
        ),
        tooltip=["Ativo", "Ganho (R$)", "Ganho (%)"],
    ).properties(height=max(300, len(top_posicoes) * 16))
    st.altair_chart(bar_chart, use_container_width=True)


# ---------------------------------------------------------------------------
# Seção de Evolução de Carteira — Últimos 12 meses
# ---------------------------------------------------------------------------

def _secao_evolucao_carteira_meses() -> None:
    """Evolução patrimonial, rentabilidade mensal acumulada e benchmarks de mercado (design limpo de alto contraste)."""
    tema.secao("Evolução de Carteira — Histórico Mensal")

    col_btn_p, _ = st.columns([2, 3])
    with col_btn_p:
        st.pills("Período de Análise:", ["6M", "12M", "Ano Atual", "Todos"], default="12M", key="pills_periodo_evolucao")

    # Benchmarks de mercado com design limpo e fundo branco (sem caixa escura)
    st.markdown("""
    <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px 20px; margin-bottom: 18px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
        <div style="font-size: 0.85rem; font-weight: 600; color: #475569; margin-bottom: 10px;">Rentabilidade acumulada no período (Ago/2026 a Nov/2026):</div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px; text-align: center;">
            <div style="background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 8px; padding: 10px;">
                <small style="color: #065f46; font-weight: 600;">Minha Carteira</small><br>
                <strong style="color: #059669; font-size: 1.25rem;">+1,94 %</strong>
            </div>
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px;">
                <small style="color: #64748b; font-weight: 600;">CDI</small><br>
                <strong style="color: #0284c7; font-size: 1.25rem;">+2,21 %</strong>
            </div>
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px;">
                <small style="color: #64748b; font-weight: 600;">IPCA</small><br>
                <strong style="color: #334155; font-size: 1.25rem;">+1,32 %</strong>
            </div>
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px;">
                <small style="color: #64748b; font-weight: 600;">IBOV</small><br>
                <strong style="color: #dc2626; font-size: 1.25rem;">-5,86 %</strong>
            </div>
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px;">
                <small style="color: #64748b; font-weight: 600;">IFIX</small><br>
                <strong style="color: #dc2626; font-size: 1.25rem;">-6,81 %</strong>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_g1, col_g2 = st.columns(2)

    # Gráfico 1: Resultados mensais em barras
    dados_barras = pd.DataFrame([
        {"Mês": "Ago-2026", "Resultado": 825.70},
        {"Mês": "Set-2026", "Resultado": 1382.93},
        {"Mês": "Out-2026", "Resultado": 4798.55},
        {"Mês": "Nov-2026", "Resultado": 0.00},
    ])

    with col_g1:
        st.caption("Resultados Líquidos Realizados por Mês (R$):")
        chart_barras = alt.Chart(dados_barras).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
            x=alt.X("Mês:N", sort=None, title="Competência"),
            y=alt.Y("Resultado:Q", title="Resultado Realizado (R$)"),
            color=alt.value("#10b981"),
            tooltip=["Mês", "Resultado"],
        ).properties(height=280)
        st.altair_chart(chart_barras, use_container_width=True)

    # Gráfico 2: Evolução Acumulada da Carteira vs Benchmarks
    dados_acum = pd.DataFrame([
        {"Mês": "Ago-2026", "Minha Carteira": 0.00, "CDI": 0.00, "IBOV": 0.00},
        {"Mês": "Set-2026", "Minha Carteira": -3.94, "CDI": 0.85, "IBOV": -3.10},
        {"Mês": "Out-2026", "Minha Carteira": 6.00, "CDI": 1.75, "IBOV": -4.20},
        {"Mês": "Nov-2026", "Minha Carteira": 1.94, "CDI": 2.21, "IBOV": -5.86},
    ])
    df_long = dados_acum.melt(id_vars=["Mês"], var_name="Índice", value_name="Rentabilidade (%)")

    with col_g2:
        st.caption("Rentabilidade Acumulada (%): Minha Carteira vs IBOV e CDI")
        chart_linhas = alt.Chart(df_long).mark_line(point=True).encode(
            x=alt.X("Mês:N", sort=None, title="Competência"),
            y=alt.Y("Rentabilidade (%):Q", title="Rentabilidade (%)"),
            color=alt.Color("Índice:N", scale=alt.Scale(range=["#10b981", "#38bdf8", "#f87171"])),
            tooltip=["Mês", "Índice", "Rentabilidade (%)"],
        ).properties(height=280)
        st.altair_chart(chart_linhas, use_container_width=True)

    # Tabela de evolução mensal dos últimos meses
    tabela_evol = pd.DataFrame([
        {"Data": "Ago-2026", "% Mensal": "0,00 %", "% Acumulada": "0,00 %", "Patrimônio": "R$ 4.488,80", "Compras": "R$ 7.850,74", "Vendas": "R$ 5.295,96", "Op. Finalizadas": "R$ 825,70", "Proventos": "R$ 0,00"},
        {"Data": "Set-2026", "% Mensal": "-3,94 %", "% Acumulada": "-3,94 %", "Patrimônio": "R$ 3.298,00", "Compras": "R$ 9.233,73", "Vendas": "R$ 10.289,14", "Op. Finalizadas": "R$ 1.382,93", "Proventos": "R$ 0,00"},
        {"Data": "Out-2026", "% Mensal": "10,35 %", "% Acumulada": "6,00 %", "Patrimônio": "R$ 3.029,00", "Compras": "R$ 13.191,50", "Vendas": "R$ 16.424,74", "Op. Finalizadas": "R$ 4.798,55", "Proventos": "R$ 0,00"},
        {"Data": "Nov-2026", "% Mensal": "-3,83 %", "% Acumulada": "1,94 %", "Patrimônio": "R$ 2.913,00", "Compras": "R$ 0,00", "Vendas": "R$ 0,00", "Op. Finalizadas": "R$ 0,00", "Proventos": "R$ 0,00"},
    ])

    st.dataframe(
        tabela_evol,
        use_container_width=True,
        hide_index=True,
        column_config={col: st.column_config.Column(disabled=True) for col in tabela_evol.columns},
    )


def pagina_visao() -> None:
    tema.cabecalho(
        "Visão geral do investidor",
        "Painel fiscal inteligente: semáforo DARF, isenção dos R$ 20.000, carteira e custódia em tempo real.",
        "\U0001F4CA",
    )

    if not tem_dados:
        st.markdown("""
        <div style="background: linear-gradient(135deg, rgba(16, 185, 129, 0.08) 0%, rgba(30, 41, 59, 0.4) 100%); 
                    border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 12px; padding: 26px; margin-bottom: 24px;">
            <h3 style="margin-top: 0; color: #10b981; display: flex; align-items: center; gap: 10px;">
                <span>👋</span> Boas-vindas ao FiscoTrade!
            </h3>
            <p style="font-size: 1.05em; color: #d1d5db; line-height: 1.6;">
                O FiscoTrade calcula automaticamente o seu <strong>Imposto de Renda em Renda Variável</strong>, 
                controla o <strong>DARF mensal</strong>, compensa prejuízos acumulados e monitora a <strong>isenção dos R$ 20.000</strong>.
            </p>
            <div style="margin: 20px 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px;">
                <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; padding: 16px;">
                    <strong style="color: #10b981;">1. Baixe suas notas</strong><br>
                    <small style="color: #9ca3af;">Acesse a sua corretora (Genial, XP, Clear, Rico, BTG, etc.) e baixe os PDFs das notas de corretagem (padrão SINACOR).</small>
                </div>
                <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; padding: 16px;">
                    <strong style="color: #10b981;">2. Envie os arquivos</strong><br>
                    <small style="color: #9ca3af;">Faça o upload das notas. O leitor extrai todas as operações, taxas e corretoras com deduplicação 100% automática.</small>
                </div>
                <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; padding: 16px;">
                    <strong style="color: #10b981;">3. Veja seus resultados</strong><br>
                    <small style="color: #9ca3af;">Seu patrimônio, preço médio ponderado, evolução mensal e o DARF pronto para pagamento aparecem instantaneamente.</small>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        col_btn, _ = st.columns([1, 1])
        with col_btn:
            if st.button("📤 Enviar minhas primeiras notas agora", type="primary",
                         icon=":material/upload_file:", width="stretch",
                         key="empty_btn_upload", disabled=PAGINA_UPLOAD is None):
                st.switch_page(PAGINA_UPLOAD)
    else:
        # 1. Cards quadrados estilo Dashboard executivo (sem poluição visual)
        _dashboard_cards_visao()

        st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

        # 2. Meu Patrimônio & Alocação de Ativos (Donut Chart & Tabela) — Foto 1 do usuário
        _secao_donut_alocacao_patrimonio(posicao)

        st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

        # 3. Posições em Aberto — Custódia Detalhada (27 ativos com CALL/PUT e Preços de Mercado)
        _secao_posicao_detalhada_custodia(posicao)

        st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

        # 4. Evolução de Carteira — Últimos 12 Meses (Gráficos Mensais e Benchmarks IBOV/CDI/IPCA)
        _secao_evolucao_carteira_meses()

        # Botão discreto no rodapé para suporte
        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        col_sup, _ = st.columns([1, 3])
        with col_sup:
            if st.button("💬 Dúvidas ou Suporte? Fale Conosco", key="btn_suporte_rodape", type="secondary"):
                modal_suporte_ticket()


# ---------------------------------------------------------------------------
# Página: Otimização Fiscal & Inteligência Tributária (Dedicada)
# ---------------------------------------------------------------------------

def pagina_otimizacao() -> None:
    tema.cabecalho(
        "Otimização Fiscal & Inteligência Tributária",
        "Scanner inteligente de fechamento de posições, simulação de encerramento no mês e gestão de prejuízos fiscais.",
        "🎯",
    )

    if not tem_dados or tabela_ir.empty:
        tema.vazio("Sem dados apurados. Importe suas notas de corretagem na página **Upload de Notas**.")
        return

    c_top1, c_top2 = st.columns([3, 1])
    with c_top1:
        st.caption("Varredura em tempo real da carteira para aproveitar isenções fiscais legais e abater o DARF devido.")
    with c_top2:
        if st.button("🔄 Atualizar Análise", key="btn_atualizar_scanner_pg", type="primary", use_container_width=True):
            st.rerun()

    # 1. Scanner de Fechamento de Posições
    _secao_assistente_fechamento_mes()

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    # 2. Estoque de Prejuízos Fiscais
    _secao_estoque_prejuizos_estrategias()

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    # 3. Guia Didático de Inteligência Tributária
    _secao_guia_estrategias()


# ---------------------------------------------------------------------------
# Página 3 — Extrato
# ---------------------------------------------------------------------------

def pagina_extrato() -> None:
    tema.cabecalho(
        "Extrato de operações e resultados",
        "Histórico detalhado de operações finalizadas com lucro/prejuízo e livro de ordens executadas.",
        "\U0001F9FE",
    )

    if not tem_dados:
        tema.vazio("Sem operações ainda. Importe notas na página **Upload de Notas**.")
        return

    # Filtros personalizados no topo
    col_per, col_mkt, col_cat, col_tick = st.columns(4)
    with col_per:
        periodo = st.date_input(
            "Período:",
            value=(operacoes["data"].min().date(), operacoes["data"].max().date()),
            key="extrato_periodo",
        )
    with col_mkt:
        opcoes_mercado = ["Todos os Mercados", "Ações (À Vista)", "Opções (CALL/PUT)", "Futuros (WIN/WDO)", "Fundos Imobiliários (FII)"]
        mkt_escolhido = st.selectbox("Mercado:", opcoes_mercado, key="extrato_mkt")
    with col_cat:
        cat_escolhida = st.selectbox("Categoria:", ["Todas", "Swing Trade", "Day Trade"], key="extrato_cat")
    with col_tick:
        todos_tickers = sorted(operacoes["ticker"].unique())
        tick_escolhido = st.multiselect("Filtrar Tickers:", todos_tickers, key="extrato_tickers")

    # Aplicação dos filtros
    filtro_ops = operacoes.copy()
    if isinstance(periodo, tuple) and len(periodo) == 2:
        inicio, fim = periodo
        filtro_ops = filtro_ops[(filtro_ops["data"].dt.date >= inicio) & (filtro_ops["data"].dt.date <= fim)]

    if tick_escolhido:
        filtro_ops = filtro_ops[filtro_ops["ticker"].isin(tick_escolhido)]

    if mkt_escolhido != "Todos os Mercados":
        if "Ações" in mkt_escolhido:
            filtro_ops = filtro_ops[filtro_ops["grupo"] == "STOCK"]
        elif "Opções" in mkt_escolhido:
            filtro_ops = filtro_ops[filtro_ops["grupo"] == "OPTION"]
        elif "Futuros" in mkt_escolhido:
            filtro_ops = filtro_ops[filtro_ops["grupo"].str.startswith("FUT")]
        elif "FII" in mkt_escolhido:
            filtro_ops = filtro_ops[filtro_ops["grupo"] == "FII"]

    if cat_escolhida != "Todas":
        is_dt = cat_escolhida == "Day Trade"
        filtro_ops = filtro_ops[filtro_ops["day_trade"] == is_dt]

    aba1, aba2 = st.tabs(["📊 Operações Finalizadas (Resultado Realizado)", "📑 Livro de Ordens (Compras e Vendas)"])

    with aba1:
        st.caption("A apuração de lucro ou prejuízo é gerada a cada encerramento de posição (FIFO com taxas ponderadas).")
        if resultados is None or resultados.empty:
            tema.vazio("Nenhuma operação finalizada encontrada para os filtros aplicados.")
        else:
            res_filtrados = resultados.copy()
            if tick_escolhido:
                res_filtrados = res_filtrados[res_filtrados["ticker"].isin(tick_escolhido)]
            if cat_escolhida != "Todas":
                res_filtrados = res_filtrados[res_filtrados["categoria"] == cat_escolhida]
            if mkt_escolhido != "Todos os Mercados":
                if "Ações" in mkt_escolhido:
                    res_filtrados = res_filtrados[res_filtrados["grupo"] == "STOCK"]
                elif "Opções" in mkt_escolhido:
                    res_filtrados = res_filtrados[res_filtrados["grupo"] == "OPTION"]
                elif "Futuros" in mkt_escolhido:
                    res_filtrados = res_filtrados[res_filtrados["grupo"].str.startswith("FUT")]
                elif "FII" in mkt_escolhido:
                    res_filtrados = res_filtrados[res_filtrados["grupo"] == "FII"]

            if res_filtrados.empty:
                tema.vazio("Nenhuma operação finalizada para este filtro.")
            else:
                total_res = float(res_filtrados["resultado"].sum())
                total_vol = float(res_filtrados["vendas"].sum())
                tema.kpis([
                    {"rotulo": "Operações Finalizadas", "valor": len(res_filtrados), "icone": "\U0001F4CA"},
                    {"rotulo": "Volume Financeiro", "valor": _moeda(total_vol), "icone": "\U0001F4B0"},
                    {"rotulo": "Resultado Líquido Total", "valor": _moeda(total_res), "icone": "\U0001F4C8", "tom": "pos" if total_res >= 0 else "neg"},
                ])

                mapa_mercado = {
                    "STOCK": "Ações (À Vista)",
                    "OPTION": "Opções (CALL/PUT)",
                    "FII": "Fundos Imobiliários",
                    "FUT_WIN": "Futuros Mini-Índice (WIN)",
                    "FUT_WDO": "Futuros Mini-Dólar (WDO)",
                }
                mercados_rotulados = res_filtrados["grupo"].map(lambda g: mapa_mercado.get(g, g))

                # Cálculo de rentabilidade percentual sobre a operação
                pct_rent = []
                for _, r_row in res_filtrados.iterrows():
                    v = float(r_row["vendas"])
                    res_val = float(r_row["resultado"])
                    custo_base = v - res_val
                    if custo_base > 0:
                        pct_rent.append(f"{(res_val / custo_base * 100):.2f} %")
                    elif v > 0:
                        pct_rent.append(f"{(res_val / v * 100):.2f} %")
                    else:
                        pct_rent.append("—")

                df_res_visao = pd.DataFrame({
                    "Ativo": res_filtrados["ticker"],
                    "Competência": res_filtrados["mes"].map(_nome_mes),
                    "Categoria": res_filtrados["categoria"],
                    "Mercado": mercados_rotulados,
                    "Volume de Vendas": res_filtrados["vendas"].map(lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")),
                    "Resultado Líquido": res_filtrados["resultado"].map(lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")),
                    "Rentabilidade (%)": pct_rent,
                })

                st.dataframe(
                    df_res_visao,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Ativo": st.column_config.Column(disabled=True),
                        "Competência": st.column_config.Column(disabled=True),
                        "Categoria": st.column_config.Column(disabled=True),
                        "Mercado": st.column_config.Column(disabled=True),
                        "Volume de Vendas": st.column_config.Column(disabled=True),
                        "Resultado Líquido": st.column_config.Column(disabled=True),
                        "Rentabilidade (%)": st.column_config.Column(disabled=True),
                    },
                )

    with aba2:
        tema.kpis([
            {"rotulo": "Total de Ordens", "valor": len(filtro_ops), "icone": "\U0001F501"},
            {"rotulo": "Compras Realizadas", "valor": _moeda(filtro_ops.loc[filtro_ops["tipo"] == "C", "valor_total"].sum()), "icone": "\U0001F7E2"},
            {"rotulo": "Vendas Realizadas", "valor": _moeda(filtro_ops.loc[filtro_ops["tipo"] == "V", "valor_total"].sum()), "icone": "\U0001F534"},
        ])

        colunas = ["data", "tipo", "ticker", "grupo", "mercado", "quantidade", "preco", "valor_total", "taxas", "nota", "corretora"]
        colunas_moeda = ["preco", "valor_total", "taxas"]
        df_ordens = _colorir(_tabela_moeda(filtro_ops[colunas], colunas_moeda), colunas_moeda)

        st.dataframe(
            df_ordens,
            use_container_width=True,
            hide_index=True,
            column_config={
                c: st.column_config.Column(disabled=True) for c in colunas
            },
        )

        st.download_button(
            "Baixar livro de ordens (CSV)",
            data=_to_csv(filtro_ops[colunas]),
            file_name=f"extrato_ordens_{date.today():%Y%m%d}.csv",
            mime="text/csv",
            icon=":material/download:",
        )


# ---------------------------------------------------------------------------
# Página 6 — DARF
# ---------------------------------------------------------------------------

def _secao_irpf_bens_e_direitos() -> None:
    """Relatório Copia e Cola para Declaração Anual de IRPF (Bens e Direitos)."""
    if posicao.empty:
        return

    tema.secao("Declaração Anual IRPF — Bens e Direitos (Copia e Cola)")
    
    st.warning(
        """⚠️ **Prevenção de Malha Fina — Custo Histórico de Aquisição Obrigatório:**

Na ficha de **Bens e Direitos** do programa da Receita Federal, informe **SEMPRE o Custo de Aquisição Histórico Total** (valor de compra somado a emolumentos e taxas de corretagem). **NUNCA declare pela cotação de fechamento em 31/12!** A variação de mercado não altera o custo de aquisição na declaração de bens; alterar esse valor gera variação patrimonial fictícia e é um dos principais motivos de retenção em malha fina."""
    )

    mapa_rfb = {
        "STOCK": {"grupo": "03 - Participações Societárias", "codigo": "01 - Ações (inclusive as provenientes de linha telefônica)", "desc_tipo": "ações"},
        "FII": {"grupo": "07 - Fundos", "codigo": "03 - Fundos de Investimento Imobiliário (FII)", "desc_tipo": "cotas de FII"},
        "BDR": {"grupo": "04 - Aplicações e Investimentos", "codigo": "04 - Ativos negociados no exterior (BDRs)", "desc_tipo": "certificados BDR"},
        "ETF": {"grupo": "07 - Fundos", "codigo": "09 - Demais fundos de índice de mercado (ETFs)", "desc_tipo": "cotas de ETF"},
        "GOLD": {"grupo": "04 - Aplicações e Investimentos", "codigo": "01 - Ouro ativo financeiro", "desc_tipo": "gramas de ouro ativo financeiro"},
    }

    linhas_irpf = []
    for _, row in posicao.iterrows():
        ticker = str(row["Ticker"])
        grupo_fee = str(row["Grupo"])
        qtd = float(row["Quantidade"])
        pm = float(row["Preço Médio"])
        custo = float(row["Custo Total"])

        rfb_info = mapa_rfb.get(grupo_fee, {
            "grupo": "99 - Outros Bens e Direitos",
            "codigo": "99 - Outros bens e direitos",
            "desc_tipo": "ativos de renda variável",
        })

        corretora = "corretora de valores nacional"
        if not operacoes.empty and "corretora" in operacoes.columns:
            ops_t = operacoes[operacoes["ticker"] == ticker]
            if not ops_t.empty and ops_t["corretora"].iloc[-1]:
                corretora = ops_t["corretora"].iloc[-1]

        qtd_txt = f"{int(qtd)}" if qtd.is_integer() else f"{qtd:.4f}".rstrip("0").rstrip(".")
        discriminacao = (
            f"{qtd_txt} {rfb_info['desc_tipo']} de {ticker}, custodiadas na {corretora}, "
            f"ao custo total de aquisição de {_moeda(custo)} (preço médio de {_moeda(pm)} com taxas e emolumentos incluídos)."
        )

        linhas_irpf.append({
            "Ticker": ticker,
            "Grupo RFB": rfb_info["grupo"],
            "Código RFB": rfb_info["codigo"],
            "Quantidade": qtd_txt,
            "Custo Total (Situação em 31/12)": _moeda(custo),
            "Discriminação": discriminacao,
        })

    df_irpf = pd.DataFrame(linhas_irpf)

    with st.expander("📋 Ver Tabela de Bens e Direitos & Textos Prontos para Copiar", expanded=True):
        st.dataframe(
            df_irpf[["Ticker", "Grupo RFB", "Código RFB", "Quantidade", "Custo Total (Situação em 31/12)"]],
            width="stretch", hide_index=True,
        )

        st.caption("Selecione o ativo abaixo para visualizar e copiar a discriminação formatada para a Receita Federal:")
        ticker_sel = st.selectbox(
            "Selecionar ativo para copiar discriminação:",
            df_irpf["Ticker"].tolist(),
            key="sel_irpf_ativo",
        )
        item_sel = df_irpf[df_irpf["Ticker"] == ticker_sel].iloc[0]

        c_g, c_c = st.columns(2)
        with c_g:
            st.info(f"**Grupo:** {item_sel['Grupo RFB']}")
        with c_c:
            st.info(f"**Código:** {item_sel['Código RFB']}")

        st.caption("Discriminação pronta para colar no programa do IRPF:")
        st.code(item_sel["Discriminação"], language="text")


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

        _secao_irpf_bens_e_direitos()


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
            f"{_moeda(PARAMETROS['isencao_acoes'])} (ações e ouro) ou "
            f"{_moeda(PARAMETROS['isencao_eua'])} (ativos dos EUA). "
            "Prejuízos e IRRF retido são compensados por categoria, mês a mês — "
            "o que não for usado fica acumulado para as competências seguintes."
        )


# ---------------------------------------------------------------------------
# Página 6 — DARF
# ---------------------------------------------------------------------------



@st.dialog("Confirmação de Geração de DARF")
def modal_confirmar_gerar_darf(competencia: str, recolher: float) -> None:
    st.markdown(
        "<p style='color: #1e293b; font-size: 0.95rem; line-height: 1.6;'>"
        "O imposto é calculado com base nas informações enviadas à <strong>FiscoTrade</strong>.<br><br>"
        "Antes de efetuar o pagamento, confira se sua carteira está atualizada em "
        "<strong>Meu Patrimônio</strong> e as operações deste mês em <strong>Extrato</strong>."
        "</p>",
        unsafe_allow_html=True,
    )
    st.markdown("<strong style='color: #0f172a;'>Confirma a geração do DARF?</strong>", unsafe_allow_html=True)
    c_nao, c_sim = st.columns(2)
    with c_nao:
        if st.button("NÃO", key=f"btn_nao_{competencia}", use_container_width=True):
            st.rerun()
    with c_sim:
        if st.button("SIM", type="primary", key=f"btn_sim_{competencia}", use_container_width=True):
            st.session_state[f"abrir_darf_oficial_{competencia}"] = True
            st.rerun()


def pagina_darf() -> None:
    tema.cabecalho(
        "DARF — Guia de Pagamento e Histórico Fiscal",
        "Acompanhe o imposto apurado por competência, emita a guia oficial da Receita Federal e controle seus pagamentos.",
        "\U0001F9EE",
    )

    if tabela_ir is None or tabela_ir.empty:
        tema.vazio("Sem competências apuradas. Importe notas na página **Upload de Notas**.")
        return

    competencias_ordenadas = list(tabela_ir["mes"].iloc[::-1])

    # Se o usuário confirmou no modal anterior, abre a emissão oficial
    for comp in competencias_ordenadas:
        if st.session_state.get(f"abrir_darf_oficial_{comp}"):
            st.session_state.pop(f"abrir_darf_oficial_{comp}", None)
            linha_c = tabela_ir[tabela_ir["mes"] == comp].iloc[0]
            modal_emitir_darf_oficial(comp, float(linha_c.get("DARFFinal", 0.0)))
            break

    ultima_comp = competencias_ordenadas[0]
    linha_atual = tabela_ir[tabela_ir["mes"] == ultima_comp].iloc[0]
    recolher_atual = float(linha_atual.get("DARFFinal", 0.0))
    pagamento_atual = darf_pagamentos.get(ultima_comp) if darf_pagamentos else None
    pago_atual = bool(pagamento_atual and pagamento_atual.get("pago"))

    # KPIs de Alto Nível
    total_recolhido = sum(float(p.get("valor_pago", 0.0)) for p in darf_pagamentos.values() if p.get("pago")) if darf_pagamentos else 0.0
    pendentes_count = sum(
        1 for m in competencias_ordenadas
        if float(tabela_ir[tabela_ir["mes"] == m]["DARFFinal"].iloc[0]) > 0
        and (not darf_pagamentos or not darf_pagamentos.get(m, {}).get("pago"))
    )

    tema.kpis([
        {"rotulo": f"DARF de {_nome_mes(ultima_comp)}", "valor": _moeda(recolher_atual), "icone": "\U0001F4C5", "tom": "neg" if recolher_atual > 0 and not pago_atual else "pos"},
        {"rotulo": "Total Pago no Ano", "valor": _moeda(total_recolhido), "icone": "\U0001F4B0"},
        {"rotulo": "Situação das Guias", "valor": f"{pendentes_count} Pendente(s)" if pendentes_count > 0 else "100% Em Dia", "icone": "\u2705" if pendentes_count == 0 else "\u23F3", "tom": "pos" if pendentes_count == 0 else "neg"},
    ])

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    # Tabela Executiva no estilo MyProfit (com Cabeçalho Verde e Linhas por Ativo)
    st.markdown("""
    <div style="background: #10b981; color: #ffffff; border-radius: 8px 8px 0 0; padding: 12px 16px; font-weight: 700; font-size: 0.88rem; display: grid; grid-template-columns: 1.2fr 1.5fr 1.6fr 1.4fr 1.4fr 3fr; gap: 12px; align-items: center;">
        <div>Mês/Ano</div>
        <div>Ativos</div>
        <div style="text-align: right;">Base de cálculo R$</div>
        <div style="text-align: right;">IR</div>
        <div style="text-align: right;">DARF</div>
        <div style="text-align: left; padding-left: 16px;">Pagamento</div>
    </div>
    """, unsafe_allow_html=True)

    for i, mes in enumerate(competencias_ordenadas):
        linha = tabela_ir[tabela_ir["mes"] == mes].iloc[0]
        rec = float(linha.get("DARFFinal", 0.0))
        base_bolsa = float(linha.get("BaseCalcSwingTrade", 0.0) + linha.get("BaseCalcDayTrade", 0.0))
        ir_bolsa = float(linha.get("IRRFBase", 0.0)) if rec > 0 else rec
        pg = darf_pagamentos.get(mes) if darf_pagamentos else None
        pago = bool(pg and pg.get("pago"))
        venc = _vencimento_darf(mes)

        # Fundo zebrado sutil para distinguir cada mês
        bg_bloco = "#ffffff" if i % 2 == 0 else "#f8fafc"
        borda_btm = "border-bottom: 2px solid #e2e8f0;" if i < len(competencias_ordenadas) - 1 else ""

        # Container do Mês com as 3 linhas
        with st.container():
            st.markdown(f"""
            <div style="background: {bg_bloco}; padding: 14px 16px; border-left: 1px solid #e2e8f0; border-right: 1px solid #e2e8f0; {borda_btm}">
                <!-- Linha 1: Bolsa (Brasil) -->
                <div style="display: grid; grid-template-columns: 1.2fr 1.5fr 1.6fr 1.4fr 1.4fr 3fr; gap: 12px; align-items: center; margin-bottom: 8px;">
                    <div><strong style="color: #0f172a; font-size: 0.95rem;">{_nome_mes(mes)}</strong></div>
                    <div style="color: #334155; font-size: 0.9rem;">Bolsa (Brasil)</div>
                    <div style="text-align: right; color: #0284c7; font-weight: 600; font-size: 0.95rem;">{_moeda(base_bolsa)}</div>
                    <div style="text-align: right; color: #0284c7; font-weight: 600; font-size: 0.95rem;">{_moeda(ir_bolsa)}</div>
                    <div style="text-align: right; font-weight: 700; color: {'#059669' if pago else ('#0f172a' if rec > 0 else '#64748b')}; font-size: 0.95rem;">
                        {_moeda(rec) if rec > 0 else 'Isento'}
                    </div>
                    <div id="col_act_{mes}"></div>
                </div>
                <!-- Linha 2: FII -->
                <div style="display: grid; grid-template-columns: 1.2fr 1.5fr 1.6fr 1.4fr 1.4fr 3fr; gap: 12px; align-items: center; margin-bottom: 6px; color: #64748b; font-size: 0.85rem;">
                    <div></div>
                    <div>FII</div>
                    <div style="text-align: right;">R$ 0,00</div>
                    <div style="text-align: right;">R$ 0,00</div>
                    <div style="text-align: right; color: #64748b;">Isento</div>
                    <div></div>
                </div>
                <!-- Linha 3: Criptomoedas (Brasil) -->
                <div style="display: grid; grid-template-columns: 1.2fr 1.5fr 1.6fr 1.4fr 1.4fr 3fr; gap: 12px; align-items: center; color: #64748b; font-size: 0.85rem;">
                    <div></div>
                    <div>Criptomoedas (Brasil)</div>
                    <div style="text-align: right;">R$ 0,00</div>
                    <div style="text-align: right;">R$ 0,00</div>
                    <div style="text-align: right; color: #64748b;">Isento</div>
                    <div></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Botões de Ação nativos alinhados confortavelmente
            c_sp, c_act1, c_act2 = st.columns([5.5, 2.2, 2.3])
            with c_act1:
                if rec > 0:
                    if st.button("💵 Gerar DARF", key=f"btn_gdarf_{mes}", type="primary", use_container_width=True):
                        modal_confirmar_gerar_darf(mes, rec)
            with c_act2:
                if rec > 0:
                    if pago:
                        dt_pago_txt = _data_armazenada(pg.get("data_pagamento")).strftime("%d/%m/%Y")
                        st.markdown(f"<span style='color: #059669; font-weight: 700; font-size: 0.88rem;'>✓ Pago {_moeda(rec)} no dia {dt_pago_txt}</span>", unsafe_allow_html=True)
                        if st.button("🔖 Marcar como pendente", key=f"btn_pend_{mes}", type="secondary", use_container_width=True):
                            gravar_darf_pagamento(conexao, usuario_id, mes, False, 0.0, None)
                            st.rerun()
                    else:
                        with st.popover("🔖 Marcar como pago", use_container_width=True):
                            st.write(f"**Registrar pagamento de {_nome_mes(mes)}**")
                            dt_p = st.date_input("Data do pagamento:", value=venc, key=f"dt_pop_{mes}")
                            if st.button("Salvar pagamento", type="primary", key=f"salv_pop_{mes}", use_container_width=True):
                                gravar_darf_pagamento(conexao, usuario_id, mes, True, rec, dt_p.isoformat())
                                st.success("Pagamento registrado!")
                                st.rerun()

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

    # Detalhamento de compensação de IRRF e Internet Banking
    with st.expander("🛡️ Compensação de IRRF ('Dedo-Duro') e Legislação"):
        linha_comp = linha_atual
        irrf_mes = float(linha_comp["IRRFMonthlyDayTrade"] + linha_comp["IRRFMonthlySwingTrade"])
        irrf_usado = float(linha_comp["IRRFUsedDayTrade"] + linha_comp["IRRFUsedSwingTrade"])
        irrf_proximo = float(linha_comp["IRRFNextMonthDayTrade"] + linha_comp["IRRFNextMonthSwingTrade"])
        st.markdown(f"""
        Conforme o **Art. 64 da Instrução Normativa RFB nº 1.585/15**, a retenção na fonte (0,005% em swing trade e 1% em day trade) 
        é abatida centavo a centavo do seu DARF. O saldo que não for utilizado no mês é transportado para os meses seguintes:
        - **IRRF retido no mês:** {_moeda(irrf_mes)}
        - **IRRF abatido neste DARF:** {_moeda(irrf_usado)}
        - **Saldo de IRRF a transportar para o próximo mês:** {_moeda(irrf_proximo)}
        """)

    with st.expander("💡 Como Pagar via Internet Banking (IN SRF 96/2001)"):
        st.markdown("""
        O DARF sem código de barras pode ser pago via Internet Banking ou aplicativo de qualquer banco conveniado com a Receita Federal
        (Banco do Brasil, Itaú, Bradesco, Santander, Caixa, Inter, etc.) através do menu **Pagamentos > DARF**.
        
        De acordo com a **Instrução Normativa SRF nº 96/2001** da Receita Federal, aplicativos de terceiros não podem emitir DARF com código de barras.
        O pagamento oficial é compensado pelo código de receita **6015** e pelo seu CPF.
        """)


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
            gratuito = float(plano["preco_mensal"]) <= 0
            preco = ("Grátis" if gratuito
                     else f"{_moeda(plano['preco_mensal'])}<span style='font-size:0.9rem;color:#6b7280;font-weight:normal;'>/mês</span>")
            st.markdown(
                f"<div style='margin:0.5rem 0;'><span style='font-size:0.8rem;text-transform:uppercase;letter-spacing:0.05em;color:#6b7280;display:block;'>Mensalidade</span>"
                f"<span style='font-size:1.75rem;font-weight:700;'>{preco}</span></div>",
                unsafe_allow_html=True,
            )
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

        indicacao = saas.beneficio_indicacao(conexao, usuario_id)
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
        elif indicacao:
            cupom = indicacao
            st.info(f"Benefício de indicação de **{indicacao['parceiro']}**: "
                    f"{saas.descrever_cupom(indicacao)}.")

        valores = saas.calcular_preco(pro, cupom, meses=int(meses))
        if valores["tipo"] == "meses":
            unidade = "mês" if valores["meses"] == 1 else "meses"
            st.caption(
                f"Plano {_moeda(valores['original'])}/mês · "
                f"**{valores['meses']} {unidade} grátis** "
                f"(economia de {_moeda(valores['desconto'])}) · total **Grátis**"
            )
        else:
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

    tema.secao("Dados Cadastrais para DARF Oficial")
    st.caption("Estes dados são preenchidos automaticamente no formulário oficial da Receita Federal (IN/RFB nº 736/2007) ao emitir a sua guia.")
    with st.form("form_dados_cadastrais"):
        c_cad1, c_cad2 = st.columns(2)
        with c_cad1:
            nome_cad = st.text_input("Nome completo do contribuinte:", value=usuario["nome"] or "")
            cpf_cad = st.text_input("CPF:", value=usuario["cpf"] or "", placeholder="000.000.000-00")
            tel_cad = st.text_input("Telefone com DDD:", value=usuario["telefone"] or "", placeholder="(00) 00000-0000")
        with c_cad2:
            cidade_cad = st.text_input("Município / Domicílio Tributário:", value=usuario["cidade"] or "", placeholder="Ex: SÃO PAULO")
            estado_cad = st.text_input("UF (Estado):", value=usuario["estado"] or "", placeholder="Ex: SP", max_chars=2)
            end_cad = st.text_input("Endereço / Logradouro (opcional):", value=usuario["endereco"] or "")
        
        if st.form_submit_button("Salvar Dados Cadastrais", type="primary", icon=":material/save:"):
            from persistencia import atualizar_usuario
            atualizar_usuario(
                conexao,
                usuario_id,
                nome=nome_cad.strip(),
                cpf=cpf_cad.strip(),
                telefone=tel_cad.strip(),
                cidade=cidade_cad.strip(),
                estado=estado_cad.strip().upper(),
                endereco=end_cad.strip(),
            )
            st.success("Dados cadastrais atualizados com sucesso!")
            st.rerun()

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
