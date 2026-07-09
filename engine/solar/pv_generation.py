"""Cálculo da potência de geração da usina fotovoltaica (8760h).

Este módulo isola a conversão de irradiância normalizada em potência DC
disponível do arranjo FV, antes do clipping do inversor. Na planilha
original essa etapa era a coluna ``L`` ("Pp_disp") da aba "Cálculo
Técnico", calculada como ``fracao_irradiancia * pot_pico_kwp`` — um
modelo puramente linear (GHI-scaling), sem nenhuma perda de sistema.

Aqui mantemos o mesmo modelo linear (adequado para o estágio atual do
projeto — um modelo físico completo com pvlib, transposição POA e efeito
de temperatura é uma evolução futura), mas adicionamos um fator de
"perdas de sistema" (sujeira, cabeamento CC/CA, mismatch entre módulos,
perdas de conexão, etc.), que a planilha original não modelava.

O valor padrão de 14% é uma aproximação de mercado consolidada (faixa
típica 10-14% para plantas FV bem projetadas, conforme literatura de
projeto fotovoltaico), usada aqui apenas como estimativa inicial —
ajustável via parâmetro.
"""
from __future__ import annotations

import numpy as np

from engine.models import SolarConfig

PERDAS_SISTEMA_PADRAO_PCT = 0.14


def gerar_potencia_fv(
    fracao_irradiancia: np.ndarray,
    solar_config: SolarConfig,
    perdas_sistema_pct: float = PERDAS_SISTEMA_PADRAO_PCT,
) -> np.ndarray:
    """Converte irradiância normalizada em potência DC disponível do arranjo FV.

    Args:
        fracao_irradiancia: array de 8760 posições com a fração de
            irradiância (0 a 1), normalizada pelo máximo anual observado
            (saída de ``SolarProfileProvider.get_normalized_profile``).
        solar_config: configuração do sistema FV (usa ``pot_pico_kwp``,
            derivado de ``pot_inv_kw * ilr``).
        perdas_sistema_pct: fração de perdas de sistema a aplicar (0 a 1).
            Representa perdas agregadas de sujeira, cabeamento, mismatch
            entre módulos etc. Valor padrão: 14%.

    Returns:
        Array de 8760 posições com a potência DC disponível do arranjo
        (kW), antes do clipping do inversor. Equivale à coluna ``L``
        ("Pp_disp") da planilha original, já líquida das perdas de sistema.

    Raises:
        ValueError: se ``fracao_irradiancia`` não tiver 8760 posições, ou
            se ``perdas_sistema_pct`` estiver fora do intervalo [0, 1).
    """
    if len(fracao_irradiancia) != 8760:
        raise ValueError(
            f"fracao_irradiancia deve ter 8760 posições, encontrado {len(fracao_irradiancia)}."
        )
    if not 0 <= perdas_sistema_pct < 1:
        raise ValueError("perdas_sistema_pct deve estar no intervalo [0, 1).")

    fator_perdas = 1.0 - perdas_sistema_pct
    return np.asarray(fracao_irradiancia, dtype=float) * solar_config.pot_pico_kwp * fator_perdas
