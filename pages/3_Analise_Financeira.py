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
import pandas as pd
import streamlit as st

from engine.financial import calcular_fluxo_de_caixa
from engine.models import EconomicConfig

st.set_page_config(page_title="Análise Financeira", page_icon="💰", layout="wide")

st.markdown("### 💰 Análise Financeira do Sistema Híbrido")
st.markdown(
    "Calcule a viabilidade econômica do investimento em FV+BESS, com base na simulação "
    "técnica mais recente (economia de diesel obtida)."
)

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

st.success(
    f"✅ Simulação técnica carregada — Energia solar: {kpis.energia_solar_utilizada_kwh:,.0f} kWh/ano, "
    f"Energia bateria: {kpis.energia_bateria_descarregada_kwh:,.0f} kWh/ano, "
    f"Energia gerador: {kpis.energia_gerador_kwh:,.0f} kWh/ano."
)

st.divider()

# --- INPUTS ECONÔMICOS ---
st.markdown("#### ⚙️ Parâmetros Econômicos")

col_capex, col_diesel, col_financ = st.columns(3)

with col_capex:
    st.markdown("**💵 CAPEX**")
    custo_fv_rs_kwp = st.number_input(
        "Custo FV (R$/kWp)", min_value=0.0, value=6500.0, step=100.0, key="fin_custo_fv"
    )
    custo_bateria_rs_kwh = st.number_input(
        "Custo BESS (R$/kWh)", min_value=0.0, value=2000.0, step=50.0, key="fin_custo_bess",
        help="Custo total do BESS por kWh de capacidade (já inclui o PCS/inversor da bateria, "
        "conforme prática de mercado para sistemas de curta duração).",
    )
    om_pct_am = st.slider(
        "O&M (% do CAPEX/ano)", min_value=0.0, max_value=5.0, value=1.0, step=0.1, key="fin_om"
    ) / 100.0

with col_diesel:
    st.markdown("**⛽ Diesel**")
    preco_diesel_rs_litro = st.number_input(
        "Preço do Diesel (R$/litro)", min_value=0.0, value=7.0, step=0.1, key="fin_diesel_preco"
    )
    inflacao_diesel_am = st.slider(
        "Inflação do Diesel (% a.a.)", min_value=0.0, max_value=20.0, value=5.0, step=0.5, key="fin_diesel_inflacao"
    ) / 100.0
    economia_por_saca_rs = st.number_input(
        "Valor da Saca (R$, referência)", min_value=0.0, value=120.0, step=5.0, key="fin_saca",
        help="Usado apenas para a métrica ilustrativa de economia em sacas de soja.",
    )

with col_financ:
    st.markdown("**🏦 Financiamento**")
    tipo_pagamento = st.selectbox(
        "Tipo de Pagamento", ["RECURSO PRÓPRIO", "FINANCIAMENTO"], key="fin_tipo_pagto"
    )
    if tipo_pagamento == "FINANCIAMENTO":
        pct_financiado = st.slider(
            "% Financiado", min_value=0, max_value=100, value=70, key="fin_pct_financ"
        ) / 100.0
        tipo_financiamento = st.selectbox("Tipo de Financiamento", ["SAC", "PRICE"], key="fin_tipo_financ")
        prazo_anos = st.number_input("Prazo (anos)", min_value=1, value=5, step=1, key="fin_prazo")
        carencia_anos = st.number_input(
            "Carência (anos)", min_value=0, max_value=int(prazo_anos) - 1, value=0, step=1, key="fin_carencia"
        )
        taxa_juros_am = st.number_input(
            "Taxa de Juros (% a.a.)", min_value=0.0, value=10.0, step=0.5, key="fin_taxa_juros"
        ) / 100.0
    else:
        pct_financiado = 0.0
        tipo_financiamento = "SAC"
        prazo_anos = 5
        carencia_anos = 0
        taxa_juros_am = 0.0

st.markdown("**📈 Análise (VPL / Horizonte)**")
col_tma, col_horiz, col_degrad = st.columns(3)
with col_tma:
    tma_am = st.number_input(
        "TMA (% a.a.)", min_value=0.0, value=5.0, step=0.5, key="fin_tma",
        help="Taxa Mínima de Atratividade, usada para descontar o fluxo de caixa no cálculo do VPL.",
    ) / 100.0
with col_horiz:
    horizonte_anos = st.number_input(
        "Horizonte (anos)", min_value=1, value=25, step=1, key="fin_horizonte"
    )
with col_degrad:
    degradacao_fv_am_ano = st.number_input(
        "Degradação FV (% a.a.)", min_value=0.0, value=0.6, step=0.1, key="fin_degradacao"
    ) / 100.0

st.divider()

calcular = st.button("💰 Calcular Viabilidade Econômica", type="primary", width="stretch")

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

if "ultima_analise_financeira" in st.session_state:
    resultado = st.session_state["ultima_analise_financeira"]

    st.markdown("#### 📊 Resultado da Análise")

    col_r1, col_r2, col_r3, col_r4 = st.columns(4)
    col_r1.metric("VPL", f"R$ {resultado.vpl_rs:,.0f}")
    col_r2.metric("TIR", f"{resultado.tir * 100:.1f} %" if resultado.tir is not None else "N/A")
    col_r3.metric("LCOE", f"R$ {resultado.lcoe_rs_kwh:.2f}/kWh")
    col_r4.metric(
        "Payback", f"{resultado.payback_anos} ano(s)" if resultado.payback_anos is not None else "N/A"
    )

    if resultado.vpl_rs > 0:
        st.success("✅ Investimento economicamente viável (VPL positivo).")
    else:
        st.error("❌ Investimento não é viável nas condições atuais (VPL negativo).")

    col_c1, col_c2, col_c3 = st.columns(3)
    col_c1.metric("CAPEX Total", f"R$ {resultado.capex.capex_total_rs:,.0f}")
    col_c2.metric("CAPEX FV", f"R$ {resultado.capex.capex_fv_rs:,.0f}")
    col_c3.metric("CAPEX BESS", f"R$ {resultado.capex.capex_bess_rs:,.0f}")

    st.markdown(
        f"**Economia de diesel (ano 1):** R$ {resultado.economia_diesel_ano1_rs:,.0f} "
        f"(≈ {resultado.economia_em_sacas_ano1:,.0f} sacas de soja/ano)"
    )

    if resultado.financiamento.valor_financiado_rs > 0:
        st.caption(
            f"Valor financiado: R$ {resultado.financiamento.valor_financiado_rs:,.0f} | "
            f"Entrada: R$ {resultado.financiamento.valor_entrada_rs:,.0f}"
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

    st.line_chart(df_fluxo[["Fluxo Acumulado (R$)"]], width="stretch", color="#2ecc71")
    st.bar_chart(df_fluxo[["Fluxo de Caixa (R$)"]], width="stretch", color="#3498db")

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
        "📥 Baixar fluxo de caixa (CSV)",
        data=csv,
        file_name="fluxo_de_caixa.csv",
        mime="text/csv",
    )
else:
    st.info("Configure os parâmetros econômicos acima e clique em **Calcular Viabilidade Econômica**.")

st.divider()
st.caption(
    "Nota metodológica: o CAPEX do gerador diesel não é incluído no investimento — o modelo "
    "assume um parque de geradores pré-existente, e a viabilidade vem da economia de diesel "
    "obtida ao adicionar FV+BESS. Tarifas de concessionária e demanda contratada (modo "
    "ZERO-GRID) ainda não são consideradas nesta fase."
)
