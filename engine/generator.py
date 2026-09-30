"""Modelo do parque de geradores diesel.

Corrige o bug identificado na planilha original: a fórmula de despacho do
gerador (coluna S de "Cálculo Técnico") nunca verificava se a potência
requisitada ultrapassava a potência nominal total do parque (`D21`). A
validação existente (`Dimensionamento!E17`) era estática (comparava `D21`
com a carga total agregada), não uma verificação hora a hora.

Aqui, ``Generator.dispatch`` aplica esse clamp explicitamente.
"""
from __future__ import annotations

import math
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

        Consumo de diesel: com ``config.curva_consumo``, é o das máquinas ligadas
        segundo a curva (inclui o consumo em vazio e a perda de eficiência em carga
        baixa; ver ``_maquinas_ativas``); sem curva, é a energia / eficiência (kWh/L).

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

        if self.config.curva_consumo is not None:
            # Ligado = entregando potência OU em "Sempre ON" com carga (nesse caso pode estar
            # em vazio, potência 0, e ainda assim queima o consumo em vazio da curva).
            ligado = potencia_kw > 0 or (self.config.modo == "Sempre ON" and carga_kw > 0)
            consumo_litros = self._consumo_pela_curva(potencia_kw, dt_h) if ligado else 0.0
        else:
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

    def _maquinas_ativas(self, potencia_kw: float) -> int:
        """Nº de máquinas ligadas para entregar ``potencia_kw`` (escalonamento automático).

        Liga o mínimo de máquinas que atende a potência sem passar da potência contínua
        de cada uma, nunca menos que ``nr_min_maquinas`` (nem menos que 1, já que o
        parque está ligado) e nunca mais que ``nr_maquinas``.
        """
        pot_continua_kw = self.config.pot_continua_kw
        necessarias = math.ceil(round(potencia_kw / pot_continua_kw, 9)) if pot_continua_kw > 0 else 1
        return min(self.config.nr_maquinas, max(self.config.nr_min_maquinas, necessarias, 1))

    def _consumo_pela_curva(self, potencia_kw: float, dt_h: float) -> float:
        """Litros consumidos no intervalo por ``n`` máquinas iguais dividindo a potência."""
        n = self._maquinas_ativas(potencia_kw)
        return n * self.config.curva_consumo.consumo_l_h_em(potencia_kw / n) * dt_h
