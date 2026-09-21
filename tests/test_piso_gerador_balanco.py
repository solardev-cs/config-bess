"""Balanço de energia hora a hora com gerador de piso de carga mínima > 0%.

Invariante que vale para os dois acoplamentos e os dois modos do gerador, depois de a sobra
do piso passar a ser absorvida (o gerador atende parte da carga; ver ``load_following.py`` /
``dc_coupled.py``):

    carga = solar_utilizado + bateria_descarga + gerador - piso_sobra + nao_suprido

com todos os termos >= 0 e o SOC sempre entre o mínimo e a capacidade.
"""
from __future__ import annotations

import numpy as np
import pytest

from engine.dispatch.dc_coupled import DcCoupledDispatch
from engine.dispatch.load_following import LoadFollowingDispatch
from engine.models import BatteryConfig, GeneratorConfig, SolarConfig
from engine.simulator import simular_ano


class _SolarSintetico:
    """Perfil solar de sino simples (nasce às 6h, pico ao meio-dia, põe às 18h)."""

    def get_normalized_profile(self) -> np.ndarray:
        hora = np.tile(np.arange(24), 365)
        return np.clip(np.sin((hora - 6) / 12 * np.pi), 0.0, None)


def _carga_irrigacao() -> np.ndarray:
    carga = np.zeros(8760)
    for dia in range(0, 365, 2):
        carga[dia * 24 + 6 : dia * 24 + 16] = 300.0
    return carga


@pytest.mark.parametrize("dispatch", [LoadFollowingDispatch(), DcCoupledDispatch()], ids=["CA", "CC"])
@pytest.mark.parametrize("modo", ["ON/OFF", "Sempre ON"])
def test_balanco_de_energia_com_piso_do_gerador(dispatch, modo):
    bateria = BatteryConfig(capacidade_kwh=723.0, c_rate=125 / 241, dod=0.9, eficiencia_rt=0.90)
    gerador = GeneratorConfig(
        nr_maquinas=1, nr_min_maquinas=1, pot_continua_kw=308.0, pot_prime_kva=495.0, fp=0.8, pot_min_pct=0.30, modo=modo
    )
    resultado = simular_ano(
        _carga_irrigacao(), SolarConfig(pot_inv_kw=600.0, ilr=1.5), _SolarSintetico(), bateria, gerador, dispatch
    )
    df = resultado.df

    balanco = df.solar_utilizado_kw + df.bateria_descarga_kw + df.gerador_kw - df.piso_sobra_kw + df.nao_suprido_kw
    assert np.allclose(balanco, df.carga_kw, atol=1e-6)

    for coluna in ("solar_utilizado_kw", "bateria_descarga_kw", "gerador_kw", "piso_sobra_kw", "nao_suprido_kw", "dump_kw"):
        assert (df[coluna] >= -1e-9).all(), coluna
    assert (df.bateria_soc_kwh >= bateria.soc_min_kwh - 1e-6).all()
    assert (df.bateria_soc_kwh <= bateria.capacidade_kwh + 1e-6).all()
    # com carga (300 kW) bem acima do piso (~119 kW), a sobra do piso é sempre absorvida
    assert df.piso_sobra_kw.max() == pytest.approx(0.0, abs=1e-6)
