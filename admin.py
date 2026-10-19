"""
admin.py
--------
Painel administrativo do SaaS, acessível apenas a usuários com perfil de
administrador (``is_admin = 1``).

Cada ``pagina_*`` é uma função sem argumentos registrada em ``app.py`` com
``st.Page`` — e **só** entra na navegação quando a sessão é de administrador,
de modo que um usuário comum não tem rota para chegar aqui.

As regras de negócio (planos, limites, cupons, checkout e métricas) estão em
``saas.py`` e o acesso ao banco em ``persistencia.py``.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import paginas
import persistencia as bd
import monitor
import regras
import saas
import tema


def _moeda(valor: float) -> str:
    """Formata um número no padrão brasileiro: R$ 1.234,56."""
    return f"R$ {float(valor or 0.0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _data(iso: str | None) -> str:
    """Data ISO guardada no banco -> ``dd/mm/aaaa`` (ou ``—``)."""
    if not iso:
        return "—"
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return "—"


# ---------------------------------------------------------------------------
# Visão geral (métricas)
# ---------------------------------------------------------------------------

def pagina_dashboard() -> None:
    tema.cabecalho(
        "Visão geral do negócio",
        "Métricas de cadastros, assinaturas e faturamento da plataforma.",
        "\U0001F4CA",
    )
    conexao = paginas.obter_conexao()
    m = saas.metricas(conexao)

    tema.kpis([
        {"rotulo": "Usuários cadastrados", "valor": m["usuarios_total"],
         "icone": "\U0001F465"},
        {"rotulo": "Assinantes PRO", "valor": m["usuarios_pagos"], "icone": "\U0001F31F"},
        {"rotulo": "Faturamento acumulado", "valor": _moeda(m["faturamento"]),
         "icone": "\U0001F4B0"},
        {"rotulo": "Ticket médio", "valor": _moeda(m["ticket_medio"]),
         "icone": "\U0001F4C8"},
    ])
    tema.kpis([
        {"rotulo": "Plano Gratuito", "valor": m["usuarios_free"], "icone": "\U0001F193"},
        {"rotulo": "Contas ativas", "valor": m["usuarios_ativos"], "icone": "\u2705"},
        {"rotulo": "Assinaturas ativas", "valor": m["assinaturas_ativas"],
         "icone": "\U0001F4CB"},
        {"rotulo": "Cupons ativos", "valor": m["cupons_ativos"], "icone": "\U0001F39F\uFE0F"},
    ])

    col1, col2 = st.columns(2)
    with col1:
        tema.secao("Distribuição de planos")
        st.bar_chart(pd.DataFrame(
            {"Usuários": [m["usuarios_free"], m["usuarios_pagos"]]},
            index=["Gratuito", "PRO"],
        ), height=300)
    with col2:
        tema.secao("Assinaturas")
        st.bar_chart(pd.DataFrame(
            {"Assinaturas": [m["assinaturas_ativas"], m["assinaturas_canceladas"]]},
            index=["Ativas", "Canceladas"],
        ), height=300)

    st.caption(
        "Faturamento considera apenas pagamentos com status **pago**. "
        "O checkout é simulado — nenhuma cobrança real é efetuada."
    )


# ---------------------------------------------------------------------------
# Contas / cadastros
# ---------------------------------------------------------------------------

def pagina_contas() -> None:
    tema.cabecalho(
        "Contas e cadastros",
        "Consulte, filtre e ajuste plano, status e permissões de cada usuário.",
        "\U0001F465",
    )
    conexao = paginas.obter_conexao()
    df = bd.listar_usuarios(conexao)

    if df.empty:
        tema.vazio("Nenhum usuário cadastrado.")
        return

    filtro = st.radio(
        "Filtro",
        ["Todos", "Gratuito (Free)", "Assinante (pago)", "Ativos", "Inativos"],
        horizontal=True,
    )
    visao = df.copy()
    if filtro == "Gratuito (Free)":
        visao = visao[visao["plano"] == "free"]
    elif filtro == "Assinante (pago)":
        visao = visao[visao["plano"] != "free"]
    elif filtro == "Ativos":
        visao = visao[visao["ativo"] == 1]
    elif filtro == "Inativos":
        visao = visao[visao["ativo"] == 0]

    st.caption(f"{len(visao)} de {len(df)} conta(s).")
    st.dataframe(visao, width="stretch", hide_index=True)

    tema.secao("Gerenciar conta")
    rotulos = {int(r.id): f"{r.usuario} — {r.email}" for r in df.itertuples()}
    escolhido = st.selectbox("Usuário", options=list(rotulos),
                             format_func=lambda i: rotulos[i], key="admin_conta")
    linha = df[df["id"] == escolhido].iloc[0]

    planos = bd.listar_planos(conexao)
    codigos = list(planos["codigo"])
    nomes = dict(zip(planos["codigo"], planos["nome"]))

    col1, col2, col3 = st.columns(3)
    with col1:
        ativo = st.toggle("Conta ativa", value=bool(linha["ativo"]),
                          key=f"ativo_{escolhido}")
    with col2:
        admin = st.toggle("Administrador", value=bool(linha["is_admin"]),
                          key=f"admin_{escolhido}")
    with col3:
        indice = codigos.index(linha["plano"]) if linha["plano"] in codigos else 0
        plano = st.selectbox("Plano", codigos, index=indice,
                             format_func=lambda c: nomes.get(c, c),
                             key=f"plano_{escolhido}")

    eu_mesmo = escolhido == st.session_state.get("usuario_id")
    if st.button("Salvar alterações", type="primary", icon=":material/save:"):
        if eu_mesmo and (not ativo or not admin):
            st.error("Você não pode desativar nem remover o seu próprio perfil de administrador.")
        else:
            saas.definir_status_usuario(conexao, escolhido, ativo)
            saas.definir_admin(conexao, escolhido, admin)
            bd.atualizar_usuario(conexao, escolhido, plano_codigo=plano)
            st.success("Conta atualizada.")
            st.rerun()


# ---------------------------------------------------------------------------
# Assinaturas
# ---------------------------------------------------------------------------

def pagina_assinaturas() -> None:
    tema.cabecalho(
        "Gestão de assinaturas",
        "Acompanhe o ciclo de vida das assinaturas e cancele quando necessário.",
        "\U0001F4CB",
    )
    conexao = paginas.obter_conexao()

    df = bd.listar_assinaturas(conexao)
    if df.empty:
        tema.vazio("Nenhuma assinatura registrada até agora.")
        return

    filtro = st.radio("Status", ["Todas", "Ativas", "Canceladas", "Substituídas"],
                      horizontal=True)
    visao = df
    if filtro == "Ativas":
        visao = df[df["status"] == "ativa"]
    elif filtro == "Canceladas":
        visao = df[df["status"] == "cancelada"]
    elif filtro == "Substituídas":
        visao = df[df["status"] == "substituida"]

    st.dataframe(visao, width="stretch", hide_index=True)

    ativas = conexao.execute(
        "SELECT a.id, a.usuario_id, u.usuario, a.plano_codigo, a.fim "
        "FROM assinaturas a JOIN usuarios u ON u.id = a.usuario_id "
        "WHERE a.status = 'ativa' ORDER BY a.id DESC"
    ).fetchall()
    if not ativas:
        st.caption("Não há assinaturas ativas para cancelar.")
        return

    tema.secao("Cancelar assinatura")
    rotulos = {int(l["id"]): f"{l['usuario']} — {l['plano_codigo']} (até {l['fim']})"
               for l in ativas}
    escolhida = st.selectbox("Assinatura ativa", options=list(rotulos),
                             format_func=lambda i: rotulos[i], key="admin_assinatura")
    usuario_id = next(int(l["usuario_id"]) for l in ativas if int(l["id"]) == escolhido)
    if st.button("Cancelar assinatura selecionada", icon=":material/cancel:"):
        bd.cancelar_assinatura(conexao, usuario_id)
        st.success("Assinatura cancelada; o usuário voltou ao plano Gratuito.")
        st.rerun()


# ---------------------------------------------------------------------------
# Pagamentos (métodos + notas fiscais)
# ---------------------------------------------------------------------------

def pagina_pagamentos() -> None:
    tema.cabecalho(
        "Pagamentos e notas fiscais",
        "Configuração das chaves de checkout, faturamento e documentos emitidos.",
        "\U0001F4B3",
    )
    conexao = paginas.obter_conexao()

    tema.secao("Métodos de pagamento")
    st.caption(
        "Chaves usadas pelo checkout. Enquanto o ambiente for **simulado**, "
        "nenhuma cobrança é feita — as chaves ficam apenas gravadas no banco "
        "local para quando a integração real for ligada."
    )
    config = bd.obter_config_pagamento(conexao)
    with st.form("form_config_pagamento"):
        ambiente = st.selectbox(
            "Ambiente", ["simulado", "producao"],
            index=0 if config.get("ambiente", "simulado") == "simulado" else 1,
        )
        pix_chave = st.text_input("Chave Pix", value=config.get("pix_chave") or "")
        pix_recebedor = st.text_input("Recebedor (Pix)",
                                      value=config.get("pix_recebedor") or "")
        cartao_provedor = st.text_input("Provedor do cartão",
                                        value=config.get("cartao_provedor") or "")
        cartao_api_key = st.text_input("API key do cartão", type="password",
                                       value=config.get("cartao_api_key") or "")
        cartao_public_key = st.text_input("Public key do cartão",
                                          value=config.get("cartao_public_key") or "")
        if st.form_submit_button("Salvar configuração", type="primary",
                                 icon=":material/save:"):
            bd.gravar_config_pagamento(conexao, {
                "pix_chave": pix_chave, "pix_recebedor": pix_recebedor,
                "cartao_provedor": cartao_provedor, "cartao_api_key": cartao_api_key,
                "cartao_public_key": cartao_public_key, "ambiente": ambiente,
            })
            st.success("Configuração de pagamento atualizada.")

    tema.secao("Pagamentos recebidos")
    pagamentos = bd.listar_pagamentos(conexao)
    if pagamentos.empty:
        st.caption("Nenhum pagamento registrado.")
    else:
        tema.kpis([
            {"rotulo": "Pagamentos", "valor": len(pagamentos), "icone": "\U0001F9FE"},
            {"rotulo": "Faturamento acumulado",
             "valor": _moeda(bd.faturamento_total(conexao)), "icone": "\U0001F4B0"},
        ])
        st.dataframe(pagamentos, width="stretch", hide_index=True)

    tema.secao("Notas fiscais emitidas")
    notas = bd.listar_notas_fiscais(conexao)
    if notas.empty:
        st.caption("Nenhuma nota fiscal emitida.")
    else:
        st.dataframe(notas, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Cupons de desconto
# ---------------------------------------------------------------------------

def pagina_cupons() -> None:
    tema.cabecalho(
        "Cupons de desconto",
        "Crie códigos promocionais e controle quantas vezes podem ser usados.",
        "\U0001F39F\uFE0F",
    )
    conexao = paginas.obter_conexao()

    tema.secao("Criar cupom")
    with st.form("form_cupom", clear_on_submit=True):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            codigo = st.text_input("Código", placeholder="BEMVINDO10")
        with col2:
            desconto = st.number_input("Desconto (%)", min_value=0.0, max_value=100.0,
                                       value=10.0, step=5.0)
        with col3:
            validade = st.date_input("Validade", value=date.today())
        with col4:
            uso_maximo = st.number_input("Limite de usos (0 = ilimitado)",
                                         min_value=0, step=1, value=0)
        if st.form_submit_button("Criar cupom", type="primary",
                                 icon=":material/add:"):
            if not codigo.strip():
                st.error("Informe o código do cupom.")
            else:
                try:
                    bd.criar_cupom(conexao, codigo, desconto,
                                   validade=validade.isoformat(), uso_maximo=int(uso_maximo))
                except ValueError as erro:
                    st.error(str(erro))
                else:
                    st.success(f"Cupom {codigo.strip().upper()} criado.")
                    st.rerun()

    tema.secao("Cupons cadastrados")
    cupons = bd.listar_cupons(conexao)
    if cupons.empty:
        tema.vazio("Nenhum cupom cadastrado ainda.")
        return

    st.dataframe(cupons, width="stretch", hide_index=True)

    tema.secao("Ativar / desativar")
    rotulos = {int(r.id): f"{r.codigo} — {r.desconto_pct:.0f}% "
                          f"({'ativo' if r.ativo else 'inativo'})"
               for r in cupons.itertuples()}
    escolhido = st.selectbox("Cupom", options=list(rotulos),
                             format_func=lambda i: rotulos[i], key="admin_cupom")
    linha = cupons[cupons["id"] == escolhido].iloc[0]
    novo = st.toggle("Ativo", value=bool(linha["ativo"]), key=f"cupom_ativo_{escolhido}")
    if st.button("Salvar cupom", icon=":material/save:"):
        bd.definir_cupom_ativo(conexao, escolhido, novo)
        st.success("Cupom atualizado.")
        st.rerun()


# ---------------------------------------------------------------------------
# Parâmetros fiscais e monitor de legislação
# ---------------------------------------------------------------------------

def pagina_parametros() -> None:
    tema.cabecalho(
        "Parâmetros fiscais e legislação",
        "Ajuste as alíquotas, isenções e o código do DARF do motor de cálculo e "
        "acompanhe mudanças nas fontes oficiais.",
        "\u2696\ufe0f",
    )
    conexao = paginas.obter_conexao()

    # -- Monitor de legislação --------------------------------------------
    tema.secao("Monitor de legislação")
    st.caption(
        "O monitor guarda uma impressão digital (hash) do conteúdo de cada "
        "fonte oficial. Ao **buscar mudanças**, ele baixa as páginas de novo e "
        "avisa quando o texto mudou — o gatilho para revisar a tabela de "
        "cálculo logo abaixo."
    )
    guardado = bd.carregar_monitor_legislacao(conexao)
    ultima = monitor.ultima_verificacao(conexao)

    col_botao, col_data = st.columns([1, 3])
    with col_botao:
        buscar = st.button("Buscar mudanças", type="primary",
                           icon=":material/travel_explore:", width="stretch")
    with col_data:
        if ultima is None:
            st.caption("Nenhuma verificação feita ainda.")
        else:
            st.caption(f"Última verificação: **{_data(ultima.isoformat())}**.")

    if buscar:
        with st.spinner("Consultando as fontes oficiais..."):
            resultados = monitor.verificar(conexao)
        guardado = bd.carregar_monitor_legislacao(conexao)
        ultima = monitor.ultima_verificacao(conexao)

        alteradas = [r["titulo"] for r in resultados if r["situacao"] == "mudou"]
        novas = [r["titulo"] for r in resultados if r["situacao"] == "primeira"]
        falhas = [r["titulo"] for r in resultados if r["situacao"] == "falhou"]

        if alteradas:
            st.warning("Mudança detectada em: " + "; ".join(alteradas)
                       + ". Revise a tabela de cálculo abaixo.")
        elif novas:
            st.info("Fontes registradas pela primeira vez: " + "; ".join(novas)
                    + ". A partir de agora, qualquer alteração será avisada.")
        elif falhas:
            st.info("Fontes consultadas, mas algumas não responderam agora "
                    f"({len(falhas)}). Tente novamente mais tarde.")
        else:
            st.success("Nada mudou desde a última verificação.")

    linhas = []
    for fonte in monitor.FONTES:
        registro = guardado.get(fonte["url"], {})
        mudou_em = registro.get("mudou_em")
        verificado = registro.get("verificado_em")
        if mudou_em:
            situacao = f"Alterada em {_data(mudou_em)}"
        elif verificado:
            situacao = "Sem mudança"
        else:
            situacao = "Não verificada"
        linhas.append({
            "Fonte oficial": fonte["titulo"],
            "Última verificação": _data(verificado),
            "Situação": situacao,
        })
    st.dataframe(pd.DataFrame(linhas), width="stretch", hide_index=True)

    if ultima is not None and (date.today() - ultima).days > monitor.DIAS_ALERTA:
        st.warning(
            f"A última verificação foi há {(date.today() - ultima).days} dias. "
            f"Recomenda-se buscar mudanças a cada {monitor.DIAS_ALERTA} dias."
        )

    # -- Tabela de cálculo -------------------------------------------------
    tema.secao("Tabela de cálculo")
    st.caption(
        "Parâmetros usados em toda a apuração. As alíquotas são frações "
        "(0,20 = 20%). Mudar aqui vale para todos os usuários e recai "
        "imediatamente sobre as telas de IR e DARF — as notas já importadas "
        "não precisam ser reenviadas."
    )
    atuais = bd.carregar_parametros_fiscais(conexao)
    with st.form("form_parametros_fiscais"):
        valores: dict[str, str] = {}
        for chave, rotulo, tipo, descricao, padrao in regras.PARAMETROS_FISCAIS:
            atual = atuais.get(chave, str(padrao))
            if tipo is float and chave.startswith("aliquota"):
                valores[chave] = st.number_input(
                    rotulo, min_value=0.0, max_value=1.0, value=float(atual),
                    step=0.01, format="%.2f", help=descricao)
            elif tipo is float:
                valores[chave] = st.number_input(
                    rotulo, min_value=0.0, value=float(atual), step=100.0,
                    format="%.2f", help=descricao)
            elif tipo is int:
                valores[chave] = st.number_input(
                    rotulo, min_value=0, max_value=12, value=int(float(atual)),
                    step=1, help=descricao)
            else:
                valores[chave] = st.text_input(rotulo, value=str(atual),
                                               help=descricao)

        if st.form_submit_button("Salvar parâmetros", type="primary",
                                 icon=":material/save:"):
            dados = {chave: str(valor) for chave, valor in valores.items()}
            bd.gravar_parametros_fiscais(conexao, dados)
            regras.aplicar_parametros(dados)
            st.success("Parâmetros atualizados — a apuração já usa os novos valores.")
            st.rerun()
