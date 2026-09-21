"""Estratégia de despacho para BESS de acoplamento CC (DC-coupled).

Num BESS DC-coupled "tudo-em-um", o inversor solar e o PCS do BESS são o
mesmo equipamento, com FV e bateria compartilhando um único barramento CC
antes da conversão para CA. Isso inverte a ordem de despacho em relação ao
acoplamento CA (``load_following.py``):

    toda a energia solar carrega o BESS primeiro (pelo lado CC, sem passar
    pelo clipping do inversor) -> a carga é sempre suprida descarregando o
    BESS -> o déficit residual aciona o gerador (respeitando piso de carga
    mínima) -> eventual sobra por geração mínima forçada do gerador reduz a
    descarga do BESS (o gerador já atende essa parcela da carga; a energia volta
    ao SOC) -> o que ainda sobrar (piso maior que a carga da hora) vira dump
    load -> resíduo final (se houver) é energia não suprida.

Duas diferenças físicas em relação ao acoplamento CA, ambas intencionais:

    1. Não existe mais um caminho "solar direto para a carga": toda a
       energia entregue à carga passa pela bateria, então incorre na perda
       de round-trip do BESS mesmo quando solar e carga coincidem na hora.
    2. Por outro lado, a energia solar usada para carregar o BESS é a
       potência DC do arranjo ANTES do clipping do inversor (``solar_dc_kw``,
       equivalente à coluna L "Pp_disp" da planilha) — não a potência já
       recortada pela potência nominal do inversor (``solar_disponivel_kw``,
       coluna M "Pinv"). Em dias de pico, isso recupera energia que no
       acoplamento CA seria perdida em clipping, desde que caiba na potência
       e capacidade do BESS.

``solar_utilizado_kw`` é sempre 0.0 nesta estratégia (nunca ``bateria_descarga_kw``
subtraída de algo): ``engine/financial.py`` soma
``energia_solar_utilizada_kwh + energia_bateria_descarregada_kwh`` como a energia
evitada total, tratando as duas parcelas como grandezas não sobrepostas (para
aplicar a degradação de FV só sobre uma e a de SOH do BESS só sobre a outra —
ver docstring de ``calcular_fluxo_de_caixa``). Como aqui NÃO existe um fluxo de
solar independente da bateria (tudo passa por ela), atribuir qualquer parte de
``bateria_descarga_kw`` também a ``solar_utilizado_kw`` contaria a mesma energia
duas vezes. A simplificação resultante — 100% da energia evitada de um BESS CC
degrada pela taxa de SOH do BESS, nenhuma pela taxa de degradação do FV — é
consistente com a física do arranjo: todo kWh entregue à carga passou pelo
ciclo de carga/descarga do BESS.

Como isso deixa o dashboard mostrando "Energia Solar: 0 kWh" mesmo quando a
maior parte (ou toda) a energia entregue teve origem solar, ``solar_armazenado_kw``
(ver ``HourResult``) reporta, só para EXIBIÇÃO, quanto de energia solar
efetivamente carregou o BESS a cada hora — sem entrar em nenhuma conta
financeira, evitando reabrir a questão de dupla contagem acima.
"""
from __future__ import annotations

from engine.battery import Battery
from engine.dispatch.base import HourInput, HourResult
from engine.generator import Generator


class DcCoupledDispatch:
    """Estratégia de despacho para BESS de acoplamento CC (FV e BESS no mesmo PCS)."""

    def dispatch_hour(
        self,
        hour_input: HourInput,
        battery: Battery,
        generator: Generator,
        dt_h: float = 1.0,
    ) -> HourResult:
        """Executa o despacho DC-coupled para uma única hora.

        Args:
            hour_input: carga e solar disponível da hora. Usa
                ``solar_dc_kw`` (potência FV antes do clipping do inversor)
                quando disponível, com fallback para ``solar_disponivel_kw``.
            battery: instância stateful do BESS (SOC é atualizado in-place).
            generator: instância do parque de geradores.
            dt_h: duração do intervalo, em horas.

        Returns:
            ``HourResult`` com o fluxo de energia completo da hora.
        """
        carga_kw = hour_input.carga_kw
        solar_dc_kw = (
            hour_input.solar_dc_kw if hour_input.solar_dc_kw is not None else hour_input.solar_disponivel_kw
        )

        # Toda a potência solar disponível (lado CC, sem clipping do inversor)
        # tenta carregar o BESS primeiro, respeitando potência e capacidade.
        charge_result = battery.charge(solar_dc_kw, dt_h=dt_h)
        curtailed_charge_kw = solar_dc_kw - charge_result.potencia_aplicada_kw

        # A carga é sempre suprida descarregando o BESS, respeitando potência e energia.
        discharge_result = battery.discharge(carga_kw, dt_h=dt_h)
        bateria_descarga_kw = discharge_result.potencia_entregue_kw

        # Déficit remanescente após o BESS, a ser coberto pelo gerador.
        deficit_pos_bateria_kw = carga_kw - bateria_descarga_kw

        gen_result = generator.dispatch(deficit_pos_bateria_kw, carga_kw=carga_kw, dt_h=dt_h)
        gerador_kw = gen_result.potencia_kw

        # Sobra por geração mínima forçada do gerador (piso de carga mínima): o gerador
        # está ligado e gerando mais do que o déficit que sobrou depois do BESS.
        sobra_piso_kw = max(0.0, (bateria_descarga_kw + gerador_kw) - carga_kw)

        # Essa geração forçada já atende parte da carga, então o BESS não precisava ter
        # descarregado essa parcela: desfaz-a (a energia volta ao SOC, sem perda de carga).
        # Só o que ainda sobrar depois disso — piso do gerador MAIOR que a carga da hora —
        # não tem para onde ir. O gerador nunca carrega o BESS: o motor assume (financeiro
        # e "fração renovável") que toda energia armazenada é de origem solar.
        descarga_evitada_kw = min(sobra_piso_kw, bateria_descarga_kw)
        if descarga_evitada_kw > 0:
            battery.desfazer_descarga(descarga_evitada_kw, dt_h=dt_h)
            bateria_descarga_kw -= descarga_evitada_kw
        piso_sobra_kw = sobra_piso_kw - descarga_evitada_kw

        # Dump load total = sobra do piso do gerador que não pôde ser absorvida (não há solar
        # direto para abater, diferente do acoplamento CA) + energia solar que não pôde ser
        # armazenada no BESS.
        dump_kw = piso_sobra_kw + curtailed_charge_kw

        # Energia não suprida por nenhuma fonte (déficit residual).
        nao_suprido_kw = max(0.0, carga_kw - (bateria_descarga_kw + gerador_kw))

        return HourResult(
            solar_direto_kw=0.0,
            solar_sobra_kw=solar_dc_kw,
            bateria_descarga_kw=bateria_descarga_kw,
            bateria_soc_kwh=battery.soc_kwh,
            gerador_kw=gerador_kw,
            piso_sobra_kw=piso_sobra_kw,
            # Sempre 0.0 nesta estratégia — ver nota no docstring do módulo sobre por que
            # atribuir parte de bateria_descarga_kw aqui também contaria energia em dobro
            # em engine/financial.py.
            solar_utilizado_kw=0.0,
            dump_kw=dump_kw,
            nao_suprido_kw=nao_suprido_kw,
            gerador_ultrapassou_limite=gen_result.ultrapassou_limite,
            solar_armazenado_kw=charge_result.potencia_aplicada_kw,
        )
