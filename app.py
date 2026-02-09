import streamlit as st
import pandas as pd
import numpy as np
import math
import os

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Perfil de Carga", page_icon="🗲", layout="wide")

# --- CONFIGURAÇÃO DO ARQUIVO DE DADOS ---
DATA_FOLDER = "data"
DATA_FILE = "ref_hidrica.csv"
FILE_PATH = os.path.join(DATA_FOLDER, DATA_FILE)

# --- FUNÇÕES DE DADOS ---

def carregar_dados():
    """Carrega o CSV tratando erros de codificação (acentos)."""
    if not os.path.exists(FILE_PATH):
        st.error(f"❌ Erro: O arquivo de dados não foi encontrado em '{FILE_PATH}'.")
        st.warning("Por favor, insira o arquivo 'ref_hidrica.csv' na pasta 'data' para continuar.")
        st.stop()
    
    try:
        # Tenta ler em UTF-8 (padrão moderno)
        return pd.read_csv(FILE_PATH, skipinitialspace=True, encoding='utf-8')
    except UnicodeDecodeError:
        try:
            # Se falhar, tenta Latin-1 (comum em arquivos de Excel/Windows BR)
            return pd.read_csv(FILE_PATH, skipinitialspace=True, encoding='latin1')
        except Exception as e:
            st.error(f"Erro ao ler o arquivo CSV: {e}")
            st.stop()

def salvar_dados(df_novo):
    """Salva o DataFrame editado de volta no CSV."""
    try:
        df_novo.to_csv(FILE_PATH, index=False, encoding='latin1')
        st.toast("Banco de dados atualizado com sucesso!", icon="💾")
    except Exception as e:
        st.error(f"Erro ao salvar arquivo: {e}")

def obter_mm_mensal(df, estado, cultura):
    """Retorna lista de 12 meses de mm para a cultura e estado selecionados."""
    if not cultura or cultura == "Nenhuma":
        return np.zeros(12)
    
    filtro = (df['UF'] == estado) & (df['Cultura'] == cultura)
    dados = df[filtro]
    
    if dados.empty:
        return np.zeros(12)
    
    # Seleciona apenas as colunas dos meses
    meses_cols = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    try:
        valores = dados.iloc[0][meses_cols].values.astype(float)
        # Substitui NaN por 0 para evitar erros matemáticos
        return np.nan_to_num(valores) 
    except Exception as e:
        st.error(f"Erro ao processar dados da cultura {cultura}: {e}")
        return np.zeros(12)

# Carrega os dados iniciais
df_ref = carregar_dados()

# --- FUNÇÕES AUXILIARES DE CÁLCULO ---

@st.dialog("Gerenciar Tabela Hídrica", width="large")
def modal():    
    # Carrega dados frescos
    df_atual = carregar_dados()
    
    # Permite mostrar e editar os dados
    st.write("Valores padrão de necessidade hídrica líquida em mm/mês.")
    #df_editado = st.data_editor(
    #    df_atual,
    #    num_rows="dynamic", # Permite adicionar linhas
    #    width="stretch",
    #    hide_index=True,
    #    key="data_editor_modal"
    #)

    # Apenas mostra os dados
    st.dataframe(df_atual, width="stretch", hide_index=True)
    
    st.caption("Fontes de dados: Embrapa (culturas), CONAB (calendário de safras), INMET (dados meteorológicos), ANA (recursos hídricos), ESALQ/USP, UFV, UFRGS, UFLA.")

    # Salva alterações de dados no CSV original
    #if st.button("💾 Salvar Alterações", type="primary", disabled=False):
    #    salvar_dados(df_editado)
    #    st.rerun() # Recarrega para atualizar os selects na interface principal

def calcular_horas_mensais(mm_necessarios, lamina_projeto_mm_21h):
    """Converte necessidade hídrica (mm) em horas de bombeamento."""
    if lamina_projeto_mm_21h <= 0: return 0
    capacidade_mm_h = lamina_projeto_mm_21h / 21.0
    return math.ceil(mm_necessarios / capacidade_mm_h)

def distribuir_carga(df, mes, grupo_idx, power_kw, horas_necessarias, janela_horas, alternancia, start_hour):
    """Distribui as horas de carga no DataFrame."""
    dias_disponiveis = []
    
    mask_mes = df.index.month == mes
    dias_do_mes = df[mask_mes].index.day.unique()
    
    for dia in dias_do_mes:
        day_of_year = df[(df.index.month == mes) & (df.index.day == dia)].index[0].dayofyear
        
        if alternancia:
            # Grupo A (idx 0): Dias Ímpares | Grupo B (idx 1): Dias Pares
            if grupo_idx == 0 and day_of_year % 2 != 0:
                dias_disponiveis.append(dia)
            elif grupo_idx == 1 and day_of_year % 2 == 0:
                dias_disponiveis.append(dia)
        else:
            dias_disponiveis.append(dia)
            
    qtd_dias_uteis = len(dias_disponiveis)
    
    if qtd_dias_uteis == 0:
        return 0, 0 
        
    horas_por_dia_base = int(horas_necessarias / qtd_dias_uteis)
    horas_restantes = horas_necessarias % qtd_dias_uteis
    
    max_horas_possiveis = qtd_dias_uteis * janela_horas
    deficit_horas = 0
    
    if horas_necessarias > max_horas_possiveis:
        deficit_horas = horas_necessarias - max_horas_possiveis
        horas_por_dia_base = janela_horas 
        horas_restantes = 0 
    
    for i, dia in enumerate(dias_disponiveis):
        horas_hoje = horas_por_dia_base
        
        if horas_restantes > 0 and horas_hoje < janela_horas:
            horas_hoje += 1
            horas_restantes -= 1
            
        horas_hoje = min(horas_hoje, janela_horas)
        
        indices = df[
            (df.index.month == mes) & 
            (df.index.day == dia) & 
            (df.index.hour >= start_hour) & 
            (df.index.hour < start_hour + horas_hoje)
        ].index
        
        col_name = f'Grupo_{"A" if grupo_idx == 0 else "B"}'
        df.loc[indices, col_name] = power_kw

    return horas_necessarias, deficit_horas

# --- INTERFACE STREAMLIT ---

st.markdown("### ⚡ Gerador de Perfil de Carga de Irrigação")
st.markdown("Defina a localização e as cargas para gerar um perfil de 8760h para o **Homer Energy**.")

with st.sidebar:
    st.logo("images/logo.png", size="large", icon_image="images/icone.png")
    st.write("")
    # 1. Inputs Globais
    st.header("🌍 Localização")
    
    # Filtra UFs disponíveis no CSV
    lista_ufs = sorted(df_ref['UF'].unique())
    estado = st.selectbox("Estado", lista_ufs)
    
    st.write("")
    st.header("🕓 Operação")
    alternancia = st.checkbox("Alternar Cargas", value=False, help="Se marcado, o Grupo A opera em dias ímpares e o Grupo B em dias pares.")

    st.write("")

    janela_operacao = st.slider(
        "Janela de Operação Diária (horas)", 
        min_value=6, 
        max_value=21, 
        value=10,
        help="Quantas horas por dia o sistema irá irrigar nos períodos de máx demanda."
    )

    st.write("")
    st.markdown(":grey[*Utilizar a menor janela possível que atenda à necessidade hídrica garante o melhor aproveitamento da energia solar e a maior economia de diesel.*]", text_alignment="justify")

    st.write("")
    t = st.time_input("Horário de Início da Irrigação Diária", "08:00", step=3600)
    t = t.strftime("%H")
    tmp = int(t)

    st.write("")
    st.header("📝 Dados")    
    if st.button("Tabela de Referência Hídrica", width="content"):
        modal()

    st.divider() 
    with st.container(horizontal=True):   
        st.space("large") 
        st.markdown(":grey[v1.1 (2026)  |  by CS]")

inicio_operacao = tmp

# --- SELEÇÃO DE CULTURAS (AGORA COM SUCESSÃO) ---
# Obtém as culturas disponíveis para aquele estado
culturas_do_estado = sorted(df_ref[df_ref['UF'] == estado]['Cultura'].unique())

col1, col2 = st.columns(2)

with col1:
    st.markdown("#### Grupo de Carga A")
    # Sub-colunas para selecionar cultura 1 e 2
    c1_a, c1_b = st.columns(2)
    with c1_a:
        cultura_a1 = st.selectbox("Cultura 1 (Principal)", culturas_do_estado, key="cA1")
    with c1_b:
        # Adiciona opção "Nenhuma"
        opcoes_c2 = ["Nenhuma"] + list(culturas_do_estado)
        cultura_a2 = st.selectbox("Cultura 2 (Sucessão)", opcoes_c2, key="cA2")
        
    potencia_a = st.number_input("Potência (kW)", min_value=0.0, value=0.0, step=1.0, key="pA")
    lamina_a = st.number_input("Lâmina de projeto (mm/21h)", min_value=0.0, value=9.0, step=0.5, key="lA", help="Quanto o pivot aplica se rodar 21h direto.")

with col2:
    if alternancia:
        st.markdown("#### Grupo de Carga B")
        c2_a, c2_b = st.columns(2)
        with c2_a:
            cultura_b1 = st.selectbox("Cultura 1 (Principal)", culturas_do_estado, key="cB1")
        with c2_b:
            opcoes_c2b = ["Nenhuma"] + list(culturas_do_estado)
            cultura_b2 = st.selectbox("Cultura 2 (Sucessão)", opcoes_c2b, key="cB2")
            
        potencia_b = st.number_input("Potência (kW)", min_value=0.0, value=0.0, step=1.0, key="pB")
        lamina_b = st.number_input("Lâmina de projeto (mm/21h)", min_value=0.0, value=9.0, step=0.5, key="lB")
    else:
        cultura_b1 = None
        cultura_b2 = None
        potencia_b = 0
        lamina_b = 0

# --- PROCESSAMENTO ---

# Criar DataFrame base
dates = pd.date_range(start="2023-01-01", end="2023-12-31 23:00", freq="h")
df = pd.DataFrame(index=dates)
df['Grupo_A'] = 0.0
df['Grupo_B'] = 0.0

warnings = []
dados_tabela_a = []
dados_tabela_b = []
meses_nomes = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

# --- PREPARAÇÃO DOS DADOS HÍDRICOS (LÓGICA DE SUCESSÃO) ---
# Busca mm da cultura 1 e cultura 2 e escolhe o MAIOR valor mês a mês
mm_a1 = obter_mm_mensal(df_ref, estado, cultura_a1)
mm_a2 = obter_mm_mensal(df_ref, estado, cultura_a2)
# numpy.maximum compara array elemento a elemento e retorna o maior
mm_final_a = np.maximum(mm_a1, mm_a2)

if alternancia:
    mm_b1 = obter_mm_mensal(df_ref, estado, cultura_b1)
    mm_b2 = obter_mm_mensal(df_ref, estado, cultura_b2)
    mm_final_b = np.maximum(mm_b1, mm_b2)
else:
    mm_final_b = np.zeros(12)

# Loop Mes a Mes
for mes in range(1, 13):
    idx = mes - 1
    
    # --- GRUPO A ---
    mm_nec_a = mm_final_a[idx]
    horas_nec_a = calcular_horas_mensais(mm_nec_a, lamina_a)
    nec_a, def_a = distribuir_carga(df, mes, 0, potencia_a, horas_nec_a, janela_operacao, alternancia, inicio_operacao)

    h_entregue_a = nec_a - def_a
    mm_entregue_a = h_entregue_a * (lamina_a / 21.0) if horas_nec_a > 0 else 0
    
    dados_tabela_a.append({
        "Mês": meses_nomes[idx],
        "Precisa (mm)": f"{mm_nec_a:.1f}",
        "Entrega (mm)": f"{min(mm_nec_a, mm_entregue_a):.1f}",
        "Déficit (mm)": f"{max(0, mm_nec_a - mm_entregue_a):.1f}"
    })

    if def_a > 0:
        warnings.append(f"⚠️ **{meses_nomes[idx]} (Grupo A):** Faltam {def_a} horas de água.")

    # --- GRUPO B ---
    if potencia_b > 0:
        mm_nec_b = mm_final_b[idx]
        horas_nec_b = calcular_horas_mensais(mm_nec_b, lamina_b)
        nec_b, def_b = distribuir_carga(df, mes, 1, potencia_b, horas_nec_b, janela_operacao, alternancia, inicio_operacao)
        
        h_entregue_b = nec_b - def_b
        mm_entregue_b = h_entregue_b * (lamina_b / 21.0) if horas_nec_b > 0 else 0
        
        dados_tabela_b.append({
            "Mês": meses_nomes[idx],
            "Precisa (mm)": f"{mm_nec_b:.1f}",
            "Entrega (mm)": f"{min(mm_nec_b, mm_entregue_b):.1f}",
            "Déficit (mm)": f"{max(0, mm_nec_b - mm_entregue_b):.1f}"
        })
        
        if def_b > 0:
            warnings.append(f"⚠️ **{meses_nomes[idx]} (Grupo B):** Faltam {def_b} horas de água.")

# Coluna Final Total
df['Total_Load_kW'] = df['Grupo_A'] + df['Grupo_B']

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
    st.error(f"**Atenção**: Configuração atual não atende à necessidade hídrica completa em {len(warnings)} casos.")
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

# Se o pico for maior que 0, calcula o fator. Se não, é 0.
if val_pico > 0:
    val_fator = (df['Total_Load_kW'].mean() / val_pico) * 100
else:
    val_fator = 0.0

# Formatação Brasileira
cons_formatado = f"{val_consumo:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
pot_formatado = f"{val_pico:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
fator_formatado = f"{val_fator:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

col_m1, col_m2, col_m3, col_m4 = st.columns(4)
col_m1.metric("Consumo Anual", f"{cons_formatado} kWh")
col_m2.metric("Potência Máxima", f"{pot_formatado} kW")
col_m3.metric("Fator de Carga", f"{fator_formatado} %")

# --- DOWNLOAD ---
@st.cache_data
def convert_df(df):
    return df['Total_Load_kW'].to_csv(index=False, header=False, decimal=",").encode('utf-8')

csv = convert_df(df)

with col_m4:
    st.write("")
    st.write("")
    st.download_button(
        label="📥 Baixar CSV",
        data=csv,
        file_name=f'perfil_{estado}_{cultura_a1}.csv',
        mime='text/csv',
    )