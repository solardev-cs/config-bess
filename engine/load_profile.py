"""Geração de perfil de carga horário (8760h) para irrigação.

Este módulo contém a lógica pura (sem Streamlit) para:
    - Converter necessidade hídrica (mm/mês) em horas de bombeamento;
    - Distribuir essas horas ao longo dos dias do mês, concentrando a
      operação em menos dias (cada um rodando ao menos ``horas_min_por_dia``
      horas) em vez de espalhar poucas horas por todos os dias, respeitando
      o teto físico diário e a alternância entre grupos de carga;
    - Montar o DataFrame final de 8760h com a carga elétrica resultante.

A distribuição de horas foi adaptada em relação ao ``app.py`` original: antes
as horas do mês eram divididas igualmente por TODOS os dias (muitos dias com
poucas horas), o que não representava a operação real. Agora o usuário informa
um mínimo de horas por dia e o app concentra a necessidade hídrica mensal em
menos dias, mantendo a lâmina de cada mês exata.
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


def _dias_espacados(dias: list[int], quantidade: int) -> list[int]:
    """Seleciona ``quantidade`` dias uniformemente espaçados de ``dias``.

    Usa posicionamento estratificado (``floor((k + 0.5) * n / d)``), que
    mantém os intervalos entre dias irrigados quase iguais — inclusive nas
    bordas do mês — para qualquer ``quantidade`` pedida. Preferido a uma
    sequência de baixa discrepância (ex.: áurea) porque, para um ``d`` fixo
    e conhecido, o espaçamento uniforme minimiza o maior intervalo seco, que
    é a restrição agronômica relevante aqui.
    """
    n = len(dias)
    if quantidade >= n:
        return list(dias)
    if quantidade <= 0:
        return []
    return [dias[int((k + 0.5) * n / quantidade)] for k in range(quantidade)]


def _escrever_dia(
    df: pd.DataFrame,
    mes: int,
    dia: int,
    hora_inicio: int | None,
    horas: int,
    col_name: str,
    power_kw: float,
) -> None:
    """Escreve ``power_kw`` em ``horas`` horas consecutivas de um dia.

    Se ``hora_inicio`` for ``None`` (modo "centralizar no meio-dia"), a janela
    daquele dia é recalculada a cada chamada a partir de ``horas`` — que varia
    dia a dia (ex.: o último dia de um bloco concentrado recebe só o resto) —
    para ficar sempre centrada em 12h: ``inicio = 12 - horas // 2``.
    """
    if horas <= 0:
        return
    inicio = hora_inicio if hora_inicio is not None else max(0, 12 - horas // 2)
    indices = df[
        (df.index.month == mes)
        & (df.index.day == dia)
        & (df.index.hour >= inicio)
        & (df.index.hour < inicio + horas)
    ].index
    df.loc[indices, col_name] = power_kw


def distribuir_carga(
    df: pd.DataFrame,
    mes: int,
    grupo_idx: int,
    power_kw: float,
    horas_necessarias: int,
    teto_horas_dia: int,
    horas_min_por_dia: int,
    alternancia: bool,
    hora_inicio: int | None,
) -> tuple[int, int, int]:
    """Distribui as horas de carga no DataFrame de 8760h.

    Modifica ``df`` in-place, escrevendo ``power_kw`` nas colunas
    ``Grupo_A``/``Grupo_B`` nas horas selecionadas.

    A necessidade hídrica mensal é concentrada em ``ceil(horas_necessarias /
    horas_min_por_dia)`` dias, uniformemente espaçados no mês; cada dia opera
    ``horas_min_por_dia`` horas, exceto o último, que recebe só o resto (para
    manter a lâmina mensal exata). Se o mês exigir mais dias do que existem
    disponíveis, o piso relaxa: as horas são espalhadas por todos os dias,
    subindo acima do mínimo até o teto físico, e o que exceder vira déficit.

    Args:
        df: DataFrame indexado por datetime horário (8760 linhas), já
            contendo as colunas ``Grupo_A`` e ``Grupo_B`` inicializadas.
        mes: mês (1-12) a distribuir.
        grupo_idx: 0 para Grupo A, 1 para Grupo B.
        power_kw: potência elétrica do grupo de carga (kW).
        horas_necessarias: total de horas de irrigação necessárias no mês.
        teto_horas_dia: teto de horas de operação por dia (já combina o
            limite físico de 21h, o horário de início manual — se houver — e
            o teto manual opcional de ``horas_max_por_dia``; ver
            ``gerar_perfil_carga``).
        horas_min_por_dia: mínimo de horas que cada dia irrigado opera.
        alternancia: se True, Grupo A opera em dias ímpares e Grupo B em
            dias pares (calendário juliano do ano).
        hora_inicio: hora do dia (0-23) em que a irrigação começa, ou
            ``None`` para centralizar automaticamente cada dia em torno do
            meio-dia (ver ``_escrever_dia``).

    Returns:
        Tupla ``(horas_necessarias, deficit_horas, dias_operados)``, onde
        ``deficit_horas`` é a quantidade de horas que não puderam ser
        atendidas dentro do teto de operação disponível e ``dias_operados``
        é o número de dias do mês em que houve irrigação.
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

    if qtd_dias_uteis == 0 or horas_necessarias <= 0:
        return horas_necessarias, 0, 0

    col_name = f'Grupo_{"A" if grupo_idx == 0 else "B"}'
    alvo = max(1, min(horas_min_por_dia, teto_horas_dia))
    dias_operacao = math.ceil(horas_necessarias / alvo)
    deficit_horas = 0

    if dias_operacao <= qtd_dias_uteis:
        # Modo concentrado: poucos dias, cada um operando ``alvo`` horas
        # (o último recebe só o resto, para manter a lâmina mensal exata).
        dias_selecionados = _dias_espacados(dias_disponiveis, dias_operacao)
        horas_restantes = horas_necessarias
        for i, dia in enumerate(dias_selecionados):
            eh_ultimo = i == len(dias_selecionados) - 1
            horas_hoje = min(horas_restantes if eh_ultimo else alvo, teto_horas_dia)
            horas_restantes -= horas_hoje
            _escrever_dia(df, mes, dia, hora_inicio, horas_hoje, col_name, power_kw)
        return horas_necessarias, 0, len(dias_selecionados)

    # Mês exige mais dias do que há disponível: espalha por todos os dias,
    # subindo as horas/dia acima do piso, até o teto físico.
    max_horas_possiveis = qtd_dias_uteis * teto_horas_dia
    if horas_necessarias > max_horas_possiveis:
        deficit_horas = horas_necessarias - max_horas_possiveis
        horas_por_dia_base = teto_horas_dia
        horas_restantes = 0
    else:
        horas_por_dia_base = horas_necessarias // qtd_dias_uteis
        horas_restantes = horas_necessarias % qtd_dias_uteis

    for dia in dias_disponiveis:
        horas_hoje = horas_por_dia_base
        if horas_restantes > 0 and horas_hoje < teto_horas_dia:
            horas_hoje += 1
            horas_restantes -= 1
        horas_hoje = min(horas_hoje, teto_horas_dia)
        _escrever_dia(df, mes, dia, hora_inicio, horas_hoje, col_name, power_kw)

    return horas_necessarias, deficit_horas, qtd_dias_uteis


@dataclass
class BalancoHidricoMes:
    """Resultado do balanço hídrico de um grupo de carga em um mês."""

    mes: str
    precisa_mm: float
    entrega_mm: float
    deficit_mm: float
    dias_operacao: int = 0


@dataclass
class ResultadoPerfilCarga:
    """Resultado completo da geração de perfil de carga de irrigação."""

    df: pd.DataFrame  # índice datetime horário de 8760h, colunas Grupo_A/Grupo_B/Total_Load_kW
    balanco_a: list[BalancoHidricoMes]
    balanco_b: list[BalancoHidricoMes]
    avisos: list[str]
    # Lâmina mínima (mm/21h) que zeraria o déficit do mês mais crítico do
    # grupo, dentro da janela diária configurada (``None`` se não há déficit).
    # Só um aviso — não altera nada automaticamente (ver gerar_perfil_carga).
    lamina_sugerida_a: float | None = None
    lamina_sugerida_b: float | None = None


def gerar_perfil_carga(
    df_ref: pd.DataFrame,
    estado: str,
    grupo_a_potencia_kw: float,
    grupo_a_lamina_mm_21h: float,
    grupo_a_cultura_1: str,
    grupo_a_cultura_2: str | None,
    horas_min_por_dia: int,
    hora_inicio: int | None,
    alternancia: bool,
    horas_max_por_dia: int | None = None,
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
        horas_min_por_dia: mínimo de horas que cada dia irrigado opera. O
            app concentra a necessidade hídrica mensal em menos dias
            respeitando esse piso (ver ``distribuir_carga``).
        hora_inicio: hora do dia em que a irrigação inicia, ou ``None`` para
            centralizar automaticamente cada dia em torno do meio-dia (modo
            recomendado para simular sistemas sem diesel, que dependem da
            janela solar — ver ``_escrever_dia``).
        alternancia: se True, ativa o Grupo B em dias alternados.
        horas_max_por_dia: teto manual opcional de horas de operação por dia
            — usado para simular a autonomia de um sistema solar+BESS sem
            diesel (ex.: 10h). ``None`` (padrão) desativa esse teto: a única
            restrição passa a ser o limite físico (21h, ou ``24 -
            hora_inicio`` se o horário for manual).
        grupo_b_*: parâmetros equivalentes para o Grupo B (usado somente se
            ``alternancia=True`` e ``grupo_b_potencia_kw > 0``).
        ano_referencia: ano-base do calendário gerado (não bissexto
            recomendado, para manter 8760h).

    Returns:
        ``ResultadoPerfilCarga`` com o DataFrame horário, o balanço hídrico
        mensal de cada grupo, a lista de avisos de déficit e (se houver
        déficit) a lâmina de projeto mínima que o eliminaria dentro da
        janela configurada.
    """
    # Teto de horas de operação por dia, combinando até duas restrições
    # independentes:
    #   - física/horário: a irrigação nunca cruza a virada do dia civil nem
    #     passa de 21h (tempo de deslocamento/reposicionamento do pivô). Com
    #     horário manual, isso vira ``min(21, 24 - hora_inicio)``; com
    #     horário automático (centralizado no meio-dia), a janela nunca cruza
    #     a virada do dia por construção, então só o limite de 21h vale.
    #   - manual (``horas_max_por_dia``): teto opcional definido pelo
    #     usuário, para simular a autonomia de um sistema sem diesel.
    # O 21h de ``calcular_horas_mensais`` é a definição da lâmina de
    # projeto — um conceito distinto deste teto operacional.
    teto_horario = 21 if hora_inicio is None else min(21, max(1, 24 - hora_inicio))
    teto_horas_dia = (
        teto_horario if horas_max_por_dia is None else max(1, min(teto_horario, horas_max_por_dia))
    )

    dates = pd.date_range(start=f"{ano_referencia}-01-01", end=f"{ano_referencia}-12-31 23:00", freq="h")
    df = pd.DataFrame(index=dates)
    df["Grupo_A"] = 0.0
    df["Grupo_B"] = 0.0

    avisos: list[str] = []
    balanco_a: list[BalancoHidricoMes] = []
    balanco_b: list[BalancoHidricoMes] = []
    lamina_sugerida_a: float | None = None
    lamina_sugerida_b: float | None = None

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
        nec_a, def_a, dias_a = distribuir_carga(
            df, mes, 0, grupo_a_potencia_kw, horas_nec_a,
            teto_horas_dia, horas_min_por_dia, alternancia, hora_inicio,
        )

        h_entregue_a = nec_a - def_a
        mm_entregue_a = h_entregue_a * (grupo_a_lamina_mm_21h / 21.0) if horas_nec_a > 0 else 0

        balanco_a.append(
            BalancoHidricoMes(
                mes=MESES_NOMES[idx],
                precisa_mm=mm_nec_a,
                entrega_mm=min(mm_nec_a, mm_entregue_a),
                deficit_mm=max(0.0, mm_nec_a - mm_entregue_a),
                dias_operacao=dias_a,
            )
        )

        if def_a > 0:
            avisos.append(f"{MESES_NOMES[idx]} (Grupo A): Faltam {def_a} horas de água.")
            if dias_a > 0:
                # Lâmina mínima que, mantendo a mesma janela diária (dias_a
                # dias a teto_horas_dia h/dia), entregaria mm_nec_a por
                # inteiro — a exigência do mês mais crítico prevalece.
                lamina_min_a = 21.0 * mm_nec_a / (dias_a * teto_horas_dia)
                lamina_sugerida_a = lamina_min_a if lamina_sugerida_a is None else max(lamina_sugerida_a, lamina_min_a)

        # --- Grupo B ---
        if grupo_b_potencia_kw > 0:
            mm_nec_b = mm_final_b[idx]
            horas_nec_b = calcular_horas_mensais(mm_nec_b, grupo_b_lamina_mm_21h)
            nec_b, def_b, dias_b = distribuir_carga(
                df, mes, 1, grupo_b_potencia_kw, horas_nec_b,
                teto_horas_dia, horas_min_por_dia, alternancia, hora_inicio,
            )

            h_entregue_b = nec_b - def_b
            mm_entregue_b = h_entregue_b * (grupo_b_lamina_mm_21h / 21.0) if horas_nec_b > 0 else 0

            balanco_b.append(
                BalancoHidricoMes(
                    mes=MESES_NOMES[idx],
                    precisa_mm=mm_nec_b,
                    entrega_mm=min(mm_nec_b, mm_entregue_b),
                    deficit_mm=max(0.0, mm_nec_b - mm_entregue_b),
                    dias_operacao=dias_b,
                )
            )

            if def_b > 0:
                avisos.append(f"{MESES_NOMES[idx]} (Grupo B): Faltam {def_b} horas de água.")
                if dias_b > 0:
                    lamina_min_b = 21.0 * mm_nec_b / (dias_b * teto_horas_dia)
                    lamina_sugerida_b = lamina_min_b if lamina_sugerida_b is None else max(lamina_sugerida_b, lamina_min_b)

    df["Total_Load_kW"] = df["Grupo_A"] + df["Grupo_B"]

    return ResultadoPerfilCarga(
        df=df,
        balanco_a=balanco_a,
        balanco_b=balanco_b,
        avisos=avisos,
        lamina_sugerida_a=lamina_sugerida_a,
        lamina_sugerida_b=lamina_sugerida_b,
    )
