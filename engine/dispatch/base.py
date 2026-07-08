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
    piso_sobra_kw: float  # T: Psobra (sobra por geração mínima forçada do gerador)
    solar_utilizado_kw: float  # U: Pinv_utiliz (solar líquido, após abater o piso do gerador)
    dump_kw: float  # V: Pdump (curtailment)
    nao_suprido_kw: float  # W: Prede (déficit não atendido por nenhuma fonte)
    gerador_ultrapassou_limite: bool = False


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
