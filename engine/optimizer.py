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

Métricas de otimização suportadas: "VPL" (maximizar) e "LCOE"
(minimizar, exibido; ver nota abaixo sobre o critério de busca real).

Cada avaliação da função objetivo roda uma simulação horária completa de
8760h (~0.1s) mais o cálculo financeiro (~instantâneo após o primeiro
import do scipy) — uma busca em intervalo limitado (``bounded``) com
~20-40 avaliações leva poucos segundos, sem necessidade de paralelismo.

Nota importante sobre a métrica "LCOE" — degenerescência e correção:
    O LCOE, como calculado em ``engine/financial.py``
    (``(capex_total + om_total) / energia_evitada_total``), é uma métrica
    INTENSIVA (uma razão), assim como a TIR. Neste modelo, o CAPEX e a
    O&M são estritamente PROPORCIONAIS ao tamanho do sistema (sem nenhum
    custo fixo), e a energia evitada também é proporcional ao tamanho
    enquanto não houver saturação/curtailment. Nessa região, o LCOE é
    MATEMATICAMENTE CONSTANTE (invariante de escala) — ou seja, qualquer
    tamanho de sistema abaixo do ponto de saturação produz exatamente o
    mesmo LCOE. Minimizar essa razão diretamente via busca numérica é,
    portanto, um problema mal-definido: o resultado depende de ruído de
    ponto flutuante e tende a convergir para sistemas artificialmente
    pequenos, sem relação com o dimensionamento economicamente correto.

    Por isso, embora o LCOE final seja calculado e reportado normalmente
    (para fins de exibição/comparação), o CRITÉRIO DE BUSCA interno para
    a métrica "LCOE" não usa a razão do LCOE diretamente. Em vez disso,
    maximiza-se o "benefício econômico total não descontado" do sistema:

        beneficio(x) = economia_de_diesel_total(x) - om_total(x) - capex_total(x)

    Ou seja, a mesma soma de fluxos de caixa nominal que já compõe o
    numerador/denominador do LCOE (fiel à natureza NÃO descontada do
    LCOE, documentada em ``financial.py``), mas como uma quantidade
    EXTENSIVA (absoluta, em R$) em vez de uma razão. Isso resolve a
    degenerescência (o benefício cresce estritamente com x até o ponto de
    saturação, tal como o VPL) e ainda captura a filosofia do LCOE (custos
    e receitas nominais, sem desconto temporal) — a única diferença para o
    critério de VPL é a ausência do desconto pela TMA.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from scipy.optimize import minimize, minimize_scalar

from engine.dispatch.base import DispatchStrategy
from engine.dispatch.dc_coupled import DcCoupledDispatch
from engine.dispatch.load_following import LoadFollowingDispatch
from engine.financial import ResultadoFinanceiro, calcular_fluxo_de_caixa
from engine.models import BatteryConfig, EconomicConfig, GeneratorConfig, SolarConfig
from engine.simulator import SimulationResult, simular_ano
from engine.solar.base import SolarProfileProvider

import numpy as np

Metrica = Literal["VPL", "LCOE"]


@dataclass
class ResultadoOtimizacao:
    """Resultado de uma etapa de otimização (FV ou BESS)."""

    valor_otimo: float  # pot_inv_kw ou capacidade_kwh, conforme a etapa
    metrica: Metrica
    valor_metrica: float  # valor da métrica exibida (VPL em R$, ou a razão de LCOE em R$/kWh) no ponto ótimo
    simulacao: SimulationResult
    financeiro: ResultadoFinanceiro
    convergiu: bool
    n_avaliacoes: int


def _beneficio_economico_nao_descontado(financeiro: ResultadoFinanceiro) -> float:
    """Benefício econômico total do sistema, em R$, sem desconto temporal.

    ``economia_de_diesel_total - om_total - capex_total``, somado sobre
    todo o horizonte (ano 1 em diante; o ano 0 não tem economia nem O&M).
    É a mesma combinação de termos nominais que compõe o LCOE
    (``(capex_total + om_total) / energia_evitada_total``), mas expressa
    como uma diferença (quantidade EXTENSIVA, em R$) em vez de uma razão.

    Isso é usado como critério de busca para a métrica "LCOE" (ver nota no
    topo do módulo sobre a degenerescência de otimizar a razão do LCOE
    diretamente): maximizar este benefício é equivalente, em espírito, a
    minimizar o LCOE, mas sem o problema de invariância de escala.
    """
    om_total_rs = sum(f.om_rs for f in financeiro.fluxos if f.ano >= 1)
    economia_diesel_total_rs = sum(f.economia_diesel_rs for f in financeiro.fluxos if f.ano >= 1)
    return economia_diesel_total_rs - om_total_rs - financeiro.capex.capex_total_rs


def _valor_busca(financeiro: ResultadoFinanceiro, metrica: Metrica) -> float | None:
    """Valor a ser MAXIMIZADO durante a busca numérica (sempre extensivo/absoluto).

    Para "VPL", é o próprio VPL. Para "LCOE", NÃO é a razão do LCOE (que é
    degenerada/invariante de escala — ver nota no topo do módulo), e sim o
    benefício econômico total não descontado, que cresce estritamente com
    o tamanho do sistema até o ponto de saturação, assim como o VPL.
    """
    if metrica == "VPL":
        return financeiro.vpl_rs
    if metrica == "LCOE":
        return _beneficio_economico_nao_descontado(financeiro)
    raise ValueError(f"Métrica desconhecida: {metrica}")


def _valor_metrica_exibicao(financeiro: ResultadoFinanceiro, metrica: Metrica) -> float | None:
    """Valor da métrica a ser REPORTADO ao usuário no ponto ótimo encontrado.

    Para "LCOE", é a razão clássica (R$/kWh evitado) — apenas para
    exibição/comparação; não é o critério usado internamente pela busca
    (ver ``_valor_busca``).
    """
    if metrica == "VPL":
        return financeiro.vpl_rs
    if metrica == "LCOE":
        return financeiro.lcoe_rs_kwh
    raise ValueError(f"Métrica desconhecida: {metrica}")


def _valor_para_minimizacao_interna(valor: float | None) -> float:
    """Converte o valor de busca (``_valor_busca``) para o espaço de MINIMIZAÇÃO
    interna do scipy.

    ``scipy.optimize.minimize_scalar`` só minimiza. Como ambos os critérios
    de busca suportados ("VPL" e o benefício não descontado usado para
    "LCOE") são quantidades a MAXIMIZAR, sempre retornamos o valor negado.
    Quando o valor é indefinido/não finito, retornamos uma penalidade
    grande e positiva, para que o otimizador se afaste desses pontos.
    """
    if valor is None or not np.isfinite(valor):
        return 1e18
    return -valor


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
    valor = _valor_busca(financeiro, metrica)
    return _valor_para_minimizacao_interna(valor)


def _funcao_objetivo_bess(
    capacidade_kwh: float,
    c_rate: float | None,
    dod: float,
    eficiencia_rt: float,
    degradacao_capacidade_am_ano: float,
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
        capacidade_kwh=max(capacidade_kwh, 0.0),
        c_rate=c_rate,
        dod=dod,
        eficiencia_rt=eficiencia_rt,
        degradacao_capacidade_am_ano=degradacao_capacidade_am_ano,
    )

    simulacao = simular_ano(
        carga_kw, solar_config, solar_provider, battery_config, generator_config, dispatch_strategy
    )
    financeiro = calcular_fluxo_de_caixa(
        simulacao.kpis, solar_config, battery_config, generator_config, economic_config
    )
    valor = _valor_busca(financeiro, metrica)
    return _valor_para_minimizacao_interna(valor)


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
    """Otimiza a potência do inversor FV para maximizar VPL, ou LCOE.

    Equivale à primeira etapa do Solver da planilha original: ajustar
    ``Dimensionamento!G7`` (Pot inv) para otimizar a métrica escolhida.

    Nota sobre a métrica "LCOE": o CRITÉRIO DE BUSCA interno não é a razão
    do LCOE diretamente (que é degenerada/invariante de escala neste
    modelo — ver docstring do módulo), e sim o benefício econômico total
    não descontado equivalente. O valor de LCOE reportado em
    ``ResultadoOtimizacao.valor_metrica`` continua sendo a razão clássica
    (R$/kWh evitado), calculada no ponto ótimo encontrado.

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
        metrica: métrica a otimizar ("VPL" ou "LCOE").

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
    valor_metrica = _valor_metrica_exibicao(financeiro_otimo, metrica)

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
    degradacao_capacidade_am_ano: float = 0.0,
    capacidade_min_kwh: float = 0.0,
    capacidade_max_kwh: float | None = None,
    metrica: Metrica = "VPL",
) -> ResultadoOtimizacao:
    """Otimiza a capacidade do BESS para maximizar VPL, ou LCOE.

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
        degradacao_capacidade_am_ano: perda de capacidade/SOH do BESS por
            ano (fixa), usada por ``calcular_fluxo_de_caixa`` para degradar
            a parcela da energia evitada atribuída à bateria ao longo do
            horizonte financeiro — não afeta a simulação técnica em si.
        capacidade_min_kwh: limite inferior de busca (kWh).
        capacidade_max_kwh: limite superior de busca. Se ``None``, usa
            8x o pico da carga como heurística de limite superior
            razoável (equivalente a ~8h de autonomia no pico).
        metrica: métrica a otimizar ("VPL" ou "LCOE"; ver nota no topo do
            módulo sobre o critério de busca real usado para "LCOE").

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
            degradacao_capacidade_am_ano,
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
        capacidade_kwh=capacidade_otima_kwh,
        c_rate=c_rate,
        dod=dod,
        eficiencia_rt=eficiencia_rt,
        degradacao_capacidade_am_ano=degradacao_capacidade_am_ano,
    )

    simulacao_otima = simular_ano(
        carga_kw, solar_config, solar_provider, battery_config_otima, generator_config, dispatch_strategy
    )
    financeiro_otimo = calcular_fluxo_de_caixa(
        simulacao_otima.kpis, solar_config, battery_config_otima, generator_config, economic_config
    )
    valor_metrica = _valor_metrica_exibicao(financeiro_otimo, metrica)

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
    degradacao_capacidade_am_ano: float = 0.0,
    metrica: Metrica = "VPL",
    pot_inv_max_kw: float | None = None,
    capacidade_max_kwh: float | None = None,
    otimizar_bess: bool = True,
) -> ResultadoOtimizacaoCompleta:
    """Executa a otimização sequencial completa: FV primeiro, depois BESS.

    Com ``otimizar_bess=False`` (sistema "Solar + Diesel"), só a etapa do FV roda: o BESS
    fica com capacidade zero e ``etapa_bess`` repete o resultado da etapa do FV (mesma
    simulação/financeiro, ``valor_otimo=0``, sem avaliações). Nesse modo o despacho deve ser
    CA (``LoadFollowingDispatch``): sem BESS não há acoplamento, e o FV do acoplamento CC
    não entregaria nada à carga.

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
        degradacao_capacidade_am_ano: perda de capacidade/SOH do BESS por
            ano (fixa) — ver ``otimizar_capacidade_bess``.
        metrica: métrica a otimizar em ambas as etapas.
        pot_inv_max_kw: limite superior de busca da potência FV (kW).
        capacidade_max_kwh: limite superior de busca da capacidade do
            BESS (kWh).

    Returns:
        ``ResultadoOtimizacaoCompleta`` com o resultado de cada etapa.
    """
    if isinstance(dispatch_strategy, DcCoupledDispatch) and otimizar_bess:
        # A busca sequencial abaixo (zerar o BESS para isolar o efeito do FV) não
        # funciona para acoplamento CC — ver docstring de
        # ``_otimizar_sistema_completo_dc_coupled``.
        if pot_inv_max_kw is None:
            pot_inv_max_kw = float(np.max(carga_kw)) * 1.5
        if capacidade_max_kwh is None:
            capacidade_max_kwh = float(np.max(carga_kw)) * 8.0
        return _otimizar_sistema_completo_dc_coupled(
            carga_kw=carga_kw,
            solar_provider=solar_provider,
            generator_config=generator_config,
            economic_config=economic_config,
            dispatch_strategy=dispatch_strategy,
            ilr=ilr,
            c_rate=c_rate,
            dod=dod,
            eficiencia_rt=eficiencia_rt,
            degradacao_capacidade_am_ano=degradacao_capacidade_am_ano,
            metrica=metrica,
            pot_inv_max_kw=pot_inv_max_kw,
            capacidade_max_kwh=capacidade_max_kwh,
        )

    battery_config_zero = BatteryConfig(
        capacidade_kwh=0.0,
        c_rate=c_rate,
        dod=dod,
        eficiencia_rt=eficiencia_rt,
        degradacao_capacidade_am_ano=degradacao_capacidade_am_ano,
    )

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

    if not otimizar_bess:
        return ResultadoOtimizacaoCompleta(
            etapa_fv=etapa_fv,
            etapa_bess=replace(etapa_fv, valor_otimo=0.0, n_avaliacoes=0),
            solar_config_otimo=solar_config_otimo,
            battery_config_otimo=battery_config_zero,
        )

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
        degradacao_capacidade_am_ano=degradacao_capacidade_am_ano,
        capacidade_max_kwh=capacidade_max_kwh,
        metrica=metrica,
    )

    battery_config_otimo = BatteryConfig(
        capacidade_kwh=etapa_bess.valor_otimo,
        c_rate=c_rate,
        dod=dod,
        eficiencia_rt=eficiencia_rt,
        degradacao_capacidade_am_ano=degradacao_capacidade_am_ano,
    )

    return ResultadoOtimizacaoCompleta(
        etapa_fv=etapa_fv,
        etapa_bess=etapa_bess,
        solar_config_otimo=solar_config_otimo,
        battery_config_otimo=battery_config_otimo,
    )


def _otimizar_sistema_completo_dc_coupled(
    carga_kw: np.ndarray,
    solar_provider: SolarProfileProvider,
    generator_config: GeneratorConfig,
    economic_config: EconomicConfig,
    dispatch_strategy: DispatchStrategy,
    ilr: float,
    c_rate: float | None,
    dod: float,
    eficiencia_rt: float,
    degradacao_capacidade_am_ano: float,
    metrica: Metrica,
    pot_inv_max_kw: float,
    capacidade_max_kwh: float,
) -> ResultadoOtimizacaoCompleta:
    """Otimização de FV+BESS para BESS de acoplamento CC — busca conjunta (2D).

    A busca sequencial usada para acoplamento CA em ``otimizar_sistema_completo``
    (1º dimensiona o FV com o BESS zerado, para isolar seu efeito; 2º dimensiona
    o BESS com o FV já fixo) não funciona para acoplamento CC: como toda a
    energia solar precisa passar pela bateria antes de chegar à carga
    (``DcCoupledDispatch``), zerar a capacidade do BESS na 1ª etapa torna
    QUALQUER potência de FV economicamente inútil (100% da energia seria
    curtailed — uma bateria de capacidade zero não consegue repassar nada).
    Isso empurra a 1ª etapa para ~0 kW, o que por sua vez empurra a 2ª etapa
    (BESS, agora sem quase nenhuma solar para armazenar) para ~0 kWh também —
    um ótimo degenerado, não o dimensionamento economicamente correto (sintoma
    observado: FV e BESS convergindo para frações de kW/kWh mesmo em cenários
    onde um sistema grande claramente compensaria).

    Aqui, FV e BESS são otimizados SIMULTANEAMENTE (busca 2D, Nelder-Mead,
    ``scipy.optimize.minimize``) sob a estratégia de despacho CC real. O ponto
    de partida da busca reaproveita o resultado da busca sequencial padrão
    rodada com ``LoadFollowingDispatch`` (acoplamento CA) — não como resposta
    final (que sempre usa ``dispatch_strategy``, a estratégia CC real, em toda
    avaliação e na simulação/financeiro reportados), mas só como uma estimativa
    inicial fisicamente razoável (mesma carga, mesmo perfil solar, mesma ordem
    de grandeza), para reduzir o risco de a busca 2D — sem gradiente, portanto
    sujeita a ótimos locais — ficar presa perto do canto degenerado (0, 0).
    """
    chute = otimizar_sistema_completo(
        carga_kw=carga_kw,
        solar_provider=solar_provider,
        generator_config=generator_config,
        economic_config=economic_config,
        dispatch_strategy=LoadFollowingDispatch(),
        ilr=ilr,
        c_rate=c_rate,
        dod=dod,
        eficiencia_rt=eficiencia_rt,
        degradacao_capacidade_am_ano=degradacao_capacidade_am_ano,
        metrica=metrica,
        pot_inv_max_kw=pot_inv_max_kw,
        capacidade_max_kwh=capacidade_max_kwh,
    )
    pot_inv_chute_kw = chute.solar_config_otimo.pot_inv_kw
    # A capacidade do BESS na estimativa de partida precisa ser suficiente para que a
    # POTÊNCIA de carga/descarga do BESS (derivada de capacidade_kwh * c_rate) consiga
    # repassar o pico do FV estimado — senão o BESS vira um gargalo de potência artificial
    # logo na largada, e a busca 2D (sem gradiente) tende a "resolver" isso encolhendo o FV
    # em vez de crescer o BESS, convergindo de novo para perto de zero. É comum a estimativa
    # de BESS vinda do acoplamento CA ser pequena (ela só precisa cobrir o excedente solar
    # que sobra da carga direta) mesmo quando o FV estimado é grande.
    capacidade_min_para_potencia_fv_kwh = pot_inv_chute_kw / c_rate if c_rate else 0.0
    x0 = np.array(
        [
            min(max(pot_inv_chute_kw, 1.0), pot_inv_max_kw),
            min(
                max(chute.battery_config_otimo.capacidade_kwh, capacidade_min_para_potencia_fv_kwh, 1.0),
                capacidade_max_kwh,
            ),
        ],
        dtype=float,
    )

    contador = [0]

    def objetivo(x: np.ndarray) -> float:
        contador[0] += 1
        pot_inv_kw = float(min(max(x[0], 0.0), pot_inv_max_kw))
        capacidade_kwh = float(min(max(x[1], 0.0), capacidade_max_kwh))
        solar_config = SolarConfig(pot_inv_kw=pot_inv_kw, ilr=ilr)
        battery_config = BatteryConfig(
            capacidade_kwh=capacidade_kwh,
            c_rate=c_rate,
            dod=dod,
            eficiencia_rt=eficiencia_rt,
            degradacao_capacidade_am_ano=degradacao_capacidade_am_ano,
        )
        simulacao = simular_ano(
            carga_kw, solar_config, solar_provider, battery_config, generator_config, dispatch_strategy
        )
        financeiro = calcular_fluxo_de_caixa(
            simulacao.kpis, solar_config, battery_config, generator_config, economic_config
        )
        return _valor_para_minimizacao_interna(_valor_busca(financeiro, metrica))

    resultado_scipy = minimize(
        objetivo,
        x0=x0,
        method="Nelder-Mead",
        bounds=[(0.0, pot_inv_max_kw), (0.0, capacidade_max_kwh)],
        options={"xatol": 1.0, "fatol": 1.0, "maxiter": 150},
    )

    pot_inv_otimo_kw = float(min(max(resultado_scipy.x[0], 0.0), pot_inv_max_kw))
    capacidade_otima_kwh = float(min(max(resultado_scipy.x[1], 0.0), capacidade_max_kwh))

    solar_config_otimo = SolarConfig(pot_inv_kw=pot_inv_otimo_kw, ilr=ilr)
    battery_config_otimo = BatteryConfig(
        capacidade_kwh=capacidade_otima_kwh,
        c_rate=c_rate,
        dod=dod,
        eficiencia_rt=eficiencia_rt,
        degradacao_capacidade_am_ano=degradacao_capacidade_am_ano,
    )
    simulacao_otima = simular_ano(
        carga_kw, solar_config_otimo, solar_provider, battery_config_otimo, generator_config, dispatch_strategy
    )
    financeiro_otimo = calcular_fluxo_de_caixa(
        simulacao_otima.kpis, solar_config_otimo, battery_config_otimo, generator_config, economic_config
    )
    valor_metrica = _valor_metrica_exibicao(financeiro_otimo, metrica)
    valor_metrica = valor_metrica if valor_metrica is not None else float("nan")
    n_avaliacoes_chute = chute.etapa_fv.n_avaliacoes + chute.etapa_bess.n_avaliacoes

    etapa_fv = ResultadoOtimizacao(
        valor_otimo=pot_inv_otimo_kw,
        metrica=metrica,
        valor_metrica=valor_metrica,
        simulacao=simulacao_otima,
        financeiro=financeiro_otimo,
        convergiu=bool(resultado_scipy.success),
        n_avaliacoes=contador[0] + n_avaliacoes_chute,
    )
    etapa_bess = ResultadoOtimizacao(
        valor_otimo=capacidade_otima_kwh,
        metrica=metrica,
        valor_metrica=valor_metrica,
        simulacao=simulacao_otima,
        financeiro=financeiro_otimo,
        convergiu=bool(resultado_scipy.success),
        n_avaliacoes=0,  # já contado em etapa_fv.n_avaliacoes (busca conjunta, não 2 etapas separadas)
    )

    return ResultadoOtimizacaoCompleta(
        etapa_fv=etapa_fv,
        etapa_bess=etapa_bess,
        solar_config_otimo=solar_config_otimo,
        battery_config_otimo=battery_config_otimo,
    )
