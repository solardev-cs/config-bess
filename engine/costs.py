"""Cálculo de CAPEX, financiamento e custo de geração diesel.

Espelha os blocos "Custos" e "Financiamento" da aba "Dimensionamento" da
planilha original, com uma diferença deliberada: o CAPEX do BESS é
modelado apenas por R$/kWh (sem custo separado de PCS por kW) — no
mercado, o custo por kWh de BESS de curta duração já reflete o custo
total do pack, incluindo o PCS.

Importante: assim como na planilha original, o CAPEX do gerador diesel
NÃO é incluído no investimento total. O modelo trata o parque de geradores
como infraestrutura pré-existente (cenário tipico: propriedade rural que
já opera com diesel e avalia adicionar FV+BESS) — a viabilidade econômica
vem da economia de diesel gerada pelo investimento incremental em FV+BESS,
não de um sistema construído do zero.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.models import BatteryConfig, EconomicConfig, GeneratorConfig, SolarConfig

# Custos de referência padrão (R$), usados como default da página Configurações
# e como fallback por quem os lê antes de o usuário visitá-la. O custo do FV
# depende do acoplamento do BESS selecionado (ver ``ModeloBess.acoplamento``);
# o do BESS não.
CUSTO_FV_PADRAO_RS_KWP_POR_ACOPLAMENTO = {"CA": 6000.0, "CC": 5500.0}
CUSTO_BESS_PADRAO_RS_KWH = 1800.0


def custo_fv_padrao_rs_kwp(acoplamento: str) -> float:
    """Custo padrão do FV (R$/kWp) para o acoplamento do BESS ("CA" ou "CC").

    Acoplamento desconhecido cai no valor de "CA" (mesmo fallback usado pelo
    catálogo de BESS quando a coluna vem vazia).
    """
    return CUSTO_FV_PADRAO_RS_KWP_POR_ACOPLAMENTO.get(acoplamento, CUSTO_FV_PADRAO_RS_KWP_POR_ACOPLAMENTO["CA"])


@dataclass
class CapexBreakdown:
    """Detalhamento do investimento inicial (CAPEX) do sistema FV+BESS."""

    capex_fv_rs: float
    capex_bess_rs: float

    @property
    def capex_total_rs(self) -> float:
        return self.capex_fv_rs + self.capex_bess_rs


def calcular_capex(
    solar_config: SolarConfig, battery_config: BatteryConfig, economic_config: EconomicConfig
) -> CapexBreakdown:
    """Calcula o CAPEX do sistema FV+BESS.

    Equivale a ``Resumo!L21`` da planilha original (embora lá o nome da
    célula fosse "Investimento FV", o valor já somava FV+BESS).

    Args:
        solar_config: configuração do sistema FV (usa ``pot_pico_kwp``).
        battery_config: configuração do BESS (usa ``capacidade_kwh``).
        economic_config: parâmetros econômicos (custos por kWp/kWh).

    Returns:
        ``CapexBreakdown`` com o detalhamento FV/BESS e o total.
    """
    capex_fv_rs = solar_config.pot_pico_kwp * economic_config.custo_fv_rs_kwp
    capex_bess_rs = battery_config.capacidade_kwh * economic_config.custo_bateria_rs_kwh
    return CapexBreakdown(capex_fv_rs=capex_fv_rs, capex_bess_rs=capex_bess_rs)


def custo_geracao_diesel_rs_kwh(
    generator_config: GeneratorConfig, economic_config: EconomicConfig, ano: int = 1
) -> float:
    """Custo de geração a diesel, em R$/kWh, no ano informado.

    Equivale a ``Dimensionamento!P11`` (ano 1) da planilha original.

    CORREÇÃO em relação à planilha original: lá, a inflação do diesel era
    aplicada como um fator FIXO e IDÊNTICO em todos os anos do fluxo de
    caixa (``Resumo!K25:K49`` sempre multiplicava a economia por
    ``(1+Dimensionamento!$P$12)``, sem nunca elevar esse fator a uma
    potência do ano) — ou seja, o preço do diesel no ano 1 e no ano 25
    recebiam exatamente o mesmo ajuste de 5%, apesar do parâmetro se
    chamar "Inflação diesel (a.a.)". Aqui a inflação é composta
    corretamente: ``preco_ano = preco_base * (1 + inflacao) ** (ano - 1)``.

    Args:
        generator_config: configuração do parque de geradores (usa
            ``eficiencia_kwh_por_litro``).
        economic_config: parâmetros econômicos (preço do diesel e sua
            inflação anual).
        ano: ano do horizonte (1 = ano corrente, sem inflação aplicada).

    Returns:
        Custo de geração a diesel, em R$/kWh.
    """
    if generator_config.eficiencia_kwh_por_litro <= 0:
        return 0.0
    preco_diesel_ano = economic_config.preco_diesel_rs_litro * (
        (1 + economic_config.inflacao_diesel_am) ** (ano - 1)
    )
    return preco_diesel_ano / generator_config.eficiencia_kwh_por_litro


def converter_kwh_para_litros(energia_kwh: float, generator_config: GeneratorConfig) -> float:
    """Converte energia (kWh) em litros de diesel equivalentes.

    Usa a mesma eficiência do parque de geradores (``eficiencia_kwh_por_litro``)
    aplicada em ``custo_geracao_diesel_rs_kwh``, permitindo expressar a
    economia de diesel (ou o consumo evitado) diretamente em litros — por
    exemplo, para a métrica "litros evitados por hectare/ano" do Relatório
    de Viabilidade.

    Args:
        energia_kwh: energia a converter (kWh).
        generator_config: configuração do parque de geradores (usa
            ``eficiencia_kwh_por_litro``).

    Returns:
        Volume equivalente de diesel, em litros. Zero se a eficiência do
        gerador for zero ou negativa (parque inexistente).
    """
    if generator_config.eficiencia_kwh_por_litro <= 0:
        return 0.0
    return energia_kwh / generator_config.eficiencia_kwh_por_litro


@dataclass
class ParametrosFinanciamento:
    """Parâmetros derivados do financiamento (valor financiado/entrada)."""

    valor_financiado_rs: float
    valor_entrada_rs: float


def calcular_financiamento(capex_total_rs: float, economic_config: EconomicConfig) -> ParametrosFinanciamento:
    """Calcula o valor financiado e o valor de entrada do investimento.

    Equivale a ``Dimensionamento!U10`` (valor financiado) e ``U11`` (entrada).

    Args:
        capex_total_rs: CAPEX total do sistema (FV+BESS).
        economic_config: parâmetros econômicos (tipo de pagamento, %
            financiado).

    Returns:
        ``ParametrosFinanciamento`` com o valor financiado e o valor de
        entrada (desembolso próprio no ano 0).
    """
    if economic_config.tipo_pagamento == "FINANCIAMENTO":
        valor_financiado_rs = capex_total_rs * economic_config.pct_financiado
        valor_entrada_rs = capex_total_rs - valor_financiado_rs
    else:
        valor_financiado_rs = 0.0
        valor_entrada_rs = capex_total_rs

    return ParametrosFinanciamento(valor_financiado_rs=valor_financiado_rs, valor_entrada_rs=valor_entrada_rs)


def calcular_parcela_price(valor_financiado_rs: float, taxa_juros_am: float, prazo_anos: int, carencia_anos: int) -> float:
    """Calcula a parcela constante do sistema PRICE (fórmula PMT).

    Equivale a ``Cálculo Financeiro!E4`` da planilha original.

    Args:
        valor_financiado_rs: valor total financiado.
        taxa_juros_am: taxa de juros anual (a.a.).
        prazo_anos: prazo total do financiamento, em anos.
        carencia_anos: anos de carência (sem amortização).

    Returns:
        Valor da parcela anual constante (R$), aplicável a partir do fim
        da carência.
    """
    n = prazo_anos - carencia_anos
    if n <= 0 or taxa_juros_am <= 0:
        return valor_financiado_rs / max(n, 1)
    fator = (1 + taxa_juros_am) ** n
    return valor_financiado_rs * (taxa_juros_am * fator) / (fator - 1)


@dataclass
class LinhaAmortizacao:
    """Uma linha da tabela de amortização (um ano)."""

    ano: int
    juros_rs: float
    amortizacao_rs: float
    parcela_rs: float
    saldo_devedor_rs: float


def calcular_tabela_amortizacao(
    valor_financiado_rs: float, economic_config: EconomicConfig
) -> list[LinhaAmortizacao]:
    """Monta a tabela de amortização do financiamento (SAC ou PRICE).

    Equivale às colunas B:F da aba "Cálculo Financeiro" da planilha
    original, para os anos 1 a ``prazo_anos``. Durante a carência, apenas
    os juros são pagos (o saldo devedor não é amortizado) — mesmo
    comportamento da planilha original.

    Nota: a planilha original tinha uma referência a uma divisão por zero
    em um ramo morto do código (nunca executado, pois o ano sempre começa
    em 1) — essa ramificação simplesmente não existe nesta implementação.

    Args:
        valor_financiado_rs: valor total financiado.
        economic_config: parâmetros econômicos (taxa de juros, prazo,
            carência, tipo de financiamento).

    Returns:
        Lista de ``LinhaAmortizacao``, uma por ano, do ano 1 até
        ``prazo_anos``. Lista vazia se ``valor_financiado_rs == 0``.
    """
    if valor_financiado_rs <= 0:
        return []

    prazo = economic_config.prazo_anos
    carencia = economic_config.carencia_anos
    taxa = economic_config.taxa_juros_am
    n_amortizacao = prazo - carencia

    parcela_price = calcular_parcela_price(valor_financiado_rs, taxa, prazo, carencia)

    linhas: list[LinhaAmortizacao] = []
    saldo_anterior = valor_financiado_rs

    for ano in range(1, prazo + 1):
        juros_rs = taxa * saldo_anterior

        if ano <= carencia:
            amortizacao_rs = 0.0
        elif economic_config.tipo_financiamento == "SAC":
            amortizacao_rs = valor_financiado_rs / n_amortizacao
        else:  # PRICE
            amortizacao_rs = parcela_price - juros_rs

        if ano <= carencia:
            parcela_rs = juros_rs
        elif economic_config.tipo_financiamento == "SAC":
            parcela_rs = juros_rs + amortizacao_rs
        else:  # PRICE
            parcela_rs = parcela_price

        saldo_devedor_rs = saldo_anterior - amortizacao_rs

        linhas.append(
            LinhaAmortizacao(
                ano=ano,
                juros_rs=juros_rs,
                amortizacao_rs=amortizacao_rs,
                parcela_rs=parcela_rs,
                saldo_devedor_rs=saldo_devedor_rs,
            )
        )
        saldo_anterior = saldo_devedor_rs

    return linhas
