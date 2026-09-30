"""Custos de referência efetivos (FV e BESS), compartilhados por Configurações,
Simulação Técnica (Otimização) e Análise Financeira.

O custo do FV padrão depende do acoplamento do BESS selecionado (CA ou CC —
ver ``engine.costs.custo_fv_padrao_rs_kwp``). Em Configurações ele pode ficar
em modo "automático" (segue o acoplamento do BESS escolhido em Simulação
Técnica) ou ser digitado à mão; quem CONSOME o valor precisa resolver isso na
hora de usar — por isso passa por ``custo_fv_efetivo_rs_kwp()`` em vez de ler
``cfg_custo_fv`` direto: se o usuário trocar de BESS CA para CC em Simulação
Técnica sem revisitar Configurações, o valor automático tem que acompanhar.

Não é uma página em si — não é passada para ``st.Page``.
"""
from __future__ import annotations

from engine.costs import custo_fv_padrao_rs_kwp
from views._bess_catalogo import CATALOGO_BESS_DEFAULT, catalogo_para_modelos_bess
from views._persist import valor_persistido


def acoplamento_bess_selecionado(linhas_catalogo: list[dict] | None = None) -> str:
    """Acoplamento ("CA"/"CC") do modelo de BESS atualmente selecionado em
    Simulação Técnica; o primeiro do catálogo se nenhum foi escolhido ainda
    (é o que o selectbox mostra por padrão), e "CA" se o catálogo está vazio.

    ``linhas_catalogo`` permite passar o catálogo recém-editado (Configurações
    o edita na própria página, depois de onde o custo do FV é desenhado); sem
    ele, usa a cópia persistida.
    """
    if linhas_catalogo is None:
        linhas_catalogo = valor_persistido("cfg_bess_catalogo", CATALOGO_BESS_DEFAULT)
    modelos = catalogo_para_modelos_bess(linhas_catalogo)
    if not modelos:
        return "CA"
    nome_selecionado = valor_persistido("bess_modelo", None)
    for modelo in modelos:
        if modelo.nome == nome_selecionado:
            return modelo.acoplamento
    return modelos[0].acoplamento


def custo_fv_efetivo_rs_kwp(acoplamento: str | None = None) -> float:
    """Custo do FV (R$/kWp) a usar agora: o valor digitado em Configurações se
    o modo automático estiver desligado; senão o padrão do acoplamento do BESS.

    ``acoplamento`` sobrescreve a detecção pelo BESS selecionado (útil quando o
    chamador já tem o modelo em mãos, ex.: o que a Otimização está usando).
    """
    if acoplamento is None:
        # Sem BESS (capacidade 0, ex.: "Solar + Diesel") o FV é sempre de acoplamento CA.
        acoplamento = acoplamento_bess_selecionado() if valor_persistido("bess_capacidade", 0.0) > 0 else "CA"
    padrao = custo_fv_padrao_rs_kwp(acoplamento)
    if valor_persistido("cfg_custo_fv_auto", True):
        return padrao
    return valor_persistido("cfg_custo_fv", padrao)
