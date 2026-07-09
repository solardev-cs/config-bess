"""Otimizador de dimensionamento do sistema FV+BESS.

Substitui o Solver do Excel (GRG não-linear, 1 variável ajustável por vez)
por uma busca em Python via ``scipy.optimize``, usando o próprio motor de
simulação (``simular_ano`` + ``calcular_fluxo_de_caixa``) como função
objetivo. Isso elimina a dependência do Solver do Excel (inexistente fora
do Excel) e é o equivalente direto ao fluxo de trabalho original:

    1. Otimiza a potência do inversor FV (``pot_inv_kw``), com o BESS
       fixo (tipicamente zerado nesta etapa, como na planilha original).
    2. Com o FV já definido, otimiza a capacidade do BESS
       (``capacidade_kwh``), mantendo o C-rate fixo (decisão de projeto:
       o C-rate é um parâmetro de entrada do usuário, não uma variável de
       otimização — ver ``BatteryConfig.c_rate``). A potência do BESS é
       sempre derivada de ``capacidade_kwh * c_rate``.

Métricas de otimização suportadas (mesmas da planilha original,
``Dimensionamento!S29:S33``): "VPL" (maximizar), "TIR" (maximizar),
"LCOE" (minimizar).

Cada avaliação da função objetivo roda uma simulação horária completa de
8760h (~0.1s) mais o cálculo financeiro (~instantâneo após o primeiro
import do scipy) — uma busca em intervalo limitado (``bounded``) com
~20-40 avaliações leva poucos segundos, sem necessidade de paralelismo.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scipy.optimize import minimize_scalar

from engine.dispatch.base import DispatchStrategy
from engine.financial import ResultadoFinanceiro, calcular_fluxo_de_caixa
from engine.models import BatteryConfig, EconomicConfig, GeneratorConfig, SolarConfig
from engine.simulator import SimulationResult, simular_ano
from engine.solar.base import SolarProfileProvider

import numpy as np

Metrica = Literal["VPL", "TIR", "LCOE"]


@dataclass
class ResultadoOtimizacao:
    """Resultado de uma etapa de otimização (FV ou BESS)."""

    valor_otimo: float  # pot_inv_kw ou capacidade_kwh, conforme a etapa
    metrica: Metrica
    valor_metrica: float  # valor da métrica otimizada no ponto ótimo
    simulacao: SimulationResult
    financeiro: ResultadoFinanceiro
    convergiu: bool
    n_avaliacoes: int


def _extrair_metrica(financeiro: ResultadoFinanceiro, metrica: Metrica) -> float | None:
    """Extrai o valor numérico da métrica escolhida do resultado financeiro.

    Returns:
        O valor da métrica, ou ``None`` se indefinida (ex.: TIR sem
        mudança de sinal no fluxo de caixa).
    """
    if metrica == "VPL":
        return financeiro.vpl_rs
    if metrica == "TIR":
        return financeiro.tir
    if metrica == "LCOE":
        return financeiro.lcoe_rs_kwh
    raise ValueError(f"Métrica desconhecida: {metrica}")


def _minimiza_ou_maximiza(metrica: Metrica) -> Literal["min", "max"]:
    """LCOE deve ser minimizado; VPL e TIR devem ser maximizados."""
    return "min" if metrica == "LCOE" else "max"


def _valor_para_minimizacao_interna(valor: float | None, metrica: Metrica) -> float:
    """Converte o valor da métrica para o espaço de MINIMIZAÇÃO interna do scipy.

    ``scipy.optimize.minimize_scalar`` só minimiza. Para métricas que devem
    ser maximizadas (VPL, TIR), retornamos o valor negado. Quando a métrica
    é indefinida (ex.: TIR sem mudança de sinal no fluxo, ou LCOE com
    energia evitada total igual a zero), retornamos uma penalidade grande
    e positiva, para que o otimizador se afaste desses pontos.
    """
    if valor is None or not np.isfinite(valor):
        return 1e18
    return -valor if _minimiza_ou_maximiza(metrica) == "max" else valor


def _funcao_objetivo_fv(
    pot_inv_kw: float,
    ilr: float,
    carga_kw: np.ndarray,
    solar_provider: SolarProfileProvider,
    battery_config: BatteryConfig,
    generator_config: GeneratorConfig,
    economic_config: EconomicConfig,
    dispatch_strategy: DispatchStrategy,
    metrica: Metrica,
    contador: list[int],
) -> float:
    """Função objetivo (a minimizar internamente) para a etapa de otimização do FV."""
    contador[0] += 1
    solar_config = SolarConfig(pot_inv_kw=max(pot_inv_kw, 0.0), ilr=ilr)

    simulacao = simular_ano(
        carga_kw, solar_config, solar_provider, battery_config, generator_config, dispatch_strategy
    )
    financeiro = calcular_fluxo_de_caixa(
        simulacao.kpis, solar_config, battery_config, generator_config, economic_config
    )
    valor = _extrair_metrica(financeiro, metrica)
    return _valor_para_minimizacao_interna(valor, metrica)


def _funcao_objetivo_bess(
    capacidade_kwh: float,
    c_rate: float | None,
    dod: float,
    eficiencia_rt: float,
    carga_kw: np.ndarray,
    solar_config: SolarConfig,
    solar_provider: SolarProfileProvider,
    generator_config: GeneratorConfig,
    economic_config: EconomicConfig,
    dispatch_strategy: DispatchStrategy,
    metrica: Metrica,
    contador: list[int],
) -> float:
    """Função objetivo (a minimizar internamente) para a etapa de otimização do BESS."""
    contador[0] += 1
    battery_config = BatteryConfig(
        capacidade_kwh=max(capacidade_kwh, 0.0), c_rate=c_rate, dod=dod, eficiencia_rt=eficiencia_rt
    )

    simulacao = simular_ano(
        carga_kw, solar_config, solar_provider, battery_config, generator_config, dispatch_strategy
    )
    financeiro = calcular_fluxo_de_caixa(
        simulacao.kpis, solar_config, battery_config, generator_config, economic_config
    )
    valor = _extrair_metrica(financeiro, metrica)
    return _valor_para_minimizacao_interna(valor, metrica)


def otimizar_potencia_fv(
    carga_kw: np.ndarray,
    solar_provider: SolarProfileProvider,
    battery_config: BatteryConfig,
    generator_config: GeneratorConfig,
    economic_config: EconomicConfig,
    dispatch_strategy: DispatchStrategy,
    ilr: float = 1.4,
    pot_inv_min_kw: float = 0.0,
    pot_inv_max_kw: float | None = None,
    metrica: Metrica = "VPL",
) -> ResultadoOtimizacao:
    """Otimiza a potência do inversor FV para maximizar VPL/TIR ou minimizar LCOE.

    Equivale à primeira etapa do Solver da planilha original: ajustar
    ``Dimensionamento!G7`` (Pot inv) para otimizar ``Dimensionamento!T30``
    (ou T29/T31, conforme a métrica escolhida em S30/S29/S31).

    Args:
        carga_kw: array de 8760 posições com a carga elétrica horária (kW).
        solar_provider: provedor do perfil normalizado de irradiância.
        battery_config: configuração do BESS mantida fixa durante esta
            etapa (tipicamente com capacidade zero, para isolar o efeito
            do FV puro, como na planilha original).
        generator_config: configuração do parque de geradores (fixa).
        economic_config: parâmetros econômicos.
        dispatch_strategy: estratégia de despacho (ex.: ``LoadFollowingDispatch()``).
        ilr: índice de sobredimensionamento do arranjo FV (fixo durante a
            otimização).
        pot_inv_min_kw: limite inferior de busca para a potência do
            inversor (kW).
        pot_inv_max_kw: limite superior de busca. Se ``None``, usa 1,5x o
            pico da carga como heurística de limite superior razoável.
        metrica: métrica a otimizar ("VPL", "TIR" ou "LCOE").

    Returns:
        ``ResultadoOtimizacao`` com a potência ótima do inversor, a
        simulação e o resultado financeiro no ponto ótimo.
    """
    if pot_inv_max_kw is None:
        pot_inv_max_kw = float(np.max(carga_kw)) * 1.5

    contador = [0]
    resultado_scipy = minimize_scalar(
        _funcao_objetivo_fv,
        bounds=(pot_inv_min_kw, pot_inv_max_kw),
        method="bounded",
        args=(
            ilr,
            carga_kw,
            solar_provider,
            battery_config,
            generator_config,
            economic_config,
            dispatch_strategy,
            metrica,
            contador,
        ),
        options={"xatol": 1.0},  # precisão de 1 kW
    )

    pot_inv_otima_kw = float(resultado_scipy.x)
    solar_config_otima = SolarConfig(pot_inv_kw=pot_inv_otima_kw, ilr=ilr)

    simulacao_otima = simular_ano(
        carga_kw, solar_config_otima, solar_provider, battery_config, generator_config, dispatch_strategy
    )
    financeiro_otimo = calcular_fluxo_de_caixa(
        simulacao_otima.kpis, solar_config_otima, battery_config, generator_config, economic_config
    )
    valor_metrica = _extrair_metrica(financeiro_otimo, metrica)

    return ResultadoOtimizacao(
        valor_otimo=pot_inv_otima_kw,
        metrica=metrica,
        valor_metrica=valor_metrica if valor_metrica is not None else float("nan"),
        simulacao=simulacao_otima,
        financeiro=financeiro_otimo,
        convergiu=bool(resultado_scipy.success),
        n_avaliacoes=contador[0],
    )


def otimizar_capacidade_bess(
    carga_kw: np.ndarray,
    solar_config: SolarConfig,
    solar_provider: SolarProfileProvider,
    generator_config: GeneratorConfig,
    economic_config: EconomicConfig,
    dispatch_strategy: DispatchStrategy,
    c_rate: float | None = 0.5,
    dod: float = 0.9,
    eficiencia_rt: float = 0.92,
    capacidade_min_kwh: float = 0.0,
    capacidade_max_kwh: float | None = None,
    metrica: Metrica = "VPL",
) -> ResultadoOtimizacao:
    """Otimiza a capacidade do BESS para maximizar VPL/TIR ou minimizar LCOE.

    Equivale à segunda etapa do Solver da planilha original: ajustar
    ``Dimensionamento!K7`` (Capacid) para otimizar a métrica escolhida,
    com o FV já dimensionado na etapa anterior.

    O C-rate é mantido fixo (parâmetro de entrada do usuário — ver
    ``BatteryConfig.c_rate``); apenas a capacidade (kWh) é otimizada, e a
    potência do BESS (kW) é sempre derivada como ``capacidade_kwh * c_rate``.

    Args:
        carga_kw: array de 8760 posições com a carga elétrica horária (kW).
        solar_config: configuração do sistema FV, já dimensionado
            (tipicamente a saída de ``otimizar_potencia_fv``).
        solar_provider: provedor do perfil normalizado de irradiância.
        generator_config: configuração do parque de geradores (fixa).
        economic_config: parâmetros econômicos.
        dispatch_strategy: estratégia de despacho.
        c_rate: C-rate fixo do BESS (potência = capacidade × c_rate).
        dod: profundidade de descarga máxima (fixa).
        eficiencia_rt: eficiência round-trip (fixa).
        capacidade_min_kwh: limite inferior de busca (kWh).
        capacidade_max_kwh: limite superior de busca. Se ``None``, usa
            8x o pico da carga como heurística de limite superior
            razoável (equivalente a ~8h de autonomia no pico).
        metrica: métrica a otimizar ("VPL", "TIR" ou "LCOE").

    Returns:
        ``ResultadoOtimizacao`` com a capacidade ótima do BESS, a
        simulação e o resultado financeiro no ponto ótimo.
    """
    if capacidade_max_kwh is None:
        capacidade_max_kwh = float(np.max(carga_kw)) * 8.0

    contador = [0]
    resultado_scipy = minimize_scalar(
        _funcao_objetivo_bess,
        bounds=(capacidade_min_kwh, capacidade_max_kwh),
        method="bounded",
        args=(
            c_rate,
            dod,
            eficiencia_rt,
            carga_kw,
            solar_config,
            solar_provider,
            generator_config,
            economic_config,
            dispatch_strategy,
            metrica,
            contador,
        ),
        options={"xatol": 1.0},  # precisão de 1 kWh
    )

    capacidade_otima_kwh = float(resultado_scipy.x)
    battery_config_otima = BatteryConfig(
        capacidade_kwh=capacidade_otima_kwh, c_rate=c_rate, dod=dod, eficiencia_rt=eficiencia_rt
    )

    simulacao_otima = simular_ano(
        carga_kw, solar_config, solar_provider, battery_config_otima, generator_config, dispatch_strategy
    )
    financeiro_otimo = calcular_fluxo_de_caixa(
        simulacao_otima.kpis, solar_config, battery_config_otima, generator_config, economic_config
    )
    valor_metrica = _extrair_metrica(financeiro_otimo, metrica)

    return ResultadoOtimizacao(
        valor_otimo=capacidade_otima_kwh,
        metrica=metrica,
        valor_metrica=valor_metrica if valor_metrica is not None else float("nan"),
        simulacao=simulacao_otima,
        financeiro=financeiro_otimo,
        convergiu=bool(resultado_scipy.success),
        n_avaliacoes=contador[0],
    )


@dataclass
class ResultadoOtimizacaoCompleta:
    """Resultado da otimização sequencial completa (FV, depois BESS)."""

    etapa_fv: ResultadoOtimizacao
    etapa_bess: ResultadoOtimizacao
    solar_config_otimo: SolarConfig
    battery_config_otimo: BatteryConfig


def otimizar_sistema_completo(
    carga_kw: np.ndarray,
    solar_provider: SolarProfileProvider,
    generator_config: GeneratorConfig,
    economic_config: EconomicConfig,
    dispatch_strategy: DispatchStrategy,
    ilr: float = 1.4,
    c_rate: float | None = 0.5,
    dod: float = 0.9,
    eficiencia_rt: float = 0.92,
    metrica: Metrica = "VPL",
    pot_inv_max_kw: float | None = None,
    capacidade_max_kwh: float | None = None,
) -> ResultadoOtimizacaoCompleta:
    """Executa a otimização sequencial completa: FV primeiro, depois BESS.

    Replica o fluxo de trabalho original com o Solver do Excel: primeiro
    dimensiona a potência do inversor FV (com BESS zerado), depois, com o
    FV já definido, dimensiona a capacidade do BESS.

    Args:
        carga_kw: array de 8760 posições com a carga elétrica horária (kW).
        solar_provider: provedor do perfil normalizado de irradiância.
        generator_config: configuração do parque de geradores (fixa em
            ambas as etapas).
        economic_config: parâmetros econômicos.
        dispatch_strategy: estratégia de despacho.
        ilr: índice de sobredimensionamento do arranjo FV.
        c_rate: C-rate fixo do BESS.
        dod: profundidade de descarga máxima do BESS.
        eficiencia_rt: eficiência round-trip do BESS.
        metrica: métrica a otimizar em ambas as etapas.
        pot_inv_max_kw: limite superior de busca da potência FV (kW).
        capacidade_max_kwh: limite superior de busca da capacidade do
            BESS (kWh).

    Returns:
        ``ResultadoOtimizacaoCompleta`` com o resultado de cada etapa.
    """
    battery_config_zero = BatteryConfig(capacidade_kwh=0.0, c_rate=c_rate, dod=dod, eficiencia_rt=eficiencia_rt)

    etapa_fv = otimizar_potencia_fv(
        carga_kw=carga_kw,
        solar_provider=solar_provider,
        battery_config=battery_config_zero,
        generator_config=generator_config,
        economic_config=economic_config,
        dispatch_strategy=dispatch_strategy,
        ilr=ilr,
        pot_inv_max_kw=pot_inv_max_kw,
        metrica=metrica,
    )

    solar_config_otimo = SolarConfig(pot_inv_kw=etapa_fv.valor_otimo, ilr=ilr)

    etapa_bess = otimizar_capacidade_bess(
        carga_kw=carga_kw,
        solar_config=solar_config_otimo,
        solar_provider=solar_provider,
        generator_config=generator_config,
        economic_config=economic_config,
        dispatch_strategy=dispatch_strategy,
        c_rate=c_rate,
        dod=dod,
        eficiencia_rt=eficiencia_rt,
        capacidade_max_kwh=capacidade_max_kwh,
        metrica=metrica,
    )

    battery_config_otimo = BatteryConfig(
        capacidade_kwh=etapa_bess.valor_otimo, c_rate=c_rate, dod=dod, eficiencia_rt=eficiencia_rt
    )

    return ResultadoOtimizacaoCompleta(
        etapa_fv=etapa_fv,
        etapa_bess=etapa_bess,
        solar_config_otimo=solar_config_otimo,
        battery_config_otimo=battery_config_otimo,
    )
