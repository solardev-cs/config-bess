"""Interface comum para estratégias de despacho horário.

Define o contrato que qualquer estratégia de despacho (load-following hoje;
time-shifting, peak-shaving e backup no futuro) deve implementar. Isso
permite que ``simulator.py`` execute o loop de 8760h chamando sempre o
mesmo método, independente da estratégia escolhida, e que o BESS/gerador/
solar sejam compartilhados entre todas as estratégias sem duplicação de
código físico.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from engine.battery import Battery
from engine.generator import Generator


@dataclass
class HourInput:
    """Entradas de uma hora do ano para o despacho."""

    hour_index: int  # 0..8759
    carga_kw: float  # E: carga elétrica da hora
    solar_disponivel_kw: float  # M: potência FV disponível após clipping do inversor (Pinv)
    solar_dc_kw: float | None = None  # L: Pp_disp, potência FV disponível ANTES do clipping do
    # inversor. Só é relevante para BESS de acoplamento CC (``DcCoupledDispatch``): nesse
    # arranjo, FV e BESS compartilham o mesmo inversor/PCS num barramento CC, então a energia
    # que seria perdida no clipping do lado CA ainda pode carregar o BESS pelo lado CC. Se
    # ``None`` (ex.: chamadas diretas de teste), as estratégias devem usar ``solar_disponivel_kw``
    # como fallback.


@dataclass
class HourResult:
    """Saída de uma hora do ano, após o despacho de todas as fontes.

    Os nomes dos campos mantêm um mapeamento claro com as colunas da
    planilha original (indicado entre parênteses), para facilitar a
    auditoria e os testes de regressão.
    """

    solar_direto_kw: float  # O: Pinv_disp (solar usado direto na carga)
    solar_sobra_kw: float  # P: Pinv_sobra (solar excedente, tenta carregar o BESS)
    bateria_descarga_kw: float  # Q: Pbat_utiliz
    bateria_soc_kwh: float  # R: SOC_bat (após a operação da hora)
    gerador_kw: float  # S: Pger
    piso_sobra_kw: float  # T: Psobra (sobra por geração mínima forçada do gerador que NÃO
    # foi absorvida — o que sobra depois de o gerador atender parte da carga e as outras
    # fontes cederem; é o que vira dump. Com piso 0% é sempre 0)
    solar_utilizado_kw: float  # U: Pinv_utiliz (solar líquido, após ceder ao piso do gerador)
    dump_kw: float  # V: Pdump (curtailment)
    nao_suprido_kw: float  # W: Prede (déficit não atendido por nenhuma fonte)
    gerador_ultrapassou_limite: bool = False
    consumo_diesel_litros: float = 0.0  # diesel consumido pelo parque na hora (``GeneratorDispatchResult.consumo_litros``)
    solar_armazenado_kw: float = 0.0  # energia solar efetivamente ACEITA pelo BESS nesta hora
    # (``charge_result.potencia_aplicada_kw``, já líquida do limite de potência/capacidade do
    # BESS, mas ANTES das perdas de descarga). Métrica só de EXIBIÇÃO — não entra em nenhuma
    # conta de energia evitada/financeiro (isso continua sendo só ``solar_utilizado_kw`` +
    # ``bateria_descarga_kw``, ver ``engine/financial.py``). Existe para dar visibilidade ao
    # usuário de quanto de energia solar realmente carregou o BESS mesmo quando
    # ``solar_utilizado_kw`` é 0.0 (acoplamento CC — ver ``dc_coupled.py``), onde "Energia
    # Solar" sozinha ficaria enganosamente zerada no dashboard.


class DispatchStrategy(Protocol):
    """Contrato que qualquer estratégia de despacho deve implementar."""

    def dispatch_hour(
        self,
        hour_input: HourInput,
        battery: Battery,
        generator: Generator,
    ) -> HourResult:
        """Executa o despacho de energia para uma única hora.

        Implementações devem chamar ``battery.charge``/``battery.discharge``
        e ``generator.dispatch`` para atualizar o estado interno do BESS e
        obter a resposta do gerador, retornando um ``HourResult`` completo.
        """
        ...
