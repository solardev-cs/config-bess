"""Testes unitários do módulo de geração de perfil de carga (engine/load_profile.py)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.load_profile import (
    calcular_horas_mensais,
    gerar_perfil_carga,
    obter_mm_mensal,
)


@pytest.fixture
def df_ref():
    return pd.DataFrame(
        [
            {
                "UF": "MT",
                "Cultura": "Soja",
                "Jan": 30,
                "Fev": 50,
                "Mar": 20,
                "Abr": 0,
                "Mai": 0,
                "Jun": 0,
                "Jul": 0,
                "Ago": 0,
                "Set": 0,
                "Out": 10,
                "Nov": 20,
                "Dez": 30,
            },
            {
                "UF": "MT",
                "Cultura": "Milho safrinha",
                "Jan": 0,
                "Fev": 10,
                "Mar": 50,
                "Abr": 100,
                "Mai": 140,
                "Jun": 130,
                "Jul": 40,
                "Ago": 0,
                "Set": 0,
                "Out": 0,
                "Nov": 0,
                "Dez": 0,
            },
        ]
    )


def test_obter_mm_mensal_retorna_zeros_para_nenhuma(df_ref):
    resultado = obter_mm_mensal(df_ref, "MT", "Nenhuma")
    assert np.array_equal(resultado, np.zeros(12))


def test_obter_mm_mensal_retorna_valores_da_cultura(df_ref):
    resultado = obter_mm_mensal(df_ref, "MT", "Soja")
    assert resultado[0] == 30
    assert resultado[1] == 50


def test_calcular_horas_mensais_zero_sem_lamina():
    assert calcular_horas_mensais(100, 0) == 0


def test_calcular_horas_mensais_arredonda_para_cima():
    # capacidade_mm_h = 9/21 ~ 0.4286; 30mm / 0.4286 ~ 70 horas
    horas = calcular_horas_mensais(30, 9.0)
    assert horas == 70


def test_gerar_perfil_carga_produz_8760_horas(df_ref):
    resultado = gerar_perfil_carga(
        df_ref=df_ref,
        estado="MT",
        grupo_a_potencia_kw=100.0,
        grupo_a_lamina_mm_21h=9.0,
        grupo_a_cultura_1="Soja",
        grupo_a_cultura_2=None,
        janela_operacao_horas=10,
        hora_inicio=8,
        alternancia=False,
    )
    assert len(resultado.df) == 8760
    assert "Total_Load_kW" in resultado.df.columns
    assert resultado.df["Total_Load_kW"].max() <= 100.0


def test_gerar_perfil_carga_sucessao_usa_maior_valor_mensal(df_ref):
    """Jan: Soja=30, Milho=0 -> usa 30. Abr: Soja=0, Milho=100 -> usa 100."""
    resultado = gerar_perfil_carga(
        df_ref=df_ref,
        estado="MT",
        grupo_a_potencia_kw=100.0,
        grupo_a_lamina_mm_21h=9.0,
        grupo_a_cultura_1="Soja",
        grupo_a_cultura_2="Milho safrinha",
        janela_operacao_horas=21,
        hora_inicio=0,
        alternancia=False,
    )
    balanco_por_mes = {b.mes: b for b in resultado.balanco_a}
    assert balanco_por_mes["Jan"].precisa_mm == pytest.approx(30.0)
    assert balanco_por_mes["Abr"].precisa_mm == pytest.approx(100.0)


def test_gerar_perfil_carga_gera_aviso_quando_deficit(df_ref):
    """Janela de operação muito pequena deve gerar déficit e aviso."""
    resultado = gerar_perfil_carga(
        df_ref=df_ref,
        estado="MT",
        grupo_a_potencia_kw=100.0,
        grupo_a_lamina_mm_21h=1.0,  # lâmina baixa -> exige muitas horas
        grupo_a_cultura_1="Milho safrinha",  # até 140mm em maio
        grupo_a_cultura_2=None,
        janela_operacao_horas=6,  # janela pequena
        hora_inicio=8,
        alternancia=False,
    )
    assert len(resultado.avisos) > 0


def test_gerar_perfil_carga_alternancia_ativa_grupo_b(df_ref):
    resultado = gerar_perfil_carga(
        df_ref=df_ref,
        estado="MT",
        grupo_a_potencia_kw=50.0,
        grupo_a_lamina_mm_21h=9.0,
        grupo_a_cultura_1="Soja",
        grupo_a_cultura_2=None,
        janela_operacao_horas=10,
        hora_inicio=8,
        alternancia=True,
        grupo_b_potencia_kw=50.0,
        grupo_b_lamina_mm_21h=9.0,
        grupo_b_cultura_1="Milho safrinha",
        grupo_b_cultura_2=None,
    )
    assert resultado.df["Grupo_B"].max() > 0
    assert len(resultado.balanco_b) > 0
