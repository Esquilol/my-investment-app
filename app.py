"""
app.py
------
Ponto de entrada do painel: configura a página, mostra a **landing pública**
(``landing.py``), faz o **gate de autenticação** (entrar / criar conta /
recuperar senha) e monta o menu lateral com ``st.navigation``.

O conteúdo de cada página fica em ``paginas.py`` (área do investidor) e
``admin.py`` (painel administrativo, restrito a ``is_admin``). As regras de
negócio do SaaS estão em ``saas.py`` e a persistência em ``persistencia.py``.
As credenciais do administrador vêm de ``st.secrets["admin"]``, nunca do código.

Execução local (no Windows, chamar o Streamlit como módulo evita problemas de PATH):

    python -m streamlit run app.py

Páginas do investidor:
    1) **Upload de Notas**     — importe as notas de corretagem em PDF.
    2) **Visão Geral**         — patrimônio, evolução e últimos negócios.
    3) **Extrato**             — todas as operações, com filtros.
    4) **Meu Patrimônio**      — posição em custódia e preço médio.
    5) **Apuração de IR**      — tabela mensal com isenção e compensação.
    6) **DARF**                — valor a recolher por competência.
    7) **Proventos**           — dividendos, JCP, rendimentos e amortizações.
    8) **Relatórios**          — exportação em CSV/Excel.
    9) **Planos e Assinatura** — planos, cupom e checkout.
   10) **Minha Conta**         — perfil e troca de senha.

Páginas do administrador (apenas ``is_admin``):
    * **Visão Geral**   — métricas de cadastros, planos e faturamento.
    * **Contas**        — cadastros com filtros e ativação/inativação.
    * **Assinaturas**   — planos vigentes, faturas e status.
    * **Pagamentos**    — métodos de pagamento e notas fiscais.
    * **Cupons**        — criação, listagem e desativação de cupons.
    * **Parâmetros fiscais** — tabela de cálculo (alíquotas, isenções, código do
      DARF) e monitor de mudanças nas fontes oficiais de legislação.

Observação: os valores apurados são uma estimativa técnica. Não substituem a
apuração oficial (GCAP/DIRPF) nem a orientação de um contador.
"""

from __future__ import annotations

import html

import streamlit as st

import admin
import auth
import landing
import paginas
import saas
import tema
from persistencia import obter_usuario

st.set_page_config(
    page_title="Gestor de Investimentos B3",
    page_icon="\U0001F4C8",
    layout="wide",
    initial_sidebar_state="expanded",
)

tema.aplicar()


# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------

def _entrar(usuario) -> None:
    """Grava a sessão autenticada e recarrega a página."""
    st.session_state.update(
        autenticado=True,
        usuario_id=int(usuario["id"]),
        usuario=usuario["usuario"],
        is_admin=bool(usuario["is_admin"]),
        vista_publica=None,
    )
    st.rerun()


def _aba_entrar(conexao) -> None:
    with st.form("form_login"):
        login = st.text_input("Usuário ou e-mail", key="login_usuario")
        senha = st.text_input("Senha", type="password", key="login_senha")
        if st.form_submit_button("Entrar", type="primary"):
            usuario = auth.autenticar(conexao, login, senha)
            if usuario is None:
                st.error("Usuário/e-mail ou senha inválidos — ou conta inativa.")
            else:
                _entrar(usuario)


def _aba_criar_conta(conexao) -> None:
    st.caption("Sua conta começa no **plano Gratuito**. Você pode assinar o PRO quando quiser.")
    with st.form("form_cadastro"):
        usuario = st.text_input("Usuário", key="cad_usuario",
                                placeholder="ex.: maria.silva")
        email = st.text_input("E-mail", key="cad_email")
        senha = st.text_input("Senha", type="password", key="cad_senha")
        confirmacao = st.text_input("Confirme a senha", type="password", key="cad_confirmacao")
        if st.form_submit_button("Criar conta", type="primary"):
            erro = auth.validar_cadastro(usuario, email, senha, confirmacao)
            if erro:
                st.error(erro)
                return
            try:
                novo_id = auth.criar_conta(conexao, usuario, email, senha)
            except ValueError as erro_banco:
                st.error(str(erro_banco))
            else:
                st.success("Conta criada! Bem-vindo(a) ao plano Gratuito.")
                _entrar({"id": novo_id, "usuario": usuario.strip(), "is_admin": 0})


def _aba_recuperar(conexao) -> None:
    st.caption(
        "A recuperação é **simulada**: como o app ainda não envia e-mails, o "
        "código é exibido aqui na tela. Gere o código e informe no formulário "
        "de redefinição ao lado."
    )
    col1, col2 = st.columns(2)
    with col1:
        with st.form("form_gerar_codigo"):
            email = st.text_input("E-mail cadastrado", key="rec_email")
            if st.form_submit_button("Gerar código"):
                token = auth.gerar_token_recuperacao(conexao, email)
                if token is None:
                    st.error("Não há conta com esse e-mail.")
                else:
                    st.success(
                        f"Código de recuperação: **{token}** "
                        f"(válido por {auth.VALIDADE_TOKEN_HORAS} hora)."
                    )
    with col2:
        with st.form("form_redefinir"):
            email = st.text_input("E-mail", key="red_email")
            codigo = st.text_input("Código de recuperação", key="red_codigo")
            nova = st.text_input("Nova senha", type="password", key="red_nova")
            confirmacao = st.text_input("Confirme a nova senha", type="password",
                                        key="red_confirmacao")
            if st.form_submit_button("Redefinir senha", type="primary"):
                if len(nova) < auth.TAMANHO_MINIMO:
                    st.error(f"A senha deve ter ao menos {auth.TAMANHO_MINIMO} caracteres.")
                elif nova != confirmacao:
                    st.error("As senhas não conferem.")
                elif auth.redefinir_senha(conexao, email, codigo, nova):
                    st.success("Senha redefinida. Já pode entrar com a nova senha.")
                else:
                    st.error("Código inválido ou expirado.")


def tela_autenticacao() -> None:
    """Tela de entrada com login, cadastro e recuperação de senha."""
    conexao = paginas.obter_conexao()
    if st.button("Voltar", icon=":material/arrow_back:"):
        st.session_state["vista_publica"] = "landing"
        st.rerun()
    st.markdown(
        '<div class="mp-marca"><div class="logo">\U0001F4C8</div>'
        "<h1>Gestor de Investimentos B3</h1></div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Entre na sua conta ou crie uma agora. As senhas são gravadas apenas "
        "como **hash PBKDF2** no ``dados.db`` local — nunca em claro."
    )

    modos = ["Entrar", "Criar conta", "Recuperar senha"]
    if st.session_state.get("auth_aba") not in modos:
        st.session_state["auth_aba"] = "Entrar"
    escolha = st.radio("Acesso", modos, horizontal=True,
                       label_visibility="collapsed", key="auth_aba")

    if escolha == "Entrar":
        _aba_entrar(conexao)
    elif escolha == "Criar conta":
        _aba_criar_conta(conexao)
    else:
        _aba_recuperar(conexao)


# ---------------------------------------------------------------------------
# Gate de acesso e navegação
# ---------------------------------------------------------------------------

if not st.session_state.get("autenticado"):
    if st.session_state.get("vista_publica") == "acesso":
        tela_autenticacao()
    else:
        landing.mostrar_landing()
    st.stop()

conexao = paginas.obter_conexao()
usuario_id = int(st.session_state["usuario_id"])

# Revalida a sessão a cada execução: uma conta desativada pelo administrador
# derruba o usuário na hora, e o perfil/período do plano são relidos do banco.
usuario_atual = obter_usuario(conexao, usuario_id)
if usuario_atual is None or not usuario_atual["ativo"]:
    st.session_state.clear()
    st.warning("Sua conta foi desativada. Procure o suporte para mais informações.")
    st.stop()

st.session_state["is_admin"] = bool(usuario_atual["is_admin"])

with st.sidebar:
    st.markdown(
        '<div style="display:flex;align-items:center;gap:.55rem;padding:.1rem 0 .45rem">'
        '<span style="font-size:1.45rem">\U0001F4C8</span>'
        "<span style=\"font-family:'Poppins',sans-serif;font-weight:600;"
        'font-size:1.02rem;color:#EAF4F2">Gestor de Investimentos</span></div>'
        f'<div style="color:#9EC9C1;font-size:.8rem;margin-bottom:.6rem">'
        f"Olá, <b style='color:#EAF4F2'>{html.escape(str(usuario_atual['usuario']))}</b>"
        "</div>",
        unsafe_allow_html=True,
    )
    rotulo_plano = saas.rotulo_plano(conexao, usuario_id)
    if saas.eh_pro(conexao, usuario_id):
        tema.mostrar_chip(f"Plano {rotulo_plano}", "pro", "\U0001F48E")
    else:
        tema.mostrar_chip(f"Plano {rotulo_plano}", "free", "\U0001F381")
    if st.session_state["is_admin"]:
        tema.mostrar_chip("Administrador", "admin", "\U0001F6E1\uFE0F")
    st.write("")
    if st.button("Sair", icon=":material/logout:", width="stretch"):
        st.session_state.clear()
        st.rerun()

paginas.carregar(usuario_id)

# A página de upload oferece um atalho para a emissão do DARF; para isso ela
# precisa da referência da página registrada na navegação.
pagina_darf = st.Page(paginas.pagina_darf, title="DARF",
                      icon=":material/request_quote:")
paginas.PAGINA_DARF = pagina_darf

paginas_investidor = [
    st.Page(paginas.pagina_upload, title="Upload de Notas",
            icon=":material/upload_file:", default=True),
    st.Page(paginas.pagina_visao, title="Visão Geral", icon=":material/dashboard:"),
    st.Page(paginas.pagina_extrato, title="Extrato", icon=":material/receipt_long:"),
    st.Page(paginas.pagina_patrimonio, title="Meu Patrimônio",
            icon=":material/account_balance_wallet:"),
    st.Page(paginas.pagina_ir, title="Apuração de IR", icon=":material/calculate:"),
    pagina_darf,
    st.Page(paginas.pagina_proventos, title="Proventos", icon=":material/payments:"),
    st.Page(paginas.pagina_relatorios, title="Relatórios", icon=":material/download:"),
    st.Page(paginas.pagina_planos, title="Planos e Assinatura",
            icon=":material/workspace_premium:"),
    st.Page(paginas.pagina_conta, title="Minha Conta", icon=":material/person:"),
]

paginas_admin = [
    st.Page(admin.pagina_dashboard, title="Visão Geral", icon=":material/insights:"),
    st.Page(admin.pagina_contas, title="Contas", icon=":material/group:"),
    st.Page(admin.pagina_assinaturas, title="Assinaturas", icon=":material/assignment:"),
    st.Page(admin.pagina_pagamentos, title="Pagamentos", icon=":material/credit_card:"),
    st.Page(admin.pagina_cupons, title="Cupons", icon=":material/local_offer:"),
    st.Page(admin.pagina_parametros, title="Parâmetros fiscais",
            icon=":material/balance:"),
]

if st.session_state["is_admin"]:
    navegacao = st.navigation({
        "Painel do investidor": paginas_investidor,
        "Administração": paginas_admin,
    })
else:
    navegacao = st.navigation(paginas_investidor)

navegacao.run()
