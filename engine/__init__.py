"""Motor de cálculo do Configurador Off-Grid.

Este pacote é 100% Python puro (sem dependências de Streamlit ou de
qualquer outra camada de interface). Ele existe para que a mesma lógica de
simulação, despacho e análise financeira possa ser reutilizada tanto pela
interface Streamlit atual quanto por uma futura API/SaaS.

Regra de ouro: nada dentro de `engine/` pode fazer `import streamlit`.
"""
