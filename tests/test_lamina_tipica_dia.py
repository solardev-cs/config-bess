import pandas as pd

from engine.load_profile import MESES_NOMES, gerar_perfil_carga


def _df_ref(mm_por_mes):
    linha = {"UF": "MT", "Cultura": "Soja"}
    linha.update(dict(zip(MESES_NOMES, mm_por_mes)))
    return pd.DataFrame([linha])


def _gerar(mm, horas_min=10, horas_max=None):
    return gerar_perfil_carga(
        df_ref=_df_ref(mm), estado="MT",
        grupo_a_potencia_kw=100, grupo_a_lamina_mm_21h=10.5,
        grupo_a_cultura_1="Soja", grupo_a_cultura_2=None,
        horas_min_por_dia=horas_min, hora_inicio=None, alternancia=False,
        horas_max_por_dia=horas_max,
    )


def test_lamina_tipica_modo_concentrado_usa_o_piso():
    # 0,5 mm/h * 10h = 5 mm por dia típico
    r = _gerar([60] + [0] * 11)
    jan = r.balanco_a[0]
    assert jan.lamina_tipica_dia_mm == 5.0


def test_lamina_tipica_com_deficit_usa_o_teto():
    # Teto 4h -> 2 mm/dia; 31 dias * 4h = 124h = 62 mm < 200 mm (déficit)
    r = _gerar([200] + [0] * 11, horas_max=4)
    jan = r.balanco_a[0]
    assert jan.deficit_mm > 0
    assert jan.lamina_tipica_dia_mm == 2.0


def test_mes_sem_irrigacao_tem_lamina_zero():
    r = _gerar([60] + [0] * 11)
    assert r.balanco_a[1].dias_operacao == 0
    assert r.balanco_a[1].lamina_tipica_dia_mm == 0.0
