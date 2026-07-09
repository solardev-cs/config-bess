"""Loop de simulação horária (8760h) — o coração do motor de cálculo.

Substitui a aba "Cálculo Técnico" da planilha original (8760 linhas com
dependência sequencial via SOC da bateria) por um loop stateful em Python.

Esta é a peça central que qualquer interface (Streamlit hoje, uma futura
API/SaaS depois) deve chamar para obter o fluxo de energia completo do
sistema híbrido ao longo do ano.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from engine.battery import Battery
from engine.dispatch.base import DispatchStrategy, HourInput
from engine.generator import Generator
from engine.models import BatteryConfig, GeneratorConfig, SimulationKPIs, SolarConfig
from engine.solar.base import SolarProfileProvider
from engine.solar.pv_generation import PERDAS_SISTEMA_PADRAO_PCT, gerar_potencia_fv


@dataclass
class SimulationResult:
    """Resultado completo de uma simulação horária de 8760h."""

    df: pd.DataFrame  # 8760 linhas, colunas equivalentes às da aba "Cálculo Técnico"
    kpis: SimulationKPIs


def simular_ano(
    carga_kw: np.ndarray,
    solar_config: SolarConfig,
    solar_provider: SolarProfileProvider,
    battery_config: BatteryConfig,
    generator_config: GeneratorConfig,
    dispatch_strategy: DispatchStrategy,
    soc_inicial_kwh: float | None = None,
    perdas_sistema_fv_pct: float = PERDAS_SISTEMA_PADRAO_PCT,
) -> SimulationResult:
    """Executa a simulação horária de 8760h do sistema híbrido.

    Args:
        carga_kw: array de 8760 posições com a carga elétrica horária (kW).
        solar_config: configuração do sistema fotovoltaico (potência do
            inversor, ILR).
        solar_provider: provedor do perfil normalizado de irradiância
            (estático ou dinâmico via API).
        battery_config: configuração do BESS.
        generator_config: configuração do parque de geradores.
        dispatch_strategy: estratégia de despacho a ser usada
            (ex.: ``LoadFollowingDispatch()``).
        soc_inicial_kwh: SOC inicial do BESS. Se ``None``, inicia no SOC
            mínimo (mesmo comportamento da planilha original).
        perdas_sistema_fv_pct: fração de perdas de sistema do arranjo FV
            (sujeira, cabeamento, mismatch etc.), aplicada em
            ``gerar_potencia_fv``. Padrão: 14%. Use ``0.0`` para reproduzir
            o comportamento da planilha original (sem perdas modeladas).

    Returns:
        ``SimulationResult`` com o DataFrame horário completo e os KPIs
        agregados da simulação.

    Raises:
        ValueError: se ``carga_kw`` não tiver exatamente 8760 posições.
    """
    if len(carga_kw) != 8760:
        raise ValueError(f"carga_kw deve ter 8760 posições, encontrado {len(carga_kw)}.")

    fracao_irradiancia = solar_provider.get_normalized_profile()
    if len(fracao_irradiancia) != 8760:
        raise ValueError(
            f"O perfil solar deve ter 8760 posições, encontrado {len(fracao_irradiancia)}."
        )

    # L: Pp_disp (potência DC disponível do arranjo, antes do clipping do inversor,
    # já líquida das perdas de sistema do FV)
    pp_disp_kw = gerar_potencia_fv(fracao_irradiancia, solar_config, perdas_sistema_fv_pct)

    # M: Pinv (potência após clipping do inversor, "Pinv_disp" na planilha)
    pinv_kw = np.minimum(pp_disp_kw, solar_config.pot_inv_kw)

    battery = Battery(battery_config, soc_inicial_kwh=soc_inicial_kwh)
    generator = Generator(generator_config)

    n = 8760
    solar_direto = np.zeros(n)
    solar_sobra = np.zeros(n)
    bateria_descarga = np.zeros(n)
    bateria_soc = np.zeros(n)
    gerador = np.zeros(n)
    piso_sobra = np.zeros(n)
    solar_utilizado = np.zeros(n)
    dump = np.zeros(n)
    nao_suprido = np.zeros(n)
    gerador_ultrapassou = np.zeros(n, dtype=bool)

    for h in range(n):
        result = dispatch_strategy.dispatch_hour(
            HourInput(hour_index=h, carga_kw=float(carga_kw[h]), solar_disponivel_kw=float(pinv_kw[h])),
            battery,
            generator,
        )
        solar_direto[h] = result.solar_direto_kw
        solar_sobra[h] = result.solar_sobra_kw
        bateria_descarga[h] = result.bateria_descarga_kw
        bateria_soc[h] = result.bateria_soc_kwh
        gerador[h] = result.gerador_kw
        piso_sobra[h] = result.piso_sobra_kw
        solar_utilizado[h] = result.solar_utilizado_kw
        dump[h] = result.dump_kw
        nao_suprido[h] = result.nao_suprido_kw
        gerador_ultrapassou[h] = result.gerador_ultrapassou_limite

    df = pd.DataFrame(
        {
            "carga_kw": carga_kw,
            "pp_disp_kw": pp_disp_kw,
            "pinv_kw": pinv_kw,
            "solar_direto_kw": solar_direto,
            "solar_sobra_kw": solar_sobra,
            "bateria_descarga_kw": bateria_descarga,
            "bateria_soc_kwh": bateria_soc,
            "gerador_kw": gerador,
            "piso_sobra_kw": piso_sobra,
            "solar_utilizado_kw": solar_utilizado,
            "dump_kw": dump,
            "nao_suprido_kw": nao_suprido,
            "gerador_ultrapassou_limite": gerador_ultrapassou,
        }
    )

    kpis = SimulationKPIs(
        energia_carga_total_kwh=float(df["carga_kw"].sum()),
        energia_solar_utilizada_kwh=float(df["solar_utilizado_kw"].sum()),
        energia_bateria_descarregada_kwh=float(df["bateria_descarga_kw"].sum()),
        energia_gerador_kwh=float(df["gerador_kw"].sum()),
        energia_nao_suprida_kwh=float(df["nao_suprido_kw"].sum()),
        energia_curtailed_kwh=float(df["dump_kw"].sum()),
        horas_com_deficit=int((df["nao_suprido_kw"] > 1e-6).sum()),
    )

    return SimulationResult(df=df, kpis=kpis)
