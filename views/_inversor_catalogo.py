"""Conversão do catálogo de inversores (editado em ``views/configuracoes.py``
via ``st.data_editor``, uma lista de dicts com colunas em português) para
``engine.inverter_catalog.ModeloInversor``.

O mapeamento nome-de-coluna -> campo do dataclass é uma escolha de
apresentação (rótulos exibidos na tabela), não lógica de negócio — por isso
fica aqui em ``views/``, não em ``engine/``.

Não é uma página em si — não é passada para ``st.Page``.
"""
from __future__ import annotations

from engine.inverter_catalog import ModeloInversor


def catalogo_para_modelos_inversor(linhas: list[dict]) -> list[ModeloInversor]:
    """Converte as linhas do editor de catálogo em ``ModeloInversor``.

    Linhas incompletas ou inválidas (ex.: uma linha nova adicionada pelo
    usuário no ``st.data_editor``, ainda vazia ou parcialmente preenchida)
    são silenciosamente ignoradas, em vez de quebrar o selectbox de
    Simulação Técnica.
    """
    modelos: list[ModeloInversor] = []
    for linha in linhas or []:
        try:
            modelos.append(
                ModeloInversor(
                    nome=str(linha.get("Modelo") or "").strip(),
                    pot_nominal_kw=float(linha.get("Potência Nominal (kW)") or 0),
                )
            )
        except (ValueError, TypeError):
            continue
    return modelos
