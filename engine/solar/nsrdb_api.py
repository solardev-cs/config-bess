"""Provedor dinâmico de perfil solar via API NSRDB (National Laboratory of
the Rockies — NLR, ex-NREL).

STATUS: implementado (Fase 2 do roadmap).

IMPORTANTE — mudança de domínio: em 29/05/2026 a NREL foi reorganizada como
"National Laboratory of the Rockies" (NLR) e o domínio da API de
desenvolvedores mudou de ``developer.nrel.gov`` para ``developer.nlr.gov``.
Este módulo já usa o domínio novo.

A planilha original usava dados no formato NSRDB PSM3/TMY (confirmado pelo
schema do Power Query embutido no arquivo: colunas Source, Location ID,
City, State, Country, Latitude, Longitude, Clearsky DHI/DNI/GHI, etc.), mas
os valores estavam "congelados" (colados como constante) para apenas 3
coordenadas fixas (RS, MT, BA). Este módulo permite que o usuário clique em
um mapa (lat/lon) e obtenha um perfil horário de 8760h diretamente da API,
para qualquer localização no Brasil.

Descoberta automática de dataset
---------------------------------
Nem toda coordenada tem um "Ano Meteorológico Típico" (TMY) sintético
disponível. Na prática (validado empiricamente com a API):

- Região Norte/Centro-Oeste do Brasil (ex.: MT, BA, GO, norte de MG):
  o dataset ``nsrdb-GOES-tmy-v4-0-0`` (TMY sintético baseado em GOES) está
  disponível.
- Região Sul/Sudeste (ex.: RS, SC, PR, SP): esse TMY NÃO está disponível;
  a API só oferece o dataset ``nsrdb-GOES-full-disc-v4-0-0``, que fornece
  dados de um ANO REAL específico (2018-2025), não um TMY sintético.

Este módulo consulta primeiro o endpoint de descoberta
(``/api/solar/nsrdb_data_query``) para essa coordenada e escolhe
automaticamente:
    1. ``nsrdb-GOES-tmy-v4-0-0`` (nome ``tmy``) se disponível — preferível,
       pois representa um ano climatologicamente "típico".
    2. Caso contrário, o ano mais recente disponível em
       ``nsrdb-GOES-full-disc-v4-0-0`` — um ano real, mas ainda assim uma
       fonte horária completa (8760h) e específica da coordenada.

Este provider implementa a mesma interface de ``SolarProfileProvider``
(``get_normalized_profile``), portanto pode substituir
``StaticTmySolarProvider`` sem qualquer alteração em ``simulator.py`` ou
``dispatch/*``.
"""
from __future__ import annotations

import hashlib
import io
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import requests

NLR_API_BASE = "https://developer.nlr.gov"
DATA_QUERY_ENDPOINT = f"{NLR_API_BASE}/api/solar/nsrdb_data_query.json"

# Nome do dataset TMY preferido (ano climatologicamente típico) e seu
# dataset de fallback (ano real), conforme observado empiricamente na API.
PREFERRED_TMY_DATASET = "nsrdb-GOES-tmy-v4-0-0"
FALLBACK_REAL_YEAR_DATASET = "nsrdb-GOES-full-disc-v4-0-0"

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "tmy" / "cache"


class NsrdbApiError(RuntimeError):
    """Erro ao consultar ou processar dados da API NSRDB/NLR."""


@dataclass
class NsrdbDatasetInfo:
    """Metadados de um dataset NSRDB disponível para uma coordenada."""

    name: str
    display_name: str
    api_url: str
    available_years: list


class NsrdbSolarProvider:
    """Provedor de perfil solar dinâmico via API NSRDB da NLR (ex-NREL).

    Args:
        lat: latitude do ponto de interesse (-90 a 90).
        lon: longitude do ponto de interesse (-180 a 180).
        api_key: chave de API da NLR (obtida em
            https://developer.nlr.gov/signup/).
        email: e-mail exigido pela API para a extração de dados (não é
            usado para envio de nada por este código; é apenas um campo
            obrigatório do request). ATENÇÃO: a API rejeita alguns
            endereços de e-mail "de exemplo" conhecidos (ex.:
            test@gmail.com, user@company.com) com erro 400 "must be a
            valid email address" — não é uma validação de formato, é uma
            blocklist de endereços de exemplo/documentação. Use um e-mail
            real ou um domínio próprio (ex.: algo@seudominio.com).
        attribute: atributo de irradiância a utilizar (default: "ghi").
        prefer_tmy: se True (default), tenta usar o dataset TMY sintético
            quando disponível na coordenada; caso contrário usa sempre o
            ano real mais recente disponível.
        cache_dir: diretório para cache em disco das respostas da API,
            evitando repetir requisições para a mesma coordenada (a API
            tem limite de taxa: 2000 requisições/dia, 1 a cada 2s).
        timeout_s: timeout de cada requisição HTTP, em segundos.
    """

    def __init__(
        self,
        lat: float,
        lon: float,
        api_key: str,
        email: str,
        attribute: str = "ghi",
        prefer_tmy: bool = True,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        timeout_s: float = 30.0,
    ):
        if not -90 <= lat <= 90:
            raise ValueError(f"Latitude fora do intervalo válido: {lat}")
        if not -180 <= lon <= 180:
            raise ValueError(f"Longitude fora do intervalo válido: {lon}")

        self.lat = lat
        self.lon = lon
        self.api_key = api_key
        self.email = email
        self.attribute = attribute
        self.prefer_tmy = prefer_tmy
        self.cache_dir = Path(cache_dir)
        self.timeout_s = timeout_s

        self._profile: Optional[np.ndarray] = None
        self.dataset_usado: Optional[str] = None
        self.ano_usado: Optional[str] = None

    # -- Cache -----------------------------------------------------------

    def _cache_key(self) -> str:
        """Chave de cache determinística baseada em lat/lon/atributo."""
        raw = f"{round(self.lat, 4)}_{round(self.lon, 4)}_{self.attribute}_{self.prefer_tmy}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _cache_paths(self) -> tuple[Path, Path]:
        key = self._cache_key()
        return self.cache_dir / f"{key}.csv", self.cache_dir / f"{key}.meta.json"

    def _load_from_cache(self) -> Optional[np.ndarray]:
        data_path, meta_path = self._cache_paths()
        if not data_path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.dataset_usado = meta.get("dataset")
            self.ano_usado = meta.get("ano")
            df = pd.read_csv(data_path)
            ghi = df["ghi_wm2"].to_numpy(dtype=float)
            if len(ghi) != 8760:
                return None
            return ghi
        except Exception:
            return None

    def _save_to_cache(self, ghi: np.ndarray, dataset: str, ano: str) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        data_path, meta_path = self._cache_paths()
        pd.DataFrame({"hour_of_year": np.arange(len(ghi)), "ghi_wm2": ghi}).to_csv(data_path, index=False)
        meta_path.write_text(
            json.dumps({"dataset": dataset, "ano": ano, "lat": self.lat, "lon": self.lon}),
            encoding="utf-8",
        )

    # -- Descoberta de datasets ------------------------------------------

    def _discover_datasets(self) -> list[NsrdbDatasetInfo]:
        """Consulta o endpoint de descoberta para listar datasets disponíveis
        na coordenada configurada.

        Returns:
            Lista de ``NsrdbDatasetInfo`` disponíveis (pode ser vazia se
            não houver cobertura NSRDB para a coordenada).

        Raises:
            NsrdbApiError: se a requisição falhar.
        """
        params = {
            "api_key": self.api_key,
            "wkt": f"POINT({self.lon} {self.lat})",
        }
        try:
            response = requests.get(DATA_QUERY_ENDPOINT, params=params, timeout=self.timeout_s)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise NsrdbApiError(f"Falha ao consultar datasets disponíveis: {exc}") from exc

        payload = response.json()
        errors = payload.get("errors") or []
        if errors:
            raise NsrdbApiError(f"API NSRDB retornou erro na descoberta: {errors}")

        datasets = []
        for item in payload.get("outputs", []):
            datasets.append(
                NsrdbDatasetInfo(
                    name=item.get("name", ""),
                    display_name=item.get("displayName", ""),
                    api_url=item.get("apiUrl", ""),
                    available_years=item.get("availableYears", []),
                )
            )
        return datasets

    def _pick_dataset_and_year(
        self, datasets: list[NsrdbDatasetInfo]
    ) -> tuple[NsrdbDatasetInfo, str]:
        """Escolhe o melhor dataset/ano disponível para a coordenada.

        Prioridade:
            1. Dataset TMY preferido (``PREFERRED_TMY_DATASET``), usando o
               nome de ano ``"tmy"`` (sempre resolve para o TMY mais
               recente disponível), se ``prefer_tmy=True``.
            2. Dataset de fallback (``FALLBACK_REAL_YEAR_DATASET``), usando
               o ano mais recente disponível (dado real, não sintético).

        Raises:
            NsrdbApiError: se nenhum dataset compatível estiver disponível
                para a coordenada.
        """
        by_name = {d.name: d for d in datasets}

        if self.prefer_tmy and PREFERRED_TMY_DATASET in by_name:
            tmy_dataset = by_name[PREFERRED_TMY_DATASET]
            if "tmy" in tmy_dataset.available_years:
                return tmy_dataset, "tmy"

        if FALLBACK_REAL_YEAR_DATASET in by_name:
            fallback_dataset = by_name[FALLBACK_REAL_YEAR_DATASET]
            anos_numericos = [y for y in fallback_dataset.available_years if isinstance(y, int)]
            if anos_numericos:
                ano_mais_recente = str(max(anos_numericos))
                return fallback_dataset, ano_mais_recente

        # Último recurso: qualquer dataset disponível com >=1 ano numérico ou "tmy".
        for dataset in datasets:
            if "tmy" in dataset.available_years:
                return dataset, "tmy"
            anos_numericos = [y for y in dataset.available_years if isinstance(y, int)]
            if anos_numericos:
                return dataset, str(max(anos_numericos))

        raise NsrdbApiError(
            f"Nenhum dataset NSRDB com cobertura horária foi encontrado para "
            f"lat={self.lat}, lon={self.lon}. Datasets retornados: "
            f"{[d.name for d in datasets]}"
        )

    # -- Download e parsing ------------------------------------------------

    def _fetch_csv(self, dataset: NsrdbDatasetInfo, ano: str) -> str:
        """Faz a requisição HTTP à API NSRDB e retorna o CSV bruto.

        Raises:
            NsrdbApiError: se a requisição falhar (inclui erros 400 da API,
                que geralmente indicam falta de cobertura para o
                atributo/ano/coordenada solicitados).
        """
        params = {
            "api_key": self.api_key,
            "email": self.email,
            "wkt": f"POINT({self.lon} {self.lat})",
            "attributes": self.attribute,
            "names": ano,
            "interval": "60",
            "utc": "false",
            "leap_day": "false",
        }
        download_url = f"{dataset.api_url}.csv"
        try:
            response = requests.get(download_url, params=params, timeout=self.timeout_s)
        except requests.RequestException as exc:
            raise NsrdbApiError(f"Falha de rede ao baixar dados NSRDB: {exc}") from exc

        if response.status_code != 200:
            raise NsrdbApiError(
                f"API NSRDB retornou status {response.status_code} para "
                f"dataset='{dataset.name}', ano='{ano}': {response.text[:300]}"
            )
        return response.text

    def _parse_ghi(self, raw_csv: str) -> np.ndarray:
        """Extrai a série horária de GHI (8760 valores) do CSV retornado.

        O formato de resposta tem 2 linhas de metadados no topo, seguidas
        do cabeçalho de dados (``Year,Month,Day,Hour,Minute,<ATRIBUTO>``).
        """
        df = pd.read_csv(io.StringIO(raw_csv), skiprows=2)
        col = next((c for c in df.columns if c.upper() == self.attribute.upper()), None)
        if col is None:
            raise NsrdbApiError(
                f"Coluna '{self.attribute}' não encontrada na resposta da API NSRDB. "
                f"Colunas disponíveis: {list(df.columns)}"
            )
        ghi = df[col].to_numpy(dtype=float)

        # Alguns anos reais podem incluir dia bissexto mesmo com
        # leap_day=false, dependendo do dataset; garante exatamente 8760.
        if len(ghi) == 8784:
            # Remove o 29 de fevereiro (últimas 24h do dia 60, considerando
            # ano começando em 1º de janeiro) — aproximação segura para
            # manter a série em 8760h.
            ghi = np.delete(ghi, slice(24 * 59, 24 * 60))
        if len(ghi) != 8760:
            raise NsrdbApiError(
                f"Resposta da API NSRDB retornou {len(ghi)} horas, esperado 8760 "
                f"(dataset/ano podem ter resolução diferente de 60 min)."
            )
        return ghi

    # -- Interface pública -------------------------------------------------

    def get_normalized_profile(self, use_cache: bool = True) -> np.ndarray:
        """Retorna a fração de irradiância horária normalizada pelo máximo anual.

        Args:
            use_cache: se True (default), tenta reaproveitar uma resposta
                em cache no disco para a mesma coordenada antes de chamar
                a API novamente.

        Returns:
            Array de 8760 posições com a fração de irradiância (0 a 1).

        Raises:
            NsrdbApiError: se não for possível obter dados válidos da API
                (sem cobertura para a coordenada, erro de rede, etc.).
        """
        if self._profile is not None:
            return self._profile

        if use_cache:
            cached = self._load_from_cache()
            if cached is not None:
                maximo = cached.max()
                self._profile = cached / maximo if maximo > 0 else np.zeros_like(cached)
                return self._profile

        datasets = self._discover_datasets()
        dataset, ano = self._pick_dataset_and_year(datasets)

        raw_csv = self._fetch_csv(dataset, ano)
        ghi = self._parse_ghi(raw_csv)

        self.dataset_usado = dataset.name
        self.ano_usado = ano

        if use_cache:
            self._save_to_cache(ghi, dataset.name, ano)

        maximo = ghi.max()
        self._profile = ghi / maximo if maximo > 0 else np.zeros_like(ghi)
        return self._profile
