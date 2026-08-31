"""Conversão do catálogo de geradores (editado em ``views/configuracoes.py``
via ``st.data_editor``, uma lista de dicts com colunas em português) para
``engine.generator_catalog.ModeloGerador``.

O mapeamento nome-de-coluna -> campo do dataclass é uma escolha de
apresentação (rótulos exibidos na tabela), não lógica de negócio — por isso
fica aqui em ``views/``, não em ``engine/``.

Não é uma página em si — não é passada para ``st.Page``.
"""
from __future__ import annotations

from engine.generator_catalog import ModeloGerador

# Linha semente exibida em Configurações e usada como fallback por quem lê o catálogo
# (``valor_persistido("cfg_geradores_catalogo", CATALOGO_GERADORES_DEFAULT)``) antes de o
# usuário ter visitado Configurações nesta sessão — sem isso, `valor_persistido` cairia num
# `[]` vazio (nenhuma chave `_persist_cfg_geradores_catalogo` ainda gravada) e páginas como
# Simulação Técnica mostrariam "Nenhum modelo cadastrado" mesmo havendo um catálogo padrão.
CATALOGO_GERADORES_DEFAULT = [
    {
        "Modelo": "BRG Slim Infinity 550",
        "Potência Nominal (kVA)": 550.0,
        "Consumo (L/h)": 77.0,
        "FP": 0.8,
        "Potência Mínima (% da Prime em kW)": 0.0,
    }
]


def catalogo_para_modelos(linhas: list[dict]) -> list[ModeloGerador]:
    """Converte as linhas do editor de catálogo em ``ModeloGerador``.

    Linhas incompletas ou inválidas (ex.: uma linha nova adicionada pelo
    usuário no ``st.data_editor``, ainda vazia ou parcialmente preenchida)
    são silenciosamente ignoradas, em vez de quebrar o selectbox de
    Simulação Técnica.
    """
    modelos: list[ModeloGerador] = []
    for linha in linhas or []:
        try:
            modelos.append(
                ModeloGerador(
                    nome=str(linha.get("Modelo") or "").strip(),
                    pot_nominal_kva=float(linha.get("Potência Nominal (kVA)") or 0),
                    consumo_l_h=float(linha.get("Consumo (L/h)") or 0),
                    fp=float(linha.get("FP") or 0),
                    pot_min_pct=float(linha.get("Potência Mínima (% da Prime em kW)") or 0) / 100.0,
                )
            )
        except (ValueError, TypeError):
            continue
    return modelos
