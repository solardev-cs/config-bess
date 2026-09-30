"""Testes unitários do otimizador de dimensionamento (engine/optimizer.py).

Usa uma carga sintética pequena e cargas/perfis simplificados para manter
os testes rápidos, focando na CORRETUDE da otimização (convergência,
direção correta de maximização/minimização) em vez de replicar cenários
realistas completos (isso já é coberto pelos testes de regressão e pela
validação manual contra a planilha).
"""
from __future__ import annotations

import numpy as np
import pytest

from engine.dispatch.dc_coupled import DcCoupledDispatch
from engine.dispatch.load_following import LoadFollowingDispatch
from engine.models import BatteryConfig, EconomicConfig, GeneratorConfig, SolarConfig
from engine.optimizer import (
    otimizar_capacidade_bess,
    otimizar_potencia_fv,
    otimizar_sistema_completo,
)


class ConstantSolarProvider:
    """Provider sintético: irradiância normalizada em formato de "dia"
    simplificado (metade das horas com sol pleno, metade sem), repetido
    ao longo do ano — suficiente para exercitar a lógica de otimização
    sem depender de rede ou arquivos de TMY reais.
    """

    def get_normalized_profile(self) -> np.ndarray:
        dia = np.array([0.0] * 6 + [1.0] * 12 + [0.0] * 6)  # 24h
        return np.tile(dia, 365)[:8760]


@pytest.fixture
def carga_kw():
    """Carga constante de 100 kW ao longo do ano (8760h)."""
    return np.full(8760, 100.0)


@pytest.fixture
def generator_config():
    return GeneratorConfig(
        nr_maquinas=2, nr_min_maquinas=1, pot_continua_kw=150, pot_prime_kva=200, eficiencia_kwh_por_litro=4.0
    )


@pytest.fixture
def economic_config_favoravel():
    """Cenário com CAPEX baixo e diesel caro: deve favorecer sistemas maiores."""
    return EconomicConfig(
        custo_fv_rs_kwp=500.0,
        custo_bateria_rs_kwh=200.0,
        preco_diesel_rs_litro=10.0,
        tma_am=0.05,
        om_pct_am=0.01,
        horizonte_anos=25,
    )


@pytest.fixture
def economic_config_desfavoravel():
    """Cenário com CAPEX muito alto: deve empurrar o ótimo para perto de zero."""
    return EconomicConfig(
        custo_fv_rs_kwp=1_000_000.0,
        custo_bateria_rs_kwh=1_000_000.0,
        preco_diesel_rs_litro=7.0,
        tma_am=0.05,
        horizonte_anos=25,
    )


def test_otimizar_potencia_fv_converge(carga_kw, generator_config, economic_config_favoravel):
    battery_config = BatteryConfig(capacidade_kwh=0.0, c_rate=0.5)
    resultado = otimizar_potencia_fv(
        carga_kw=carga_kw,
        solar_provider=ConstantSolarProvider(),
        battery_config=battery_config,
        generator_config=generator_config,
        economic_config=economic_config_favoravel,
        dispatch_strategy=LoadFollowingDispatch(),
        metrica="VPL",
    )
    assert resultado.convergiu
    assert resultado.valor_otimo > 0
    assert resultado.n_avaliacoes > 0


def test_otimizar_potencia_fv_capex_alto_empurra_para_zero(carga_kw, generator_config, economic_config_desfavoravel):
    battery_config = BatteryConfig(capacidade_kwh=0.0, c_rate=0.5)
    resultado = otimizar_potencia_fv(
        carga_kw=carga_kw,
        solar_provider=ConstantSolarProvider(),
        battery_config=battery_config,
        generator_config=generator_config,
        economic_config=economic_config_desfavoravel,
        dispatch_strategy=LoadFollowingDispatch(),
        metrica="VPL",
    )
    # Com CAPEX extremo, o ótimo deve estar próximo do limite inferior (zero).
    assert resultado.valor_otimo < carga_kw.max() * 0.1


def test_otimizar_potencia_fv_vpl_no_otimo_e_maior_que_nos_extremos(
    carga_kw, generator_config, economic_config_favoravel
):
    """O VPL no ponto ótimo deve ser >= VPL nos limites do intervalo de busca
    (validação básica de que a otimização de fato melhora o resultado).
    """
    battery_config = BatteryConfig(capacidade_kwh=0.0, c_rate=0.5)
    resultado = otimizar_potencia_fv(
        carga_kw=carga_kw,
        solar_provider=ConstantSolarProvider(),
        battery_config=battery_config,
        generator_config=generator_config,
        economic_config=economic_config_favoravel,
        dispatch_strategy=LoadFollowingDispatch(),
        metrica="VPL",
        pot_inv_max_kw=200.0,
    )

    from engine.financial import calcular_fluxo_de_caixa
    from engine.simulator import simular_ano

    for pot_extrema in (0.0, 200.0):
        solar_config_extrema = SolarConfig(pot_inv_kw=pot_extrema, ilr=1.4)
        sim_extrema = simular_ano(
            carga_kw, solar_config_extrema, ConstantSolarProvider(), battery_config, generator_config, LoadFollowingDispatch()
        )
        fin_extrema = calcular_fluxo_de_caixa(
            sim_extrema.kpis, solar_config_extrema, battery_config, generator_config, economic_config_favoravel
        )
        assert resultado.valor_metrica >= fin_extrema.vpl_rs - 1e-3


def test_otimizar_capacidade_bess_converge(carga_kw, generator_config, economic_config_favoravel):
    solar_config = SolarConfig(pot_inv_kw=100.0, ilr=1.4)
    resultado = otimizar_capacidade_bess(
        carga_kw=carga_kw,
        solar_config=solar_config,
        solar_provider=ConstantSolarProvider(),
        generator_config=generator_config,
        economic_config=economic_config_favoravel,
        dispatch_strategy=LoadFollowingDispatch(),
        c_rate=0.5,
        metrica="VPL",
    )
    assert resultado.convergiu
    assert resultado.valor_otimo >= 0
    assert resultado.n_avaliacoes > 0


def test_otimizar_capacidade_bess_capex_alto_empurra_para_zero(
    carga_kw, generator_config, economic_config_desfavoravel
):
    solar_config = SolarConfig(pot_inv_kw=50.0, ilr=1.4)
    resultado = otimizar_capacidade_bess(
        carga_kw=carga_kw,
        solar_config=solar_config,
        solar_provider=ConstantSolarProvider(),
        generator_config=generator_config,
        economic_config=economic_config_desfavoravel,
        dispatch_strategy=LoadFollowingDispatch(),
        c_rate=0.5,
        metrica="VPL",
    )
    assert resultado.valor_otimo < carga_kw.max() * 0.5


def test_otimizar_sistema_completo_roda_as_duas_etapas(carga_kw, generator_config, economic_config_favoravel):
    resultado = otimizar_sistema_completo(
        carga_kw=carga_kw,
        solar_provider=ConstantSolarProvider(),
        generator_config=generator_config,
        economic_config=economic_config_favoravel,
        dispatch_strategy=LoadFollowingDispatch(),
        metrica="VPL",
    )
    assert resultado.etapa_fv.convergiu
    assert resultado.etapa_bess.convergiu
    assert resultado.solar_config_otimo.pot_inv_kw == pytest.approx(resultado.etapa_fv.valor_otimo)
    assert resultado.battery_config_otimo.capacidade_kwh == pytest.approx(resultado.etapa_bess.valor_otimo)
    # A etapa do BESS deve rodar sobre o FV já otimizado da etapa anterior.
    assert resultado.battery_config_otimo.c_rate == 0.5


def test_otimizar_sistema_completo_metrica_lcoe_minimiza(carga_kw, generator_config, economic_config_favoravel):
    resultado = otimizar_sistema_completo(
        carga_kw=carga_kw,
        solar_provider=ConstantSolarProvider(),
        generator_config=generator_config,
        economic_config=economic_config_favoravel,
        dispatch_strategy=LoadFollowingDispatch(),
        metrica="LCOE",
    )
    assert resultado.etapa_bess.valor_metrica > 0
    assert np.isfinite(resultado.etapa_bess.valor_metrica)


def test_otimizar_lcoe_nao_e_degenerado_perto_de_zero(carga_kw, generator_config, economic_config_favoravel):
    """Regressão: a métrica "LCOE" NÃO deve mais convergir para sistemas
    artificialmente pequenos por causa da invariância de escala da razão
    do LCOE (ver nota em ``engine/optimizer.py``). Com carga constante e
    perfil solar em "bloco" (metade do dia com sol pleno), o ponto de
    saturação físico do FV puro é exatamente ``carga_kw.max()`` — o
    dimensionamento por LCOE deve chegar próximo desse ponto, assim como
    o VPL, em vez de parar perto de zero.
    """
    battery_config = BatteryConfig(capacidade_kwh=0.0, c_rate=0.5)
    resultado = otimizar_potencia_fv(
        carga_kw=carga_kw,
        solar_provider=ConstantSolarProvider(),
        battery_config=battery_config,
        generator_config=generator_config,
        economic_config=economic_config_favoravel,
        dispatch_strategy=LoadFollowingDispatch(),
        metrica="LCOE",
    )
    assert resultado.valor_otimo > carga_kw.max() * 0.8


def test_otimizar_lcoe_capex_alto_empurra_para_zero(carga_kw, generator_config, economic_config_desfavoravel):
    """Em cenário claramente desfavorável, o dimensionamento por LCOE deve
    colapsar para perto de zero, assim como o VPL (o benefício econômico
    não descontado usado como critério de busca também é negativo/decrescente
    em todo o intervalo nesse cenário).
    """
    battery_config = BatteryConfig(capacidade_kwh=0.0, c_rate=0.5)
    resultado = otimizar_potencia_fv(
        carga_kw=carga_kw,
        solar_provider=ConstantSolarProvider(),
        battery_config=battery_config,
        generator_config=generator_config,
        economic_config=economic_config_desfavoravel,
        dispatch_strategy=LoadFollowingDispatch(),
        metrica="LCOE",
    )
    assert resultado.valor_otimo < carga_kw.max() * 0.1


def test_otimizar_sistema_completo_dc_coupled_nao_colapsa_para_zero(
    carga_kw, generator_config, economic_config_favoravel
):
    """Regressão: a busca sequencial padrão (zerar o BESS para isolar o efeito
    do FV, usada para acoplamento CA) torna qualquer FV inútil sob acoplamento
    CC (toda a energia seria curtailed por não haver BESS para repassá-la),
    empurrando FV e BESS para um ótimo degenerado perto de zero mesmo em
    cenários claramente favoráveis a um sistema grande — sintoma real
    reportado: 0,5 kW de FV e 2,1 kWh de BESS onde o acoplamento CA (mesmo
    cenário) produzia ~450 kW / ~600 kWh. ``otimizar_sistema_completo`` deve
    detectar ``DcCoupledDispatch`` e rodar a busca conjunta (2D) em vez da
    busca sequencial.
    """
    resultado = otimizar_sistema_completo(
        carga_kw=carga_kw,
        solar_provider=ConstantSolarProvider(),
        generator_config=generator_config,
        economic_config=economic_config_favoravel,
        dispatch_strategy=DcCoupledDispatch(),
        metrica="VPL",
    )
    assert resultado.etapa_fv.convergiu
    assert resultado.solar_config_otimo.pot_inv_kw > carga_kw.max() * 0.5
    assert resultado.battery_config_otimo.capacidade_kwh > carga_kw.max() * 1.0


def test_otimizar_capacidade_bess_c_rate_none_funciona(carga_kw, generator_config, economic_config_favoravel):
    """Deve funcionar também no modo legado (c_rate=None, sem limite de potência)."""
    solar_config = SolarConfig(pot_inv_kw=100.0, ilr=1.4)
    resultado = otimizar_capacidade_bess(
        carga_kw=carga_kw,
        solar_config=solar_config,
        solar_provider=ConstantSolarProvider(),
        generator_config=generator_config,
        economic_config=economic_config_favoravel,
        dispatch_strategy=LoadFollowingDispatch(),
        c_rate=None,
        metrica="VPL",
    )
    assert resultado.convergiu


def test_otimizar_sem_bess_roda_so_a_etapa_fv_e_zera_o_bess(carga_kw, generator_config, economic_config_favoravel):
    """"Solar + Diesel": BESS com capacidade 0, etapa 2 pulada, FV igual ao da otimização completa."""
    from engine.dispatch.load_following import LoadFollowingDispatch

    kwargs = dict(
        carga_kw=carga_kw, solar_provider=ConstantSolarProvider(), generator_config=generator_config,
        economic_config=economic_config_favoravel, dispatch_strategy=LoadFollowingDispatch(),
    )
    completo = otimizar_sistema_completo(**kwargs)
    sem_bess = otimizar_sistema_completo(**kwargs, otimizar_bess=False)

    assert sem_bess.battery_config_otimo.capacidade_kwh == 0.0
    assert sem_bess.etapa_bess.n_avaliacoes == 0
    assert sem_bess.etapa_bess.valor_otimo == 0.0
    assert sem_bess.solar_config_otimo.pot_inv_kw == pytest.approx(completo.solar_config_otimo.pot_inv_kw)
