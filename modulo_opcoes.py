"""
Módulo de Gestão e Diário de Operações de Opções — FiscoTrade.

Permite ao operador de renda variável acompanhar posições abertas, monitorar
o rendimento das opções em carteira, registrar rolagens com preservação de capital
(50% no bolso e 50% reinvestido em opções líquidas próximas do dinheiro),
além de sincronizar dados com planilhas e exportar relatórios.
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
        if "/" in str(val):
            return str(val)
        return date.fromisoformat(str(val)[:10]).strftime("%d/%m/%Y")
    except Exception:
        return str(val)


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
        "💡 **Regra de Ouro da Rolagem**: Ao atingir a meta de lucro (ex: +100%), o operador "
        "encerra a posição, guarda **50% do valor final obtido no bolso** (garantindo lucro líquido) "
        "e reinveste os outros **50% na nova opção**, buscando **boa liquidez** e preço de exercício "
        "**mais próximo da linha do dinheiro (ATM)** para continuar surfando a tendência."
    )

    c1, c2 = st.columns(2)
    with c1:
        dt_rolagem = st.date_input("Data da Rolagem", value=date.today())
        data_str = dt_rolagem.strftime("%d/%m/%Y")
    with c2:
        preco_saida = st.number_input(
            "Preço de Saída da Atual (R$)",
            min_value=0.01,
            value=float(preco_atual if preco_atual > 0 else preco_pago * 2.0),
            step=0.01,
            format="%.2f",
            help="Preço unitário de venda para encerrar a perna atual."
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

    st.markdown("---")
    st.markdown("#### Simulação Financeira da Rolagem")
    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("Montante Final Obtido", _moeda(valor_final), f"+{lucro_pct:.1f}%")
    with m2:
        st.metric("💰 50% Lucro no Bolso", _moeda(metade_bolso), help="Preservação de capital garantida!")
    with m3:
        st.metric("🚀 50% Reinvestir (Novo Alvo)", _moeda(metade_reinvestir))

    st.markdown("---")
    st.markdown("#### Dados da Nova Opção (Perna Futura)")
    info_sugestao = bd.identificar_opcao(codigo)

    nc1, nc2, nc3 = st.columns(3)
    with nc1:
        novo_codigo = st.text_input(
            "Novo Código da Opção",
            value="",
            placeholder="Ex: BEEFX400",
            help="Escolha uma opção com boa liquidez mais próxima do dinheiro (ATM) para a próxima série."
        ).strip().upper()
    with nc2:
        novo_preco = st.number_input(
            "Preço Unitário da Nova Opção (R$)",
            min_value=0.01,
            value=float(preco_pago),
            step=0.01,
            format="%.2f"
        )
    with nc3:
        sugestao_qtd = max(100.0, round((metade_reinvestir / novo_preco) / 100) * 100) if novo_preco > 0 else 100.0
        nova_qtd = st.number_input(
            "Quantidade",
            min_value=1.0,
            value=float(sugestao_qtd),
            step=100.0,
            help=f"Calculado para aproximar do alvo de {_moeda(metade_reinvestir)}"
        )

    novo_alocado_calc = nova_qtd * novo_preco
    st.caption(f"Valor a ser alocado na nova opção: **{_moeda(novo_alocado_calc)}**")

    obs = st.text_input("Observações da Rolagem", value="Rolagem com preservação de 50% de lucro.")

    if st.button("Confirmar Rolagem", type="primary", use_container_width=True, icon=":material/sync:"):
        if not novo_codigo:
            st.error("Informe o novo código da opção para onde a posição será rolada.")
        else:
            nova_id = bd.rolar_opcao_operacao(
                conexao, usuario_id, op["id"],
                data_rolagem=data_str,
                preco_fechamento=preco_saida,
                novo_codigo=novo_codigo,
                novo_preco_pago=novo_preco,
                nova_quantidade=nova_qtd,
                observacoes=obs,
            )
            st.success(f"Rolagem executada com sucesso! A opção {codigo} foi encerrada e a nova opção {novo_codigo} foi aberta.")
            st.rerun()


@st.dialog("🏁 Encerrar Operação")
def modal_encerrar_opcao(op: dict) -> None:
    conexao = paginas.obter_conexao()
    usuario_id = int(st.session_state["usuario_id"])

    codigo = op["codigo"]
    preco_pago = float(op["preco_pago"])
    preco_atual = float(op["preco_atual"]) if float(op.get("preco_atual") or 0.0) > 0 else preco_pago
    quantidade = float(op["quantidade"])
    alocado = float(op["valor_alocado"])

    st.markdown(f"### Encerrar Operação **{codigo}**")
    c1, c2 = st.columns(2)
    with c1:
        dt_fim = st.date_input("Data de Encerramento", value=date.today())
        data_str = dt_fim.strftime("%d/%m/%Y")
    with c2:
        preco_saida = st.number_input(
            "Preço de Saída Unitário (R$)",
            min_value=0.00,
            value=float(preco_atual),
            step=0.01,
            format="%.2f",
            help="Preço pelo qual a opção foi vendida (ou recomprada no caso de venda coberta)."
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
    obs = st.text_input("Observações de Fechamento", value="")

    if st.button("Confirmar Encerramento", type="primary", use_container_width=True, icon=":material/check:"):
        bd.encerrar_opcao_operacao(
            conexao, usuario_id, op["id"],
            data_fim=data_str,
            preco_recebido=preco_saida,
            observacoes=obs,
        )
        st.success(f"Operação {codigo} encerrada com sucesso!")
        st.rerun()


@st.dialog("⚡ Atualizar Cotação Atual")
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
        format="%.2f"
    )

    if preco_pago > 0:
        rend_pct = ((novo_preco - preco_pago) / preco_pago) * 100
        st.markdown(f"**Rendimento projetado no preço:** `{rend_pct:+.1f}%`")
        if rend_pct >= float(op.get("meta_rolagem_pct", 100.0)):
            st.success("🎯 **Meta de Rolagem Atingida!** Essa operação está pronta para rolagem.")

    if st.button("Salvar Cotação", type="primary", use_container_width=True):
        bd.atualizar_cotacao_opcao(conexao, usuario_id, op["id"], novo_preco)
        st.success("Cotação atualizada.")
        st.rerun()


def pagina_diario_opcoes() -> None:
    tema.cabecalho(
        "Gestão e Diário de Opções",
        "Acompanhe suas operações, controle posições abertas e receba alertas inteligentes de rolagem com preservação de capital.",
        "📈"
    )
    conexao = paginas.obter_conexao()
    usuario_id = int(st.session_state["usuario_id"])

    ops = bd.listar_opcoes_operacoes(conexao, usuario_id)

    # 1. Onboarding se o diário estiver vazio
    if not ops:
        st.markdown("""
        <div style="background: linear-gradient(135deg, #f0fdf4 0%, #e6f7ec 100%); border: 1px solid #86efac; border-radius: 12px; padding: 24px; margin-bottom: 24px;">
            <h3 style="color: #166534; margin: 0 0 10px 0;">👋 Bem-vindo ao Diário de Operações de Opções!</h3>
            <p style="color: #14532d; font-size: 0.95rem; line-height: 1.5; margin-bottom: 16px;">
                Organize todas as suas compras de CALLs, PUTs, lançamentos e travas. 
                Monitore o rendimento das suas posições abertas e seja avisado na hora certa de efetuar a 
                <strong>rolagem com preservação de 50% de lucro no bolso</strong>.
            </p>
        </div>
        """, unsafe_allow_html=True)

        col_in1, col_in2 = st.columns(2)
        with col_in1:
            if st.button("📥 Sincronizar com Minha Planilha Google", type="primary", use_container_width=True, icon=":material/sync:"):
                try:
                    with st.spinner("Importando operações da planilha Google..."):
                        res = bd.importar_opcoes_google_sheet(conexao, usuario_id)
                        st.success(f"Sucesso! {res['importadas']} operações importadas e {res['atualizadas']} atualizadas.")
                        st.rerun()
                except Exception as e:
                    st.error(f"Erro ao importar da planilha: {e}")
        with col_in2:
            st.caption("Ou utilize as abas abaixo para cadastrar suas operações manualmente.")

    # 2. Métricas Consolidadas
    encerradas = [o for o in ops if o["status"] in ("encerrada", "rolada")]
    abertas = [o for o in ops if o["status"] == "aberta"]

    vitoriosas = len([o for o in encerradas if o["sucesso"] == "s"])
    win_rate = (vitoriosas / len(encerradas) * 100) if encerradas else 0.0
    lucro_total = sum(float(o["resultado_financeiro"]) for o in encerradas)
    capital_aberto = sum(float(o["valor_alocado"]) for o in abertas)

    # Verificar gatilhos de rolagem prontos (rendimento >= meta)
    rolagens_prontas = []
    for o in abertas:
        p_pago = float(o["preco_pago"])
        p_atual = float(o.get("preco_atual") or p_pago)
        meta = float(o.get("meta_rolagem_pct") or 100.0)
        if p_pago > 0 and p_atual > 0:
            if "VENDA" in o.get("estrutura", ""):
                rend = ((float(o.get("preco_recebido") or p_pago) - p_atual) / float(o.get("preco_recebido") or p_pago)) * 100
            else:
                rend = ((p_atual - p_pago) / p_pago) * 100
            if rend >= meta:
                rolagens_prontas.append((o, rend))

    tema.kpis([
        {"rotulo": "Taxa de Acerto (Win Rate)", "valor": f"{win_rate:.1f}%", "icone": "🎯"},
        {"rotulo": "Lucro Realizado Total", "valor": _moeda(lucro_total), "icone": "💰"},
        {"rotulo": "Capital Alocado em Aberto", "valor": _moeda(capital_aberto), "icone": "🛡️"},
        {"rotulo": "Posições Prontas p/ Rolar", "valor": f"{len(rolagens_prontas)} alerta(s)", "icone": "🚨"},
    ])

    # 3. Alerta de Destaque para Rolagem
    if rolagens_prontas:
        st.markdown("""
        <div style="background: #fffbeb; border: 1.5px solid #f59e0b; border-radius: 10px; padding: 14px 18px; margin: 16px 0;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 1.3rem;">🎯</span>
                <strong style="color: #92400e; font-size: 1.05rem;">Gatilho de Rolagem Atingido!</strong>
            </div>
            <div style="color: #78350f; font-size: 0.9rem; margin-top: 4px;">
                Uma ou mais opções atingiram a meta de rendimento. Recomendação: <strong>colocar ~50% no bolso</strong> e rolar os outros 50% para a opção ATM mais líquida da próxima série.
            </div>
        </div>
        """, unsafe_allow_html=True)
        for op_pronta, rend_pct in rolagens_prontas:
            col_al1, col_al2 = st.columns([3, 1])
            with col_al1:
                st.markdown(f"**{op_pronta['codigo']}** ({op_pronta.get('estrutura')}) — Entrada: `{_moeda(op_pronta['preco_pago'])}` | Atual: `{_moeda(op_pronta['preco_atual'])}` | Rendimento: **+{rend_pct:.1f}%** 🚀")
            with col_al2:
                if st.button(f"🔄 Rolar {op_pronta['codigo']}", key=f"btn_alerta_rol_{op_pronta['id']}", type="primary", use_container_width=True):
                    modal_rolar_opcao(op_pronta)

    # 4. Abas do Diário
    aba_abertas, aba_encerradas, aba_nova, aba_importar = st.tabs([
        f"🟢 Posições Abertas ({len(abertas)})",
        f"📜 Histórico Encerradas ({len(encerradas)})",
        "➕ Nova Operação",
        "📥 Sincronização & Dados"
    ])

    # --- ABA 1: POSIÇÕES ABERTAS ---
    with aba_abertas:
        if not abertas:
            st.info("Nenhuma posição aberta no momento.")
        else:
            st.caption("Acompanhe o rendimento não realizado das suas opções e acione a rolagem ou encerramento a qualquer momento.")

            for op in abertas:
                p_pago = float(op["preco_pago"])
                p_atual = float(op.get("preco_atual") or p_pago)
                meta = float(op.get("meta_rolagem_pct") or 100.0)
                alocado_op = float(op["valor_alocado"])
                if p_pago > 0:
                    rend_pct = ((p_atual - p_pago) / p_pago) * 100
                else:
                    rend_pct = 0.0

                atingiu_meta = rend_pct >= meta

                card_bg = "#f0fdf4" if atingiu_meta else "#ffffff"
                card_border = "#22c55e" if atingiu_meta else "#e2e8f0"

                st.markdown(f"""
                <div style="background: {card_bg}; border: 1.5px solid {card_border}; border-radius: 10px; padding: 14px 16px; margin-bottom: 8px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <div>
                            <span style="font-size: 1.15rem; font-weight: 800; color: #0f172a;">{op['codigo']}</span>
                            <span style="font-size: 0.8rem; background: #e2e8f0; color: #334155; padding: 2px 8px; border-radius: 4px; margin-left: 8px; font-weight: 600;">{op.get('estrutura')}</span>
                            <span style="font-size: 0.8rem; color: #64748b; margin-left: 8px;">Início: {_p_data(op['data_inicio'])}</span>
                        </div>
                        <div>
                            <span style="font-size: 1.1rem; font-weight: 800; color: {'#16a34a' if rend_pct >= 0 else '#dc2626'};">
                                {rend_pct:+.1f}%
                            </span>
                            {'<span style="background: #fef08a; color: #854d0e; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; margin-left: 6px;">🎯 ROLAR</span>' if atingiu_meta else ''}
                        </div>
                    </div>
                    <div style="display: flex; gap: 20px; font-size: 0.85rem; color: #475569;">
                        <div>Pago: <strong>{_moeda(p_pago)}</strong></div>
                        <div>Cotação Atual: <strong>{_moeda(p_atual)}</strong></div>
                        <div>Alocado: <strong>{_moeda(alocado_op)}</strong></div>
                        <div>Meta Rolagem: <strong>{meta:.0f}%</strong></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                c_b1, c_b2, c_b3, c_b4 = st.columns([1.2, 1.2, 1.2, 1])
                with c_b1:
                    if st.button("✏️ Cotação", key=f"btn_cot_{op['id']}", use_container_width=True):
                        modal_atualizar_cotacao(op)
                with c_b2:
                    if st.button("🔄 Rolar Opção", key=f"btn_rol_{op['id']}", type="primary" if atingiu_meta else "secondary", use_container_width=True):
                        modal_rolar_opcao(op)
                with c_b3:
                    if st.button("🏁 Encerrar", key=f"btn_enc_{op['id']}", use_container_width=True):
                        modal_encerrar_opcao(op)
                with c_b4:
                    if st.button("💨 Virou Pó", key=f"btn_po_{op['id']}", use_container_width=True, help="Encerra a R$ 0,00"):
                        bd.encerrar_opcao_operacao(
                            conexao, usuario_id, op["id"],
                            data_fim=date.today().strftime("%d/%m/%Y"),
                            preco_recebido=0.00,
                            observacoes="Expirou no pó"
                        )
                        st.success(f"{op['codigo']} encerrada no pó.")
                        st.rerun()

    # --- ABA 2: HISTÓRICO DE ENCERRADAS ---
    with aba_encerradas:
        if not encerradas:
            st.info("Nenhuma operação encerrada ainda.")
        else:
            df_enc = pd.DataFrame(encerradas)
            col_fil1, col_fil2 = st.columns(2)
            with col_fil1:
                ativos_unicos = ["Todos"] + sorted(list({str(x) for x in df_enc["ativo_subjacente"] if pd.notna(x)}))
                filtro_ativo = st.selectbox("Filtrar por Ativo Subjacente", ativos_unicos)
            with col_fil2:
                estruturas = ["Todas"] + sorted(list({str(x) for x in df_enc["estrutura"] if pd.notna(x)}))
                filtro_est = st.selectbox("Filtrar por Estrutura", estruturas)

            df_view = df_enc.copy()
            if filtro_ativo != "Todos":
                df_view = df_view[df_view["ativo_subjacente"] == filtro_ativo]
            if filtro_est != "Todas":
                df_view = df_view[df_view["estrutura"] == filtro_est]

            st.caption(f"Exibindo {len(df_view)} de {len(df_enc)} operações encerradas.")

            colunas_exibir = [
                "codigo", "estrutura", "data_inicio", "data_fim", "dias",
                "preco_pago", "preco_recebido", "resultado_pct", "valor_alocado",
                "valor_final", "resultado_financeiro", "sucesso", "status", "observacoes"
            ]
            df_show = df_view[[c for c in colunas_exibir if c in df_view.columns]].copy()
            df_show.columns = [
                "Código", "Estrutura", "Início", "Fim", "Dias",
                "Pago (R$)", "Recebido (R$)", "Resultado %", "Alocado (R$)",
                "Final (R$)", "Lucro (R$)", "Sucesso", "Status", "Obs"
            ]
            st.dataframe(df_show, use_container_width=True, hide_index=True)

            # Botão de exclusão com segurança
            with st.expander("🗑️ Excluir ou Corrigir uma Operação"):
                op_del = st.selectbox(
                    "Selecione a operação",
                    options=encerradas,
                    format_func=lambda o: f"{o['codigo']} ({_p_data(o['data_inicio'])} a {_p_data(o['data_fim'])}) — Lucro: {_moeda(o['resultado_financeiro'])}"
                )
                if st.button("Excluir Operação Selecionada", type="secondary"):
                    bd.excluir_opcao_operacao(conexao, usuario_id, op_del["id"])
                    st.success("Operação excluída.")
                    st.rerun()

    # --- ABA 3: NOVA OPERAÇÃO MANUAL ---
    with aba_nova:
        st.markdown("#### Cadastrar Nova Operação")
        st.caption("Preencha os dados da sua operação. O ticker preenche automaticamente o ativo base e tipo de opção.")

        with st.form("form_nova_operacao"):
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                cod_in = st.text_input("Código da Opção", placeholder="Ex: PETRK511 ou BOVAI42").strip().upper()
            with fc2:
                estrutura_in = st.selectbox(
                    "Estrutura / Estratégia",
                    ["COMPRA DE CALL", "COMPRA DE PUT", "VENDA DE CALL", "VENDA DE PUT", "TRAVA", "OUTRA"]
                )
            with fc3:
                dt_in = st.date_input("Data de Início", value=date.today())

            info_auto = bd.identificar_opcao(cod_in) if cod_in else {}
            st.caption(f"Detectado: Ativo: **{info_auto.get('ativo_subjacente', '—')}** | Tipo: **{info_auto.get('tipo_opcao', '—')}** | Vencimento: **{info_auto.get('mes_vencimento', '—')}**")

            fc4, fc5, fc6 = st.columns(3)
            with fc4:
                preco_in = st.number_input("Preço Pago Unitário (R$)", min_value=0.01, value=1.00, step=0.01, format="%.2f")
            with fc5:
                qtd_in = st.number_input("Quantidade de Contratos", min_value=1.0, value=100.0, step=100.0)
            with fc6:
                meta_in = st.number_input("Meta de Rolagem (%)", min_value=10.0, value=100.0, step=10.0, help="Alvo de rendimento para disparo do alerta de rolagem.")

            alocado_estimado = qtd_in * preco_in
            st.info(f"Capital total a ser alocado: **{_moeda(alocado_estimado)}**")

            obs_in = st.text_input("Observações / Tese do trade", placeholder="Ex: Rompimento de resistência, volatilidade baixa...")

            submit = st.form_submit_button("Salvar Operação no Diário", type="primary", icon=":material/add:")
            if submit:
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
                        "valor_alocado": alocado_estimado,
                        "meta_rolagem_pct": meta_in,
                        "observacoes": obs_in,
                        "status": "aberta"
                    })
                    st.success(f"Operação {cod_in} cadastrada com sucesso!")
                    st.rerun()

    # --- ABA 4: IMPORTAÇÃO E SINCRONIZAÇÃO ---
    with aba_importar:
        st.markdown("#### Sincronização com Planilha Google")
        st.write(
            "Você pode sincronizar ou reimportar as operações diretamente da sua planilha Google. "
            "A sincronização apenas lê os dados em modo **somente leitura**, sem fazer nenhuma alteração na sua planilha original."
        )

        sheet_id_input = st.text_input(
            "ID da Planilha Google (Spreadsheet ID)",
            value="1N2Sv8LwM_VTT5SVKorBAGS2vUKoKdvn3jdvhlwaUl5k"
        )
        if st.button("📥 Importar / Sincronizar Agora", type="primary", icon=":material/sync:"):
            try:
                with st.spinner("Lendo planilha 'Minhas Operacoes'..."):
                    res = bd.importar_opcoes_google_sheet(conexao, usuario_id, sheet_id_input)
                    st.success(f"Sincronização concluída! {res['importadas']} nova(s) operação(ões) inserida(s) e {res['atualizadas']} atualizada(s).")
                    st.rerun()
            except Exception as e:
                st.error(f"Erro na sincronização: {e}")

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
