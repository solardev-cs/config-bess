"""Dataclasses de configuração e resultado usadas pelo motor de cálculo.

Estas classes espelham os blocos de entrada da planilha original
(principalmente a aba "Dimensionamento"), mas já corrigem os problemas
identificados na análise da planilha:

- BatteryConfig agora modela POTÊNCIA (kW) além de CAPACIDADE (kWh), via
  ``c_rate``. Isso corrige o bug em que o BESS conseguia entregar/absorver
  qualquer potência instantânea, limitado apenas pela energia disponível.
  Para comparar 1:1 com o comportamento antigo do Excel (sem limite de
  potência), defina ``c_rate=None`` (modo "legado").
- GeneratorConfig expõe ``pot_total_kw`` para permitir o clamp de potência
  máxima hora a hora no despacho (bug antigo: o gerador podia ultrapassar a
  potência nominal total do parque).
- EconomicConfig já reserva um campo de custo por kW do BESS (PCS), que
  faltava por completo na planilha original.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Optional

ModoGerador = Literal["ON/OFF", "Sempre ON"]
TipoPagamento = Literal["RECURSO PRÓPRIO", "FINANCIAMENTO"]
TipoFinanciamento = Literal["SAC", "PRICE"]


@dataclass
class BatteryConfig:
    """Configuração do banco de baterias (BESS).

    Attributes:
        capacidade_kwh: Capacidade nominal de energia do BESS (kWh).
            Equivale à célula ``Dimensionamento!K7`` da planilha original.
        c_rate: Taxa de carga/descarga do BESS, em C (ex.: 0.5C significa
            que o BESS descarrega totalmente em 2 horas). A potência é
            derivada como ``capacidade_kwh * c_rate``.
            Se ``None``, o BESS não tem limite de potência (modo "legado",
            replica o comportamento — incorreto — da planilha original,
            útil apenas para testes de regressão).
        dod: Profundidade de descarga máxima permitida (0 a 1).
            Equivale a ``Dimensionamento!K8``.
        eficiencia_rt: Eficiência round-trip do BESS (0 a 1). A planilha
            original não modelava nenhuma perda (eficiência = 1.0).
        degradacao_capacidade_am_ano: Fração de perda de capacidade por ano
            (SOH), usada no motor financeiro (fase 3) para simular a
            degradação do BESS ao longo de 25 anos. A planilha original não
            modelava isso (apenas a degradação do FV existia).
    """

    capacidade_kwh: float
    c_rate: Optional[float] = None
    dod: float = 0.9
    eficiencia_rt: float = 1.0
    degradacao_capacidade_am_ano: float = 0.0

    def __post_init__(self) -> None:
        if self.capacidade_kwh < 0:
            raise ValueError("capacidade_kwh não pode ser negativa.")
        if self.c_rate is not None and self.c_rate <= 0:
            raise ValueError("c_rate deve ser positivo (ou None para modo legado).")
        if not 0 < self.dod <= 1:
            raise ValueError("dod deve estar no intervalo (0, 1].")
        if not 0 < self.eficiencia_rt <= 1:
            raise ValueError("eficiencia_rt deve estar no intervalo (0, 1].")
        if self.degradacao_capacidade_am_ano < 0:
            raise ValueError("degradacao_capacidade_am_ano não pode ser negativa.")

    @property
    def soc_min_kwh(self) -> float:
        """SOC mínimo permitido (kWh). Equivale a ``Dimensionamento!K9``."""
        return self.capacidade_kwh * (1 - self.dod)

    @property
    def potencia_kw(self) -> float:
        """Potência máxima de carga/descarga do BESS (kW).

        ``math.inf`` quando ``c_rate`` é ``None`` (modo legado).
        """
        if self.c_rate is None:
            return math.inf
        return self.capacidade_kwh * self.c_rate

    @property
    def eficiencia_unidirecional(self) -> float:
        """Eficiência aplicada em cada sentido (carga OU descarga).

        Deriva da eficiência round-trip via raiz quadrada, forma padrão de
        distribuir a perda igualmente entre carga e descarga.
        """
        return math.sqrt(self.eficiencia_rt)


@dataclass
class GeneratorConfig:
    """Configuração do parque de geradores diesel.

    Espelha o bloco "Gerador" da aba Dimensionamento.
    """

    nr_maquinas: int
    nr_min_maquinas: int
    pot_continua_kw: float
    pot_prime_kva: float
    fp: float = 0.8
    pot_min_pct: float = 0.0
    modo: ModoGerador = "ON/OFF"
    eficiencia_kwh_por_litro: float = 4.0816  # ~ (1/245)*1000, valor original da planilha

    def __post_init__(self) -> None:
        if self.nr_maquinas < 0 or self.nr_min_maquinas < 0:
            raise ValueError("nr_maquinas e nr_min_maquinas não podem ser negativos.")
        if self.nr_min_maquinas > self.nr_maquinas:
            raise ValueError("nr_min_maquinas não pode ser maior que nr_maquinas.")
        if self.pot_continua_kw < 0 or self.pot_prime_kva < 0:
            raise ValueError("Potências do gerador não podem ser negativas.")
        if not 0 < self.fp <= 1:
            raise ValueError("fp (fator de potência) deve estar no intervalo (0, 1].")
        if not 0 <= self.pot_min_pct <= 1:
            raise ValueError("pot_min_pct deve estar no intervalo [0, 1].")

    @property
    def pot_total_kw(self) -> float:
        """Potência contínua total do parque (kW). Equivale a ``D21``."""
        return self.pot_continua_kw * self.nr_maquinas

    @property
    def pot_prime_kw(self) -> float:
        """Potência prime por máquina, em kW (kVA x FP). Equivale a ``D14``."""
        return self.pot_prime_kva * self.fp

    @property
    def pot_minima_kw(self) -> float:
        """Piso de carga mínima do parque em operação (kW). Equivale a ``D22``."""
        return self.nr_min_maquinas * self.pot_prime_kw * self.pot_min_pct


@dataclass
class SolarConfig:
    """Configuração do sistema fotovoltaico.

    Espelha o bloco "FV" da aba Dimensionamento.
    """

    pot_inv_kw: float
    ilr: float = 1.4
    localizacao: str = "MT"

    def __post_init__(self) -> None:
        if self.pot_inv_kw < 0:
            raise ValueError("pot_inv_kw não pode ser negativa.")
        if self.ilr <= 0:
            raise ValueError("ilr deve ser positivo.")

    @property
    def pot_pico_kwp(self) -> float:
        """Potência de pico do arranjo FV (kWp). Equivale a ``G9``."""
        return self.pot_inv_kw * self.ilr


@dataclass
class EconomicConfig:
    """Parâmetros econômicos usados no motor financeiro (fase 3).

    Já inclui ``custo_bateria_rs_kw`` (custo do PCS/inversor do BESS), que
    não existia na planilha original (bug 1b da análise) — o capex do BESS
    lá era calculado só por R$/kWh.
    """

    custo_fv_rs_kwp: float = 6500.0
    custo_bateria_rs_kwh: float = 2000.0
    custo_bateria_rs_kw: float = 0.0
    preco_diesel_rs_litro: float = 7.0
    inflacao_diesel_am: float = 0.05
    tarifa_concessionaria_rs_kwh: float = 0.0
    inflacao_tarifa_am: float = 0.0
    tarifa_demanda_rs_kw: float = 0.0
    demanda_contratada_kw: float = 0.0
    tma_am: float = 0.05
    om_pct_am: float = 0.01
    tipo_pagamento: TipoPagamento = "RECURSO PRÓPRIO"
    pct_financiado: float = 0.0
    tipo_financiamento: TipoFinanciamento = "SAC"
    prazo_anos: int = 5
    carencia_anos: int = 0
    taxa_juros_am: float = 0.10
    degradacao_fv_am_ano: float = 0.006
    horizonte_anos: int = 25


@dataclass
class GrupoCargaConfig:
    """Configuração de um grupo de carga de irrigação (Grupo A ou B)."""

    potencia_kw: float
    lamina_projeto_mm_21h: float
    cultura_principal: str
    cultura_sucessao: Optional[str] = None


@dataclass
class OperacaoIrrigacaoConfig:
    """Configuração operacional do perfil de irrigação anual."""

    estado: str
    janela_operacao_horas: int = 10
    hora_inicio: int = 8
    alternancia: bool = False


@dataclass
class SimulationKPIs:
    """Indicadores agregados de uma simulação horária de 8760h."""

    energia_carga_total_kwh: float
    energia_solar_utilizada_kwh: float
    energia_bateria_descarregada_kwh: float
    energia_gerador_kwh: float
    energia_nao_suprida_kwh: float
    energia_curtailed_kwh: float
    horas_com_deficit: int
    fracao_solar: float = field(init=False)
    lolp: float = field(init=False)  # Loss of Load Probability (fração de horas com déficit)

    def __post_init__(self) -> None:
        self.fracao_solar = (
            self.energia_solar_utilizada_kwh / self.energia_carga_total_kwh
            if self.energia_carga_total_kwh > 0
            else 0.0
        )
        self.lolp = self.horas_com_deficit / 8760.0
