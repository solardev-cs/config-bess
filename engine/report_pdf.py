"""Geração do PDF do Relatório de Viabilidade Econômica.

Este módulo é puro (sem dependência de ``streamlit``): recebe um
``RelatorioContexto`` já totalmente preenchido (dados de carga, KPIs
técnicos, configurações de FV/BESS/gerador e o ``ResultadoFinanceiro``) e
devolve os bytes do PDF pronto para download.

Os gráficos são recebidos como PNG (bytes) já renderizados — a página
Streamlit gera as figuras com ``matplotlib`` uma única vez e as reaproveita
tanto na tela quanto no PDF, evitando duplicar a lógica de plotagem.

Layout inspirado no relatório histórico "Resumo de Viabilidade" da
planilha original (``history/Config_OFF.xlsx``, aba "Resumo"):
    1. Capa/cabeçalho (cliente, projeto, GNF, revisão)
    2. Lista de cargas
    3. Perfis de consumo (gráficos)
    4. Dados técnicos do sistema (FV/Diesel/BESS)
    5. Resultados de economia (diesel, soja, por hectare)
    6. Fluxo de caixa (tabela + gráfico acumulado)
    7. Indicadores de retorno (VPL, TIR, LCOE, Payback, Caixa Total)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from fpdf import FPDF
from fpdf.fonts import FontFace

from engine.financial import ResultadoFinanceiro
from engine.models import BatteryConfig, GeneratorConfig, SimulationKPIs, SolarConfig

COR_AZUL = (41, 128, 185)
COR_CINZA_CLARO = (240, 240, 240)
COR_TEXTO_CINZA = (100, 100, 100)

ESTILO_CABECALHO_TABELA = FontFace(emphasis="B", color=(255, 255, 255), fill_color=COR_AZUL)

# Mapa de caracteres Unicode comuns (em textos digitados normalmente, como
# em-dash "–—", aspas tipográficas, bullets) que NÃO existem na codificação
# latin-1 usada pelas fontes core do fpdf2 (Helvetica). Sem este saneamento,
# qualquer texto com esses caracteres levantaria ``FPDFUnicodeEncodingException``
# em tempo de geração do PDF — preferimos degradar graciosamente para o
# equivalente ASCII mais próximo.
_SUBSTITUICOES_UNICODE = {
    "\u2014": "-",  # em dash —
    "\u2013": "-",  # en dash –
    "\u2018": "'",  # aspas tipográficas simples ‘
    "\u2019": "'",  # '
    "\u201c": '"',  # aspas tipográficas duplas “
    "\u201d": '"',  # ”
    "\u2022": "-",  # bullet •
    "\u2026": "...",  # ellipsis …
}


def _sanitizar(texto: str) -> str:
    """Substitui caracteres Unicode não suportados pela fonte core (latin-1).

    Aplicado a todo texto antes de ser escrito no PDF, para evitar que o
    relatório quebre por causa de um em-dash ou aspas tipográficas digitadas
    nos campos de cabeçalho ou nas observações.
    """
    for original, substituto in _SUBSTITUICOES_UNICODE.items():
        texto = texto.replace(original, substituto)
    return texto


@dataclass
class GrupoCargaInfo:
    """Uma linha da Lista de Cargas do relatório."""

    nome: str
    descricao: str
    potencia_kw: float
    potencia_cv: float
    lamina_mm_21h: float
    area_ha: float = 0.0


@dataclass
class RelatorioContexto:
    """Agrega todos os dados necessários para montar o PDF do relatório."""

    # Cabeçalho
    cliente: str
    cidade: str
    estado: str
    gnf: str
    revisao: str

    # Cargas
    grupos: list[GrupoCargaInfo]
    consumo_anual_kwh: float
    potencia_total_kw: float

    # Técnico
    kpis: SimulationKPIs
    solar_config: SolarConfig
    battery_config: BatteryConfig
    generator_config: GeneratorConfig

    # Financeiro
    resultado_financeiro: ResultadoFinanceiro
    consumo_diesel_litros_ano1: float
    economia_diesel_litros_ano1: float

    # Área total irrigada (soma dos grupos), para métricas por hectare.
    area_total_ha: float = 0.0

    # Gráficos (PNG em bytes), gerados pela página Streamlit.
    grafico_perfil_anual_png: Optional[bytes] = None
    grafico_perfil_hibrido_png: Optional[bytes] = None
    grafico_fluxo_caixa_png: Optional[bytes] = None

    observacoes: list[str] = field(default_factory=list)


def _fmt_moeda(valor: float) -> str:
    texto = f"{valor:,.0f}"
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def _fmt_num(valor: float, decimais: int = 1) -> str:
    texto = f"{valor:,.{decimais}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


class RelatorioPDF(FPDF):
    """Subclasse do FPDF com cabeçalho/rodapé padronizados do relatório.

    Sobrescreve ``normalize_text`` (o ponto único por onde todo texto passa
    antes de ser escrito no PDF) para sanear caracteres Unicode não
    suportados pela fonte core (ver ``_sanitizar``), evitando que o
    relatório quebre por causa de texto digitado pelo usuário (cliente,
    cidade, observações etc.) ou de tabelas montadas dinamicamente.
    """

    titulo_relatorio = "Relatório de Viabilidade Econômica"

    def normalize_text(self, text: str) -> str:  # noqa: D102 (override do fpdf2)
        return super().normalize_text(_sanitizar(text))

    def header(self) -> None:  # noqa: D102 (override do fpdf2)
        self.set_fill_color(*COR_AZUL)
        self.rect(0, 0, self.w, 14, style="F")
        self.set_xy(10, 3)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(255, 255, 255)
        self.cell(0, 8, self.titulo_relatorio)
        self.set_text_color(0, 0, 0)
        self.set_fill_color(255, 255, 255)
        self.set_y(18)

    def footer(self) -> None:  # noqa: D102 (override do fpdf2)
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*COR_TEXTO_CINZA)
        self.cell(0, 8, f"Página {self.page_no()}", align="C")
        self.set_text_color(0, 0, 0)

    def secao(self, titulo: str) -> None:
        """Escreve um título de seção com uma barra colorida à esquerda."""
        self.ln(2)
        y = self.get_y()
        self.set_fill_color(*COR_AZUL)
        self.rect(10, y, 2, 7, style="F")
        self.set_fill_color(255, 255, 255)
        self.set_xy(14, y)
        self.set_font("Helvetica", "B", 13)
        self.cell(0, 7, titulo)
        self.ln(9)

    def kpi_card(self, x: float, y: float, w: float, h: float, label: str, valor: str) -> None:
        """Desenha um cartão de indicador (fundo cinza claro, label + valor)."""
        self.set_xy(x, y)
        self.set_fill_color(*COR_CINZA_CLARO)
        self.rect(x, y, w, h, style="F")
        self.set_fill_color(255, 255, 255)
        self.set_xy(x, y + 2)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*COR_TEXTO_CINZA)
        self.cell(w, 5, label, align="C")
        self.set_xy(x, y + 8)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(0, 0, 0)
        self.cell(w, 7, valor, align="C")


def _pagina_capa_e_cargas(pdf: RelatorioPDF, ctx: RelatorioContexto) -> None:
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, "Sistema Híbrido Off-Grid", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 13)
    pdf.set_text_color(*COR_TEXTO_CINZA)
    pdf.cell(0, 7, f"{ctx.cliente}    |    {ctx.cidade} / {ctx.estado}    |    GNF {ctx.gnf}    |    {ctx.revisao}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    pdf.secao("Lista de Cargas")
    linhas = [["Grupo", "Descrição", "Pot (kW)", "Pot (CV)", "Lâmina (mm/21h)", "Área Irr (ha)"]]
    for g in ctx.grupos:
        linhas.append(
            [
                g.nome,
                g.descricao,
                _fmt_num(g.potencia_kw, 1),
                _fmt_num(g.potencia_cv, 1),
                _fmt_num(g.lamina_mm_21h, 1),
                _fmt_num(g.area_ha, 0) if g.area_ha > 0 else "-",
            ]
        )
    with pdf.table(
        linhas,
        col_widths=(22, 48, 28, 26, 34, 22),
        text_align="CENTER",
        cell_fill_mode="NONE",
        headings_style=ESTILO_CABECALHO_TABELA,
    ):
        pass

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(50, 7, "Potência Total:")
    pdf.set_font("Helvetica", "", 13)
    pdf.cell(0, 7, f"{_fmt_num(ctx.potencia_total_kw, 2)} kW", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(50, 7, "Consumo Total:")
    pdf.set_font("Helvetica", "", 13)
    pdf.cell(0, 7, f"{_fmt_num(ctx.consumo_anual_kwh, 0)} kWh/ano", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    if ctx.grafico_perfil_anual_png is not None:
        pdf.secao("Perfil de Consumo")
        pdf.image(ctx.grafico_perfil_anual_png, x=10, w=pdf.epw)

    if ctx.grafico_perfil_hibrido_png is not None:
        y_restante = pdf.h - pdf.get_y() - pdf.b_margin
        if y_restante < 70:
            pdf.add_page()
        pdf.image(ctx.grafico_perfil_hibrido_png, x=10, w=pdf.epw)


def _pagina_tecnico_e_economia(pdf: RelatorioPDF, ctx: RelatorioContexto) -> None:
    pdf.add_page()
    kpis = ctx.kpis
    resultado = ctx.resultado_financeiro

    TAM_LABEL = 80
    TAM_FONTE = 13
    ALTURA_LINHA = 10

    def linha_dado(label: str, valor: str) -> None:
        pdf.set_font("Helvetica", "B", TAM_FONTE)
        pdf.cell(TAM_LABEL, ALTURA_LINHA, label)
        pdf.set_font("Helvetica", "", TAM_FONTE)
        pdf.cell(0, ALTURA_LINHA, valor, new_x="LMARGIN", new_y="NEXT")

    pdf.secao("Dados Técnicos do Sistema")
    linha_dado("Potência FV:", f"{_fmt_num(ctx.solar_config.pot_pico_kwp, 1)} kWp / {_fmt_num(ctx.solar_config.pot_inv_kw, 1)} kW")
    linha_dado(
        "Potência Diesel:",
        f"{_fmt_num(ctx.generator_config.pot_total_kw, 1)} kW ({ctx.generator_config.nr_maquinas} x {_fmt_num(ctx.generator_config.pot_prime_kva, 0)} kVA)",
    )
    linha_dado("Potência BESS:", f"{_fmt_num(ctx.battery_config.capacidade_kwh, 1)} kWh / {_fmt_num(ctx.battery_config.potencia_kw, 1)} kW")
    pdf.ln(5)
    linha_dado("Energia FV:", f"{_fmt_num(kpis.energia_solar_utilizada_kwh, 0)} kWh/ano")
    linha_dado("Percentual FV:", f"{_fmt_num(kpis.fracao_solar * 100, 1)} %")
    linha_dado("Energia diesel:", f"{_fmt_num(kpis.energia_gerador_kwh, 0)} kWh/ano")
    linha_dado("Consumo diesel:", f"{_fmt_num(ctx.consumo_diesel_litros_ano1, 0)} litros/ano (1º ano)")
    pdf.ln(4)

    pdf.secao("Resultados de Economia (1º ano)")

    pdf.set_font("Helvetica", "B", TAM_FONTE)
    pdf.cell(TAM_LABEL, ALTURA_LINHA, "Investimento FV+BESS:")
    pdf.set_font("Helvetica", "", TAM_FONTE)
    pdf.cell(0, ALTURA_LINHA, _fmt_moeda(resultado.capex.capex_total_rs), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)

    linha_dado("Economia diesel:", f"{_fmt_num(ctx.economia_diesel_litros_ano1, 0)} litros")
    linha_dado("Economia R$:", _fmt_moeda(resultado.economia_diesel_ano1_rs))
    linha_dado("Economia soja:", f"{_fmt_num(resultado.economia_em_sacas_ano1, 0)} sacas (R$/saca de referência)")

    if ctx.area_total_ha > 0:
        economia_ha = resultado.economia_diesel_ano1_rs / ctx.area_total_ha
        diesel_ha = ctx.economia_diesel_litros_ano1 / ctx.area_total_ha
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", TAM_FONTE)
        pdf.cell(0, ALTURA_LINHA, f"Economia por Hectare (área irrigada: {_fmt_num(ctx.area_total_ha, 0)} ha)", new_x="LMARGIN", new_y="NEXT")
        linha_dado("Economia R$/ha/ano:", _fmt_moeda(economia_ha))
        linha_dado("Diesel evitado L/ha/ano:", f"{_fmt_num(diesel_ha, 1)} L/ha")


def _pagina_fluxo_de_caixa(pdf: RelatorioPDF, ctx: RelatorioContexto) -> None:
    pdf.add_page()
    resultado = ctx.resultado_financeiro

    pdf.secao("Fluxo de Caixa")
    linhas = [["Ano", "Economia", "Custos (O&M + Financ.)", "Fluxo de Caixa", "FC Acumulado"]]
    for f in resultado.fluxos:
        custos_rs = f.om_rs + f.parcela_financiamento_rs
        linhas.append(
            [
                str(f.ano) if f.ano > 0 else "-",
                _fmt_moeda(f.economia_diesel_rs) if f.ano > 0 else "-",
                _fmt_moeda(-custos_rs) if f.ano > 0 else _fmt_moeda(f.fluxo_caixa_rs),
                _fmt_moeda(f.fluxo_caixa_rs),
                _fmt_moeda(f.fluxo_acumulado_rs),
            ]
        )
    with pdf.table(
        linhas,
        col_widths=(16, 40, 40, 40, 44),
        text_align="RIGHT",
        line_height=5.2,
        cell_fill_mode="NONE",
        headings_style=ESTILO_CABECALHO_TABELA,
    ):
        pass

    if ctx.grafico_fluxo_caixa_png is not None:
        pdf.add_page()
        pdf.secao("Fluxo de Caixa Acumulado")
        pdf.image(ctx.grafico_fluxo_caixa_png, x=10, w=pdf.epw)

    pdf.secao("Indicadores de Retorno")
    tir_texto = f"{resultado.tir * 100:.1f} %" if resultado.tir is not None else "N/A"
    payback_texto = f"{resultado.payback_anos} ano(s)" if resultado.payback_anos is not None else "N/A"

    largura_card = (pdf.epw - 12) / 3
    y0 = pdf.get_y()
    pdf.kpi_card(10, y0, largura_card, 20, "VPL", _fmt_moeda(resultado.vpl_rs))
    pdf.kpi_card(10 + largura_card + 6, y0, largura_card, 20, "TIR", tir_texto)
    pdf.kpi_card(10 + 2 * (largura_card + 6), y0, largura_card, 20, "Payback", payback_texto)

    horizonte_anos = max((f.ano for f in resultado.fluxos), default=0)
    y1 = y0 + 26
    pdf.kpi_card(10, y1, largura_card, 20, "LCOE", f"{resultado.lcoe_rs_kwh:.2f} R$/kWh")
    pdf.kpi_card(10 + largura_card + 6, y1, largura_card, 20, f"Caixa Total ({horizonte_anos} anos)", _fmt_moeda(sum(f.fluxo_caixa_rs for f in resultado.fluxos)))

    pdf.set_xy(10, y1 + 28)
    if ctx.observacoes:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "Observações", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(*COR_TEXTO_CINZA)
        for obs in ctx.observacoes:
            pdf.multi_cell(0, 4.5, f"- {obs}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)


def gerar_pdf_relatorio(ctx: RelatorioContexto) -> bytes:
    """Monta o PDF completo do Relatório de Viabilidade Econômica.

    Args:
        ctx: contexto totalmente preenchido com os dados de carga, técnicos
            e financeiros do sistema híbrido, mais os gráficos (PNG) já
            renderizados pela página Streamlit.

    Returns:
        Bytes do arquivo PDF pronto para download.
    """
    pdf = RelatorioPDF(orientation="P", format="A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(10, 18, 10)

    _pagina_capa_e_cargas(pdf, ctx)
    _pagina_tecnico_e_economia(pdf, ctx)
    _pagina_fluxo_de_caixa(pdf, ctx)

    saida = pdf.output()
    return bytes(saida)
