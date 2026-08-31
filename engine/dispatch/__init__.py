"""Estratégias de despacho de energia entre fontes (interface comum)."""
from __future__ import annotations

from engine.bess_catalog import TipoAcoplamentoBess
from engine.dispatch.base import DispatchStrategy
from engine.dispatch.dc_coupled import DcCoupledDispatch
from engine.dispatch.load_following import LoadFollowingDispatch


def dispatch_strategy_para_acoplamento(acoplamento: TipoAcoplamentoBess) -> DispatchStrategy:
    """Escolhe a estratégia de despacho a partir do acoplamento do BESS.

    "CA" -> ``LoadFollowingDispatch`` (solar cobre a carga direto, sobra
    carrega o BESS). "CC" -> ``DcCoupledDispatch`` (toda a solar carrega o
    BESS primeiro, a carga é sempre suprida pela descarga do BESS) — ver
    docstring de ``dc_coupled.py`` e a nota de arquitetura no ``CLAUDE.md``.
    """
    if acoplamento == "CC":
        return DcCoupledDispatch()
    return LoadFollowingDispatch()
