"""Catálogo de modelos de inversor fotovoltaico.

Análogo a ``engine/generator_catalog.py``: o usuário cadastra modelos de
inversor (nome + potência nominal) em ``views/configuracoes.py``, e a página
Simulação Técnica escolhe um modelo por nome em vez de digitar a potência
livremente. Ao rodar a Otimização, a potência ótima contínua (kW) é
arredondada para cima até o múltiplo inteiro mais próximo da potência
nominal do modelo escolhido — reflete que uma usina real é montada com N
unidades discretas de um inversor de catálogo, não uma potência arbitrária.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class ModeloInversor:
    """Um modelo de inversor cadastrado no catálogo (dado de placa/catálogo).

    Attributes:
        nome: identificação do modelo (livre, usado como rótulo no
            selectbox de Simulação Técnica — deve ser único no catálogo).
        pot_nominal_kw: potência nominal (ativa, CA) de uma unidade do
            inversor, em kW — valor de catálogo do fabricante.
    """

    nome: str
    pot_nominal_kw: float

    def __post_init__(self) -> None:
        if not self.nome:
            raise ValueError("nome do modelo não pode ser vazio.")
        if self.pot_nominal_kw <= 0:
            raise ValueError("pot_nominal_kw deve ser positiva.")

    def unidades_para(self, potencia_alvo_kw: float) -> int:
        """Nº de unidades deste modelo necessárias para atingir/superar
        ``potencia_alvo_kw`` (arredondamento para cima, mínimo 1)."""
        return max(1, math.ceil(potencia_alvo_kw / self.pot_nominal_kw))

    def potencia_final_kw(self, potencia_alvo_kw: float) -> float:
        """Potência total (kW) ao arredondar ``potencia_alvo_kw`` para cima
        até o múltiplo inteiro mais próximo de ``pot_nominal_kw``."""
        return self.unidades_para(potencia_alvo_kw) * self.pot_nominal_kw
