"""Testes unitários do módulo financeiro (engine/financial.py)."""
from __future__ import annotations

import pytest

from engine.financial import calcular_fluxo_de_caixa
from engine.models import BatteryConfig, EconomicConfig, GeneratorConfig, SimulationKPIs, SolarConfig


def _kpis(energia_solar=500_000, energia_bateria=100_000, energia_gerador=300_000, energia_carga=900_000):
    return SimulationKPIs(
        energia_carga_total_kwh=energia_carga,
        energia_solar_utilizada_kwh=energia_solar,
        energia_bateria_descarregada_kwh=energia_bateria,
        energia_gerador_kwh=energia_gerador,
        energia_nao_suprida_kwh=0.0,
        energia_curtailed_kwh=0.0,
        horas_com_deficit=0,
    )


def _configs(**overrides):
    solar_config = SolarConfig(pot_inv_kw=800, ilr=1.4)
    battery_config = BatteryConfig(capacidade_kwh=1000, c_rate=0.5)
    generator_config = GeneratorConfig(
        nr_maquinas=2, nr_min_maquinas=2, pot_continua_kw=315, pot_prime_kva=500, eficiencia_kwh_por_litro=4.0
    )
    economic_defaults = dict(
        custo_fv_rs_kwp=6500,
        custo_bateria_rs_kwh=2000,
        preco_diesel_rs_litro=7.0,
        inflacao_diesel_am=0.05,
        tma_am=0.05,
        om_pct_am=0.01,
        tipo_pagamento="RECURSO PRÓPRIO",
        horizonte_anos=25,
        degradacao_fv_am_ano=0.006,
    )
    economic_defaults.update(overrides)
    economic_config = EconomicConfig(**economic_defaults)
    return solar_config, battery_config, generator_config, economic_config


def test_fluxo_de_caixa_tem_horizonte_mais_ano_zero():
    solar_config, battery_config, generator_config, economic_config = _configs(horizonte_anos=25)
    resultado = calcular_fluxo_de_caixa(_kpis(), solar_config, battery_config, generator_config, economic_config)

    assert len(resultado.fluxos) == 26  # ano 0 + 25 anos
    assert resultado.fluxos[0].ano == 0
    assert resultado.fluxos[0].fluxo_caixa_rs < 0  # desembolso inicial


def test_fluxo_de_caixa_ano0_igual_a_menos_capex_sem_financiamento():
    solar_config, battery_config, generator_config, economic_config = _configs(tipo_pagamento="RECURSO PRÓPRIO")
    resultado = calcular_fluxo_de_caixa(_kpis(), solar_config, battery_config, generator_config, economic_config)

    assert resultado.fluxos[0].fluxo_caixa_rs == pytest.approx(-resultado.capex.capex_total_rs)


def test_fluxo_de_caixa_com_financiamento_reduz_desembolso_inicial():
    solar_config, battery_config, generator_config, economic_config = _configs(
        tipo_pagamento="FINANCIAMENTO", pct_financiado=0.7, prazo_anos=5, taxa_juros_am=0.10
    )
    resultado = calcular_fluxo_de_caixa(_kpis(), solar_config, battery_config, generator_config, economic_config)

    entrada_esperada = resultado.capex.capex_total_rs * 0.3
    assert resultado.fluxos[0].fluxo_caixa_rs == pytest.approx(-entrada_esperada)
    # Nos anos com financiamento ativo, deve haver parcela > 0.
    assert resultado.fluxos[1].parcela_financiamento_rs > 0


def test_fluxo_de_caixa_degradacao_fv_reduz_energia_evitada_ao_longo_do_tempo():
    """Com degradação de BESS zerada (default), só a parcela solar degrada."""
    solar_config, battery_config, generator_config, economic_config = _configs(degradacao_fv_am_ano=0.01)
    kpis = _kpis()
    resultado = calcular_fluxo_de_caixa(kpis, solar_config, battery_config, generator_config, economic_config)

    energia_ano1 = resultado.fluxos[1].energia_evitada_kwh
    energia_ano10 = resultado.fluxos[10].energia_evitada_kwh
    esperado_ano10 = kpis.energia_solar_utilizada_kwh * (0.99**9) + kpis.energia_bateria_descarregada_kwh
    assert energia_ano10 < energia_ano1
    assert energia_ano10 == pytest.approx(esperado_ano10)


def test_fluxo_de_caixa_degradacao_bess_reduz_energia_bateria_ao_longo_do_tempo():
    """A degradação de capacidade/SOH do BESS (BatteryConfig) degrada só a
    parcela de energia evitada atribuída à bateria, independente da
    degradação do FV."""
    solar_config, _, generator_config, economic_config = _configs(degradacao_fv_am_ano=0.0)
    battery_config = BatteryConfig(capacidade_kwh=1000, c_rate=0.5, degradacao_capacidade_am_ano=0.02)
    kpis = _kpis()
    resultado = calcular_fluxo_de_caixa(kpis, solar_config, battery_config, generator_config, economic_config)

    energia_ano1 = resultado.fluxos[1].energia_evitada_kwh
    energia_ano10 = resultado.fluxos[10].energia_evitada_kwh
    esperado_ano10 = kpis.energia_solar_utilizada_kwh + kpis.energia_bateria_descarregada_kwh * (0.98**9)
    assert energia_ano10 < energia_ano1
    assert energia_ano10 == pytest.approx(esperado_ano10)


def test_fluxo_de_caixa_vpl_positivo_para_cenario_favoravel():
    """Cenário com economia de diesel alta e CAPEX moderado deve gerar VPL positivo."""
    solar_config, battery_config, generator_config, economic_config = _configs(
        tma_am=0.05, custo_fv_rs_kwp=1000, custo_bateria_rs_kwh=500
    )
    resultado = calcular_fluxo_de_caixa(
        _kpis(energia_solar=800_000, energia_bateria=200_000),
        solar_config,
        battery_config,
        generator_config,
        economic_config,
    )
    assert resultado.vpl_rs > 0


def test_fluxo_de_caixa_vpl_negativo_para_cenario_desfavoravel():
    """CAPEX muito alto com pouca economia de diesel deve gerar VPL negativo."""
    solar_config, battery_config, generator_config, economic_config = _configs(
        custo_fv_rs_kwp=100_000, custo_bateria_rs_kwh=100_000
    )
    resultado = calcular_fluxo_de_caixa(
        _kpis(energia_solar=1000, energia_bateria=100),
        solar_config,
        battery_config,
        generator_config,
        economic_config,
    )
    assert resultado.vpl_rs < 0


def test_fluxo_de_caixa_tir_none_quando_sempre_negativo():
    solar_config, battery_config, generator_config, economic_config = _configs(
        custo_fv_rs_kwp=1_000_000, custo_bateria_rs_kwh=1_000_000
    )
    resultado = calcular_fluxo_de_caixa(
        _kpis(energia_solar=100, energia_bateria=10), solar_config, battery_config, generator_config, economic_config
    )
    assert resultado.tir is None


def test_fluxo_de_caixa_tir_positiva_para_cenario_favoravel():
    solar_config, battery_config, generator_config, economic_config = _configs(
        custo_fv_rs_kwp=1000, custo_bateria_rs_kwh=500
    )
    resultado = calcular_fluxo_de_caixa(
        _kpis(energia_solar=800_000, energia_bateria=200_000),
        solar_config,
        battery_config,
        generator_config,
        economic_config,
    )
    assert resultado.tir is not None
    assert resultado.tir > 0
    # VPL calculado à taxa da TIR deve ser ~0.
    from engine.financial import _calcular_npv

    fluxos_rs = [f.fluxo_caixa_rs for f in resultado.fluxos]
    assert _calcular_npv(resultado.tir, fluxos_rs) == pytest.approx(0.0, abs=1.0)


def test_fluxo_de_caixa_lcoe_positivo():
    solar_config, battery_config, generator_config, economic_config = _configs()
    resultado = calcular_fluxo_de_caixa(_kpis(), solar_config, battery_config, generator_config, economic_config)
    assert resultado.lcoe_rs_kwh > 0


def test_fluxo_de_caixa_payback_dentro_do_horizonte():
    solar_config, battery_config, generator_config, economic_config = _configs(
        custo_fv_rs_kwp=500, custo_bateria_rs_kwh=200
    )
    resultado = calcular_fluxo_de_caixa(
        _kpis(energia_solar=800_000, energia_bateria=200_000),
        solar_config,
        battery_config,
        generator_config,
        economic_config,
    )
    assert resultado.payback_anos is not None
    assert 0 < resultado.payback_anos <= economic_config.horizonte_anos


def test_fluxo_de_caixa_payback_none_quando_nunca_paga():
    solar_config, battery_config, generator_config, economic_config = _configs(
        custo_fv_rs_kwp=1_000_000, custo_bateria_rs_kwh=1_000_000
    )
    resultado = calcular_fluxo_de_caixa(
        _kpis(energia_solar=100, energia_bateria=10), solar_config, battery_config, generator_config, economic_config
    )
    assert resultado.payback_anos is None


def test_fluxo_de_caixa_economia_em_sacas():
    solar_config, battery_config, generator_config, economic_config = _configs(economia_por_saca_rs=120.0)
    resultado = calcular_fluxo_de_caixa(_kpis(), solar_config, battery_config, generator_config, economic_config)
    assert resultado.economia_em_sacas_ano1 == pytest.approx(
        resultado.economia_diesel_ano1_rs / 120.0
    )
