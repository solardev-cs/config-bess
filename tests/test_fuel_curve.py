"""Curva de consumo de diesel: interpolação, escala por modelo, gerador, simulador e financeiro."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from engine.dispatch.load_following import LoadFollowingDispatch
from engine.financial import calcular_fluxo_de_caixa
from engine.fuel_curve import CURVA_CONSUMO_REFERENCIA, CurvaConsumo
from engine.generator import Generator
from engine.generator_catalog import ModeloGerador, generator_config_from_modelo
from engine.models import BatteryConfig, EconomicConfig, SimulationKPIs, SolarConfig
from engine.simulator import consumo_diesel_cenario_base, simular_ano


def _modelo(**overrides) -> ModeloGerador:
    defaults = dict(nome="Slim 550", pot_nominal_kva=550.0, consumo_l_h=77.0, fp=0.8, pot_min_pct=0.0)
    defaults.update(overrides)
    return ModeloGerador(**defaults)


# --- CurvaConsumo -----------------------------------------------------------------------------


def test_curva_referencia_reproduz_pontos_medidos_do_teste():
    c = CURVA_CONSUMO_REFERENCIA
    assert len(c.pot_kw) == 39
    assert c.consumo_l_h_em(0) == pytest.approx(4.3)
    assert c.consumo_l_h_em(207) == pytest.approx(48.2)
    assert c.consumo_l_h_em(409) == pytest.approx(102.6)


def test_curva_interpola_linearmente_entre_pontos():
    curva = CurvaConsumo(pot_kw=(0.0, 100.0), consumo_l_h=(10.0, 30.0))
    assert curva.consumo_l_h_em(50.0) == pytest.approx(20.0)


def test_curva_abaixo_do_primeiro_ponto_vale_o_consumo_em_vazio_e_acima_do_ultimo_prolonga():
    curva = CurvaConsumo(pot_kw=(0.0, 100.0), consumo_l_h=(10.0, 30.0))
    assert curva.consumo_l_h_em(-5.0) == pytest.approx(10.0)
    assert curva.consumo_em_vazio_l_h == pytest.approx(10.0)
    assert curva.consumo_l_h_em(150.0) == pytest.approx(40.0)


def test_curva_valida_entradas():
    with pytest.raises(ValueError):
        CurvaConsumo(pot_kw=(0.0,), consumo_l_h=(1.0,))
    with pytest.raises(ValueError):
        CurvaConsumo(pot_kw=(0.0, 0.0), consumo_l_h=(1.0, 2.0))
    with pytest.raises(ValueError):
        CurvaConsumo(pot_kw=(0.0, 1.0), consumo_l_h=(1.0,))


# --- Escala por modelo ------------------------------------------------------------------------


@pytest.mark.parametrize("kva, consumo", [(550.0, 77.0), (250.0, 38.0), (900.0, 120.0)])
def test_curva_do_modelo_reproduz_consumo_de_catalogo_na_potencia_continua(kva, consumo):
    modelo = _modelo(pot_nominal_kva=kva, consumo_l_h=consumo)
    assert modelo.curva_consumo.consumo_l_h_em(modelo.pot_continua_kw) == pytest.approx(consumo)


def test_curva_do_modelo_escala_potencia_e_mantem_o_formato():
    modelo = _modelo(pot_nominal_kva=275.0, consumo_l_h=38.5)  # metade do modelo de referência
    curva = modelo.curva_consumo
    ref = CURVA_CONSUMO_REFERENCIA
    assert curva.pot_kw[-1] == pytest.approx(ref.pot_kw[-1] / 2)
    fator = curva.consumo_l_h_em(modelo.pot_continua_kw) / ref.consumo_l_h_em(308.0)
    assert curva.consumo_em_vazio_l_h == pytest.approx(ref.consumo_em_vazio_l_h * fator)


def test_generator_config_from_modelo_leva_a_curva():
    modelo = _modelo()
    config = generator_config_from_modelo(modelo, nr_maquinas=1, nr_min_maquinas=1)
    assert config.curva_consumo == modelo.curva_consumo


# --- Generator --------------------------------------------------------------------------------


def _config(modo="ON/OFF", nr=2, nr_min=1, **overrides):
    modelo = _modelo(**overrides)
    return generator_config_from_modelo(modelo, nr_maquinas=nr, nr_min_maquinas=nr_min, modo=modo)


def test_consumo_pela_curva_no_ponto_de_catalogo():
    config = _config()
    resultado = Generator(config).dispatch(deficit_kw=config.pot_continua_kw)
    assert resultado.consumo_litros == pytest.approx(77.0)


def test_carga_baixa_consome_mais_litros_por_kwh_que_carga_alta():
    gerador = Generator(_config())
    baixo = gerador.dispatch(deficit_kw=30.0).consumo_litros / 30.0
    alto = gerador.dispatch(deficit_kw=300.0).consumo_litros / 300.0
    assert baixo > 1.5 * alto


def test_on_off_desligado_nao_consome():
    assert Generator(_config()).dispatch(deficit_kw=-10.0).consumo_litros == 0.0


def test_sempre_on_sem_deficit_consome_o_vazio_com_carga_e_nada_sem_carga():
    config = _config(modo="Sempre ON")
    vazio = config.curva_consumo.consumo_em_vazio_l_h
    assert Generator(config).dispatch(deficit_kw=-50.0, carga_kw=200.0).consumo_litros == pytest.approx(vazio)
    assert Generator(config).dispatch(deficit_kw=-50.0, carga_kw=0.0).consumo_litros == 0.0


def test_escalonamento_liga_mais_maquinas_acima_da_potencia_continua():
    config = _config(nr=3, nr_min=1)
    gerador = Generator(config)
    pc = config.pot_continua_kw
    assert gerador._maquinas_ativas(0.5 * pc) == 1
    assert gerador._maquinas_ativas(pc) == 1
    assert gerador._maquinas_ativas(1.01 * pc) == 2
    assert gerador._maquinas_ativas(2.5 * pc) == 3


def test_nr_min_maior_forca_mais_maquinas_e_mais_consumo_em_carga_baixa():
    p = 50.0
    uma = Generator(_config(nr=2, nr_min=1)).dispatch(deficit_kw=p).consumo_litros
    duas = Generator(_config(nr=2, nr_min=2)).dispatch(deficit_kw=p).consumo_litros
    assert duas > uma


def test_sem_curva_o_consumo_continua_linear_pela_eficiencia():
    config = replace(_config(), curva_consumo=None, eficiencia_kwh_por_litro=4.0)
    assert Generator(config).dispatch(deficit_kw=200.0).consumo_litros == pytest.approx(50.0)


# --- Simulador: consumo e cenário base --------------------------------------------------------


class _SolarSintetico:
    def get_normalized_profile(self) -> np.ndarray:
        hora = np.tile(np.arange(24), 365)
        return np.clip(np.sin((hora - 6) / 12 * np.pi), 0.0, None)


def _carga() -> np.ndarray:
    carga = np.zeros(8760)
    for dia in range(0, 365, 2):
        carga[dia * 24 + 6 : dia * 24 + 16] = 200.0
    return carga


def _simular(gerador, pot_inv_kw=400.0, capacidade_kwh=500.0):
    return simular_ano(
        _carga(),
        SolarConfig(pot_inv_kw=pot_inv_kw, ilr=1.5),
        _SolarSintetico(),
        BatteryConfig(capacidade_kwh=capacidade_kwh, c_rate=0.5, dod=0.9, eficiencia_rt=0.9),
        gerador,
        LoadFollowingDispatch(),
    )


def test_kpi_de_consumo_e_a_soma_horaria():
    resultado = _simular(_config(nr=1, nr_min=1))
    assert resultado.kpis.consumo_diesel_litros == pytest.approx(resultado.df["consumo_diesel_l"].sum())
    assert resultado.kpis.consumo_diesel_litros > 0


def test_sem_fv_e_bess_o_consumo_do_sistema_e_igual_ao_do_cenario_base():
    resultado = _simular(_config(nr=1, nr_min=1), pot_inv_kw=0.0, capacidade_kwh=0.0)
    assert resultado.kpis.consumo_diesel_base_litros == pytest.approx(resultado.kpis.consumo_diesel_litros)


def test_fv_e_bess_reduzem_o_consumo_frente_ao_cenario_base():
    kpis = _simular(_config(nr=1, nr_min=1)).kpis
    assert kpis.consumo_diesel_litros < kpis.consumo_diesel_base_litros


def test_cenario_base_ignora_nr_min_do_sistema():
    """O FV/BESS não recebe crédito por consertar máquinas demais ligadas."""
    base_1 = _simular(_config(nr=2, nr_min=1)).kpis.consumo_diesel_base_litros
    base_2 = _simular(_config(nr=2, nr_min=2)).kpis.consumo_diesel_base_litros
    assert base_1 == pytest.approx(base_2)


def test_parque_pequeno_nao_limita_o_cenario_base():
    """Parque menor que o pico: o cenário base ainda atende a carga inteira (parque pelo pico)."""
    carga = np.zeros(8760)
    carga[:1000] = 450.0  # pico > potência contínua de 1 máquina (308 kW)
    pequeno = consumo_diesel_cenario_base(carga, _config(nr=1, nr_min=1))
    adequado = consumo_diesel_cenario_base(carga, _config(nr=2, nr_min=1))
    assert pequeno == pytest.approx(adequado)
    # 1000 h x 450 kW, atendidos por 2 máquinas a 225 kW cada (sem clamp em 308 kW)
    assert pequeno == pytest.approx(1000 * 2 * _config().curva_consumo.consumo_l_h_em(225.0))


def test_cenario_base_atende_so_a_energia_que_o_sistema_atendeu():
    carga = _carga()
    config = _config(nr=1, nr_min=1)
    tudo = consumo_diesel_cenario_base(carga, config)
    nada = consumo_diesel_cenario_base(carga, config, nao_suprido_kw=carga)
    metade = consumo_diesel_cenario_base(carga, config, nao_suprido_kw=carga / 2)
    assert nada == 0.0
    assert 0.0 < metade < tudo


def test_sistema_sem_gerador_e_sem_fv_bess_nao_recebe_credito_de_diesel_evitado():
    """Não atende nada (nao_suprido = carga): o diesel 'evitado' tem que ser zero, não o do base inteiro."""
    resultado = _simular(_config(nr=0, nr_min=0), pot_inv_kw=0.0, capacidade_kwh=0.0)
    assert resultado.kpis.consumo_diesel_litros == 0.0
    assert resultado.kpis.consumo_diesel_base_litros == pytest.approx(0.0)


def test_sistema_sem_gerador_com_fv_bess_recebe_credito_so_do_que_atendeu():
    resultado = _simular(_config(nr=0, nr_min=0))
    kpis = resultado.kpis
    assert kpis.consumo_diesel_litros == 0.0
    assert 0.0 < kpis.consumo_diesel_base_litros < consumo_diesel_cenario_base(_carga(), _config(nr=1, nr_min=1))


def test_sem_curva_nao_ha_cenario_base():
    config = replace(_config(), curva_consumo=None)
    assert consumo_diesel_cenario_base(_carga(), config) is None
    assert _simular(config).kpis.consumo_diesel_base_litros is None


# --- Financeiro -------------------------------------------------------------------------------


def _kpis(base=None, sistema=0.0, solar=100_000.0, bateria=50_000.0):
    return SimulationKPIs(
        energia_carga_total_kwh=400_000.0,
        energia_solar_utilizada_kwh=solar,
        energia_bateria_descarregada_kwh=bateria,
        energia_gerador_kwh=250_000.0,
        energia_nao_suprida_kwh=0.0,
        energia_curtailed_kwh=0.0,
        horas_com_deficit=0,
        consumo_diesel_litros=sistema,
        consumo_diesel_base_litros=base,
    )


def _fluxo(kpis, **eco):
    economic = EconomicConfig(preco_diesel_rs_litro=7.0, inflacao_diesel_am=0.05, degradacao_fv_am_ano=0.0, **eco)
    battery = BatteryConfig(capacidade_kwh=1000.0, c_rate=0.5, degradacao_capacidade_am_ano=0.0)
    return calcular_fluxo_de_caixa(kpis, SolarConfig(pot_inv_kw=100.0), battery, _config(), economic)


def test_economia_com_curva_e_diesel_do_cenario_base_menos_o_do_sistema():
    resultado = _fluxo(_kpis(base=60_000.0, sistema=10_000.0))
    assert resultado.economia_diesel_litros_ano1 == pytest.approx(50_000.0)
    assert resultado.economia_diesel_ano1_rs == pytest.approx(50_000.0 * 7.0)


def test_economia_com_curva_tem_inflacao_do_diesel_composta_e_ignora_eficiencia_nominal():
    resultado = _fluxo(_kpis(base=60_000.0, sistema=10_000.0), horizonte_anos=5)
    ano1, ano3 = resultado.fluxos[1], resultado.fluxos[3]
    assert ano3.economia_diesel_rs == pytest.approx(ano1.economia_diesel_rs * 1.05**2)


def test_economia_com_curva_acompanha_degradacao_na_proporcao_da_energia_evitada():
    economic = EconomicConfig(preco_diesel_rs_litro=7.0, inflacao_diesel_am=0.0, degradacao_fv_am_ano=0.10)
    battery = BatteryConfig(capacidade_kwh=1000.0, c_rate=0.5, degradacao_capacidade_am_ano=0.0)
    resultado = calcular_fluxo_de_caixa(
        _kpis(base=60_000.0, sistema=10_000.0, bateria=0.0), SolarConfig(pot_inv_kw=100.0), battery, _config(), economic
    )
    assert resultado.fluxos[2].economia_diesel_rs == pytest.approx(resultado.fluxos[1].economia_diesel_rs * 0.9)


def test_sem_curva_o_financeiro_segue_o_calculo_legado_por_kwh_evitado():
    config = replace(_config(), curva_consumo=None, eficiencia_kwh_por_litro=4.0)
    economic = EconomicConfig(preco_diesel_rs_litro=7.0, inflacao_diesel_am=0.0)
    battery = BatteryConfig(capacidade_kwh=1000.0, c_rate=0.5)
    resultado = calcular_fluxo_de_caixa(_kpis(), SolarConfig(pot_inv_kw=100.0), battery, config, economic)
    assert resultado.economia_diesel_litros_ano1 == pytest.approx(150_000.0 / 4.0)
    assert resultado.economia_diesel_ano1_rs == pytest.approx(150_000.0 / 4.0 * 7.0)
