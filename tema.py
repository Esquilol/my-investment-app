"""
tema.py
-------
Sistema de design do app: paleta, tipografia e componentes visuais reutilizáveis.

A identidade é inspirada em painéis financeiros limpos — verde-petróleo como cor
de marca, superfícies claras, cantos suaves e microinterações discretas — sem
abrir mão da simplicidade: tudo é montado com o próprio Streamlit, apenas com
uma camada de CSS e pequenos componentes HTML.

Uso típico, uma vez por execução, antes de renderizar as páginas::

    import tema
    tema.aplicar()

Depois é só chamar os componentes: :func:`hero`, :func:`cabecalho`,
:func:`secao`, :func:`kpis`, :func:`chip`, :func:`vazio`.
"""

from __future__ import annotations

import html

import streamlit as st

# ---------------------------------------------------------------------------
# Paleta
# ---------------------------------------------------------------------------

PRIMARIA = "#17776C"
PRIMARIA_ESCURA = "#0E3B37"
PRIMARIA_CLARA = "#4FD1B5"
VERDE = "#1E7A46"
VERMELHO = "#C0392B"
AMBAR = "#B7791F"
MUTED = "#6B7280"
TEXTO = "#1F2933"


def _esc(texto) -> str:
    """Escapa texto dinâmico antes de injetar no HTML (evita injeção)."""
    return html.escape(str(texto), quote=True)


_FONTES = (
    "https://fonts.googleapis.com/css2?"
    "family=Poppins:wght@500;600;700&family=Inter:wght@400;500;600&display=swap"
)

_CSS = f"""
<style>
@import url('{_FONTES}');

:root {{
  --mp-primaria: {PRIMARIA};
  --mp-primaria-escura: {PRIMARIA_ESCURA};
  --mp-primaria-clara: {PRIMARIA_CLARA};
  --mp-primaria-suave: #E6F2F0;
  --mp-verde: {VERDE};
  --mp-vermelho: {VERMELHO};
  --mp-ambar: {AMBAR};
  --mp-bg: #F4F6F8;
  --mp-superficie: #FFFFFF;
  --mp-texto: {TEXTO};
  --mp-muted: {MUTED};
  --mp-borda: #E4E9ED;
  --mp-raio: 14px;
  --mp-sombra: 0 1px 2px rgba(16,24,40,.05), 0 10px 28px -18px rgba(16,24,40,.22);
}}

html, body, [class*="css"] {{
  font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
}}
h1, h2, h3, h4, h5 {{
  font-family: 'Poppins', 'Inter', sans-serif !important;
  letter-spacing: -.01em; color: var(--mp-texto);
}}

.stApp {{ background: var(--mp-bg); }}
[data-testid="stHeader"] {{ background: transparent; }}
#MainMenu, footer {{ visibility: hidden; }}

.block-container {{
  padding-top: 1.7rem; padding-bottom: 3rem; max-width: 1220px;
}}

/* ---------------- Barra lateral ---------------- */
[data-testid="stSidebar"] {{ border-right: 1px solid rgba(255,255,255,.07); }}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {{ border-radius: 10px; }}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {{
  background: rgba(255,255,255,.08);
}}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] {{
  background: rgba(79,209,181,.16);
}}

/* ---------------- Cabeçalho de página ---------------- */
.mp-cabecalho {{ display: flex; gap: 14px; align-items: center; margin: .2rem 0 1.15rem; }}
.mp-cabecalho .mp-ico {{
  width: 46px; height: 46px; border-radius: 13px; flex-shrink: 0;
  display: grid; place-items: center; font-size: 1.35rem;
  background: var(--mp-primaria-suave); color: var(--mp-primaria);
  box-shadow: inset 0 0 0 1px rgba(23,119,108,.14);
}}
.mp-cabecalho h2 {{ margin: 0; font-size: 1.32rem; font-weight: 600; }}
.mp-cabecalho p {{ margin: .12rem 0 0; color: var(--mp-muted); font-size: .87rem; }}

/* ---------------- Destaque (hero) ---------------- */
.mp-hero {{
  position: relative; overflow: hidden; border-radius: 18px;
  padding: 26px 28px; margin-bottom: 1.3rem; color: #fff;
  background: linear-gradient(120deg, {PRIMARIA_ESCURA} 0%, {PRIMARIA} 58%, #1E9E86 100%);
  box-shadow: 0 20px 44px -24px rgba(14,59,55,.8);
}}
.mp-hero:after {{
  content: ''; position: absolute; inset: 0; pointer-events: none;
  background-image:
    radial-gradient(circle at 88% 18%, rgba(79,209,181,.38), transparent 44%),
    radial-gradient(circle at 72% 130%, rgba(255,255,255,.13), transparent 46%);
}}
.mp-hero h1 {{ color: #fff; margin: 0; font-size: 1.72rem; font-weight: 600; }}
.mp-hero p {{
  margin: .4rem 0 0; color: rgba(255,255,255,.88); font-size: .95rem;
  max-width: 64ch; line-height: 1.45;
}}
.mp-hero .mp-hero-ico {{
  position: absolute; right: 22px; bottom: -16px; font-size: 5.4rem;
  opacity: .16; pointer-events: none;
}}

/* ---------------- Título de seção ---------------- */
.mp-secao {{
  display: flex; align-items: center; gap: .55rem;
  margin: 1.15rem 0 .6rem; font-family: 'Poppins', sans-serif;
  font-weight: 600; font-size: 1rem; color: var(--mp-texto);
}}
.mp-secao:before {{
  content: ''; width: 4px; height: 17px; border-radius: 4px;
  background: linear-gradient(180deg, {PRIMARIA}, {PRIMARIA_CLARA});
}}

/* ---------------- Cartões de indicador ---------------- */
.mp-kpi {{
  background: var(--mp-superficie); border: 1px solid var(--mp-borda);
  border-radius: var(--mp-raio); padding: 1rem 1.1rem; height: 100%;
  box-shadow: var(--mp-sombra);
  transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}}
.mp-kpi:hover {{
  transform: translateY(-3px);
  box-shadow: 0 16px 34px -20px rgba(16,24,40,.5);
  border-color: rgba(23,119,108,.35);
}}
.mp-kpi .rotulo {{
  display: flex; align-items: center; gap: .4rem; font-size: .76rem;
  text-transform: uppercase; letter-spacing: .04em; font-weight: 600;
  color: var(--mp-muted);
}}
.mp-kpi .valor {{
  font-family: 'Poppins', sans-serif; font-size: 1.5rem; font-weight: 600;
  margin-top: .32rem; color: var(--mp-texto); line-height: 1.15;
}}
.mp-kpi .delta {{ font-size: .8rem; font-weight: 600; margin-top: .22rem; }}
.mp-kpi.pos .valor {{ color: var(--mp-verde); }}
.mp-kpi.neg .valor {{ color: var(--mp-vermelho); }}

/* ---------------- Etiquetas (chips) ---------------- */
.mp-chip {{
  display: inline-flex; align-items: center; gap: .35rem;
  padding: .22rem .62rem; border-radius: 999px;
  font-size: .76rem; font-weight: 600;
}}
.mp-chip.pro {{ background: linear-gradient(120deg,#F4C95D,#E0A82E); color: #4a3606; }}
.mp-chip.free {{
  background: rgba(255,255,255,.13); color: #EAF4F2;
  border: 1px solid rgba(255,255,255,.26);
}}
.mp-chip.admin {{ background: rgba(79,209,181,.18); color: #BFF3E6; }}
.mp-chip.neutro {{
  background: var(--mp-primaria-suave); color: var(--mp-primaria);
}}

/* ---------------- Estado vazio ---------------- */
.mp-vazio {{
  border: 1px dashed var(--mp-borda); border-radius: var(--mp-raio);
  padding: 1.35rem 1rem; text-align: center; color: var(--mp-muted);
  background: #FBFCFD; font-size: .92rem;
}}
.mp-vazio .ico {{ font-size: 1.6rem; display: block; margin-bottom: .3rem; }}

/* ---------------- Ajustes nos widgets nativos ---------------- */
[data-testid="stMetric"] {{
  background: var(--mp-superficie); border: 1px solid var(--mp-borda);
  border-radius: var(--mp-raio); padding: .85rem 1rem;
  box-shadow: var(--mp-sombra);
  transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}}
[data-testid="stMetric"]:hover {{
  transform: translateY(-2px);
  box-shadow: 0 16px 34px -20px rgba(16,24,40,.45);
  border-color: rgba(23,119,108,.35);
}}
[data-testid="stMetricLabel"] {{
  text-transform: uppercase; letter-spacing: .03em;
  font-size: .73rem; font-weight: 600; color: var(--mp-muted);
}}
[data-testid="stMetricValue"] {{ font-family: 'Poppins', sans-serif; font-weight: 600; }}

.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
  border-radius: 10px; font-weight: 600;
  transition: transform .15s ease, box-shadow .15s ease, filter .15s ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover,
.stFormSubmitButton > button:hover {{ transform: translateY(-1px); }}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
  background: linear-gradient(120deg, {PRIMARIA}, #1E9E86);
  border: none; box-shadow: 0 12px 24px -14px rgba(23,119,108,.9);
}}

[data-testid="stExpander"] {{
  border: 1px solid var(--mp-borda); border-radius: var(--mp-raio);
  background: var(--mp-superficie); box-shadow: var(--mp-sombra); overflow: hidden;
}}
[data-testid="stExpander"] summary {{ font-weight: 600; }}

.stTabs [data-baseweb="tab-list"] {{
  gap: .3rem; border-bottom: 1px solid var(--mp-borda);
}}
.stTabs [data-baseweb="tab"] {{
  border-radius: 9px 9px 0 0; padding: .5rem .95rem; font-weight: 600;
}}
.stTabs [aria-selected="true"] {{
  background: var(--mp-primaria-suave); color: var(--mp-primaria);
}}

[data-testid="stDataFrame"] {{
  border: 1px solid var(--mp-borda); border-radius: 12px;
  overflow: hidden; box-shadow: var(--mp-sombra);
}}
[data-testid="stAlert"] {{ border-radius: 12px; }}

/* ---------------- Tela de acesso ---------------- */
.mp-marca {{ text-align: center; margin-bottom: .6rem; }}
.mp-marca .logo {{ font-size: 2.6rem; line-height: 1; }}
.mp-marca h1 {{ font-size: 1.55rem; margin: .35rem 0 0; }}

/* ---------------- Telas pequenas ---------------- */
@media (max-width: 640px) {{
  .block-container {{ padding-left: 1rem; padding-right: 1rem; padding-top: 1rem; }}
  .mp-hero {{ padding: 20px; }} .mp-hero h1 {{ font-size: 1.34rem; }}
  .mp-hero .mp-hero-ico {{ font-size: 3.6rem; right: 12px; }}
  .mp-kpi .valor {{ font-size: 1.26rem; }}
  .mp-cabecalho h2 {{ font-size: 1.15rem; }}
}}
</style>
"""


def aplicar() -> None:
    """Injeta o CSS do tema. Chamar uma vez por execução, antes das páginas."""
    st.markdown(_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Componentes
# ---------------------------------------------------------------------------

def hero(titulo: str, subtitulo: str = "", icone: str = "\U0001F4C8") -> None:
    """Faixa de destaque com gradiente da marca no topo da página."""
    st.markdown(
        f'<div class="mp-hero"><h1>{_esc(titulo)}</h1>'
        + (f"<p>{_esc(subtitulo)}</p>" if subtitulo else "")
        + f'<span class="mp-hero-ico">{icone}</span></div>',
        unsafe_allow_html=True,
    )


def cabecalho(titulo: str, subtitulo: str = "", icone: str = "\U0001F4C8") -> None:
    """Cabeçalho de página: ícone em destaque + título + descrição curta."""
    st.markdown(
        f'<div class="mp-cabecalho"><div class="mp-ico">{icone}</div><div>'
        f"<h2>{_esc(titulo)}</h2>"
        + (f"<p>{_esc(subtitulo)}</p>" if subtitulo else "")
        + "</div></div>",
        unsafe_allow_html=True,
    )


def secao(titulo: str) -> None:
    """Título de seção com a barra de acento da marca."""
    st.markdown(f'<div class="mp-secao">{_esc(titulo)}</div>', unsafe_allow_html=True)


def chip(texto: str, estilo: str = "neutro", icone: str = "") -> str:
    """Devolve o HTML de uma etiqueta (use com ``unsafe_allow_html``)."""
    prefixo = f"{icone} " if icone else ""
    return f'<span class="mp-chip {_esc(estilo)}">{prefixo}{_esc(texto)}</span>'


def mostrar_chip(texto: str, estilo: str = "neutro", icone: str = "") -> None:
    """Renderiza uma etiqueta."""
    st.markdown(chip(texto, estilo, icone), unsafe_allow_html=True)


def kpis(itens: list[dict]) -> None:
    """
    Linha de cartões de indicador.

    Cada item é um dicionário com ``rotulo`` e ``valor`` (obrigatórios) e,
    opcionalmente, ``icone``, ``delta``, ``tom`` (``"pos"``/``"neg"``) e
    ``cor_delta``.
    """
    if not itens:
        return
    colunas = st.columns(len(itens))
    for coluna, item in zip(colunas, itens):
        tom = item.get("tom", "")
        delta = item.get("delta")
        cor_delta = item.get("cor_delta", MUTED)
        with coluna:
            st.markdown(
                f'<div class="mp-kpi {_esc(tom)}">'
                f'<div class="rotulo">{item.get("icone", "")} '
                f'{_esc(item.get("rotulo", ""))}</div>'
                f'<div class="valor">{_esc(item.get("valor", ""))}</div>'
                + (f'<div class="delta" style="color:{cor_delta}">{_esc(delta)}</div>'
                   if delta else "")
                + "</div>",
                unsafe_allow_html=True,
            )


def vazio(mensagem: str, icone: str = "\U0001F4ED") -> None:
    """Estado vazio amigável, para quando ainda não há dados."""
    st.markdown(
        f'<div class="mp-vazio"><span class="ico">{icone}</span>{_esc(mensagem)}</div>',
        unsafe_allow_html=True,
    )
