import json
from datetime import time

import numpy as np
import pytest

from engine.project_io import (
    SCHEMA_VERSION,
    ProjetoInvalidoError,
    desserializar,
    serializar,
)


def _projeto_exemplo():
    return {
        "home_cliente": "Fazenda Água Boa",
        "mapa_lat": -12.5,
        "hora_inicio_auto": False,
        "hora_inicio_irrigacao": time(8, 0),
        "pA": np.float64(110.0),
        "ger_nr": np.int64(2),
        "fv_modelo": None,
    }


def _configuracoes_exemplo():
    return {
        "cfg_custo_bess": 1800.0,
        "cfg_geradores_catalogo": [
            {"Modelo": "G1", "kVA": 550, "Consumo (L/h)": float("nan")},
        ],
    }


def test_round_trip_preserva_valores_e_tipos():
    texto = serializar(_projeto_exemplo(), _configuracoes_exemplo())
    carregado = desserializar(texto)

    assert carregado.schema_version == SCHEMA_VERSION
    assert carregado.projeto["home_cliente"] == "Fazenda Água Boa"
    assert carregado.projeto["hora_inicio_irrigacao"] == time(8, 0)
    assert carregado.projeto["pA"] == 110.0
    assert carregado.projeto["ger_nr"] == 2
    assert carregado.projeto["hora_inicio_auto"] is False
    assert "fv_modelo" not in carregado.projeto  # None não é gravado
    # NaN vira None dentro da linha do catálogo (JSON não tem NaN)
    assert carregado.configuracoes["cfg_geradores_catalogo"][0]["Consumo (L/h)"] is None
    assert carregado.avisos == []


def test_chaves_desconhecidas_e_tipos_invalidos_sao_descartados_com_aviso():
    documento = {
        "schema_version": SCHEMA_VERSION,
        "projeto": {"home_cliente": 123, "chave_maliciosa": "x", "pA": 5.0},
        "configuracoes": {"cfg_tma": True},
    }
    carregado = desserializar(json.dumps(documento))

    assert carregado.projeto == {"pA": 5.0}
    assert carregado.configuracoes == {}
    assert len(carregado.avisos) == 3


def test_json_quebrado_levanta_erro():
    with pytest.raises(ProjetoInvalidoError):
        desserializar("{nao eh json")


def test_documento_sem_schema_version_levanta_erro():
    with pytest.raises(ProjetoInvalidoError):
        desserializar(json.dumps({"projeto": {}}))


def test_versao_futura_levanta_erro():
    with pytest.raises(ProjetoInvalidoError):
        desserializar(json.dumps({"schema_version": SCHEMA_VERSION + 1, "projeto": {}, "configuracoes": {}}))


def test_arquivo_gigante_levanta_erro():
    with pytest.raises(ProjetoInvalidoError):
        desserializar(" " * 2_000_000)


def test_blocos_vazios_sao_validos():
    carregado = desserializar(serializar({}, None))
    assert carregado.projeto == {} and carregado.configuracoes == {}
    assert carregado.avisos == []


def test_tipos_numericos_sao_coagidos_ao_esperado_pelo_widget():
    # JSON vindo de JS/banco perde o ".0": 120.0 chega como 120; 5.0 como 5.
    documento = {
        "schema_version": SCHEMA_VERSION,
        "projeto": {"pA": 120, "ger_nr": 2.0, "bess_dod": 90},
        "configuracoes": {"cfg_tma": 5, "cfg_horizonte_anos": 25.0},
    }
    carregado = desserializar(json.dumps(documento))

    assert isinstance(carregado.projeto["pA"], float) and carregado.projeto["pA"] == 120.0
    assert isinstance(carregado.projeto["ger_nr"], int) and carregado.projeto["ger_nr"] == 2
    assert isinstance(carregado.projeto["bess_dod"], int)
    assert isinstance(carregado.configuracoes["cfg_tma"], float)
    assert isinstance(carregado.configuracoes["cfg_horizonte_anos"], int)


def test_inteiro_com_valor_fracionario_e_rejeitado():
    documento = {"schema_version": SCHEMA_VERSION, "projeto": {"ger_nr": 2.5}, "configuracoes": {}}
    carregado = desserializar(json.dumps(documento))
    assert carregado.projeto == {}
    assert len(carregado.avisos) == 1
