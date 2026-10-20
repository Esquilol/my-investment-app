"""
landing.py
----------
Página pública de apresentação, mostrada **antes do login**: as seções
**Início**, **Planos** e **Dúvidas**, com os atalhos para **criar conta** e
**acessar a conta**.

O texto descreve apenas o que este app faz — sem métricas de audiência
inventadas nem referência a serviços de terceiros. Os planos exibidos são lidos
do banco (tabela ``planos``), o mesmo que o checkout usa, para que a página
nunca anuncie algo que o app não entrega.

Uso::

    import landing
    landing.mostrar_landing()
"""

from __future__ import annotations

import html

import streamlit as st

import persistencia as bd
import tema

MARCA = "Gestor de Investimentos B3"

#: Seções do app mostradas em cartões na landing (apenas o que ele faz hoje).
FUNCIONALIDADES = [
    {
        "icone": "\U0001F9EE",
        "titulo": "Imposto de renda",
        "texto": "Organize suas operações e acompanhe a apuração mês a mês.",
        "topicos": [
            "Apuração mensal automática",
            "Cálculo de lucros e prejuízos",
            "Compensação de prejuízos anteriores",
            "Isenção de até R$ 20 mil (ações/BDR/ouro) e R$ 35 mil (EUA)",
        ],
    },
    {
        "icone": "\U0001F4BC",
        "titulo": "Carteira",
        "texto": "Monitore patrimônio, posição em custódia e preço médio.",
        "topicos": [
            "Ações e fundos imobiliários",
            "Opções e futuros",
            "Ativos dos EUA (ações e ETFs)",
            "Evolução patrimonial",
        ],
    },
    {
        "icone": "\U0001F9FE",
        "titulo": "DARF",
        "texto": "Apure o valor a recolher por competência e controle o pagamento.",
        "topicos": [
            "Código de receita 6015",
            "Vencimento no mês seguinte",
            "Status por competência (em aberto, vencido, pago)",
        ],
    },
    {
        "icone": "\U0001F4B0",
        "titulo": "Proventos",
        "texto": "Registre proventos e acompanhe o imposto retido na fonte.",
        "topicos": [
            "Dividendos e JCP",
            "Rendimentos e amortizações",
            "IRRF retido por provento",
        ],
    },
    {
        "icone": "\U0001F4CA",
        "titulo": "Relatórios",
        "texto": "Exporte os dados da sua carteira e da apuração.",
        "topicos": [
            "Operações e posição",
            "Apuração mensal de IR",
            "Exportação em Excel/CSV (plano PRO)",
        ],
    },
    {
        "icone": "\U0001F512",
        "titulo": "Segurança",
        "texto": "Seus dados ficam isolados por conta, e a senha nunca em claro.",
        "topicos": [
            "Senha em hash PBKDF2, com sal por usuário",
            "Isolamento dos dados por usuário",
            "Sessão revalidada a cada acesso",
        ],
    },
]

#: Perguntas frequentes da seção Dúvidas.
DUVIDAS = [
    ("Serve para mim?",
     "Serve para quem investe na B3 — ações, fundos imobiliários, opções e "
     "futuros — ou em ações e ETFs dos EUA, e quer organizar o imposto de renda "
     "a partir das notas de corretagem."),
    ("Vai me ajudar com o imposto de renda?",
     "Sim. O app apura o resultado mensal por modalidade, aplica a isenção de "
     "vendas, compensa prejuízos anteriores, abate o IRRF retido e calcula o "
     "valor do DARF. O resultado é uma **estimativa técnica**: não substitui a "
     "apuração oficial (GCAP/DIRPF) nem a orientação de um contador."),
    ("Como meus investimentos entram no sistema?",
     "Você importa as notas de corretagem em **PDF**, uma ou várias de uma vez. "
     "O app lê as operações, as taxas e o IRRF de cada nota — sem digitação "
     "manual."),
    ("Quanto custa?",
     "Você começa no plano **Gratuito**, com limite de notas importadas. O plano "
     "**PRO** libera notas ilimitadas e a exportação completa. Os valores estão "
     "na seção Planos, logo acima."),
    ("O sistema é seguro?",
     "A senha é gravada apenas como *hash* PBKDF2, com sal aleatório por "
     "usuário — nunca em texto claro. Cada conta só enxerga os próprios dados, "
     "e a sessão é revalidada a cada acesso."),
    ("E se eu assinar e me arrepender?",
     "A assinatura pode ser cancelada na própria página **Planos e Assinatura**, "
     "dentro do app, sem burocracia."),
]

_CSS = """<style>
.mp-logo {
  display: flex; align-items: center; gap: .5rem; font-family: 'Poppins', sans-serif;
  font-weight: 700; font-size: 1.06rem; color: var(--mp-primaria); line-height: 1.2;
}
.mp-nav {
  display: flex; gap: 1.5rem; flex-wrap: wrap; margin: .2rem 0 1.1rem;
  border-bottom: 1px solid var(--mp-borda);
}
.mp-nav a {
  text-decoration: none; color: var(--mp-muted); font-weight: 600;
  font-size: .9rem; padding: 0 0 .55rem;
}
.mp-nav a:hover { color: var(--mp-primaria); }
.mp-card {
  background: var(--mp-superficie); border: 1px solid var(--mp-borda);
  border-radius: var(--mp-raio); padding: 1.05rem 1.15rem; height: 100%;
  box-shadow: var(--mp-sombra);
  transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}
.mp-card:hover {
  transform: translateY(-3px); border-color: rgba(23,119,108,.35);
  box-shadow: 0 16px 34px -20px rgba(16,24,40,.5);
}
.mp-card .ico { font-size: 1.4rem; }
.mp-card h4 { margin: .4rem 0 .28rem; font-size: 1rem; }
.mp-card .txt { color: var(--mp-muted); font-size: .87rem; margin: 0; }
.mp-card ul {
  margin: .5rem 0 0; padding-left: 1.05rem; color: var(--mp-muted);
  font-size: .85rem; line-height: 1.65;
}
.mp-faixa { display: flex; gap: 1rem; flex-wrap: wrap; margin: .2rem 0 1.2rem; }
.mp-faixa .item {
  flex: 1 1 180px; background: var(--mp-superficie); border: 1px solid var(--mp-borda);
  border-radius: var(--mp-raio); padding: .85rem 1rem; box-shadow: var(--mp-sombra);
}
.mp-faixa .item .rotulo {
  font-size: .74rem; text-transform: uppercase; letter-spacing: .04em;
  font-weight: 600; color: var(--mp-muted);
}
.mp-faixa .item .valor {
  font-family: 'Poppins', sans-serif; font-weight: 600; font-size: 1.12rem;
  margin-top: .2rem; color: var(--mp-primaria);
}
.mp-rodape {
  margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--mp-borda);
  color: var(--mp-muted); font-size: .8rem; line-height: 1.7;
}
</style>"""


def _e(texto) -> str:
    """Escapa texto dinâmico antes de injetar no HTML."""
    return html.escape(str(texto), quote=True)


def _moeda(valor: float) -> str:
    """Número no padrão brasileiro: ``R$ 29,90``."""
    return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _abrir_acesso(aba: str) -> None:
    """Troca a vista pública pela tela de acesso, já na aba pedida."""
    st.session_state["vista_publica"] = "acesso"
    st.session_state["auth_aba"] = aba
    st.rerun()


def _ir(ancora: str) -> str:
    """Link interno para uma seção da própria página."""
    return f'<a href="#{ancora}" target="_self">'


# ---------------------------------------------------------------------------
# Blocos da página
# ---------------------------------------------------------------------------

def _topo() -> None:
    """Marca, menu (Início/Planos/Dúvidas) e atalhos de conta."""
    marca, _, criar, entrar = st.columns([2.4, 2.4, 1.2, 1.9],
                                         vertical_alignment="center")
    with marca:
        st.markdown(f'<div class="mp-logo">\U0001F4C8 <span>{_e(MARCA)}</span></div>',
                    unsafe_allow_html=True)
    with criar:
        if st.button("Criar conta", key="nav_criar", width="stretch"):
            _abrir_acesso("Criar conta")
    with entrar:
        if st.button("Acessar minha conta", key="nav_entrar", type="primary",
                     width="stretch"):
            _abrir_acesso("Entrar")

    st.markdown(
        '<div class="mp-nav">'
        + _ir("inicio") + "Início</a>"
        + _ir("planos") + "Planos</a>"
        + _ir("duvidas") + "Dúvidas</a>"
        + "</div>",
        unsafe_allow_html=True,
    )


def _inicio() -> None:
    """Seção Início: destaque, faixa de recursos e funcionalidades."""
    st.markdown('<div id="inicio"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="mp-hero">'
        "<h1>Sua declaração de investimentos sem dor de cabeça.</h1>"
        "<p>Acompanhe seu patrimônio, apure o imposto de renda e emita o DARF num só "
        "lugar — direto das suas notas de corretagem em PDF.</p></div>",
        unsafe_allow_html=True,
    )

    col_ir, col_conta = st.columns([1, 1])
    with col_ir:
        if st.button("Resolver meu IR", key="hero_ir", type="primary", width="stretch"):
            _abrir_acesso("Criar conta")
    with col_conta:
        if st.button("Acessar minha conta", key="hero_entrar", width="stretch"):
            _abrir_acesso("Entrar")

    st.markdown(
        '<div class="mp-faixa">'
        '<div class="item"><div class="rotulo">Entrada dos dados</div>'
        '<div class="valor">Notas em PDF</div></div>'
        '<div class="item"><div class="rotulo">Apuração</div>'
        '<div class="valor">Mensal, automática</div></div>'
        '<div class="item"><div class="rotulo">Recolhimento</div>'
        '<div class="valor">DARF 6015</div></div>'
        "</div>",
        unsafe_allow_html=True,
    )

    tema.secao("O que o app faz")
    st.caption("Controle completo dos seus investimentos em um só lugar.")
    _cartoes(FUNCIONALIDADES)


def _cartoes(itens: list[dict], por_linha: int = 3) -> None:
    """Grade de cartões com ícone, título, descrição e tópicos."""
    for inicio in range(0, len(itens), por_linha):
        colunas = st.columns(por_linha)
        for coluna, item in zip(colunas, itens[inicio:inicio + por_linha]):
            topicos = "".join(f"<li>{_e(t)}</li>" for t in item.get("topicos", []))
            with coluna:
                st.markdown(
                    f'<div class="mp-card"><div class="ico">{item.get("icone", "")}</div>'
                    f'<h4>{_e(item["titulo"])}</h4>'
                    f'<p class="txt">{_e(item.get("texto", ""))}</p>'
                    + (f"<ul>{topicos}</ul>" if topicos else "")
                    + "</div>",
                    unsafe_allow_html=True,
                )


def _planos(conexao) -> None:
    """Seção Planos, com os planos reais lidos do banco."""
    st.markdown('<div id="planos"></div>', unsafe_allow_html=True)
    tema.secao("Planos")
    st.caption("Escolha o plano que melhor se encaixa nos seus objetivos como investidor.")

    planos = bd.listar_planos(conexao)
    if planos.empty:
        st.info("Os planos ainda estão sendo configurados.")
        return

    for coluna, (_, plano) in zip(st.columns(len(planos)), planos.iterrows()):
        gratuito = float(plano["preco_mensal"]) <= 0
        with coluna, st.container(border=True):
            st.markdown(f"#### {plano['nome']}")
            st.caption("Ideal para começar" if gratuito else "Para quem investe sem limite")
            st.metric("Mensalidade",
                      "Grátis" if gratuito else f"{_moeda(plano['preco_mensal'])}/mês")
            limite = ("ilimitadas" if int(plano["limite_notas"]) < 0
                      else str(int(plano["limite_notas"])))
            st.caption(f"Notas importadas: **{limite}**")
            st.caption("Exportação em Excel: "
                       + ("**sim**" if plano["exporta_excel"] else "não"))
            if plano["descricao"]:
                st.caption(plano["descricao"])
            if st.button("Criar conta", key=f"plano_{plano['codigo']}",
                         type="primary" if not gratuito else "secondary",
                         width="stretch"):
                _abrir_acesso("Criar conta")


def _duvidas() -> None:
    """Seção Dúvidas (perguntas frequentes)."""
    st.markdown('<div id="duvidas"></div>', unsafe_allow_html=True)
    tema.secao("Dúvidas antes de começar")
    st.caption("As perguntas mais comuns sobre o app, os planos e a apuração.")
    for pergunta, resposta in DUVIDAS:
        with st.expander(pergunta):
            st.markdown(resposta)

    col1, _ = st.columns([1, 3])
    with col1:
        if st.button("Criar conta grátis", key="faq_criar", type="primary",
                     width="stretch"):
            _abrir_acesso("Criar conta")


def _rodape() -> None:
    st.markdown(
        '<div class="mp-rodape">'
        f"<b>{_e(MARCA)}</b> — apuração de IR e controle de investimentos a partir das "
        "notas de corretagem.<br>"
        "Os valores apurados são uma **estimativa técnica** e não substituem a apuração "
        "oficial (GCAP/DIRPF) nem a orientação de um contador."
        "</div>",
        unsafe_allow_html=True,
    )


def mostrar_landing() -> None:
    """Renderiza a página pública completa (Início, Planos e Dúvidas)."""
    st.markdown(_CSS, unsafe_allow_html=True)
    conexao = None
    try:
        import paginas  # import local: evita ciclo entre os módulos

        conexao = paginas.obter_conexao()
    except Exception:  # banco indisponível: mostra a landing sem os planos
        conexao = None

    _topo()
    _inicio()
    if conexao is not None:
        _planos(conexao)
    _duvidas()
    _rodape()


__all__ = ["mostrar_landing", "MARCA"]
