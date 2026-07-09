"""Testes unitários do cálculo de geração de potência FV (engine/solar/pv_generation.py)."""
from __future__ import annotations

import numpy as np
import pytest

from engine.models import SolarConfig
from engine.solar.pv_generation import gerar_potencia_fv


def test_gerar_potencia_fv_shape_correto():
    fracao = np.linspace(0, 1, 8760)
    config = SolarConfig(pot_inv_kw=800, ilr=1.4)
    resultado = gerar_potencia_fv(fracao, config, perdas_sistema_pct=0.0)
    assert resultado.shape == (8760,)


def test_gerar_potencia_fv_pico_sem_perdas_igual_a_pot_pico_kwp():
    fracao = np.ones(8760)
    config = SolarConfig(pot_inv_kw=800, ilr=1.4)  # pot_pico_kwp = 1120
    resultado = gerar_potencia_fv(fracao, config, perdas_sistema_pct=0.0)
    assert np.allclose(resultado, 1120.0)


def test_gerar_potencia_fv_fracao_zero_resulta_potencia_zero():
    fracao = np.zeros(8760)
    config = SolarConfig(pot_inv_kw=800, ilr=1.4)
    resultado = gerar_potencia_fv(fracao, config, perdas_sistema_pct=0.14)
    assert np.allclose(resultado, 0.0)


def test_gerar_potencia_fv_aplica_perdas_de_sistema():
    fracao = np.ones(8760)
    config = SolarConfig(pot_inv_kw=800, ilr=1.4)  # pot_pico_kwp = 1120
    resultado = gerar_potencia_fv(fracao, config, perdas_sistema_pct=0.14)
    assert np.allclose(resultado, 1120.0 * 0.86)


def test_gerar_potencia_fv_usa_perdas_padrao_quando_nao_informado():
    fracao = np.ones(8760)
    config = SolarConfig(pot_inv_kw=800, ilr=1.4)
    resultado = gerar_potencia_fv(fracao, config)
    assert np.allclose(resultado, 1120.0 * 0.86)


def test_gerar_potencia_fv_shape_invalido_levanta_erro():
    fracao = np.ones(100)
    config = SolarConfig(pot_inv_kw=800, ilr=1.4)
    with pytest.raises(ValueError):
        gerar_potencia_fv(fracao, config)


@pytest.mark.parametrize("perdas_invalidas", [-0.1, 1.0, 1.5])
def test_gerar_potencia_fv_perdas_fora_do_intervalo_levanta_erro(perdas_invalidas):
    fracao = np.ones(8760)
    config = SolarConfig(pot_inv_kw=800, ilr=1.4)
    with pytest.raises(ValueError):
        gerar_potencia_fv(fracao, config, perdas_sistema_pct=perdas_invalidas)


def test_gerar_potencia_fv_proporcional_a_fracao():
    fracao = np.array([0.0] * 4380 + [0.5] * 4380)
    config = SolarConfig(pot_inv_kw=100, ilr=1.0)  # pot_pico_kwp = 100
    resultado = gerar_potencia_fv(fracao, config, perdas_sistema_pct=0.0)
    assert np.allclose(resultado[:4380], 0.0)
    assert np.allclose(resultado[4380:], 50.0)
