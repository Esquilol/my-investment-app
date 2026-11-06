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

/* ---------------- Tabela Padrão Premium FiscoTrade Slim ---------------- */
.ft-tab-container {{
  width: 100%; max-width: 100%; overflow-x: auto; background: var(--mp-superficie, #ffffff);
  border: 1px solid var(--mp-borda, #e2e8f0); border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04); margin: 8px 0 16px 0;
}}
.ft-tab {{
  width: 100%; border-collapse: collapse;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 0.84rem; color: #1e293b; text-align: left;
}}
.ft-tab th {{
  background-color: #f8fafc; color: #475569; font-weight: 700;
  font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.4px;
  padding: 9px 12px; border-bottom: 2px solid #e2e8f0; white-space: nowrap;
  position: sticky; top: 0; z-index: 10;
}}
.ft-tab th.col-r {{ text-align: right; }}
.ft-tab th.col-c {{ text-align: center; }}
.ft-tab td {{
  padding: 8px 12px; border-bottom: 1px solid #f1f5f9; vertical-align: middle;
}}
.ft-tab tr:hover {{ background-color: #f8fafc; transition: background-color 0.12s ease; }}
.ft-tab tr:last-child td {{ border-bottom: none; }}
.ft-tab td.col-r {{
  text-align: right; font-variant-numeric: tabular-nums;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.84rem;
}}
.ft-tab td.col-c {{ text-align: center; }}
.ft-sub {{ font-size: 0.73rem; color: #64748b; margin-top: 2px; display: flex; align-items: center; gap: 5px; }}
.ft-sub-r {{ font-size: 0.73rem; color: #64748b; margin-top: 2px; display: flex; justify-content: flex-end; align-items: center; gap: 5px; }}
.ft-ticker {{ font-weight: 700; color: #0f172a; letter-spacing: 0.2px; font-size: 0.88rem; }}
.ft-badge-call {{ background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0; padding: 1px 5px; border-radius: 4px; font-weight: 700; font-size: 0.65rem; text-transform: uppercase; }}
.ft-badge-put {{ background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; padding: 1px 5px; border-radius: 4px; font-weight: 700; font-size: 0.65rem; text-transform: uppercase; }}
.ft-badge-darf {{ background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; padding: 2px 7px; border-radius: 5px; font-weight: 700; font-size: 0.72rem; display: inline-block; white-space: nowrap; }}
.ft-badge-isento {{ background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; padding: 2px 7px; border-radius: 5px; font-weight: 700; font-size: 0.72rem; display: inline-block; white-space: nowrap; }}
.ft-badge-acumular {{ background: #fefce8; color: #a16207; border: 1px solid #fde047; padding: 2px 7px; border-radius: 5px; font-weight: 700; font-size: 0.72rem; display: inline-block; white-space: nowrap; }}
.ft-status-aberta {{ background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 0.70rem; }}
.ft-status-encerrada {{ background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 0.70rem; }}
.ft-val-pos {{ color: #16a34a; font-weight: 700; }}
.ft-val-neg {{ color: #dc2626; font-weight: 700; }}
.ft-val-neu {{ color: #64748b; font-weight: 500; }}


/* ---------------- Tela de acesso ---------------- */
.mp-marca {{ text-align: center; margin-bottom: .6rem; }}
.mp-marca .logo {{ font-size: 2.6rem; line-height: 1; }}
.mp-marca h1 {{ font-size: 1.55rem; margin: .35rem 0 0; }}

/* ---------------- Telas pequenas ---------------- */
@media (max-width: 768px) {{
  .block-container {{ padding-left: 1rem; padding-right: 1rem; padding-top: 1rem; }}
  .mp-hero {{ padding: 20px; }} .mp-hero h1 {{ font-size: 1.34rem; }}
  .mp-hero .mp-hero-ico {{ font-size: 3.6rem; right: 12px; }}
  .mp-kpi .valor {{ font-size: 1.26rem; }}
  .mp-cabecalho h2 {{ font-size: 1.15rem; }}
  [data-testid="column"] {{ min-width: 45% !important; margin-bottom: 8px !important; }}
  .stButton > button {{ font-size: 0.82rem !important; padding: 0.4rem 0.5rem !important; }}
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


def tabela(
    dados,
    colunas_direita: list[str] | None = None,
    colunas_centro: list[str] | None = None,
    ocultar_moeda: bool = False,
    max_altura: int | None = 520,
) -> None:
    """
    Renderiza tabela HTML nativa e responsiva no padrão premium FiscoTrade Slim.
    Aplica tipografia monospace tabular em valores numéricos/monetários, badges de status,
    tickers estilizados e realce de cores (verde para positivo, vermelho para negativo).
    """
    import html as _html
    import re as _re
    import pandas as pd

    if isinstance(dados, pd.DataFrame):
        df = dados.copy()
    elif hasattr(dados, "data") and isinstance(getattr(dados, "data"), pd.DataFrame):
        df = dados.data.copy()
    elif isinstance(dados, list):
        df = pd.DataFrame(dados)
    else:
        try:
            df = pd.DataFrame(dados)
        except Exception:
            st.dataframe(dados, use_container_width=True, hide_index=True)
            return

    if df.empty:
        st.info("Nenhum registro para exibir.")
        return

    col_r_set = set(colunas_direita or [])
    col_c_set = set(colunas_centro or [])
    cols = list(df.columns)

    align_map = {}
    for c in cols:
        clow = str(c).lower().strip()
        if c in col_r_set:
            align_map[c] = "col-r"
        elif c in col_c_set:
            align_map[c] = "col-c"
        elif any(k in clow for k in [
            "valor", "preço", "preco", "custo", "total", "aloc", "notional",
            "strike", "ganho", "resultado", "lucro", "prej", "venda", "compra",
            "taxa", "ir", "darf", "base", "%", "rentab", "rend", "pago",
            "receb", "qtd", "quant", "dias", "contrat", "saldo", "patrimonio",
            "compras", "vendas", "proventos"
        ]):
            align_map[c] = "col-r"
        elif any(k in clow for k in [
            "situa", "status", "tipo", "grupo rfb", "código rfb", "codigo rfb",
            "vencimento", "alerta", "radar", "lado"
        ]):
            align_map[c] = "col-c"
        else:
            align_map[c] = ""

    style_container = f"max-height: {max_altura}px; overflow-y: auto;" if max_altura else ""
    parts = [f'<div class="ft-tab-container" style="{style_container}"><table class="ft-tab">']
    parts.append("<thead><tr>")
    for c in cols:
        cls = align_map[c]
        parts.append(f'<th class="{cls}">{_html.escape(str(c))}</th>')
    parts.append("</tr></thead><tbody>")

    for _, row in df.iterrows():
        parts.append("<tr>")
        for c in cols:
            val = row[c]
            cls = align_map[c]
            if pd.isna(val) or val is None:
                val_str = "—"
            elif isinstance(val, (float, int)) and not isinstance(val, bool):
                clow = str(c).lower().strip()
                if "%" in clow or "rentab" in clow:
                    if val > 0:
                        val_str = f"+{val:.2f} %"
                    elif val < 0:
                        val_str = f"-{abs(val):.2f} %"
                    else:
                        val_str = f"{val:.2f} %"
                elif any(k in clow for k in ["ganho", "resultado", "lucro", "prej"]):
                    if val > 0:
                        val_str = f"+R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    elif val < 0:
                        val_str = f"-R$ {abs(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    else:
                        val_str = "R$ 0,00"
                elif any(k in clow for k in ["valor", "preço", "preco", "custo", "total", "aloc", "notional", "strike", "venda", "compra", "taxa", "ir", "darf", "base", "saldo", "patrimonio", "compras", "vendas", "proventos", "pago", "receb"]):
                    if val < 0:
                        val_str = f"-R$ {abs(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    else:
                        val_str = f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                elif any(k in clow for k in ["qtd", "quant", "lancamentos", "ordens"]):
                    val_str = f"{int(val):,}".replace(",", ".")
                else:
                    val_str = str(val)
            else:
                val_str = str(val).strip()

            if ocultar_moeda and "R$" in val_str:
                val_str = _re.sub(r'R\$\s*[\d\.,-]+', 'R$ *****', val_str)

            # Badges inteligentes
            if val_str == "DARF a pagar":
                cel_html = '<span class="ft-badge-darf">🚨 DARF a pagar</span>'
            elif val_str == "Isento":
                cel_html = '<span class="ft-badge-isento">🟢 Isento</span>'
            elif val_str == "Acumular":
                cel_html = '<span class="ft-badge-acumular">🟡 Acumular</span>'
            elif val_str in ("C", "COMPRA", "CALL"):
                cel_html = f'<span class="ft-badge-call">{_html.escape(val_str)}</span>'
            elif val_str in ("V", "VENDA", "PUT"):
                cel_html = f'<span class="ft-badge-put">{_html.escape(val_str)}</span>'
            elif c in ("Ativo", "Ticker", "Código", "Opção") and _re.match(r'^[A-Za-z0-9]{4,8}$', val_str):
                cel_html = f'<span class="ft-ticker">{_html.escape(val_str)}</span>'
            else:
                is_neg = False
                if val_str.startswith("-") and any(ch.isdigit() for ch in val_str) and not _re.match(r'^\d{4}-\d{2}', val_str):
                    is_neg = True
                elif "R$ -" in val_str or "-R$" in val_str:
                    is_neg = True

                is_pos = False
                if (val_str.startswith("+") or (any(k in str(c).lower() for k in ["resultado", "lucro", "ganho", "rentab", "%", "desempenho"]) and not is_neg)):
                    if val_str not in ("0,00 %", "R$ 0,00", "0.0%", "—", "0 %", "0,00", "0.00", "0"):
                        is_pos = True

                if is_neg:
                    cel_html = f'<span class="ft-val-neg">{_html.escape(val_str)}</span>'
                elif is_pos:
                    cel_html = f'<span class="ft-val-pos">{_html.escape(val_str)}</span>'
                elif any(k in str(c).lower() for k in ["resultado", "lucro", "ganho", "rentab", "%", "desempenho"]) and val_str in ("0,00 %", "R$ 0,00", "0.0%", "—", "0 %", "0,00", "0.00", "0"):
                    cel_html = f'<span class="ft-val-neu">{_html.escape(val_str)}</span>'
                else:
                    cel_html = _html.escape(val_str)

            parts.append(f'<td class="{cls}">{cel_html}</td>')
        parts.append("</tr>")
    parts.append("</tbody></table></div>")

    html_final = "".join(parts)
    if hasattr(st, "html"):
        st.html(html_final)
    else:
        st.markdown(html_final, unsafe_allow_html=True)
