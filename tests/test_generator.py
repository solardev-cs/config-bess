"""Testes unitários do modelo do gerador (engine/generator.py).

Cobrem especificamente o bug corrigido: clamp de potência máxima total do
parque, que a planilha original não fazia hora a hora.
"""
from __future__ import annotations

import pytest

from engine.generator import Generator
from engine.models import GeneratorConfig


def _config(**overrides):
    defaults = dict(
        nr_maquinas=2,
        nr_min_maquinas=2,
        pot_continua_kw=315,
        pot_prime_kva=500,
        fp=0.8,
        pot_min_pct=0.0,
        modo="ON/OFF",
    )
    defaults.update(overrides)
    return GeneratorConfig(**defaults)


def test_pot_total_kw_e_continua_vezes_numero_de_maquinas():
    config = _config()
    assert config.pot_total_kw == pytest.approx(630.0)


def test_generator_dispatch_nunca_ultrapassa_potencia_total():
    """Bug corrigido: déficit maior que a capacidade do parque deve ser clampado."""
    config = _config()
    generator = Generator(config)

    result = generator.dispatch(deficit_kw=1000.0)  # > 630 kW de capacidade total

    assert result.potencia_kw == pytest.approx(630.0)
    assert result.ultrapassou_limite is True


def test_generator_dispatch_dentro_do_limite_nao_marca_ultrapassagem():
    config = _config()
    generator = Generator(config)

    result = generator.dispatch(deficit_kw=400.0)

    assert result.potencia_kw == pytest.approx(400.0)
    assert result.ultrapassou_limite is False


def test_generator_on_off_desliga_sem_deficit():
    config = _config()
    generator = Generator(config)

    result = generator.dispatch(deficit_kw=-50.0)

    assert result.potencia_kw == pytest.approx(0.0)


def test_generator_on_off_respeita_piso_minimo():
    config = _config(pot_min_pct=0.5)  # piso = nr_min_maquinas * pot_prime_kw * 0.5
    generator = Generator(config)
    piso_esperado = config.pot_minima_kw

    result = generator.dispatch(deficit_kw=1.0)  # déficit pequeno, menor que o piso

    assert result.potencia_kw == pytest.approx(piso_esperado)


def test_generator_sempre_on_opera_mesmo_sem_deficit_se_ha_carga():
    config = _config(modo="Sempre ON", pot_min_pct=0.3)
    generator = Generator(config)
    piso_esperado = config.pot_minima_kw

    result = generator.dispatch(deficit_kw=-100.0, carga_kw=500.0)

    assert result.potencia_kw == pytest.approx(piso_esperado)


def test_generator_sempre_on_desliga_sem_carga():
    config = _config(modo="Sempre ON", pot_min_pct=0.3)
    generator = Generator(config)

    result = generator.dispatch(deficit_kw=-100.0, carga_kw=0.0)

    assert result.potencia_kw == pytest.approx(0.0)


def test_generator_zero_maquinas_nao_despacha():
    config = _config(nr_maquinas=0, nr_min_maquinas=0)
    generator = Generator(config)

    result = generator.dispatch(deficit_kw=500.0)

    assert result.potencia_kw == pytest.approx(0.0)
    assert result.consumo_litros == pytest.approx(0.0)


def test_generator_consumo_litros_proporcional_a_eficiencia():
    config = _config(eficiencia_kwh_por_litro=4.0)
    generator = Generator(config)

    result = generator.dispatch(deficit_kw=200.0)

    assert result.consumo_litros == pytest.approx(50.0)
