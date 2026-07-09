"""Página Streamlit: Simulação Técnica do Sistema Híbrido (Fases 2 e 3).

Fluxo único:
    1. Selecione a localização no mapa (perfil de irradiância via API NSRDB).
    2. Configure os componentes do sistema: usina FV, BESS e gerador diesel.
    3. Rode a simulação horária (8760h) usando a carga gerada na página
       inicial ("Gerador de Perfil de Carga de Irrigação").
    4. Analise o fluxo de energia entre as fontes e os indicadores de
       desempenho (KPIs) do sistema.

Esta página consome diretamente o motor de cálculo (``engine/*``), sem
duplicar nenhuma lógica de negócio — apenas monta as configurações a
partir dos inputs do usuário e chama ``engine.simulator.simular_ano``.
"""
import folium
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from engine.dispatch.load_following import LoadFollowingDispatch
from engine.models import BatteryConfig, EconomicConfig, GeneratorConfig, SolarConfig
from engine.optimizer import otimizar_sistema_completo
from engine.simulator import simular_ano
from engine.solar.nsrdb_api import NsrdbApiError, NsrdbSolarProvider

st.set_page_config(page_title="Simulação Técnica", page_icon="🗺️", layout="wide")

st.markdown("### 🗺️ Simulação Técnica do Sistema Híbrido")
st.markdown(
    "Selecione a localização no mapa, configure os componentes do sistema (FV, BESS e "
    "gerador) e simule o fluxo de energia horário (8760h) usando a carga elétrica gerada "
    "na página inicial."
)

# --- CREDENCIAIS DA API ---


def obter_credenciais_api() -> tuple[str | None, str | None]:
    """Obtém api_key e email a partir de st.secrets, com mensagem de erro amigável."""
    try:
        api_key = st.secrets["nlr_api"]["api_key"]
        email = st.secrets["nlr_api"]["email"]
        return api_key, email
    except Exception:
        return None, None


api_key, email = obter_credenciais_api()

if not api_key:
    st.error(
        "❌ Credenciais da API NLR não configuradas. Crie o arquivo "
        "`.streamlit/secrets.toml` com as chaves `[nlr_api] api_key` e `email` "
        "(veja `.streamlit/secrets.toml.example`)."
    )
    st.stop()

# --- VERIFICA SE HÁ CARGA DISPONÍVEL ---
carga_kw = st.session_state.get("carga_kw")

if carga_kw is None:
    st.warning(
        "⚠️ Nenhum perfil de carga encontrado. Vá até a página inicial "
        "(**Gerador de Perfil de Carga de Irrigação**) e gere um perfil antes de simular."
    )
else:
    st.success(
        f"✅ Perfil de carga carregado: **{st.session_state.get('carga_descricao', '—')}** "
        f"({st.session_state.get('carga_estado', '—')}) — "
        f"consumo anual de {carga_kw.sum():,.0f} kWh, pico de {carga_kw.max():,.1f} kW."
    )

# --- ESTADO DA SESSÃO (MAPA) ---
if "mapa_lat" not in st.session_state:
    st.session_state.mapa_lat = -15.78  # Brasília, centro aproximado do Brasil
if "mapa_lon" not in st.session_state:
    st.session_state.mapa_lon = -47.93

st.divider()

# --- 1. LOCALIZAÇÃO ---
st.markdown("#### 📍 1. Localização (perfil solar)")
col_mapa, col_info_local = st.columns([2, 1])

with col_mapa:
    m = folium.Map(location=[st.session_state.mapa_lat, st.session_state.mapa_lon], zoom_start=4)
    folium.Marker(
        [st.session_state.mapa_lat, st.session_state.mapa_lon],
        tooltip="Localização selecionada",
        icon=folium.Icon(color="green", icon="bolt", prefix="fa"),
    ).add_to(m)

    mapa_evento = st_folium(m, height=350, width="100%", key="mapa_solar")

    if mapa_evento and mapa_evento.get("last_clicked"):
        st.session_state.mapa_lat = mapa_evento["last_clicked"]["lat"]
        st.session_state.mapa_lon = mapa_evento["last_clicked"]["lng"]

with col_info_local:
    st.metric("Latitude", f"{st.session_state.mapa_lat:.4f}")
    st.metric("Longitude", f"{st.session_state.mapa_lon:.4f}")
    st.caption(
        "Clique no mapa para escolher a coordenada. O perfil de irradiância será obtido "
        "da API NSRDB no momento da simulação (com cache local)."
    )

st.divider()

# --- 2. OTIMIZAÇÃO (OPCIONAL) ---
st.markdown("#### 🎯 2. Otimização de Dimensionamento (opcional)")
st.markdown(
    "Em vez de definir manualmente a potência do FV e a capacidade do BESS, você pode "
    "otimizar esses dois valores automaticamente, maximizando VPL/TIR ou minimizando o LCOE. "
    "O gerador diesel (abaixo) e o C-rate/DoD/eficiência do BESS são mantidos fixos durante a "
    "otimização — apenas a **potência do inversor FV** e a **capacidade do BESS** são ajustadas, "
    "na mesma sequência do Solver original (FV primeiro, depois BESS)."
)

col_opt1, col_opt2, col_opt3 = st.columns(3)
with col_opt1:
    metrica_otimizacao = st.selectbox(
        "Métrica a otimizar", ["VPL", "TIR", "LCOE"], key="opt_metrica",
        help="VPL e TIR são maximizados; LCOE é minimizado.",
    )
with col_opt2:
    st.caption("Parâmetros econômicos usados na otimização (mesmos valores padrão da página Análise Financeira):")
    custo_fv_otimizacao = st.number_input(
        "Custo FV (R$/kWp)", min_value=0.0, value=6500.0, step=100.0, key="opt_custo_fv"
    )
    custo_bess_otimizacao = st.number_input(
        "Custo BESS (R$/kWh)", min_value=0.0, value=2000.0, step=50.0, key="opt_custo_bess"
    )
with col_opt3:
    preco_diesel_otimizacao = st.number_input(
        "Preço Diesel (R$/litro)", min_value=0.0, value=7.0, step=0.1, key="opt_preco_diesel"
    )
    tma_otimizacao = st.number_input(
        "TMA (% a.a.)", min_value=0.0, value=5.0, step=0.5, key="opt_tma"
    ) / 100.0

otimizar = st.button(
    "🎯 Otimizar Dimensionamento (FV + BESS)", width="stretch", disabled=carga_kw is None
)

if otimizar and carga_kw is not None:
    with st.spinner("Otimizando potência FV e capacidade do BESS (pode levar alguns segundos)..."):
        try:
            solar_provider_opt = NsrdbSolarProvider(
                lat=st.session_state.mapa_lat, lon=st.session_state.mapa_lon, api_key=api_key, email=email
            )
            generator_config_opt = GeneratorConfig(
                nr_maquinas=int(st.session_state.get("ger_nr", 2)),
                nr_min_maquinas=int(st.session_state.get("ger_nr_min", 2)),
                pot_continua_kw=float(st.session_state.get("ger_continua", 315.0)),
                pot_prime_kva=float(st.session_state.get("ger_prime", 500.0)),
                fp=float(st.session_state.get("ger_fp", 0.8)),
                pot_min_pct=float(st.session_state.get("ger_pot_min", 0)) / 100.0,
                modo=st.session_state.get("ger_modo", "ON/OFF"),
            )
            economic_config_opt = EconomicConfig(
                custo_fv_rs_kwp=custo_fv_otimizacao,
                custo_bateria_rs_kwh=custo_bess_otimizacao,
                preco_diesel_rs_litro=preco_diesel_otimizacao,
                tma_am=tma_otimizacao,
            )

            resultado_otimizacao = otimizar_sistema_completo(
                carga_kw=carga_kw,
                solar_provider=solar_provider_opt,
                generator_config=generator_config_opt,
                economic_config=economic_config_opt,
                dispatch_strategy=LoadFollowingDispatch(),
                ilr=float(st.session_state.get("fv_ilr", 1.4)),
                c_rate=float(st.session_state.get("bess_c_rate", 0.5)),
                dod=float(st.session_state.get("bess_dod", 90)) / 100.0,
                eficiencia_rt=float(st.session_state.get("bess_eff", 92)) / 100.0,
                metrica=metrica_otimizacao,
            )
        except NsrdbApiError as e:
            st.error(f"❌ Erro ao consultar a API NSRDB: {e}")
            st.stop()

    # Preenche os campos manuais abaixo com o resultado ótimo.
    st.session_state["fv_pot_inv"] = round(resultado_otimizacao.solar_config_otimo.pot_inv_kw, 1)
    st.session_state["bess_capacidade"] = round(resultado_otimizacao.battery_config_otimo.capacidade_kwh, 1)

    st.success(
        f"✅ Otimização concluída ({resultado_otimizacao.etapa_fv.n_avaliacoes + resultado_otimizacao.etapa_bess.n_avaliacoes} "
        f"avaliações)! Potência FV ótima: **{resultado_otimizacao.solar_config_otimo.pot_inv_kw:,.1f} kW** | "
        f"Capacidade BESS ótima: **{resultado_otimizacao.battery_config_otimo.capacidade_kwh:,.1f} kWh** | "
        f"{metrica_otimizacao}: **{resultado_otimizacao.etapa_bess.valor_metrica:,.2f}**"
    )
    st.rerun()

st.divider()

# --- 3. CONFIGURAÇÃO DO SISTEMA ---
st.markdown("#### ⚙️ 3. Configuração do Sistema")

col_fv, col_bess, col_ger = st.columns(3)

with col_fv:
    st.markdown("**☀️ Usina Solar (FV)**")
    pot_inv_kw = st.number_input(
        "Potência do Inversor (kW)", min_value=0.0, value=800.0, step=10.0, key="fv_pot_inv"
    )
    ilr = st.number_input(
        "ILR (DC/AC)", min_value=1.0, value=1.4, step=0.05, key="fv_ilr",
        help="Índice de sobredimensionamento (Inverter Load Ratio): razão entre a potência "
        "de pico do arranjo (kWp) e a potência do inversor (kW).",
    )
    st.caption(f"Potência de pico do arranjo: **{pot_inv_kw * ilr:,.0f} kWp**")

with col_bess:
    st.markdown("**🔋 BESS (Bateria)**")
    capacidade_kwh = st.number_input(
        "Capacidade (kWh)", min_value=0.0, value=1446.0, step=50.0, key="bess_capacidade"
    )
    c_rate = st.number_input(
        "C-rate", min_value=0.05, value=0.5, step=0.05, key="bess_c_rate",
        help="Taxa de carga/descarga. Ex.: 0,5C = descarga total em 2h. "
        "Potência derivada = capacidade × C-rate.",
    )
    dod = st.slider("DoD — Profundidade de Descarga (%)", min_value=10, max_value=100, value=90, key="bess_dod") / 100.0
    eficiencia_rt = st.slider(
        "Eficiência Round-trip (%)", min_value=70, max_value=100, value=92, key="bess_eff"
    ) / 100.0
    st.caption(f"Potência derivada: **{capacidade_kwh * c_rate:,.0f} kW**")

with col_ger:
    st.markdown("**⚡ Gerador Diesel**")
    nr_maquinas = st.number_input("Nº de Geradores", min_value=0, value=2, step=1, key="ger_nr")
    nr_min_maquinas = st.number_input(
        "Nº Mínimo em Operação", min_value=0, value=2, step=1, key="ger_nr_min",
        help="Número mínimo de máquinas que devem permanecer ligadas quando o parque está em operação.",
    )
    pot_prime_kva = st.number_input("Potência Prime (kVA)", min_value=0.0, value=500.0, step=10.0, key="ger_prime")
    fp = st.slider("Fator de Potência", min_value=0.7, max_value=1.0, value=0.8, step=0.01, key="ger_fp")
    pot_continua_kw = st.number_input(
        "Potência Contínua por Máquina (kW)", min_value=0.0, value=315.0, step=5.0, key="ger_continua"
    )
    modo = st.selectbox("Modo de Operação", ["ON/OFF", "Sempre ON"], key="ger_modo")
    pot_min_pct = st.slider(
        "Piso de Carga Mínima (%)", min_value=0, max_value=100, value=0, key="ger_pot_min",
        help="Percentual mínimo de carga do parque para evitar operação com baixa carga (ruim para motores diesel).",
    ) / 100.0
    st.caption(f"Potência total do parque: **{pot_continua_kw * nr_maquinas:,.0f} kW**")

st.divider()

simular = st.button(
    "🚀 Simular Sistema Híbrido (8760h)", type="primary", width="stretch", disabled=carga_kw is None
)

# --- 3. SIMULAÇÃO E RESULTADOS ---
if simular and carga_kw is not None:
    with st.spinner("Obtendo perfil solar e simulando 8760 horas..."):
        try:
            solar_provider = NsrdbSolarProvider(
                lat=st.session_state.mapa_lat,
                lon=st.session_state.mapa_lon,
                api_key=api_key,
                email=email,
            )
            solar_config = SolarConfig(pot_inv_kw=pot_inv_kw, ilr=ilr)
            battery_config = BatteryConfig(
                capacidade_kwh=capacidade_kwh, c_rate=c_rate, dod=dod, eficiencia_rt=eficiencia_rt
            )
            generator_config = GeneratorConfig(
                nr_maquinas=nr_maquinas,
                nr_min_maquinas=nr_min_maquinas,
                pot_continua_kw=pot_continua_kw,
                pot_prime_kva=pot_prime_kva,
                fp=fp,
                pot_min_pct=pot_min_pct,
                modo=modo,
            )

            resultado = simular_ano(
                carga_kw=carga_kw,
                solar_config=solar_config,
                solar_provider=solar_provider,
                battery_config=battery_config,
                generator_config=generator_config,
                dispatch_strategy=LoadFollowingDispatch(),
            )
        except NsrdbApiError as e:
            st.error(f"❌ Erro ao consultar a API NSRDB: {e}")
            st.stop()
        except ValueError as e:
            st.error(f"❌ Erro de configuração: {e}")
            st.stop()

    st.session_state["ultima_simulacao"] = resultado
    st.session_state["ultima_solar_config"] = solar_config
    st.session_state["ultima_battery_config"] = battery_config
    st.session_state["ultima_generator_config"] = generator_config

    dataset_label = {
        "nsrdb-GOES-tmy-v4-0-0": "TMY sintético (ano meteorológico típico)",
        "nsrdb-GOES-full-disc-v4-0-0": "Ano real observado",
    }.get(solar_provider.dataset_usado, solar_provider.dataset_usado)

    st.success(
        f"✅ Simulação concluída! Dataset solar: **{dataset_label}** (ano: {solar_provider.ano_usado})"
    )

if "ultima_simulacao" in st.session_state:
    resultado = st.session_state["ultima_simulacao"]
    df = resultado.df
    kpis = resultado.kpis

    st.markdown("#### 📊 4. Resultados da Simulação")

    col_k1, col_k2, col_k3, col_k4, col_k5 = st.columns(5)
    col_k1.metric("Fração Solar", f"{kpis.fracao_solar * 100:.1f} %")
    col_k2.metric("Energia Solar", f"{kpis.energia_solar_utilizada_kwh:,.0f} kWh")
    col_k3.metric("Energia Bateria", f"{kpis.energia_bateria_descarregada_kwh:,.0f} kWh")
    col_k4.metric("Energia Gerador", f"{kpis.energia_gerador_kwh:,.0f} kWh")
    col_k5.metric("LOLP (déficit)", f"{kpis.lolp * 100:.2f} %", help="Loss of Load Probability: fração de horas do ano com energia não suprida.")

    if kpis.energia_nao_suprida_kwh > 1e-3:
        st.warning(
            f"⚠️ Sistema subdimensionado: {kpis.energia_nao_suprida_kwh:,.1f} kWh não supridos "
            f"em {kpis.horas_com_deficit} horas do ano."
        )
    if kpis.energia_curtailed_kwh > 1e-3:
        st.info(f"ℹ️ Energia excedente (curtailment/dump): {kpis.energia_curtailed_kwh:,.1f} kWh/ano.")

    dates = pd.date_range(start="2023-01-01", periods=8760, freq="h")

    st.markdown("**Fluxo de Energia (semana de exemplo)**")
    semana_inicio = st.slider("Selecione a semana do ano", 1, 52, 3, key="semana_fluxo")
    inicio_h = (semana_inicio - 1) * 168
    fim_h = inicio_h + 168

    df_fluxo = pd.DataFrame(
        {
            "Carga (kW)": df["carga_kw"].to_numpy()[inicio_h:fim_h],
            "Solar Utilizado (kW)": df["solar_utilizado_kw"].to_numpy()[inicio_h:fim_h],
            "Bateria (kW)": df["bateria_descarga_kw"].to_numpy()[inicio_h:fim_h],
            "Gerador (kW)": df["gerador_kw"].to_numpy()[inicio_h:fim_h],
        },
        index=dates[inicio_h:fim_h],
    )
    st.area_chart(
        df_fluxo[["Solar Utilizado (kW)", "Bateria (kW)", "Gerador (kW)"]],
        width="stretch",
        color=["#f39c12", "#3498db", "#7f8c8d"],
    )
    st.line_chart(df_fluxo[["Carga (kW)"]], width="stretch", color="#e74c3c")

    st.markdown("**Estado de Carga da Bateria (SOC) — Ano Completo**")
    df_soc = pd.DataFrame({"SOC (kWh)": df["bateria_soc_kwh"].to_numpy()}, index=dates)
    st.area_chart(df_soc, width="stretch", color="#3498db")

    with st.expander("Ver dados horários completos (primeiras 48h)"):
        st.dataframe(df.head(48), width="stretch")

    csv = df.to_csv().encode("utf-8")
    st.download_button(
        "📥 Baixar resultado completo (CSV, 8760h)",
        data=csv,
        file_name="simulacao_tecnica_8760h.csv",
        mime="text/csv",
    )

    st.divider()
    st.info(
        "💾 Esta simulação foi salva automaticamente e já pode ser utilizada na página "
        "**Análise Financeira** para calcular VPL, TIR, LCOE e Payback do investimento.",
        icon="➡️",
    )
elif not simular:
    st.info("Configure o sistema acima e clique em **Simular Sistema Híbrido** para ver os resultados.")

st.divider()
st.caption(
    "Fonte solar: NSRDB (National Solar Radiation Database), via API da "
    "[NLR - National Laboratory of the Rockies](https://developer.nlr.gov/docs/solar/nsrdb/) "
    "(anteriormente NREL). Estratégia de despacho: load-following."
)
