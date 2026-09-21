"""Testes unitários da estratégia de despacho DC-coupled (BESS acoplamento CC)."""
from __future__ import annotations

import pytest

from engine.battery import Battery
from engine.dispatch.base import HourInput
from engine.dispatch.dc_coupled import DcCoupledDispatch
from engine.generator import Generator
from engine.models import BatteryConfig, GeneratorConfig


def _battery(c_rate=None, capacidade=250, dod=0.9, eficiencia_rt=1.0, soc_inicial=None):
    config = BatteryConfig(capacidade_kwh=capacidade, c_rate=c_rate, dod=dod, eficiencia_rt=eficiencia_rt)
    return Battery(config, soc_inicial_kwh=soc_inicial)


def _generator(**overrides):
    defaults = dict(
        nr_maquinas=1,
        nr_min_maquinas=1,
        pot_continua_kw=1000,
        pot_prime_kva=1000,
        fp=1.0,
        pot_min_pct=0.0,
        modo="ON/OFF",
    )
    defaults.update(overrides)
    return Generator(GeneratorConfig(**defaults))


def test_solar_carrega_bateria_antes_de_suprir_a_carga():
    battery = _battery(soc_inicial=25.0, capacidade=250, c_rate=None)
    generator = _generator()
    dispatch = DcCoupledDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=50.0, solar_disponivel_kw=100.0), battery, generator)

    # Não existe caminho "solar direto" no acoplamento CC.
    assert result.solar_direto_kw == pytest.approx(0.0)
    assert result.bateria_descarga_kw == pytest.approx(50.0)
    assert result.gerador_kw == pytest.approx(0.0)
    assert result.nao_suprido_kw == pytest.approx(0.0)
    # solar_utilizado_kw fica 0.0 (evita dupla contagem no financeiro), mas
    # solar_armazenado_kw (métrica só de exibição) reporta a solar real que entrou no BESS.
    assert result.solar_utilizado_kw == pytest.approx(0.0)
    assert result.solar_armazenado_kw == pytest.approx(100.0)
    # SOC: 25 + 100 (carga) - 50 (descarga) = 75, sem perdas (eficiencia_rt=1.0).
    assert battery.soc_kwh == pytest.approx(75.0)


def test_deficit_e_coberto_pela_bateria_antes_do_gerador():
    battery = _battery(soc_inicial=250.0, capacidade=250, c_rate=None)
    generator = _generator()
    dispatch = DcCoupledDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=100.0, solar_disponivel_kw=0.0), battery, generator)

    assert result.bateria_descarga_kw == pytest.approx(100.0)
    assert result.gerador_kw == pytest.approx(0.0)


def test_deficit_residual_aciona_gerador():
    battery = _battery(soc_inicial=25.0, capacidade=250, c_rate=None, dod=0.9)  # sem energia disponível
    generator = _generator()
    dispatch = DcCoupledDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=100.0, solar_disponivel_kw=0.0), battery, generator)

    assert result.bateria_descarga_kw == pytest.approx(0.0)
    assert result.gerador_kw == pytest.approx(100.0)


def test_perda_de_round_trip_incide_mesmo_com_solar_igual_a_carga():
    """Diferença física central em relação ao acoplamento CA: como toda a energia
    entregue à carga passa pela bateria, a perda de round-trip incide mesmo quando
    a solar da hora é exatamente igual à carga (o que no acoplamento CA não gera
    nenhuma perda, pois o fluxo é direto)."""
    battery = _battery(soc_inicial=0.0, capacidade=1000, dod=1.0, c_rate=None, eficiencia_rt=0.81)
    generator = _generator(nr_maquinas=0, nr_min_maquinas=0)  # isola o efeito, sem gerador cobrindo o resíduo
    dispatch = DcCoupledDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=100.0, solar_disponivel_kw=100.0), battery, generator)

    # eficiência unidirecional = sqrt(0.81) = 0.9 -> 100 carregados vira 90 kWh no pack,
    # e só 90*0.9 = 81 kW conseguem ser descarregados de volta.
    assert result.bateria_descarga_kw == pytest.approx(81.0)
    assert result.nao_suprido_kw == pytest.approx(19.0)


def test_bateria_no_teto_gera_dump_load_quando_ha_sobra_solar():
    battery = _battery(soc_inicial=250.0, capacidade=250, c_rate=None)  # já no teto
    generator = _generator()
    dispatch = DcCoupledDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=50.0, solar_disponivel_kw=100.0), battery, generator)

    assert result.bateria_descarga_kw == pytest.approx(50.0)
    assert result.dump_kw == pytest.approx(100.0)  # toda a sobra solar não coube na bateria
    assert battery.soc_kwh == pytest.approx(250.0 - 50.0)


def test_bateria_respeita_limite_de_potencia_de_carga():
    """C-rate 0,5 com 250 kWh -> 125 kW. Sobra de 200 kW deve ser parcialmente
    armazenada (125 kW) e o restante (75 kW) deve virar dump."""
    battery = _battery(soc_inicial=25.0, capacidade=250, c_rate=0.5, dod=0.9)
    generator = _generator()
    dispatch = DcCoupledDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=0.0, solar_disponivel_kw=200.0), battery, generator)

    assert result.dump_kw == pytest.approx(75.0)
    assert battery.soc_kwh == pytest.approx(150.0)


def test_usa_solar_pre_clip_para_carregar_a_bateria():
    """Recupera energia que seria perdida no clipping do inversor no acoplamento CA:
    o BESS CC carrega com a potência DC do arranjo antes do clip (``solar_dc_kw``),
    não com a potência já recortada pelo inversor (``solar_disponivel_kw``)."""
    battery = _battery(soc_inicial=0.0, capacidade=1000, dod=1.0, c_rate=None)
    generator = _generator()
    dispatch = DcCoupledDispatch()

    result = dispatch.dispatch_hour(
        HourInput(0, carga_kw=0.0, solar_disponivel_kw=50.0, solar_dc_kw=150.0), battery, generator
    )

    assert result.solar_sobra_kw == pytest.approx(150.0)
    assert battery.soc_kwh == pytest.approx(150.0)


# --- Sobra do piso do gerador: o gerador já atende parte da carga, o BESS descarrega menos ---


def test_gerador_sempre_on_no_piso_reduz_a_descarga_do_bess_em_vez_de_virar_dump():
    """Carga 300 kW, BESS com energia de sobra, gerador Sempre ON com piso de 120 kW:
    o gerador entrega 120 e o BESS só os 180 restantes — nada é jogado fora."""
    battery = _battery(soc_inicial=250.0, capacidade=250, c_rate=None)
    generator = _generator(modo="Sempre ON", pot_continua_kw=400, pot_prime_kva=400, pot_min_pct=0.3)  # piso 120
    dispatch = DcCoupledDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=300.0, solar_disponivel_kw=0.0), battery, generator)

    assert result.gerador_kw == pytest.approx(120.0)
    assert result.bateria_descarga_kw == pytest.approx(180.0)
    assert result.piso_sobra_kw == pytest.approx(0.0)
    assert result.dump_kw == pytest.approx(0.0)
    assert result.nao_suprido_kw == pytest.approx(0.0)
    # o SOC só perdeu os 180 kW efetivamente descarregados (eficiência 1,0)
    assert battery.soc_kwh == pytest.approx(250.0 - 180.0)


def test_gerador_on_off_com_deficit_menor_que_o_piso_tambem_absorve_a_sobra():
    """BESS quase vazio entrega só 270 kW dos 300; falta 30 < piso (120): o gerador liga no
    piso, e a bateria devolve ao SOC o que não precisava ter descarregado."""
    battery = _battery(soc_inicial=40.0 + 270.0, capacidade=400, c_rate=None, dod=0.9)  # 270 kWh disponíveis
    generator = _generator(modo="ON/OFF", pot_continua_kw=400, pot_prime_kva=400, pot_min_pct=0.3)  # piso 120
    dispatch = DcCoupledDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=300.0, solar_disponivel_kw=0.0), battery, generator)

    assert result.gerador_kw == pytest.approx(120.0)  # o déficit era só 30
    assert result.bateria_descarga_kw == pytest.approx(180.0)  # 270 - 90 de sobra absorvida
    assert result.piso_sobra_kw == pytest.approx(0.0)
    assert result.bateria_descarga_kw + result.gerador_kw == pytest.approx(300.0)
    assert battery.soc_kwh == pytest.approx(40.0 + 90.0)  # sobraram 90 dos 270 kWh disponíveis


def test_piso_maior_que_a_carga_deixa_so_o_excedente_como_dump():
    """Carga 100 kW < piso 120 kW: a bateria não descarrega nada e os 20 kW acima da carga
    não têm para onde ir (o gerador nunca carrega o BESS) -> dump."""
    battery = _battery(soc_inicial=250.0, capacidade=250, c_rate=None)
    generator = _generator(modo="Sempre ON", pot_continua_kw=400, pot_prime_kva=400, pot_min_pct=0.3)  # piso 120
    dispatch = DcCoupledDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=100.0, solar_disponivel_kw=0.0), battery, generator)

    assert result.gerador_kw == pytest.approx(120.0)
    assert result.bateria_descarga_kw == pytest.approx(0.0)
    assert result.piso_sobra_kw == pytest.approx(20.0)
    assert result.dump_kw == pytest.approx(20.0)
    assert battery.soc_kwh == pytest.approx(250.0)  # nada foi descarregado


def test_piso_zero_nao_muda_nada():
    """Paridade: com piso 0% o gerador só cobre o déficit, então não há sobra a absorver."""
    battery = _battery(soc_inicial=40.0 + 100.0, capacidade=400, c_rate=None, dod=0.9)  # 100 kWh disponíveis
    generator = _generator(modo="Sempre ON", pot_min_pct=0.0)
    dispatch = DcCoupledDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=300.0, solar_disponivel_kw=0.0), battery, generator)

    assert result.bateria_descarga_kw == pytest.approx(100.0)
    assert result.gerador_kw == pytest.approx(200.0)
    assert result.piso_sobra_kw == pytest.approx(0.0)
