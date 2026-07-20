"""Testes unitários do módulo de custos (engine/costs.py)."""
from __future__ import annotations

import pytest

from engine.costs import (
    calcular_capex,
    calcular_financiamento,
    calcular_parcela_price,
    calcular_tabela_amortizacao,
    converter_kwh_para_litros,
    custo_geracao_diesel_rs_kwh,
)
from engine.models import BatteryConfig, EconomicConfig, GeneratorConfig, SolarConfig


def test_calcular_capex_soma_fv_e_bess():
    solar_config = SolarConfig(pot_inv_kw=800, ilr=1.4)  # pot_pico_kwp = 1120
    battery_config = BatteryConfig(capacidade_kwh=1000, c_rate=0.5)
    economic_config = EconomicConfig(custo_fv_rs_kwp=6500, custo_bateria_rs_kwh=2000)

    capex = calcular_capex(solar_config, battery_config, economic_config)

    assert capex.capex_fv_rs == pytest.approx(1120 * 6500)
    assert capex.capex_bess_rs == pytest.approx(1000 * 2000)
    assert capex.capex_total_rs == pytest.approx(1120 * 6500 + 1000 * 2000)


def test_custo_geracao_diesel_ano1_sem_inflacao():
    generator_config = GeneratorConfig(
        nr_maquinas=2, nr_min_maquinas=2, pot_continua_kw=315, pot_prime_kva=500, eficiencia_kwh_por_litro=4.0
    )
    economic_config = EconomicConfig(preco_diesel_rs_litro=7.0, inflacao_diesel_am=0.05)

    custo = custo_geracao_diesel_rs_kwh(generator_config, economic_config, ano=1)

    assert custo == pytest.approx(7.0 / 4.0)


def test_custo_geracao_diesel_composto_ao_longo_dos_anos():
    """Corrige o bug da planilha original: a inflação deve ser composta
    (elevada à potência do ano), não aplicada como fator fixo repetido.
    """
    generator_config = GeneratorConfig(
        nr_maquinas=2, nr_min_maquinas=2, pot_continua_kw=315, pot_prime_kva=500, eficiencia_kwh_por_litro=4.0
    )
    economic_config = EconomicConfig(preco_diesel_rs_litro=7.0, inflacao_diesel_am=0.05)

    custo_ano1 = custo_geracao_diesel_rs_kwh(generator_config, economic_config, ano=1)
    custo_ano2 = custo_geracao_diesel_rs_kwh(generator_config, economic_config, ano=2)
    custo_ano10 = custo_geracao_diesel_rs_kwh(generator_config, economic_config, ano=10)

    assert custo_ano2 == pytest.approx(custo_ano1 * 1.05)
    assert custo_ano10 == pytest.approx(custo_ano1 * (1.05**9))


def test_calcular_financiamento_recurso_proprio():
    economic_config = EconomicConfig(tipo_pagamento="RECURSO PRÓPRIO")
    resultado = calcular_financiamento(100_000, economic_config)

    assert resultado.valor_financiado_rs == pytest.approx(0.0)
    assert resultado.valor_entrada_rs == pytest.approx(100_000)


def test_calcular_financiamento_com_financiamento_parcial():
    economic_config = EconomicConfig(tipo_pagamento="FINANCIAMENTO", pct_financiado=0.7)
    resultado = calcular_financiamento(100_000, economic_config)

    assert resultado.valor_financiado_rs == pytest.approx(70_000)
    assert resultado.valor_entrada_rs == pytest.approx(30_000)


def test_calcular_parcela_price_sem_carencia():
    parcela = calcular_parcela_price(valor_financiado_rs=100_000, taxa_juros_am=0.10, prazo_anos=5, carencia_anos=0)
    # PMT conhecido: 100000 * (0.10*1.1^5)/(1.1^5-1) ~= 26379.75
    assert parcela == pytest.approx(26379.75, rel=1e-3)


def test_calcular_tabela_amortizacao_sac_soma_amortizacao_total():
    economic_config = EconomicConfig(
        tipo_financiamento="SAC", prazo_anos=5, carencia_anos=0, taxa_juros_am=0.10
    )
    linhas = calcular_tabela_amortizacao(100_000, economic_config)

    assert len(linhas) == 5
    soma_amortizacao = sum(l.amortizacao_rs for l in linhas)
    assert soma_amortizacao == pytest.approx(100_000)
    assert linhas[-1].saldo_devedor_rs == pytest.approx(0.0, abs=1e-6)
    # SAC: amortização constante
    assert linhas[0].amortizacao_rs == pytest.approx(linhas[1].amortizacao_rs)


def test_calcular_tabela_amortizacao_price_parcela_constante():
    economic_config = EconomicConfig(
        tipo_financiamento="PRICE", prazo_anos=5, carencia_anos=0, taxa_juros_am=0.10
    )
    linhas = calcular_tabela_amortizacao(100_000, economic_config)

    assert len(linhas) == 5
    parcelas = [l.parcela_rs for l in linhas]
    assert all(p == pytest.approx(parcelas[0]) for p in parcelas)
    assert linhas[-1].saldo_devedor_rs == pytest.approx(0.0, abs=1e-6)


def test_calcular_tabela_amortizacao_respeita_carencia():
    economic_config = EconomicConfig(
        tipo_financiamento="SAC", prazo_anos=5, carencia_anos=2, taxa_juros_am=0.10
    )
    linhas = calcular_tabela_amortizacao(100_000, economic_config)

    # Durante a carência (anos 1 e 2), não há amortização, só juros.
    assert linhas[0].amortizacao_rs == pytest.approx(0.0)
    assert linhas[1].amortizacao_rs == pytest.approx(0.0)
    assert linhas[0].parcela_rs == pytest.approx(linhas[0].juros_rs)
    # A amortização ocorre nos 3 anos restantes.
    assert linhas[2].amortizacao_rs > 0
    assert linhas[-1].saldo_devedor_rs == pytest.approx(0.0, abs=1e-6)


def test_calcular_tabela_amortizacao_vazia_sem_financiamento():
    economic_config = EconomicConfig()
    linhas = calcular_tabela_amortizacao(0.0, economic_config)
    assert linhas == []


def test_converter_kwh_para_litros():
    generator_config = GeneratorConfig(
        nr_maquinas=2, nr_min_maquinas=2, pot_continua_kw=315, pot_prime_kva=500, eficiencia_kwh_por_litro=4.0
    )
    assert converter_kwh_para_litros(400.0, generator_config) == pytest.approx(100.0)


def test_converter_kwh_para_litros_eficiencia_zero_retorna_zero():
    generator_config = GeneratorConfig(
        nr_maquinas=2, nr_min_maquinas=2, pot_continua_kw=315, pot_prime_kva=500, eficiencia_kwh_por_litro=0.0
    )
    assert converter_kwh_para_litros(400.0, generator_config) == pytest.approx(0.0)
