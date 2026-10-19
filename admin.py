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
import saas


def _moeda(valor: float) -> str:
    """Formata um número no padrão brasileiro: R$ 1.234,56."""
    return f"R$ {float(valor or 0.0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------------------
# Visão geral (métricas)
# ---------------------------------------------------------------------------

def pagina_dashboard() -> None:
    st.subheader("\U0001F4CA Visão geral do negócio")
    conexao = paginas.obter_conexao()
    m = saas.metricas(conexao)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Usuários cadastrados", m["usuarios_total"])
    c2.metric("Assinantes PRO", m["usuarios_pagos"])
    c3.metric("Faturamento acumulado", _moeda(m["faturamento"]))
    c4.metric("Ticket médio", _moeda(m["ticket_medio"]))

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Plano Gratuito", m["usuarios_free"])
    c6.metric("Contas ativas", m["usuarios_ativos"])
    c7.metric("Assinaturas ativas", m["assinaturas_ativas"])
    c8.metric("Cupons ativos", m["cupons_ativos"])

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Distribuição de planos**")
        st.bar_chart(pd.DataFrame(
            {"Usuários": [m["usuarios_free"], m["usuarios_pagos"]]},
            index=["Gratuito", "PRO"],
        ))
    with col2:
        st.markdown("**Assinaturas**")
        st.bar_chart(pd.DataFrame(
            {"Assinaturas": [m["assinaturas_ativas"], m["assinaturas_canceladas"]]},
            index=["Ativas", "Canceladas"],
        ))

    st.caption(
        "Faturamento considera apenas pagamentos com status **pago**. "
        "O checkout é simulado — nenhuma cobrança real é efetuada."
    )


# ---------------------------------------------------------------------------
# Contas / cadastros
# ---------------------------------------------------------------------------

def pagina_contas() -> None:
    st.subheader("\U0001F465 Verificar contas / cadastros")
    conexao = paginas.obter_conexao()
    df = bd.listar_usuarios(conexao)

    if df.empty:
        st.info("Nenhum usuário cadastrado.")
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

    st.divider()
    st.markdown("**Gerenciar conta**")
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
    if st.button("Salvar alterações", type="primary"):
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
    st.subheader("\U0001F4CB Gestão de assinaturas ativas")
    conexao = paginas.obter_conexao()

    df = bd.listar_assinaturas(conexao)
    if df.empty:
        st.info("Nenhuma assinatura registrada até agora.")
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

    st.divider()
    st.markdown("**Cancelar assinatura**")
    rotulos = {int(l["id"]): f"{l['usuario']} — {l['plano_codigo']} (até {l['fim']})"
               for l in ativas}
    escolhida = st.selectbox("Assinatura ativa", options=list(rotulos),
                             format_func=lambda i: rotulos[i], key="admin_assinatura")
    usuario_id = next(int(l["usuario_id"]) for l in ativas if int(l["id"]) == escolhido)
    if st.button("Cancelar assinatura selecionada"):
        bd.cancelar_assinatura(conexao, usuario_id)
        st.success("Assinatura cancelada; o usuário voltou ao plano Gratuito.")
        st.rerun()


# ---------------------------------------------------------------------------
# Pagamentos (métodos + notas fiscais)
# ---------------------------------------------------------------------------

def pagina_pagamentos() -> None:
    st.subheader("\U0001F4B3 Pagamentos e notas fiscais")
    conexao = paginas.obter_conexao()

    st.markdown("**Métodos de pagamento**")
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
        if st.form_submit_button("Salvar configuração", type="primary"):
            bd.gravar_config_pagamento(conexao, {
                "pix_chave": pix_chave, "pix_recebedor": pix_recebedor,
                "cartao_provedor": cartao_provedor, "cartao_api_key": cartao_api_key,
                "cartao_public_key": cartao_public_key, "ambiente": ambiente,
            })
            st.success("Configuração de pagamento atualizada.")

    st.divider()
    st.markdown("**Pagamentos recebidos**")
    pagamentos = bd.listar_pagamentos(conexao)
    if pagamentos.empty:
        st.caption("Nenhum pagamento registrado.")
    else:
        st.dataframe(pagamentos, width="stretch", hide_index=True)
        st.metric("Faturamento acumulado", _moeda(bd.faturamento_total(conexao)))

    st.markdown("**Notas fiscais emitidas**")
    notas = bd.listar_notas_fiscais(conexao)
    if notas.empty:
        st.caption("Nenhuma nota fiscal emitida.")
    else:
        st.dataframe(notas, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Cupons de desconto
# ---------------------------------------------------------------------------

def pagina_cupons() -> None:
    st.subheader("\U0001F39F\uFE0F Gestão de cupons de desconto")
    conexao = paginas.obter_conexao()

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
        if st.form_submit_button("Criar cupom", type="primary"):
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

    st.divider()
    cupons = bd.listar_cupons(conexao)
    if cupons.empty:
        st.info("Nenhum cupom cadastrado.")
        return

    st.dataframe(cupons, width="stretch", hide_index=True)

    st.markdown("**Ativar / desativar**")
    rotulos = {int(r.id): f"{r.codigo} — {r.desconto_pct:.0f}% "
                          f"({'ativo' if r.ativo else 'inativo'})"
               for r in cupons.itertuples()}
    escolhido = st.selectbox("Cupom", options=list(rotulos),
                             format_func=lambda i: rotulos[i], key="admin_cupom")
    linha = cupons[cupons["id"] == escolhido].iloc[0]
    novo = st.toggle("Ativo", value=bool(linha["ativo"]), key=f"cupom_ativo_{escolhido}")
    if st.button("Salvar cupom"):
        bd.definir_cupom_ativo(conexao, escolhido, novo)
        st.success("Cupom atualizado.")
        st.rerun()
