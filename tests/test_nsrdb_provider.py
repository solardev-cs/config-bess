"""Testes unitários do provedor dinâmico de perfil solar via API NSRDB/NLR.

Usa mocks de ``requests`` para não depender de rede real nem consumir a
cota de requisições da API durante a suíte de testes automatizada.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from engine.solar.nsrdb_api import (
    FALLBACK_REAL_YEAR_DATASET,
    PREFERRED_TMY_DATASET,
    NsrdbApiError,
    NsrdbSolarProvider,
)


def _mock_discovery_response(datasets: list[dict]) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"errors": [], "outputs": datasets}
    response.raise_for_status = MagicMock()
    return response


def _mock_csv_response(status_code: int, ghi_values: np.ndarray | None = None, error_text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    if status_code == 200 and ghi_values is not None:
        header = "Source,Location ID\nNSRDB,123\nYear,Month,Day,Hour,Minute,GHI\n"
        rows = "\n".join(f"2023,1,1,{i},0,{v}" for i, v in enumerate(ghi_values[:24]))
        # Gera exatamente 8760 linhas de dados simples.
        rows = "\n".join(f"2023,1,1,{i % 24},0,{v}" for i, v in enumerate(ghi_values))
        response.text = header + rows
    else:
        response.text = error_text
    return response


@pytest.fixture
def ghi_8760():
    """Série sintética de 8760 valores de GHI com um pico conhecido."""
    rng = np.random.default_rng(42)
    values = rng.uniform(0, 900, size=8760)
    values[100] = 1000.0  # pico conhecido
    return values


def test_pick_dataset_prefere_tmy_quando_disponivel():
    provider = NsrdbSolarProvider(lat=-12.54, lon=-55.45, api_key="key", email="a@b.com")
    datasets = [
        MagicMock(name=PREFERRED_TMY_DATASET, available_years=["tmy", "tmy-2023"]),
        MagicMock(name=FALLBACK_REAL_YEAR_DATASET, available_years=[2022, 2023, 2024]),
    ]
    # MagicMock's `.name` attr needs explicit assignment (constructor `name=` is special)
    for d, n in zip(datasets, [PREFERRED_TMY_DATASET, FALLBACK_REAL_YEAR_DATASET]):
        d.name = n

    dataset, ano = provider._pick_dataset_and_year(datasets)
    assert dataset.name == PREFERRED_TMY_DATASET
    assert ano == "tmy"


def test_pick_dataset_fallback_para_ano_real_quando_sem_tmy():
    provider = NsrdbSolarProvider(lat=-30.03, lon=-51.23, api_key="key", email="a@b.com")
    dataset_fallback = MagicMock(available_years=[2022, 2023, 2025])
    dataset_fallback.name = FALLBACK_REAL_YEAR_DATASET

    dataset, ano = provider._pick_dataset_and_year([dataset_fallback])
    assert dataset.name == FALLBACK_REAL_YEAR_DATASET
    assert ano == "2025"  # deve escolher o ano mais recente


def test_pick_dataset_levanta_erro_sem_datasets_compativeis():
    provider = NsrdbSolarProvider(lat=0.0, lon=0.0, api_key="key", email="a@b.com")
    with pytest.raises(NsrdbApiError):
        provider._pick_dataset_and_year([])


def test_lat_lon_invalidos_levantam_erro():
    with pytest.raises(ValueError):
        NsrdbSolarProvider(lat=999, lon=0, api_key="key", email="a@b.com")
    with pytest.raises(ValueError):
        NsrdbSolarProvider(lat=0, lon=999, api_key="key", email="a@b.com")


@patch("engine.solar.nsrdb_api.requests.get")
def test_get_normalized_profile_fluxo_completo_tmy(mock_get, ghi_8760, tmp_path):
    """Fluxo completo: descoberta -> escolha do TMY -> download -> parsing -> normalização."""
    discovery_resp = _mock_discovery_response(
        [
            {
                "name": PREFERRED_TMY_DATASET,
                "displayName": "NSRDB GOES Tmy V4.0.0",
                "apiUrl": "https://developer.nlr.gov/api/nsrdb/v2/solar/nsrdb-GOES-tmy-v4-0-0-download",
                "availableYears": ["tmy", "tmy-2023"],
            }
        ]
    )
    csv_resp = _mock_csv_response(200, ghi_values=ghi_8760)
    mock_get.side_effect = [discovery_resp, csv_resp]

    provider = NsrdbSolarProvider(
        lat=-12.54, lon=-55.45, api_key="key", email="a@b.com", cache_dir=tmp_path
    )
    profile = provider.get_normalized_profile(use_cache=False)

    assert len(profile) == 8760
    assert profile.max() == pytest.approx(1.0)
    assert profile.min() >= 0.0
    assert provider.dataset_usado == PREFERRED_TMY_DATASET
    assert provider.ano_usado == "tmy"


@patch("engine.solar.nsrdb_api.requests.get")
def test_get_normalized_profile_fallback_ano_real(mock_get, ghi_8760, tmp_path):
    """Quando não há TMY disponível, deve usar o dataset de ano real (fallback)."""
    discovery_resp = _mock_discovery_response(
        [
            {
                "name": FALLBACK_REAL_YEAR_DATASET,
                "displayName": "NSRDB GOES Full Disc V4.0.0",
                "apiUrl": "https://developer.nlr.gov/api/nsrdb/v2/solar/nsrdb-GOES-full-disc-v4-0-0-download",
                "availableYears": [2022, 2023, 2024, 2025],
            }
        ]
    )
    csv_resp = _mock_csv_response(200, ghi_values=ghi_8760)
    mock_get.side_effect = [discovery_resp, csv_resp]

    provider = NsrdbSolarProvider(
        lat=-30.03, lon=-51.23, api_key="key", email="a@b.com", cache_dir=tmp_path
    )
    profile = provider.get_normalized_profile(use_cache=False)

    assert len(profile) == 8760
    assert provider.dataset_usado == FALLBACK_REAL_YEAR_DATASET
    assert provider.ano_usado == "2025"


@patch("engine.solar.nsrdb_api.requests.get")
def test_get_normalized_profile_sem_cobertura_levanta_erro(mock_get, tmp_path):
    discovery_resp = _mock_discovery_response([])
    mock_get.side_effect = [discovery_resp]

    provider = NsrdbSolarProvider(
        lat=0.0, lon=0.0, api_key="key", email="a@b.com", cache_dir=tmp_path
    )
    with pytest.raises(NsrdbApiError):
        provider.get_normalized_profile(use_cache=False)


@patch("engine.solar.nsrdb_api.requests.get")
def test_get_normalized_profile_erro_400_na_descoberta(mock_get, tmp_path):
    error_resp = MagicMock()
    error_resp.status_code = 400
    error_resp.json.return_value = {"errors": ["No data available at the provided location"]}
    error_resp.raise_for_status = MagicMock()
    mock_get.side_effect = [error_resp]

    provider = NsrdbSolarProvider(
        lat=0.0, lon=0.0, api_key="key", email="a@b.com", cache_dir=tmp_path
    )
    with pytest.raises(NsrdbApiError):
        provider.get_normalized_profile(use_cache=False)


@patch("engine.solar.nsrdb_api.requests.get")
def test_get_normalized_profile_erro_400_no_download(mock_get, tmp_path):
    discovery_resp = _mock_discovery_response(
        [
            {
                "name": PREFERRED_TMY_DATASET,
                "displayName": "NSRDB GOES Tmy V4.0.0",
                "apiUrl": "https://developer.nlr.gov/api/nsrdb/v2/solar/nsrdb-GOES-tmy-v4-0-0-download",
                "availableYears": ["tmy"],
            }
        ]
    )
    csv_resp = _mock_csv_response(400, error_text='{"errors": ["Bad Request"]}')
    mock_get.side_effect = [discovery_resp, csv_resp]

    provider = NsrdbSolarProvider(
        lat=-12.54, lon=-55.45, api_key="key", email="a@b.com", cache_dir=tmp_path
    )
    with pytest.raises(NsrdbApiError):
        provider.get_normalized_profile(use_cache=False)


@patch("engine.solar.nsrdb_api.requests.get")
def test_cache_evita_segunda_chamada_a_api(mock_get, ghi_8760, tmp_path):
    """Uma segunda instância com a mesma coordenada deve reaproveitar o cache em disco."""
    discovery_resp = _mock_discovery_response(
        [
            {
                "name": PREFERRED_TMY_DATASET,
                "displayName": "NSRDB GOES Tmy V4.0.0",
                "apiUrl": "https://developer.nlr.gov/api/nsrdb/v2/solar/nsrdb-GOES-tmy-v4-0-0-download",
                "availableYears": ["tmy"],
            }
        ]
    )
    csv_resp = _mock_csv_response(200, ghi_values=ghi_8760)
    mock_get.side_effect = [discovery_resp, csv_resp]

    provider1 = NsrdbSolarProvider(
        lat=-12.54, lon=-55.45, api_key="key", email="a@b.com", cache_dir=tmp_path
    )
    profile1 = provider1.get_normalized_profile(use_cache=True)
    assert mock_get.call_count == 2  # descoberta + download

    # Segunda instância: NÃO deve chamar requests.get novamente.
    provider2 = NsrdbSolarProvider(
        lat=-12.54, lon=-55.45, api_key="key", email="a@b.com", cache_dir=tmp_path
    )
    profile2 = provider2.get_normalized_profile(use_cache=True)

    assert mock_get.call_count == 2  # não aumentou
    assert np.allclose(profile1, profile2)
    assert provider2.dataset_usado == PREFERRED_TMY_DATASET
    assert provider2.ano_usado == "tmy"


@patch("engine.solar.nsrdb_api.requests.get")
def test_profile_e_memoizado_na_mesma_instancia(mock_get, ghi_8760, tmp_path):
    """Chamar get_normalized_profile duas vezes na MESMA instância não deve
    refazer a requisição (memoização em memória).
    """
    discovery_resp = _mock_discovery_response(
        [
            {
                "name": PREFERRED_TMY_DATASET,
                "displayName": "NSRDB GOES Tmy V4.0.0",
                "apiUrl": "https://developer.nlr.gov/api/nsrdb/v2/solar/nsrdb-GOES-tmy-v4-0-0-download",
                "availableYears": ["tmy"],
            }
        ]
    )
    csv_resp = _mock_csv_response(200, ghi_values=ghi_8760)
    mock_get.side_effect = [discovery_resp, csv_resp]

    provider = NsrdbSolarProvider(
        lat=-12.54, lon=-55.45, api_key="key", email="a@b.com", cache_dir=tmp_path
    )
    provider.get_normalized_profile(use_cache=False)
    provider.get_normalized_profile(use_cache=False)

    assert mock_get.call_count == 2  # não dobrou
