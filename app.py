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

import paginas

st.set_page_config(
    page_title="Gestor de Investimentos B3",
    page_icon="\U0001F4C8",
    layout="wide",
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
