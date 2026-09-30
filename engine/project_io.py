"""Serialização de projetos (inputs do usuário) para/de JSON versionado.

Python puro, sem streamlit — reutilizável por uma futura API/banco: o mesmo
texto JSON gerado aqui pode ser gravado numa coluna JSONB. Um "projeto" é o
conjunto de INPUTS do usuário (não os resultados calculados, que são
recalculáveis), dividido em dois blocos:

- ``projeto``: dados do cliente, localização, perfil de carga, configuração
  técnica (gerador/FV/BESS) e financeira;
- ``configuracoes``: parâmetros de referência (custos, TMA, degradação) e
  catálogos de equipamentos — reaproveitáveis entre projetos.

Só chaves conhecidas (``CHAVES_PROJETO``/``CHAVES_CONFIG``) com o tipo esperado
são aceitas; o resto é descartado com um aviso, para que um arquivo editado à
mão ou de outra versão não injete estado arbitrário no app.
"""
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, time

import numpy as np

SCHEMA_VERSION = 1
TAMANHO_MAXIMO_CARACTERES = 1_000_000
MAX_LINHAS_CATALOGO = 200

# chave -> tipo esperado: texto | inteiro | decimal | bool | hora | catalogo.
# inteiro/decimal importam: os widgets numéricos do Streamlit rejeitam tipos mistos
# (ex.: value=int com step=float), e JSON de outras origens (JS, banco) perde o ".0".
CHAVES_PROJETO = {
    # Home
    "home_cliente": "texto", "home_cidade": "texto", "home_estado": "texto",
    "home_gnf": "texto", "home_revisao": "texto",
    "mapa_lat": "decimal", "mapa_lon": "decimal",
    # Perfil de Carga
    "carga_estado_input": "texto",
    "hora_inicio_auto": "bool", "hora_inicio_irrigacao": "hora",
    "horas_max_auto": "bool", "horas_max_operacao": "inteiro",
    "horas_min_operacao": "inteiro", "alternancia": "bool",
    "cA1": "texto", "cA2": "texto", "cB1": "texto", "cB2": "texto",
    "pA": "decimal", "lA": "decimal", "aA": "decimal",
    "pB": "decimal", "lB": "decimal", "aB": "decimal",
    # Simulação Técnica
    "opt_metrica": "texto", "opt_tipo_sistema": "texto",
    "ger_modelo": "texto", "ger_nr": "inteiro", "ger_nr_min": "inteiro", "ger_modo": "texto",
    "fv_modelo": "texto", "fv_pot_inv": "decimal", "fv_ilr": "decimal",
    "bess_modelo": "texto", "bess_capacidade": "decimal", "bess_dod": "inteiro",
    # Análise Financeira
    "fin_om": "decimal", "fin_diesel_inflacao": "decimal", "fin_tipo_pagto": "texto",
    "fin_pct_financ": "inteiro", "fin_tipo_financ": "texto", "fin_prazo": "inteiro",
    "fin_carencia": "inteiro", "fin_taxa_juros": "decimal",
}

CHAVES_CONFIG = {
    "cfg_custo_bess": "decimal", "cfg_preco_diesel": "decimal", "cfg_tma": "decimal",
    "cfg_horizonte_anos": "inteiro", "cfg_valor_saca": "decimal",
    "cfg_custo_fv": "decimal", "cfg_custo_fv_auto": "bool",
    "cfg_degradacao_fv": "decimal", "cfg_degradacao_bess_soh": "decimal",
    "cfg_curva_modelo": "texto",
    "cfg_geradores_catalogo": "catalogo", "cfg_inversores_catalogo": "catalogo",
    "cfg_bess_catalogo": "catalogo",
}

_TAG_TIPO = "__tipo__"


class ProjetoInvalidoError(ValueError):
    """Arquivo que não é um projeto válido (JSON quebrado, versão futura etc.)."""


@dataclass
class ProjetoCarregado:
    projeto: dict
    configuracoes: dict
    schema_version: int
    salvo_em: str | None = None
    avisos: list[str] = field(default_factory=list)


def _limpar(valor):
    """Converte para tipos JSON puros (numpy -> python, NaN -> None, time -> tag)."""
    if isinstance(valor, time):
        return {_TAG_TIPO: "time", "valor": valor.strftime("%H:%M:%S")}
    if isinstance(valor, np.generic):
        valor = valor.item()
    if isinstance(valor, float) and not math.isfinite(valor):
        return None
    if isinstance(valor, dict):
        return {str(k): _limpar(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_limpar(v) for v in valor]
    return valor


def _decodificar(valor):
    """Inverso de `_limpar` para o que tem tag (hoje só `time`)."""
    if isinstance(valor, dict) and valor.get(_TAG_TIPO) == "time":
        try:
            return datetime.strptime(str(valor.get("valor")), "%H:%M:%S").time()
        except ValueError:
            return None
    return valor


def _coagir(tipo, valor):
    """Normaliza o tipo numérico ao esperado pelo widget (120 -> 120.0; 5.0 -> 5)."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return valor
    if tipo == "decimal":
        return float(valor)
    if tipo == "inteiro" and float(valor).is_integer():
        return int(valor)
    return valor


def _tipo_valido(tipo, valor) -> bool:
    if tipo == "texto":
        return isinstance(valor, str)
    if tipo == "inteiro":  # já coagido por `_coagir`: um float não-inteiro (2.5) sobra e é rejeitado
        return isinstance(valor, int) and not isinstance(valor, bool)
    if tipo == "decimal":
        return isinstance(valor, float) and math.isfinite(valor)
    if tipo == "bool":
        return isinstance(valor, bool)
    if tipo == "hora":
        return isinstance(valor, time)
    if tipo == "catalogo":
        return (
            isinstance(valor, list)
            and len(valor) <= MAX_LINHAS_CATALOGO
            and all(
                isinstance(linha, dict)
                and all(
                    isinstance(k, str) and (v is None or isinstance(v, (str, int, float, bool)))
                    for k, v in linha.items()
                )
                for linha in valor
            )
        )
    return False


def _filtrar(bloco, esquema: dict, nome_bloco: str, avisos: list[str]) -> dict:
    if not isinstance(bloco, dict):
        avisos.append(f"Bloco '{nome_bloco}' ausente ou inválido — ignorado.")
        return {}
    aceitos = {}
    for chave, bruto in bloco.items():
        if chave not in esquema:
            avisos.append(f"Campo desconhecido ignorado: {chave}")
            continue
        valor = _coagir(esquema[chave], _decodificar(bruto))
        if valor is None:
            continue
        if not _tipo_valido(esquema[chave], valor):
            avisos.append(f"Valor inválido para '{chave}' — ignorado.")
            continue
        aceitos[chave] = valor
    return aceitos


def serializar(projeto: dict, configuracoes: dict | None = None, salvo_em: str | None = None) -> str:
    """Gera o texto JSON de um projeto. Só chaves conhecidas com valor não-nulo entram."""
    def _so_validas(bloco, esquema):
        limpo = {}
        for chave, valor in (bloco or {}).items():
            if chave not in esquema or valor is None:
                continue
            valor = _coagir(esquema[chave], _limpar(valor))
            if _tipo_valido(esquema[chave], _decodificar(valor)):
                limpo[chave] = valor
        return limpo

    documento = {
        "schema_version": SCHEMA_VERSION,
        "salvo_em": salvo_em or datetime.now().isoformat(timespec="seconds"),
        "projeto": _so_validas(projeto, CHAVES_PROJETO),
        "configuracoes": _so_validas(configuracoes, CHAVES_CONFIG),
    }
    return json.dumps(documento, ensure_ascii=False, indent=2)


# Migrações incrementais: MIGRACOES[n] converte o documento da versão n para n+1.
MIGRACOES: dict = {}


def desserializar(texto: str) -> ProjetoCarregado:
    """Lê e valida o texto de um projeto. Levanta `ProjetoInvalidoError` se não for utilizável."""
    if len(texto) > TAMANHO_MAXIMO_CARACTERES:
        raise ProjetoInvalidoError("Arquivo grande demais para ser um projeto.")
    try:
        documento = json.loads(texto)
    except json.JSONDecodeError as erro:
        raise ProjetoInvalidoError(f"Arquivo não é um JSON válido ({erro.msg}).") from erro
    if not isinstance(documento, dict) or not isinstance(documento.get("schema_version"), int):
        raise ProjetoInvalidoError("Arquivo não parece ser um projeto do ConfigBESS.")

    versao = documento["schema_version"]
    if versao > SCHEMA_VERSION:
        raise ProjetoInvalidoError(
            f"Projeto salvo numa versão mais nova do app (formato v{versao}; este app entende até v{SCHEMA_VERSION})."
        )
    while versao < SCHEMA_VERSION:
        migrar = MIGRACOES.get(versao)
        if migrar is None:
            raise ProjetoInvalidoError(f"Não há migração do formato v{versao}.")
        documento = migrar(documento)
        versao += 1

    avisos: list[str] = []
    return ProjetoCarregado(
        projeto=_filtrar(documento.get("projeto"), CHAVES_PROJETO, "projeto", avisos),
        configuracoes=_filtrar(documento.get("configuracoes"), CHAVES_CONFIG, "configuracoes", avisos),
        schema_version=documento["schema_version"],
        salvo_em=documento.get("salvo_em") if isinstance(documento.get("salvo_em"), str) else None,
        avisos=avisos,
    )
