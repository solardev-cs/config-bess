"""Página Streamlit: Análise Financeira do Sistema Híbrido.

Consome o resultado da última simulação técnica (página "Simulação
Técnica") e os parâmetros econômicos/financeiros informados pelo usuário
para calcular:
    - CAPEX (FV + BESS);
    - Financiamento (recurso próprio ou financiado, SAC ou PRICE);
    - Fluxo de caixa anual ao longo do horizonte (padrão 25 anos);
    - VPL, TIR, LCOE e Payback.

Esta página não duplica nenhuma lógica de negócio: apenas monta
``EconomicConfig`` a partir dos inputs do usuário e chama
``engine.financial.calcular_fluxo_de_caixa``.
"""
import altair as alt
import pandas as pd
import streamlit as st

from engine.costs import CUSTO_BESS_PADRAO_RS_KWH
from engine.financial import calcular_fluxo_de_caixa
from engine.formatting import formatar_brl, formatar_numero
from engine.models import EconomicConfig
from views._custos_referencia import custo_fv_efetivo_rs_kwp
from views._nav import stepper
from views._persist import indice_persistido, persistir, valor_persistido
from views._staleness import aviso_se_desatualizado, publicar_snapshot_atual, snapshot_financeiro

stepper("views/analise_financeira.py")

# --- VERIFICA SE HÁ SIMULAÇÃO TÉCNICA DISPONÍVEL ---
resultado_tecnico = st.session_state.get("ultima_simulacao")
solar_config = st.session_state.get("ultima_solar_config")
battery_config = st.session_state.get("ultima_battery_config")
generator_config = st.session_state.get("ultima_generator_config")

if resultado_tecnico is None or solar_config is None:
    st.warning(
        "⚠️ Nenhuma simulação técnica encontrada. Vá até a página "
        "**Simulação Técnica**, configure o sistema e rode a simulação antes de continuar."
    )
    st.stop()

kpis = resultado_tecnico.kpis

# --- INPUTS ECONÔMICOS ---
st.markdown("#### :primary[:material/candlestick_chart:] Parâmetros Econômicos")

custo_fv_rs_kwp = custo_fv_efetivo_rs_kwp()
custo_bateria_rs_kwh = valor_persistido("cfg_custo_bess", CUSTO_BESS_PADRAO_RS_KWH)
preco_diesel_rs_litro = valor_persistido("cfg_preco_diesel", 7.0)
tma_am = valor_persistido("cfg_tma", 5.0) / 100.0
economia_por_saca_rs = valor_persistido("cfg_valor_saca", 120.0)
horizonte_anos = valor_persistido("cfg_horizonte_anos", 25)
degradacao_fv_am_ano = valor_persistido("cfg_degradacao_fv", 0.6) / 100.0

col_financ, col_diesel, col_capex, col_link = st.columns(4)

with col_link:
    st.write("")
    st.write("")
    st.write("")
    st.write("")
    st.page_link("views/configuracoes.py", label="Editar", icon=":material/settings_b_roll:")
  
with col_capex:
    st.markdown("**:material/payments: OPEX**")
    om_pct_am = persistir("fin_om", st.slider(
        "O&M (% do CAPEX/ano)", min_value=0.0, max_value=5.0, value=valor_persistido("fin_om", 1.0), step=0.1, key="fin_om"
    )) / 100.0

with col_diesel:
    st.markdown("**:material/oil_barrel: Diesel**")
    inflacao_diesel_am = persistir("fin_diesel_inflacao", st.slider(
        "Inflação do Diesel (% a.a.)", min_value=0.0, max_value=20.0, value=valor_persistido("fin_diesel_inflacao", 5.0), step=0.5, key="fin_diesel_inflacao"
    )) / 100.0

with col_financ:
    st.markdown("**:material/currency_exchange: Financiamento**")
    _opcoes_pagto = ["RECURSO PRÓPRIO", "FINANCIAMENTO"]
    tipo_pagamento = persistir("fin_tipo_pagto", st.selectbox(
        "Tipo de Pagamento", _opcoes_pagto,
        index=indice_persistido("fin_tipo_pagto", _opcoes_pagto),
        key="fin_tipo_pagto",
    ))
    if tipo_pagamento == "FINANCIAMENTO":
        pct_financiado = persistir("fin_pct_financ", st.slider(
            "% Financiado", min_value=0, max_value=100, value=valor_persistido("fin_pct_financ", 70), key="fin_pct_financ"
        )) / 100.0
        _opcoes_financ = ["SAC", "PRICE"]
        tipo_financiamento = persistir("fin_tipo_financ", st.selectbox(
            "Tipo de Financiamento", _opcoes_financ,
            index=indice_persistido("fin_tipo_financ", _opcoes_financ),
            key="fin_tipo_financ",
        ))
        prazo_anos = persistir("fin_prazo", st.number_input("Prazo (anos)", min_value=1, value=valor_persistido("fin_prazo", 5), step=1, key="fin_prazo"))
        carencia_anos = persistir("fin_carencia", st.number_input(
            "Carência (anos)", min_value=0, max_value=int(prazo_anos) - 1,
            value=min(valor_persistido("fin_carencia", 0), int(prazo_anos) - 1), step=1, key="fin_carencia",
        ))
        taxa_juros_am = persistir("fin_taxa_juros", st.number_input(
            "Taxa de Juros (% a.a.)", min_value=0.0, value=valor_persistido("fin_taxa_juros", 10.0), step=0.5, key="fin_taxa_juros"
        )) / 100.0
    else:
        pct_financiado = 0.0
        tipo_financiamento = "SAC"
        prazo_anos = 5
        carencia_anos = 0
        taxa_juros_am = 0.0

st.caption(
    (
        f"Custo FV: **{formatar_brl(custo_fv_rs_kwp, 0)}/kWp** | "
        f"Custo BESS: **{formatar_brl(custo_bateria_rs_kwh, 0)}/kWh** | "
        f"Preço Diesel: **{formatar_brl(preco_diesel_rs_litro, 2)}/L** | "
        f"TMA: **{formatar_numero(tma_am * 100, 1)}% a.a.** | "
        f"Horizonte: **{int(horizonte_anos)} anos** | "
        f"Degradação FV: **{formatar_numero(degradacao_fv_am_ano * 100, 1)}% a.a.**"
    # Escapa "$" — o markdown do Streamlit trata "$...$" como delimitador de
    # LaTeX/matemática; com dois "R$" na mesma legenda (Custo FV e Custo
    # BESS), tudo entre o 1º e o 2º "$" virava fórmula em vez de texto.
    ).replace("$", "\\$")
)

# Publica o snapshot atual dos widgets a cada rerun desta página (não só ao
# clicar em Calcular) — outras páginas (Relatório) leem esta cópia para
# detectar desatualização, já que o Streamlit descarta os valores dos
# widgets acima assim que o usuário navega para outra página.
snapshot_atual_financeiro = snapshot_financeiro(resultado_tecnico)
publicar_snapshot_atual("financeiro_widgets_atual", snapshot_atual_financeiro)

col_opt1, col_opt2 = st.columns([1, 2])
with col_opt1:
    st.write("")
    calcular = st.button(":material/functions: Cálculo Econômico", type="primary", width="stretch")

if calcular:
    economic_config = EconomicConfig(
        custo_fv_rs_kwp=custo_fv_rs_kwp,
        custo_bateria_rs_kwh=custo_bateria_rs_kwh,
        preco_diesel_rs_litro=preco_diesel_rs_litro,
        inflacao_diesel_am=inflacao_diesel_am,
        tma_am=tma_am,
        om_pct_am=om_pct_am,
        tipo_pagamento=tipo_pagamento,
        pct_financiado=pct_financiado,
        tipo_financiamento=tipo_financiamento,
        prazo_anos=int(prazo_anos),
        carencia_anos=int(carencia_anos),
        taxa_juros_am=taxa_juros_am,
        degradacao_fv_am_ano=degradacao_fv_am_ano,
        horizonte_anos=int(horizonte_anos),
        economia_por_saca_rs=economia_por_saca_rs,
    )

    resultado_financeiro = calcular_fluxo_de_caixa(
        kpis, solar_config, battery_config, generator_config, economic_config
    )
    st.session_state["ultima_analise_financeira"] = resultado_financeiro
    st.session_state["ultima_analise_financeira_config"] = snapshot_atual_financeiro

if "ultima_analise_financeira" in st.session_state:
    resultado = st.session_state["ultima_analise_financeira"]
  
    st.divider()
  
    st.markdown("#### :primary[:material/analytics:] Resultado da Análise")

    aviso_se_desatualizado(
        "ultima_analise_financeira_config",
        snapshot_atual_financeiro,
        "Os parâmetros econômicos ou a configuração do sistema foram alterados desde o último cálculo. Os resultados abaixo são do cálculo anterior — "
        "rode o **Cálculo Econômico** novamente.",
    )

    col_r1, col_r2, col_r3, col_r4 = st.columns(4)
    col_r1.metric("VPL", formatar_brl(resultado.vpl_rs, 0))
    col_r2.metric("TIR", f"{formatar_numero(resultado.tir * 100, 1)} %" if resultado.tir is not None else "N/A")
    col_r3.metric("LCOE", f"{formatar_brl(resultado.lcoe_rs_kwh, 2)}/kWh")
    col_r4.metric(
        "Payback", f"{resultado.payback_anos} ano(s)" if resultado.payback_anos is not None else "N/A"
    )

    if resultado.vpl_rs > 0:
        st.success("✅ Investimento economicamente viável (VPL positivo).")
    else:
        st.error("❌ Investimento não é viável nas condições atuais (VPL negativo).")

    col_c1, col_c2, col_c3 = st.columns(3)
    col_c1.metric("CAPEX Total", formatar_brl(resultado.capex.capex_total_rs, 0))
    col_c2.metric("CAPEX FV", formatar_brl(resultado.capex.capex_fv_rs, 0))
    col_c3.metric("CAPEX BESS", formatar_brl(resultado.capex.capex_bess_rs, 0))

    st.markdown(
        f"**Economia de diesel (ano 1):** {formatar_brl(resultado.economia_diesel_ano1_rs, 0)} "
        f"(≈ {formatar_numero(resultado.economia_em_sacas_ano1, 0)} sacas de soja/ano)"
    )
    if kpis.consumo_diesel_base_litros is not None:
        st.caption(
            f"Diesel sem FV/BESS: {formatar_numero(kpis.consumo_diesel_base_litros, 0)} L/ano − "
            f"diesel do sistema: {formatar_numero(kpis.consumo_diesel_litros, 0)} L/ano = "
            f"evitado: {formatar_numero(resultado.economia_diesel_litros_ano1, 0)} L/ano."
        )

    if resultado.financiamento.valor_financiado_rs > 0:
        st.caption(
            f"Valor financiado: {formatar_brl(resultado.financiamento.valor_financiado_rs, 0)} | "
            f"Entrada: {formatar_brl(resultado.financiamento.valor_entrada_rs, 0)}"
        )

    st.markdown("**Fluxo de Caixa Acumulado**")
    df_fluxo = pd.DataFrame(
        [
            {
                "Ano": f.ano,
                "Fluxo de Caixa (R$)": f.fluxo_caixa_rs,
                "Fluxo Acumulado (R$)": f.fluxo_acumulado_rs,
            }
            for f in resultado.fluxos
        ]
    ).set_index("Ano")

    # st.bar_chart não permite girar os rótulos do eixo X; Altair sim (anos na vertical).
    grafico_fluxo = (
        alt.Chart(df_fluxo[["Fluxo Acumulado (R$)"]].reset_index())
        .mark_bar(color="#2ecc71")
        .encode(
            x=alt.X("Ano:O", title="Ano", axis=alt.Axis(labelAngle=-90)),
            y=alt.Y("Fluxo Acumulado (R$):Q", title="Fluxo Acumulado (R$)"),
            tooltip=["Ano:O", alt.Tooltip("Fluxo Acumulado (R$):Q", format=",.0f")],
        )
    )
    st.altair_chart(grafico_fluxo, width="stretch")

    with st.expander("Ver tabela completa de fluxo de caixa"):
        df_tabela = pd.DataFrame(
            [
                {
                    "Ano": f.ano,
                    "Energia Evitada (kWh)": f.energia_evitada_kwh,
                    "Economia Diesel (R$)": f.economia_diesel_rs,
                    "O&M (R$)": f.om_rs,
                    "Parcela Financiamento (R$)": f.parcela_financiamento_rs,
                    "Fluxo de Caixa (R$)": f.fluxo_caixa_rs,
                    "Fluxo Acumulado (R$)": f.fluxo_acumulado_rs,
                }
                for f in resultado.fluxos
            ]
        )
        st.dataframe(df_tabela, width="stretch", hide_index=True)

    csv = df_tabela.to_csv(index=False).encode("utf-8")
    st.download_button(
        "📥 Baixar Fluxo de Caixa em CSV",
        data=csv,
        file_name="fluxo_de_caixa.csv",
        mime="text/csv",
    )

st.divider()
st.caption(
    "Nota metodológica: o CAPEX do gerador diesel não é incluído no investimento — o modelo "
    "assume um parque de geradores pré-existente, e a viabilidade vem da economia de diesel "
    "obtida ao adicionar FV+BESS. Tarifas de concessionária e demanda contratada (modo "
    "ZERO-GRID) ainda não são consideradas nesta fase."
)
