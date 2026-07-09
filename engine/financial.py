"""Fluxo de caixa, VPL, TIR, LCOE e Payback do sistema FV+BESS.

Combina a lógica das abas "Cálculo Financeiro" (amortização do
financiamento, degradação do FV) e "Resumo" (tabela de fluxo de caixa
anual, VPL, TIR, LCOE, Payback) da planilha original em um único módulo,
com as seguintes simplificações/decisões deliberadas:

- O CAPEX do gerador diesel não entra no investimento: o modelo assume um
  parque de geradores pré-existente, e a viabilidade vem da economia de
  diesel obtida ao adicionar FV+BESS (mesma premissa da planilha original).
- A "energia evitada" (energia que deixou de vir do diesel graças ao
  FV+BESS) é calculada de forma limpa a partir dos KPIs da simulação
  técnica: ``energia_solar_utilizada_kwh + energia_bateria_descarregada_kwh``.
  Isso substitui a fórmula original (``Q8766+U8766-V8766/2``), que somava a
  descarga da bateria à energia solar utilizada e subtraía a metade do
  dump load como uma correção ad-hoc de possível dupla contagem — no motor
  corrigido, ``solar_utilizado`` e ``bateria_descarga`` já são grandezas
  limpas e não sobrepostas (validado por ``test_conservacao_de_energia_horaria``
  em ``tests/test_regression_excel.py``), então a correção não é necessária.
- A degradação anual (``degradacao_fv_am_ano``) é aplicada sobre o total da
  "energia evitada" do ano 1, sem re-executar a simulação horária de 8760h
  para cada um dos 25 anos — mesma abordagem simplificada da planilha
  original (que só degradava a energia, não repetia a simulação técnica).
- O custo de O&M é uma fração constante do CAPEX total, sem inflação anual
  — mesmo comportamento da planilha original (linha ``P`` da aba "Cálculo
  Financeiro" idêntica em todos os anos).
- O LCOE é calculado de forma NÃO descontada (soma nominal de custos /
  soma nominal de energia), replicando fielmente ``Resumo!K77``. Isso é
  uma simplificação comum em relatórios de viabilidade rápidos, mas não é
  o LCOE "rigoroso" (que usaria fluxos descontados no numerador e
  denominador). Documentado aqui para transparência.
- O Payback é calculado contando quantos anos (incluindo o ano 0) têm
  fluxo de caixa acumulado negativo — mesma lógica de
  ``COUNTIF(N24:N49,"<0")`` da planilha original. É uma aproximação
  (assume fluxo acumulado monotonicamente crescente), não uma
  interpolação exata do mês/dia do payback.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.costs import (
    CapexBreakdown,
    ParametrosFinanciamento,
    calcular_capex,
    calcular_financiamento,
    calcular_tabela_amortizacao,
    custo_geracao_diesel_rs_kwh,
)
from engine.models import BatteryConfig, EconomicConfig, GeneratorConfig, SimulationKPIs, SolarConfig


@dataclass
class FluxoCaixaAno:
    """Uma linha da tabela de fluxo de caixa (um ano, incluindo o ano 0)."""

    ano: int
    energia_evitada_kwh: float
    economia_diesel_rs: float
    om_rs: float
    parcela_financiamento_rs: float
    fluxo_caixa_rs: float
    fluxo_acumulado_rs: float


@dataclass
class ResultadoFinanceiro:
    """Resultado completo da análise financeira do sistema FV+BESS."""

    capex: CapexBreakdown
    financiamento: ParametrosFinanciamento
    fluxos: list[FluxoCaixaAno]  # ano 0 até horizonte_anos
    vpl_rs: float
    tir: float | None  # None se não houver mudança de sinal no fluxo (TIR indefinida)
    lcoe_rs_kwh: float
    payback_anos: int | None  # None se o investimento não se paga dentro do horizonte
    economia_diesel_ano1_rs: float
    economia_em_sacas_ano1: float


def _calcular_npv(taxa_am: float, fluxos_rs: list[float]) -> float:
    """VPL de uma série de fluxos de caixa (índice 0 = ano 0, sem desconto)."""
    return sum(fluxo / ((1 + taxa_am) ** ano) for ano, fluxo in enumerate(fluxos_rs))


def _calcular_irr(fluxos_rs: list[float]) -> float | None:
    """TIR de uma série de fluxos de caixa, via busca de raiz (bisseção).

    Retorna ``None`` se não houver mudança de sinal no fluxo acumulado
    (TIR matematicamente indefinida ou múltiplas soluções instáveis).
    """
    from scipy.optimize import brentq

    def npv_em(taxa: float) -> float:
        return _calcular_npv(taxa, fluxos_rs)

    # Busca um intervalo com mudança de sinal entre uma taxa muito negativa
    # (próxima de -100%) e uma taxa muito alta (500%).
    taxa_min, taxa_max = -0.99, 5.0
    npv_min, npv_max = npv_em(taxa_min), npv_em(taxa_max)

    if npv_min == 0:
        return taxa_min
    if npv_max == 0:
        return taxa_max
    if (npv_min > 0) == (npv_max > 0):
        return None  # sem mudança de sinal no intervalo pesquisado

    try:
        return brentq(npv_em, taxa_min, taxa_max)
    except (ValueError, RuntimeError):
        return None


def calcular_fluxo_de_caixa(
    kpis: SimulationKPIs,
    solar_config: SolarConfig,
    battery_config: BatteryConfig,
    generator_config: GeneratorConfig,
    economic_config: EconomicConfig,
) -> ResultadoFinanceiro:
    """Monta o fluxo de caixa completo e calcula VPL/TIR/LCOE/Payback.

    Args:
        kpis: indicadores agregados da simulação técnica de 8760h
            (``SimulationResult.kpis``), usados para obter a energia
            evitada de diesel no ano 1.
        solar_config: configuração do sistema FV (usado no CAPEX).
        battery_config: configuração do BESS (usado no CAPEX).
        generator_config: configuração do parque de geradores (usado no
            custo de geração a diesel).
        economic_config: parâmetros econômicos e de financiamento.

    Returns:
        ``ResultadoFinanceiro`` com o CAPEX, os parâmetros de
        financiamento, a tabela de fluxo de caixa ano a ano e os
        indicadores VPL, TIR, LCOE e Payback.
    """
    capex = calcular_capex(solar_config, battery_config, economic_config)
    financiamento = calcular_financiamento(capex.capex_total_rs, economic_config)
    tabela_amortizacao = calcular_tabela_amortizacao(financiamento.valor_financiado_rs, economic_config)
    amortizacao_por_ano = {linha.ano: linha for linha in tabela_amortizacao}

    energia_evitada_ano1_kwh = kpis.energia_solar_utilizada_kwh + kpis.energia_bateria_descarregada_kwh
    om_rs_anual = capex.capex_total_rs * economic_config.om_pct_am

    fluxos: list[FluxoCaixaAno] = []

    # --- Ano 0: desembolso inicial ---
    fluxo_ano0 = -financiamento.valor_entrada_rs
    fluxos.append(
        FluxoCaixaAno(
            ano=0,
            energia_evitada_kwh=0.0,
            economia_diesel_rs=0.0,
            om_rs=0.0,
            parcela_financiamento_rs=0.0,
            fluxo_caixa_rs=fluxo_ano0,
            fluxo_acumulado_rs=fluxo_ano0,
        )
    )

    energia_evitada_total_kwh = 0.0
    om_total_rs = 0.0
    economia_diesel_ano1_rs = 0.0
    acumulado = fluxo_ano0

    for ano in range(1, economic_config.horizonte_anos + 1):
        energia_evitada_kwh = energia_evitada_ano1_kwh * (
            (1 - economic_config.degradacao_fv_am_ano) ** (ano - 1)
        )
        custo_diesel_kwh = custo_geracao_diesel_rs_kwh(generator_config, economic_config, ano)
        economia_diesel_rs = energia_evitada_kwh * custo_diesel_kwh

        if ano == 1:
            economia_diesel_ano1_rs = economia_diesel_rs

        linha_amortizacao = amortizacao_por_ano.get(ano)
        parcela_rs = linha_amortizacao.parcela_rs if linha_amortizacao else 0.0

        fluxo_rs = economia_diesel_rs - om_rs_anual - parcela_rs
        acumulado += fluxo_rs

        energia_evitada_total_kwh += energia_evitada_kwh
        om_total_rs += om_rs_anual

        fluxos.append(
            FluxoCaixaAno(
                ano=ano,
                energia_evitada_kwh=energia_evitada_kwh,
                economia_diesel_rs=economia_diesel_rs,
                om_rs=om_rs_anual,
                parcela_financiamento_rs=parcela_rs,
                fluxo_caixa_rs=fluxo_rs,
                fluxo_acumulado_rs=acumulado,
            )
        )

    fluxos_rs = [f.fluxo_caixa_rs for f in fluxos]
    vpl_rs = _calcular_npv(economic_config.tma_am, fluxos_rs)
    tir = _calcular_irr(fluxos_rs)

    lcoe_rs_kwh = (
        (capex.capex_total_rs + om_total_rs) / energia_evitada_total_kwh
        if energia_evitada_total_kwh > 0
        else float("nan")
    )

    horas_negativas = sum(1 for f in fluxos if f.fluxo_acumulado_rs < 0)
    payback_anos = horas_negativas if horas_negativas < len(fluxos) else None

    economia_em_sacas_ano1 = (
        economia_diesel_ano1_rs / economic_config.economia_por_saca_rs
        if economic_config.economia_por_saca_rs > 0
        else 0.0
    )

    return ResultadoFinanceiro(
        capex=capex,
        financiamento=financiamento,
        fluxos=fluxos,
        vpl_rs=vpl_rs,
        tir=tir,
        lcoe_rs_kwh=lcoe_rs_kwh,
        payback_anos=payback_anos,
        economia_diesel_ano1_rs=economia_diesel_ano1_rs,
        economia_em_sacas_ano1=economia_em_sacas_ano1,
    )
