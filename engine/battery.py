"""Modelo físico do BESS (Battery Energy Storage System).

Este módulo corrige o bug mais crítico identificado na planilha original:
o BESS conseguia carregar/descarregar qualquer potência instantânea,
limitado apenas pela energia disponível (kWh), nunca por um limite de
potência (kW). Na prática isso permitia, por exemplo, uma bateria de
250 kWh entregar 5.000 kW em uma hora — fisicamente impossível.

Aqui, ``Battery`` modela corretamente:
    - Limite de potência de carga/descarga (kW), derivado do C-rate;
    - Limite de energia (SOC mínimo e capacidade máxima, kWh);
    - Eficiência round-trip (perdas na conversão AC/DC e química da célula).

A classe é stateful (mantém o SOC atual) para ser usada dentro do loop
horário do ``simulator.py``, mas também pode ser usada isoladamente pelas
futuras estratégias de time-shifting, peak-shaving e backup — por isso os
métodos ``charge``/``discharge`` são genéricos e não conhecem nada sobre
despacho load-following.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.models import BatteryConfig


@dataclass
class ChargeResult:
    """Resultado de uma operação de carga do BESS."""

    potencia_aplicada_kw: float  # potência de carga efetivamente aceita pelo BESS (no lado AC/DC de entrada)
    energia_armazenada_kwh: float  # energia que efetivamente entrou no pack (após perdas)
    soc_kwh: float  # novo SOC após a operação


@dataclass
class DischargeResult:
    """Resultado de uma operação de descarga do BESS."""

    potencia_entregue_kw: float  # potência de descarga efetivamente entregue (lado AC/DC de saída)
    energia_retirada_kwh: float  # energia efetivamente retirada do pack (antes das perdas de saída)
    soc_kwh: float  # novo SOC após a operação


class Battery:
    """Instância stateful de um BESS, com SOC atual controlado internamente.

    Args:
        config: parâmetros do BESS (capacidade, C-rate, DoD, eficiência).
        soc_inicial_kwh: SOC inicial. Se ``None``, inicia no SOC mínimo
            (mesmo comportamento da planilha original, que inicializa
            ``R6 = Dimensionamento!K9``).
    """

    def __init__(self, config: BatteryConfig, soc_inicial_kwh: float | None = None):
        self.config = config
        self.soc_kwh = soc_inicial_kwh if soc_inicial_kwh is not None else config.soc_min_kwh

    def reset(self, soc_inicial_kwh: float | None = None) -> None:
        """Reinicia o SOC do BESS (útil para rodar múltiplas simulações)."""
        self.soc_kwh = soc_inicial_kwh if soc_inicial_kwh is not None else self.config.soc_min_kwh

    def charge(self, potencia_disponivel_kw: float, dt_h: float = 1.0) -> ChargeResult:
        """Carrega o BESS com a potência disponível (ex.: sobra solar).

        A potência de carga é limitada pelo menor entre:
            (a) a potência disponível oferecida;
            (b) o limite de potência do BESS (derivado do C-rate);
            (c) o espaço restante até a capacidade máxima, respeitando a
                eficiência de carga (para não ultrapassar o teto de SOC).

        Args:
            potencia_disponivel_kw: potência (kW) disponível para carregar
                o BESS nesta hora (deve ser >= 0).
            dt_h: duração do intervalo de tempo, em horas (padrão 1h).

        Returns:
            ``ChargeResult`` com a potência aplicada, a energia
            efetivamente armazenada (já líquida de perdas) e o novo SOC.
        """
        if potencia_disponivel_kw < 0:
            raise ValueError("potencia_disponivel_kw não pode ser negativa.")

        eff = self.config.eficiencia_unidirecional
        espaco_livre_kwh = self.config.capacidade_kwh - self.soc_kwh

        # Potência AC/DC máxima que, aplicada por dt_h e multiplicada pela
        # eficiência, ainda cabe no espaço livre do pack.
        pot_limite_espaco_kw = (espaco_livre_kwh / eff) / dt_h if dt_h > 0 else 0.0

        potencia_aplicada_kw = min(
            potencia_disponivel_kw,
            self.config.potencia_kw,
            max(pot_limite_espaco_kw, 0.0),
        )

        energia_armazenada_kwh = potencia_aplicada_kw * dt_h * eff
        self.soc_kwh = min(self.config.capacidade_kwh, self.soc_kwh + energia_armazenada_kwh)

        return ChargeResult(
            potencia_aplicada_kw=potencia_aplicada_kw,
            energia_armazenada_kwh=energia_armazenada_kwh,
            soc_kwh=self.soc_kwh,
        )

    def discharge(self, potencia_requisitada_kw: float, dt_h: float = 1.0) -> DischargeResult:
        """Descarrega o BESS para atender a potência requisitada (ex.: déficit de carga).

        A potência de descarga é limitada pelo menor entre:
            (a) a potência requisitada (déficit a cobrir);
            (b) o limite de potência do BESS (derivado do C-rate);
            (c) a energia disponível acima do SOC mínimo, respeitando a
                eficiência de descarga.

        Args:
            potencia_requisitada_kw: potência (kW) que se deseja extrair do
                BESS nesta hora (deve ser >= 0).
            dt_h: duração do intervalo de tempo, em horas (padrão 1h).

        Returns:
            ``DischargeResult`` com a potência entregue, a energia retirada
            do pack (bruta, antes das perdas de saída) e o novo SOC.
        """
        if potencia_requisitada_kw < 0:
            raise ValueError("potencia_requisitada_kw não pode ser negativa.")

        eff = self.config.eficiencia_unidirecional
        energia_disponivel_kwh = max(self.soc_kwh - self.config.soc_min_kwh, 0.0)

        # Potência AC/DC máxima de saída que, sustentada por dt_h, ainda
        # respeita a energia disponível no pack (considerando perdas).
        pot_limite_energia_kw = (energia_disponivel_kwh * eff) / dt_h if dt_h > 0 else 0.0

        potencia_entregue_kw = min(
            potencia_requisitada_kw,
            self.config.potencia_kw,
            max(pot_limite_energia_kw, 0.0),
        )

        energia_retirada_kwh = (potencia_entregue_kw * dt_h) / eff if eff > 0 else 0.0
        self.soc_kwh = max(self.config.soc_min_kwh, self.soc_kwh - energia_retirada_kwh)

        return DischargeResult(
            potencia_entregue_kw=potencia_entregue_kw,
            energia_retirada_kwh=energia_retirada_kwh,
            soc_kwh=self.soc_kwh,
        )
