"""Testes de regressão contra os valores reais extraídos da planilha original.

Estes testes garantem que a portabilidade da lógica de despacho para
Python não introduziu desvios além dos que foram CORRIGIDOS
intencionalmente (documentados na análise da planilha). Rodamos o motor em
"modo legado" (``c_rate=None``, ``eficiencia_rt=1.0``) para reproduzir o
comportamento físico da planilha o mais fielmente possível.

Referência: aba "Cálculo Técnico" do arquivo ``history/Config_OFF.xlsx``,
projeto "Paulo Franz" (MT), config: 2 geradores de 315 kW contínuo, FV de
800 kW de inversor (ILR 1,4), BESS de 1.446 kWh.

Valores de referência (extraídos via openpyxl, ``data_only=True``):
    E8766 (carga total)         = 1_938_829.3451623067
    M8766 (Pinv total)          = 1_811_268.4444444466
    P8766 (Pinv_sobra total)    = 1_067_077.213460594
    Q8766 (Pbat_utiliz total)   =   375_898.951747374
    S8766 (Pger total)          =   818_739.1624308705
    U8766 (Pinv_utiliz total)   =   744_191.2309838256
    V8766 (Pdump total)         =         0.0
    W8766 (Prede total)         =  ~0.0 (arredondamento de ponto flutuante)

ACHADO ADICIONAL (não estava na análise anterior): a fórmula da célula
``Q6`` (primeira hora do ano, linha 6) é DIFERENTE de todas as demais —
usa ``IF((E6-O6)>K7, K7, E6-O6)`` em vez de
``IF((E6-O6)>(SOC_ant-K9), SOC_ant-K9, E6-O6)``. Isso permite que a
bateria descarregue 608,36 kW já na primeira hora do ano, mesmo com o SOC
inicial no mínimo (``R6 = K9`` = SOC mínimo, sem nenhuma energia
"acima do mínimo" disponível) — ou seja, a planilha permite que a bateria
entregue energia "do nada" apenas na hora 0, por um erro de condição de
contorno na fórmula. Nosso motor NÃO reproduz esse bug (o SOC inicial é
respeitado corretamente em todas as horas, incluindo a primeira), o que
gera uma diferença de exatamente 608,36 kWh entre ``Q`` e ``S`` no total
anual. Os testes abaixo validam essa diferença de forma explícita.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from engine.dispatch.load_following import LoadFollowingDispatch
from engine.models import BatteryConfig, GeneratorConfig, SolarConfig
from engine.simulator import simular_ano
from engine.solar.static_tmy import StaticTmySolarProvider

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Bug conhecido e documentado da planilha original: a fórmula de Q6 (hora 0)
# permite a bateria descarregar sem ter energia disponível acima do SOC
# mínimo. Nosso motor corrige isso; a diferença esperada é exatamente a
# potência descarregada nessa hora na planilha original.
BUG_HORA_0_KWH = 608.3621052631579

REF_E8766 = 1_938_829.3451623067
REF_M8766 = 1_811_268.4444444466
REF_P8766 = 1_067_077.213460594
REF_Q8766 = 375_898.951747374
REF_S8766 = 818_739.1624308705
REF_U8766 = 744_191.2309838256
REF_V8766 = 0.0


class _LegacyDivisorSolarProvider:
    """Provider auxiliar de teste: reproduz o divisor de normalização
    HARDCODED e desatualizado da planilha original (H4=1260 para MT), em
    vez do máximo real da série (1078). Usado apenas para isolar o bug da
    hora 0 (test_..._bug_hora_0), sem misturar com a correção do divisor
    de normalização (achado 2.1 da análise), que é testada separadamente
    em ``test_pinv_total_bate_com_a_planilha_apos_correcao_normalizacao``.
    """

    def get_normalized_profile(self):
        df = pd.read_csv(DATA_DIR / "tmy" / "MT.csv")
        ghi = df["ghi_wm2"].to_numpy(dtype=float)
        return ghi / 1260.0


def _rodar_simulacao(solar_provider):
    carga_df = pd.read_csv(DATA_DIR / "carga_referencia_excel.csv")
    carga_kw = carga_df["carga_kw"].to_numpy()

    battery_config = BatteryConfig(capacidade_kwh=1446, c_rate=None, dod=0.9, eficiencia_rt=1.0)
    generator_config = GeneratorConfig(
        nr_maquinas=2,
        nr_min_maquinas=2,
        pot_continua_kw=315,
        pot_prime_kva=500,
        fp=0.8,
        pot_min_pct=0.0,
        modo="ON/OFF",
    )
    solar_config = SolarConfig(pot_inv_kw=800, ilr=1.4, localizacao="MT")

    return simular_ano(
        carga_kw,
        solar_config,
        solar_provider,
        battery_config,
        generator_config,
        LoadFollowingDispatch(),
        perdas_sistema_fv_pct=0.0,  # planilha original não modelava perdas de sistema FV
    )


@pytest.fixture(scope="module")
def resultado_simulacao():
    """Simulação com o divisor de normalização CORRIGIDO (comportamento
    recomendado para uso real).
    """
    return _rodar_simulacao(StaticTmySolarProvider("MT"))


@pytest.fixture(scope="module")
def resultado_simulacao_divisor_legado():
    """Simulação com o divisor de normalização IGUAL ao da planilha
    original (para isolar exclusivamente o bug da hora 0, sem misturar com
    a correção do divisor de normalização).
    """
    return _rodar_simulacao(_LegacyDivisorSolarProvider())


def test_carga_total_bate_com_a_planilha(resultado_simulacao):
    assert resultado_simulacao.df["carga_kw"].sum() == pytest.approx(REF_E8766, rel=1e-9)


def test_pinv_total_bate_com_a_planilha_apos_correcao_normalizacao(resultado_simulacao):
    """Usamos o divisor CORRETO (máximo real da série MT = 1078), diferente do
    divisor hardcoded desatualizado da planilha (H4=1260). Por isso o Pinv
    total é MAIOR que o da planilha (mais energia solar disponível) — essa é
    uma correção intencional (achado 2.1 da análise), não uma regressão.
    """
    assert resultado_simulacao.df["pinv_kw"].sum() > REF_M8766


def test_bateria_descarga_bate_com_a_planilha_exceto_bug_hora_0(resultado_simulacao_divisor_legado):
    """A diferença deve ser EXATAMENTE a energia do bug isolado na hora 0."""
    diferenca = REF_Q8766 - resultado_simulacao_divisor_legado.df["bateria_descarga_kw"].sum()
    assert diferenca == pytest.approx(BUG_HORA_0_KWH, abs=1e-6)


def test_gerador_total_bate_com_a_planilha_exceto_bug_hora_0(resultado_simulacao_divisor_legado):
    """O gerador teve que compensar a energia que a bateria NÃO entregou
    (por não ter mais o bug da hora 0), então o total do gerador aqui é
    MAIOR que o da planilha, na mesma magnitude do bug corrigido.
    """
    diferenca = resultado_simulacao_divisor_legado.df["gerador_kw"].sum() - REF_S8766
    assert diferenca == pytest.approx(BUG_HORA_0_KWH, abs=1e-6)


def test_nenhuma_energia_nao_suprida(resultado_simulacao):
    """No modo legado (sem limite de potência do BESS), o sistema deve
    conseguir suprir 100% da carga, assim como a planilha original.
    """
    assert resultado_simulacao.df["nao_suprido_kw"].sum() == pytest.approx(0.0, abs=1e-6)


def test_soc_nunca_abaixo_do_minimo_nem_acima_da_capacidade(resultado_simulacao):
    soc = resultado_simulacao.df["bateria_soc_kwh"]
    soc_min_esperado = 1446 * (1 - 0.9)
    assert soc.min() >= soc_min_esperado - 1e-6
    assert soc.max() <= 1446 + 1e-6


def test_conservacao_de_energia_horaria(resultado_simulacao):
    """Em toda hora, a soma das fontes que atendem a carga deve ser
    consistente: carga = solar_utilizado + bateria_descarga + gerador -
    nao_suprido (dentro de tolerância numérica).
    """
    df = resultado_simulacao.df
    atendimento = df["solar_utilizado_kw"] + df["bateria_descarga_kw"] + df["gerador_kw"]
    residuo = df["carga_kw"] - atendimento + df["nao_suprido_kw"]
    assert np.allclose(residuo, 0.0, atol=1e-6)
