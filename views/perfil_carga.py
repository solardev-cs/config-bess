import altair as alt
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

# Reserva o topo da coluna direita para o slider de Horas Mínimas — só dá pra
# desenhá-lo depois de calcular teto_horas_dia (mais abaixo), mas ele precisa
# aparecer visualmente acima do bloco de Horas Máximas nessa mesma coluna.
with col_loc2:
    horas_min_slot = st.empty()

with col_loc1:
    hora_inicio_auto = persistir("hora_inicio_auto", st.checkbox(
        "Janela de irrigação automática",
        value=valor_persistido("hora_inicio_auto", True), key="hora_inicio_auto",
        help=(
            "Quando ativada, centra a janela de irrigação diária em torno do meio-dia, para máximo aproveitamento da irradiação solar "
            " — ideal para sistemas sem diesel (solar+BESS). Desative para escolher um horário de "
            "início manual, por exemplo, para reduzir perdas por evaporação/deriva irrigando fora do horário de pico de calor e vento."
        ),
    ))
    if hora_inicio_auto:
        tmp = None
    else:
        t = persistir("hora_inicio_irrigacao", st.time_input(
            "Horário de Início da Irrigação Diária",
            value=valor_persistido("hora_inicio_irrigacao", "08:00"),
            step=3600, key="hora_inicio_irrigacao",
        ))
        tmp = int(t.strftime("%H"))

# Teto vindo do horário: com início manual, a irrigação não pode cruzar a
# virada do dia civil (distribuir_carga() só agenda horas dentro do mesmo dia)
# nem passar de 21h (tempo de deslocamento/reposicionamento do pivô). Com
# horário automático (centralizado no meio-dia), a janela nunca cruza a
# virada do dia por construção, então só o limite de 21h vale.
teto_horario = 21 if tmp is None else min(21, max(1, 24 - tmp))

with col_loc2:
    horas_max_auto = persistir("horas_max_auto", st.checkbox(
        "Nr. máximo de horas de irrigação diária automático",
        value=valor_persistido("horas_max_auto", True), key="horas_max_auto",
        help=(
            "Quando ativado, calcula o período de irrigação diário conforme a necessidade hídrica, respeitando apenas os limites físicos ou de tempo. Desative para definir um teto de horas de irrigação por dia — ideal para sistemas sem diesel (solar+BESS), por ex.: 8-10h)"
        ),
    ))
    if horas_max_auto:
        horas_max_operacao = None
    else:
        hmax_min = 1
        if hmax_min < teto_horario:
            hmax_default = max(hmax_min, min(valor_persistido("horas_max_operacao", teto_horario), teto_horario))
            horas_max_operacao = persistir("horas_max_operacao", st.slider(
                "Horas Máximas de Operação por Dia",
                min_value=hmax_min, max_value=teto_horario, value=hmax_default,
                key="horas_max_operacao",
                help="Teto de horas de irrigação por dia. Acima dele, o mês que não couber vira déficit em vez de mais horas/dia.",
            ))
        else:
            # min == max (janela já colapsada em 1h) -> st.slider crasharia.
            horas_max_operacao = persistir("horas_max_operacao", st.number_input(
                "Horas Máximas de Operação por Dia",
                min_value=hmax_min, max_value=teto_horario, value=teto_horario, step=1,
                key="horas_max_operacao",
            ))

# Teto efetivo (para limitar o slider de Horas Mínimas): combina o teto do
# horário com o teto manual opcional, igual à lógica de gerar_perfil_carga().
teto_horas_dia = teto_horario if horas_max_operacao is None else min(teto_horario, horas_max_operacao)

hmin_min = 1
hmin_default = max(hmin_min, min(valor_persistido("horas_min_operacao", 10), teto_horas_dia))
ajuda_hmin = (
    "Mínimo de horas que cada dia de irrigação opera. O app concentra a "
    "necessidade hídrica mensal em menos dias — cada um rodando ao menos esse "
    f"número de horas — em vez de espalhar poucas horas por todos os dias do mês. "
    f"Limitado a {teto_horas_dia}h pelo horário/teto máximo escolhidos."
)
with horas_min_slot.container():
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
        # st.slider exige min_value < max_value estritamente. Com um teto bem
        # apertado (ex.: início 23h -> só resta 1h antes da virada do dia),
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
    horas_max_por_dia=horas_max_operacao,
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

def dados_balanco(balanco):
    """Linhas do balanço hídrico por mês; "-" em meses sem irrigação."""
    dados = []
    for b in balanco:
        if b.dias_operacao == 0 and b.deficit_mm <= 0:
            dados.append({
                "Mês": b.mes, "Precisa (mm)": "-", "Entrega (mm)": "-",
                "Déficit (mm)": "-", "Dias de operação": "-",
            })
        else:
            dados.append({
                "Mês": b.mes,
                "Precisa (mm)": f"{b.precisa_mm:.1f}",
                "Entrega (mm)": f"{b.entrega_mm:.1f}",
                "Déficit (mm)": f"{b.deficit_mm:.1f}",
                "Dias de operação": str(b.dias_operacao),
            })
    return dados


dados_tabela_a = dados_balanco(resultado.balanco_a)
dados_tabela_b = dados_balanco(resultado.balanco_b)

# --- RESULTADOS VISUAIS ---

st.divider()
st.markdown("#### Resultado do Perfil")
st.write("")

LINHAS_DEFICIT = ["Precisa (mm)", "Entrega (mm)", "Déficit (mm)"]

def meses_em_deficit(balanco):
    return {b.mes for b in balanco if b.deficit_mm > 0}

def style_deficit(meses_deficit, linhas=None):
    """Pinta de vermelho (nas ``linhas`` dadas, ou todas) as colunas dos meses em déficit."""
    def _estilo(col):
        vermelho = col.name in meses_deficit
        return ['color: red' if vermelho and (linhas is None or linha in linhas) else '' for linha in col.index]
    return _estilo

def dados_lamina_dia(balanco):
    """Linhas "Precisa/Entrega (mm/dia)" por mês; "-" em meses sem irrigação."""
    dados = []
    for b in balanco:
        if b.dias_operacao > 0:
            precisa = formatar_numero(b.precisa_mm / b.dias_operacao, 1)
            entrega = formatar_numero(b.lamina_tipica_dia_mm, 1)
        else:
            precisa = entrega = "-"
        dados.append({"Mês": b.mes, "Precisa (mm/dia)": precisa, "Entrega (mm/dia)": entrega})
    return dados

def gerar_df_transposto(dados):
    df_t = pd.DataFrame(dados).set_index("Mês").T
    return df_t

tab_col1, tab_col2 = st.columns(2)

with tab_col1:
    st.markdown(f"**Balanço Hídrico A ({cultura_a1} + {cultura_a2})**")
    df_a_final = gerar_df_transposto(dados_tabela_a)
    st.dataframe(df_a_final.style.apply(style_deficit(meses_em_deficit(resultado.balanco_a), LINHAS_DEFICIT), axis=0), width="content")

with tab_col2:
    if potencia_b > 0:
        st.markdown(f"**Balanço Hídrico B ({cultura_b1} + {cultura_b2})**")
        df_b_final = gerar_df_transposto(dados_tabela_b)
        st.dataframe(df_b_final.style.apply(style_deficit(meses_em_deficit(resultado.balanco_b), LINHAS_DEFICIT), axis=0), width="content")

st.markdown("**Lâmina Necessária x Real**")
lam_col1, lam_col2 = st.columns(2)

with lam_col1:
    st.dataframe(
        gerar_df_transposto(dados_lamina_dia(resultado.balanco_a)).style.apply(
            style_deficit(meses_em_deficit(resultado.balanco_a)), axis=0),
        width="content",
    )

with lam_col2:
    if potencia_b > 0:
        st.dataframe(
            gerar_df_transposto(dados_lamina_dia(resultado.balanco_b)).style.apply(
                style_deficit(meses_em_deficit(resultado.balanco_b)), axis=0),
            width="content",
        )

if warnings:
    st.warning(f"**Atenção**: Configuração atual não atende à necessidade hídrica completa em {len(warnings)} casos.")
    with st.expander("Ver detalhes dos déficits"):
        for w in warnings: st.write(w)
else:
    st.success("**Configuração Válida**: Necessidade hídrica atendida.")

# Sugestão de lâmina maior (só um aviso — o ajuste é manual, no campo
# "Lâmina de projeto" de cada grupo, acima).
if resultado.lamina_sugerida_a is not None:
    st.info(
        f"💧 Para atender a necessidade hídrica do **Grupo A** dentro da janela diária "
        f"atual, considere um pivô com lâmina de projeto de pelo menos "
        f"**{formatar_numero(resultado.lamina_sugerida_a, 1)} mm/21h** "
        f"(atual: {formatar_numero(lamina_a, 1)} mm/21h) — ajuste manualmente o campo "
        f"'Lâmina de projeto' do Grupo A acima."
    )
if potencia_b > 0 and resultado.lamina_sugerida_b is not None:
    st.info(
        f"💧 Para atender a necessidade hídrica do **Grupo B** dentro da janela diária "
        f"atual, considere um pivô com lâmina de projeto de pelo menos "
        f"**{formatar_numero(resultado.lamina_sugerida_b, 1)} mm/21h** "
        f"(atual: {formatar_numero(lamina_b, 1)} mm/21h) — ajuste manualmente o campo "
        f"'Lâmina de projeto' do Grupo B acima."
    )

st.write("")
st.area_chart(df['Total_Load_kW'], width="stretch", color="#2ecc71")

# Mapa de calor anual (dia x hora): mesma leitura do "Yearly Profile" do
# HOMER — eixo X = dia do ano, eixo Y esquerdo = hora do dia, cor = potência
# (kW), com a escala de cor completa (preto -> azul -> ciano -> verde ->
# amarelo -> laranja -> vermelho), igual ao HOMER. Gráfico nativo do
# Streamlit (Altair/Vega-Lite, mesma família do st.area_chart usado acima e
# do SOC em Simulação Técnica) — não matplotlib: fica interativo (tooltip,
# zoom/pan) em vez de uma imagem estática.
st.write("")
dias_ano = np.repeat(np.arange(1, 366), 24)
horas_dia = np.tile(np.arange(0, 24), 365)
df_heatmap = pd.DataFrame({
    "dia": dias_ano,
    "dia_ini": dias_ano - 0.5,
    "dia_fim": dias_ano + 0.5,
    "hora": horas_dia,
    "hora_fim": horas_dia + 1,
    "kw": df['Total_Load_kW'].to_numpy(),
})

# Gradiente só para as horas COM irrigação; 0 kW é forçado a preto puro via
# alt.condition (a escala contínua sozinha, mesmo com domínio calibrado
# ponto a ponto, não bate no preto exato em 0 — fica um azul escuro).
CORES_HOMER_GRADIENTE = ["#0000ff", "#00ffff", "#00ff00", "#ffff00", "#ff8000", "#ff0000"]
pico_kw = float(df['Total_Load_kW'].max()) or 1.0
n_cores = len(CORES_HOMER_GRADIENTE)
dominio_cores = [pico_kw * i / (n_cores - 1) for i in range(n_cores)]

ALTURA_HEATMAP = 340

# Dia-do-ano do 1º dia de cada mês (ano de referência não bissexto — igual
# ao ano_referencia fixo em engine/load_profile.py), usado pra rotular o
# eixo X por mês em vez de número do dia.
MESES_ABREV = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
DIAS_INICIO_MES = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
LABEL_EXPR_MESES = " : ".join(
    f"datum.value == {dia} ? '{mes}'" for dia, mes in zip(DIAS_INICIO_MES, MESES_ABREV)
) + " : ''"

grafico_heatmap = alt.Chart(df_heatmap).mark_rect().encode(
    x=alt.X(
        "dia_ini:Q", title=None,
        scale=alt.Scale(domain=[1, 365], nice=False),
        axis=alt.Axis(values=DIAS_INICIO_MES, labelExpr=LABEL_EXPR_MESES, labelOverlap=False),
    ),
    x2="dia_fim:Q",
    y=alt.Y(
        "hora:Q", title="Hora do Dia",
        scale=alt.Scale(domain=[0, 24], nice=False),
        axis=alt.Axis(values=list(range(0, 25, 2)), labelOverlap=False),
    ),
    y2="hora_fim:Q",
    color=alt.condition(
        alt.datum.kw <= 0,
        alt.value("#000000"),
        alt.Color(
            "kw:Q", title="Potência (kW)",
            scale=alt.Scale(domain=dominio_cores, range=CORES_HOMER_GRADIENTE, nice=False),
            legend=alt.Legend(
                # values=dominio_cores força o 0 kW a aparecer no rótulo da
                # legenda — sem isso o Vega-Lite escolhe "ticks bonitos" (ex.
                # 100, 200, ...) por conta própria e pode pular o extremo.
                values=dominio_cores,
                padding=0,
                # {"expr": "height"} amarra o comprimento do gradiente ao
                # sinal de altura da ÁREA DE PLOTAGEM do Vega (o mesmo valor
                # de ALTURA_HEATMAP passado em .properties(height=...)) — não
                # ao elemento gráfico inteiro (que inclui o título acima).
                gradientLength={"expr": "height"},
                titleOrient="left",
            ),
        ),
    ),
    tooltip=[
        alt.Tooltip("dia:Q", title="Dia"),
        alt.Tooltip("hora:Q", title="Hora"),
        alt.Tooltip("kw:Q", title="Potência (kW)", format=".1f"),
    ],
).properties(height=ALTURA_HEATMAP, title="Perfil Anual de Carga")

st.altair_chart(grafico_heatmap, width="stretch")

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