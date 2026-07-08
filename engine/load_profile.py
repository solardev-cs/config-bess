"""Geração de perfil de carga horário (8760h) para irrigação.

Este módulo contém a lógica pura (sem Streamlit) para:
    - Converter necessidade hídrica (mm/mês) em horas de bombeamento;
    - Distribuir essas horas ao longo dos dias do mês, respeitando janela de
      operação e alternância entre grupos de carga;
    - Montar o DataFrame final de 8760h com a carga elétrica resultante.

As funções aqui são extraídas 1:1 do ``app.py`` original (mesma lógica,
mesmo comportamento), apenas reorganizadas para não depender de
``streamlit`` e para receberem seus parâmetros explicitamente em vez de
lerem variáveis de módulo/sessão.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

MESES_NOMES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
MESES_COLS = MESES_NOMES


def obter_mm_mensal(df_ref: pd.DataFrame, estado: str, cultura: str | None) -> np.ndarray:
    """Retorna um array de 12 meses (mm) para a cultura e estado selecionados.

    Args:
        df_ref: DataFrame com a tabela de referência hídrica (colunas UF,
            Cultura, Jan..Dez).
        estado: sigla da UF (ex. "MT").
        cultura: nome da cultura, ou None/"Nenhuma" para retornar zeros.

    Returns:
        Array numpy de 12 posições (mm/mês). Zeros se não houver dados.
    """
    if not cultura or cultura == "Nenhuma":
        return np.zeros(12)

    filtro = (df_ref["UF"] == estado) & (df_ref["Cultura"] == cultura)
    dados = df_ref[filtro]

    if dados.empty:
        return np.zeros(12)

    valores = dados.iloc[0][MESES_COLS].values.astype(float)
    return np.nan_to_num(valores)


def calcular_horas_mensais(mm_necessarios: float, lamina_projeto_mm_21h: float) -> int:
    """Converte necessidade hídrica (mm) em horas de bombeamento no mês.

    Args:
        mm_necessarios: necessidade hídrica líquida do mês (mm).
        lamina_projeto_mm_21h: lâmina de projeto do sistema de irrigação,
            expressa em mm aplicados caso operasse 21h contínuas.

    Returns:
        Número inteiro de horas necessárias (arredondado para cima).
    """
    if lamina_projeto_mm_21h <= 0:
        return 0
    capacidade_mm_h = lamina_projeto_mm_21h / 21.0
    return math.ceil(mm_necessarios / capacidade_mm_h)


def distribuir_carga(
    df: pd.DataFrame,
    mes: int,
    grupo_idx: int,
    power_kw: float,
    horas_necessarias: int,
    janela_horas: int,
    alternancia: bool,
    start_hour: int,
) -> tuple[int, int]:
    """Distribui as horas de carga no DataFrame de 8760h.

    Modifica ``df`` in-place, escrevendo ``power_kw`` nas colunas
    ``Grupo_A``/``Grupo_B`` nas horas selecionadas.

    Args:
        df: DataFrame indexado por datetime horário (8760 linhas), já
            contendo as colunas ``Grupo_A`` e ``Grupo_B`` inicializadas.
        mes: mês (1-12) a distribuir.
        grupo_idx: 0 para Grupo A, 1 para Grupo B.
        power_kw: potência elétrica do grupo de carga (kW).
        horas_necessarias: total de horas de irrigação necessárias no mês.
        janela_horas: janela diária máxima de operação (horas).
        alternancia: se True, Grupo A opera em dias ímpares e Grupo B em
            dias pares (calendário juliano do ano).
        start_hour: hora do dia (0-23) em que a irrigação começa.

    Returns:
        Tupla ``(horas_necessarias, deficit_horas)``, onde ``deficit_horas``
        é a quantidade de horas que não puderam ser atendidas dentro da
        janela de operação disponível.
    """
    dias_disponiveis = []

    mask_mes = df.index.month == mes
    dias_do_mes = df[mask_mes].index.day.unique()

    for dia in dias_do_mes:
        day_of_year = df[(df.index.month == mes) & (df.index.day == dia)].index[0].dayofyear

        if alternancia:
            # Grupo A (idx 0): Dias Ímpares | Grupo B (idx 1): Dias Pares
            if grupo_idx == 0 and day_of_year % 2 != 0:
                dias_disponiveis.append(dia)
            elif grupo_idx == 1 and day_of_year % 2 == 0:
                dias_disponiveis.append(dia)
        else:
            dias_disponiveis.append(dia)

    qtd_dias_uteis = len(dias_disponiveis)

    if qtd_dias_uteis == 0:
        return 0, 0

    horas_por_dia_base = int(horas_necessarias / qtd_dias_uteis)
    horas_restantes = horas_necessarias % qtd_dias_uteis

    max_horas_possiveis = qtd_dias_uteis * janela_horas
    deficit_horas = 0

    if horas_necessarias > max_horas_possiveis:
        deficit_horas = horas_necessarias - max_horas_possiveis
        horas_por_dia_base = janela_horas
        horas_restantes = 0

    for dia in dias_disponiveis:
        horas_hoje = horas_por_dia_base

        if horas_restantes > 0 and horas_hoje < janela_horas:
            horas_hoje += 1
            horas_restantes -= 1

        horas_hoje = min(horas_hoje, janela_horas)

        indices = df[
            (df.index.month == mes)
            & (df.index.day == dia)
            & (df.index.hour >= start_hour)
            & (df.index.hour < start_hour + horas_hoje)
        ].index

        col_name = f'Grupo_{"A" if grupo_idx == 0 else "B"}'
        df.loc[indices, col_name] = power_kw

    return horas_necessarias, deficit_horas


@dataclass
class BalancoHidricoMes:
    """Resultado do balanço hídrico de um grupo de carga em um mês."""

    mes: str
    precisa_mm: float
    entrega_mm: float
    deficit_mm: float


@dataclass
class ResultadoPerfilCarga:
    """Resultado completo da geração de perfil de carga de irrigação."""

    df: pd.DataFrame  # índice datetime horário de 8760h, colunas Grupo_A/Grupo_B/Total_Load_kW
    balanco_a: list[BalancoHidricoMes]
    balanco_b: list[BalancoHidricoMes]
    avisos: list[str]


def gerar_perfil_carga(
    df_ref: pd.DataFrame,
    estado: str,
    grupo_a_potencia_kw: float,
    grupo_a_lamina_mm_21h: float,
    grupo_a_cultura_1: str,
    grupo_a_cultura_2: str | None,
    janela_operacao_horas: int,
    hora_inicio: int,
    alternancia: bool,
    grupo_b_potencia_kw: float = 0.0,
    grupo_b_lamina_mm_21h: float = 0.0,
    grupo_b_cultura_1: str | None = None,
    grupo_b_cultura_2: str | None = None,
    ano_referencia: int = 2023,
) -> ResultadoPerfilCarga:
    """Gera o perfil de carga horário de 8760h para irrigação.

    Reproduz a lógica de processamento originalmente implementada em
    ``app.py``, incluindo a regra de sucessão de culturas (usa o MAIOR
    valor mensal entre cultura principal e cultura de sucessão).

    Args:
        df_ref: tabela de referência hídrica (UF, Cultura, Jan..Dez).
        estado: sigla da UF.
        grupo_a_potencia_kw: potência elétrica do Grupo A (kW).
        grupo_a_lamina_mm_21h: lâmina de projeto do Grupo A.
        grupo_a_cultura_1: cultura principal do Grupo A.
        grupo_a_cultura_2: cultura de sucessão do Grupo A (ou None).
        janela_operacao_horas: janela diária máxima de operação.
        hora_inicio: hora do dia em que a irrigação inicia.
        alternancia: se True, ativa o Grupo B em dias alternados.
        grupo_b_*: parâmetros equivalentes para o Grupo B (usado somente se
            ``alternancia=True`` e ``grupo_b_potencia_kw > 0``).
        ano_referencia: ano-base do calendário gerado (não bissexto
            recomendado, para manter 8760h).

    Returns:
        ``ResultadoPerfilCarga`` com o DataFrame horário, o balanço hídrico
        mensal de cada grupo e a lista de avisos de déficit.
    """
    dates = pd.date_range(start=f"{ano_referencia}-01-01", end=f"{ano_referencia}-12-31 23:00", freq="h")
    df = pd.DataFrame(index=dates)
    df["Grupo_A"] = 0.0
    df["Grupo_B"] = 0.0

    avisos: list[str] = []
    balanco_a: list[BalancoHidricoMes] = []
    balanco_b: list[BalancoHidricoMes] = []

    mm_a1 = obter_mm_mensal(df_ref, estado, grupo_a_cultura_1)
    mm_a2 = obter_mm_mensal(df_ref, estado, grupo_a_cultura_2)
    mm_final_a = np.maximum(mm_a1, mm_a2)

    if alternancia:
        mm_b1 = obter_mm_mensal(df_ref, estado, grupo_b_cultura_1)
        mm_b2 = obter_mm_mensal(df_ref, estado, grupo_b_cultura_2)
        mm_final_b = np.maximum(mm_b1, mm_b2)
    else:
        mm_final_b = np.zeros(12)

    for mes in range(1, 13):
        idx = mes - 1

        # --- Grupo A ---
        mm_nec_a = mm_final_a[idx]
        horas_nec_a = calcular_horas_mensais(mm_nec_a, grupo_a_lamina_mm_21h)
        nec_a, def_a = distribuir_carga(
            df, mes, 0, grupo_a_potencia_kw, horas_nec_a, janela_operacao_horas, alternancia, hora_inicio
        )

        h_entregue_a = nec_a - def_a
        mm_entregue_a = h_entregue_a * (grupo_a_lamina_mm_21h / 21.0) if horas_nec_a > 0 else 0

        balanco_a.append(
            BalancoHidricoMes(
                mes=MESES_NOMES[idx],
                precisa_mm=mm_nec_a,
                entrega_mm=min(mm_nec_a, mm_entregue_a),
                deficit_mm=max(0.0, mm_nec_a - mm_entregue_a),
            )
        )

        if def_a > 0:
            avisos.append(f"{MESES_NOMES[idx]} (Grupo A): Faltam {def_a} horas de água.")

        # --- Grupo B ---
        if grupo_b_potencia_kw > 0:
            mm_nec_b = mm_final_b[idx]
            horas_nec_b = calcular_horas_mensais(mm_nec_b, grupo_b_lamina_mm_21h)
            nec_b, def_b = distribuir_carga(
                df, mes, 1, grupo_b_potencia_kw, horas_nec_b, janela_operacao_horas, alternancia, hora_inicio
            )

            h_entregue_b = nec_b - def_b
            mm_entregue_b = h_entregue_b * (grupo_b_lamina_mm_21h / 21.0) if horas_nec_b > 0 else 0

            balanco_b.append(
                BalancoHidricoMes(
                    mes=MESES_NOMES[idx],
                    precisa_mm=mm_nec_b,
                    entrega_mm=min(mm_nec_b, mm_entregue_b),
                    deficit_mm=max(0.0, mm_nec_b - mm_entregue_b),
                )
            )

            if def_b > 0:
                avisos.append(f"{MESES_NOMES[idx]} (Grupo B): Faltam {def_b} horas de água.")

    df["Total_Load_kW"] = df["Grupo_A"] + df["Grupo_B"]

    return ResultadoPerfilCarga(df=df, balanco_a=balanco_a, balanco_b=balanco_b, avisos=avisos)
