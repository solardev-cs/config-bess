"""Carregamento do CSV de referência hídrica (``data/ref_hidrica.csv``),
compartilhado por Perfil de Carga (gera o perfil de carga de 8760h a partir
dele) e Configurações (exibe a tabela para consulta).

Não é uma página em si — não é passada para ``st.Page``.
"""
import os

import pandas as pd
import streamlit as st

DATA_FOLDER = "data"
DATA_FILE = "ref_hidrica.csv"
FILE_PATH = os.path.join(DATA_FOLDER, DATA_FILE)


@st.cache_data
def carregar_dados() -> pd.DataFrame:
    """Carrega o CSV tratando erros de codificação (acentos)."""
    if not os.path.exists(FILE_PATH):
        st.error(f"❌ Erro: O arquivo de dados não foi encontrado em '{FILE_PATH}'.")
        st.warning("Por favor, insira o arquivo 'ref_hidrica.csv' na pasta 'data' para continuar.")
        st.stop()

    try:
        # Tenta ler em UTF-8 (padrão moderno)
        return pd.read_csv(FILE_PATH, skipinitialspace=True, encoding="utf-8")
    except UnicodeDecodeError:
        try:
            # Se falhar, tenta Latin-1 (comum em arquivos de Excel/Windows BR)
            return pd.read_csv(FILE_PATH, skipinitialspace=True, encoding="latin1")
        except Exception as e:
            st.error(f"Erro ao ler o arquivo CSV: {e}")
            st.stop()
