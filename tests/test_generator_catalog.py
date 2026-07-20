"""Testes unitários do catálogo de geradores (engine/generator_catalog.py)."""
from __future__ import annotations

import pytest

from engine.generator_catalog import ModeloGerador, generator_config_from_modelo


def _modelo(**overrides):
    defaults = dict(nome="Modelo X", pot_nominal_kva=550.0, consumo_l_h=75.0, fp=0.8, pot_min_pct=0.3)
    defaults.update(overrides)
    return ModeloGerador(**defaults)


def test_pot_nominal_kw_e_nominal_kva_vezes_fp():
    modelo = _modelo(pot_nominal_kva=500.0, fp=0.8)
    assert modelo.pot_nominal_kw == pytest.approx(400.0)


def test_pot_prime_kva_e_90_por_cento_da_nominal():
    modelo = _modelo(pot_nominal_kva=500.0)
    assert modelo.pot_prime_kva == pytest.approx(450.0)


def test_pot_prime_kw_e_prime_kva_vezes_fp():
    modelo = _modelo(pot_nominal_kva=500.0, fp=0.8)
    assert modelo.pot_prime_kw == pytest.approx(450.0 * 0.8)


def test_pot_continua_kw_e_56_por_cento_da_nominal_kva():
    modelo = _modelo(pot_nominal_kva=500.0)
    assert modelo.pot_continua_kw == pytest.approx(280.0)


def test_pot_continua_kva_e_continua_kw_dividido_por_fp():
    modelo = _modelo(pot_nominal_kva=500.0, fp=0.8)
    assert modelo.pot_continua_kva == pytest.approx(280.0 / 0.8)


def test_eficiencia_kwh_por_litro_e_continua_kw_sobre_consumo():
    modelo = _modelo(pot_nominal_kva=500.0, consumo_l_h=70.0)
    # pot_continua_kw = 500 * 0.56 = 280
    assert modelo.eficiencia_kwh_por_litro == pytest.approx(280.0 / 70.0)


def test_pot_minima_kw_e_prime_kw_vezes_piso_percentual():
    modelo = _modelo(pot_nominal_kva=500.0, fp=0.8, pot_min_pct=0.3)
    # pot_prime_kva = 450, pot_prime_kw = 450 * 0.8 = 360
    assert modelo.pot_minima_kw == pytest.approx(360.0 * 0.3)


def test_modelo_rejeita_valores_invalidos():
    with pytest.raises(ValueError):
        _modelo(nome="")
    with pytest.raises(ValueError):
        _modelo(pot_nominal_kva=0)
    with pytest.raises(ValueError):
        _modelo(consumo_l_h=0)
    with pytest.raises(ValueError):
        _modelo(fp=0)
    with pytest.raises(ValueError):
        _modelo(pot_min_pct=1.5)


def test_generator_config_from_modelo_usa_potencias_derivadas():
    modelo = _modelo(pot_nominal_kva=500.0, consumo_l_h=70.0, fp=0.8, pot_min_pct=0.3)
    config = generator_config_from_modelo(modelo, nr_maquinas=2, nr_min_maquinas=1, modo="Sempre ON")

    assert config.nr_maquinas == 2
    assert config.nr_min_maquinas == 1
    assert config.modo == "Sempre ON"
    assert config.pot_continua_kw == pytest.approx(modelo.pot_continua_kw)
    assert config.pot_prime_kva == pytest.approx(modelo.pot_prime_kva)
    assert config.fp == pytest.approx(modelo.fp)
    assert config.pot_min_pct == pytest.approx(modelo.pot_min_pct)
    assert config.eficiencia_kwh_por_litro == pytest.approx(modelo.eficiencia_kwh_por_litro)
    assert config.pot_total_kw == pytest.approx(modelo.pot_continua_kw * 2)
