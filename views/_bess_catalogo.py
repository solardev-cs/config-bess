"""Conversão do catálogo de BESS (editado em ``views/configuracoes.py`` via
``st.data_editor``, uma lista de dicts com colunas em português) para
``engine.bess_catalog.ModeloBess``.

O mapeamento nome-de-coluna -> campo do dataclass é uma escolha de
apresentação (rótulos exibidos na tabela), não lógica de negócio — por isso
fica aqui em ``views/``, não em ``engine/``.

Não é uma página em si — não é passada para ``st.Page``.
"""
from __future__ import annotations

from engine.bess_catalog import ModeloBess

# Linha semente exibida em Configurações e usada como fallback por quem lê o catálogo
# (``valor_persistido("cfg_bess_catalogo", CATALOGO_BESS_DEFAULT)``) antes de o usuário ter
# visitado Configurações nesta sessão — ver nota em ``_gerador_catalogo.py``.
CATALOGO_BESS_DEFAULT = [
    {
        "Modelo": "BSCW400H", "Capacidade Nominal (kWh)": 241.0, "Potência Nominal (kW)": 125.0,
        "Eficiência (%)": 90.0, "Acoplamento Solar": "CA",
    },
]


def catalogo_para_modelos_bess(linhas: list[dict]) -> list[ModeloBess]:
    """Converte as linhas do editor de catálogo em ``ModeloBess``.

    Linhas incompletas ou inválidas (ex.: uma linha nova adicionada pelo
    usuário no ``st.data_editor``, ainda vazia ou parcialmente preenchida)
    são silenciosamente ignoradas, em vez de quebrar o selectbox de
    Simulação Técnica.
    """
    modelos: list[ModeloBess] = []
    for linha in linhas or []:
        try:
            modelos.append(
                ModeloBess(
                    nome=str(linha.get("Modelo") or "").strip(),
                    capacidade_nominal_kwh=float(linha.get("Capacidade Nominal (kWh)") or 0),
                    pot_nominal_kw=float(linha.get("Potência Nominal (kW)") or 0),
                    eficiencia_pct=float(linha.get("Eficiência (%)") or 0),
                    acoplamento=str(linha.get("Acoplamento Solar") or "CA").strip() or "CA",
                )
            )
        except (ValueError, TypeError):
            continue
    return modelos
