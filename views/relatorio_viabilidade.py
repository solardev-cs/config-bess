"""Página Streamlit: Relatório de Viabilidade Econômica do Sistema Híbrido.

Consolida em um único relatório objetivo os dados coletados/calculados nas
páginas anteriores:
    - Home (identificação do projeto);
    - Perfil de Carga (Lista de Cargas + perfil de consumo);
    - Simulação Técnica (dados técnicos do sistema FV+BESS+Diesel);
    - Análise Financeira (fluxo de caixa, VPL, TIR, LCOE, Payback).

Não duplica nenhuma lógica de negócio: apenas lê os resultados já
persistidos em ``st.session_state`` e os organiza visualmente, no mesmo
espírito da aba "Resumo" da planilha original (``history/Config_OFF.xlsx``).

Além dos itens da planilha original, adiciona métricas de economia por
hectare irrigado — mais intuitivas para o produtor rural do que apenas
R$/kWh ou R$ totais — e permite baixar o relatório completo em PDF.
"""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from engine.costs import custo_geracao_diesel_rs_kwh
from engine.formatting import formatar_brl, formatar_numero
from engine.report_pdf import GrupoCargaInfo, RelatorioContexto, gerar_pdf_relatorio
from views._nav import stepper
from views._persist import valor_persistido
from views._staleness import aviso_se_desatualizado

stepper("views/relatorio_viabilidade.py")

# --- VERIFICA SE HÁ DADOS SUFICIENTES DAS PÁGINAS ANTERIORES ---
carga_kw = st.session_state.get("carga_kw")
carga_grupos = st.session_state.get("carga_grupos", [])
resultado_tecnico = st.session_state.get("ultima_simulacao")
solar_config = st.session_state.get("ultima_solar_config")
battery_config = st.session_state.get("ultima_battery_config")
generator_config = st.session_state.get("ultima_generator_config")
resultado_financeiro = st.session_state.get("ultima_analise_financeira")

faltando = []
if carga_kw is None:
    faltando.append("**Perfil de Carga**")
if resultado_tecnico is None or solar_config is None:
    faltando.append("**Simulação Técnica**")
if resultado_financeiro is None:
    faltando.append("**Análise Financeira**")

if faltando:
    st.warning(
        "⚠️ Para gerar o relatório completo, primeiro conclua as etapas anteriores: "
        + ", ".join(faltando)
        + "."
    )
    st.stop()

kpis = resultado_tecnico.kpis
df_tecnico = resultado_tecnico.df

# Compara com a última foto PUBLICADA pelas próprias páginas de origem
# (não recalcula ao vivo aqui) — o Streamlit descarta o valor dos widgets de
# Simulação Técnica/Análise Financeira assim que se navega para outra
# página, então um recálculo feito a partir do Relatório sempre daria tudo
# desatualizado. Ver `views/_staleness.py` para o porquê.
sim_desatualizada = aviso_se_desatualizado(
    "ultima_simulacao_config",
    st.session_state.get("simulacao_widgets_atual"),
    "A configuração do sistema mudou. Revise e "
    "simule novamente antes de enviar o relatório ao cliente.",
)
fin_desatualizada = aviso_se_desatualizado(
    "ultima_analise_financeira_config",
    st.session_state.get("financeiro_widgets_atual"),
    "A análise financeira mudou. Revise e calcule novamente "
    "antes de enviar o relatório ao cliente.",
)

# --- 1. CABEÇALHO DO RELATÓRIO ---
st.markdown("#### :primary[:material/assignment:] Identificação do Projeto")

cliente = valor_persistido("home_cliente", "")
cidade = valor_persistido("home_cidade", "")
estado_relatorio = valor_persistido("home_estado", "")
gnf = valor_persistido("home_gnf", "")
revisao = valor_persistido("home_revisao", "Rev01")

col_h1, col_h2, col_h3, col_h4 = st.columns(4)
col_h1.metric("Cliente", cliente or "—")
col_h2.metric("Cidade", cidade or "—")
col_h3.metric("Estado (UF)", estado_relatorio or "—")
col_h4.metric("GNF / Nº do Projeto", gnf or "—")
st.caption(f"Revisão: {revisao} — edite esses dados na página **Home**.")

st.divider()

# --- 2. LISTA DE CARGAS ---
st.markdown("#### :primary[:material/bolt:] Lista de Cargas")

if carga_grupos:
    linhas_cargas = []
    grupos_info: list[GrupoCargaInfo] = []
    area_total_ha = 0.0

    for g in carga_grupos:
        descricao = g["cultura_principal"]
        if g.get("cultura_sucessao"):
            descricao += f" + {g['cultura_sucessao']}"
        potencia_kw = g["potencia_kw"]
        potencia_cv = potencia_kw / 0.7355  # 1 CV = 0,7355 kW
        area_ha = g.get("area_ha", 0.0) or 0.0
        area_total_ha += area_ha

        linhas_cargas.append(
            {
                "Grupo": g["nome"],
                "Descrição": descricao,
                "Potência (CV)": formatar_numero(potencia_cv, 1),
                "Potência (kW)": formatar_numero(potencia_kw, 1),
                "Lâmina (mm/21h)": formatar_numero(g['lamina_mm_21h'], 1),
                "Área (ha)": formatar_numero(area_ha, 0) if area_ha > 0 else "—",
            }
        )
        grupos_info.append(
            GrupoCargaInfo(
                nome=g["nome"],
                descricao=descricao,
                potencia_kw=potencia_kw,
                potencia_cv=potencia_cv,
                lamina_mm_21h=g["lamina_mm_21h"],
                area_ha=area_ha,
            )
        )

    st.dataframe(pd.DataFrame(linhas_cargas), width="stretch", hide_index=True)
else:
    st.info("Nenhum detalhe de grupo de carga encontrado — apenas o consumo total será exibido.")
    grupos_info = []
    area_total_ha = 0.0

consumo_anual_kwh = float(sum(carga_kw))
potencia_total_kw = float(max(carga_kw)) if len(carga_kw) else 0.0

col_m1, col_m2, col_m3 = st.columns(3)
col_m1.metric("Potência Total", f"{formatar_numero(potencia_total_kw, 1)} kW")
col_m2.metric("Consumo Total", f"{formatar_numero(consumo_anual_kwh, 0)} kWh/ano")
if area_total_ha > 0:
    col_m3.metric("Área Irrigada Total", f"{formatar_numero(area_total_ha, 0)} ha")

st.divider()

# --- 3. PERFIL DE CONSUMO ---
st.markdown("#### :primary[:material/bar_chart:] Perfil de Consumo")

dates = pd.date_range(start="2023-01-01", periods=8760, freq="h")
df_carga = pd.DataFrame({"carga_kw": carga_kw}, index=dates)
consumo_mensal = df_carga["carga_kw"].resample("MS").sum()
meses_nomes = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

fig_anual, ax_anual = plt.subplots(figsize=(9, 3))
ax_anual.bar(meses_nomes, consumo_mensal.to_numpy(), color="#7f8c8d")
ax_anual.set_title("Perfil Anual de Consumo (kWh/mês)")
ax_anual.set_ylabel("kWh")
ax_anual.grid(axis="y", alpha=0.3)
fig_anual.tight_layout()

buf_anual = io.BytesIO()
fig_anual.savefig(buf_anual, format="png", dpi=150)
plt.close(fig_anual)
grafico_perfil_anual_png = buf_anual.getvalue()

st.pyplot(fig_anual)

dia_exemplo = st.slider(
    "Dia do ano para o perfil híbrido (carga x FV x bateria x diesel)", 1, 365,
    value=st.session_state.get("rel_dia_exemplo", 180), key="rel_dia_exemplo",
)
inicio_h = (dia_exemplo - 1) * 24
fim_h = inicio_h + 24

df_dia = pd.DataFrame(
    {
        "Carga (kW)": df_tecnico["carga_kw"].to_numpy()[inicio_h:fim_h],
        "Solar (kW)": df_tecnico["solar_utilizado_kw"].to_numpy()[inicio_h:fim_h],
        "Bateria (kW)": df_tecnico["bateria_descarga_kw"].to_numpy()[inicio_h:fim_h],
        "Diesel (kW)": df_tecnico["gerador_kw"].to_numpy()[inicio_h:fim_h],
    },
    index=range(24),
)

fig_dia, ax_dia = plt.subplots(figsize=(9, 3))
ax_dia.plot(df_dia.index, df_dia["Carga (kW)"], color="#2c3e50", label="Carga", linewidth=2)
ax_dia.plot(df_dia.index, df_dia["Solar (kW)"], color="#f39c12", label="Solar (FV)")
ax_dia.plot(df_dia.index, df_dia["Bateria (kW)"], color="#3498db", label="Bateria")
ax_dia.plot(df_dia.index, df_dia["Diesel (kW)"], color="#7f8c8d", label="Diesel")
ax_dia.set_title(f"Perfil Híbrido — Dia {dia_exemplo}")
ax_dia.set_xlabel("Hora do dia")
ax_dia.set_ylabel("kW")
ax_dia.legend(loc="upper right", fontsize=8)
ax_dia.grid(alpha=0.3)
fig_dia.tight_layout()

buf_dia = io.BytesIO()
fig_dia.savefig(buf_dia, format="png", dpi=150)
plt.close(fig_dia)
grafico_perfil_hibrido_png = buf_dia.getvalue()

st.pyplot(fig_dia)

st.divider()

# --- 4. DADOS TÉCNICOS DO SISTEMA ---
st.markdown("#### :primary[:material/handyman:] Dados Técnicos do Sistema")

col_t1, col_t2, col_t3 = st.columns(3)
col_t1.metric("Potência FV", f"{formatar_numero(solar_config.pot_pico_kwp, 0)} kWp / {formatar_numero(solar_config.pot_inv_kw, 0)} kW")
col_t2.metric(
    "Potência Diesel",
    f"{formatar_numero(generator_config.pot_total_kw, 0)} kW ({generator_config.nr_maquinas}x {formatar_numero(generator_config.pot_prime_kva, 0)} kVA)",
)
col_t3.metric("Potência BESS", f"{formatar_numero(battery_config.capacidade_kwh, 0)} kWh / {formatar_numero(battery_config.potencia_kw, 0)} kW")

# No acoplamento CC, "Energia FV" (``energia_solar_utilizada_kwh``) é sempre 0 kWh por
# construção — toda a energia solar passa pelo BESS antes de chegar à carga (ver
# ``engine/dispatch/dc_coupled.py``) — então essa tile troca de fonte para
# ``energia_solar_armazenada_kwh``, mesmo tratamento já aplicado em Simulação Técnica.
acoplamento_bess = st.session_state.get("ultima_bess_acoplamento", "CA")

col_t4, col_t5, col_t6, col_t7 = st.columns(4)
if acoplamento_bess == "CC":
    col_t4.metric(
        "Energia FV Armazenada", f"{formatar_numero(kpis.energia_solar_armazenada_kwh, 0)} kWh/ano",
        help="Energia solar que efetivamente carregou o BESS no ano (acoplamento CC) — a "
        "diferença até a energia do BESS é a perda de round-trip.",
    )
else:
    col_t4.metric("Energia FV", f"{formatar_numero(kpis.energia_solar_utilizada_kwh, 0)} kWh/ano")
col_t5.metric(
    "Fração Renovável", f"{formatar_numero(kpis.fracao_energia_origem_solar * 100, 1)} %",
    help="Fração da carga coberta por energia de origem solar, direta ou via BESS — mesma "
    "conta nos acoplamentos CA e CC (ver SimulationKPIs.fracao_energia_origem_solar).",
)
col_t6.metric("Energia Diesel", f"{formatar_numero(kpis.energia_gerador_kwh, 0)} kWh/ano")

# Consumo diesel ano 1 (litros): simulado hora a hora pelo parque de geradores (curva de consumo).
consumo_diesel_litros_ano1 = kpis.consumo_diesel_litros
col_t7.metric("Consumo Diesel", f"{formatar_numero(consumo_diesel_litros_ano1, 0)} L/ano")

st.divider()

# --- 5. RESULTADOS DE ECONOMIA ---
st.markdown("#### :primary[:material/mintmark:] Resultados de Economia (1º ano)")

economia_diesel_litros_ano1 = resultado_financeiro.economia_diesel_litros_ano1

col_e1, col_e2, col_e3 = st.columns(3)
col_e1.metric("Economia Diesel", f"{formatar_numero(economia_diesel_litros_ano1, 0)} L")
col_e2.metric("Economia R$", formatar_brl(resultado_financeiro.economia_diesel_ano1_rs, 0))
col_e3.metric("Economia em Sacas de Soja", f"{formatar_numero(resultado_financeiro.economia_em_sacas_ano1, 0)} sacas")

if area_total_ha > 0:
    st.markdown(f"**🌱 Economia por Hectare** (área irrigada total: {formatar_numero(area_total_ha, 0)} ha)")
    economia_rs_ha = resultado_financeiro.economia_diesel_ano1_rs / area_total_ha
    diesel_l_ha = economia_diesel_litros_ano1 / area_total_ha

    col_ha1, col_ha2 = st.columns(2)
    col_ha1.metric("Economia por Hectare/ano", f"{formatar_brl(economia_rs_ha, 0)}/ha")
    col_ha2.metric("Diesel Evitado por Hectare/ano", f"{formatar_numero(diesel_l_ha, 1)} L/ha")
else:
    st.caption(
        "ℹ️ Informe a **Área irrigada (ha)** na página **Perfil de Carga** para ver a economia "
        "por hectare — uma métrica mais intuitiva para o dimensionamento agrícola."
    )

col_capex1, col_capex2, col_capex3 = st.columns(3)
col_capex1.metric("CAPEX Total (FV+BESS)", formatar_brl(resultado_financeiro.capex.capex_total_rs, 0))
col_capex2.metric("CAPEX FV", formatar_brl(resultado_financeiro.capex.capex_fv_rs, 0))
col_capex3.metric("CAPEX BESS", formatar_brl(resultado_financeiro.capex.capex_bess_rs, 0))

st.divider()

# --- 6. FLUXO DE CAIXA ---
st.markdown("#### :primary[:material/finance:] Fluxo de Caixa")

df_fluxo = pd.DataFrame(
    [
        {
            "Ano": f.ano,
            "Economia (R$)": f.economia_diesel_rs,
            "Custos (R$)": -(f.om_rs + f.parcela_financiamento_rs),
            "Fluxo de Caixa (R$)": f.fluxo_caixa_rs,
            "Fluxo Acumulado (R$)": f.fluxo_acumulado_rs,
        }
        for f in resultado_financeiro.fluxos
    ]
)

fig_fluxo, ax_fluxo = plt.subplots(figsize=(9, 3.5))
cores = ["#e74c3c" if v < 0 else "#2ecc71" for v in df_fluxo["Fluxo Acumulado (R$)"]]
ax_fluxo.bar(df_fluxo["Ano"], df_fluxo["Fluxo Acumulado (R$)"], color=cores)
ax_fluxo.axhline(0, color="black", linewidth=0.8)
ax_fluxo.set_title("Fluxo de Caixa Acumulado")
ax_fluxo.set_xlabel("Ano")
ax_fluxo.set_ylabel("R$")
ax_fluxo.grid(axis="y", alpha=0.3)
fig_fluxo.tight_layout()

buf_fluxo = io.BytesIO()
fig_fluxo.savefig(buf_fluxo, format="png", dpi=150)
plt.close(fig_fluxo)
grafico_fluxo_caixa_png = buf_fluxo.getvalue()

st.pyplot(fig_fluxo)

with st.expander("Ver tabela completa de fluxo de caixa"):
    st.dataframe(df_fluxo.set_index("Ano"), width="stretch")

st.divider()

# --- 7. INDICADORES DE RETORNO ---
st.markdown("#### :primary[:material/finance_mode:] Indicadores de Retorno")

col_r1, col_r2, col_r3, col_r4, col_r5 = st.columns(5)
col_r1.metric("VPL", formatar_brl(resultado_financeiro.vpl_rs, 0))
col_r2.metric("TIR", f"{formatar_numero(resultado_financeiro.tir * 100, 1)} %" if resultado_financeiro.tir is not None else "N/A")
col_r3.metric("LCOE", f"{formatar_brl(resultado_financeiro.lcoe_rs_kwh, 2)}/kWh")
col_r4.metric(
    "Payback", f"{resultado_financeiro.payback_anos} ano(s)" if resultado_financeiro.payback_anos is not None else "N/A"
)
caixa_total_rs = sum(f.fluxo_caixa_rs for f in resultado_financeiro.fluxos)
col_r5.metric("Caixa Total", formatar_brl(caixa_total_rs, 0))

if resultado_financeiro.vpl_rs > 0:
    st.success("✅ Investimento economicamente viável (VPL positivo).")
else:
    st.error("❌ Investimento não é viável nas condições atuais (VPL negativo).")

st.divider()

# --- 8. EXPORTAR PDF ---
st.markdown("#### :primary[:material/download:] Exportar Relatório")

observacoes = [
    "O CAPEX do gerador diesel não é incluído no investimento: o cálculo de retorno considera "
    "como cenário-base a operação 100% a diesel, e a economia (e portanto o retorno do "
    "investimento) é calculada a partir da redução de consumo de diesel obtida com o FV+BESS.",
    "LCOE calculado de forma não descontada (soma nominal de custos / soma nominal de energia evitada).",
]

ctx = RelatorioContexto(
    cliente=cliente or "-",
    cidade=cidade or "-",
    estado=estado_relatorio or "-",
    gnf=gnf or "-",
    revisao=revisao or "-",
    grupos=grupos_info,
    consumo_anual_kwh=consumo_anual_kwh,
    potencia_total_kw=potencia_total_kw,
    kpis=kpis,
    solar_config=solar_config,
    battery_config=battery_config,
    generator_config=generator_config,
    acoplamento_bess=acoplamento_bess,
    resultado_financeiro=resultado_financeiro,
    consumo_diesel_litros_ano1=consumo_diesel_litros_ano1,
    economia_diesel_litros_ano1=economia_diesel_litros_ano1,
    area_total_ha=area_total_ha,
    grafico_perfil_anual_png=grafico_perfil_anual_png,
    grafico_perfil_hibrido_png=grafico_perfil_hibrido_png,
    grafico_fluxo_caixa_png=grafico_fluxo_caixa_png,
    observacoes=observacoes,
)

pdf_bytes = gerar_pdf_relatorio(ctx)

st.download_button(
    "📄 Baixar Relatório em PDF",
    data=pdf_bytes,
    file_name=f"relatorio_viabilidade_{(gnf or 'projeto').replace(' ', '_')}.pdf",
    mime="application/pdf",
    type="primary",
)

st.caption(
    "Relatório gerado a partir das configurações atuais das páginas Home, Perfil de Carga, "
    "Simulação Técnica e Análise Financeira. Ajuste os parâmetros nessas páginas para atualizar "
    "os valores aqui."
)
