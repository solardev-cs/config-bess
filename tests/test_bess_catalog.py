"""Testes unitários do catálogo de BESS (engine/bess_catalog.py)."""
from __future__ import annotations

import pytest

from engine.bess_catalog import ModeloBess


def _modelo(**overrides):
    defaults = dict(nome="BESS 250kWh", capacidade_nominal_kwh=250.0, pot_nominal_kw=125.0, eficiencia_pct=92.0)
    defaults.update(overrides)
    return ModeloBess(**defaults)


def test_modelo_rejeita_valores_invalidos():
    with pytest.raises(ValueError):
        _modelo(nome="")
    with pytest.raises(ValueError):
        _modelo(capacidade_nominal_kwh=0.0)
    with pytest.raises(ValueError):
        _modelo(pot_nominal_kw=0.0)
    with pytest.raises(ValueError):
        _modelo(eficiencia_pct=0.0)
    with pytest.raises(ValueError):
        _modelo(eficiencia_pct=101.0)


def test_eficiencia_rt_e_fracao_do_percentual():
    modelo = _modelo(eficiencia_pct=92.0)
    assert modelo.eficiencia_rt == pytest.approx(0.92)


def test_c_rate_e_potencia_nominal_sobre_capacidade_nominal():
    modelo = _modelo(capacidade_nominal_kwh=250.0, pot_nominal_kw=125.0)
    assert modelo.c_rate == pytest.approx(0.5)


def test_c_rate_independe_do_numero_de_unidades():
    """A razão potência/capacidade é a mesma do modelo, não importa quantas
    unidades forem instaladas (ambas escalam pelo mesmo N)."""
    modelo = _modelo(capacidade_nominal_kwh=250.0, pot_nominal_kw=125.0)
    n = 4
    assert (modelo.pot_nominal_kw * n) / (modelo.capacidade_nominal_kwh * n) == pytest.approx(modelo.c_rate)


def test_unidades_para_arredonda_para_cima():
    modelo = _modelo(capacidade_nominal_kwh=250.0)
    assert modelo.unidades_para(600.0) == 3
    assert modelo.unidades_para(750.0) == 3
    assert modelo.unidades_para(751.0) == 4


def test_unidades_para_minimo_uma_unidade():
    modelo = _modelo(capacidade_nominal_kwh=250.0)
    assert modelo.unidades_para(0.0) == 1


def test_capacidade_final_kwh_e_multiplo_inteiro_do_nominal():
    modelo = _modelo(capacidade_nominal_kwh=250.0)
    assert modelo.capacidade_final_kwh(600.0) == pytest.approx(750.0)
    assert modelo.capacidade_final_kwh(250.0) == pytest.approx(250.0)
