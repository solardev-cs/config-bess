"""Testes unitários do modelo de BESS (engine/battery.py).

Cobrem especificamente o bug corrigido: limite de potência de
carga/descarga derivado do C-rate, que a planilha original não tinha.
"""
from __future__ import annotations

import math

import pytest

from engine.battery import Battery
from engine.models import BatteryConfig


def test_battery_config_deriva_potencia_do_c_rate():
    """C-rate 0,5 (2h) com 250 kWh deve resultar em 125 kW de potência."""
    config = BatteryConfig(capacidade_kwh=250, c_rate=0.5, dod=0.9)
    assert config.potencia_kw == pytest.approx(125.0)
    assert config.soc_min_kwh == pytest.approx(25.0)


def test_battery_config_c_rate_none_e_ilimitado_modo_legado():
    """Sem c_rate definido, a potência é ilimitada (replica o bug original)."""
    config = BatteryConfig(capacidade_kwh=250, c_rate=None)
    assert math.isinf(config.potencia_kw)


def test_battery_charge_respeita_limite_de_potencia():
    """Uma bateria de 125 kW não pode carregar a 500 kW mesmo com energia disponível."""
    config = BatteryConfig(capacidade_kwh=250, c_rate=0.5, dod=0.9, eficiencia_rt=1.0)
    battery = Battery(config, soc_inicial_kwh=25.0)  # SOC no mínimo, muito espaço livre

    result = battery.charge(potencia_disponivel_kw=500.0, dt_h=1.0)

    assert result.potencia_aplicada_kw == pytest.approx(125.0)
    assert result.energia_armazenada_kwh == pytest.approx(125.0)
    assert battery.soc_kwh == pytest.approx(150.0)


def test_battery_discharge_respeita_limite_de_potencia():
    """Uma bateria de 125 kW não pode descarregar 500 kW mesmo com energia disponível."""
    config = BatteryConfig(capacidade_kwh=250, c_rate=0.5, dod=0.9, eficiencia_rt=1.0)
    battery = Battery(config, soc_inicial_kwh=250.0)  # SOC cheio, muita energia disponível

    result = battery.discharge(potencia_requisitada_kw=500.0, dt_h=1.0)

    assert result.potencia_entregue_kw == pytest.approx(125.0)
    assert result.energia_retirada_kwh == pytest.approx(125.0)
    assert battery.soc_kwh == pytest.approx(125.0)


def test_battery_charge_respeita_limite_de_energia_mesmo_com_potencia_disponivel():
    """Perto do teto de capacidade, a carga é limitada mesmo dentro do limite de potência."""
    config = BatteryConfig(capacidade_kwh=250, c_rate=1.0, dod=0.9, eficiencia_rt=1.0)  # 250 kW de potência
    battery = Battery(config, soc_inicial_kwh=240.0)  # só 10 kWh de espaço livre

    result = battery.charge(potencia_disponivel_kw=200.0, dt_h=1.0)

    assert result.potencia_aplicada_kw == pytest.approx(10.0)
    assert battery.soc_kwh == pytest.approx(250.0)


def test_battery_discharge_respeita_soc_minimo():
    """Não pode descarregar abaixo do SOC mínimo (DoD)."""
    config = BatteryConfig(capacidade_kwh=250, c_rate=1.0, dod=0.9, eficiencia_rt=1.0)
    battery = Battery(config, soc_inicial_kwh=30.0)  # SOC min = 25 kWh, só 5 kWh disponíveis

    result = battery.discharge(potencia_requisitada_kw=200.0, dt_h=1.0)

    assert result.potencia_entregue_kw == pytest.approx(5.0)
    assert battery.soc_kwh == pytest.approx(25.0)


def test_battery_eficiencia_round_trip_reduz_energia_util():
    """Com eficiência round-trip de 90%, carregar e descarregar a mesma energia gera perda líquida."""
    config = BatteryConfig(capacidade_kwh=1000, c_rate=None, dod=1.0, eficiencia_rt=0.9)
    battery = Battery(config, soc_inicial_kwh=0.0)

    charge_result = battery.charge(potencia_disponivel_kw=100.0, dt_h=1.0)
    # Eficiência unidirecional = sqrt(0.9) ~ 0.9487
    assert charge_result.energia_armazenada_kwh == pytest.approx(100 * (0.9**0.5), rel=1e-6)

    soc_apos_carga = battery.soc_kwh
    discharge_result = battery.discharge(potencia_requisitada_kw=1000.0, dt_h=1.0)

    # A energia total entregue deve ser MENOR que a energia armazenada
    # (perda round-trip), e o round-trip completo deve ser ~90%.
    assert discharge_result.potencia_entregue_kw < charge_result.energia_armazenada_kwh
    round_trip_eff = discharge_result.potencia_entregue_kw / 100.0
    assert round_trip_eff == pytest.approx(0.9, rel=1e-6)
    assert battery.soc_kwh == pytest.approx(0.0, abs=1e-6)


def test_battery_reset_volta_ao_soc_minimo_por_padrao():
    config = BatteryConfig(capacidade_kwh=250, c_rate=0.5, dod=0.9)
    battery = Battery(config, soc_inicial_kwh=200.0)
    battery.reset()
    assert battery.soc_kwh == pytest.approx(config.soc_min_kwh)


@pytest.mark.parametrize("capacidade,c_rate,esperado_kw", [
    (250, 0.5, 125.0),
    (1000, 1.0, 1000.0),
    (500, 0.25, 125.0),
])
def test_c_rate_para_diferentes_capacidades(capacidade, c_rate, esperado_kw):
    config = BatteryConfig(capacidade_kwh=capacidade, c_rate=c_rate)
    assert config.potencia_kw == pytest.approx(esperado_kw)


def test_desfazer_descarga_devolve_a_energia_ao_soc():
    """Desfazer uma descarga é o exato inverso de ``discharge`` (mesma eficiência)."""
    config = BatteryConfig(capacidade_kwh=250, c_rate=None, dod=0.9, eficiencia_rt=0.81)  # 0,9 por sentido
    battery = Battery(config, soc_inicial_kwh=200.0)

    battery.discharge(90.0)  # tira 90 / 0,9 = 100 kWh do pack
    assert battery.soc_kwh == pytest.approx(100.0)

    battery.desfazer_descarga(45.0)  # devolve 45 / 0,9 = 50 kWh
    assert battery.soc_kwh == pytest.approx(150.0)


def test_desfazer_descarga_nunca_passa_da_capacidade():
    config = BatteryConfig(capacidade_kwh=250, c_rate=None, dod=0.9)
    battery = Battery(config, soc_inicial_kwh=240.0)
    battery.desfazer_descarga(500.0)
    assert battery.soc_kwh == pytest.approx(250.0)
