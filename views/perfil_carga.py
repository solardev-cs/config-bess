import streamlit as st
import pandas as pd
import numpy as np

from engine.formatting import formatar_numero
from engine.load_profile import gerar_perfil_carga
from views._dados_hidricos import carregar_dados
from views._nav import stepper
from views._persist import indice_persistido, persistir, valor_persistido

stepper("views/perfil_carga.py")

# Carrega os dados de referência hídrica (a tabela completa fica disponível
# para consulta na página Configurações).
df_ref = carregar_dados()

# --- INTERFACE STREAMLIT ---

# --- LOCALIZAÇÃO E OPERAÇÃO (INPUTS GLOBAIS) ---
st.markdown("#### :primary[:material/track_changes:] Dados de Irrigação")

col_loc1, col_loc2 = st.columns(2)
with col_loc1:
    # Filtra UFs disponíveis no CSV
    lista_ufs = sorted(df_ref['UF'].unique())
    # Prioriza a última seleção feita nesta própria página; só cai no estado
    # cadastrado na Home se o usuário ainda não tiver escolhido nada aqui.
    estado_default = valor_persistido("carga_estado_input", None) or valor_persistido("home_estado", None)
    index_estado = lista_ufs.index(estado_default) if estado_default in lista_ufs else 0
    estado = persistir("carga_estado_input", st.selectbox("Estado", lista_ufs, index=index_estado, key="carga_estado_input"))

col_op1, col_op2 = st.columns(2)
with col_op1:
    t = persistir("hora_inicio_irrigacao", st.time_input(
        "Horário de Início da Irrigação Diária",
        value=valor_persistido("hora_inicio_irrigacao", "08:00"),
        step=3600, key="hora_inicio_irrigacao",
    ))
    t = t.strftime("%H")
    tmp = int(t)
with col_op2:
    st.write("")
    st.caption("*Ajuste o horário de início da irrigação e o número mínimo de horas de operação por dia de forma a aproveitar ao máximo a janela de irradiação solar e suprir a necessidade hídrica anual.*", text_alignment="justify")

# Teto físico de horas de operação por dia: a irrigação nunca cruza a virada
# do dia — distribuir_carga() (engine/load_profile.py) só agenda horas dentro
# do mesmo dia civil, então horas além de 24 - hora_inicio "sumiriam"
# silenciosamente sem entrar no cálculo de déficit — nem passa de 21h (tempo
# de deslocamento/reposicionamento do pivô).
teto_horas_dia = min(21, max(1, 24 - tmp))
hmin_min = 1
hmin_default = max(hmin_min, min(valor_persistido("horas_min_operacao", 10), teto_horas_dia))
ajuda_hmin = (
    "Mínimo de horas que cada dia de irrigação opera. O app concentra a "
    "necessidade hídrica mensal em menos dias — cada um rodando ao menos esse "
    "número de horas — em vez de espalhar poucas horas por todos os dias do mês. "
    f"Limitado a {teto_horas_dia}h pelo horário de início escolhido."
)
with col_loc2:
    if hmin_min < teto_horas_dia:
        horas_min_operacao = persistir("horas_min_operacao", st.slider(
            "Horas Mínimas de Operação por Dia",
            min_value=hmin_min,
            max_value=teto_horas_dia,
            value=hmin_default,
            key="horas_min_operacao",
            help=ajuda_hmin,
        ))
    else:
        # st.slider exige min_value < max_value estritamente. Com um início
        # tarde o bastante (ex.: 23h -> só resta 1h antes da virada do dia),
        # min e max colapsam no mesmo valor e o slider não tem intervalo para
        # desenhar — usamos number_input (que aceita min == max) em vez de crashar.
        horas_min_operacao = persistir("horas_min_operacao", st.number_input(
            "Horas Mínimas de Operação por Dia",
            min_value=hmin_min,
            max_value=teto_horas_dia,
            value=hmin_default,
            step=1,
            key="horas_min_operacao",
            help=ajuda_hmin,
        ))

col_al1, col_al2 = st.columns(2)
with col_al1:
    st.write("")
    alternancia = persistir("alternancia", st.checkbox(
        "Alternar Cargas", value=valor_persistido("alternancia", False), key="alternancia",
        help="Se marcado, o Grupo A opera em dias ímpares e o Grupo B em dias pares.",
    ))

inicio_operacao = tmp

st.divider()

# --- SELEÇÃO DE CULTURAS (AGORA COM SUCESSÃO) ---
st.markdown("#### :primary[:material/psychiatry:] Grupos de Carga")

# Obtém as culturas disponíveis para aquele estado
culturas_do_estado = sorted(df_ref[df_ref['UF'] == estado]['Cultura'].unique())

col1, col2 = st.columns(2)

with col1:
    st.markdown("##### Grupo de Carga A")
    # Sub-colunas para selecionar cultura 1 e 2
    c1_a, c1_b = st.columns(2)
    with c1_a:
        cultura_a1 = persistir("cA1", st.selectbox(
            "Cultura 1 (Principal)", culturas_do_estado,
            index=indice_persistido("cA1", culturas_do_estado), key="cA1",
        ))
    with c1_b:
        # Adiciona opção "Nenhuma"
        opcoes_c2 = ["Nenhuma"] + list(culturas_do_estado)
        cultura_a2 = persistir("cA2", st.selectbox(
            "Cultura 2 (Sucessão)", opcoes_c2,
            index=indice_persistido("cA2", opcoes_c2), key="cA2",
        ))

    potencia_a = persistir("pA", st.number_input("Potência (kW)", min_value=0.0, value=valor_persistido("pA", 0.0), step=1.0, key="pA"))
    lamina_a = persistir("lA", st.number_input("Lâmina de projeto (mm/21h)", min_value=0.0, value=valor_persistido("lA", 9.0), step=0.5, key="lA", help="Quanto o pivot aplica se rodar 21h direto."))
    area_a = persistir("aA", st.number_input("Área irrigada (ha)", min_value=0.0, value=valor_persistido("aA", 0.0), step=10.0, key="aA", help="Usada apenas para métricas de economia por hectare no Relatório de Viabilidade."))

with col2:
    if alternancia:
        st.markdown("##### Grupo de Carga B")
        c2_a, c2_b = st.columns(2)
        with c2_a:
            cultura_b1 = persistir("cB1", st.selectbox(
                "Cultura 1 (Principal)", culturas_do_estado,
                index=indice_persistido("cB1", culturas_do_estado), key="cB1",
            ))
        with c2_b:
            opcoes_c2b = ["Nenhuma"] + list(culturas_do_estado)
            cultura_b2 = persistir("cB2", st.selectbox(
                "Cultura 2 (Sucessão)", opcoes_c2b,
                index=indice_persistido("cB2", opcoes_c2b), key="cB2",
            ))

        potencia_b = persistir("pB", st.number_input("Potência (kW)", min_value=0.0, value=valor_persistido("pB", 0.0), step=1.0, key="pB"))
        lamina_b = persistir("lB", st.number_input("Lâmina de projeto (mm/21h)", min_value=0.0, value=valor_persistido("lB", 9.0), step=0.5, key="lB"))
        area_b = persistir("aB", st.number_input("Área irrigada (ha)", min_value=0.0, value=valor_persistido("aB", 0.0), step=10.0, key="aB", help="Usada apenas para métricas de economia por hectare no Relatório de Viabilidade."))

        if potencia_b <= 0:
            st.info("ℹ️ Defina a **Potência (kW)** do Grupo B para ativá-lo — sem ela, este grupo é ignorado no perfil de carga.")
    else:
        cultura_b1 = None
        cultura_b2 = None
        potencia_b = 0
        lamina_b = 0
        area_b = 0

# --- PROCESSAMENTO (via engine/load_profile.py) ---

resultado = gerar_perfil_carga(
    df_ref=df_ref,
    estado=estado,
    grupo_a_potencia_kw=potencia_a,
    grupo_a_lamina_mm_21h=lamina_a,
    grupo_a_cultura_1=cultura_a1,
    grupo_a_cultura_2=cultura_a2,
    horas_min_por_dia=horas_min_operacao,
    hora_inicio=inicio_operacao,
    alternancia=alternancia,
    grupo_b_potencia_kw=potencia_b,
    grupo_b_lamina_mm_21h=lamina_b,
    grupo_b_cultura_1=cultura_b1,
    grupo_b_cultura_2=cultura_b2,
)

df = resultado.df
warnings = [f"⚠️ **{aviso}**" for aviso in resultado.avisos]

# Persiste o perfil de carga gerado para ser consumido pela página de
# Simulação Técnica (engine/simulator.py), evitando que o usuário precise
# refazer esse cadastro em outra tela.
st.session_state["carga_kw"] = df["Total_Load_kW"].to_numpy()
st.session_state["carga_estado"] = estado
st.session_state["carga_descricao"] = (
    f"{cultura_a1}" + (f" + {cultura_b1}" if alternancia and potencia_b > 0 else "")
)

# Estrutura detalhada por grupo de carga, usada pela página de Relatório de
# Viabilidade (Lista de Cargas + métricas de economia por hectare).
grupos_carga = [
    {
        "nome": "Grupo A",
        "cultura_principal": cultura_a1,
        "cultura_sucessao": cultura_a2 if cultura_a2 != "Nenhuma" else None,
        "potencia_kw": potencia_a,
        "lamina_mm_21h": lamina_a,
        "area_ha": area_a,
    }
]
if alternancia and potencia_b > 0:
    grupos_carga.append(
        {
            "nome": "Grupo B",
            "cultura_principal": cultura_b1,
            "cultura_sucessao": cultura_b2 if cultura_b2 != "Nenhuma" else None,
            "potencia_kw": potencia_b,
            "lamina_mm_21h": lamina_b,
            "area_ha": area_b,
        }
    )
st.session_state["carga_grupos"] = grupos_carga

dados_tabela_a = [
    {
        "Mês": b.mes,
        "Precisa (mm)": f"{b.precisa_mm:.1f}",
        "Entrega (mm)": f"{b.entrega_mm:.1f}",
        "Déficit (mm)": f"{b.deficit_mm:.1f}",
        "Dias de operação": b.dias_operacao,
    }
    for b in resultado.balanco_a
]
dados_tabela_b = [
    {
        "Mês": b.mes,
        "Precisa (mm)": f"{b.precisa_mm:.1f}",
        "Entrega (mm)": f"{b.entrega_mm:.1f}",
        "Déficit (mm)": f"{b.deficit_mm:.1f}",
        "Dias de operação": b.dias_operacao,
    }
    for b in resultado.balanco_b
]

# --- RESULTADOS VISUAIS ---

st.divider()
st.markdown("#### Resultado do Perfil")
st.write("")

def style_deficit(col):
    is_deficit = float(col.get('Déficit (mm)', 0).replace(',','.')) > 0
    return ['color: red' if is_deficit else '' for _ in col]

def gerar_df_transposto(dados):
    df_t = pd.DataFrame(dados).set_index("Mês").T
    return df_t

tab_col1, tab_col2 = st.columns(2)

with tab_col1:
    st.markdown(f"**Balanço Hídrico A ({cultura_a1} + {cultura_a2})**")
    df_a_final = gerar_df_transposto(dados_tabela_a)
    st.dataframe(df_a_final.style.apply(style_deficit, axis=0), width="content")

with tab_col2:
    if potencia_b > 0:
        st.markdown(f"**Balanço Hídrico B ({cultura_b1} + {cultura_b2})**")
        df_b_final = gerar_df_transposto(dados_tabela_b)
        st.dataframe(df_b_final.style.apply(style_deficit, axis=0), width="content")

if warnings:
    st.warning(f"**Atenção**: Configuração atual não atende à necessidade hídrica completa em {len(warnings)} casos.")
    with st.expander("Ver detalhes dos déficits"):
        for w in warnings: st.write(w)
else:
    st.success("**Configuração Válida**: Necessidade hídrica atendida.")

st.write("")
st.area_chart(df['Total_Load_kW'], width="stretch", color="#2ecc71")

with st.expander("Ver perfil do dia 1"):
    st.dataframe(df.head(24),)

# --- MÉTRICAS ---
val_consumo = df['Total_Load_kW'].sum()
val_pico = df['Total_Load_kW'].max()
# Horas em que o sistema está irrigando no ano (qualquer grupo ativo).
val_horas_operacao = int((df['Total_Load_kW'] > 0).sum())

# Se o pico for maior que 0, calcula o fator. Se não, é 0.
if val_pico > 0:
    val_fator = (df['Total_Load_kW'].mean() / val_pico) * 100
else:
    val_fator = 0.0

# Formatação Brasileira
cons_formatado = formatar_numero(val_consumo, 2)
pot_formatado = formatar_numero(val_pico, 2)
fator_formatado = formatar_numero(val_fator, 2)
horas_formatado = formatar_numero(val_horas_operacao, 0)

col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
col_m1.metric("Consumo Anual", f"{cons_formatado} kWh")
col_m2.metric("Potência Máxima", f"{pot_formatado} kW")
col_m3.metric("Fator de Carga", f"{fator_formatado} %")
col_m4.metric("Horas de Operação (ano)", f"{horas_formatado} h")

# --- DOWNLOAD ---
@st.cache_data
def convert_df(df):
    return df['Total_Load_kW'].to_csv(index=False, header=False, decimal=",").encode('utf-8')

csv = convert_df(df)

with col_m5:
    st.write("")
    st.write("")
    st.download_button(
        label="📥 Baixar Perfil em CSV",
        data=csv,
        file_name=f'perfil_{estado}_{cultura_a1}.csv',
        mime='text/csv',
    )

st.divider()