"""Curva de consumo de diesel do gerador (potência de saída x litros/hora).

O modelo antigo convertia energia em litros com uma eficiência constante
(kWh/L), o que ignora dois efeitos reais de um motor diesel: o consumo em
vazio (ligado, sem carga, já queima combustível) e a piora de eficiência em
carga baixa. Aqui o consumo de UMA máquina é uma função da potência que ela
entrega, interpolada linearmente entre pontos medidos.

Há uma única curva de referência (teste do BRG Slim Infinity 550 kVA), válida
para todos os modelos do catálogo: ``ModeloGerador.curva_consumo``
(``engine/generator_catalog.py``) a escala pela potência nominal e pelo consumo
de catálogo de cada modelo, então nenhum gerador precisa de curva própria.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass


@dataclass(frozen=True)
class CurvaConsumo:
    """Consumo de combustível de uma máquina em função da potência entregue.

    Attributes:
        pot_kw: potências (kW) dos pontos da curva, estritamente crescentes.
        consumo_l_h: consumo (L/h) em cada ponto, na mesma ordem de ``pot_kw``.
    """

    pot_kw: tuple[float, ...]
    consumo_l_h: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.pot_kw) != len(self.consumo_l_h):
            raise ValueError("pot_kw e consumo_l_h devem ter o mesmo número de pontos.")
        if len(self.pot_kw) < 2:
            raise ValueError("A curva precisa de ao menos 2 pontos.")
        if any(b <= a for a, b in zip(self.pot_kw, self.pot_kw[1:])):
            raise ValueError("pot_kw deve ser estritamente crescente.")
        if any(c < 0 for c in self.consumo_l_h):
            raise ValueError("consumo_l_h não pode ser negativo.")

    @property
    def consumo_em_vazio_l_h(self) -> float:
        """Consumo com o gerador ligado e sem carga (primeiro ponto da curva)."""
        return self.consumo_l_h[0]

    def consumo_l_h_em(self, pot_kw: float) -> float:
        """Consumo (L/h) na potência ``pot_kw``, por interpolação linear.

        Abaixo do primeiro ponto vale o consumo em vazio; acima do último, o
        último segmento é prolongado (na prática o despacho já limita a
        potência da máquina à sua potência contínua, dentro da faixa medida).
        """
        xs, ys = self.pot_kw, self.consumo_l_h
        if pot_kw <= xs[0]:
            return ys[0]
        i = min(bisect_right(xs, pot_kw), len(xs) - 1)
        x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
        return y0 + (y1 - y0) * (pot_kw - x0) / (x1 - x0)

    def escalada(self, fator_pot: float, fator_consumo: float) -> "CurvaConsumo":
        """Nova curva com as potências x ``fator_pot`` e os consumos x ``fator_consumo``."""
        return CurvaConsumo(
            pot_kw=tuple(p * fator_pot for p in self.pot_kw),
            consumo_l_h=tuple(c * fator_consumo for c in self.consumo_l_h),
        )


# Curva de referência: teste de consumo do BRG Slim Infinity 550 kVA (potência
# nominal 440 kW com FP 0,8; potência contínua 308 kW). Pontos medidos, sem
# suavização — inclusive o degrau entre 10 e 20 kW (5,6 -> 13,8 L/h), que é
# característica da medição em carga muito baixa.
POT_NOMINAL_REFERENCIA_KW = 440.0
CURVA_CONSUMO_REFERENCIA = CurvaConsumo(
    pot_kw=(
        0, 10, 20, 30, 41, 52, 63, 70, 81, 92,
        103, 114, 127, 138, 147, 158, 169, 176, 186, 197,
        207, 219, 225, 234, 255, 264, 275, 285, 296, 307,
        317, 329, 340, 350, 360, 373, 390, 399, 409,
    ),
    consumo_l_h=(
        4.3, 5.6, 13.8, 15.4, 16.0, 16.9, 18.7, 19.3, 21.3, 23.4,
        26.0, 28.7, 30.2, 32.1, 34.2, 37.8, 39.7, 41.1, 42.4, 44.5,
        48.2, 50.2, 51.2, 54.4, 58.5, 62.5, 63.5, 67.7, 68.5, 71.3,
        74.1, 77.2, 81.1, 82.6, 87.3, 91.3, 96.0, 99.6, 102.6,
    ),
)
