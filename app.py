"""
app.py
------
Ponto de entrada do painel: configura a página, carrega o estado do banco e
monta o menu lateral (``st.navigation``). O conteúdo de cada página está em
``paginas.py``.

Execução local (no Windows, chamar o Streamlit como módulo evita problemas de PATH):

    python -m streamlit run app.py

Páginas:
    1) **Upload de Notas**  — importe as notas de corretagem em PDF.
    2) **Visão Geral**      — patrimônio, evolução e últimos negócios.
    3) **Extrato**          — todas as operações, com filtros.
    4) **Meu Patrimônio**   — posição em custódia e preço médio.
    5) **Apuração de IR**   — tabela mensal com isenção e compensação.
    6) **DARF**             — valor a recolher por competência.
    7) **Proventos**        — dividendos, JCP, rendimentos e amortizações.
    8) **Relatórios**       — exportação em CSV/Excel.

As operações ficam gravadas em ``dados.db`` (SQLite), com deduplicação por
número de nota. As regras fiscais estão em ``regras.py`` e a persistência em
``persistencia.py``.

Observação: os valores apurados são uma estimativa técnica. Não substituem a
apuração oficial (GCAP/DIRPF) nem a orientação de um contador.
"""

from __future__ import annotations

import streamlit as st

import auth
import paginas
from persistencia import conectar

st.set_page_config(
    page_title="Gestor de Investimentos B3",
    page_icon="\U0001F4C8",
    layout="wide",
)


def tela_login() -> None:
    """Formulário de entrada: cria a senha no primeiro uso ou pede para autenticar."""
    conexao = conectar()
    st.title("\U0001F512 Gestor de Investimentos B3")

    if not auth.tem_usuario(conexao):
        st.subheader("Definir senha de acesso")
        st.caption(
            "Primeiro acesso: defina a senha que protegerá o app neste computador. "
            "A senha é gravada apenas como hash (PBKDF2) no ``dados.db`` local."
        )
        with st.form("form_criar_senha"):
            usuario = st.text_input("Usuário", value="investidor")
            senha = st.text_input("Nova senha", type="password")
            confirmacao = st.text_input("Confirme a senha", type="password")
            if st.form_submit_button("Criar senha", type="primary"):
                if len(senha) < auth.TAMANHO_MINIMO:
                    st.error(f"Use ao menos {auth.TAMANHO_MINIMO} caracteres.")
                elif senha != confirmacao:
                    st.error("As senhas não conferem.")
                else:
                    auth.definir_senha(conexao, usuario, senha)
                    st.session_state["autenticado"] = True
                    st.rerun()
        return

    st.subheader("Entrar")
    with st.form("form_login"):
        usuario = st.text_input("Usuário", value="investidor")
        senha = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            if auth.verificar_senha(conexao, usuario, senha):
                st.session_state["autenticado"] = True
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos.")


if not st.session_state.get("autenticado"):
    tela_login()
    st.stop()

st.sidebar.button(
    "Sair",
    on_click=lambda: st.session_state.update(autenticado=False),
    icon="\U0001F513",
)

st.title("\U0001F4C8 Gestor de Investimentos B3")
st.caption(
    "Importe notas de corretagem em PDF e acompanhe posição, proventos e IR "
    "automaticamente. Dados gravados localmente em SQLite (com deduplicação por nota)."
)

paginas.carregar()

navegacao = st.navigation([
    st.Page(paginas.pagina_upload, title="Upload de Notas", icon="\U0001F4C1", default=True),
    st.Page(paginas.pagina_visao, title="Visão Geral", icon="\U0001F4CA"),
    st.Page(paginas.pagina_extrato, title="Extrato", icon="\U0001F9FE"),
    st.Page(paginas.pagina_patrimonio, title="Meu Patrimônio", icon="\U0001F4BC"),
    st.Page(paginas.pagina_ir, title="Apuração de IR", icon="\U0001F4B0"),
    st.Page(paginas.pagina_darf, title="DARF", icon="\U0001F9EE"),
    st.Page(paginas.pagina_proventos, title="Proventos", icon="\U0001F4B5"),
    st.Page(paginas.pagina_relatorios, title="Relatórios", icon="\U0001F4E5"),
])
navegacao.run()
