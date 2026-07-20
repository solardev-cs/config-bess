"""Catálogo de modelos de gerador diesel e derivação de suas potências.

Substitui os inputs manuais de "Potência Prime (kVA)", "Fator de Potência" e
"Potência Contínua por Máquina (kW)" (antes digitados à mão em Simulação
Técnica, sem relação com nenhum gerador real) por um catálogo de modelos
cadastrado em ``views/configuracoes.py``: o usuário informa apenas os 4 dados
de placa/catálogo do fabricante — nome do modelo, potência nominal (kVA),
consumo de combustível a plena carga (L/h) e fator de potência —, e todas as
demais potências (nominal em kW, prime, contínua) e a eficiência de consumo
(kWh/litro, usada por ``engine/costs.py`` para o custo de geração a diesel)
são derivadas automaticamente por fórmulas padrão de catálogo de geradores
diesel, em vez de ficarem soltas e editáveis sem vínculo entre si.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.models import GeneratorConfig, ModoGerador

# Razões padrão de catálogo (mercado de geradores diesel a partir da potência
# nominal em kVA): a potência prime é tipicamente 90% da nominal, e a
# potência contínua (a que o motor sustenta de forma segura e permanente,
# sem prazo limitado como a prime) gira em torno de 56% da nominal.
FATOR_PRIME_SOBRE_NOMINAL = 0.9
FATOR_CONTINUA_SOBRE_NOMINAL_KVA = 0.56


@dataclass
class ModeloGerador:
    """Um modelo de gerador cadastrado no catálogo (dados de placa/catálogo).

    Attributes:
        nome: identificação do modelo (livre, usado como rótulo no
            selectbox de Simulação Técnica — deve ser único no catálogo).
        pot_nominal_kva: potência nominal (standby) do gerador, em kVA —
            valor de catálogo do fabricante.
        consumo_l_h: consumo de combustível a plena carga contínua, em
            litros/hora — valor de catálogo do fabricante.
        fp: fator de potência do gerador (0 a 1).
        pot_min_pct: piso de carga mínima permitida pelo fabricante, como
            fração da potência prime (0 a 1) — evita operação prolongada em
            baixa carga (ruim para motores diesel, risco de "wet stacking").
    """

    nome: str
    pot_nominal_kva: float
    consumo_l_h: float
    fp: float = 0.8
    pot_min_pct: float = 0.0

    def __post_init__(self) -> None:
        if not self.nome:
            raise ValueError("nome do modelo não pode ser vazio.")
        if self.pot_nominal_kva <= 0:
            raise ValueError("pot_nominal_kva deve ser positiva.")
        if self.consumo_l_h <= 0:
            raise ValueError("consumo_l_h deve ser positivo.")
        if not 0 < self.fp <= 1:
            raise ValueError("fp deve estar no intervalo (0, 1].")
        if not 0 <= self.pot_min_pct <= 1:
            raise ValueError("pot_min_pct deve estar no intervalo [0, 1].")

    @property
    def pot_nominal_kw(self) -> float:
        """Potência nominal ativa (kW) = potência nominal (kVA) × FP."""
        return self.pot_nominal_kva * self.fp

    @property
    def pot_prime_kva(self) -> float:
        """Potência prime (kVA) = 90% da potência nominal (kVA)."""
        return self.pot_nominal_kva * FATOR_PRIME_SOBRE_NOMINAL

    @property
    def pot_prime_kw(self) -> float:
        """Potência prime ativa (kW) = potência prime (kVA) × FP."""
        return self.pot_prime_kva * self.fp

    @property
    def pot_continua_kw(self) -> float:
        """Potência contínua ativa (kW) = 56% da potência nominal (kVA)."""
        return self.pot_nominal_kva * FATOR_CONTINUA_SOBRE_NOMINAL_KVA

    @property
    def pot_continua_kva(self) -> float:
        """Potência contínua (kVA) = potência contínua ativa (kW) / FP."""
        return self.pot_continua_kw / self.fp

    @property
    def eficiencia_kwh_por_litro(self) -> float:
        """Eficiência de consumo (kWh/litro) = potência contínua ativa (kW)
        / consumo de combustível (L/h) — usada por
        ``engine/costs.py::custo_geracao_diesel_rs_kwh`` para converter o
        preço do diesel (R$/litro) em custo de geração (R$/kWh)."""
        return self.pot_continua_kw / self.consumo_l_h

    @property
    def pot_minima_kw(self) -> float:
        """Piso de carga mínima de UMA máquina (kW) = potência prime ativa
        (kW) × piso percentual (``pot_min_pct``) — mesma base de cálculo de
        ``GeneratorConfig.pot_minima_kw`` (``engine/models.py``), mas sem
        multiplicar pelo número de máquinas mínimas em operação."""
        return self.pot_prime_kw * self.pot_min_pct


def generator_config_from_modelo(
    modelo: ModeloGerador, nr_maquinas: int, nr_min_maquinas: int, modo: ModoGerador = "ON/OFF"
) -> GeneratorConfig:
    """Monta um ``GeneratorConfig`` a partir de um modelo do catálogo.

    Todas as potências e a eficiência de consumo do parque vêm do modelo
    escolhido — apenas a quantidade de máquinas e o modo de operação são
    parâmetros da simulação, não do gerador em si.
    """
    return GeneratorConfig(
        nr_maquinas=nr_maquinas,
        nr_min_maquinas=nr_min_maquinas,
        pot_continua_kw=modelo.pot_continua_kw,
        pot_prime_kva=modelo.pot_prime_kva,
        fp=modelo.fp,
        pot_min_pct=modelo.pot_min_pct,
        modo=modo,
        eficiencia_kwh_por_litro=modelo.eficiencia_kwh_por_litro,
    )
