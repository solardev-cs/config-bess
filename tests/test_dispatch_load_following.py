"""Testes unitários da estratégia de despacho load-following."""
from __future__ import annotations

import pytest

from engine.battery import Battery
from engine.dispatch.base import HourInput
from engine.dispatch.load_following import LoadFollowingDispatch
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


def test_solar_cobre_carga_totalmente_sem_sobra():
    battery = _battery(soc_inicial=25.0)
    generator = _generator()
    dispatch = LoadFollowingDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=100.0, solar_disponivel_kw=100.0), battery, generator)

    assert result.solar_direto_kw == pytest.approx(100.0)
    assert result.bateria_descarga_kw == pytest.approx(0.0)
    assert result.gerador_kw == pytest.approx(0.0)
    assert result.nao_suprido_kw == pytest.approx(0.0)


def test_sobra_solar_carrega_bateria():
    battery = _battery(soc_inicial=25.0, capacidade=250)
    generator = _generator()
    dispatch = LoadFollowingDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=50.0, solar_disponivel_kw=100.0), battery, generator)

    assert result.solar_direto_kw == pytest.approx(50.0)
    assert result.solar_sobra_kw == pytest.approx(50.0)
    assert result.solar_armazenado_kw == pytest.approx(50.0)  # toda a sobra coube no BESS
    assert battery.soc_kwh == pytest.approx(75.0)


def test_deficit_e_coberto_pela_bateria_antes_do_gerador():
    battery = _battery(soc_inicial=250.0, capacidade=250, c_rate=None)
    generator = _generator()
    dispatch = LoadFollowingDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=100.0, solar_disponivel_kw=0.0), battery, generator)

    assert result.bateria_descarga_kw == pytest.approx(100.0)
    assert result.gerador_kw == pytest.approx(0.0)


def test_deficit_residual_aciona_gerador():
    battery = _battery(soc_inicial=25.0, capacidade=250, c_rate=None, dod=0.9)  # sem energia disponível
    generator = _generator()
    dispatch = LoadFollowingDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=100.0, solar_disponivel_kw=0.0), battery, generator)

    assert result.bateria_descarga_kw == pytest.approx(0.0)
    assert result.gerador_kw == pytest.approx(100.0)


def test_deficit_maior_que_todas_as_fontes_gera_nao_suprido():
    battery = _battery(soc_inicial=25.0, capacidade=250, c_rate=None, dod=0.9)
    generator = _generator(nr_maquinas=1, pot_continua_kw=50, pot_prime_kva=50, fp=1.0)
    dispatch = LoadFollowingDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=100.0, solar_disponivel_kw=0.0), battery, generator)

    assert result.gerador_kw == pytest.approx(50.0)  # clampado pela potência total do parque
    assert result.nao_suprido_kw == pytest.approx(50.0)


def test_bateria_no_teto_gera_dump_load_quando_ha_sobra_solar():
    """Corrige o bug 2.2: sobra solar que não pode ser armazenada (BESS já
    no teto) deve aparecer no dump load, não ser silenciosamente descartada.
    """
    battery = _battery(soc_inicial=250.0, capacidade=250, c_rate=None)  # já no teto
    generator = _generator()
    dispatch = LoadFollowingDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=50.0, solar_disponivel_kw=100.0), battery, generator)

    assert result.solar_direto_kw == pytest.approx(50.0)
    assert result.dump_kw == pytest.approx(50.0)  # sobra que não coube na bateria
    assert result.solar_armazenado_kw == pytest.approx(0.0)  # BESS já no teto, nada foi aceito
    assert battery.soc_kwh == pytest.approx(250.0)


def test_bateria_respeita_limite_de_potencia_de_carga():
    """C-rate 0,5 com 250 kWh -> 125 kW. Sobra de 200 kW deve ser parcialmente
    armazenada (125 kW) e o restante (75 kW) deve virar dump.
    """
    battery = _battery(soc_inicial=25.0, capacidade=250, c_rate=0.5, dod=0.9)
    generator = _generator()
    dispatch = LoadFollowingDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=0.0, solar_disponivel_kw=200.0), battery, generator)

    assert result.dump_kw == pytest.approx(75.0)
    assert battery.soc_kwh == pytest.approx(150.0)


# --- Sobra do piso do gerador: as outras fontes cedem (BESS 1º, solar direta 2º) ---


def test_gerador_no_piso_reduz_primeiro_a_descarga_da_bateria():
    """Sem solar: carga 300, gerador Sempre ON com piso 120 -> gerador 120, BESS só 180."""
    battery = _battery(soc_inicial=250.0, capacidade=250, c_rate=None)
    generator = _generator(modo="Sempre ON", pot_continua_kw=400, pot_prime_kva=400, pot_min_pct=0.3)
    dispatch = LoadFollowingDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=300.0, solar_disponivel_kw=0.0), battery, generator)

    assert result.gerador_kw == pytest.approx(120.0)
    assert result.bateria_descarga_kw == pytest.approx(180.0)
    assert result.piso_sobra_kw == pytest.approx(0.0)
    assert result.dump_kw == pytest.approx(0.0)
    assert battery.soc_kwh == pytest.approx(250.0 - 180.0)


def test_gerador_no_piso_faz_a_solar_direta_ceder_e_a_solar_liberada_carrega_a_bateria():
    """Solar 300 cobre toda a carga (300), BESS não descarrega. Gerador Sempre ON no piso (120):
    a solar direta cede 120, que vai carregar o BESS em vez de virar dump."""
    battery = _battery(soc_inicial=100.0, capacidade=400, c_rate=None, dod=0.9)
    generator = _generator(modo="Sempre ON", pot_continua_kw=400, pot_prime_kva=400, pot_min_pct=0.3)
    dispatch = LoadFollowingDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=300.0, solar_disponivel_kw=300.0), battery, generator)

    assert result.gerador_kw == pytest.approx(120.0)
    assert result.solar_utilizado_kw == pytest.approx(180.0)  # 300 - 120 cedidos
    assert result.solar_armazenado_kw == pytest.approx(120.0)  # a parcela liberada foi para o BESS
    assert battery.soc_kwh == pytest.approx(100.0 + 120.0)
    assert result.piso_sobra_kw == pytest.approx(0.0)
    assert result.dump_kw == pytest.approx(0.0)
    assert result.nao_suprido_kw == pytest.approx(0.0)


def test_solar_liberada_que_nao_cabe_no_bess_vira_dump():
    """Mesmo cenário, mas com o BESS já cheio: a solar liberada não tem onde ser guardada."""
    battery = _battery(soc_inicial=400.0, capacidade=400, c_rate=None)
    generator = _generator(modo="Sempre ON", pot_continua_kw=400, pot_prime_kva=400, pot_min_pct=0.3)
    dispatch = LoadFollowingDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=300.0, solar_disponivel_kw=300.0), battery, generator)

    assert result.solar_utilizado_kw == pytest.approx(180.0)
    assert result.solar_armazenado_kw == pytest.approx(0.0)
    assert result.dump_kw == pytest.approx(120.0)


def test_piso_maior_que_a_carga_deixa_so_o_excedente_como_dump():
    battery = _battery(soc_inicial=250.0, capacidade=250, c_rate=None)
    generator = _generator(modo="Sempre ON", pot_continua_kw=400, pot_prime_kva=400, pot_min_pct=0.3)
    dispatch = LoadFollowingDispatch()

    result = dispatch.dispatch_hour(HourInput(0, carga_kw=100.0, solar_disponivel_kw=0.0), battery, generator)

    assert result.bateria_descarga_kw == pytest.approx(0.0)
    assert result.piso_sobra_kw == pytest.approx(20.0)
    assert result.dump_kw == pytest.approx(20.0)
