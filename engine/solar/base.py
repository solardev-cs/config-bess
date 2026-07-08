"""Interface comum para provedores de perfil de irradiância solar.

A planilha original tinha o perfil de irradiância "congelado" como valores
fixos (colados) para 3 estados (RS, MT, BA). Definir esta interface permite
trocar essa fonte estática por uma fonte dinâmica (ex.: API NSRDB da NREL,
com o usuário clicando num mapa) sem alterar o restante do motor de
cálculo — ``simulator.py`` e ``dispatch/*`` só dependem desta interface.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np


class SolarProfileProvider(Protocol):
    """Contrato que qualquer fonte de perfil solar deve implementar."""

    def get_normalized_profile(self) -> np.ndarray:
        """Retorna um array de 8760 posições com a fração de irradiância.

        Cada valor está no intervalo [0, 1], representando a fração da
        irradiância máxima anual observada naquela hora. Multiplicar esse
        array pela potência de pico do arranjo FV (kWp) fornece a potência
        disponível antes do clipping do inversor (equivalente à coluna
        ``L`` = "Pp_disp" da planilha original).
        """
        ...
