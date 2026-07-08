"""Estratégia de despacho load-following.

Réplica corrigida da estratégia de despacho implementada na aba "Cálculo
Técnico" da planilha original. A lógica de fluxo de energia é a mesma:

    solar -> cobre carga direta -> excedente carrega bateria ->
    déficit descarrega bateria -> resíduo aciona gerador (respeitando
    piso de carga mínima) -> sobra do piso é abatida do solar ->
    o que não pode ser abatido vira dump load -> resíduo final (se houver)
    é energia não suprida.

Correções aplicadas em relação à planilha original:
    1. A carga/descarga do BESS agora respeita o limite de potência (kW),
       não apenas o limite de energia (kWh) — via ``Battery.charge`` /
       ``Battery.discharge`` (bug 1a da análise).
    2. Quando o BESS está com o SOC no teto e ainda há sobra solar, a
       energia que não pode ser armazenada agora é contabilizada no "dump
       load" (V), em vez de ser silenciosamente descartada sem
       contabilização (bug 2.2 da análise).
    3. O despacho do gerador agora recebe a carga total da hora (para o
       modo "Sempre ON") e nunca ultrapassa a potência nominal total do
       parque (bug 1g da análise, resolvido dentro de ``Generator.dispatch``).
"""
from __future__ import annotations

from engine.battery import Battery
from engine.dispatch.base import HourInput, HourResult
from engine.generator import Generator


class LoadFollowingDispatch:
    """Estratégia de despacho load-following (a mesma da planilha original, corrigida)."""

    def dispatch_hour(
        self,
        hour_input: HourInput,
        battery: Battery,
        generator: Generator,
        dt_h: float = 1.0,
    ) -> HourResult:
        """Executa o despacho load-following para uma única hora.

        Args:
            hour_input: carga e solar disponível da hora.
            battery: instância stateful do BESS (SOC é atualizado in-place).
            generator: instância do parque de geradores.
            dt_h: duração do intervalo, em horas.

        Returns:
            ``HourResult`` com o fluxo de energia completo da hora.
        """
        carga_kw = hour_input.carga_kw
        solar_disp_kw = hour_input.solar_disponivel_kw

        # O: solar usado direto na carga (equivalente a Pinv_disp)
        solar_direto_kw = min(solar_disp_kw, carga_kw)

        # P: sobra solar bruta, candidata a carregar o BESS (Pinv_sobra)
        solar_sobra_bruta_kw = solar_disp_kw - solar_direto_kw

        # Carrega o BESS com a sobra solar, respeitando potência e capacidade.
        charge_result = battery.charge(solar_sobra_bruta_kw, dt_h=dt_h)
        curtailed_charge_kw = solar_sobra_bruta_kw - charge_result.potencia_aplicada_kw

        # Déficit remanescente após usar solar direto, antes do BESS.
        deficit_pre_bateria_kw = carga_kw - solar_direto_kw

        # Q: descarrega o BESS para cobrir o déficit, respeitando potência e energia.
        discharge_result = battery.discharge(deficit_pre_bateria_kw, dt_h=dt_h)
        bateria_descarga_kw = discharge_result.potencia_entregue_kw

        # Déficit remanescente após solar + BESS, a ser coberto pelo gerador.
        deficit_pos_bateria_kw = deficit_pre_bateria_kw - bateria_descarga_kw

        gen_result = generator.dispatch(deficit_pos_bateria_kw, carga_kw=carga_kw, dt_h=dt_h)
        gerador_kw = gen_result.potencia_kw

        # T: sobra por geração mínima forçada do gerador (piso de carga mínima)
        piso_sobra_kw = max(0.0, (solar_direto_kw + bateria_descarga_kw + gerador_kw) - carga_kw)

        # U: solar líquido efetivamente utilizado (após abater o piso do gerador)
        solar_utilizado_kw = max(0.0, solar_direto_kw - piso_sobra_kw)

        # V: dump load total = sobra do piso mínimo do gerador que não pôde ser
        # abatida do solar + energia solar que não pôde ser armazenada no BESS
        # (BESS já no teto de capacidade/potência) — este segundo termo é a
        # correção do bug 2.2 (curtailment "invisível" da planilha original).
        dump_piso_kw = max(0.0, piso_sobra_kw - solar_direto_kw)
        dump_kw = dump_piso_kw + curtailed_charge_kw

        # W: energia não suprida por nenhuma fonte (déficit residual)
        nao_suprido_kw = max(0.0, carga_kw - (bateria_descarga_kw + gerador_kw + solar_utilizado_kw))

        return HourResult(
            solar_direto_kw=solar_direto_kw,
            solar_sobra_kw=solar_sobra_bruta_kw,
            bateria_descarga_kw=bateria_descarga_kw,
            bateria_soc_kwh=battery.soc_kwh,
            gerador_kw=gerador_kw,
            piso_sobra_kw=piso_sobra_kw,
            solar_utilizado_kw=solar_utilizado_kw,
            dump_kw=dump_kw,
            nao_suprido_kw=nao_suprido_kw,
            gerador_ultrapassou_limite=gen_result.ultrapassou_limite,
        )
