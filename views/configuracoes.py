"""Página Streamlit: Configurações Gerais do App.

Parâmetros econômicos e de sistema que raramente mudam de uma simulação
para outra (custos de referência, TMA, preço do diesel etc.) — em vez de
serem redigitados em cada página que os usa (Simulação Técnica, na
Otimização, e Análise Financeira), ficam centralizados aqui em
``st.session_state`` (chaves ``cfg_*``) e são lidos, não reeditados, pelas
demais páginas.
"""
import altair as alt
import pandas as pd
import streamlit as st

from engine.costs import CUSTO_BESS_PADRAO_RS_KWH, custo_fv_padrao_rs_kwp
from engine.formatting import formatar_numero
from views._bess_catalogo import CATALOGO_BESS_DEFAULT
from views._custos_referencia import acoplamento_bess_selecionado
from views._dados_hidricos import carregar_dados
from views._gerador_catalogo import CATALOGO_GERADORES_DEFAULT, catalogo_para_modelos
from views._inversor_catalogo import CATALOGO_INVERSORES_DEFAULT
from views._persist import indice_persistido, persistir, valor_persistido

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
    # O custo do FV (modo automático por acoplamento do BESS) depende do catálogo de BESS,
    # que só é editado bem mais abaixo nesta mesma página — então reserva o lugar aqui e
    # preenche depois do editor do catálogo (mesmo padrão de placeholder do Perfil de Carga),
    # senão trocar o acoplamento no catálogo só refletiria aqui na interação seguinte.
    slot_custo_fv = st.empty()
with col_c2:
    persistir("cfg_custo_bess", st.number_input(
        "Custo BESS (R$/kWh)", min_value=0.0, value=valor_persistido("cfg_custo_bess", CUSTO_BESS_PADRAO_RS_KWH), step=50.0, key="cfg_custo_bess",
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

df_catalogo_gerador = pd.DataFrame(valor_persistido("cfg_geradores_catalogo", CATALOGO_GERADORES_DEFAULT))
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

# --- Curva de consumo de diesel (uma só, escalada por modelo — ver engine/fuel_curve.py) ---
st.markdown("**Curva de Consumo de Diesel**")
modelos_curva = {m.nome: m for m in catalogo_para_modelos(df_catalogo_editado.to_dict("records"))}
if not modelos_curva:
    st.info("Cadastre ao menos um modelo de gerador no catálogo acima para ver a curva de consumo.")
else:
    _nomes_curva = list(modelos_curva)
    col_sel_curva, _ = st.columns([1, 2])
    with col_sel_curva:
        nome_curva = persistir("cfg_curva_modelo", st.selectbox(
            "Modelo", _nomes_curva, index=indice_persistido("cfg_curva_modelo", _nomes_curva), key="cfg_curva_modelo",
            help="A curva medida no BRG Slim Infinity 550 vale para todos os modelos: é escalada pela "
            "potência nominal e pelo consumo (L/h) cadastrado de cada um, então não é preciso "
            "cadastrar uma curva por gerador.",
        ))
    modelo_curva = modelos_curva[nome_curva]
    curva = modelo_curva.curva_consumo
    df_curva = pd.DataFrame({
        "Carga (kW)": curva.pot_kw,
        "% da Nominal": [p / modelo_curva.pot_nominal_kw * 100 for p in curva.pot_kw],
        "Consumo (L/h)": curva.consumo_l_h,
    })
    df_curva["Eficiência (kWh/L)"] = df_curva["Carga (kW)"] / df_curva["Consumo (L/h)"]

    col_curva_tab, col_curva_graf = st.columns(2)
    with col_curva_tab:
        st.dataframe(
            df_curva, width="stretch", hide_index=True, height=360,
            column_config={
                "Carga (kW)": st.column_config.NumberColumn(format="%.0f"),
                "% da Nominal": st.column_config.NumberColumn(format="%.0f%%"),
                "Consumo (L/h)": st.column_config.NumberColumn(format="%.1f"),
                "Eficiência (kWh/L)": st.column_config.NumberColumn(format="%.2f"),
            },
        )
    with col_curva_graf:
        grafico_curva = alt.Chart(df_curva).mark_line(point=True, color="#e67e22").encode(
            x=alt.X("Carga (kW):Q", title="Carga (kW)"),
            y=alt.Y("Consumo (L/h):Q", title="Consumo (L/h)"),
            tooltip=[
                alt.Tooltip("Carga (kW):Q", format=".0f"),
                alt.Tooltip("Consumo (L/h):Q", format=".1f"),
                alt.Tooltip("Eficiência (kWh/L):Q", format=".2f"),
            ],
        ).properties(height=360)
        st.altair_chart(grafico_curva, width="stretch")
    st.caption(
        f"Consumo em vazio (ligado, sem carga): **{formatar_numero(curva.consumo_em_vazio_l_h, 1)} L/h**. "
        "Curva medida em teste de carga do BRG Slim Infinity 550, escalada para o modelo selecionado."
    )

st.divider()

st.markdown("#### :primary[:material/sunny:] Catálogo de Inversores")

df_catalogo_inversor = pd.DataFrame(valor_persistido("cfg_inversores_catalogo", CATALOGO_INVERSORES_DEFAULT))
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

df_catalogo_bess = pd.DataFrame(valor_persistido("cfg_bess_catalogo", CATALOGO_BESS_DEFAULT))
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
        "Acoplamento Solar": st.column_config.SelectboxColumn(
            "Acoplamento Solar", options=["CA", "CC"], required=True,
            help="CA: BESS com PCS próprio — a energia solar cobre a carga primeiro, e só a "
            "sobra carrega o BESS. CC: BESS e inversor solar são o mesmo equipamento — toda a "
            "energia solar carrega o BESS primeiro, e a carga é sempre suprida pela descarga "
            "do BESS. Determina a estratégia de despacho usada na Simulação Técnica.",
        ),
    },
)
persistir("cfg_bess_catalogo", df_catalogo_bess_editado.to_dict("records"))

# --- Custo FV (preenche o espaço reservado lá em cima; ver comentário em `slot_custo_fv`) ---
acoplamento_bess = acoplamento_bess_selecionado(df_catalogo_bess_editado.to_dict("records"))
custo_fv_padrao = custo_fv_padrao_rs_kwp(acoplamento_bess)
# session_state (e não só o valor persistido): o clique no checkbox só chega ao script na
# execução seguinte, e o number_input abaixo é desenhado ANTES do checkbox.
custo_fv_automatico = st.session_state.get("cfg_custo_fv_auto", valor_persistido("cfg_custo_fv_auto", True))
with slot_custo_fv.container():
    if custo_fv_automatico:
        # Sem key: o valor exibido vem do `value=` e acompanha o acoplamento a cada execução.
        st.number_input("Custo FV (R$/kWp)", value=custo_fv_padrao, step=100.0, disabled=True)
    else:
        persistir("cfg_custo_fv", st.number_input(
            "Custo FV (R$/kWp)", min_value=0.0, value=valor_persistido("cfg_custo_fv", custo_fv_padrao),
            step=100.0, key="cfg_custo_fv",
        ))
    persistir("cfg_custo_fv_auto", st.checkbox(
        "Automático (conforme acoplamento do BESS)",
        value=valor_persistido("cfg_custo_fv_auto", True), key="cfg_custo_fv_auto",
    ))

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

st.markdown("#### :primary[:material/account_tree:] Estratégia de Despacho")
st.markdown(
    """
Passo a passo do que o simulador faz em **cada hora do ano (8760h)** para atender a carga. O estado de carga
do BESS (SOC) passa de uma hora para a seguinte; no início do ano ele começa no SOC mínimo.

**0. Preparação da hora (igual nos dois acoplamentos)**
1. **Carga:** valor da hora no perfil gerado em Perfil de Carga.
2. **Solar:** a irradiância horária normalizada (TMY/NSRDB) é convertida em potência DC do arranjo
   (potência do inversor × ILR × fração de irradiância, já descontadas as perdas de sistema de 14%).
   No acoplamento CA essa potência é limitada pela potência do inversor (clipping); no CC é usada antes do clipping.
3. **Limites do BESS:** potência de carga/descarga = capacidade × C-rate do modelo; SOC mínimo = capacidade × (1 − DoD);
   a perda de round-trip é dividida igualmente entre carga e descarga (eficiência por sentido = raiz da eficiência round-trip).
4. **Limites do gerador:** piso de carga = nº mínimo em operação × potência prime × % mínimo do catálogo;
   teto de potência = nº de geradores × potência contínua. Com nº de geradores = 0, o gerador nunca entra.

**A. Acoplamento CA** (BESS com PCS próprio) — prioridade: solar direta → BESS → gerador
1. **Solar direta:** a solar atende a carga primeiro, até o valor da carga.
2. **Recarga do BESS:** a sobra de solar (o que passou da carga) carrega o BESS, limitada pela potência do BESS,
   pelo espaço livre até a capacidade máxima e pela eficiência de carga. O que não couber é curtailment (excedente/dump).
3. **Descarga do BESS:** o que falta da carga depois da solar é pedido ao BESS, limitado pela potência do BESS,
   pela energia disponível acima do SOC mínimo e pela eficiência de descarga.
4. **Gerador:** o déficit que restou depois de solar + BESS vai para o gerador (regras mais abaixo).
5. **Sobra por piso do gerador:** se o gerador precisar operar acima do déficit (por causa do piso), ele já está
   atendendo parte da carga, então as outras fontes cedem, nesta ordem: (a) o BESS descarrega menos (a energia volta
   ao SOC, sem perda); (b) a solar direta cede, e a parcela liberada carrega o BESS (dentro da potência de carga que
   ainda resta na hora) — o que não couber é solar não utilizada e vira excedente/dump. Só o que sobrar mesmo assim
   (piso do gerador maior que a carga da hora) vira excedente/dump. O gerador nunca carrega a bateria.
6. **Energia não suprida:** a carga que nenhuma fonte cobriu vira déficit (é o que compõe o LOLP).

**B. Acoplamento CC** (BESS e inversor solar no mesmo equipamento) — prioridade: BESS (alimentado pela solar) → gerador
1. **Recarga do BESS:** toda a solar DC disponível carrega o BESS primeiro, com os mesmos limites de potência,
   espaço livre e eficiência. O que não couber é curtailment (excedente/dump).
2. **Descarga do BESS:** a carga é sempre atendida pela descarga do BESS, com os mesmos limites (potência, energia
   acima do SOC mínimo, eficiência) — incluindo a energia que acabou de entrar na mesma hora. Não existe solar direta
   para a carga: toda energia entregue paga a perda de round-trip.
3. **Gerador:** o déficit que restou depois do BESS vai para o gerador (regras mais abaixo).
4. **Sobra por piso do gerador:** se o gerador precisar operar acima do déficit (por causa do piso), ele já está
   atendendo parte da carga, então o BESS descarrega menos (a energia volta ao SOC, sem perda). Só o que sobrar
   depois disso (piso do gerador maior que a carga da hora) vira excedente/dump. O gerador nunca carrega a bateria.
5. **Energia não suprida:** igual ao CA.

**Regras do gerador (nos dois acoplamentos)**
- **ON/OFF:** só liga se houver déficit. Potência = déficit, mas nunca abaixo do piso: se o déficit for menor que o
  piso, opera no piso e a parte acima do déficit é tratada como "Sobra por piso do gerador" (passo acima). Sem
  déficit, fica desligado.
- **Sempre ON:** fica ligado sempre que há carga, com potência = déficit ou o piso, o que for maior — mesmo que
  solar + BESS já cubram tudo (nesse caso opera no piso, atendendo parte da carga, e as outras fontes cedem).
- Com piso de 0% não há sobra: o gerador só cobre o déficit, e os dois modos ficam idênticos.
- Em ambos os modos a potência é limitada ao teto do parque; a parte do déficit acima do teto vira energia não suprida.
- **Consumo de diesel:** vem da curva de consumo do modelo (Catálogo de Geradores, acima), que inclui o consumo em
  vazio e a perda de eficiência em carga baixa. Se a potência exceder a contínua de uma máquina, o parque liga mais
  máquinas automaticamente (escalonamento), dividindo a carga igualmente — nunca menos que o nº mínimo em operação.
  Em "Sempre ON", o gerador ligado sem déficit queima o consumo em vazio.

**Contabilidade (uso no financeiro)**
- Energia evitada de diesel = solar utilizada + energia descarregada pelo BESS. No CC a "solar utilizada" é sempre 0
  (tudo passa pelo BESS), então 100% da energia evitada é contada como energia da bateria; a solar que carregou o BESS
  aparece apenas como informação (Energia Solar Armazenada).
- Excedente (curtailment/dump) = solar que não coube no BESS + solar liberada para o gerador que também não coube
  (CA) + sobra do piso do gerador que nenhuma fonte pôde absorver (piso maior que a carga da hora).
- O diesel consumido é sempre o da energia realmente gerada (inclusive no piso): o que muda com a absorção da sobra é
  que a bateria (e a solar) deixam de ser gastas à toa quando o gerador já está atendendo a carga.
- **Economia de diesel** = diesel do cenário sem FV/BESS (o parque atendendo a carga inteira, com escalonamento
  automático a partir de 1 máquina) − diesel do sistema simulado, em litros × preço do diesel. Nos anos seguintes, os
  litros evitados acompanham a degradação de FV/BESS. Sem FV/BESS o gerador ligado em carga baixa é ineficiente;
  desligá-lo evita o consumo em vazio inteiro, não só os kWh gerados.
"""
)

st.divider()