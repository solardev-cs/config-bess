"""Testes unitários dos campos computados de ``engine.models.SimulationKPIs``."""
from __future__ import annotations

import pytest

from engine.models import SimulationKPIs


def test_fracao_energia_origem_solar_soma_solar_direto_e_bateria():
    """Acoplamento CA: solar direto e descarga do BESS contam juntos."""
    kpis = SimulationKPIs(
        energia_carga_total_kwh=1000.0,
        energia_solar_utilizada_kwh=600.0,
        energia_bateria_descarregada_kwh=300.0,
        energia_gerador_kwh=100.0,
        energia_nao_suprida_kwh=0.0,
        energia_curtailed_kwh=0.0,
        horas_com_deficit=0,
    )
    assert kpis.fracao_solar == pytest.approx(0.6)  # só a parcela direta
    assert kpis.fracao_energia_origem_solar == pytest.approx(0.9)  # direta + via BESS


def test_fracao_energia_origem_solar_funciona_quando_solar_direto_e_zero():
    """Acoplamento CC: energia_solar_utilizada_kwh é sempre 0.0 por construção
    (ver engine/dispatch/dc_coupled.py), mas a energia entregue pelo BESS ainda
    deve contar como de origem solar na fração combinada."""
    kpis = SimulationKPIs(
        energia_carga_total_kwh=1000.0,
        energia_solar_utilizada_kwh=0.0,
        energia_bateria_descarregada_kwh=850.0,
        energia_gerador_kwh=150.0,
        energia_nao_suprida_kwh=0.0,
        energia_curtailed_kwh=0.0,
        horas_com_deficit=0,
    )
    assert kpis.fracao_solar == pytest.approx(0.0)
    assert kpis.fracao_energia_origem_solar == pytest.approx(0.85)


def test_fracao_energia_origem_solar_com_carga_total_zero():
    kpis = SimulationKPIs(
        energia_carga_total_kwh=0.0,
        energia_solar_utilizada_kwh=0.0,
        energia_bateria_descarregada_kwh=0.0,
        energia_gerador_kwh=0.0,
        energia_nao_suprida_kwh=0.0,
        energia_curtailed_kwh=0.0,
        horas_com_deficit=0,
    )
    assert kpis.fracao_energia_origem_solar == pytest.approx(0.0)
