"""Página Streamlit: Home — Identificação do Projeto e Localização.

Primeira etapa do fluxo: dados de identificação do cliente/projeto (usados
no cabeçalho do Relatório de Viabilidade) e a localização no mapa (usada
para obter o perfil de irradiância solar via API NSRDB na Simulação
Técnica). Fica em ``session_state`` para as demais páginas consumirem.
"""
import folium
import streamlit as st
from streamlit_folium import st_folium

from views._dados_hidricos import carregar_dados
from views._nav import stepper
from views._persist import indice_persistido, persistir, valor_persistido

stepper("views/home.py")

# --- IDENTIFICAÇÃO DO PROJETO ---
st.markdown("#### :primary[:material/assignment:] Identificação do Projeto")

# Mesma tabela de referência hídrica usada em Perfil de Carga/Configurações —
# um único selectbox de UFs válidas em todo o app, em vez de um campo de
# texto livre aqui que podia divergir da UF usada nos cálculos.
df_ref = carregar_dados()
lista_ufs = sorted(df_ref["UF"].unique())

col_h1, col_h2, col_h3, col_h4, col_h5 = st.columns(5)
with col_h1:
    persistir("home_cliente", st.text_input("Cliente", value=valor_persistido("home_cliente", ""), key="home_cliente"))
with col_h2:
    persistir("home_cidade", st.text_input("Cidade", value=valor_persistido("home_cidade", ""), key="home_cidade"))
with col_h3:
    persistir("home_estado", st.selectbox(
        "Estado", lista_ufs, index=indice_persistido("home_estado", lista_ufs), key="home_estado",
    ))
with col_h4:
    persistir("home_gnf", st.text_input("GNF", value=valor_persistido("home_gnf", ""), key="home_gnf"))
with col_h5:
    persistir("home_revisao", st.text_input("Revisão", value=valor_persistido("home_revisao", "Rev00"), key="home_revisao"))

st.divider()

# --- LOCALIZAÇÃO (MAPA) ---
st.markdown("#### :primary[:material/location_on:] Localização")

# Sem localização default: só grava mapa_lat/mapa_lon quando o usuário
# efetivamente clica no mapa. Antes, a coordenada nascia com o centro do
# Brasil já preenchido, e o stepper (views/_nav.py) usa a presença dessa
# chave como "etapa concluída" — ou seja, a Home aparecia com ✓ mesmo que
# ninguém tivesse escolhido uma localização real, arriscando simular contra
# a coordenada errada sem o usuário perceber.
LAT_CENTRO_BRASIL, LON_CENTRO_BRASIL = -15.78, -47.93
localizacao_definida = "mapa_lat" in st.session_state

col_mapa, col_info_local = st.columns([2, 1])

with col_mapa:
    lat_exibicao = st.session_state.get("mapa_lat", LAT_CENTRO_BRASIL)
    lon_exibicao = st.session_state.get("mapa_lon", LON_CENTRO_BRASIL)

    m = folium.Map(location=[lat_exibicao, lon_exibicao], zoom_start=10 if localizacao_definida else 4)
    if localizacao_definida:
        folium.Marker(
            [lat_exibicao, lon_exibicao],
            tooltip="Localização selecionada",
            icon=folium.Icon(color="green", icon="bolt", prefix="fa"),
        ).add_to(m)

    mapa_evento = st_folium(m, height=400, width="100%", key="mapa_solar_home")

    if mapa_evento and mapa_evento.get("last_clicked"):
        st.session_state.mapa_lat = mapa_evento["last_clicked"]["lat"]
        st.session_state.mapa_lon = mapa_evento["last_clicked"]["lng"]
        localizacao_definida = True

with col_info_local:
    if localizacao_definida:
        st.metric("Latitude", f"{st.session_state.mapa_lat:.4f}")
        st.metric("Longitude", f"{st.session_state.mapa_lon:.4f}")
    else:
        st.info("📍 Nenhuma localização escolhida ainda.")
    st.caption(
        "Clique no mapa para escolher a coordenada."
        "O perfil de irradiação anual será obtido do NSRDB."
    )

st.divider()