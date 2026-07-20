"""Catálogo de modelos de BESS (banco de baterias).

Análogo a ``engine/generator_catalog.py`` e ``engine/inverter_catalog.py``:
o usuário cadastra modelos de BESS (nome, capacidade nominal, potência
nominal e eficiência round-trip) em ``views/configuracoes.py``. A eficiência
deixa de ser um slider manual em Simulação Técnica — passa a vir do modelo
escolhido, como a eficiência de consumo do gerador já vem do seu catálogo.
Ao rodar a Otimização, a capacidade ótima (kWh) é arredondada para cima até
o múltiplo inteiro mais próximo da capacidade nominal do modelo escolhido —
reflete que um banco de baterias real é montado com N unidades/racks
discretos de um modelo de catálogo, não uma capacidade arbitrária.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class ModeloBess:
    """Um modelo de BESS cadastrado no catálogo (dado de placa/catálogo).

    Attributes:
        nome: identificação do modelo (livre, usado como rótulo no
            selectbox de Simulação Técnica — deve ser único no catálogo).
        capacidade_nominal_kwh: capacidade nominal de energia de uma
            unidade do BESS, em kWh — valor de catálogo do fabricante.
        pot_nominal_kw: potência nominal (carga/descarga) de uma unidade
            do BESS, em kW — valor de catálogo do fabricante.
        eficiencia_pct: eficiência round-trip do BESS (0 a 100, em %) —
            valor de catálogo do fabricante.
    """

    nome: str
    capacidade_nominal_kwh: float
    pot_nominal_kw: float
    eficiencia_pct: float

    def __post_init__(self) -> None:
        if not self.nome:
            raise ValueError("nome do modelo não pode ser vazio.")
        if self.capacidade_nominal_kwh <= 0:
            raise ValueError("capacidade_nominal_kwh deve ser positiva.")
        if self.pot_nominal_kw <= 0:
            raise ValueError("pot_nominal_kw deve ser positiva.")
        if not 0 < self.eficiencia_pct <= 100:
            raise ValueError("eficiencia_pct deve estar no intervalo (0, 100].")

    @property
    def eficiencia_rt(self) -> float:
        """Eficiência round-trip como fração (0 a 1), para
        ``BatteryConfig.eficiencia_rt`` (``engine/models.py``)."""
        return self.eficiencia_pct / 100.0

    @property
    def c_rate(self) -> float:
        """C-rate do modelo = potência nominal (kW) / capacidade nominal
        (kWh) — não é mais um input manual em Simulação Técnica, já que a
        capacidade e a potência totais do BESS são sempre múltiplos do
        mesmo nº de unidades deste modelo, então a razão entre elas
        (o C-rate) é fixa pelo catálogo, independente de quantas unidades
        forem instaladas. Usado como ``BatteryConfig.c_rate``."""
        return self.pot_nominal_kw / self.capacidade_nominal_kwh

    def unidades_para(self, capacidade_alvo_kwh: float) -> int:
        """Nº de unidades deste modelo necessárias para atingir/superar
        ``capacidade_alvo_kwh`` (arredondamento para cima, mínimo 1)."""
        return max(1, math.ceil(capacidade_alvo_kwh / self.capacidade_nominal_kwh))

    def capacidade_final_kwh(self, capacidade_alvo_kwh: float) -> float:
        """Capacidade total (kWh) ao arredondar ``capacidade_alvo_kwh`` para
        cima até o múltiplo inteiro mais próximo de
        ``capacidade_nominal_kwh``."""
        return self.unidades_para(capacidade_alvo_kwh) * self.capacidade_nominal_kwh
