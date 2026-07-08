"""Provedor dinâmico de perfil solar via API NSRDB (NREL).

STATUS: stub de interface (Fase 2 do roadmap). A implementação completa
será feita quando a API key da NREL estiver disponível
(https://developer.nrel.gov/docs/solar/nsrdb/).

A planilha original já usava dados no formato NSRDB PSM3/TMY (confirmado
pelo schema do Power Query embutido no arquivo: colunas Source, Location
ID, City, State, Country, Latitude, Longitude, Clearsky DHI/DNI/GHI, etc.),
mas os valores estavam "congelados" (colados como constante) para apenas
3 coordenadas fixas (RS, MT, BA). Este módulo permitirá que o usuário
clique em um mapa (lat/lon) e obtenha um perfil horário de 8760h
diretamente da API, para qualquer localização no Brasil.

Este provider implementa a mesma interface de ``SolarProfileProvider``
(``get_normalized_profile``), portanto pode substituir
``StaticTmySolarProvider`` sem qualquer alteração em ``simulator.py`` ou
``dispatch/*``.
"""
from __future__ import annotations

import numpy as np
import requests

NSRDB_PSM3_ENDPOINT = "https://developer.nrel.gov/api/nsrdb/v2/solar/psm3-tmy-download.csv"


class NsrdbSolarProvider:
    """Provedor de perfil solar dinâmico via API NSRDB da NREL.

    Args:
        lat: latitude do ponto de interesse.
        lon: longitude do ponto de interesse.
        api_key: chave de API da NREL (obtida em
            https://developer.nrel.gov/signup/).
        attribute: atributo de irradiância a utilizar (default: "ghi").
        timeout_s: timeout da requisição HTTP, em segundos.
    """

    def __init__(
        self,
        lat: float,
        lon: float,
        api_key: str,
        attribute: str = "ghi",
        timeout_s: float = 30.0,
    ):
        self.lat = lat
        self.lon = lon
        self.api_key = api_key
        self.attribute = attribute
        self.timeout_s = timeout_s
        self._profile: np.ndarray | None = None

    def _fetch_raw_csv(self) -> str:
        """Faz a requisição HTTP à API NSRDB e retorna o CSV bruto.

        Levanta ``requests.HTTPError`` em caso de falha na requisição.
        """
        params = {
            "api_key": self.api_key,
            "wkt": f"POINT({self.lon} {self.lat})",
            "names": "tmy",
            "attributes": self.attribute,
            "interval": "60",
            "utc": "false",
        }
        response = requests.get(NSRDB_PSM3_ENDPOINT, params=params, timeout=self.timeout_s)
        response.raise_for_status()
        return response.text

    def _parse_ghi(self, raw_csv: str) -> np.ndarray:
        """Extrai a série horária de GHI (8760 valores) do CSV do NSRDB.

        O formato PSM3 tem 2 linhas de metadados no topo, seguidas do
        cabeçalho e dos dados horários.
        """
        import io

        import pandas as pd

        df = pd.read_csv(io.StringIO(raw_csv), skiprows=2)
        col = next((c for c in df.columns if c.upper() == self.attribute.upper()), None)
        if col is None:
            raise ValueError(f"Coluna '{self.attribute}' não encontrada na resposta da API NSRDB.")
        ghi = df[col].to_numpy(dtype=float)
        if len(ghi) != 8760:
            raise ValueError(f"Resposta da API NSRDB retornou {len(ghi)} horas, esperado 8760.")
        return ghi

    def get_normalized_profile(self) -> np.ndarray:
        """Retorna a fração de irradiância horária normalizada pelo máximo anual."""
        if self._profile is None:
            raw_csv = self._fetch_raw_csv()
            ghi = self._parse_ghi(raw_csv)
            maximo = ghi.max()
            self._profile = ghi / maximo if maximo > 0 else np.zeros_like(ghi)
        return self._profile
