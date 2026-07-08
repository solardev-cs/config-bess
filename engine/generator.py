"""Modelo do parque de geradores diesel.

Corrige o bug identificado na planilha original: a fórmula de despacho do
gerador (coluna S de "Cálculo Técnico") nunca verificava se a potência
requisitada ultrapassava a potência nominal total do parque (`D21`). A
validação existente (`Dimensionamento!E17`) era estática (comparava `D21`
com a carga total agregada), não uma verificação hora a hora.

Aqui, ``Generator.dispatch`` aplica esse clamp explicitamente.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.models import GeneratorConfig


@dataclass
class GeneratorDispatchResult:
    """Resultado do despacho do gerador em uma hora."""

    potencia_kw: float
    consumo_litros: float
    ultrapassou_limite: bool  # True se a demanda pedida excedia pot_total_kw


class Generator:
    """Parque de geradores diesel, com despacho hora a hora.

    Args:
        config: parâmetros do parque de geradores.
    """

    def __init__(self, config: GeneratorConfig):
        self.config = config

    def dispatch(self, deficit_kw: float, carga_kw: float = 0.0, dt_h: float = 1.0) -> GeneratorDispatchResult:
        """Calcula a potência de saída do gerador para cobrir um déficit.

        Replica a lógica original da planilha (piso de carga mínima quando
        o parque está operando, respeitando o modo ON/OFF vs Sempre ON),
        mas agora limitando explicitamente a potência de saída à potência
        nominal total do parque (``pot_total_kw``) — o bug original nunca
        fazia esse clamp.

        Args:
            deficit_kw: potência que falta cobrir após solar + BESS
                (``E - (O + Q)`` na planilha original). Pode ser negativo
                (sobra) ou positivo (déficit).
            carga_kw: carga total da hora (``E`` na planilha original).
                Só é relevante no modo "Sempre ON", onde o gerador
                permanece ligado sempre que há carga (mesmo que
                solar+bateria já cubram 100% do déficit), respeitando o
                piso de carga mínima. É um comportamento INTENCIONAL da
                planilha original (genset sempre girando por confiabilidade),
                não um bug — mas precisa ser documentado explicitamente.
            dt_h: duração do intervalo de tempo, em horas.

        Returns:
            ``GeneratorDispatchResult`` com a potência de saída do
            gerador, o consumo de diesel no intervalo e um flag indicando
            se o déficit pedido ultrapassava a capacidade do parque
            (útil para relatar ao usuário que o parque está subdimensionado).
        """
        if self.config.nr_maquinas <= 0:
            return GeneratorDispatchResult(potencia_kw=0.0, consumo_litros=0.0, ultrapassou_limite=False)

        pot_minima = self.config.pot_minima_kw
        pot_total = self.config.pot_total_kw

        if self.config.modo == "ON/OFF":
            if deficit_kw > 0:
                potencia_kw = pot_minima if 0 < deficit_kw < pot_minima else deficit_kw
            else:
                potencia_kw = 0.0
        elif self.config.modo == "Sempre ON":
            if carga_kw > 0:
                potencia_kw = pot_minima if deficit_kw < pot_minima else deficit_kw
            else:
                potencia_kw = 0.0
        else:
            raise ValueError(f"Modo de gerador desconhecido: {self.config.modo}")

        ultrapassou_limite = potencia_kw > pot_total
        potencia_kw = min(potencia_kw, pot_total)

        consumo_litros = (
            potencia_kw * dt_h / self.config.eficiencia_kwh_por_litro
            if self.config.eficiencia_kwh_por_litro > 0
            else 0.0
        )

        return GeneratorDispatchResult(
            potencia_kw=potencia_kw,
            consumo_litros=consumo_litros,
            ultrapassou_limite=ultrapassou_limite,
        )
