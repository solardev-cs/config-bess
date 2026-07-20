"""Página Streamlit: Configurações Gerais do App.

Parâmetros econômicos e de sistema que raramente mudam de uma simulação
para outra (custos de referência, TMA, preço do diesel etc.) — em vez de
serem redigitados em cada página que os usa (Simulação Técnica, na
Otimização, e Análise Financeira), ficam centralizados aqui em
``st.session_state`` (chaves ``cfg_*``) e são lidos, não reeditados, pelas
demais páginas.
"""
import pandas as pd
import streamlit as st

from views._dados_hidricos import carregar_dados
from views._persist import persistir, valor_persistido

#st.markdown("### :primary[:material/settings:] Configurações Gerais")
#st.markdown(
#    "Parâmetros de referência usados em várias páginas do app. Ajuste-os aqui quando "
#    "os custos de mercado ou premissas financeiras mudarem — não é necessário redigitá-los "
#    "a cada simulação."
#)

#st.divider()

st.markdown("#### :primary[:material/local_atm:] Custos de Referência")
col_c1, col_c2, col_c3 = st.columns(3)
with col_c1:
    persistir("cfg_custo_fv", st.number_input(
        "Custo FV (R$/kWp)", min_value=0.0, value=valor_persistido("cfg_custo_fv", 6500.0), step=100.0, key="cfg_custo_fv"
    ))
with col_c2:
    persistir("cfg_custo_bess", st.number_input(
        "Custo BESS (R$/kWh)", min_value=0.0, value=valor_persistido("cfg_custo_bess", 2000.0), step=50.0, key="cfg_custo_bess",
        help="Custo total do BESS por kWh de capacidade (já inclui o PCS/inversor da bateria, "
        "conforme prática de mercado para sistemas de curta duração).",
    ))
with col_c3:
    persistir("cfg_preco_diesel", st.number_input(
        "Preço do Diesel (R$/litro)", min_value=0.0, value=valor_persistido("cfg_preco_diesel", 7.0), step=0.1, key="cfg_preco_diesel"
    ))

st.divider()

st.markdown("#### :primary[:material/candlestick_chart:] Premissas Financeiras")
col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    persistir("cfg_tma", st.number_input(
        "TMA (% a.a.)", min_value=0.0, value=valor_persistido("cfg_tma", 5.0), step=0.5, key="cfg_tma",
        help="Taxa Mínima de Atratividade, usada para descontar o fluxo de caixa no cálculo do VPL.",
    ))
with col_f2:
    persistir("cfg_horizonte_anos", st.number_input(
        "Horizonte (anos)", min_value=1, value=valor_persistido("cfg_horizonte_anos", 25), step=1, key="cfg_horizonte_anos"
    ))
with col_f3:
    persistir("cfg_valor_saca", st.number_input(
        "Valor da Saca de Soja (R$, referência)", min_value=0.0, value=valor_persistido("cfg_valor_saca", 120.0), step=5.0, key="cfg_valor_saca",
        help="Usado apenas para a métrica ilustrativa de economia em sacas de soja.",
    ))

st.divider()

st.markdown("#### :primary[:material/oil_barrel:] Catálogo de Geradores")

_CATALOGO_COLUNAS = ["Modelo", "Potência Nominal (kVA)", "Consumo (L/h)", "FP", "Potência Mínima (% da Prime em kW)"]
_CATALOGO_DEFAULT = [
    {
        "Modelo": "BRG Slim Infinity 550",
        "Potência Nominal (kVA)": 550.0,
        "Consumo (L/h)": 77.0,
        "FP": 0.8,
        "Potência Mínima (% da Prime em kW)": 0.0,
    }
]

df_catalogo_gerador = pd.DataFrame(valor_persistido("cfg_geradores_catalogo", _CATALOGO_DEFAULT))
df_catalogo_editado = st.data_editor(
    df_catalogo_gerador,
    num_rows="dynamic",
    width="stretch",
    hide_index=True,
    key="cfg_geradores_catalogo_editor",
    column_config={
        "Modelo": st.column_config.TextColumn("Modelo", required=True),
        "Potência Nominal (kVA)": st.column_config.NumberColumn(
            "Potência Nominal (kVA)", min_value=0.0, step=10.0, required=True,
            help="Potência nominal (standby) de catálogo do fabricante.",
        ),
        "Consumo (L/h)": st.column_config.NumberColumn(
            "Consumo (L/h)", min_value=0.0, step=1.0, required=True,
            help="Consumo de combustível a plena carga contínua, de catálogo do fabricante.",
        ),
        "FP": st.column_config.NumberColumn(
            "FP", min_value=0.01, max_value=1.0, step=0.01, required=True,
            help="Fator de potência do gerador.",
        ),
        "Potência Mínima (% da Prime em kW)": st.column_config.NumberColumn(
            "Potência Mínima (% da Prime em kW)", min_value=0.0, max_value=100.0, step=5.0, required=True,
            help="Piso de carga mínima recomendado pelo fabricante (% da potência prime) — "
            "evita operação prolongada em baixa carga.",
        ),
    },
)
persistir("cfg_geradores_catalogo", df_catalogo_editado.to_dict("records"))

st.divider()

st.markdown("#### :primary[:material/sunny:] Catálogo de Inversores")

_CATALOGO_INVERSOR_DEFAULT = [
    {"Modelo": "SIW500G-T100-W0", "Potência Nominal (kW)": 100.0},
]

df_catalogo_inversor = pd.DataFrame(valor_persistido("cfg_inversores_catalogo", _CATALOGO_INVERSOR_DEFAULT))
df_catalogo_inversor_editado = st.data_editor(
    df_catalogo_inversor,
    num_rows="dynamic",
    width="stretch",
    hide_index=True,
    key="cfg_inversores_catalogo_editor",
    column_config={
        "Modelo": st.column_config.TextColumn("Modelo", required=True),
        "Potência Nominal (kW)": st.column_config.NumberColumn(
            "Potência Nominal (kW)", min_value=0.0, step=10.0, required=True,
            help="Potência nominal (ativa, CA) de uma unidade do inversor, de catálogo do fabricante.",
        ),
    },
)
persistir("cfg_inversores_catalogo", df_catalogo_inversor_editado.to_dict("records"))

st.divider()

st.markdown("#### :primary[:material/battery_5_bar:] Catálogo de BESS")

_CATALOGO_BESS_DEFAULT = [
    {"Modelo": "BSCW400H", "Capacidade Nominal (kWh)": 241.0, "Potência Nominal (kW)": 125.0, "Eficiência (%)": 90.0},
]

df_catalogo_bess = pd.DataFrame(valor_persistido("cfg_bess_catalogo", _CATALOGO_BESS_DEFAULT))
df_catalogo_bess_editado = st.data_editor(
    df_catalogo_bess,
    num_rows="dynamic",
    width="stretch",
    hide_index=True,
    key="cfg_bess_catalogo_editor",
    column_config={
        "Modelo": st.column_config.TextColumn("Modelo", required=True),
        "Capacidade Nominal (kWh)": st.column_config.NumberColumn(
            "Capacidade Nominal (kWh)", min_value=0.0, step=50.0, required=True,
            help="Capacidade nominal de energia de uma unidade do BESS, de catálogo do fabricante.",
        ),
        "Potência Nominal (kW)": st.column_config.NumberColumn(
            "Potência Nominal (kW)", min_value=0.0, step=10.0, required=True,
            help="Potência nominal de carga/descarga de uma unidade do BESS, de catálogo do fabricante.",
        ),
        "Eficiência (%)": st.column_config.NumberColumn(
            "Eficiência (%)", min_value=0.0, max_value=100.0, step=1.0, required=True,
            help="Eficiência round-trip do BESS, de catálogo do fabricante.",
        ),
    },
)
persistir("cfg_bess_catalogo", df_catalogo_bess_editado.to_dict("records"))

st.divider()

st.markdown("#### :primary[:material/trending_down:] Degradação dos Equipamentos")
col_d1, col_d2 = st.columns(2)
with col_d1:
    persistir("cfg_degradacao_fv", st.number_input(
        "Degradação FV (% a.a.)", min_value=0.0, value=valor_persistido("cfg_degradacao_fv", 0.6), step=0.1, key="cfg_degradacao_fv"
    ))
with col_d2:
    persistir("cfg_degradacao_bess_soh", st.number_input(
        "Degradação BESS / SoH (% a.a.)", min_value=0.0, value=valor_persistido("cfg_degradacao_bess_soh", 2.0), step=0.1, key="cfg_degradacao_bess_soh",
        help="State of Health: perda de capacidade útil da bateria por ano, aplicada em "
        "engine/financial.py sobre a parcela de energia evitada atribuída à bateria.",
    ))

st.divider()

st.markdown("#### :primary[:material/water_lux:] Tabela de Referência Hídrica")
st.markdown(
    "Valores padrão de necessidade hídrica líquida em mm/mês por cultura/região, usados "
    "pela página **Perfil de Carga** para calcular o perfil de irrigação de 8760h."
)
df_ref = carregar_dados()
st.dataframe(df_ref, width="stretch", hide_index=True)
st.caption(
    "Fontes de dados: Embrapa (culturas), CONAB (calendário de safras), INMET (dados "
    "meteorológicos), ANA (recursos hídricos), ESALQ/USP, UFV, UFRGS, UFLA."
)

st.divider()