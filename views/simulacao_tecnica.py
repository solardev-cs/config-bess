"""Página Streamlit: Simulação Técnica do Sistema Híbrido (Fases 2 e 3).

Fluxo único:
    1. Configure os componentes do sistema: usina FV, BESS e gerador diesel
       (opcionalmente via otimização automática).
    2. Rode a simulação horária (8760h) usando a carga gerada na página
       "Perfil de Carga" e a localização definida na página "Home".
    3. Analise o fluxo de energia entre as fontes e os indicadores de
       desempenho (KPIs) do sistema.

Esta página consome diretamente o motor de cálculo (``engine/*``), sem
duplicar nenhuma lógica de negócio — apenas monta as configurações a
partir dos inputs do usuário e chama ``engine.simulator.simular_ano``.
"""
import numpy as np
import pandas as pd
import streamlit as st

from engine.dispatch import dispatch_strategy_para_acoplamento
from engine.formatting import formatar_brl, formatar_numero
from engine.generator_catalog import generator_config_from_modelo
from engine.models import BatteryConfig, EconomicConfig, SolarConfig
from engine.optimizer import otimizar_sistema_completo
from engine.simulator import simular_ano
from engine.solar.nsrdb_api import NsrdbApiError, NsrdbSolarProvider
from views._bess_catalogo import CATALOGO_BESS_DEFAULT, catalogo_para_modelos_bess
from views._gerador_catalogo import CATALOGO_GERADORES_DEFAULT, catalogo_para_modelos
from views._inversor_catalogo import CATALOGO_INVERSORES_DEFAULT, catalogo_para_modelos_inversor
from views._nav import stepper
from views._persist import forcar_valor, indice_persistido, persistir, valor_persistido
from views._staleness import aviso_se_desatualizado, publicar_snapshot_atual, snapshot_simulacao

stepper("views/simulacao_tecnica.py")

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

# --- VERIFICA SE HÁ CARGA E LOCALIZAÇÃO DISPONÍVEIS ---
carga_kw = st.session_state.get("carga_kw")
mapa_lat = st.session_state.get("mapa_lat")
mapa_lon = st.session_state.get("mapa_lon")

if carga_kw is None:
    st.warning(
        "⚠️ Nenhum perfil de carga encontrado. Vá até a página "
        "**Perfil de Carga** e gere um perfil antes de simular."
    )

if mapa_lat is None or mapa_lon is None:
    st.warning(
        "⚠️ Nenhuma localização definida. Vá até a página **Home** e selecione a "
        "localização no mapa antes de simular."
    )

pronto_para_simular = carga_kw is not None and mapa_lat is not None and mapa_lon is not None

# --- CATÁLOGOS (cadastrados em Configurações) ---
# Fallback nos mesmos defaults exibidos em Configurações (não um `[]` vazio): sem isso, um
# usuário que chega direto nesta página, sem nunca ter visitado Configurações nesta sessão,
# via "Nenhum modelo cadastrado" mesmo havendo um catálogo padrão — `valor_persistido()` só
# enxerga a cópia persistida depois que a página Configurações roda ao menos uma vez.
modelos_catalogo = catalogo_para_modelos(valor_persistido("cfg_geradores_catalogo", CATALOGO_GERADORES_DEFAULT))
modelos_por_nome = {m.nome: m for m in modelos_catalogo}

modelos_inversor_catalogo = catalogo_para_modelos_inversor(
    valor_persistido("cfg_inversores_catalogo", CATALOGO_INVERSORES_DEFAULT)
)
modelos_inversor_por_nome = {m.nome: m for m in modelos_inversor_catalogo}

modelos_bess_catalogo = catalogo_para_modelos_bess(valor_persistido("cfg_bess_catalogo", CATALOGO_BESS_DEFAULT))
modelos_bess_por_nome = {m.nome: m for m in modelos_bess_catalogo}

# --- 1. OTIMIZAÇÃO ---
st.markdown("#### :primary[:material/recenter:] Otimização do Sistema")
if carga_kw is not None:
    st.caption(
        f"Consumo anual: **{formatar_numero(carga_kw.sum(), 0)} kWh**. Potência carga: **{formatar_numero(carga_kw.max(), 1)} kW**."
    )

custo_fv_otimizacao = valor_persistido("cfg_custo_fv", 6500.0)
custo_bess_otimizacao = valor_persistido("cfg_custo_bess", 2000.0)
preco_diesel_otimizacao = valor_persistido("cfg_preco_diesel", 7.0)
tma_otimizacao = valor_persistido("cfg_tma", 5.0) / 100.0
degradacao_bess_otimizacao = valor_persistido("cfg_degradacao_bess_soh", 2.0) / 100.0

col_opt1, col_opt2 = st.columns([1, 2])
with col_opt1:
    _opcoes_metrica = ["VPL", "LCOE"]
    metrica_otimizacao = persistir("opt_metrica", st.selectbox(
        "Métrica a otimizar", _opcoes_metrica,
        index=indice_persistido("opt_metrica", _opcoes_metrica),
        key="opt_metrica",
        help="VPL é maximizado; LCOE é minimizado.",
    ))
    st.write("")
    otimizar = st.button(
    ":material/bolt: Otimizar", type="primary", width="stretch", disabled=not pronto_para_simular
)
with col_opt2:
    st.write("")
    st.write("")
    st.write("")
    st.write("")
    st.write("")
    st.write("")
    st.write("")
    st.page_link("views/configuracoes.py", label="Editar Parâmetros de Otimização", icon=":material/settings_b_roll:")

if otimizar and pronto_para_simular:
    modelo_opt = modelos_por_nome.get(valor_persistido("ger_modelo", None))
    if modelo_opt is None:
        st.error("❌ Selecione um modelo de gerador cadastrado antes de otimizar.")
        st.stop()
    modelo_inv_opt = modelos_inversor_por_nome.get(valor_persistido("fv_modelo", None))
    if modelo_inv_opt is None:
        st.error("❌ Selecione um modelo de inversor cadastrado antes de otimizar.")
        st.stop()
    modelo_bess_opt = modelos_bess_por_nome.get(valor_persistido("bess_modelo", None))
    if modelo_bess_opt is None:
        st.error("❌ Selecione um modelo de BESS cadastrado antes de otimizar.")
        st.stop()

    with st.spinner("Otimizando..."):
        try:
            solar_provider_opt = NsrdbSolarProvider(
                lat=mapa_lat, lon=mapa_lon, api_key=api_key, email=email
            )

            # 1º: gerador — dimensionamento simples (não é uma busca numérica
            # como FV/BESS abaixo): quantas unidades do modelo escolhido são
            # necessárias para a potência ativa total do parque superar o
            # pico de carga. Todas as máquinas dimensionadas precisam estar
            # em operação para cobrir esse pico, então o mínimo em operação
            # é igual ao total.
            carga_pico_kw = float(carga_kw.max())
            nr_necessario = max(1, int(np.ceil(carga_pico_kw / modelo_opt.pot_continua_kw)))

            generator_config_opt = generator_config_from_modelo(
                modelo_opt,
                nr_maquinas=nr_necessario,
                nr_min_maquinas=nr_necessario,
                modo=valor_persistido("ger_modo", "ON/OFF"),
            )
            economic_config_opt = EconomicConfig(
                custo_fv_rs_kwp=custo_fv_otimizacao,
                custo_bateria_rs_kwh=custo_bess_otimizacao,
                preco_diesel_rs_litro=preco_diesel_otimizacao,
                tma_am=tma_otimizacao,
            )

            # 2º: FV, 3º: BESS — nessa ordem dentro de otimizar_sistema_completo,
            # já com o parque de geradores acima fixo.
            resultado_otimizacao = otimizar_sistema_completo(
                carga_kw=carga_kw,
                solar_provider=solar_provider_opt,
                generator_config=generator_config_opt,
                economic_config=economic_config_opt,
                dispatch_strategy=dispatch_strategy_para_acoplamento(modelo_bess_opt.acoplamento),
                ilr=float(st.session_state.get("fv_ilr", 1.4)),
                c_rate=modelo_bess_opt.c_rate,
                dod=float(st.session_state.get("bess_dod", 90)) / 100.0,
                eficiencia_rt=modelo_bess_opt.eficiencia_rt,
                degradacao_capacidade_am_ano=degradacao_bess_otimizacao,
                metrica=metrica_otimizacao,
            )
        except NsrdbApiError as e:
            st.error(f"❌ Erro ao consultar a API NSRDB: {e}")
            st.stop()

    # A potência do FV e a capacidade do BESS ótimas (contínuas) são
    # arredondadas para cima até o múltiplo inteiro da potência/capacidade
    # nominal do modelo escolhido — uma usina/banco de baterias real é
    # montado com N unidades discretas de catálogo, não um valor arbitrário.
    unidades_fv = modelo_inv_opt.unidades_para(resultado_otimizacao.solar_config_otimo.pot_inv_kw)
    pot_inv_final_kw = modelo_inv_opt.potencia_final_kw(resultado_otimizacao.solar_config_otimo.pot_inv_kw)
    unidades_bess = modelo_bess_opt.unidades_para(resultado_otimizacao.battery_config_otimo.capacidade_kwh)
    capacidade_final_kwh = modelo_bess_opt.capacidade_final_kwh(resultado_otimizacao.battery_config_otimo.capacidade_kwh)

    # Preenche os campos manuais abaixo com o resultado ótimo.
    forcar_valor("ger_nr", nr_necessario)
    forcar_valor("ger_nr_min", nr_necessario)
    forcar_valor("fv_pot_inv", round(pot_inv_final_kw, 1))
    forcar_valor("bess_capacidade", round(capacidade_final_kwh, 1))
    # Guarda também o valor ótimo contínuo (antes de arredondar para o
    # múltiplo do catálogo), só para exibição — não é a chave de um widget.
    persistir("fv_pot_inv_calculado", round(resultado_otimizacao.solar_config_otimo.pot_inv_kw, 1))
    persistir("bess_capacidade_calculada", round(resultado_otimizacao.battery_config_otimo.capacidade_kwh, 1))

    st.success(
        f"✅ Otimização concluída ({resultado_otimizacao.etapa_fv.n_avaliacoes + resultado_otimizacao.etapa_bess.n_avaliacoes} "
        f"avaliações)! Nº de Geradores: **{nr_necessario}** | "
        f"FV: **{unidades_fv}× {formatar_numero(modelo_inv_opt.pot_nominal_kw, 0)} kW = {formatar_numero(pot_inv_final_kw, 0)} kW** | "
        f"BESS: **{unidades_bess}× {formatar_numero(modelo_bess_opt.capacidade_nominal_kwh, 0)} kWh = {formatar_numero(capacidade_final_kwh, 0)} kWh** | "
        f"{metrica_otimizacao}: **{formatar_numero(resultado_otimizacao.etapa_bess.valor_metrica, 2)}**"
    )
    st.rerun()

st.divider()

# --- 2. CONFIGURAÇÃO DO SISTEMA ---
st.markdown("#### :primary[:material/handyman:] Configuração do Sistema")

col_ger, col_fv, col_bess = st.columns(3)

with col_ger:
    st.markdown(":material/oil_barrel:  **Gerador Diesel**")

    _nomes_modelos = list(modelos_por_nome.keys())
    if not _nomes_modelos:
        st.warning("⚠️ Nenhum modelo de gerador cadastrado.")
        st.page_link("views/configuracoes.py", label="Cadastrar em Configurações", icon=":material/settings_b_roll:")
        modelo_gerador = None
    else:
        nome_modelo = persistir("ger_modelo", st.selectbox(
            "Modelo do Gerador", _nomes_modelos,
            index=indice_persistido("ger_modelo", _nomes_modelos),
            key="ger_modelo",
            help="Modelos cadastrados em Configurações → Dados do Gerador (Catálogo).",
        ))
        modelo_gerador = modelos_por_nome[nome_modelo]

    nr_maquinas = persistir("ger_nr", st.number_input("Nº de Geradores", min_value=0, value=valor_persistido("ger_nr", 0), step=1, key="ger_nr"))
    nr_min_maquinas = persistir("ger_nr_min", st.number_input(
        "Nº Mínimo em Operação", min_value=0, value=valor_persistido("ger_nr_min", 0), step=1, key="ger_nr_min",
        help="Número mínimo de máquinas que devem permanecer ligadas quando o parque está em operação.",
    ))

    _opcoes_modo = ["ON/OFF", "Sempre ON"]
    modo = persistir("ger_modo", st.selectbox(
        "Modo de Operação", _opcoes_modo,
        index=indice_persistido("ger_modo", _opcoes_modo),
        key="ger_modo",
    ))

    if modelo_gerador is not None:
        st.caption(
            f"Eficiência: **{formatar_numero(modelo_gerador.eficiencia_kwh_por_litro, 2)} kWh/L** | "
            f"Potência mínima: **{formatar_numero(modelo_gerador.pot_minima_kw, 0)} kW** | "
            f"Potência contínua: **{formatar_numero(modelo_gerador.pot_continua_kw, 0)} kW** | "
            f"Potência total: **{formatar_numero(modelo_gerador.pot_continua_kw * nr_maquinas, 0)} kW**"
        )

with col_fv:
    st.markdown(":material/sunny: **Usina FV**")

    _nomes_inversores = list(modelos_inversor_por_nome.keys())
    if not _nomes_inversores:
        st.warning("⚠️ Nenhum modelo de inversor cadastrado.")
        st.page_link("views/configuracoes.py", label="Cadastrar em Configurações", icon=":material/settings_b_roll:")
        modelo_inversor = None
    else:
        nome_modelo_inv = persistir("fv_modelo", st.selectbox(
            "Modelo do Inversor", _nomes_inversores,
            index=indice_persistido("fv_modelo", _nomes_inversores),
            key="fv_modelo",
            help="Modelos cadastrados em Configurações → Catálogo de Inversores.",
        ))
        modelo_inversor = modelos_inversor_por_nome[nome_modelo_inv]

    pot_inv_kw = persistir("fv_pot_inv", st.number_input(
        "Potência do Inversor (kW)", min_value=0.0, value=valor_persistido("fv_pot_inv", 0.0), step=10.0, key="fv_pot_inv"
    ))
    _pot_inv_calculado = valor_persistido("fv_pot_inv_calculado", None)
    if _pot_inv_calculado is not None:
        st.caption(f"Calculado: **{formatar_numero(_pot_inv_calculado, 1)} kW**")

    ilr = persistir("fv_ilr", st.number_input(
        "ILR (DC/AC)", min_value=1.0, value=valor_persistido("fv_ilr", 1.4), step=0.05, key="fv_ilr",
        help="Índice de sobredimensionamento (Inverter Load Ratio): razão entre a potência "
        "de pico do arranjo (kWp) e a potência do inversor (kW).",
    ))

    st.caption(f"Potência Pico: **{formatar_numero(pot_inv_kw * ilr, 0)} kWp**")

with col_bess:
    st.markdown(":material/battery_5_bar: **BESS**")

    _nomes_bess = list(modelos_bess_por_nome.keys())
    if not _nomes_bess:
        st.warning("⚠️ Nenhum modelo de BESS cadastrado.")
        st.page_link("views/configuracoes.py", label="Cadastrar em Configurações", icon=":material/settings_b_roll:")
        modelo_bess = None
    else:
        nome_modelo_bess = persistir("bess_modelo", st.selectbox(
            "Modelo do BESS", _nomes_bess,
            index=indice_persistido("bess_modelo", _nomes_bess),
            key="bess_modelo",
            help="Modelos cadastrados em Configurações → Catálogo de BESS.",
        ))
        modelo_bess = modelos_bess_por_nome[nome_modelo_bess]

    capacidade_kwh = persistir("bess_capacidade", st.number_input(
        "Capacidade (kWh)", min_value=0.0, value=valor_persistido("bess_capacidade", 0.0), step=50.0, key="bess_capacidade"
    ))
    _capacidade_bess_calculada = valor_persistido("bess_capacidade_calculada", None)
    if _capacidade_bess_calculada is not None:
        st.caption(f"Calculado: **{formatar_numero(_capacidade_bess_calculada, 1)} kWh**")

    dod = persistir("bess_dod", st.slider("DoD — Profundidade de Descarga (%)", min_value=10, max_value=100, value=valor_persistido("bess_dod", 90), key="bess_dod")) / 100.0

    # C-rate não é mais um input manual: a capacidade e a potência totais do
    # BESS são sempre múltiplos do mesmo nº de unidades do modelo escolhido,
    # então a razão entre elas (o C-rate) já é fixa pelo catálogo — ver
    # ModeloBess.c_rate.
    c_rate = modelo_bess.c_rate if modelo_bess is not None else None
    eficiencia_rt = modelo_bess.eficiencia_rt if modelo_bess is not None else None

    if modelo_bess is not None:
        _legenda_bess = (
            f"Potência: **{formatar_numero(capacidade_kwh * c_rate, 0)} kW** | "
            f"C-rate: **{formatar_numero(c_rate, 2)}** | "
            f"Eficiência: **{formatar_numero(modelo_bess.eficiencia_pct, 0)}%** | "
            f"Acoplamento: **{modelo_bess.acoplamento}**"
        )
    else:
        _legenda_bess = "Selecione um modelo de BESS para ver a potência e o C-rate derivados."
    st.caption(_legenda_bess)

# Publica o snapshot atual dos widgets a cada rerun desta página (não só ao
# clicar em Simular) — outras páginas (Relatório) leem esta cópia para
# detectar desatualização, já que o Streamlit descarta os valores dos
# widgets acima assim que o usuário navega para outra página.
snapshot_atual_simulacao = snapshot_simulacao(carga_kw, mapa_lat, mapa_lon)
publicar_snapshot_atual("simulacao_widgets_atual", snapshot_atual_simulacao)

col_opt1, col_opt2 = st.columns([1, 2])
with col_opt1:
    st.write("")
    simular = st.button(
    ":material/functions: Cálculo Técnico", type="primary", width="stretch",
    disabled=not pronto_para_simular or modelo_gerador is None or modelo_bess is None,
    )

# --- SIMULAÇÃO E RESULTADOS ---
if simular and pronto_para_simular:
    if modelo_gerador is None:
        st.error("❌ Selecione um modelo de gerador cadastrado antes de simular.")
        st.stop()
    if modelo_bess is None:
        st.error("❌ Selecione um modelo de BESS cadastrado antes de simular.")
        st.stop()

    with st.spinner("Simulando..."):
        try:
            solar_provider = NsrdbSolarProvider(
                lat=mapa_lat,
                lon=mapa_lon,
                api_key=api_key,
                email=email,
            )
            solar_config = SolarConfig(pot_inv_kw=pot_inv_kw, ilr=ilr)
            battery_config = BatteryConfig(
                capacidade_kwh=capacidade_kwh,
                c_rate=c_rate,
                dod=dod,
                eficiencia_rt=eficiencia_rt,
                degradacao_capacidade_am_ano=valor_persistido("cfg_degradacao_bess_soh", 2.0) / 100.0,
            )
            generator_config = generator_config_from_modelo(
                modelo_gerador, nr_maquinas=nr_maquinas, nr_min_maquinas=nr_min_maquinas, modo=modo,
            )

            resultado = simular_ano(
                carga_kw=carga_kw,
                solar_config=solar_config,
                solar_provider=solar_provider,
                battery_config=battery_config,
                generator_config=generator_config,
                dispatch_strategy=dispatch_strategy_para_acoplamento(modelo_bess.acoplamento),
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
    st.session_state["ultima_simulacao_config"] = snapshot_atual_simulacao
    # Guardado à parte (não vem de BatteryConfig) para a seção de resultados abaixo saber, sem
    # ambiguidade e sem depender do widget "Modelo do BESS" atual (que pode já ter mudado), qual
    # acoplamento gerou ESTA simulação — usado só para decidir a legenda de "Energia Solar".
    st.session_state["ultima_bess_acoplamento"] = modelo_bess.acoplamento

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

    st.divider()
  
    st.markdown("#### :primary[:material/analytics:] Resultados da Simulação")

    aviso_se_desatualizado(
        "ultima_simulacao_config",
        snapshot_atual_simulacao,
        "A configuração do sistema foi alterada desde a última "
        "simulação. Os resultados abaixo são da configuração anterior — rode o **Cálculo Técnico** novamente.",
    )

    # "Fração Renovável" (energia de origem solar, direta OU via BESS) é a mesma conta nos dois
    # acoplamentos — ver ``SimulationKPIs.fracao_energia_origem_solar``. Já "Energia Solar" (só a
    # parcela direta, ``energia_solar_utilizada_kwh``) é sempre 0 kWh por construção no
    # acoplamento CC — toda a energia solar passa pelo BESS antes de chegar à carga, e esse campo
    # fica reservado para o financeiro não contar a mesma energia 2x (ver
    # ``engine/dispatch/dc_coupled.py``) — então essa tile troca de fonte quando o acoplamento é
    # CC, em vez de mostrar 0 kWh enganosamente.
    acoplamento_cc = st.session_state.get("ultima_bess_acoplamento") == "CC"

    col_k1, col_k2, col_k3, col_k4, col_k5 = st.columns(5)
    col_k1.metric(
        "Fração Renovável", f"{kpis.fracao_energia_origem_solar * 100:.1f} %",
        help="Fração da carga coberta por energia de origem solar, direta ou via BESS.",
    )
    if acoplamento_cc:
        col_k2.metric(
            "Energia Solar Armazenada", f"{formatar_numero(kpis.energia_solar_armazenada_kwh, 0)} kWh",
            help="Energia solar que efetivamente carregou o BESS no ano. A diferença até \"Energia "
            "Bateria\" ao lado é a perda de round-trip do BESS.",
        )
    else:
        col_k2.metric("Energia Solar", f"{formatar_numero(kpis.energia_solar_utilizada_kwh, 0)} kWh")
    col_k3.metric("Energia Bateria", f"{formatar_numero(kpis.energia_bateria_descarregada_kwh, 0)} kWh")
    col_k4.metric("Energia Gerador", f"{formatar_numero(kpis.energia_gerador_kwh, 0)} kWh")
    col_k5.metric("LOLP (déficit)", f"{kpis.lolp * 100:.2f} %", help="Loss of Load Probability: fração de horas do ano com energia não suprida.")

    if kpis.energia_nao_suprida_kwh > 1e-3:
        st.warning(
            f"⚠️ Sistema subdimensionado: {formatar_numero(kpis.energia_nao_suprida_kwh, 1)} kWh não supridos "
            f"em {kpis.horas_com_deficit} horas do ano."
        )
    if kpis.energia_curtailed_kwh > 1e-3:
        st.info(f"ℹ️ Energia excedente (curtailment/dump): {formatar_numero(kpis.energia_curtailed_kwh, 1)} kWh/ano.")

    dates = pd.date_range(start="2023-01-01", periods=8760, freq="h")

    st.markdown("**Fluxo de Energia (semana de exemplo)**")
    semana_inicio = st.slider(
        "Selecione a semana do ano", 1, 52,
        value=st.session_state.get("semana_fluxo", 3), key="semana_fluxo",
    )
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
        "📥 Baixar Perfil Completo em CSV",
        data=csv,
        file_name="simulacao_tecnica_8760h.csv",
        mime="text/csv",
    )
    
elif not simular:
    st.info("Configure o sistema acima e clique em **Cálculo Técnico** para ver os resultados.")

st.divider()