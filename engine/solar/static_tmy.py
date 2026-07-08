"""Provedor estático de perfil solar, baseado em TMY fixo por estado.

Substitui as colunas ``G/H/I`` ("TMY_RS", "TMY_MT", "TMY_BA") da aba
"Cálculo Técnico" da planilha original, que continham 8760 valores de
irradiância (GHI, W/m²) colados como constantes — extraídos originalmente
via Power Query do NSRDB (NREL), mas desconectados da fonte dinâmica.

Correção importante em relação à planilha original: os divisores de
normalização (``H4``/``I4``, usados para MT e BA) estavam hardcoded em
valores desatualizados (1260 e 1540), enquanto o máximo real das séries é
1078 e 1106 respectivamente. Isso fazia a fração de irradiância nunca
atingir 1.0 para esses dois estados, subestimando a geração solar em
todas as horas do ano. Aqui, a normalização sempre usa o máximo real da
própria série (equivalente ao que já era feito corretamente para RS via
``G4 = MAX(G6:G8765)``).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "tmy"

ESTADOS_DISPONIVEIS = ("RS", "MT", "BA")


class StaticTmySolarProvider:
    """Provedor de perfil solar a partir de um arquivo TMY estático local.

    Args:
        estado: sigla da UF (uma das ``ESTADOS_DISPONIVEIS``).
        data_dir: diretório onde os CSVs ``{UF}.csv`` estão armazenados.
            Cada arquivo deve ter as colunas ``hour_of_year`` (0-8759) e
            ``ghi_wm2`` (irradiância horária, W/m²).
    """

    def __init__(self, estado: str, data_dir: Path | str = DATA_DIR):
        if estado not in ESTADOS_DISPONIVEIS:
            raise ValueError(f"Estado '{estado}' não suportado. Disponíveis: {ESTADOS_DISPONIVEIS}")
        self.estado = estado
        self.data_dir = Path(data_dir)
        self._profile: np.ndarray | None = None

    def _load(self) -> np.ndarray:
        path = self.data_dir / f"{self.estado}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Arquivo TMY não encontrado: {path}")
        df = pd.read_csv(path)
        ghi = df["ghi_wm2"].to_numpy(dtype=float)
        if len(ghi) != 8760:
            raise ValueError(f"Arquivo TMY de '{self.estado}' deve ter 8760 linhas, encontrado {len(ghi)}.")
        return ghi

    def get_normalized_profile(self) -> np.ndarray:
        """Retorna a fração de irradiância horária normalizada pelo máximo anual."""
        if self._profile is None:
            ghi = self._load()
            maximo = ghi.max()
            self._profile = ghi / maximo if maximo > 0 else np.zeros_like(ghi)
        return self._profile
