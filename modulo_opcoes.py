"""
Módulo de Gestão e Diário de Operações de Opções — FiscoTrade.

Permite ao investidor de derivativos acompanhar suas posições abertas, monitorar o
rendimento percentual, acionar a rolagem com preservação de capital (50% no bolso e 50%
reinvestido em opções líquidas próximas do dinheiro), virada de tendência (CALL <-> PUT),
visão integralizada completa das operações, edição/exclusão individual e importação de planilhas.
"""

from __future__ import annotations

from datetime import date, datetime
import pandas as pd
import streamlit as st

import paginas
import persistencia as bd
import tema


def _moeda(valor: float) -> str:
    s = f"{valor:,.2f}"
    return f"R$ {s.replace(',', 'X').replace('.', ',').replace('X', '.')}"


def _p_data(val: str | None) -> str:
    if not val:
        return "—"
    try:
        s = str(val).strip()
        if "/" in s:
            return s
        if "-" in s and len(s) >= 10:
            return date.fromisoformat(s[:10]).strftime("%d/%m/%Y")
        return s
    except Exception:
        return str(val)


def _extrair_iso_data(val: str | None) -> str | None:
    """Extrai string ISO YYYY-MM-DD para comparação precisa de datas."""
    if not val:
        return None
    s = str(val).strip()
    if "-" in s and len(s) >= 10:
        return s[:10]
    if "/" in s:
        partes = s.split("/")
        if len(partes) == 3:
            d, m, y = partes[0].zfill(2), partes[1].zfill(2), partes[2]
            if len(y) == 4:
                return f"{y}-{m}-{d}"
    return None


def _calc_rend_op(op: dict) -> float:
    """Calcula rendimento percentual de uma operação para ordenação."""
    p_pago = float(op.get("preco_pago") or 0.0)
    p_atual = float(op.get("preco_atual") or p_pago)
    if "VENDA" in str(op.get("estrutura", "")).upper():
        p_rec = float(op.get("preco_recebido") or p_pago)
        return ((p_rec - p_atual) / p_rec * 100) if p_rec > 0 else 0.0
    return ((p_atual - p_pago) / p_pago * 100) if p_pago > 0 else 0.0


# ---------------------------------------------------------------------------
# Estilos e Renderizadores de Tabelas Web Nativas (Layout Slim com Rolagem Fluida)
# ---------------------------------------------------------------------------

def _render_css_tabela() -> str:
    return (
        "<style>"
        ".ft-tab-container{width:100%;max-width:100%;overflow-x:auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.04);margin:8px 0 16px 0;}"
        ".ft-tab{width:100%;border-collapse:collapse;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:0.84rem;color:#1e293b;text-align:left;}"
        ".ft-tab th{background-color:#f8fafc;color:#475569;font-weight:700;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.4px;padding:9px 12px;border-bottom:2px solid #e2e8f0;white-space:nowrap;}"
        ".ft-tab th.col-r{text-align:right;}"
        ".ft-tab th.col-c{text-align:center;}"
        ".ft-tab td{padding:8px 12px;border-bottom:1px solid #f1f5f9;vertical-align:middle;}"
        ".ft-tab tr:hover{background-color:#f8fafc;transition:background-color 0.12s ease;}"
        ".ft-tab tr:last-child td{border-bottom:none;}"
        ".ft-tab td.col-r{text-align:right;font-variant-numeric:tabular-nums;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:0.84rem;}"
        ".ft-tab td.col-c{text-align:center;}"
        ".ft-sub{font-size:0.73rem;color:#64748b;margin-top:2px;display:flex;align-items:center;gap:5px;}"
        ".ft-sub-r{font-size:0.73rem;color:#64748b;margin-top:2px;display:flex;justify-content:flex-end;align-items:center;gap:5px;}"
        ".ft-ticker{font-weight:700;color:#0f172a;letter-spacing:0.2px;font-size:0.88rem;}"
        ".ft-badge-call{background:#f0fdf4;color:#15803d;border:1px solid #bbf7d0;padding:1px 5px;border-radius:4px;font-weight:700;font-size:0.65rem;text-transform:uppercase;}"
        ".ft-badge-put{background:#fef2f2;color:#b91c1c;border:1px solid #fecaca;padding:1px 5px;border-radius:4px;font-weight:700;font-size:0.65rem;text-transform:uppercase;}"
        ".ft-badge-rolar{background:#dcfce7;color:#15803d;border:1.5px solid #22c55e;padding:3px 8px;border-radius:5px;font-weight:800;font-size:0.72rem;display:inline-block;white-space:nowrap;}"
        ".ft-status-aberta{background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;padding:2px 6px;border-radius:4px;font-weight:600;font-size:0.70rem;}"
        ".ft-status-encerrada{background:#f1f5f9;color:#475569;border:1px solid #cbd5e1;padding:2px 6px;border-radius:4px;font-weight:600;font-size:0.70rem;}"
        ".ft-status-rolada{background:#f0fdf4;color:#15803d;border:1px solid #bbf7d0;padding:2px 6px;border-radius:4px;font-weight:600;font-size:0.70rem;}"
        ".ft-status-virada{background:#faf5ff;color:#7e22ce;border:1px solid #e9d5ff;padding:2px 6px;border-radius:4px;font-weight:600;font-size:0.70rem;}"
        ".ft-val-pos{color:#16a34a;font-weight:700;}"
        ".ft-val-neg{color:#dc2626;font-weight:700;}"
        ".ft-val-neu{color:#64748b;font-weight:500;}"
        ".ft-radar-favor{background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0;padding:2px 8px;border-radius:12px;font-weight:700;font-size:0.68rem;display:inline-flex;align-items:center;gap:3px;white-space:nowrap;}"
        ".ft-radar-contra{background:#fef2f2;color:#dc2626;border:1px solid #fecaca;padding:2px 8px;border-radius:12px;font-weight:700;font-size:0.68rem;display:inline-flex;align-items:center;gap:3px;white-space:nowrap;}"
        ".ft-radar-atencao{background:#fefce8;color:#ca8a04;border:1px solid #fef08a;padding:2px 8px;border-radius:12px;font-weight:700;font-size:0.68rem;display:inline-flex;align-items:center;gap:3px;white-space:nowrap;}"
        ".ft-radar-virada{background:#ecfdf5;color:#059669;border:1px solid #a7f3d0;padding:2px 8px;border-radius:12px;font-weight:700;font-size:0.68rem;display:inline-flex;align-items:center;gap:3px;white-space:nowrap;}"
        ".ft-radar-virada-alerta{background:#fff1f2;color:#e11d48;border:1px solid #fecdd3;padding:2px 8px;border-radius:12px;font-weight:700;font-size:0.68rem;display:inline-flex;align-items:center;gap:3px;white-space:nowrap;}"
        ".ft-radar-ind{background:#f8fafc;color:#64748b;border:1px solid #cbd5e1;padding:2px 8px;border-radius:12px;font-weight:600;font-size:0.68rem;display:inline-flex;align-items:center;gap:3px;white-space:nowrap;}"
        "</style>"
    )


def _fmt_pct(val: float) -> str:
    if val > 0.05:
        return f'<span class="ft-val-pos">+{val:.1f}% &utrif;</span>'
    elif val < -0.05:
        return f'<span class="ft-val-neg">{val:.1f}% &dtrif;</span>'
    return '<span class="ft-val-neu">+0.0% &mdash;</span>'


def _fmt_moeda_delta(val: float) -> str:
    if val > 0.01:
        return f'<span class="ft-val-pos">+{_moeda(val)} &utrif;</span>'
    elif val < -0.01:
        return f'<span class="ft-val-neg">-{_moeda(abs(val))} &dtrif;</span>'
    return f'<span class="ft-val-neu">{_moeda(0.0)} &mdash;</span>'


def _moeda_priv(valor: float, ocultar: bool = False) -> str:
    if ocultar:
        return "R$ *****"
    return _moeda(valor)


def _fmt_moeda_delta_priv(val: float, ocultar: bool = False) -> str:
    if ocultar:
        if val > 0.01:
            return '<span class="ft-val-pos">+R$ ***** &utrif;</span>'
        elif val < -0.01:
            return '<span class="ft-val-neg">-R$ ***** &dtrif;</span>'
        return '<span class="ft-val-neu">R$ ***** &mdash;</span>'
    return _fmt_moeda_delta(val)


def _badge_est(est: str | None) -> str:
    est_u = (est or "").upper()
    if "PUT" in est_u:
        return '<span class="ft-badge-put">PUT</span>'
    elif "CALL" in est_u:
        return '<span class="ft-badge-call">CALL</span>'
    return f'<span class="ft-badge-call">{est or "—"}</span>'


def _avaliar_sinal_radar(radar: dict, estrutura: str) -> dict:
    """
    Motor quantitativo proprietário de inteligência de mercado.
    Mapeia a direção do ativo em relação à estrutura da opção sem expor indicadores subjacentes.
    """
    if not radar or radar.get("status") != "ok":
        return {
            "badge_html": '<span class="ft-radar-ind" title="Aguardando dados de mercado do ativo">⚪ Em Análise</span>',
            "status_radar": "indisponivel",
        }

    tend = radar.get("tendencia")  # 'alta' ou 'baixa'
    virada_recente = radar.get("virada_recente", False)
    possivel_virada = radar.get("possivel_virada", False)

    est_u = (estrutura or "").upper()
    is_put = "PUT" in est_u
    if "VENDA" in est_u:
        quer_alta = is_put
    else:
        quer_alta = not is_put

    a_favor = (tend == "alta" and quer_alta) or (tend == "baixa" and not quer_alta)

    if virada_recente:
        if a_favor:
            badge = '<span class="ft-radar-virada" title="Tendência confirmou virada a favor da operação">🔄 Virada Confirmada</span>'
            status = "virada_favor"
        else:
            badge = '<span class="ft-radar-virada-alerta" title="Alerta: ativo confirmou virada contra a operação">🔄 Virada Detectada</span>'
            status = "virada_contra"
    elif possivel_virada:
        badge = '<span class="ft-radar-atencao" title="Ativo testando faixa chave de suporte/resistência">🟡 Possível Virada</span>'
        status = "possivel_virada"
    elif a_favor:
        badge = '<span class="ft-radar-favor" title="Ativo em tendência favorável à operação">🟢 A Favor</span>'
        status = "a_favor"
    else:
        badge = '<span class="ft-radar-contra" title="Ativo em tendência oposta à operação">🔴 Contra Tendência</span>'
        status = "contra"

    return {
        "badge_html": badge,
        "status_radar": status,
        "tendencia": tend,
    }


def _exibir_html(html_str: str) -> None:
    """Renderiza HTML de forma segura e nativa sem risco de ser interpretado como código pelo markdown."""
    if hasattr(st, "html"):
        st.html(html_str)
    else:
        st.markdown(html_str, unsafe_allow_html=True)


def _render_html_tabela_abertas(linhas: list[dict], ocultar: bool = False) -> str:
    parts = [_render_css_tabela(), '<div class="ft-tab-container"><table class="ft-tab">']
    parts.append(
        "<thead><tr>"
        "<th>Opção / Ativo</th>"
        "<th>Início / Prazo</th>"
        '<th class="col-r">Cotação</th>'
        '<th class="col-r">Performance</th>'
        '<th class="col-c">Radar Tendência</th>'
        '<th class="col-r">Alocado</th>'
        '<th class="col-c">Alerta Rolagem</th>'
        "</tr></thead><tbody>"
    )
    for row in linhas:
        rend_pct = row["rend_pct"]
        lucro_rs = row["lucro_rs"]
        atingiu = row["atingiu"]
        badge_gatilho = (
            f'<span class="ft-badge-rolar">🎯 ROLAR (+{rend_pct:.0f}%)</span>'
            if atingiu
            else '<span class="ft-val-neu">Normal</span>'
        )
        badge_radar = row.get("badge_radar", '<span class="ft-radar-ind">⚪ Em Análise</span>')
        rot_pr = "Rec:" if "VENDA" in str(row.get("estrutura", "")).upper() else "Pago:"

        destaque = row.get("destaque_dia")
        tr_style = ""
        tag_destaque = ""
        if destaque == "verde":
            tr_style = ' style="background-color: #ecfdf5 !important; border-left: 4px solid #10b981;"'
            tag_destaque = ' <span style="background: #dcfce7; color: #15803d; border: 1px solid #86efac; padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 700; text-transform: uppercase;">🟢 Nova</span>'

        parts.append(
            f"<tr{tr_style}>"
            f'<td><div><span class="ft-ticker">{row["codigo"]}</span>{tag_destaque}</div>'
            f'<div class="ft-sub">{_badge_est(row["estrutura"])} <span>{row["ativo"]}</span></div></td>'
            f'<td><div>{row["inicio"]}</div>'
            f'<div class="ft-sub">{row["dias"]} dias &bull; {row["qtd"]:,} un</div></td>'
            f'<td class="col-r"><div>{rot_pr} {_moeda_priv(row["pago"], ocultar)}</div>'
            f'<div class="ft-sub-r">Atual: <strong>{_moeda_priv(row["atual"], ocultar)}</strong></div></td>'
            f'<td class="col-r"><div>{_fmt_pct(rend_pct)}</div>'
            f'<div class="ft-sub-r">{_fmt_moeda_delta_priv(lucro_rs, ocultar)}</div></td>'
            f'<td class="col-c">{badge_radar}</td>'
            f'<td class="col-r">{_moeda_priv(row["alocado"], ocultar)}</td>'
            f'<td class="col-c">{badge_gatilho}</td>'
            "</tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _render_html_tabela_encerradas(linhas: list[dict], ocultar: bool = False) -> str:
    parts = [_render_css_tabela(), '<div class="ft-tab-container"><table class="ft-tab">']
    parts.append(
        "<thead><tr>"
        "<th>Opção / Ativo</th>"
        "<th>Período / Prazo</th>"
        '<th class="col-r">Preço (Pago ➔ Saída)</th>'
        '<th class="col-r">Capital (Aloc ➔ Final)</th>'
        '<th class="col-r">Resultado %</th>'
        '<th class="col-r">Lucro (R$)</th>'
        '<th class="col-c">Status</th>'
        "</tr></thead><tbody>"
    )
    for row in linhas:
        res_pct = row["res_pct"]
        res_fin = row["res_fin"]
        st_badge = f'<span class="ft-status-{row["status"].lower()}">{row["status"].capitalize()}</span>'
        rot_e = "Rec:" if "VENDA" in str(row.get("estrutura", "")).upper() else "Pago:"
        rot_s = "Recompra:" if "VENDA" in str(row.get("estrutura", "")).upper() else "Saída:"

        destaque = row.get("destaque_dia")
        tr_style = ""
        tag_destaque = ""
        if destaque == "vermelho":
            tr_style = ' style="background-color: #fef2f2 !important; border-left: 4px solid #ef4444;"'
            tag_destaque = ' <span style="background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 700; text-transform: uppercase;">🔴 Recente</span>'

        parts.append(
            f"<tr{tr_style}>"
            f'<td><div><span class="ft-ticker">{row["codigo"]}</span>{tag_destaque}</div>'
            f'<div class="ft-sub">{_badge_est(row["estrutura"])} <span>{row["ativo"]}</span></div></td>'
            f'<td><div>{row["inicio"]} &rarr; {row["fim"]}</div>'
            f'<div class="ft-sub">{row["dias"]} dias &bull; {row["qtd"]:,} un</div></td>'
            f'<td class="col-r"><div>{rot_e} {_moeda_priv(row["pago"], ocultar)}</div>'
            f'<div class="ft-sub-r">{rot_s} <strong>{_moeda_priv(row["recebido"], ocultar)}</strong></div></td>'
            f'<td class="col-r"><div>Aloc: {_moeda_priv(row["alocado"], ocultar)}</div>'
            f'<div class="ft-sub-r">Final: {_moeda_priv(row["final"], ocultar)}</div></td>'
            f'<td class="col-r">{_fmt_pct(res_pct)}</td>'
            f'<td class="col-r">{_fmt_moeda_delta_priv(res_fin, ocultar)}</td>'
            f'<td class="col-c">{st_badge}</td>'
            "</tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _render_html_tabela_completa(linhas: list[dict], ocultar: bool = False) -> str:
    parts = [_render_css_tabela(), '<div class="ft-tab-container"><table class="ft-tab">']
    parts.append(
        "<thead><tr>"
        "<th>Opção / Ativo</th>"
        "<th>Período / Prazo</th>"
        '<th class="col-r">Preço (Pago ➔ Saída/Atual)</th>'
        '<th class="col-r">Capital (Aloc ➔ Final)</th>'
        '<th class="col-r">Resultado %</th>'
        '<th class="col-r">Lucro (R$)</th>'
        '<th class="col-c">Status</th>'
        "</tr></thead><tbody>"
    )
    for row in linhas:
        res_pct = row["res_pct"]
        lucro_val = row["lucro_val"]
        st_badge = f'<span class="ft-status-{row["status"].lower()}">{row["status"].capitalize()}</span>'
        fim_txt = row["fim"] if row["status"] != "aberta" else "Em aberto"
        
        if row["status"] == "aberta":
            preco_str = f"{_moeda_priv(row['atual'], ocultar)} (atual)"
            final_str = "—"
            lucro_str = "—"
        else:
            preco_str = _moeda_priv(row["recebido"], ocultar)
            final_str = _moeda_priv(row["final"], ocultar)
            lucro_str = _fmt_moeda_delta_priv(lucro_val, ocultar)

        destaque = row.get("destaque_dia")
        tr_style = ""
        tag_destaque = ""
        if destaque == "verde":
            tr_style = ' style="background-color: #ecfdf5 !important; border-left: 4px solid #10b981;"'
            tag_destaque = ' <span style="background: #dcfce7; color: #15803d; border: 1px solid #86efac; padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 700; text-transform: uppercase;">🟢 Nova</span>'
        elif destaque == "vermelho":
            tr_style = ' style="background-color: #fef2f2 !important; border-left: 4px solid #ef4444;"'
            tag_destaque = ' <span style="background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 700; text-transform: uppercase;">🔴 Recente</span>'

        parts.append(
            f"<tr{tr_style}>"
            f'<td><div><span class="ft-ticker">{row["codigo"]}</span>{tag_destaque}</div>'
            f'<div class="ft-sub">{_badge_est(row["estrutura"])} <span>{row["ativo"]}</span></div></td>'
            f'<td><div>{row["inicio"]} &rarr; {fim_txt}</div>'
            f'<div class="ft-sub">{row["dias"]} dias &bull; {row["qtd"]:,} un</div></td>'
            f'<td class="col-r"><div>Pago: {_moeda_priv(row["pago"], ocultar)}</div>'
            f'<div class="ft-sub-r">Saída/Atual: <strong>{preco_str}</strong></div></td>'
            f'<td class="col-r"><div>Aloc: {_moeda_priv(row["alocado"], ocultar)}</div>'
            f'<div class="ft-sub-r">Final: {final_str}</div></td>'
            f'<td class="col-r">{_fmt_pct(res_pct)}</td>'
            f'<td class="col-r">{lucro_str}</td>'
            f'<td class="col-c">{st_badge}</td>'
            "</tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Modais de Ações do Diário
# ---------------------------------------------------------------------------



def _render_html_tabela_abertas_modo_aula(linhas: list[dict]) -> str:
    """Renderiza a tabela de posições abertas no Modo Aula (sem quantidades e sem capital alocado)."""
    parts = [_render_css_tabela(), '<div class="ft-tab-container"><table class="ft-tab">']
    parts.append(
        "<thead><tr>"
        "<th>Opção / Ativo</th>"
        "<th>Início / Prazo</th>"
        '<th class="col-r">Cotação</th>'
        '<th class="col-r">Performance (%)</th>'
        '<th class="col-c">Radar Tendência</th>'
        '<th class="col-c">Alerta Rolagem</th>'
        "</tr></thead><tbody>"
    )
    for row in linhas:
        rend_pct = float(row.get("rend_pct") or 0.0)
        atingiu = bool(row.get("atingiu") or row.get("atingiu_rolagem", False))
        badge_gatilho = (
            f'<span class="ft-badge-rolar">🎯 ROLAR (+{rend_pct:.0f}%)</span>'
            if atingiu
            else '<span class="ft-val-neu">Normal</span>'
        )
        badge_radar = row.get("radar") or row.get("badge_radar") or '<span class="ft-radar-ind">⚪ Em Análise</span>' 
        rot_pr = "Rec:" if "VENDA" in str(row.get("estrutura", "")).upper() else "Pago:"

        destaque = row.get("destaque_dia")
        tr_style = ""
        tag_destaque = ""
        if destaque == "verde":
            tr_style = ' style="background-color: #ecfdf5 !important; border-left: 4px solid #10b981;"'
            tag_destaque = ' <span style="background: #dcfce7; color: #15803d; border: 1px solid #86efac; padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 700; text-transform: uppercase;">🟢 Nova</span>'

        parts.append(
            f"<tr{tr_style}>"
            f'<td><div><span class="ft-ticker">{row["codigo"]}</span>{tag_destaque}</div>'
            f'<div class="ft-sub">{_badge_est(row["estrutura"])} <span>{row["ativo"]}</span></div></td>'
            f'<td><div>{row["inicio"]}</div>'
            f'<div class="ft-sub">{row["dias"]} dias</div></td>'
            f'<td class="col-r"><div>{rot_pr} R$ {row["pago"]:,.2f}</div>'
            f'<div class="ft-sub-r">Atual: <strong>R$ {row["atual"]:,.2f}</strong></div></td>'
            f'<td class="col-r"><div style="font-size: 0.95rem; font-weight: 700;">{_fmt_pct(rend_pct)}</div></td>'
            f'<td class="col-c">{badge_radar}</td>'
            f'<td class="col-c">{badge_gatilho}</td>'
            "</tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _render_html_planilha_sala_aula(nome_sala: str, data_hora_aula: str, linhas: list[dict], zoom_pct: str = "100%") -> str:
    """Renderiza a planilha idêntica ao modelo de apresentação do professor (ex: SALA AO VIVO)."""
    css_sala = f"""
    <style>
    @media print {{
        body {{ margin: 0; padding: 10px; background: #ffffff !important; }}
        .no-print {{ display: none !important; }}
        .sala-box {{ box-shadow: none !important; border: 1px solid #000 !important; zoom: 100% !important; }}
        .sala-header {{ background: #000000 !important; color: #22c55e !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
        .sala-row-verde {{ background-color: #dcfce7 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
        .sala-row-vermelho {{ background-color: #fecaca !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    }}
    .sala-wrapper {{ width: 100%; overflow-x: auto; margin: 10px 0 20px 0; }}
    .sala-box {{ width: 100%; border: 2px solid #1e293b; border-radius: 8px; overflow: hidden; background: #ffffff; box-shadow: 0 4px 12px rgba(0,0,0,0.08); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; zoom: {zoom_pct}; }}
    .sala-header {{ background: #000000; color: #22c55e; padding: 14px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 3px solid #22c55e; }}
    .sala-title {{ font-size: 1.6rem; font-weight: 900; letter-spacing: 1.5px; text-transform: uppercase; color: #22c55e; text-shadow: 0 0 10px rgba(34,197,94,0.4); }}
    .sala-sub {{ font-size: 0.85rem; color: #94a3b8; font-weight: 600; }}
    .sala-table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
    .sala-table th {{ background: #f8fafc; color: #0f172a; font-weight: 800; font-size: 0.72rem; text-transform: uppercase; padding: 8px 10px; border: 1px solid #cbd5e1; text-align: center; }}
    .sala-table td {{ padding: 6px 10px; border: 1px solid #cbd5e1; vertical-align: middle; }}
    .sala-table td.col-r {{ text-align: right; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .sala-table td.col-c {{ text-align: center; }}
    .sala-row-verde {{ background-color: #dcfce7 !important; color: #14532d; font-weight: 600; }}
    .sala-row-vermelho {{ background-color: #fecaca !important; color: #7f1d1d; font-weight: 600; }}
    .sala-row-roxa {{ background-color: #ede9fe !important; color: #4c1d95; font-weight: 600; }}
    </style>
    """
    parts = [css_sala, '<div class="sala-wrapper"><div class="sala-box">']
    parts.append(f"""
    <div class="sala-header">
        <div>
            <div class="sala-title">{nome_sala}</div>
            <div class="sala-sub">📅 {data_hora_aula} • 🟢 CARTEIRA ATUALIZADA</div>
        </div>
        <div class="no-print" style="display:flex;gap:10px;align-items:center;">
            <button onclick="window.print()" style="cursor:pointer;background:#22c55e;color:#000000;border:none;font-weight:800;font-size:0.75rem;padding:7px 14px;border-radius:6px;box-shadow:0 2px 6px rgba(0,0,0,0.3);">
                🖨️ Imprimir / Salvar PDF
            </button>
        </div>
    </div>
    <div style="overflow-x: auto;">
    <table class="sala-table">
        <thead>
            <tr>
                <th>CÓDIGO</th>
                <th>ESTRUTURA</th>
                <th>DATA INÍCIO</th>
                <th>DATA FINAL</th>
                <th>DIAS</th>
                <th>RECEBIDO</th>
                <th>PAGO</th>
                <th>RESULTADO</th>
                <th>SUCESSO</th>
                <th>STATUS</th>
            </tr>
        </thead>
        <tbody>
    """)

    for row in linhas:
        destaque = row.get("destaque_dia")
        st_lower = str(row.get("status", "")).lower()
        cls_tr = ""
        if destaque == "verde" or (st_lower == "aberta" and destaque == "verde"):
            cls_tr = ' class="sala-row-verde"'
        elif destaque == "vermelho" or (st_lower != "aberta" and destaque == "vermelho"):
            cls_tr = ' class="sala-row-vermelho"'

        fim_str = row.get("fim") or "—"
        if fim_str in ("—", "None", "") and st_lower == "aberta":
            fim_str = ""

        p_rec_str = f"R$ {float(row.get('recebido') or 0.0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        p_pago_str = f"R$ {float(row.get('pago') or 0.0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        res_str = f"{float(row.get('res_pct') or 0.0):+.2f}%"
        suc_str = "S" if (row.get("sucesso") == "s" or float(row.get("res_pct") or 0.0) > 0) else ""

        parts.append(f"""
            <tr{cls_tr}>
                <td style="font-weight: 700;">{row['codigo']}</td>
                <td>{row.get('estrutura', '—')}</td>
                <td class="col-c">{row['inicio']}</td>
                <td class="col-c">{fim_str}</td>
                <td class="col-c">{row.get('dias', 0)}</td>
                <td class="col-r">{p_rec_str}</td>
                <td class="col-r">{p_pago_str}</td>
                <td class="col-r" style="font-weight: 700;">{res_str}</td>
                <td class="col-c">{suc_str}</td>
                <td class="col-c" style="font-weight: 700;">{str(row.get('status', '')).capitalize()}</td>
            </tr>
        """)

    parts.append("</tbody></table></div></div></div>")
    return "".join(parts)


@st.dialog("🔄 Rolar Opção com Preservação de Capital")
def modal_rolar_opcao(op: dict) -> None:
    conexao = paginas.obter_conexao()
    usuario_id = int(st.session_state["usuario_id"])

    codigo = op["codigo"]
    preco_pago = float(op["preco_pago"])
    preco_atual = float(op["preco_atual"]) if float(op.get("preco_atual") or 0.0) > 0 else preco_pago
    quantidade = float(op["quantidade"])
    alocado = float(op["valor_alocado"])

    st.markdown(f"### Rolagem da Opção **{codigo}** ({op.get('estrutura', 'COMPRA')})")
    st.info(
        "💡 **Critério de Rolagem**: O operador realiza o lucro da posição atual, reinveste "
        "parte na nova opção (buscando opções líquidas próximas do dinheiro ATM) e preserva "
        "o restante garantido no bolso."
    )

    c1, c2 = st.columns(2)
    with c1:
        dt_rolagem = st.date_input("Data da Rolagem", value=date.today(), key="modal_rol_dt")
        data_str = dt_rolagem.strftime("%d/%m/%Y")
    with c2:
        preco_saida = st.number_input(
            "Preço de Saída da Atual (R$)",
            min_value=0.01,
            value=float(preco_atual if preco_atual > 0 else preco_pago * 2.0),
            step=0.01,
            format="%.2f",
            help="Preço unitário de saída para encerrar a perna atual.",
            key="modal_rol_preco_saida"
        )

    valor_final = quantidade * preco_saida
    if "VENDA" in str(op.get("estrutura", "")).upper():
        lucro_r = alocado - valor_final
        p_base = float(op.get("preco_recebido") or preco_pago)
        lucro_pct = ((p_base - preco_saida) / p_base * 100) if p_base > 0 else 0.0
    else:
        lucro_r = valor_final - alocado
        lucro_pct = ((preco_saida - preco_pago) / preco_pago * 100) if preco_pago > 0 else 0.0

    st.markdown("#### Configurar Nova Opção (Perna Futura)")
    nc1, nc2, nc3 = st.columns(3)
    with nc1:
        novo_codigo = st.text_input(
            "Novo Código da Opção",
            value="",
            placeholder="Ex: BEEFX400",
            help="Escolha uma opção com boa liquidez mais próxima do dinheiro (ATM).",
            key="modal_rol_novo_cod"
        ).strip().upper()
    with nc2:
        novo_preco = st.number_input(
            "Preço Unitário da Nova (R$)",
            min_value=0.01,
            value=float(preco_pago),
            step=0.01,
            format="%.2f",
            key="modal_rol_novo_preco"
        )
    with nc3:
        alvo_sugerido_50 = valor_final * 0.50
        sugestao_qtd = max(100.0, round((alvo_sugerido_50 / novo_preco) / 100) * 100) if novo_preco > 0 else 100.0
        nova_qtd = st.number_input(
            "Quantidade",
            min_value=1.0,
            value=float(sugestao_qtd),
            step=100.0,
            key="modal_rol_nova_qtd"
        )

    # Recálculo dinâmico e realista da proporção bolso vs reinvestido
    novo_alocado_calc = nova_qtd * novo_preco
    bolso_real = max(0.0, valor_final - novo_alocado_calc)
    pct_reinvestido = (novo_alocado_calc / valor_final * 100) if valor_final > 0 else 0.0
    pct_bolso = (bolso_real / valor_final * 100) if valor_final > 0 else 0.0

    st.markdown(f"""
    <div style="display: flex; gap: 10px; margin: 15px 0;">
        <div style="flex: 1; min-width: 0; background: #f8fafc; border: 1.5px solid #cbd5e1; border-radius: 8px; padding: 12px; text-align: center;">
            <div style="font-size: 0.72rem; color: #64748b; font-weight: 700; text-transform: uppercase;">Total Obtido da Saída</div>
            <div style="font-size: clamp(0.95rem, 2vw, 1.2rem); font-weight: 700; color: #0f172a; margin: 4px 0; white-space: nowrap;">{_moeda(valor_final)}</div>
            <div style="font-size: 0.75rem; color: {'#16a34a' if lucro_r >= 0 else '#dc2626'}; font-weight: 700;">{lucro_pct:+.1f}% ({_moeda(lucro_r)})</div>
        </div>
        <div style="flex: 1; min-width: 0; background: #f0fdf4; border: 1.5px solid #86efac; border-radius: 8px; padding: 12px; text-align: center;">
            <div style="font-size: 0.72rem; color: #15803d; font-weight: 700; text-transform: uppercase;">💰 {pct_bolso:.1f}% no Bolso</div>
            <div style="font-size: clamp(0.95rem, 2vw, 1.2rem); font-weight: 700; color: #166534; margin: 4px 0; white-space: nowrap;">{_moeda(bolso_real)}</div>
            <div style="font-size: 0.75rem; color: #15803d; font-weight: 600;">Caixa Livre Garantido</div>
        </div>
        <div style="flex: 1; min-width: 0; background: #eff6ff; border: 1.5px solid #93c5fd; border-radius: 8px; padding: 12px; text-align: center;">
            <div style="font-size: 0.72rem; color: #1d4ed8; font-weight: 700; text-transform: uppercase;">🚀 {pct_reinvestido:.1f}% Reinvestido</div>
            <div style="font-size: clamp(0.95rem, 2vw, 1.2rem); font-weight: 700; color: #1e40af; margin: 4px 0; white-space: nowrap;">{_moeda(novo_alocado_calc)}</div>
            <div style="font-size: 0.75rem; color: #1d4ed8; font-weight: 600;">Nova Opção ({nova_qtd:,.0f} un)</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if novo_alocado_calc > valor_final:
        st.warning(f"⚠️ O capital reinvestido ({_moeda(novo_alocado_calc)}) é maior que o valor total obtido na saída ({_moeda(valor_final)}). Será necessário um aporte de {_moeda(novo_alocado_calc - valor_final)}.")

    obs = st.text_input("Observações", value=f"Rolagem: {_moeda(bolso_real)} no bolso ({pct_bolso:.1f}%) e {_moeda(novo_alocado_calc)} reinvestido ({pct_reinvestido:.1f}%).", key="modal_rol_obs")

    if st.button("Confirmar Rolagem", type="primary", use_container_width=True, icon=":material/sync:"):
        if not novo_codigo:
            st.error("Informe o novo código da opção.")
        else:
            bd.rolar_opcao_operacao(
                conexao, usuario_id, op["id"],
                data_rolagem=data_str,
                preco_fechamento=preco_saida,
                novo_codigo=novo_codigo,
                novo_preco_pago=novo_preco,
                nova_quantidade=nova_qtd,
                observacoes=obs,
            )
            st.success(f"Rolagem executada com sucesso! {codigo} encerrada e {novo_codigo} aberta.")
            st.rerun()

@st.dialog("🔄 Virada de Tendência (CALL ⇄ PUT)")
def modal_virar_tendencia(op: dict) -> None:
    """Encerra a posição atual e abre uma nova perna no sentido oposto da tendência."""
    conexao = paginas.obter_conexao()
    usuario_id = int(st.session_state["usuario_id"])

    codigo = op["codigo"]
    estrutura_atual = op.get("estrutura", "COMPRA DE PUT")
    preco_pago = float(op["preco_pago"])
    preco_atual = float(op.get("preco_atual") or preco_pago)
    quantidade = float(op["quantidade"])
    alocado = float(op["valor_alocado"])

    # Sugestão de inversão
    if "PUT" in estrutura_atual:
        estrutura_sugerida = estrutura_atual.replace("PUT", "CALL")
    elif "CALL" in estrutura_atual:
        estrutura_sugerida = estrutura_atual.replace("CALL", "PUT")
    else:
        estrutura_sugerida = "COMPRA DE CALL"

    st.markdown(f"### Virada de Tendência da Opção **{codigo}**")
    st.caption(f"Posição atual: **{estrutura_atual}** | Alocado: **{_moeda(alocado)}** | Quantidade: **{int(quantidade):,} un**")
    st.info(
        "🔄 **Virada de Tendência**: O ativo reverteu a tendência. Encerre a perna atual "
        "e abra imediatamente a nova perna na direção oposta para acompanhar o novo movimento do mercado."
    )

    c1, c2 = st.columns(2)
    with c1:
        dt_virada = st.date_input("Data da Virada", value=date.today(), key="modal_vir_dt")
        dt_str = dt_virada.strftime("%d/%m/%Y")
    with c2:
        preco_fechamento = st.number_input(
            "Preço de Saída da Atual (R$)",
            min_value=0.00,
            value=float(preco_atual),
            step=0.01,
            format="%.2f",
            help="Preço unitário pelo qual você encerra a perna atual.",
            key="modal_vir_fech"
        )

    valor_final = quantidade * preco_fechamento
    if "VENDA" in estrutura_atual:
        res_fin = alocado - valor_final
        res_pct = ((op.get("preco_recebido", 0) - preco_fechamento) / op.get("preco_recebido", 1) * 100) if op.get("preco_recebido", 0) > 0 else 0.0
    else:
        res_fin = valor_final - alocado
        res_pct = ((preco_fechamento - preco_pago) / preco_pago * 100) if preco_pago > 0 else 0.0

    st.markdown(f"""
    <div style="background: #f8fafc; border: 1.5px solid #cbd5e1; border-radius: 8px; padding: 10px 14px; margin: 10px 0; display: flex; justify-content: space-between;">
        <span>Resultado Perna Atual: <strong style="color: {'#16a34a' if res_fin >= 0 else '#dc2626'};">{_moeda(res_fin)} ({res_pct:+.1f}%)</strong></span>
        <span>Valor Final Resgatado: <strong>{_moeda(valor_final)}</strong></span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("#### Nova Perna (Sentido Invertido)")
    nc1, nc2, nc3, nc4 = st.columns([1.5, 1.8, 1.2, 1.2])
    with nc1:
        novo_cod = st.text_input("Novo Código", placeholder="Ex: PETRC350", key="modal_vir_novo_cod").strip().upper()
    with nc2:
        estruturas = ["COMPRA DE CALL", "COMPRA DE PUT", "VENDA DE CALL", "VENDA DE PUT"]
        idx_est = estruturas.index(estrutura_sugerida) if estrutura_sugerida in estruturas else 0
        nova_est = st.selectbox("Nova Estrutura", estruturas, index=idx_est, key="modal_vir_nova_est")
    with nc3:
        novo_pago = st.number_input("Preço Pago (R$)", min_value=0.01, value=0.50, step=0.01, format="%.2f", key="modal_vir_novo_pago")
    with nc4:
        nova_qtd = st.number_input("Quantidade", min_value=1.0, value=float(quantidade), step=100.0, key="modal_vir_nova_qtd")

    novo_alocado = nova_qtd * novo_pago
    st.caption(f"Capital alocado na nova perna invertida: **{_moeda(novo_alocado)}**")
    obs_vir = st.text_input("Observações", value=f"Virada de tendência de {codigo} ({estrutura_atual}) para {novo_cod or 'nova opção'}.", key="modal_vir_obs")

    if st.button("Confirmar Virada de Tendência", type="primary", use_container_width=True, icon=":material/swap_horiz:"):
        if not novo_cod:
            st.error("Informe o código da nova opção.")
        else:
            bd.virar_tendencia_opcao_operacao(
                conexao, usuario_id, op["id"],
                data_virada=dt_str,
                preco_fechamento=preco_fechamento,
                novo_codigo=novo_cod,
                novo_preco_pago=novo_pago,
                nova_quantidade=nova_qtd,
                nova_estrutura=nova_est,
                observacoes=obs_vir,
            )
            st.success(f"Virada executada! {codigo} encerrada e {novo_cod} ({nova_est}) aberta.")
            st.rerun()


@st.dialog("🏁 Encerrar Operação (Total ou Parcial / Diminuir Mão)")
def modal_encerrar_opcao(op: dict) -> None:
    conexao = paginas.obter_conexao()
    usuario_id = int(st.session_state["usuario_id"])

    codigo = op["codigo"]
    preco_pago = float(op["preco_pago"])
    preco_atual = float(op.get("preco_atual") or preco_pago)
    quantidade = float(op["quantidade"])
    alocado = float(op["valor_alocado"])

    st.markdown(f"### Encerrar Operação **{codigo}** ({op.get('estrutura', 'COMPRA')})")
    st.caption(f"Posição atual: **{quantidade:,.0f} un** a **R$ {preco_pago:.2f}** | Cotação Atual: **R$ {preco_atual:.2f}**")

    c1, c2 = st.columns(2)
    with c1:
        dt_fim = st.date_input("Data de Encerramento", value=date.today(), key="modal_enc_dt")
        data_str = dt_fim.strftime("%d/%m/%Y")
    with c2:
        preco_saida = st.number_input(
            "Preço de Saída Unitário (R$)",
            min_value=0.00,
            value=float(preco_atual),
            step=0.01,
            format="%.2f",
            key="modal_enc_preco_saida"
        )

    qtd_encerrar = st.number_input(
        "Quantidade de Contratos a Encerrar",
        min_value=1.0,
        max_value=float(quantidade),
        value=float(quantidade),
        step=100.0,
        help=f"Deixe {quantidade:,.0f} para encerrar tudo, ou informe manualmente para realização parcial (diminuição de mão).",
        key="modal_enc_qtd"
    )

    is_parcial = qtd_encerrar < quantidade
    alocado_fechado = qtd_encerrar * preco_pago
    valor_final = qtd_encerrar * preco_saida

    if "VENDA" in str(op.get("estrutura", "")).upper():
        p_base = float(op.get("preco_recebido") or preco_pago)
        res_fin = alocado_fechado - valor_final
        res_pct = ((p_base - preco_saida) / p_base * 100) if p_base > 0 else 0.0
    else:
        res_fin = valor_final - alocado_fechado
        res_pct = ((preco_saida - preco_pago) / preco_pago * 100) if preco_pago > 0 else 0.0

    if is_parcial:
        qtd_reman = quantidade - qtd_encerrar
        aloc_reman = qtd_reman * preco_pago
        st.markdown(f"""
        <div style="background: #eff6ff; border: 1.5px solid #93c5fd; border-radius: 8px; padding: 12px; margin: 12px 0;">
            <div style="font-weight: 700; color: #1e40af; margin-bottom: 6px;">
                ⚡ Realização Parcial de Lucro (Diminuição de Mão)
            </div>
            <div style="font-size: 0.88rem; color: #1e293b; line-height: 1.5;">
                • <strong>{qtd_encerrar:,.0f} un</strong> serão encerradas com lucro de <strong style="color: {'#16a34a' if res_fin >= 0 else '#dc2626'};">{_moeda(res_fin)} ({res_pct:+.1f}%)</strong> (vai para o Histórico de Encerradas).<br>
                • <strong>{qtd_reman:,.0f} un</strong> continuarão ativas em Posições Abertas (capital alocado restante: <strong>{_moeda(aloc_reman)}</strong>).
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="background: #f8fafc; border: 1.5px solid #cbd5e1; border-radius: 8px; padding: 10px 14px; margin: 10px 0; display: flex; justify-content: space-between;">
            <span>Resultado: <strong style="color: {'#16a34a' if res_fin >= 0 else '#dc2626'};">{_moeda(res_fin)} ({res_pct:+.1f}%)</strong></span>
            <span>Valor Final Resgatado: <strong>{_moeda(valor_final)}</strong></span>
        </div>
        """, unsafe_allow_html=True)

    obs = st.text_input("Observações de Fechamento", value="", key="modal_enc_obs")

    btn_label = "Confirmar Realização Parcial" if is_parcial else "Confirmar Encerramento Total"
    if st.button(btn_label, type="primary", use_container_width=True, icon=":material/check:"):
        if is_parcial:
            bd.realizar_parcial_opcao_operacao(
                conexao, usuario_id, op["id"],
                quantidade_encerrar=qtd_encerrar,
                preco_saida=preco_saida,
                data_fim=data_str,
                observacoes=obs,
            )
            st.success(f"Realização parcial de {qtd_encerrar:,.0f} un concluída! Restam {quantidade - qtd_encerrar:,.0f} un abertas.")
        else:
            bd.encerrar_opcao_operacao(
                conexao, usuario_id, op["id"],
                data_fim=data_str,
                preco_recebido=preco_saida,
                observacoes=obs,
            )
            st.success(f"Operação {codigo} encerrada com sucesso!")
        st.rerun()


@st.dialog("➕ Aumentar Posição / Comprar Mais")
def modal_aumentar_posicao(op: dict) -> None:
    conexao = paginas.obter_conexao()
    usuario_id = int(st.session_state["usuario_id"])

    codigo = op["codigo"]
    preco_pago = float(op["preco_pago"])
    preco_atual = float(op.get("preco_atual") or preco_pago)
    quantidade = float(op["quantidade"])
    alocado = float(op["valor_alocado"])

    st.markdown(f"### Aumentar Mão na Opção **{codigo}** ({op.get('estrutura', 'COMPRA')})")
    st.info(
        "💡 **Aumento de Mão (Comprar Mais)**: Adiciona mais contratos a esta posição aberta. "
        "O sistema recalcula automaticamente a quantidade total, o novo capital alocado e o "
        "**novo preço médio ponderado (PM)** da operação."
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        dt_compra = st.date_input("Data da Nova Compra", value=date.today(), key="modal_aum_dt")
        data_str = dt_compra.strftime("%d/%m/%Y")
    with c2:
        qtd_adicional = st.number_input(
            "Quantidade a Comprar",
            min_value=1.0,
            value=100.0,
            step=100.0,
            key="modal_aum_qtd"
        )
    with c3:
        preco_adicional = st.number_input(
            "Preço da Nova Compra (R$)",
            min_value=0.01,
            value=float(preco_atual if preco_atual > 0 else preco_pago),
            step=0.01,
            format="%.2f",
            key="modal_aum_preco"
        )

    novo_aporte = qtd_adicional * preco_adicional
    nova_qtd_total = quantidade + qtd_adicional
    novo_alocado_total = alocado + novo_aporte
    novo_pm = novo_alocado_total / nova_qtd_total if nova_qtd_total > 0 else preco_pago

    st.markdown(f"""
    <div style="background: #f0fdf4; border: 1.5px solid #86efac; border-radius: 8px; padding: 12px; margin: 12px 0;">
        <div style="font-weight: 700; color: #166534; margin-bottom: 6px;">
            📊 Recálculo da Posição Ponderada
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; text-align: center; margin-top: 8px;">
            <div style="background: white; padding: 8px; border-radius: 6px; border: 1px solid #bbf7d0;">
                <div style="font-size: 0.72rem; color: #64748b; font-weight: 600;">NOVA QUANTIDADE</div>
                <div style="font-size: 1.05rem; font-weight: 700; color: #0f172a;">{nova_qtd_total:,.0f} un</div>
                <div style="font-size: 0.72rem; color: #16a34a;">+{qtd_adicional:,.0f} adicionadas</div>
            </div>
            <div style="background: white; padding: 8px; border-radius: 6px; border: 1px solid #bbf7d0;">
                <div style="font-size: 0.72rem; color: #64748b; font-weight: 600;">NOVO PREÇO MÉDIO (PM)</div>
                <div style="font-size: 1.05rem; font-weight: 700; color: #0f172a;">{_moeda(novo_pm)}</div>
                <div style="font-size: 0.72rem; color: #64748b;">Antes: {_moeda(preco_pago)}</div>
            </div>
            <div style="background: white; padding: 8px; border-radius: 6px; border: 1px solid #bbf7d0;">
                <div style="font-size: 0.72rem; color: #64748b; font-weight: 600;">NOVO CAPITAL ALOCADO</div>
                <div style="font-size: 1.05rem; font-weight: 700; color: #0f172a;">{_moeda(novo_alocado_total)}</div>
                <div style="font-size: 0.72rem; color: #16a34a;">+{_moeda(novo_aporte)} novo aporte</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    obs = st.text_input("Observações", value=f"Aumento de mão: +{qtd_adicional:,.0f} un a R$ {preco_adicional:.2f}.", key="modal_aum_obs")

    if st.button("Confirmar Aumento de Posição", type="primary", use_container_width=True, icon=":material/add:"):
        bd.aumentar_posicao_opcao_operacao(
            conexao, usuario_id, op["id"],
            quantidade_adicional=qtd_adicional,
            preco_adicional=preco_adicional,
            data_compra=data_str,
            observacoes=obs,
        )
        st.success(f"Posição de {codigo} aumentada para {nova_qtd_total:,.0f} un com novo PM de {_moeda(novo_pm)}!")
        st.rerun()

@st.dialog("✏️ Editar / Corrigir Operação")
def modal_editar_operacao(op: dict) -> None:
    """Permite alterar qualquer campo da operação e recalcula as métricas automaticamente."""
    conexao = paginas.obter_conexao()
    usuario_id = int(st.session_state["usuario_id"])

    st.markdown(f"### Editar Operação **{op['codigo']}** (ID #{op['id']})")
    st.caption("Ajuste qualquer dado da operação. Dias, valor alocado e resultados são recalculados na hora.")

    c1, c2, c3 = st.columns([1.5, 2, 1.5])
    with c1:
        novo_cod = st.text_input("Código", value=str(op["codigo"]), key="edt_cod").strip().upper()
    with c2:
        estruturas = ["COMPRA DE CALL", "COMPRA DE PUT", "VENDA DE CALL", "VENDA DE PUT", "TRAVA", "OUTRA"]
        est_atual = str(op.get("estrutura") or "COMPRA DE CALL").upper()
        idx_est = estruturas.index(est_atual) if est_atual in estruturas else 0
        nova_est = st.selectbox("Estrutura", estruturas, index=idx_est, key="edt_est")
    with c3:
        status_opts = ["aberta", "encerrada", "rolada", "virada"]
        st_atual = str(op.get("status") or "aberta").lower()
        idx_st = status_opts.index(st_atual) if st_atual in status_opts else 0
        novo_status = st.selectbox("Status", status_opts, index=idx_st, key="edt_status")

    c4, c5, c6 = st.columns(3)
    with c4:
        dt_ini_str = _p_data(op["data_inicio"])
        dt_ini = st.text_input("Data Início (DD/MM/AAAA)", value=dt_ini_str, key="edt_dt_ini")
    with c5:
        dt_fim_str = _p_data(op.get("data_fim")) if op.get("data_fim") else ""
        dt_fim = st.text_input("Data Fim (DD/MM/AAAA ou vazio)", value=dt_fim_str, key="edt_dt_fim")
    with c6:
        dias_val = op.get("dias")
        dias_in = st.number_input("Dias (0 = auto)", min_value=0, value=int(dias_val or 0), step=1, key="edt_dias")

    c7, c8, c9 = st.columns(3)
    with c7:
        qtd_in = st.number_input("Quantidade", min_value=1.0, value=float(op.get("quantidade") or 100.0), step=100.0, key="edt_qtd")
    with c8:
        pago_in = st.number_input("Preço Pago (R$)", min_value=0.00, value=float(op.get("preco_pago") or 0.0), step=0.01, format="%.2f", key="edt_pago")
    with c9:
        if novo_status == "aberta":
            preco_aux = st.number_input("Cotação Atual (R$)", min_value=0.00, value=float(op.get("preco_atual") or pago_in), step=0.01, format="%.2f", key="edt_paux")
            recebido_in = 0.0
        else:
            recebido_in = st.number_input("Preço Saída / Recebido (R$)", min_value=0.00, value=float(op.get("preco_recebido") or pago_in), step=0.01, format="%.2f", key="edt_prec")
            preco_aux = recebido_in

    obs_in = st.text_input("Observações", value=str(op.get("observacoes") or ""), key="edt_obs")

    # Preview dos cálculos
    aloc_calc = qtd_in * pago_in
    if novo_status != "aberta":
        final_calc = qtd_in * recebido_in
        if "VENDA" in nova_est:
            res_calc = aloc_calc - final_calc
            pct_calc = ((op.get("preco_recebido", 0) - recebido_in) / op.get("preco_recebido", 1) * 100) if op.get("preco_recebido", 0) > 0 else 0.0
        else:
            res_calc = final_calc - aloc_calc
            pct_calc = ((recebido_in - pago_in) / pago_in * 100) if pago_in > 0 else 0.0
        st.caption(f"Valor Alocado: **{_moeda(aloc_calc)}** | Valor Final: **{_moeda(final_calc)}** | Lucro: **{_moeda(res_calc)} ({pct_calc:+.1f}%)**")
    else:
        st.caption(f"Valor Alocado: **{_moeda(aloc_calc)}** | Cotação: **{_moeda(preco_aux)}**")

    if st.button("Salvar Alterações", type="primary", use_container_width=True, icon=":material/save:"):
        dados_atualizacao = {
            "codigo": novo_cod,
            "estrutura": nova_est,
            "status": novo_status,
            "data_inicio": dt_ini,
            "data_fim": dt_fim.strip() if dt_fim else None,
            "dias": int(dias_in) if dias_in > 0 else None,
            "quantidade": qtd_in,
            "preco_pago": pago_in,
            "preco_recebido": recebido_in,
            "preco_atual": preco_aux,
            "valor_alocado": aloc_calc,
            "observacoes": obs_in,
        }
        bd.atualizar_opcao_operacao_completa(conexao, usuario_id, op["id"], dados_atualizacao)
        st.success("Operação atualizada com sucesso!")
        st.rerun()


@st.dialog("🗑️ Excluir Operação")
def modal_excluir_operacao(op: dict) -> None:
    conexao = paginas.obter_conexao()
    usuario_id = int(st.session_state["usuario_id"])

    st.markdown(f"### Excluir Operação **{op['codigo']}**?")
    st.warning(
        f"Atenção: A operação **{op['codigo']}** ({op.get('estrutura')}) cadastrada em "
        f"**{_p_data(op['data_inicio'])}** será permanentemente removida do seu diário."
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Sim, Excluir", type="primary", use_container_width=True, icon=":material/delete:"):
            bd.excluir_opcao_operacao(conexao, usuario_id, op["id"])
            st.success("Operação removida com sucesso!")
            st.rerun()
    with c2:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


@st.dialog("✏️ Atualizar Cotação")
def modal_atualizar_cotacao(op: dict) -> None:
    conexao = paginas.obter_conexao()
    usuario_id = int(st.session_state["usuario_id"])

    codigo = op["codigo"]
    preco_pago = float(op["preco_pago"])
    preco_atual = float(op.get("preco_atual") or preco_pago)

    st.markdown(f"### Atualizar Preço Corrente de **{codigo}**")
    st.caption(f"Preço de Entrada Pago: **{_moeda(preco_pago)}**")

    novo_preco = st.number_input(
        "Cotação Atual de Mercado (R$)",
        min_value=0.01,
        value=float(preco_atual),
        step=0.01,
        format="%.2f",
        key="modal_cot_novo_preco"
    )

    if preco_pago > 0:
        rend_pct = ((novo_preco - preco_pago) / preco_pago) * 100
        st.markdown(f"**Rendimento no preço atual:** `{rend_pct:+.1f}%`")
        if rend_pct >= float(op.get("meta_rolagem_pct", 100.0)):
            st.success("🎯 **Meta de Rolagem Atingida!** Opção pronta para rolagem.")

    if st.button("Salvar Cotação", type="primary", use_container_width=True):
        bd.atualizar_cotacao_opcao(conexao, usuario_id, op["id"], novo_preco)
        st.success("Cotação atualizada.")
        st.rerun()


# ---------------------------------------------------------------------------
# Página Principal do Diário de Opções
# ---------------------------------------------------------------------------



def _secao_ambiente_modo_aula(
    conexao,
    usuario_id: int,
    sala: dict,
    ops: list[dict],
    abertas: list[dict],
    encerradas: list[dict],
    data_mais_recente_carteira: str | None,
    gatilho_global: float
) -> None:
    """Ambiente didático e de mentoria ao vivo (Modo Aula)."""
    # Configurações dinâmicas e editáveis da Sala
    nome_sala_atual = str(sala.get("nome") or "SALA AO VIVO")
    aloc_pct_atual = float(sala.get("alocacao_pct_padrao") or 1.0)
    cap_sim_atual = float(sala.get("capital_simulado_padrao") or 20000.0)

    subtitulo_padrao = f"Ambiente didático ao vivo • Metodologia: {aloc_pct_atual:.1f}% de risco por opção • Rolagem com 50% garantido no bolso"
    subtitulo_atual = str(sala.get("subtitulo_metodologia") or subtitulo_padrao)

    criterio_padrao = "embolsar 50% do valor final garantido no bolso e reinvestir os outros 50% na opção ATM mais líquida da próxima série."
    criterio_atual = str(sala.get("criterio_rolagem") or criterio_padrao)

    modo_dh_atual = str(sala.get("data_hora_modo") or "auto")
    dh_pers_atual = str(sala.get("data_hora_personalizada") or "")
    gatilho_aula_atual = float(sala.get("gatilho_rolagem_pct") or gatilho_global)

    if modo_dh_atual == "manual" and dh_pers_atual:
        data_hora_exibida = dh_pers_atual
    else:
        dt_hoje_str = date.today().strftime("%d/%m/%Y")
        hora_atual_str = datetime.now().strftime("%H:%M")
        data_hora_exibida = f"{dt_hoje_str} às {hora_atual_str}"

    # Banner superior da Sala
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #090d16 0%, #111827 100%); border: 2px solid #22c55e; border-radius: 12px; padding: 18px 24px; margin-bottom: 20px; box-shadow: 0 4px 14px rgba(34,197,94,0.15);">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
            <div>
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 1.8rem; font-weight: 900; color: #22c55e; letter-spacing: 1px;">🎓 {nome_sala_atual}</span>
                    <span style="background: #22c55e; color: #000; font-weight: 800; font-size: 0.68rem; padding: 2px 8px; border-radius: 4px; text-transform: uppercase;">Modo Aula Ativo</span>
                </div>
                <div style="font-size: 0.85rem; color: #94a3b8; margin-top: 4px;">
                    {subtitulo_atual}
                </div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 0.95rem; font-weight: 700; color: #f8fafc;">📅 {data_hora_exibida}</div>
                <div style="font-size: 0.72rem; color: #94a3b8;">Papel: <strong>{str(sala.get('papel', 'professor')).upper()}</strong></div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 1. Controles ao vivo para o professor: Atualizar Cotações em Tempo Real & Sugestão de Rolagem
    col_a_sync1, col_a_sync2 = st.columns([2, 3])
    with col_a_sync1:
        if st.button("⚡ Atualizar Cotações em Tempo Real", type="primary", use_container_width=True, icon=":material/sync:", key="btn_sync_aula_top"):
            with st.spinner("Atualizando cotações das opções com a B3..."):
                atualizadas, msg_api = bd.sincronizar_cotacoes_opcoes(conexao, usuario_id)
                if atualizadas > 0:
                    st.success(msg_api)
                    st.rerun()
                else:
                    st.info(msg_api)
    with col_a_sync2:
        st.caption("📡 **Fonte de Dados:** B3 / Yahoo Finance (Cotações de Fechamento / Último Negócio) e monitor quantitativo de derivativos.")

    # Verificar gatilhos de rolagem prontos
    rolagens_prontas_aula = []
    for o in abertas:
        p_pago = float(o["preco_pago"])
        p_atual = float(o.get("preco_atual") or p_pago)
        if p_pago > 0 and p_atual > 0:
            if "VENDA" in str(o.get("estrutura", "")).upper():
                rend = ((float(o.get("preco_recebido") or p_pago) - p_atual) / float(o.get("preco_recebido") or p_pago)) * 100
            else:
                rend = ((p_atual - p_pago) / p_pago) * 100
            if rend >= gatilho_aula_atual:
                rolagens_prontas_aula.append((o, rend))

    if rolagens_prontas_aula:
        with st.container():
            st.warning(
                f"🎯 **Gatilho de Rolagem Atingido na Aula!** {len(rolagens_prontas_aula)} opção(ões) atingiram o alvo configurado (≥{gatilho_aula_atual:.0f}%). "
                f"Critério didático da metodologia: **{criterio_atual}**"
            )
            for op_pronta, rend_pct in rolagens_prontas_aula:
                c_al1, c_al2 = st.columns([3, 1])
                with c_al1:
                    st.markdown(f"**{op_pronta['codigo']}** ({op_pronta.get('estrutura')}) — Entrada: `R$ {float(op_pronta['preco_pago']):.2f}` | Atual: `R$ {float(op_pronta.get('preco_atual') or op_pronta['preco_pago']):.2f}` | Rendimento: **+{rend_pct:.1f}%** 🚀")
                with c_al2:
                    if st.button(f"🔄 Rolar {op_pronta['codigo']}", key=f"btn_aula_rol_{op_pronta['id']}", type="primary", use_container_width=True):
                        modal_rolar_opcao(op_pronta)

    # Configurações Completas da Sala, Textos e Metodologia (Editável pelo Dono)
    with st.expander("⚙️ Personalizar Informações da Sala, Textos e Metodologia"):
        st.caption("Personalize o nome da sala, os textos exibidos no banner superior, data/hora da aula e regras didáticas de rolagem:")

        c_cf1, c_cf2 = st.columns([2, 1.2])
        with c_cf1:
            nome_sala_in = st.text_input("Nome da Sala / Aula", value=nome_sala_atual, key="cfg_sala_nome").strip()
        with c_cf2:
            gatilho_rol_in = st.number_input("Alvo de Rolagem (%)", min_value=10.0, max_value=500.0, value=gatilho_aula_atual, step=10.0, key="cfg_sala_gatilho_rol")

        subtitulo_in = st.text_input(
            "Subtítulo / Descrição da Metodologia (Exibido abaixo do nome da sala no banner)",
            value=subtitulo_atual,
            key="cfg_sala_subtitulo",
            help="Texto explicativo que aparece logo abaixo do nome da sala no banner superior."
        ).strip()

        criterio_rol_in = st.text_area(
            "Critério Didático de Rolagem (Texto exibido no alerta)",
            value=criterio_atual,
            key="cfg_sala_criterio_rol",
            help="Mensagem que explica a regra de rolagem aos alunos quando o gatilho é atingido."
        ).strip()

        c_dh1, c_dh2 = st.columns([1.5, 2])
        with c_dh1:
            modo_dh_opcoes = ["🕒 Data/Hora Automática (Ao vivo)", "✏️ Data/Hora Personalizada"]
            idx_modo_dh = 1 if modo_dh_atual == "manual" else 0
            sel_modo_dh = st.radio("Exibição da Data e Hora:", modo_dh_opcoes, index=idx_modo_dh, key="cfg_sala_modo_dh")
            novo_modo_dh = "manual" if "Personalizada" in sel_modo_dh else "auto"
        with c_dh2:
            dh_pers_in = st.text_input(
                "Data e Hora Customizada da Aula",
                value=dh_pers_atual if dh_pers_atual else data_hora_exibida,
                disabled=(novo_modo_dh == "auto"),
                key="cfg_sala_dh_pers",
                help="Exemplo: 07/11/2026 às 00:50 ou 06/11/2026 às 20:00"
            ).strip()

        c_par1, c_par2 = st.columns(2)
        with c_par1:
            aloc_padrao_in = st.number_input("Risco por Opção (%)", min_value=0.1, max_value=20.0, value=aloc_pct_atual, step=0.5, key="cfg_sala_aloc")
        with c_par2:
            cap_sim_in = st.number_input("Capital Simulado Padrão (R$)", min_value=100.0, max_value=1_000_000.0, value=cap_sim_atual, step=1000.0, key="cfg_sala_cap")

        cur_u = conexao.execute("SELECT usuario, nome FROM usuarios WHERE id = ?", (int(usuario_id),))
        u_row = cur_u.fetchone()
        prof_nome = (u_row[1] if u_row and u_row[1] else (u_row[0] if u_row else "Professor"))

        if st.button("💾 Salvar Personalizações da Sala", type="primary", icon=":material/save:"):
            bd.atualizar_config_sala_aula(
                conexao,
                sala["id"],
                nome_sala_in,
                aloc_padrao_in,
                cap_sim_in,
                subtitulo_in,
                criterio_rol_in,
                novo_modo_dh,
                dh_pers_in,
                gatilho_rol_in,
                usuario_id,
                prof_nome
            )
            st.success("Configurações e textos da sala atualizados com sucesso!")
            st.rerun()

    # Abas do Modo Aula
    aba_aula_abertas, aba_aula_print, aba_aula_simulador, aba_aula_equipe = st.tabs([
        f"🟢 Posições da Turma ({len(abertas)})",
        "📸 Print para Alunos (Visão Planilha)",
        "🧮 Simulador de Capital (Regra 1%)",
        "👥 Professores & Auditoria",
    ])

    # 1. ABA: POSIÇÕES DA TURMA (VISUAL LIMPO SEM QUANTIDADES E SEM R$)
    with aba_aula_abertas:
        if not abertas:
            st.info("Nenhuma posição aberta no momento.")
        else:
            col_cfg1, col_cfg2, col_cfg3 = st.columns([1.5, 1.5, 1.5])
            with col_cfg1:
                ativos_ab = ["Todos"] + sorted(list({str(x.get("ativo_subjacente") or x["codigo"][:4]) for x in abertas}))
                filtro_ab_ativo = st.selectbox("Filtrar por Ativo", ativos_ab, key="fil_aula_ab_ativo")
            with col_cfg2:
                est_ab = ["Todas"] + sorted(list({str(x.get("estrutura")) for x in abertas if x.get("estrutura")}))
                filtro_ab_est = st.selectbox("Filtrar por Estrutura", est_ab, key="fil_aula_ab_est")
            with col_cfg3:
                opcoes_ordem = [
                    "🔤 Ordem Alfabética (A-Z)",
                    "📅 Início: Mais Recente Primeiro",
                    "⏳ Início: Mais Antiga Primeiro",
                    "📈 Maior Rentabilidade (%)",
                    "📉 Menor Rentabilidade (%)",
                    "⏱️ Mais Dias em Aberto",
                ]
                ordem_sel = st.selectbox("Ordenar Posições por:", opcoes_ordem, index=0, key="sel_ordem_aula_abertas")

            abertas_filtradas = abertas
            if filtro_ab_ativo != "Todos":
                abertas_filtradas = [o for o in abertas_filtradas if (o.get("ativo_subjacente") or o["codigo"][:4]) == filtro_ab_ativo]
            if filtro_ab_est != "Todas":
                abertas_filtradas = [o for o in abertas_filtradas if o.get("estrutura") == filtro_ab_est]

            if ordem_sel == "🔤 Ordem Alfabética (A-Z)":
                abertas_filtradas.sort(key=lambda x: (str(x.get("codigo", "")).upper(), x.get("id", 0)))
            elif ordem_sel == "📅 Início: Mais Recente Primeiro":
                abertas_filtradas.sort(key=lambda x: (_extrair_iso_data(x.get("data_inicio")) or "", str(x.get("codigo", "")).upper()), reverse=True)
            elif ordem_sel == "⏳ Início: Mais Antiga Primeiro":
                abertas_filtradas.sort(key=lambda x: (_extrair_iso_data(x.get("data_inicio")) or "", str(x.get("codigo", "")).upper()))
            elif ordem_sel == "📈 Maior Rentabilidade (%)":
                abertas_filtradas.sort(key=lambda x: (_calc_rend_op(x), str(x.get("codigo", "")).upper()), reverse=True)
            elif ordem_sel == "📉 Menor Rentabilidade (%)":
                abertas_filtradas.sort(key=lambda x: (_calc_rend_op(x), str(x.get("codigo", "")).upper()))
            elif ordem_sel == "⏱️ Mais Dias em Aberto":
                abertas_filtradas.sort(key=lambda x: (int(x.get("dias") or bd._calcular_dias_operacao(x.get("data_inicio"))), str(x.get("codigo", "")).upper()), reverse=True)

            # Radar de tendência
            ativos_sub_unicos = {str(x.get("ativo_subjacente") or x["codigo"][:4]) for x in abertas_filtradas}
            radares_map = {at: bd.obter_radar_tendencia_ativo(at) for at in ativos_sub_unicos}

            linhas_abertas_aula = []
            for op in abertas_filtradas:
                p_pago = float(op["preco_pago"])
                p_atual = float(op.get("preco_atual") or p_pago)
                qtd_op = float(op["quantidade"])
                if "VENDA" in str(op.get("estrutura", "")).upper():
                    p_rec = float(op.get("preco_recebido") or p_pago)
                    rend_pct = ((p_rec - p_atual) / p_rec * 100) if p_rec > 0 else 0.0
                else:
                    rend_pct = ((p_atual - p_pago) / p_pago * 100) if p_pago > 0 else 0.0

                atingiu = rend_pct >= gatilho_global
                dias_op = op.get("dias") or bd._calcular_dias_operacao(op["data_inicio"])
                ativo_nome = str(op.get("ativo_subjacente") or op["codigo"][:4])
                dados_radar = radares_map.get(ativo_nome, {})
                sinal_radar = _avaliar_sinal_radar(dados_radar, op.get("estrutura", ""))

                d_op_ini = _extrair_iso_data(op.get("data_inicio"))
                destaque_dia = "verde" if (d_op_ini and d_op_ini == data_mais_recente_carteira) else None

                linhas_abertas_aula.append({
                    "id": op["id"],
                    "codigo": op["codigo"],
                    "ativo": op.get("ativo_subjacente") or op["codigo"][:4],
                    "estrutura": op.get("estrutura", "—"),
                    "inicio": _p_data(op["data_inicio"]),
                    "dias": int(dias_op),
                    "pago": p_pago,
                    "atual": p_atual,
                    "rend_pct": rend_pct,
                    "atingiu": atingiu,
                    "atingiu_rolagem": atingiu,
                    "radar": sinal_radar,
                    "badge_radar": sinal_radar,
                    "destaque_dia": destaque_dia,
                })

            _exibir_html(_render_html_tabela_abertas_modo_aula(linhas_abertas_aula))

            # Ações pedagógicas rápidas (sem exibir finanças privadas)
            st.markdown("##### ⚡ Execuções em Aula (Rolagem / Virada de Tendência)")
            ops_dict = {
                o["id"]: f"{o['codigo']} ({o.get('estrutura')}) — Entrada: {_p_data(o['data_inicio'])} [{o['preco_pago']:.2f}]"
                for o in abertas
            }
            col_a1, col_a2, col_a3, col_a4 = st.columns([3, 1.2, 1.2, 1.2])
            with col_a1:
                op_sel_id = st.selectbox(
                    "Selecione uma opção da carteira para interagir:",
                    options=list(ops_dict.keys()),
                    format_func=lambda i: ops_dict[i],
                    key="sel_op_modo_aula_acao"
                )
            op_alvo = next((o for o in abertas if o["id"] == op_sel_id), None)
            if op_alvo:
                with col_a2:
                    if st.button("🔄 Rolar Opção", type="primary", use_container_width=True, key="btn_aula_rol"):
                        modal_rolar_opcao(op_alvo)
                with col_a3:
                    if st.button("🔀 Virar Tendência", use_container_width=True, key="btn_aula_virar"):
                        modal_virar_tendencia(op_alvo)
                with col_a4:
                    if st.button("✏️ Editar", use_container_width=True, key="btn_aula_edt"):
                        modal_editar_operacao(op_alvo)

    # 2. ABA: PRINT PARA ALUNOS (VISÃO PLANILHA SALA AO VIVO)
    with aba_aula_print:
        st.markdown(f"#### 📸 Visão Planilha de Apresentação — {sala['nome']}")
        st.caption("Visão da carteira atualizada para a aula: posições abertas atuais + fechamentos do dia (destaque em cores). Posições antigas já fechadas são filtradas automaticamente.")

        # Linhas: APENAS posições abertas + posições encerradas NO DIA (fechamento mais recente)
        linhas_planilha = []
        for o in abertas:
            p_pago = float(o.get("preco_pago") or 0.0)
            p_rec = float(o.get("preco_recebido") or 0.0)
            p_atual = float(o.get("preco_atual") or p_pago)
            dias_op = o.get("dias") or bd._calcular_dias_operacao(o.get("data_inicio"), o.get("data_fim"))
            if "VENDA" in str(o.get("estrutura", "")).upper():
                base_c = p_rec if p_rec > 0 else p_pago
                res_pct = ((base_c - p_atual) / base_c * 100) if base_c > 0 else 0.0
            else:
                res_pct = ((p_atual - p_pago) / p_pago * 100) if p_pago > 0 else 0.0

            d_ini = _extrair_iso_data(o.get("data_inicio"))
            # Aberta no dia de alteração -> Verde! Mantida de dias anteriores -> Sem destaque
            destaque = "verde" if (d_ini and d_ini == data_mais_recente_carteira) else None

            linhas_planilha.append({
                "codigo": o["codigo"],
                "estrutura": o.get("estrutura", "—"),
                "inicio": _p_data(o.get("data_inicio")),
                "fim": "",
                "dias": int(dias_op),
                "pago": p_pago,
                "recebido": p_atual,
                "res_pct": res_pct,
                "sucesso": "s" if res_pct > 0 else "n",
                "status": "aberta",
                "destaque_dia": destaque,
            })

        for o in encerradas:
            d_fim = _extrair_iso_data(o.get("data_fim"))
            # Apenas encerramentos do dia!
            if d_fim and d_fim == data_mais_recente_carteira:
                p_pago = float(o.get("preco_pago") or 0.0)
                p_rec = float(o.get("preco_recebido") or 0.0)
                dias_op = o.get("dias") or bd._calcular_dias_operacao(o.get("data_inicio"), o.get("data_fim"))
                res_pct = float(o.get("resultado_pct") or 0.0)

                linhas_planilha.append({
                    "codigo": o["codigo"],
                    "estrutura": o.get("estrutura", "—"),
                    "inicio": _p_data(o.get("data_inicio")),
                    "fim": _p_data(o.get("data_fim")),
                    "dias": int(dias_op),
                    "pago": p_pago,
                    "recebido": p_rec,
                    "res_pct": res_pct,
                    "sucesso": o.get("sucesso", "s" if res_pct > 0 else "n"),
                    "status": o.get("status", "encerrada"),
                    "destaque_dia": "vermelho",
                })

        # Ordenar por código
        linhas_planilha.sort(key=lambda x: (0 if str(x.get("status")).lower() == "aberta" else 1, str(x.get("codigo")).upper()))

        # Controles de Zoom e Link Temporário
        c_zoom, c_link = st.columns([2.5, 2])
        with c_zoom:
            zoom_sel = st.select_slider(
                "🔍 Escala / Zoom da Planilha (Ajuste para Caber na Tela da Live):",
                options=["70%", "80%", "85%", "90%", "95%", "100%", "110%", "120%"],
                value="100%",
                key="slider_zoom_aula_planilha"
            )
        with c_link:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            if st.button("🔗 Gerar Link Temporário para Alunos (Válido 20h)", type="secondary", icon=":material/share:", use_container_width=True):
                novo_token = bd.criar_link_temporario_aula(conexao, sala["id"], usuario_id, horas_validade=20)
                st.session_state["ultimo_token_aula"] = novo_token

        if "ultimo_token_aula" in st.session_state:
            tok = st.session_state["ultimo_token_aula"]
            link_alunos = f"?view=print_aula&token={tok}"
            st.success("✅ **Link Temporário Gerado com Sucesso! Válido por 20 horas.**")
            st.info("Copie e envie aos alunos para que eles abram a planilha ao vivo em tela cheia e tirem prints diretamente:")
            st.code(link_alunos, language="text")

        # Exibição da Planilha Sala de Aula
        _exibir_html(_render_html_planilha_sala_aula(nome_sala_atual, data_hora_exibida, linhas_planilha, zoom_pct=zoom_sel))

        # Texto pronto para copiar para o grupo de alunos
        with st.expander("📋 Texto Pronto para Copiar p/ Alunos (Telegram / WhatsApp)"):
            tot_ab = len(abertas)
            vitoriosas_enc = len([o for o in encerradas if o.get("sucesso") == "s"])
            win_rate_calc = (vitoriosas_enc / len(encerradas) * 100) if encerradas else 100.0

            resumo_zap = f"""🚀 *AULA AO VIVO — {sala['nome']}*
📅 *Data:* {dt_hoje_str} às {hora_atual_str}

📊 *STATUS DA CARTEIRA DIDÁTICA:*
• Posições Abertas Ativas: {tot_ab} opções
• Operações Encerradas no Método: {len(encerradas)} trades
• Taxa de Acerto (Win Rate): {win_rate_calc:.1f}%

🎯 *REGRAS DA METODOLOGIA:*
1. Alocação disciplinada de {sala.get('alocacao_pct_padrao', 1.0):.1f}% do capital por opção.
2. Rolagem de preservação com 50% de lucro garantido no bolso.
3. Virada de tendência quando o radar quantitativo sinalizar inversão."""
            st.code(resumo_zap, language="text")

    # 3. ABA: SIMULADOR DE CAPITAL DO ALUNO (COMPOSTAGEM DIDÁTICA E DINÂMICA DE CAIXA)
    with aba_aula_simulador:
        st.markdown("#### 🧮 Simulador de Crescimento de Carteira do Aluno")
        st.info(
            f"💡 **Dinâmica Didática de Alocação e Gestão de Caixa**: "
            "Defina o capital total do aluno (ex: R$ 20.000,00) e o limite de risco (ex: 1% por opção). "
            "A cada entrada, o aluno desembolsa o valor correspondente (ex: R$ 200,00 por trade). "
            "Ao encerrar uma opção, o capital investido retorna ao caixa somado ao lucro ou deduzido do prejuízo obtido."
        )

        scol1, scol2 = st.columns(2)
        with scol1:
            sim_cap_inicial = st.number_input(
                "Capital Inicial Total do Aluno (R$)",
                min_value=100.0,
                max_value=10_000_000.0,
                value=float(sala.get("capital_simulado_padrao", 20000.0)),
                step=1000.0,
                format="%.2f",
                key="sim_aluno_cap_ini"
            )
        with scol2:
            sim_pct_risco = st.number_input(
                "Risco / Alocação por Opção (%)",
                min_value=0.1,
                max_value=20.0,
                value=float(sala.get("alocacao_pct_padrao", 1.0)),
                step=0.5,
                format="%.1f",
                key="sim_aluno_pct_risco"
            )

        aloc_por_trade = sim_cap_inicial * (sim_pct_risco / 100.0)

        # Ordenação cronológica das operações fechadas (do início ao fim)
        enc_cron = list(encerradas)
        enc_cron.sort(key=lambda x: (_extrair_iso_data(x.get("data_fim")) or _extrair_iso_data(x.get("data_inicio")) or "", x.get("id", 0)))

        saldo_caixa = sim_cap_inicial
        tabela_simulada = []
        lucro_realizado_total_sim = 0.0

        for i, op in enumerate(enc_cron, 1):
            res_pct = float(op.get("resultado_pct") or 0.0)
            lucro_trade = aloc_por_trade * (res_pct / 100.0)
            retorno_caixa = aloc_por_trade + lucro_trade
            saldo_caixa += lucro_trade
            lucro_realizado_total_sim += lucro_trade

            tabela_simulada.append({
                "#": i,
                "Opção": op["codigo"],
                "Estrutura": op.get("estrutura", "—"),
                "Data Saída": _p_data(op.get("data_fim")),
                "Alocado (1%)": f"R$ {aloc_por_trade:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                "Resultado (%)": f"{res_pct:+.1f}%",
                "Lucro do Aluno": f"{'+' if lucro_trade >= 0 else '-'}R$ {abs(lucro_trade):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                "Retorno ao Caixa": f"R$ {retorno_caixa:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                "Caixa Acumulado": f"R$ {saldo_caixa:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            })

        # Alocação atual em aberto
        total_alocado_aberto = len(abertas) * aloc_por_trade
        caixa_livre_hoje = max(0.0, saldo_caixa - total_alocado_aberto)

        # Flutuante em aberto
        lucro_flutuante_aberto = 0.0
        for op in abertas:
            p_pago = float(op.get("preco_pago") or 0.0)
            p_atual = float(op.get("preco_atual") or p_pago)
            if p_pago > 0:
                rend_ab = ((p_atual - p_pago) / p_pago) if "VENDA" not in str(op.get("estrutura", "")).upper() else ((p_pago - p_atual) / p_pago)
                lucro_flutuante_aberto += (aloc_por_trade * rend_ab)

        patrimonio_total_sim = saldo_caixa + lucro_flutuante_aberto
        lucro_liquido_total_sim = patrimonio_total_sim - sim_cap_inicial
        pct_total_sim = (lucro_liquido_total_sim / sim_cap_inicial * 100) if sim_cap_inicial > 0 else 0.0

        # Cards com layout amplo em CSS responsivo (sem truncamento '10.000,...')
        c_ini_fmt = f"R$ {sim_cap_inicial:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        aloc_fmt = f"R$ {aloc_por_trade:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        caixa_fmt = f"R$ {caixa_livre_hoje:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        aloc_ab_fmt = f"R$ {total_alocado_aberto:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        lucro_fmt = f"{'+' if lucro_realizado_total_sim >= 0 else '-'}R$ {abs(lucro_realizado_total_sim):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        patr_fmt = f"R$ {patrimonio_total_sim:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        st.markdown(f"""
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin:15px 0 20px 0;">
            <div style="flex:1;min-width:180px;background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;box-shadow:0 2px 6px rgba(0,0,0,0.04);">
                <div style="font-size:0.75rem;font-weight:700;color:#64748b;text-transform:uppercase;">💼 Capital Inicial</div>
                <div style="font-size:1.25rem;font-weight:900;color:#0f172a;white-space:nowrap;margin-top:4px;">{c_ini_fmt}</div>
                <div style="font-size:0.75rem;color:#94a3b8;margin-top:2px;">Base de partida</div>
            </div>
            <div style="flex:1;min-width:180px;background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;box-shadow:0 2px 6px rgba(0,0,0,0.04);">
                <div style="font-size:0.75rem;font-weight:700;color:#64748b;text-transform:uppercase;">🎯 Entrada por Opção ({sim_pct_risco:.1f}%)</div>
                <div style="font-size:1.25rem;font-weight:900;color:#0d9488;white-space:nowrap;margin-top:4px;">{aloc_fmt}</div>
                <div style="font-size:0.75rem;color:#94a3b8;margin-top:2px;">Desembolso por trade</div>
            </div>
            <div style="flex:1;min-width:180px;background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;box-shadow:0 2px 6px rgba(0,0,0,0.04);">
                <div style="font-size:0.75rem;font-weight:700;color:#64748b;text-transform:uppercase;">💵 Caixa Livre Disponível</div>
                <div style="font-size:1.25rem;font-weight:900;color:#1e293b;white-space:nowrap;margin-top:4px;">{caixa_fmt}</div>
                <div style="font-size:0.75rem;color:#94a3b8;margin-top:2px;">Disponível para compras</div>
            </div>
            <div style="flex:1;min-width:180px;background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;box-shadow:0 2px 6px rgba(0,0,0,0.04);">
                <div style="font-size:0.75rem;font-weight:700;color:#64748b;text-transform:uppercase;">📊 Alocado em Aberto</div>
                <div style="font-size:1.25rem;font-weight:900;color:#3b82f6;white-space:nowrap;margin-top:4px;">{aloc_ab_fmt}</div>
                <div style="font-size:0.75rem;color:#94a3b8;margin-top:2px;">{len(abertas)} opções ativas</div>
            </div>
            <div style="flex:1;min-width:180px;background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;box-shadow:0 2px 6px rgba(0,0,0,0.04);">
                <div style="font-size:0.75rem;font-weight:700;color:#64748b;text-transform:uppercase;">💰 Lucro Realizado</div>
                <div style="font-size:1.25rem;font-weight:900;color:#16a34a;white-space:nowrap;margin-top:4px;">{lucro_fmt}</div>
                <div style="font-size:0.75rem;color:#16a34a;margin-top:2px;font-weight:700;">{len(enc_cron)} trades fechados</div>
            </div>
            <div style="flex:1;min-width:180px;background:#ffffff;border:2px solid #16a34a;border-radius:10px;padding:14px 16px;box-shadow:0 2px 6px rgba(22,163,74,0.12);">
                <div style="font-size:0.75rem;font-weight:700;color:#16a34a;text-transform:uppercase;">🚀 Patrimônio Total</div>
                <div style="font-size:1.25rem;font-weight:900;color:#0f172a;white-space:nowrap;margin-top:4px;">{patr_fmt}</div>
                <div style="font-size:0.75rem;color:#16a34a;margin-top:2px;font-weight:700;">{pct_total_sim:+.1f}% de crescimento</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if not tabela_simulada:
            st.info("Ainda não há operações encerradas para exibir o histórico cronológico de trades do aluno.")
        else:
            st.markdown("##### 📜 Histórico de Retornos das Operações Encerradas do Aluno")
            tema.tabela(pd.DataFrame(tabela_simulada))

    # 4. ABA: PROFESSORES & AUDITORIA
    with aba_aula_equipe:
        st.markdown(f"#### 👥 Equipe de Professores da {sala['nome']}")
        st.caption("Acesso compartilhado entre professores da sala. Registro oficial por nome completo e data de ingresso.")

        professores = bd.listar_professores_sala(conexao, sala["id"])
        linhas_prof = []
        for p in professores:
            # Formatar data de Brasília sem hora: DD/MM/YYYY
            dt_raw = str(p.get("adicionado_em") or "")
            dt_br = dt_raw[:10]
            if len(dt_br.split("-")) == 3:
                ano, mes, dia = dt_br.split("-")
                dt_br = f"{dia}/{mes}/{ano}"

            linhas_prof.append({
                "Professor (Nome Completo)": p.get("nome") or p.get("usuario") or "Professor",
                "Data de Ingresso": dt_br,
                "Papel": "Proprietário da Sala" if p.get("papel") == "dono" else "Professor Convidado",
                "vinculo_id": p.get("vinculo_id"),
                "usuario_id": p.get("usuario_id"),
                "papel_raw": p.get("papel"),
            })

        df_prof_vis = pd.DataFrame(linhas_prof)[["Professor (Nome Completo)", "Data de Ingresso", "Papel"]]
        st.dataframe(df_prof_vis, use_container_width=True, hide_index=True)

        # Adicionar novo professor por E-mail e CPF
        if sala.get("papel") == "dono":
            with st.expander("➕ Adicionar Professor à Equipe (por E-mail e CPF)"):
                st.caption("Informe o e-mail e CPF cadastrados do professor para localizá-lo e conceder acesso:")
                with st.form("form_add_prof_email_cpf"):
                    col_p1, col_p2 = st.columns(2)
                    with col_p1:
                        email_add_prof = st.text_input("E-mail de Cadastro do Professor", placeholder="exemplo@email.com").strip()
                    with col_p2:
                        cpf_add_prof = st.text_input("CPF do Professor", placeholder="000.000.000-00 ou apenas dígitos").strip()

                    btn_salvar_prof = st.form_submit_button("➕ Buscar e Salvar Professor", type="primary", use_container_width=True)
                    if btn_salvar_prof:
                        if not email_add_prof or not cpf_add_prof:
                            st.error("Informe tanto o e-mail quanto o CPF do professor cadastrado.")
                        else:
                            u_achado = bd.buscar_usuario_por_email_cpf(conexao, email_add_prof, cpf_add_prof)
                            if not u_achado:
                                st.error("Nenhum usuário cadastrado foi encontrado com esse e-mail e CPF. Verifique os dados.")
                            else:
                                achado_id = int(u_achado["id"])
                                if any(p["usuario_id"] == achado_id for p in professores):
                                    st.warning("Este professor já está cadastrado na equipe desta sala.")
                                else:
                                    # Ativa permissão de modo aula no usuário se necessário
                                    conexao.execute("UPDATE usuarios SET permite_modo_aula = 1 WHERE id = ?", (achado_id,))
                                    bd.adicionar_professor_sala(conexao, sala["id"], achado_id, usuario_id, prof_nome, papel="professor")
                                    st.success(f"Professor(a) **{u_achado.get('nome') or u_achado.get('usuario')}** adicionado(a) com sucesso!")
                                    st.rerun()

            # Opção de remover professor convidado
            profs_convidados = [p for p in linhas_prof if p["papel_raw"] != "dono"]
            if profs_convidados:
                with st.expander("🗑️ Gerenciar / Remover Acesso de Professor Convidado"):
                    opcoes_rem = {p["usuario_id"]: p["Professor (Nome Completo)"] for p in profs_convidados}
                    prof_rem_id = st.selectbox("Selecione o professor para revogar o acesso:", options=list(opcoes_rem.keys()), format_func=lambda i: opcoes_rem[i], key="sel_rem_prof_sala")
                    if st.button("Revogar Acesso do Professor", type="secondary"):
                        bd.remover_professor_sala(conexao, sala["id"], prof_rem_id, usuario_id, prof_nome)
                        st.success("Acesso revogado com sucesso.")
                        st.rerun()

        st.markdown("##### 📋 Trilha de Auditoria da Sala (Quem Alterou o Quê)")
        logs = bd.listar_logs_sala(conexao, sala["id"], limite=40)
        if not logs:
            st.info("Nenhuma alteração registrada ainda nesta sala.")
        else:
            tema.tabela(pd.DataFrame(logs)[["data_hora", "autor_nome", "acao", "detalhes"]])


def pagina_diario_opcoes() -> None:
    tema.cabecalho(
        "Gestão e Diário de Opções",
        "Acompanhe suas operações, controle posições abertas, realize rolagens com preservação de capital e virada de tendência.",
        "📈"
    )
    conexao = paginas.obter_conexao()
    usuario_id = int(st.session_state["usuario_id"])

    # Controle do Modo Print / Privacidade (Ocultar R$)
    if "opcoes_ocultar_moeda" not in st.session_state:
        st.session_state["opcoes_ocultar_moeda"] = False
    ocultar_moeda = bool(st.session_state["opcoes_ocultar_moeda"])

    ops = bd.listar_opcoes_operacoes(conexao, usuario_id)

    # 1. Onboarding se o diário estiver vazio
    if not ops:
        st.info("👋 **Bem-vindo ao Diário de Opções!** Você ainda não possui operações cadastradas. Anexe sua planilha Excel/CSV na aba 'Importar Planilha' ou cadastre sua primeira operação abaixo.")

    # 2. Métricas Consolidadas
    encerradas = [o for o in ops if o["status"] in ("encerrada", "rolada", "virada")]
    abertas = [o for o in ops if o["status"] == "aberta"]

    # Identificar a data mais recente com movimentação na carteira para destaque dinâmico
    datas_todas_ops = []
    for o in ops:
        d_ini = _extrair_iso_data(o.get("data_inicio"))
        if d_ini:
            datas_todas_ops.append(d_ini)
        d_fim = _extrair_iso_data(o.get("data_fim"))
        if d_fim:
            datas_todas_ops.append(d_fim)
    data_mais_recente_carteira = max(datas_todas_ops) if datas_todas_ops else None

    # Ordenação inicial padrão das Posições Abertas: Ordem Alfabética por Código
    abertas.sort(key=lambda x: (str(x.get("codigo", "")).upper(), x.get("id", 0)))

    # Ordenação do Histórico de Encerradas: Fechamento mais recente para o mais antigo
    def _chave_data_recente(d_str: str | None) -> str:
        if not d_str or not isinstance(d_str, str):
            return ""
        partes = d_str.strip().split("/")
        if len(partes) == 3:
            return f"{partes[2]}-{partes[1].zfill(2)}-{partes[0].zfill(2)}"
        return d_str.strip()

    encerradas.sort(
        key=lambda x: (_chave_data_recente(x.get("data_fim")), _chave_data_recente(x.get("data_inicio")), x.get("id", 0)),
        reverse=True
    )

    vitoriosas = len([o for o in encerradas if o["sucesso"] == "s"])
    win_rate = (vitoriosas / len(encerradas) * 100) if encerradas else 0.0
    lucro_total = sum(float(o["resultado_financeiro"]) for o in encerradas)

    # Capital Inicial da Carteira (editável pelo usuário e persistido no banco)
    chave_cap_sessao = "opcoes_capital_inicial"
    if chave_cap_sessao not in st.session_state:
        st.session_state[chave_cap_sessao] = bd.obter_capital_inicial_opcoes(conexao, usuario_id, padrao=1000.0)
    capital_inicial = float(st.session_state[chave_cap_sessao])

    patrimonio_realizado = capital_inicial + lucro_total
    # Nova métrica: % acumulada (soma das % de ganho das operações encerradas)
    pct_acumulada = sum(float(o.get("resultado_pct") or 0.0) for o in encerradas)
    # Retorno Real sobre Capital Inicial nas operações encerradas
    retorno_sobre_capital = (lucro_total / capital_inicial * 100) if capital_inicial > 0 else 0.0

    # Configuração dinâmica do alerta de rolagem (80%, 100%, 120%, 150%)
    if "meta_alerta_rolagem" not in st.session_state:
        st.session_state["meta_alerta_rolagem"] = 100.0

    gatilho_global = float(st.session_state["meta_alerta_rolagem"])

    # Modo Aula (Acesso Especial de Professor / Educador configurado pelo Admin)
    permite_modo_aula = bool(st.session_state.get("permite_modo_aula", False))
    if "modo_aula_ativo" not in st.session_state:
        st.session_state["modo_aula_ativo"] = False

    if permite_modo_aula:
        c_mode1, c_mode2 = st.columns([3, 1.2])
        with c_mode1:
            st.markdown(
                "<div style='display:flex;align-items:center;gap:8px;padding:8px 12px;background:rgba(13,148,136,0.08);border-left:4px solid #0d9488;border-radius:6px;font-size:13px;color:#0f766e;font-weight:600;margin-bottom:12px;'>"
                "🎓 <span>Painel do Professor habilitado: alterne entre sua carteira pessoal e o <b>Modo Aula</b> para seus alunos.</span>"
                "</div>",
                unsafe_allow_html=True
            )
        with c_mode2:
            modo_aula_ativo = st.toggle(
                "🎓 Ativar Modo Aula",
                value=st.session_state["modo_aula_ativo"],
                key="toggle_modo_aula_switch",
                help="Ativa a visualização didática sem quantidades e sem R$ alocado, com Visão Planilha Sala de Aula e Simulador de 1%."
            )
            st.session_state["modo_aula_ativo"] = modo_aula_ativo

        if st.session_state["modo_aula_ativo"]:
            sala = bd.obter_ou_criar_sala_padrao_professor(conexao, usuario_id, "SALA AO VIVO")
            _secao_ambiente_modo_aula(
                conexao,
                usuario_id,
                sala,
                ops,
                abertas,
                encerradas,
                data_mais_recente_carteira,
                gatilho_global
            )
            return

    # Barra Superior de Controles: Capital Inicial | Patrimônio Realizado | Modo Print
    if ocultar_moeda:
        st.info("👁️ **Modo Print Ativo**: Valores em R$ estão ocultos com `*****`. Percentuais, rentabilidades e dados analíticos continuam visíveis para você tirar prints e compartilhar com segurança.")

    c_cap1, c_cap2, c_cap3 = st.columns([1.8, 1.8, 1.4])
    with c_cap1:
        if ocultar_moeda:
            st.text_input(
                "💼 Capital Inicial (R$)",
                value="R$ *****",
                disabled=True,
                help="Oculto no Modo Print para compartilhamento seguro."
            )
        else:
            def _atualizar_cap_inicial():
                val = float(st.session_state.get("widget_cap_inicial_opcoes", 1000.0))
                st.session_state[chave_cap_sessao] = val
                bd.salvar_capital_inicial_opcoes(conexao, usuario_id, val)

            st.number_input(
                "💼 Capital Inicial da Carteira (R$)",
                min_value=1.0,
                max_value=10_000_000.0,
                value=capital_inicial,
                step=100.0,
                format="%.2f",
                key="widget_cap_inicial_opcoes",
                on_change=_atualizar_cap_inicial,
                help="Informe o valor inicial da sua carteira para calcular o retorno real das operações encerradas."
            )

    with c_cap2:
        val_patrimonio = _moeda_priv(patrimonio_realizado, ocultar_moeda)
        st.text_input(
            "💰 Patrimônio Atual (Realizado)",
            value=val_patrimonio,
            disabled=True,
            help="Capital Inicial + Lucro Realizado acumulado das operações encerradas."
        )

    with c_cap3:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        btn_txt = "🙈 Exibir R$ (Print Ativo)" if ocultar_moeda else "👁️ Ocultar R$ (Modo Print)"
        btn_tipo = "primary" if ocultar_moeda else "secondary"
        if st.button(btn_txt, key="btn_toggle_print_opcoes", type=btn_tipo, use_container_width=True, help="Oculta valores em R$ para você tirar print mantendo apenas as porcentagens e dados analíticos"):
            st.session_state["opcoes_ocultar_moeda"] = not ocultar_moeda
            st.rerun()

    # Verificar gatilhos de rolagem prontos
    rolagens_prontas = []
    for o in abertas:
        p_pago = float(o["preco_pago"])
        p_atual = float(o.get("preco_atual") or p_pago)
        if p_pago > 0 and p_atual > 0:
            if "VENDA" in o.get("estrutura", ""):
                rend = ((float(o.get("preco_recebido") or p_pago) - p_atual) / float(o.get("preco_recebido") or p_pago)) * 100
            else:
                rend = ((p_atual - p_pago) / p_pago) * 100
            if rend >= gatilho_global:
                rolagens_prontas.append((o, rend))

    delta_base = f"Base: {_moeda_priv(capital_inicial, ocultar_moeda)}"
    tema.kpis([
        {"rotulo": "Taxa de Acerto (Win Rate)", "valor": f"{win_rate:.1f}%", "icone": "🎯"},
        {"rotulo": "Lucro Realizado Total", "valor": _moeda_priv(lucro_total, ocultar_moeda), "icone": "💰"},
        {"rotulo": "Rentabilidade Acumulada (%)", "valor": f"{pct_acumulada:+.1f}%", "icone": "📈"},
        {
            "rotulo": "Retorno S/ Capital Inicial",
            "valor": f"{retorno_sobre_capital:+.1f}%",
            "icone": "🚀",
            "delta": delta_base,
            "tom": "pos" if retorno_sobre_capital >= 0 else "neg",
        },
    ])

    if rolagens_prontas:
        tema.kpis([
            {
                "rotulo": f"Posições Prontas p/ Rolar (≥{gatilho_global:.0f}%)",
                "valor": f"{len(rolagens_prontas)} alerta(s)",
                "icone": "🚨",
                "tom": "pos",
            },
        ])

    # 3. Alerta de Destaque para Rolagem
    if rolagens_prontas:
        with st.container():
            st.warning(
                f"🎯 **Gatilho de Rolagem Atingido!** {len(rolagens_prontas)} opção(ões) atingiram o alvo configurado (≥{gatilho_global:.0f}%). "
                "Critério de execução: **embolsar 50% do valor final** e **reinvestir os outros 50%** na opção ATM mais líquida da próxima série."
            )
            for op_pronta, rend_pct in rolagens_prontas:
                c_al1, c_al2 = st.columns([3, 1])
                with c_al1:
                    p_pago_str = _moeda_priv(op_pronta['preco_pago'], ocultar_moeda)
                    p_atual_str = _moeda_priv(op_pronta['preco_atual'], ocultar_moeda)
                    st.markdown(f"**{op_pronta['codigo']}** ({op_pronta.get('estrutura')}) — Entrada: `{p_pago_str}` | Atual: `{p_atual_str}` | Rendimento: **+{rend_pct:.1f}%** 🚀")
                with c_al2:
                    if st.button(f"🔄 Rolar {op_pronta['codigo']}", key=f"btn_alerta_rol_{op_pronta['id']}", type="primary", use_container_width=True):
                        modal_rolar_opcao(op_pronta)

    # 4. Abas do Diário (Com Aba Integralizada / Visão Completa)
    aba_abertas, aba_encerradas, aba_completa, aba_nova, aba_importar = st.tabs([
        f"🟢 Posições Abertas ({len(abertas)})",
        f"📜 Histórico Encerradas ({len(encerradas)})",
        f"📑 Visão Completa ({len(ops)})",
        "➕ Nova Operação",
        "📥 Importar Planilha"
    ])

    # --- ABA 1: POSIÇÕES ABERTAS (FORMATO SLIM, SEM MENUS CONFUSOS) ---
    with aba_abertas:
        if not abertas:
            st.info("Nenhuma posição aberta no momento.")
        else:
            # Sincronização de Cotações com a B3
            col_sync1, col_sync2 = st.columns([2.0, 3.0])
            with col_sync1:
                if st.button("⚡ Atualizar Cotações em Tempo Real", type="primary", use_container_width=True, icon=":material/sync:"):
                    with st.spinner("Atualizando cotações das opções com a B3..."):
                        atualizadas, msg_api = bd.sincronizar_cotacoes_opcoes(conexao, usuario_id)
                        if atualizadas > 0:
                            st.success(msg_api)
                            st.rerun()
                        else:
                            st.info(msg_api)
            with col_sync2:
                st.markdown(
                    "<div style='padding-top: 8px; font-size: 0.85rem; color: #888;'>"
                    "📡 <strong>Fonte oficial:</strong> B3 Market Data (MDS em Tempo Real) &bull; Derivativos B3"
                    "</div>",
                    unsafe_allow_html=True
                )

            # Barra de Configuração, Filtros e Ordenação
            col_cfg1, col_cfg2, col_cfg3, col_cfg4 = st.columns([1.2, 1.2, 1.2, 1.6])
            with col_cfg1:
                alerta_opcoes = [80.0, 100.0, 120.0, 150.0]
                idx_sel = alerta_opcoes.index(gatilho_global) if gatilho_global in alerta_opcoes else 1
                novo_gatilho = st.selectbox(
                    "🎯 Alerta Rolagem",
                    alerta_opcoes,
                    index=idx_sel,
                    format_func=lambda x: f"Gatilho ≥ {x:.0f}%",
                    key="sel_gatilho_alerta_box"
                )
                if novo_gatilho != gatilho_global:
                    st.session_state["meta_alerta_rolagem"] = novo_gatilho
                    st.rerun()

            with col_cfg2:
                ativos_ab = ["Todos"] + sorted(list({str(x.get("ativo_subjacente") or x["codigo"][:4]) for x in abertas}))
                filtro_ab_ativo = st.selectbox("Filtrar Ativo", ativos_ab, key="fil_ab_ativo")

            with col_cfg3:
                est_ab = ["Todas"] + sorted(list({str(x.get("estrutura")) for x in abertas if x.get("estrutura")}))
                filtro_ab_est = st.selectbox("Filtrar Estrutura", est_ab, key="fil_ab_est")

            with col_cfg4:
                opcoes_ordem = [
                    "🔤 Ordem Alfabética (A-Z)",
                    "📅 Início: Mais Recente Primeiro",
                    "⏳ Início: Mais Antiga Primeiro",
                    "💰 Maior Capital Alocado",
                    "📈 Maior Rentabilidade (%)",
                    "📉 Menor Rentabilidade (%)",
                    "⏱️ Mais Dias em Aberto",
                ]
                ordem_sel = st.selectbox("Ordenar Posições por:", opcoes_ordem, index=0, key="sel_ordem_abertas")

            abertas_filtradas = abertas
            if filtro_ab_ativo != "Todos":
                abertas_filtradas = [o for o in abertas_filtradas if (o.get("ativo_subjacente") or o["codigo"][:4]) == filtro_ab_ativo]
            if filtro_ab_est != "Todas":
                abertas_filtradas = [o for o in abertas_filtradas if o.get("estrutura") == filtro_ab_est]

            # Ordenação dinâmica selecionada pelo usuário
            if ordem_sel == "🔤 Ordem Alfabética (A-Z)":
                abertas_filtradas.sort(key=lambda x: (str(x.get("codigo", "")).upper(), x.get("id", 0)))
            elif ordem_sel == "📅 Início: Mais Recente Primeiro":
                abertas_filtradas.sort(key=lambda x: (_extrair_iso_data(x.get("data_inicio")) or "", str(x.get("codigo", "")).upper()), reverse=True)
            elif ordem_sel == "⏳ Início: Mais Antiga Primeiro":
                abertas_filtradas.sort(key=lambda x: (_extrair_iso_data(x.get("data_inicio")) or "", str(x.get("codigo", "")).upper()))
            elif ordem_sel == "💰 Maior Capital Alocado":
                abertas_filtradas.sort(key=lambda x: (float(x.get("valor_alocado") or 0.0), str(x.get("codigo", "")).upper()), reverse=True)
            elif ordem_sel == "📈 Maior Rentabilidade (%)":
                abertas_filtradas.sort(key=lambda x: (_calc_rend_op(x), str(x.get("codigo", "")).upper()), reverse=True)
            elif ordem_sel == "📉 Menor Rentabilidade (%)":
                abertas_filtradas.sort(key=lambda x: (_calc_rend_op(x), str(x.get("codigo", "")).upper()))
            elif ordem_sel == "⏱️ Mais Dias em Aberto":
                abertas_filtradas.sort(key=lambda x: (int(x.get("dias") or bd._calcular_dias_operacao(x.get("data_inicio"))), str(x.get("codigo", "")).upper()), reverse=True)

            st.caption(f"Exibindo {len(abertas_filtradas)} de {len(abertas)} opções abertas.")

            # Pré-busca quantitativa de radar para os ativos únicos em aberto (cache interno de 10 min)
            ativos_sub_unicos = {str(x.get("ativo_subjacente") or x["codigo"][:4]) for x in abertas_filtradas}
            radares_map = {at: bd.obter_radar_tendencia_ativo(at) for at in ativos_sub_unicos}

            # Montagem das linhas para a tabela slim com Radar de Tendência
            linhas_abertas = []
            for op in abertas_filtradas:
                p_pago = float(op["preco_pago"])
                p_atual = float(op.get("preco_atual") or p_pago)
                alocado_op = float(op["valor_alocado"])
                qtd_op = float(op["quantidade"])
                if "VENDA" in str(op.get("estrutura", "")).upper():
                    p_rec = float(op.get("preco_recebido") or p_pago)
                    rend_pct = ((p_rec - p_atual) / p_rec * 100) if p_rec > 0 else 0.0
                    lucro_rs = (p_rec - p_atual) * qtd_op
                else:
                    rend_pct = ((p_atual - p_pago) / p_pago * 100) if p_pago > 0 else 0.0
                    lucro_rs = (p_atual - p_pago) * qtd_op

                atingiu = rend_pct >= gatilho_global
                dias_op = op.get("dias") or bd._calcular_dias_operacao(op["data_inicio"])
                ativo_nome = str(op.get("ativo_subjacente") or op["codigo"][:4])

                dados_radar = radares_map.get(ativo_nome, {})
                sinal_radar = _avaliar_sinal_radar(dados_radar, op.get("estrutura", ""))

                d_op_ini = _extrair_iso_data(op.get("data_inicio"))
                destaque_dia = "verde" if (d_op_ini and d_op_ini == data_mais_recente_carteira) else None

                linhas_abertas.append({
                    "id": op["id"],
                    "codigo": op["codigo"],
                    "ativo": ativo_nome,
                    "estrutura": op.get("estrutura", "—"),
                    "inicio": _p_data(op["data_inicio"]),
                    "dias": int(dias_op),
                    "qtd": int(qtd_op),
                    "pago": p_pago,
                    "atual": p_atual,
                    "rend_pct": rend_pct,
                    "lucro_rs": lucro_rs,
                    "alocado": alocado_op,
                    "atingiu": atingiu,
                    "badge_radar": sinal_radar["badge_html"],
                    "destaque_dia": destaque_dia,
                })

            opcoes_dict = {
                o["id"]: f"{o['codigo']} ({o.get('estrutura')}) — Pago {_moeda_priv(o['preco_pago'], ocultar_moeda)} | Atual {_moeda_priv(o.get('preco_atual') or o['preco_pago'], ocultar_moeda)}"
                for o in abertas_filtradas
            }

            if not linhas_abertas:
                st.info("Nenhuma posição aberta encontrada com os filtros selecionados.")
            else:
                _exibir_html(_render_html_tabela_abertas(linhas_abertas, ocultar=ocultar_moeda))

                # Barra de Ações Rápidas por Opção
                if opcoes_dict:
                    st.markdown("##### ⚡ Ações Rápidas por Ativo")
                    col_sel, col_act1, col_act2, col_act3, col_act4, col_act5, col_act6 = st.columns([2.2, 1.0, 1.0, 1.1, 1.1, 1.0, 1.0])
                    with col_sel:
                        op_escolhida_id = st.selectbox(
                            "Selecione uma opção:",
                            options=list(opcoes_dict.keys()),
                            format_func=lambda i: opcoes_dict[i],
                            key="sel_op_aberta_acao"
                        )

                    op_alvo = next((o for o in abertas_filtradas if o["id"] == op_escolhida_id), None)
                    if op_alvo:
                        with col_act1:
                            if st.button("🔄 Rolar", type="primary", use_container_width=True, help="Rolar com preservação de capital"):
                                modal_rolar_opcao(op_alvo)
                        with col_act2:
                            if st.button("🔄 Virar", type="secondary", use_container_width=True, help="Virada de tendência (CALL ⇄ PUT)"):
                                modal_virar_tendencia(op_alvo)
                        with col_act3:
                            if st.button("➕ Mão", use_container_width=True, help="Aumentar posição / comprar mais cotas"):
                                modal_aumentar_posicao(op_alvo)
                        with col_act4:
                            if st.button("🏁 Saída", use_container_width=True, help="Encerrar posição (total ou parcial / diminuir mão)"):
                                modal_encerrar_opcao(op_alvo)
                        with col_act5:
                            if st.button("✏️ Editar", use_container_width=True, help="Editar e corrigir qualquer dado"):
                                modal_editar_operacao(op_alvo)
                        with col_act6:
                            if st.button("🗑️ Excluir", use_container_width=True, help="Remover do diário"):
                                modal_excluir_operacao(op_alvo)

            # Editor rápido de cotações em massa
            with st.expander("⚡ Atualizar Cotações de Todas as Opções Abertas"):
                st.caption("Altere a cotação de mercado corrente de cada opção e salve para recalcular os alertas:")
                editor_data = []
                for op in abertas_filtradas:
                    p_pago = float(op["preco_pago"])
                    p_atual = float(op.get("preco_atual") or p_pago)
                    editor_data.append({
                        "ID": op["id"],
                        "Código": op["codigo"],
                        "Preço Pago": p_pago,
                        "Cotação Atual": p_atual
                    })
                df_editor = pd.DataFrame(editor_data)
                editado = st.data_editor(
                    df_editor,
                    disabled=["ID", "Código", "Preço Pago"],
                    use_container_width=True,
                    hide_index=True,
                    key="editor_cotacoes_em_massa"
                )
                if st.button("Salvar Todas as Cotações", type="primary", icon=":material/save:"):
                    for _, row in editado.iterrows():
                        oid = int(row["ID"])
                        nova_cot = float(row["Cotação Atual"])
                        bd.atualizar_cotacao_opcao(conexao, usuario_id, oid, nova_cot)
                    st.success("Cotações atualizadas com sucesso!")
                    st.rerun()

    # --- ABA 2: HISTÓRICO DE ENCERRADAS ---
    with aba_encerradas:
        if not encerradas:
            st.info("Nenhuma operação encerrada ainda.")
        else:
            col_fil1, col_fil2 = st.columns(2)
            with col_fil1:
                ativos_unicos = ["Todos"] + sorted(list({str(x.get("ativo_subjacente") or x["codigo"][:4]) for x in encerradas}))
                filtro_ativo = st.selectbox("Filtrar por Ativo Subjacente", ativos_unicos, key="fil_enc_ativo")
            with col_fil2:
                estruturas = ["Todas"] + sorted(list({str(x.get("estrutura")) for x in encerradas if x.get("estrutura")}))
                filtro_est = st.selectbox("Filtrar por Estrutura", estruturas, key="fil_enc_est")

            encerradas_filtradas = encerradas
            if filtro_ativo != "Todos":
                encerradas_filtradas = [o for o in encerradas_filtradas if (o.get("ativo_subjacente") or o["codigo"][:4]) == filtro_ativo]
            if filtro_est != "Todas":
                encerradas_filtradas = [o for o in encerradas_filtradas if o.get("estrutura") == filtro_est]

            encerradas_filtradas.sort(
                key=lambda x: (_chave_data_recente(x.get("data_fim")), _chave_data_recente(x.get("data_inicio")), x.get("id", 0)),
                reverse=True
            )

            st.caption(f"Exibindo {len(encerradas_filtradas)} de {len(encerradas)} operações encerradas.")

            linhas_enc = []
            for o in encerradas_filtradas:
                p_pago = float(o["preco_pago"])
                p_rec = float(o.get("preco_recebido") or 0.0)
                aloc = float(o.get("valor_alocado") or 0.0)
                v_fin = float(o.get("valor_final") or 0.0)
                res_fin = float(o.get("resultado_financeiro") or 0.0)
                res_pct = float(o.get("resultado_pct") or 0.0)
                dias_op = o.get("dias") or bd._calcular_dias_operacao(o["data_inicio"], o.get("data_fim"))
                qtd_op = float(o.get("quantidade") or 0.0)

                d_op_fim = _extrair_iso_data(o.get("data_fim"))
                destaque_dia = "vermelho" if (d_op_fim and d_op_fim == data_mais_recente_carteira) else None

                linhas_enc.append({
                    "id": o["id"],
                    "codigo": o["codigo"],
                    "ativo": o.get("ativo_subjacente") or o["codigo"][:4],
                    "estrutura": o.get("estrutura", "—"),
                    "inicio": _p_data(o["data_inicio"]),
                    "fim": _p_data(o.get("data_fim")),
                    "dias": int(dias_op),
                    "qtd": int(qtd_op),
                    "pago": p_pago,
                    "recebido": p_rec,
                    "res_pct": res_pct,
                    "res_fin": res_fin,
                    "alocado": aloc,
                    "final": v_fin,
                    "status": str(o.get("status", "encerrada")),
                    "obs": o.get("observacoes") or "",
                    "destaque_dia": destaque_dia,
                })

            enc_dict = {
                o["id"]: f"{o['codigo']} ({_p_data(o['data_inicio'])} a {_p_data(o.get('data_fim'))}) — Lucro: {_moeda_priv(o.get('resultado_financeiro', 0), ocultar_moeda)}"
                for o in encerradas_filtradas
            }

            if not linhas_enc:
                st.info("Nenhuma operação encerrada encontrada com os filtros selecionados.")
            else:
                _exibir_html(_render_html_tabela_encerradas(linhas_enc, ocultar=ocultar_moeda))

                # Ações de Edição e Exclusão Individual
                if enc_dict:
                    st.markdown("##### ⚙️ Gerenciar Operação Encerrada")
                    col_e_sel, col_e_btn1, col_e_btn2 = st.columns([3, 1.2, 1.2])
                    with col_e_sel:
                        op_enc_sel_id = st.selectbox(
                            "Selecione uma operação para editar ou excluir:",
                            options=list(enc_dict.keys()),
                            format_func=lambda i: enc_dict[i],
                            key="sel_op_enc_gerenciar"
                        )
                    op_enc_alvo = next((o for o in encerradas_filtradas if o["id"] == op_enc_sel_id), None)
                    if op_enc_alvo:
                        with col_e_btn1:
                            if st.button("✏️ Editar Operação", type="primary", use_container_width=True, key="btn_edt_enc"):
                                modal_editar_operacao(op_enc_alvo)
                        with col_e_btn2:
                            if st.button("🗑️ Excluir Operação", type="secondary", use_container_width=True, key="btn_del_enc"):
                                modal_excluir_operacao(op_enc_alvo)

    # --- ABA 3: VISÃO COMPLETA (INTEGRALIZADA COMO NA PLANILHA DE CONTROLE) ---
    with aba_completa:
        st.markdown("#### 📑 Visão Integralizada (Todas as Operações)")
        st.caption(
            "Visualização consolidada de todas as operações (abertas e encerradas) em ordem de execução, "
            "exatamente como na sua planilha original. Edite ou exclua qualquer registro individualmente."
        )

        col_fc1, col_fc2, col_fc3 = st.columns([1.5, 1.5, 1.5])
        with col_fc1:
            filtro_status_comp = st.selectbox(
                "Filtrar por Status",
                ["Todos", "Abertas", "Encerradas", "Roladas", "Viradas"],
                key="fil_comp_status"
            )
        with col_fc2:
            ativos_todos = ["Todos"] + sorted(list({str(x.get("ativo_subjacente") or x["codigo"][:4]) for x in ops}))
            filtro_comp_ativo = st.selectbox("Filtrar por Ativo", ativos_todos, key="fil_comp_ativo")
        with col_fc3:
            est_todas = ["Todas"] + sorted(list({str(x.get("estrutura")) for x in ops if x.get("estrutura")}))
            filtro_comp_est = st.selectbox("Filtrar por Estrutura", est_todas, key="fil_comp_est")

        ops_vis = ops
        if filtro_status_comp == "Abertas":
            ops_vis = [o for o in ops_vis if o["status"] == "aberta"]
        elif filtro_status_comp == "Encerradas":
            ops_vis = [o for o in ops_vis if o["status"] == "encerrada"]
        elif filtro_status_comp == "Roladas":
            ops_vis = [o for o in ops_vis if o["status"] == "rolada"]
        elif filtro_status_comp == "Viradas":
            ops_vis = [o for o in ops_vis if o["status"] == "virada"]

        if filtro_comp_ativo != "Todos":
            ops_vis = [o for o in ops_vis if (o.get("ativo_subjacente") or o["codigo"][:4]) == filtro_comp_ativo]
        if filtro_comp_est != "Todas":
            ops_vis = [o for o in ops_vis if o.get("estrutura") == filtro_comp_est]

        st.caption(f"Exibindo {len(ops_vis)} de {len(ops)} operações registradas.")

        linhas_comp = []
        for o in ops_vis:
            st_op = o.get("status", "aberta").lower()
            p_pago = float(o["preco_pago"])
            p_rec = float(o.get("preco_recebido") or 0.0)
            p_atual = float(o.get("preco_atual") or p_pago)
            aloc = float(o.get("valor_alocado") or 0.0)
            v_fin = float(o.get("valor_final") or 0.0)
            res_fin = float(o.get("resultado_financeiro") or 0.0)
            qtd_op = float(o.get("quantidade") or 0.0)

            if st_op == "aberta":
                res_pct = ((p_atual - p_pago) / p_pago * 100) if p_pago > 0 else 0.0
            else:
                res_pct = float(o.get("resultado_pct") or 0.0)

            dias_op = o.get("dias") or bd._calcular_dias_operacao(o["data_inicio"], o.get("data_fim"))

            destaque_comp = None
            if st_op == "aberta":
                d_ini = _extrair_iso_data(o.get("data_inicio"))
                if d_ini and d_ini == data_mais_recente_carteira:
                    destaque_comp = "verde"
            else:
                d_fim = _extrair_iso_data(o.get("data_fim"))
                if d_fim and d_fim == data_mais_recente_carteira:
                    destaque_comp = "vermelho"

            linhas_comp.append({
                "id": o["id"],
                "codigo": o["codigo"],
                "ativo": o.get("ativo_subjacente") or o["codigo"][:4],
                "estrutura": o.get("estrutura", "—"),
                "inicio": _p_data(o["data_inicio"]),
                "fim": _p_data(o.get("data_fim")),
                "dias": int(dias_op),
                "qtd": int(qtd_op),
                "pago": p_pago,
                "recebido": p_rec,
                "atual": p_atual,
                "res_pct": res_pct,
                "lucro_val": res_fin,
                "alocado": aloc,
                "final": v_fin,
                "status": st_op,
                "obs": o.get("observacoes") or "",
                "destaque_dia": destaque_comp,
            })

        comp_dict = {
            o["id"]: f"#{o['id']} {o['codigo']} ({str(o.get('status', '')).upper()}) — Entrada: {_p_data(o['data_inicio'])} Pago {_moeda_priv(o['preco_pago'], ocultar_moeda)}"
            for o in ops_vis
        }

        if not linhas_comp:
            st.info("Nenhuma operação encontrada com os filtros selecionados.")
        else:
            _exibir_html(_render_html_tabela_completa(linhas_comp, ocultar=ocultar_moeda))

            # Gestor individual
            if comp_dict:
                st.markdown("##### ⚙️ Ação Individual sobre a Operação")
                col_c_sel, col_c_btn1, col_c_btn2 = st.columns([3, 1.2, 1.2])
                with col_c_sel:
                    op_comp_sel_id = st.selectbox(
                        "Selecione uma operação para editar ou excluir:",
                        options=list(comp_dict.keys()),
                        format_func=lambda i: comp_dict[i],
                        key="sel_op_comp_gerenciar"
                    )
                op_comp_alvo = next((o for o in ops_vis if o["id"] == op_comp_sel_id), None)
                if op_comp_alvo:
                    with col_c_btn1:
                        if st.button("✏️ Editar Operação", type="primary", use_container_width=True, key="btn_edt_comp"):
                            modal_editar_operacao(op_comp_alvo)
                    with col_c_btn2:
                        if st.button("🗑️ Excluir Operação", type="secondary", use_container_width=True, key="btn_del_comp"):
                            modal_excluir_operacao(op_comp_alvo)

    # --- ABA 4: NOVA OPERAÇÃO MANUAL (CADASTRO RÁPIDO COM QUANTIDADE E PREÇO) ---
    with aba_nova:
        st.markdown("#### ⚡ Adicionar Operação Rápida")
        st.caption("Informe a quantidade de contratos e o preço pago unitário. O valor alocado é calculado automaticamente.")

        with st.form("form_nova_operacao_rapida"):
            r1, r2, r3 = st.columns([1.5, 2, 1.5])
            with r1:
                cod_in = st.text_input("Código da Opção", placeholder="Ex: BEEFX400").strip().upper()
            with r2:
                estrutura_in = st.selectbox(
                    "Estrutura",
                    ["COMPRA DE CALL", "COMPRA DE PUT", "VENDA DE CALL", "VENDA DE PUT", "TRAVA", "OUTRA"]
                )
            with r3:
                dt_in = st.date_input("Data Início", value=date.today())

            r4, r5, r6 = st.columns(3)
            with r4:
                qtd_in = st.number_input("Quantidade de Contratos", min_value=1.0, value=100.0, step=100.0)
            with r5:
                preco_in = st.number_input("Preço Pago Unitário (R$)", min_value=0.01, value=0.50, step=0.01, format="%.2f")
            with r6:
                aloc_calculado = qtd_in * preco_in
                st.metric("Valor Alocado Total", _moeda(aloc_calculado))

            obs_in = st.text_input("Observações (opcional)", placeholder="Ex: Entrada por rompimento de suporte / média de 20")

            salvar = st.form_submit_button("➕ Salvar Operação no Diário", type="primary", use_container_width=True)
            if salvar:
                if not cod_in:
                    st.error("Informe o código da opção.")
                else:
                    bd.salvar_opcao_operacao(conexao, usuario_id, {
                        "codigo": cod_in,
                        "estrutura": estrutura_in,
                        "data_inicio": dt_in.strftime("%d/%m/%Y"),
                        "quantidade": qtd_in,
                        "preco_pago": preco_in,
                        "preco_atual": preco_in,
                        "valor_alocado": aloc_calculado,
                        "meta_rolagem_pct": gatilho_global,
                        "observacoes": obs_in,
                        "status": "aberta"
                    })
                    st.success(f"Operação {cod_in} cadastrada com sucesso!")
                    st.rerun()

    # --- ABA 5: IMPORTAR, EXPORTAR & GERENCIAR BASE ---
    with aba_importar:
        st.markdown("#### 📥 Central de Importação, Exportação e Gestão de Dados")
        st.write(
            "Gerencie integralmente as operações do seu Diário de Opções: importe arquivos do Profit ou planilhas padrão, "
            "exporte seus dados para backup em Excel/CSV ou zere a carteira para realizar uma importação 100% limpa."
        )

        st.markdown("##### 1. Importar Planilha de Operações")
        st.info(
            "🛡️ **Filtro Anti-Duplicidade Ativo:** O sistema reconhece cada operação pelo código e data: "
            "ele atualiza posições existentes e insere apenas novos registros, sem duplicar sua carteira."
        )

        col_up, col_mod = st.columns([2, 1.2])
        with col_up:
            arquivo_subido = st.file_uploader(
                "Arraste ou selecione seu arquivo",
                type=["xlsx", "xls", "csv"],
                key="upload_planilha_opcoes",
                help="Suporta exportação do Profit (Relatório de Performance > Operações) e planilha modelo padrão (.xlsx/.csv)"
            )
        with col_mod:
            st.markdown("**Modelo padrão:**")
            st.caption("Baixe nossa planilha modelo pré-configurada se preferir preencher manualmente:")
            st.download_button(
                "⬇️ Baixar Modelo Excel (.xlsx)",
                data=bd.gerar_modelo_planilha_opcoes(),
                file_name="modelo_diario_opcoes.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                icon=":material/download:",
            )

        if arquivo_subido is not None:
            if st.button("🚀 Processar e Importar Operações", type="primary", use_container_width=True, icon=":material/upload_file:"):
                try:
                    with st.spinner("Processando e cadastrando operações..."):
                        bytes_arquivo = arquivo_subido.getvalue()
                        res = bd.importar_opcoes_arquivo(conexao, usuario_id, bytes_arquivo, arquivo_subido.name)
                        # Verificação e higienização automática contra duplicatas
                        bd.sanitizar_duplicatas_opcoes(conexao, usuario_id)
                        origem_txt = "do Nelogica Profit" if res.get("is_profit") else "da planilha modelo"
                        st.success(
                            f"✅ Importação {origem_txt} concluída com sucesso! **{res['importadas']}** nova(s) operação(ões) inserida(s) "
                            f"e **{res['atualizadas']}** atualizada(s). Posições abertas e encerradas organizadas automaticamente."
                        )
                        st.rerun()
                except Exception as e:
                    st.error(f"Erro ao processar o arquivo: {e}")

        st.markdown("---")
        st.markdown("##### 2. Exportar Dados do Diário (Backup / Relatórios)")
        c_exp1, c_exp2 = st.columns(2)
        with c_exp1:
            st.metric("Total de Registros Disponíveis", f"{len(ops)} operações")
        with c_exp2:
            st.caption(f"Inclui **{len(abertas)}** posições abertas e **{len(encerradas)}** operações encerradas/roladas.")

        if ops:
            c_bt_exp1, c_bt_exp2 = st.columns(2)
            with c_bt_exp1:
                excel_bytes = bd.exportar_diario_opcoes_excel(ops)
                st.download_button(
                    "📊 Baixar Diário em Excel (.xlsx)",
                    data=excel_bytes,
                    file_name=f"diario_opcoes_{date.today().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    icon=":material/download:",
                    use_container_width=True,
                    key="btn_down_excel_aba_imp"
                )
            with c_bt_exp2:
                csv_str = bd.exportar_diario_opcoes_csv(ops)
                st.download_button(
                    "📄 Baixar Diário em CSV (.csv)",
                    data=csv_str.encode("utf-8-sig"),
                    file_name=f"diario_opcoes_{date.today().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    type="secondary",
                    icon=":material/description:",
                    use_container_width=True,
                    key="btn_down_csv_aba_imp"
                )

        st.markdown("---")
        st.markdown("##### 3. Limpeza de Dados e Recomeço do Zero")
        st.caption("Caso deseje reiniciar o diário do zero ou eliminar operações duplicadas que possam ter sido inseridas anteriormente:")

        col_clr1, col_clr2 = st.columns(2)
        with col_clr1:
            with st.expander("🧹 Remover Duplicatas Existentes da Carteira"):
                st.write("Varre sua carteira e elimina registros duplicados que compartilham o mesmo código e data, preservando o histórico oficial.")
                if st.button("Remover Duplicatas Agora", type="secondary", icon=":material/cleaning_services:", key="btn_dedup_opcoes"):
                    removidas = bd.sanitizar_duplicatas_opcoes(conexao, usuario_id)
                    if removidas > 0:
                        st.success(f"Foram removidas {removidas} operação(ões) duplicada(s) com sucesso!")
                        st.rerun()
                    else:
                        st.info("Nenhuma duplicata encontrada na carteira.")

        with col_clr2:
            with st.expander("🗑️ Zerar Diário de Opções (Apagar Tudo p/ Importação Limpa)"):
                st.warning("⚠️ **Atenção:** Esta ação apagará todas as operações do seu Diário de Opções. Utilize esta opção se desejar fazer uma importação 100% limpa do zero.")
                check_confirma = st.checkbox("Confirmo que desejo apagar todas as operações do meu diário", key="chk_zerar_opcoes_confirma")
                if st.button("🗑️ Zerar Diário de Opções Agora", type="primary", disabled=not check_confirma, key="btn_zerar_opcoes_definitivo"):
                    total_apagado = bd.limpar_dados_opcoes(conexao, usuario_id)
                    st.success(f"Diário zerado com sucesso! {total_apagado} operação(ões) apagada(s). Agora você pode fazer uma importação limpa.")
                    st.rerun()

    # 5. Banner de Upsell Fiscal Trade se o usuário não possuir o módulo fiscal ativo
    if not st.session_state.get("modulo_fiscal", True):
        st.markdown("---")
        st.markdown("""
        <div style="background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%); border: 1.5px solid #93c5fd; border-radius: 12px; padding: 20px; margin-top: 20px;">
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
                <span style="font-size: 1.5rem;">🏛️</span>
                <strong style="font-size: 1.1rem; color: #1e40af;">Gostaria de apurar o DARF e compensar prejuízos automaticamente?</strong>
            </div>
            <p style="color: #1e3a8a; font-size: 0.9rem; line-height: 1.5; margin-bottom: 12px;">
                O <strong>Módulo Fiscal Trade</strong> calcula seu IR mensal sobre operações em bolsa, 
                deduz suas taxas de corretagem da B3 e compensa prejuízos acumulados para você não pagar imposto indevido.
            </p>
            <span style="font-size: 0.85rem; font-weight: 700; color: #2563eb;">Entre em contato com o suporte ou solicite a ativação no seu perfil!</span>
        </div>
        """, unsafe_allow_html=True)


def pagina_publica_print_aula(conexao, token: str) -> None:
    """Visão limpa e pública da planilha da aula para alunos (sem login, link temporário de 20h)."""
    dados_link = bd.validar_link_temporario_aula(conexao, token)
    if not dados_link:
        st.error("⏰ **Este link temporário expirou ou é inválido.** Os links para alunos têm validade máxima de 20 horas. Peça ao seu professor um novo link de acesso.")
        return

    sala_nome = dados_link.get("sala_nome", "SALA AO VIVO")
    dono_usuario_id = int(dados_link["dono_usuario_id"])

    ops = bd.listar_opcoes_operacoes(conexao, dono_usuario_id)
    abertas = [o for o in ops if o["status"] == "aberta"]
    encerradas = [o for o in ops if o["status"] in ("encerrada", "rolada", "virada")]

    # Identificar data mais recente
    datas_todas = []
    for o in ops:
        d_ini = _extrair_iso_data(o.get("data_inicio"))
        if d_ini:
            datas_todas.append(d_ini)
        d_fim = _extrair_iso_data(o.get("data_fim"))
        if d_fim:
            datas_todas.append(d_fim)
    data_mais_recente_carteira = max(datas_todas) if datas_todas else None

    # Linhas da Planilha: Abertas + Fechadas NO DIA
    linhas_planilha = []
    for o in abertas:
        p_pago = float(o.get("preco_pago") or 0.0)
        p_rec = float(o.get("preco_recebido") or 0.0)
        p_atual = float(o.get("preco_atual") or p_pago)
        dias_op = o.get("dias") or bd._calcular_dias_operacao(o.get("data_inicio"), o.get("data_fim"))
        if "VENDA" in str(o.get("estrutura", "")).upper():
            base_c = p_rec if p_rec > 0 else p_pago
            res_pct = ((base_c - p_atual) / base_c * 100) if base_c > 0 else 0.0
        else:
            res_pct = ((p_atual - p_pago) / p_pago * 100) if p_pago > 0 else 0.0

        d_ini = _extrair_iso_data(o.get("data_inicio"))
        destaque = "verde" if (d_ini and d_ini == data_mais_recente_carteira) else None

        linhas_planilha.append({
            "codigo": o["codigo"],
            "estrutura": o.get("estrutura", "—"),
            "inicio": _p_data(o.get("data_inicio")),
            "fim": "",
            "dias": int(dias_op),
            "pago": p_pago,
            "recebido": p_atual,
            "res_pct": res_pct,
            "sucesso": "s" if res_pct > 0 else "n",
            "status": "aberta",
            "destaque_dia": destaque,
        })

    for o in encerradas:
        d_fim = _extrair_iso_data(o.get("data_fim"))
        if d_fim and d_fim == data_mais_recente_carteira:
            p_pago = float(o.get("preco_pago") or 0.0)
            p_rec = float(o.get("preco_recebido") or 0.0)
            dias_op = o.get("dias") or bd._calcular_dias_operacao(o.get("data_inicio"), o.get("data_fim"))
            res_pct = float(o.get("resultado_pct") or 0.0)

            linhas_planilha.append({
                "codigo": o["codigo"],
                "estrutura": o.get("estrutura", "—"),
                "inicio": _p_data(o.get("data_inicio")),
                "fim": _p_data(o.get("data_fim")),
                "dias": int(dias_op),
                "pago": p_pago,
                "recebido": p_rec,
                "res_pct": res_pct,
                "sucesso": o.get("sucesso", "s" if res_pct > 0 else "n"),
                "status": o.get("status", "encerrada"),
                "destaque_dia": "vermelho",
            })

    linhas_planilha.sort(key=lambda x: (0 if str(x.get("status")).lower() == "aberta" else 1, str(x.get("codigo")).upper()))

    cur_s = conexao.execute("SELECT * FROM salas_aula WHERE id = ?", (int(dados_link["sala_id"]),))
    row_s = cur_s.fetchone()
    sala_obj = dict(zip([d[0] for d in cur_s.description], row_s)) if row_s else {}
    if sala_obj.get("data_hora_modo") == "manual" and str(sala_obj.get("data_hora_personalizada") or "").strip():
        dt_str = str(sala_obj["data_hora_personalizada"]).strip()
    else:
        agora_br = datetime.now()
        dt_str = agora_br.strftime("%d/%m/%Y às %H:%M")
    expira_fmt = ""
    try:
        expira_fmt = datetime.fromisoformat(dados_link["expira_em"]).strftime("%d/%m/%Y às %H:%M")
    except Exception:
        pass

    st.markdown(f"""
    <div style="background:linear-gradient(135deg, #090d16 0%, #111827 100%);border:2px solid #22c55e;border-radius:12px;padding:16px 20px;margin-bottom:15px;">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
            <div>
                <span style="font-size:1.6rem;font-weight:900;color:#22c55e;">🎓 {sala_nome}</span>
                <div style="font-size:0.85rem;color:#94a3b8;margin-top:2px;">Acesso ao vivo para alunos • Posições atualizadas da carteira</div>
            </div>
            <div style="text-align:right;">
                <div style="background:#1e293b;border:1px solid #334155;color:#38bdf8;font-size:0.8rem;padding:6px 12px;border-radius:6px;font-weight:700;">
                    ⏱️ Link válido até {expira_fmt}
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    zoom_pub = st.select_slider(
        "🔍 Ajustar Zoom da Planilha:",
        options=["70%", "80%", "85%", "90%", "95%", "100%", "110%", "120%"],
        value="100%",
        key="slider_zoom_pub_aluno"
    )

    _exibir_html(_render_html_planilha_sala_aula(sala_nome, dt_str, linhas_planilha, zoom_pct=zoom_pub))
