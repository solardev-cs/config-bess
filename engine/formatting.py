"""Formatação de números no padrão brasileiro (milhar com ponto, decimal com
vírgula) — usada pelas páginas Streamlit (``views/*.py``) para exibir
valores ao usuário.

Substitui o padrão ad hoc espalhado pelas páginas (``f"{x:,.2f}".replace(...)``
ou, pior, um único ``.replace(",", ".")`` que corrompe o separador decimal
sempre que o valor formatado tem casas decimais — ex.: ``f"{1234.5:,.1f}"``
gera ``"1,234.5"``, e um `.replace(",", ".")` isolado produz ``"1.234.5"``
em vez de ``"1.234,5"``).
"""


def formatar_numero(valor: float, casas_decimais: int = 0) -> str:
    """Formata ``valor`` no padrão pt-BR: milhar com ``.``, decimal com ``,``."""
    texto = f"{valor:,.{casas_decimais}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_brl(valor: float, casas_decimais: int = 0) -> str:
    """Formata ``valor`` como moeda: ``"R$ 1.234,56"``."""
    return f"R$ {formatar_numero(valor, casas_decimais)}"
