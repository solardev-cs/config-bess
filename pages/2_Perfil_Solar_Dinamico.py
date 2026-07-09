"""Página Streamlit: Perfil Solar Dinâmico (Fase 2 do roadmap).

Permite ao usuário clicar em um mapa do Brasil para escolher uma
coordenada (lat/lon) e obter, em tempo real, o perfil horário de
irradiância solar (8760h) via API NSRDB da NLR (National Laboratory of
the Rockies, ex-NREL).

Esta página é a demonstração da Fase 2: substitui os 3 estados fixos
(RS/MT/BA, extraídos e "congelados" da planilha original) por uma fonte
dinâmica, cobrindo qualquer ponto do Brasil com dados reais.
"""
import folium
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from engine.solar.nsrdb_api import NsrdbApiError, NsrdbSolarProvider

st.set_page_config(page_title="Perfil Solar Dinâmico", page_icon="🗺️", layout="wide")

st.markdown("### 🗺️ Perfil Solar Dinâmico (via API NSRDB)")
st.markdown(
    "Clique em qualquer ponto do mapa para obter o perfil horário de irradiância solar "
    "(8760h) daquela coordenada, direto da base de dados NSRDB (National Solar Radiation "
    "Database), mantida pela **NLR** (National Laboratory of the Rockies, antiga NREL)."
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

# --- ESTADO DA SESSÃO ---
if "mapa_lat" not in st.session_state:
    st.session_state.mapa_lat = -15.78  # Brasília, centro aproximado do Brasil
if "mapa_lon" not in st.session_state:
    st.session_state.mapa_lon = -47.93

col_mapa, col_resultado = st.columns([1, 1])

with col_mapa:
    st.markdown("#### 📍 Selecione a localização")

    m = folium.Map(location=[st.session_state.mapa_lat, st.session_state.mapa_lon], zoom_start=4)
    folium.Marker(
        [st.session_state.mapa_lat, st.session_state.mapa_lon],
        tooltip="Localização selecionada",
        icon=folium.Icon(color="green", icon="bolt", prefix="fa"),
    ).add_to(m)

    mapa_evento = st_folium(m, height=450, width="100%", key="mapa_solar")

    if mapa_evento and mapa_evento.get("last_clicked"):
        st.session_state.mapa_lat = mapa_evento["last_clicked"]["lat"]
        st.session_state.mapa_lon = mapa_evento["last_clicked"]["lng"]

    st.caption(
        f"Latitude: `{st.session_state.mapa_lat:.4f}` | Longitude: `{st.session_state.mapa_lon:.4f}`"
    )

    buscar = st.button("☀️ Buscar Perfil Solar", type="primary", width="stretch")

with col_resultado:
    st.markdown("#### 📊 Resultado")

    if buscar:
        with st.spinner("Consultando API NSRDB..."):
            try:
                provider = NsrdbSolarProvider(
                    lat=st.session_state.mapa_lat,
                    lon=st.session_state.mapa_lon,
                    api_key=api_key,
                    email=email,
                )
                perfil = provider.get_normalized_profile(use_cache=True)
            except NsrdbApiError as e:
                st.error(f"❌ Erro ao consultar a API NSRDB: {e}")
                st.stop()

        dataset_label = {
            "nsrdb-GOES-tmy-v4-0-0": "TMY sintético (ano meteorológico típico)",
            "nsrdb-GOES-full-disc-v4-0-0": "Ano real observado",
        }.get(provider.dataset_usado, provider.dataset_usado)

        st.success(
            f"✅ Perfil obtido com sucesso!  \n"
            f"**Dataset:** {dataset_label}  \n"
            f"**Ano:** {provider.ano_usado}"
        )

        dates = pd.date_range(start="2023-01-01", periods=8760, freq="h")
        df_perfil = pd.DataFrame({"Fração de Irradiância": perfil}, index=dates)

        st.area_chart(df_perfil, width="stretch", color="#f39c12")

        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Pico de Irradiância (normalizado)", f"{perfil.max():.2f}")
        col_m2.metric("Média Anual (normalizado)", f"{perfil.mean():.3f}")
        col_m3.metric("Horas com Sol (>0)", f"{int((perfil > 0).sum())} h")

        with st.expander("Ver dados horários (primeiras 48h)"):
            st.dataframe(df_perfil.head(48), width="stretch")

        csv = df_perfil.to_csv().encode("utf-8")
        st.download_button(
            "📥 Baixar perfil normalizado (CSV)",
            data=csv,
            file_name=f"perfil_solar_{st.session_state.mapa_lat:.2f}_{st.session_state.mapa_lon:.2f}.csv",
            mime="text/csv",
        )
    else:
        st.info("Clique no mapa e depois em **Buscar Perfil Solar** para ver os resultados.")

st.divider()
st.caption(
    "Fonte: NSRDB (National Solar Radiation Database), via API da "
    "[NLR - National Laboratory of the Rockies](https://developer.nlr.gov/docs/solar/nsrdb/) "
    "(anteriormente NREL). Cobertura pode variar por região: regiões Norte/Centro-Oeste do "
    "Brasil geralmente têm TMY sintético disponível; regiões Sul/Sudeste podem retornar "
    "apenas dados de um ano real específico (fallback automático)."
)
