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


def _badge_est(est: str | None) -> str:
    est_u = (est or "").upper()
    if "PUT" in est_u:
        return '<span class="ft-badge-put">PUT</span>'
    elif "CALL" in est_u:
        return '<span class="ft-badge-call">CALL</span>'
    return f'<span class="ft-badge-call">{est or "—"}</span>'


def _exibir_html(html_str: str) -> None:
    """Renderiza HTML de forma segura e nativa sem risco de ser interpretado como código pelo markdown."""
    if hasattr(st, "html"):
        st.html(html_str)
    else:
        st.markdown(html_str, unsafe_allow_html=True)


def _render_html_tabela_abertas(linhas: list[dict]) -> str:
    parts = [_render_css_tabela(), '<div class="ft-tab-container"><table class="ft-tab">']
    parts.append(
        "<thead><tr>"
        "<th>Opção / Ativo</th>"
        "<th>Início / Prazo</th>"
        "<th class=\"col-r\">Cotação (Pago ➔ Atual)</th>"
        "<th class=\"col-r\">Alocado</th>"
        "<th class=\"col-r\">Rendimento %</th>"
        "<th class=\"col-r\">Lucro / Prej (R$)</th>"
        "<th class=\"col-c\">Alerta Rolagem</th>"
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
        parts.append(
            "<tr>"
            f'<td><div><span class="ft-ticker">{row["codigo"]}</span></div>'
            f'<div class="ft-sub">{_badge_est(row["estrutura"])} <span>{row["ativo"]}</span></div></td>'
            f'<td><div>{row["inicio"]}</div>'
            f'<div class="ft-sub">{row["dias"]} dias &bull; {row["qtd"]:,} un</div></td>'
            f'<td class="col-r"><div>Pago: {_moeda(row["pago"])}</div>'
            f'<div class="ft-sub-r">Atual: <strong>{_moeda(row["atual"])}</strong></div></td>'
            f'<td class="col-r">{_moeda(row["alocado"])}</td>'
            f'<td class="col-r">{_fmt_pct(rend_pct)}</td>'
            f'<td class="col-r">{_fmt_moeda_delta(lucro_rs)}</td>'
            f'<td class="col-c">{badge_gatilho}</td>'
            "</tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _render_html_tabela_encerradas(linhas: list[dict]) -> str:
    parts = [_render_css_tabela(), '<div class="ft-tab-container"><table class="ft-tab">']
    parts.append(
        "<thead><tr>"
        "<th>Opção / Ativo</th>"
        "<th>Período / Prazo</th>"
        "<th class=\"col-r\">Preço (Pago ➔ Saída)</th>"
        "<th class=\"col-r\">Capital (Aloc ➔ Final)</th>"
        "<th class=\"col-r\">Resultado %</th>"
        "<th class=\"col-r\">Lucro (R$)</th>"
        "<th class=\"col-c\">Status</th>"
        "</tr></thead><tbody>"
    )
    for row in linhas:
        res_pct = row["res_pct"]
        res_fin = row["res_fin"]
        st_badge = f'<span class="ft-status-{row["status"].lower()}">{row["status"].capitalize()}</span>'
        parts.append(
            "<tr>"
            f'<td><div><span class="ft-ticker">{row["codigo"]}</span></div>'
            f'<div class="ft-sub">{_badge_est(row["estrutura"])} <span>{row["ativo"]}</span></div></td>'
            f'<td><div>{row["inicio"]} &rarr; {row["fim"]}</div>'
            f'<div class="ft-sub">{row["dias"]} dias &bull; {row["qtd"]:,} un</div></td>'
            f'<td class="col-r"><div>Pago: {_moeda(row["pago"])}</div>'
            f'<div class="ft-sub-r">Saída: <strong>{_moeda(row["recebido"])}</strong></div></td>'
            f'<td class="col-r"><div>Aloc: {_moeda(row["alocado"])}</div>'
            f'<div class="ft-sub-r">Final: {_moeda(row["final"])}</div></td>'
            f'<td class="col-r">{_fmt_pct(res_pct)}</td>'
            f'<td class="col-r">{_fmt_moeda_delta(res_fin)}</td>'
            f'<td class="col-c">{st_badge}</td>'
            "</tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _render_html_tabela_completa(linhas: list[dict]) -> str:
    parts = [_render_css_tabela(), '<div class="ft-tab-container"><table class="ft-tab">']
    parts.append(
        "<thead><tr>"
        "<th>Opção / Ativo</th>"
        "<th>Período / Prazo</th>"
        "<th class=\"col-r\">Preço (Pago ➔ Saída/Atual)</th>"
        "<th class=\"col-r\">Capital (Aloc ➔ Final)</th>"
        "<th class=\"col-r\">Resultado %</th>"
        "<th class=\"col-r\">Lucro (R$)</th>"
        "<th class=\"col-c\">Status</th>"
        "</tr></thead><tbody>"
    )
    for row in linhas:
        res_pct = row["res_pct"]
        lucro_val = row["lucro_val"]
        st_badge = f'<span class="ft-status-{row["status"].lower()}">{row["status"].capitalize()}</span>'
        fim_txt = row["fim"] if row["status"] != "aberta" else "Em aberto"
        parts.append(
            "<tr>"
            f'<td><div><span class="ft-ticker">{row["codigo"]}</span></div>'
            f'<div class="ft-sub">{_badge_est(row["estrutura"])} <span>{row["ativo"]}</span></div></td>'
            f'<td><div>{row["inicio"]} &rarr; {fim_txt}</div>'
            f'<div class="ft-sub">{row["dias"]} dias &bull; {row["qtd"]:,} un</div></td>'
            f'<td class="col-r"><div>Pago: {_moeda(row["pago"])}</div>'
            f'<div class="ft-sub-r">Saída/Atual: <strong>{row["preco_col_str"]}</strong></div></td>'
            f'<td class="col-r"><div>Aloc: {_moeda(row["alocado"])}</div>'
            f'<div class="ft-sub-r">Final: {_moeda(row["final"]) if row["status"] != "aberta" else "—"}</div></td>'
            f'<td class="col-r">{_fmt_pct(res_pct)}</td>'
            f'<td class="col-r">{_fmt_moeda_delta(lucro_val) if row["status"] != "aberta" else "—"}</td>'
            f'<td class="col-c">{st_badge}</td>'
            "</tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Modais de Ações do Diário
# ---------------------------------------------------------------------------

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
        "💡 **Critério de Rolagem**: Ao bater a meta de lucro (ex: +100%), o operador "
        "guarda **~50% do valor final no bolso** (lucro garantido) e reinveste os outros **50% "
        "na nova opção**, buscando **boa liquidez** e preço de exercício **mais próximo da linha do dinheiro (ATM)**."
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
    if "VENDA" in op.get("estrutura", ""):
        lucro_r = alocado - valor_final
        lucro_pct = ((op["preco_recebido"] - preco_saida) / op["preco_recebido"] * 100) if op.get("preco_recebido", 0) > 0 else 0.0
    else:
        lucro_r = valor_final - alocado
        lucro_pct = ((preco_saida - preco_pago) / preco_pago * 100) if preco_pago > 0 else 0.0

    metade_bolso = valor_final * 0.50
    metade_reinvestir = valor_final * 0.50

    # Cartões de resumo responsivos (sem truncamento por ellipsis)
    st.markdown(f"""
    <div style="display: flex; gap: 10px; margin: 15px 0;">
        <div style="flex: 1; min-width: 0; background: #f8fafc; border: 1.5px solid #cbd5e1; border-radius: 8px; padding: 12px; text-align: center;">
            <div style="font-size: 0.72rem; color: #64748b; font-weight: 700; text-transform: uppercase;">Total Obtido</div>
            <div style="font-size: clamp(0.95rem, 2vw, 1.2rem); font-weight: 700; color: #0f172a; margin: 4px 0; white-space: nowrap;">{_moeda(valor_final)}</div>
            <div style="font-size: 0.75rem; color: #16a34a; font-weight: 700;">{lucro_pct:+.1f}%</div>
        </div>
        <div style="flex: 1; min-width: 0; background: #f0fdf4; border: 1.5px solid #86efac; border-radius: 8px; padding: 12px; text-align: center;">
            <div style="font-size: 0.72rem; color: #15803d; font-weight: 700; text-transform: uppercase;">💰 50% no Bolso</div>
            <div style="font-size: clamp(0.95rem, 2vw, 1.2rem); font-weight: 700; color: #166534; margin: 4px 0; white-space: nowrap;">{_moeda(metade_bolso)}</div>
            <div style="font-size: 0.75rem; color: #15803d; font-weight: 600;">Lucro Garantido</div>
        </div>
        <div style="flex: 1; min-width: 0; background: #eff6ff; border: 1.5px solid #93c5fd; border-radius: 8px; padding: 12px; text-align: center;">
            <div style="font-size: 0.72rem; color: #1d4ed8; font-weight: 700; text-transform: uppercase;">🚀 50% Reinvestir</div>
            <div style="font-size: clamp(0.95rem, 2vw, 1.2rem); font-weight: 700; color: #1e40af; margin: 4px 0; white-space: nowrap;">{_moeda(metade_reinvestir)}</div>
            <div style="font-size: 0.75rem; color: #1d4ed8; font-weight: 600;">Nova Perna</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("#### Nova Opção (Perna Futura)")

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
        sugestao_qtd = max(100.0, round((metade_reinvestir / novo_preco) / 100) * 100) if novo_preco > 0 else 100.0
        nova_qtd = st.number_input(
            "Quantidade",
            min_value=1.0,
            value=float(sugestao_qtd),
            step=100.0,
            help=f"Calculado para aproximar do alvo de {_moeda(metade_reinvestir)}",
            key="modal_rol_nova_qtd"
        )

    novo_alocado_calc = nova_qtd * novo_preco
    st.caption(f"Valor a alocar na nova opção: **{_moeda(novo_alocado_calc)}**")

    obs = st.text_input("Observações", value="Rolagem com preservação de 50% de lucro.", key="modal_rol_obs")

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
    st.caption(f"Posição atual: **{estrutura_atual}** | Alocado: **{_moeda(alocado)}**")
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


@st.dialog("🏁 Encerrar Operação")
def modal_encerrar_opcao(op: dict) -> None:
    conexao = paginas.obter_conexao()
    usuario_id = int(st.session_state["usuario_id"])

    codigo = op["codigo"]
    preco_pago = float(op["preco_pago"])
    preco_atual = float(op.get("preco_atual") or preco_pago)
    quantidade = float(op["quantidade"])
    alocado = float(op["valor_alocado"])

    st.markdown(f"### Encerrar Operação **{codigo}**")
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

    valor_final = quantidade * preco_saida
    if "VENDA" in op.get("estrutura", ""):
        res_fin = alocado - valor_final
        res_pct = ((op["preco_recebido"] - preco_saida) / op["preco_recebido"] * 100) if op.get("preco_recebido", 0) > 0 else 0.0
    else:
        res_fin = valor_final - alocado
        res_pct = ((preco_saida - preco_pago) / preco_pago * 100) if preco_pago > 0 else 0.0

    st.markdown(
        f"**Resultado:** `{_moeda(res_fin)}` (`{res_pct:+.1f}%`) | "
        f"**Valor Final:** `{_moeda(valor_final)}`"
    )
    obs = st.text_input("Observações de Fechamento", value="", key="modal_enc_obs")

    if st.button("Confirmar Encerramento", type="primary", use_container_width=True, icon=":material/check:"):
        bd.encerrar_opcao_operacao(
            conexao, usuario_id, op["id"],
            data_fim=data_str,
            preco_recebido=preco_saida,
            observacoes=obs,
        )
        st.success(f"Operação {codigo} encerrada!")
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

def pagina_diario_opcoes() -> None:
    tema.cabecalho(
        "Gestão e Diário de Opções",
        "Acompanhe suas operações, controle posições abertas, realize rolagens com preservação de capital e virada de tendência.",
        "📈"
    )
    conexao = paginas.obter_conexao()
    usuario_id = int(st.session_state["usuario_id"])

    ops = bd.listar_opcoes_operacoes(conexao, usuario_id)

    # 1. Onboarding se o diário estiver vazio
    if not ops:
        st.info("👋 **Bem-vindo ao Diário de Opções!** Você ainda não possui operações cadastradas. Anexe sua planilha Excel/CSV na aba 'Importar Planilha' ou cadastre sua primeira operação abaixo.")

    # 2. Métricas Consolidadas
    encerradas = [o for o in ops if o["status"] in ("encerrada", "rolada", "virada")]
    abertas = [o for o in ops if o["status"] == "aberta"]

    vitoriosas = len([o for o in encerradas if o["sucesso"] == "s"])
    win_rate = (vitoriosas / len(encerradas) * 100) if encerradas else 0.0
    lucro_total = sum(float(o["resultado_financeiro"]) for o in encerradas)
    capital_aberto = sum(float(o["valor_alocado"]) for o in abertas)
    capital_encerrado = sum(float(o["valor_alocado"]) for o in encerradas)

    # Nova métrica: % acumulada (soma das % de ganho das operações encerradas)
    pct_acumulada = sum(float(o.get("resultado_pct") or 0.0) for o in encerradas)
    # Nova métrica: % retorno sobre capital alocado nas encerradas
    retorno_sobre_capital = (lucro_total / capital_encerrado * 100) if capital_encerrado > 0 else 0.0

    # Configuração dinâmica do alerta de rolagem (80%, 100%, 120%, 150%)
    if "meta_alerta_rolagem" not in st.session_state:
        st.session_state["meta_alerta_rolagem"] = 100.0

    gatilho_global = float(st.session_state["meta_alerta_rolagem"])

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

    tema.kpis([
        {"rotulo": "Taxa de Acerto (Win Rate)", "valor": f"{win_rate:.1f}%", "icone": "🎯"},
        {"rotulo": "Lucro Realizado Total", "valor": _moeda(lucro_total), "icone": "💰"},
        {"rotulo": "Rentabilidade Acumulada (%)", "valor": f"{pct_acumulada:+.1f}%", "icone": "📈"},
        {"rotulo": "Retorno s/ Capital Alocado", "valor": f"{retorno_sobre_capital:+.1f}%", "icone": "🚀"},
    ])
    tema.kpis([
        {"rotulo": "Capital Alocado em Aberto", "valor": _moeda(capital_aberto), "icone": "🛡️"},
        {"rotulo": f"Posições Prontas p/ Rolar (≥{gatilho_global:.0f}%)", "valor": f"{len(rolagens_prontas)} alerta(s)", "icone": "🚨"},
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
                    st.markdown(f"**{op_pronta['codigo']}** ({op_pronta.get('estrutura')}) — Entrada: `{_moeda(op_pronta['preco_pago'])}` | Atual: `{_moeda(op_pronta['preco_atual'])}` | Rendimento: **+{rend_pct:.1f}%** 🚀")
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
            col_sync1, _ = st.columns([2.2, 2.8])
            with col_sync1:
                if st.button("⚡ Atualizar Cotações em Tempo Real", type="primary", use_container_width=True, icon=":material/sync:"):
                    with st.spinner("Atualizando cotações das opções com a B3..."):
                        atualizadas, msg_api = bd.sincronizar_cotacoes_opcoes(conexao, usuario_id)
                        if atualizadas > 0:
                            st.success(msg_api)
                            st.rerun()
                        else:
                            st.info(msg_api)

            # Barra de Configuração e Filtros
            col_cfg1, col_cfg2, col_cfg3 = st.columns([1.5, 1.5, 1.5])
            with col_cfg1:
                alerta_opcoes = [80.0, 100.0, 120.0, 150.0]
                idx_sel = alerta_opcoes.index(gatilho_global) if gatilho_global in alerta_opcoes else 1
                novo_gatilho = st.selectbox(
                    "🎯 Alerta de Rolagem em %",
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
                filtro_ab_ativo = st.selectbox("Filtrar por Ativo", ativos_ab, key="fil_ab_ativo")

            with col_cfg3:
                est_ab = ["Todas"] + sorted(list({str(x.get("estrutura")) for x in abertas if x.get("estrutura")}))
                filtro_ab_est = st.selectbox("Filtrar por Estrutura", est_ab, key="fil_ab_est")

            abertas_filtradas = abertas
            if filtro_ab_ativo != "Todos":
                abertas_filtradas = [o for o in abertas_filtradas if (o.get("ativo_subjacente") or o["codigo"][:4]) == filtro_ab_ativo]
            if filtro_ab_est != "Todas":
                abertas_filtradas = [o for o in abertas_filtradas if o.get("estrutura") == filtro_ab_est]

            st.caption(f"Exibindo {len(abertas_filtradas)} de {len(abertas)} opções abertas.")

            # Montagem das linhas para a tabela limpa
            linhas_abertas = []
            for op in abertas_filtradas:
                p_pago = float(op["preco_pago"])
                p_atual = float(op.get("preco_atual") or p_pago)
                alocado_op = float(op["valor_alocado"])
                qtd_op = float(op["quantidade"])
                rend_pct = ((p_atual - p_pago) / p_pago * 100) if p_pago > 0 else 0.0
                lucro_rs = alocado_op * (rend_pct / 100.0)
                atingiu = rend_pct >= gatilho_global
                dias_op = op.get("dias") or bd._calcular_dias_operacao(op["data_inicio"])

                linhas_abertas.append({
                    "id": op["id"],
                    "codigo": op["codigo"],
                    "ativo": op.get("ativo_subjacente") or op["codigo"][:4],
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
                })

            opcoes_dict = {
                o["id"]: f"{o['codigo']} ({o.get('estrutura')}) — Pago {_moeda(o['preco_pago'])} | Atual {_moeda(o.get('preco_atual') or o['preco_pago'])}"
                for o in abertas_filtradas
            }

            if not linhas_abertas:
                st.info("Nenhuma posição aberta encontrada com os filtros selecionados.")
            else:
                _exibir_html(_render_html_tabela_abertas(linhas_abertas))

                # Barra de Ações Rápidas por Opção
                if opcoes_dict:
                    st.markdown("##### ⚡ Ações Rápidas por Ativo")
                    col_sel, col_act1, col_act2, col_act3, col_act4, col_act5 = st.columns([2.5, 1.2, 1.3, 1.2, 1.2, 1.1])
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
                            if st.button("🔄 Rolar", type="primary", use_container_width=True, help="Rolar com 50% de lucro no bolso"):
                                modal_rolar_opcao(op_alvo)
                        with col_act2:
                            if st.button("🔄 Virar", type="secondary", use_container_width=True, help="Virada de tendência (CALL ⇄ PUT)"):
                                modal_virar_tendencia(op_alvo)
                        with col_act3:
                            if st.button("✏️ Editar", use_container_width=True, help="Editar e corrigir qualquer dado"):
                                modal_editar_operacao(op_alvo)
                        with col_act4:
                            if st.button("🏁 Encerrar", use_container_width=True, help="Encerrar posição"):
                                modal_encerrar_opcao(op_alvo)
                        with col_act5:
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
                    "obs": o.get("observacoes") or ""
                })

            enc_dict = {
                o["id"]: f"{o['codigo']} ({_p_data(o['data_inicio'])} a {_p_data(o.get('data_fim'))}) — Lucro: {_moeda(o.get('resultado_financeiro', 0))}"
                for o in encerradas_filtradas
            }

            if not linhas_enc:
                st.info("Nenhuma operação encerrada encontrada com os filtros selecionados.")
            else:
                _exibir_html(_render_html_tabela_encerradas(linhas_enc))

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

    # --- ABA 3: VISÃO COMPLETA (INTEGRALIZADA COMO NA PLANILHA NITRO) ---
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
                preco_col = _moeda(p_atual) + " (atual)"
                lucro_col = "—"
                fin_col = "—"
            else:
                res_pct = float(o.get("resultado_pct") or 0.0)
                preco_col = _moeda(p_rec)
                lucro_col = _moeda(res_fin)
                fin_col = _moeda(v_fin)

            dias_op = o.get("dias") or bd._calcular_dias_operacao(o["data_inicio"], o.get("data_fim"))

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
                "preco_col_str": preco_col,
                "res_pct": res_pct,
                "lucro_val": res_fin,
                "alocado": aloc,
                "final": v_fin,
                "status": st_op,
                "obs": o.get("observacoes") or ""
            })

        comp_dict = {
            o["id"]: f"#{o['id']} {o['codigo']} ({str(o.get('status', '')).upper()}) — Entrada: {_p_data(o['data_inicio'])} Pago {_moeda(o['preco_pago'])}"
            for o in ops_vis
        }

        if not linhas_comp:
            st.info("Nenhuma operação encontrada com os filtros selecionados.")
        else:
            _exibir_html(_render_html_tabela_completa(linhas_comp))

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

    # --- ABA 5: IMPORTAR PLANILHA ---
    with aba_importar:
        st.markdown("#### Importar Planilha de Operações (Excel ou CSV)")
        st.write(
            "Anexe sua planilha Nitro ou arquivo de controle. O sistema mapeia automaticamente "
            "as colunas de **Código**, **Estrutura**, **Datas**, **Preço Pago**, **Preço Recebido**, "
            "**Quantidade** e **Status**, e calcula automaticamente dias e resultados ausentes."
        )

        col_up, col_mod = st.columns([2, 1.2])
        with col_up:
            arquivo_subido = st.file_uploader(
                "Arraste ou selecione sua planilha",
                type=["xlsx", "xls", "csv"],
                key="upload_planilha_opcoes",
                help="Suporta planilhas padrão com colunas: Código, Estrutura, Data Início, Pago, Recebido, etc."
            )
        with col_mod:
            st.markdown("**Modelo padrão:**")
            st.caption("Baixe nossa planilha modelo pré-configurada para preencher seus trades:")
            st.download_button(
                "⬇️ Baixar Modelo Excel (.xlsx)",
                data=bd.gerar_modelo_planilha_opcoes(),
                file_name="modelo_diario_opcoes.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                icon=":material/download:",
            )

        if arquivo_subido is not None:
            if st.button("🚀 Processar e Importar Planilha", type="primary", use_container_width=True, icon=":material/upload_file:"):
                try:
                    with st.spinner("Processando e cadastrando operações..."):
                        bytes_arquivo = arquivo_subido.getvalue()
                        res = bd.importar_opcoes_arquivo(conexao, usuario_id, bytes_arquivo, arquivo_subido.name)
                        st.success(
                            f"Importação concluída com sucesso! **{res['importadas']}** nova(s) operação(ões) inserida(s) "
                            f"e **{res['atualizadas']}** atualizada(s). Dias e resultados faltantes foram calculados automaticamente."
                        )
                        st.rerun()
                except Exception as e:
                    st.error(f"Erro ao processar o arquivo: {e}")

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
