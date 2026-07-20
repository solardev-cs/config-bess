"""Testes unitários do catálogo de inversores (engine/inverter_catalog.py)."""
from __future__ import annotations

import pytest

from engine.inverter_catalog import ModeloInversor


def test_modelo_rejeita_valores_invalidos():
    with pytest.raises(ValueError):
        ModeloInversor(nome="", pot_nominal_kw=100.0)
    with pytest.raises(ValueError):
        ModeloInversor(nome="X", pot_nominal_kw=0.0)
    with pytest.raises(ValueError):
        ModeloInversor(nome="X", pot_nominal_kw=-10.0)


def test_unidades_para_arredonda_para_cima():
    modelo = ModeloInversor(nome="Inversor 100kW", pot_nominal_kw=100.0)
    assert modelo.unidades_para(250.0) == 3
    assert modelo.unidades_para(300.0) == 3
    assert modelo.unidades_para(301.0) == 4


def test_unidades_para_minimo_uma_unidade():
    modelo = ModeloInversor(nome="Inversor 100kW", pot_nominal_kw=100.0)
    assert modelo.unidades_para(0.0) == 1
    assert modelo.unidades_para(-5.0) == 1


def test_potencia_final_kw_e_multiplo_inteiro_do_nominal():
    modelo = ModeloInversor(nome="Inversor 100kW", pot_nominal_kw=100.0)
    assert modelo.potencia_final_kw(250.0) == pytest.approx(300.0)
    assert modelo.potencia_final_kw(100.0) == pytest.approx(100.0)
