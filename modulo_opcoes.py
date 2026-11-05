"""
Módulo de Gestão e Diário de Operações de Opções — FiscoTrade.

Permite ao investidor de derivativos acompanhar suas posições abertas em formato slim,
monitorar o rendimento %, acionar a rolagem com preservação de capital (50% no bolso e 50% reinvestido
em opções líquidas próximas do dinheiro), registrar operações de forma ultra-rápida e importar planilhas Excel/CSV.
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
        "💡 **Critério de Rolagem**: Ao bater a meta de lucro (ex: +100%), o operador "
        "guarda **~50% do valor final no bolso** (lucro garantido) e reinveste os outros **50% "
        "na nova opção**, buscando **boa liquidez** e preço de exercício **mais próximo da linha do dinheiro (ATM)**."
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
            help="Preço unitário de saída para encerrar a perna atual."
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
    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("Total Obtido", _moeda(valor_final), f"+{lucro_pct:.1f}%")
    with m2:
        st.metric("💰 50% Lucro no Bolso", _moeda(metade_bolso))
    with m3:
        st.metric("🚀 50% Reinvestir", _moeda(metade_reinvestir))

    st.markdown("---")
    st.markdown("#### Nova Opção (Perna Futura)")

    nc1, nc2, nc3 = st.columns(3)
    with nc1:
        novo_codigo = st.text_input(
            "Novo Código da Opção",
            value="",
            placeholder="Ex: BEEFX400",
            help="Escolha uma opção com boa liquidez mais próxima do dinheiro (ATM)."
        ).strip().upper()
    with nc2:
        novo_preco = st.number_input(
            "Preço Unitário da Nova (R$)",
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
    st.caption(f"Valor a alocar na nova opção: **{_moeda(novo_alocado_calc)}**")

    obs = st.text_input("Observações", value="Rolagem com preservação de 50% de lucro.")

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
            st.success(f"Rolagem executada! {codigo} encerrada e {novo_codigo} aberta.")
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
        st.success(f"Operação {codigo} encerrada!")
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
        format="%.2f"
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
        st.info("👋 **Bem-vindo ao Diário de Opções!** Você ainda não possui operações cadastradas. Anexe sua planilha Excel/CSV na aba 'Importar Planilha' ou cadastre sua primeira operação abaixo.")

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
        with st.container():
            st.warning(
                f"🎯 **Gatilho de Rolagem Atingido!** {len(rolagens_prontas)} opção(ões) atingiram a meta de lucro (≥100%). "
                "Critério sugerido: **embolsar 50% do valor final** e **rolar os outros 50%** para a opção ATM mais líquida da próxima série."
            )
            for op_pronta, rend_pct in rolagens_prontas:
                c_al1, c_al2 = st.columns([3, 1])
                with c_al1:
                    st.markdown(f"**{op_pronta['codigo']}** ({op_pronta.get('estrutura')}) — Entrada: `{_moeda(op_pronta['preco_pago'])}` | Atual: `{_moeda(op_pronta['preco_atual'])}` | Rendimento: **+{rend_pct:.1f}%** 🚀")
                with c_al2:
                    if st.button(f"🔄 Rolar {op_pronta['codigo']}", key=f"btn_alerta_rol_{op_pronta['id']}", type="primary", use_container_width=True):
                        modal_rolar_opcao(op_pronta)

    # 4. Abas do Diário (Slim & Rápido)
    aba_abertas, aba_encerradas, aba_nova, aba_importar = st.tabs([
        f"🟢 Posições Abertas ({len(abertas)})",
        f"📜 Histórico Encerradas ({len(encerradas)})",
        "➕ Nova Operação",
        "📥 Importar Planilha"
    ])

    # --- ABA 1: POSIÇÕES ABERTAS (FORMATO SLIM TABLE) ---
    with aba_abertas:
        if not abertas:
            st.info("Nenhuma posição aberta no momento.")
        else:
            st.caption(f"{len(abertas)} opções abertas em carteira. Visualize o rendimento e acione as ações rapidamente.")

            # Montagem do DataFrame slim
            linhas_abertas = []
            for op in abertas:
                p_pago = float(op["preco_pago"])
                p_atual = float(op.get("preco_atual") or p_pago)
                meta = float(op.get("meta_rolagem_pct") or 100.0)
                alocado_op = float(op["valor_alocado"])
                qtd_op = float(op["quantidade"])

                if p_pago > 0:
                    rend_pct = ((p_atual - p_pago) / p_pago) * 100
                else:
                    rend_pct = 0.0

                atingiu = rend_pct >= meta
                status_aviso = f"🎯 ROLAR (+{rend_pct:.1f}%)" if atingiu else (f"+{rend_pct:.1f}%" if rend_pct > 0 else f"{rend_pct:.1f}%")

                linhas_abertas.append({
                    "ID": op["id"],
                    "Código": op["codigo"],
                    "Ativo": op.get("ativo_subjacente", "—"),
                    "Estrutura": op.get("estrutura", "—"),
                    "Início": _p_data(op["data_inicio"]),
                    "Qtd": int(qtd_op),
                    "Pago (R$)": p_pago,
                    "Atual (R$)": p_atual,
                    "Rendimento %": f"{rend_pct:+.1f}%",
                    "Alocado (R$)": alocado_op,
                    "Meta": f"{meta:.0f}%",
                    "Gatilho": "🎯 ROLAR" if atingiu else "Em andamento"
                })

            df_ab_view = pd.DataFrame(linhas_abertas)
            st.dataframe(
                df_ab_view.drop(columns=["ID"]),
                use_container_width=True,
                hide_index=True
            )

            # Barra de Ações Rápidas por Opção
            st.markdown("##### ⚡ Ações Rápidas para Posições Abertas")
            col_sel, col_act1, col_act2, col_act3, col_act4 = st.columns([2.5, 1.2, 1.2, 1.2, 1])

            opcoes_dict = {o["id"]: f"{o['codigo']} ({o.get('estrutura')}) - Pago {_moeda(o['preco_pago'])}" for o in abertas}
            with col_sel:
                op_escolhida_id = st.selectbox(
                    "Selecione uma opção:",
                    options=list(opcoes_dict.keys()),
                    format_func=lambda i: opcoes_dict[i],
                    key="sel_op_aberta_acao"
                )

            op_alvo = next((o for o in abertas if o["id"] == op_escolhida_id), None)
            if op_alvo:
                with col_act1:
                    if st.button("🔄 Rolar", type="primary", use_container_width=True, help="Rolar com 50% no bolso"):
                        modal_rolar_opcao(op_alvo)
                with col_act2:
                    if st.button("✏️ Cotação", use_container_width=True, help="Atualizar preço corrente"):
                        modal_atualizar_cotacao(op_alvo)
                with col_act3:
                    if st.button("🏁 Encerrar", use_container_width=True, help="Encerrar posição"):
                        modal_encerrar_opcao(op_alvo)
                with col_act4:
                    if st.button("💨 Pó", use_container_width=True, help="Encerrar a R$ 0,00"):
                        bd.encerrar_opcao_operacao(
                            conexao, usuario_id, op_alvo["id"],
                            data_fim=date.today().strftime("%d/%m/%Y"),
                            preco_recebido=0.00,
                            observacoes="Expirou no pó"
                        )
                        st.success(f"{op_alvo['codigo']} encerrada no pó.")
                        st.rerun()

            # Editor rápido de cotações em massa
            with st.expander("⚡ Atualizar Cotações de Todas as Opções Abertas (Tabela Rápida)"):
                st.caption("Edite a coluna 'Atual (R$)' das opções e clique no botão abaixo para recalcular todos os rendimentos:")
                df_editor = df_ab_view[["ID", "Código", "Pago (R$)", "Atual (R$)"]].copy()
                editado = st.data_editor(
                    df_editor,
                    disabled=["ID", "Código", "Pago (R$)"],
                    use_container_width=True,
                    hide_index=True,
                    key="editor_cotacoes_em_massa"
                )
                if st.button("Salvar Todas as Cotações", type="primary", icon=":material/save:"):
                    for _, row in editado.iterrows():
                        oid = int(row["ID"])
                        nova_cot = float(row["Atual (R$)"])
                        bd.atualizar_cotacao_opcao(conexao, usuario_id, oid, nova_cot)
                    st.success("Todas as cotações foram atualizadas com sucesso!")
                    st.rerun()

    # --- ABA 2: HISTÓRICO DE ENCERRADAS (SLIM TABLE) ---
    with aba_encerradas:
        if not encerradas:
            st.info("Nenhuma operação encerrada ainda.")
        else:
            df_enc = pd.DataFrame(encerradas)
            col_fil1, col_fil2 = st.columns(2)
            with col_fil1:
                ativos_unicos = ["Todos"] + sorted(list({str(x) for x in df_enc["ativo_subjacente"] if pd.notna(x)}))
                filtro_ativo = st.selectbox("Filtrar por Ativo Subjacente", ativos_unicos, key="fil_enc_ativo")
            with col_fil2:
                estruturas = ["Todas"] + sorted(list({str(x) for x in df_enc["estrutura"] if pd.notna(x)}))
                filtro_est = st.selectbox("Filtrar por Estrutura", estruturas, key="fil_enc_est")

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

            with st.expander("🗑️ Excluir ou Corrigir uma Operação"):
                op_del = st.selectbox(
                    "Selecione a operação",
                    options=encerradas,
                    format_func=lambda o: f"{o['codigo']} ({_p_data(o['data_inicio'])} a {_p_data(o['data_fim'])}) — Lucro: {_moeda(o['resultado_financeiro'])}",
                    key="sel_op_del"
                )
                if st.button("Excluir Operação Selecionada", type="secondary"):
                    bd.excluir_opcao_operacao(conexao, usuario_id, op_del["id"])
                    st.success("Operação excluída.")
                    st.rerun()

    # --- ABA 3: NOVA OPERAÇÃO MANUAL (SIMPLES COMO PREENCHER PLANILHA) ---
    with aba_nova:
        st.markdown("#### ⚡ Adicionar Operação Rápida")
        st.caption("Preencha apenas o código, estrutura, data e preço pago. O ativo base e tipo são identificados na hora.")

        with st.form("form_nova_operacao_rapida"):
            r1, r2, r3, r4, r5 = st.columns([1.5, 1.8, 1.2, 1.2, 1.3])
            with r1:
                cod_in = st.text_input("Código da Opção", placeholder="Ex: BEEFX400").strip().upper()
            with r2:
                estrutura_in = st.selectbox(
                    "Estrutura",
                    ["COMPRA DE CALL", "COMPRA DE PUT", "VENDA DE CALL", "VENDA DE PUT", "TRAVA", "OUTRA"]
                )
            with r3:
                dt_in = st.date_input("Data Início", value=date.today())
            with r4:
                preco_in = st.number_input("Preço Pago (R$)", min_value=0.01, value=0.50, step=0.01, format="%.2f")
            with r5:
                aloc_in = st.number_input("Valor Alocado (R$)", min_value=1.0, value=150.0, step=10.0, format="%.2f")

            obs_in = st.text_input("Observações (opcional)", placeholder="Ex: Entrada por tendência / rompimento")

            # Cálculo automático de quantidade
            qtd_estimada = round(aloc_in / preco_in) if preco_in > 0 else 100
            st.caption(f"Quantidade estimada de contratos: **{qtd_estimada}** | Preço unitário: **{_moeda(preco_in)}**")

            salvar = st.form_submit_button("➕ Salvar Operação no Diário", type="primary", use_container_width=True)
            if salvar:
                if not cod_in:
                    st.error("Informe o código da opção.")
                else:
                    bd.salvar_opcao_operacao(conexao, usuario_id, {
                        "codigo": cod_in,
                        "estrutura": estrutura_in,
                        "data_inicio": dt_in.strftime("%d/%m/%Y"),
                        "quantidade": qtd_estimada,
                        "preco_pago": preco_in,
                        "preco_atual": preco_in,
                        "valor_alocado": aloc_in,
                        "meta_rolagem_pct": 100.0,
                        "observacoes": obs_in,
                        "status": "aberta"
                    })
                    st.success(f"Operação {cod_in} cadastrada com sucesso!")
                    st.rerun()

    # --- ABA 4: IMPORTAR PLANILHA ---
    with aba_importar:
        st.markdown("#### Importar Planilha de Operações (Excel ou CSV)")
        st.write(
            "Anexe a planilha com o histórico das suas operações. O leitor identifica automaticamente "
            "as colunas de **Código/Ticker**, **Estrutura**, **Datas**, **Preço Pago**, **Preço Recebido**, "
            "**Valor Alocado** e **Status**."
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
                        st.success(f"Importação realizada com sucesso! {res['importadas']} nova(s) operação(ões) inserida(s) e {res['atualizadas']} atualizada(s).")
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
