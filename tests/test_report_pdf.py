"""Teste smoke do módulo de geração de PDF do relatório (engine/report_pdf.py).

Não valida o conteúdo visual do PDF (fora do escopo de um teste unitário),
apenas que a função ``gerar_pdf_relatorio`` roda sem erros e devolve bytes
de um PDF válido, para os três cenários relevantes: com gráficos, sem
gráficos, e com/sem área irrigada informada (métricas por hectare).
"""
from __future__ import annotations

from engine.costs import calcular_capex, calcular_financiamento, calcular_tabela_amortizacao
from engine.financial import calcular_fluxo_de_caixa
from engine.models import BatteryConfig, EconomicConfig, GeneratorConfig, SimulationKPIs, SolarConfig
from engine.report_pdf import GrupoCargaInfo, RelatorioContexto, gerar_pdf_relatorio


def _contexto_base(area_total_ha: float = 0.0, com_graficos: bool = False) -> RelatorioContexto:
    kpis = SimulationKPIs(
        energia_carga_total_kwh=813_300,
        energia_solar_utilizada_kwh=758_222,
        energia_bateria_descarregada_kwh=0.0,
        energia_gerador_kwh=55_078,
        energia_nao_suprida_kwh=0.0,
        energia_curtailed_kwh=0.0,
        horas_com_deficit=0,
    )
    solar_config = SolarConfig(pot_inv_kw=450, ilr=1.4)
    battery_config = BatteryConfig(capacidade_kwh=1205, c_rate=0.5)
    generator_config = GeneratorConfig(
        nr_maquinas=1, nr_min_maquinas=1, pot_continua_kw=315, pot_prime_kva=550, eficiencia_kwh_por_litro=4.0816
    )
    economic_config = EconomicConfig(
        custo_fv_rs_kwp=6500, custo_bateria_rs_kwh=2000, preco_diesel_rs_litro=7.0, tma_am=0.05
    )

    resultado_financeiro = calcular_fluxo_de_caixa(
        kpis, solar_config, battery_config, generator_config, economic_config
    )

    grafico_png = None
    if com_graficos:
        import io

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        ax.plot([1, 2, 3], [1, 2, 3])
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        grafico_png = buf.getvalue()

    return RelatorioContexto(
        cliente="Cliente Teste",
        cidade="Juara",
        estado="MT",
        gnf="96133",
        revisao="Rev01",
        grupos=[
            GrupoCargaInfo(
                nome="Grupo A",
                descricao="Soja + Milho",
                potencia_kw=608.36,
                potencia_cv=785.25,
                lamina_mm_21h=9.0,
                area_ha=area_total_ha,
            )
        ],
        consumo_anual_kwh=kpis.energia_carga_total_kwh,
        potencia_total_kw=608.36,
        kpis=kpis,
        solar_config=solar_config,
        battery_config=battery_config,
        generator_config=generator_config,
        resultado_financeiro=resultado_financeiro,
        consumo_diesel_litros_ano1=13_494,
        economia_diesel_litros_ano1=186_889,
        area_total_ha=area_total_ha,
        grafico_perfil_anual_png=grafico_png,
        grafico_perfil_hibrido_png=grafico_png,
        grafico_fluxo_caixa_png=grafico_png,
        observacoes=["Nota metodológica de teste."],
    )


def test_gerar_pdf_relatorio_sem_graficos_retorna_pdf_valido():
    ctx = _contexto_base(area_total_ha=0.0, com_graficos=False)
    pdf_bytes = gerar_pdf_relatorio(ctx)

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 500
    assert pdf_bytes.startswith(b"%PDF")


def test_gerar_pdf_relatorio_com_graficos_retorna_pdf_valido():
    ctx = _contexto_base(area_total_ha=0.0, com_graficos=True)
    pdf_bytes = gerar_pdf_relatorio(ctx)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000


def test_gerar_pdf_relatorio_com_area_irrigada_inclui_metricas_por_hectare():
    ctx = _contexto_base(area_total_ha=350.0, com_graficos=False)
    pdf_bytes = gerar_pdf_relatorio(ctx)

    assert pdf_bytes.startswith(b"%PDF")
    # Um PDF com a seção de economia por hectare deve ser maior que sem ela
    # (mais texto renderizado); comparação indireta, já que o conteúdo bruto
    # do PDF não é texto plano legível diretamente.
    ctx_sem_area = _contexto_base(area_total_ha=0.0, com_graficos=False)
    pdf_bytes_sem_area = gerar_pdf_relatorio(ctx_sem_area)
    assert len(pdf_bytes) >= len(pdf_bytes_sem_area)
