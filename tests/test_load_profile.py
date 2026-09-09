"""Testes unitários do módulo de geração de perfil de carga (engine/load_profile.py)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.load_profile import (
    _dias_espacados,
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
        horas_min_por_dia=10,
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
        horas_min_por_dia=21,
        hora_inicio=0,
        alternancia=False,
    )
    balanco_por_mes = {b.mes: b for b in resultado.balanco_a}
    assert balanco_por_mes["Jan"].precisa_mm == pytest.approx(30.0)
    assert balanco_por_mes["Abr"].precisa_mm == pytest.approx(100.0)


def test_gerar_perfil_carga_gera_aviso_quando_deficit(df_ref):
    """Necessidade hídrica alta demais para o teto diário deve gerar déficit."""
    resultado = gerar_perfil_carga(
        df_ref=df_ref,
        estado="MT",
        grupo_a_potencia_kw=100.0,
        grupo_a_lamina_mm_21h=1.0,  # lâmina baixa -> exige muitas horas
        grupo_a_cultura_1="Milho safrinha",  # até 140mm em maio
        grupo_a_cultura_2=None,
        horas_min_por_dia=10,
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
        horas_min_por_dia=10,
        hora_inicio=8,
        alternancia=True,
        grupo_b_potencia_kw=50.0,
        grupo_b_lamina_mm_21h=9.0,
        grupo_b_cultura_1="Milho safrinha",
        grupo_b_cultura_2=None,
    )
    assert resultado.df["Grupo_B"].max() > 0
    assert len(resultado.balanco_b) > 0


# --- Concentração de horas por dia (horas_min_por_dia) ---


def _kwargs_soja(df_ref, **overrides):
    base = dict(
        df_ref=df_ref,
        estado="MT",
        grupo_a_potencia_kw=100.0,
        grupo_a_lamina_mm_21h=9.0,
        grupo_a_cultura_1="Soja",
        grupo_a_cultura_2=None,
        horas_min_por_dia=10,
        hora_inicio=0,
        alternancia=False,
    )
    base.update(overrides)
    return base


def test_horas_min_concentra_operacao_em_menos_dias(df_ref):
    """Jan (Soja MT): 30mm / (9/21) = 70h -> 7 dias a 10h/dia."""
    resultado = gerar_perfil_carga(**_kwargs_soja(df_ref, horas_min_por_dia=10))

    jan = resultado.df[resultado.df.index.month == 1]
    ativos = jan[jan["Grupo_A"] > 0]
    horas_por_dia = ativos.groupby(ativos.index.day).size()

    assert len(horas_por_dia) == 7
    assert (horas_por_dia == 10).all()

    balanco_jan = next(b for b in resultado.balanco_a if b.mes == "Jan")
    assert balanco_jan.dias_operacao == 7


def test_horas_min_mantem_lamina_mensal_exata(df_ref):
    resultado = gerar_perfil_carga(**_kwargs_soja(df_ref, horas_min_por_dia=12))

    for b in resultado.balanco_a:
        assert b.deficit_mm == pytest.approx(0.0)

    # Total de horas ativas no ano == soma das horas necessárias por mês
    # (70 + 117 + 47 + 24 + 47 + 70 para Soja MT com lâmina 9).
    total_ativas = int((resultado.df["Grupo_A"] > 0).sum())
    assert total_ativas == 70 + 117 + 47 + 24 + 47 + 70


def test_energia_anual_independe_de_horas_min(df_ref):
    """Mudar o mínimo remodela a curva mas não muda a energia total."""
    r_curto = gerar_perfil_carga(**_kwargs_soja(df_ref, horas_min_por_dia=6))
    r_longo = gerar_perfil_carga(**_kwargs_soja(df_ref, horas_min_por_dia=18))

    assert r_curto.df["Total_Load_kW"].sum() == pytest.approx(
        r_longo.df["Total_Load_kW"].sum()
    )


def test_horas_min_limitada_pelo_teto_do_horario_de_inicio(df_ref):
    """Início às 20h -> teto de 4h/dia (24 - 20); o mínimo de 10 é reduzido."""
    resultado = gerar_perfil_carga(
        **_kwargs_soja(df_ref, horas_min_por_dia=10, hora_inicio=20)
    )
    ativos = resultado.df[resultado.df["Grupo_A"] > 0]

    assert ativos.index.hour.min() >= 20  # nunca cruza a meia-noite
    horas_por_dia = ativos.groupby([ativos.index.month, ativos.index.day]).size()
    assert horas_por_dia.max() <= 4


def test_fallback_espalha_quando_mes_exige_todos_os_dias(df_ref):
    """Milho safrinha, Mai=140mm: 327h nao cabem em 10h/dia concentrados,
    mas cabem espalhadas por 31 dias dentro do teto de 21h."""
    resultado = gerar_perfil_carga(
        **_kwargs_soja(
            df_ref,
            grupo_a_cultura_1="Milho safrinha",
            horas_min_por_dia=10,
        )
    )
    maio = next(b for b in resultado.balanco_a if b.mes == "Mai")
    assert maio.dias_operacao == 31
    assert maio.deficit_mm == pytest.approx(0.0)


def test_fallback_gera_deficit_quando_ultrapassa_o_teto(df_ref):
    resultado = gerar_perfil_carga(
        **_kwargs_soja(
            df_ref,
            grupo_a_cultura_1="Milho safrinha",
            grupo_a_lamina_mm_21h=1.0,  # exige horas demais para qualquer teto
            horas_min_por_dia=10,
        )
    )
    maio = next(b for b in resultado.balanco_a if b.mes == "Mai")
    assert maio.deficit_mm > 0
    assert maio.dias_operacao == 31


def test_dias_espacados_mantem_intervalos_uniformes():
    dias = list(range(1, 31))  # 30 dias no mês

    sel = _dias_espacados(dias, 6)
    assert len(sel) == 6
    assert len(set(sel)) == 6
    gaps = [b - a for a, b in zip(sel, sel[1:])]
    assert max(gaps) - min(gaps) <= 1

    assert _dias_espacados(dias, 99) == dias
    assert _dias_espacados(dias, 0) == []
