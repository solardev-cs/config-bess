"""Salvar/abrir projeto (export/import JSON) na sidebar.

NÃO é uma página. Um "projeto" é o conjunto de inputs guardados em
``st.session_state`` pelo padrão ``persistir()`` (chaves ``_persist_<key>``, ver
``views/_persist.py``) mais a localização do mapa (``mapa_lat``/``mapa_lon``,
gravadas direto). A (de)serialização, o esquema de chaves aceitas e a validação
ficam em ``engine/project_io.py``; aqui só há o vínculo com o ``session_state``.

Resultados calculados (perfil de carga, simulação, análise financeira) não são
salvos — ao abrir um projeto eles são descartados e recalculados nas páginas.
"""
import copy
import re
from datetime import datetime
import unicodedata

import streamlit as st

from engine.costs import CUSTO_BESS_PADRAO_RS_KWH
from engine.project_io import (
    CHAVES_CONFIG,
    CHAVES_PROJETO,
    ProjetoInvalidoError,
    desserializar,
    serializar,
)
from views._bess_catalogo import CATALOGO_BESS_DEFAULT
from views._gerador_catalogo import CATALOGO_GERADORES_DEFAULT
from views._inversor_catalogo import CATALOGO_INVERSORES_DEFAULT

_CHAVES_DIRETAS = ("mapa_lat", "mapa_lon")  # gravadas direto no session_state (sem persistir())

# Resultados derivados dos inputs: descartados ao abrir um projeto para não
# exibir números do projeto anterior (as páginas os recalculam/pedem recálculo).
_CHAVES_DERIVADAS = (
    "carga_kw", "carga_estado", "carga_descricao", "carga_grupos",
    "ultima_simulacao", "ultima_solar_config", "ultima_battery_config",
    "ultima_generator_config", "ultima_simulacao_config", "ultima_bess_acoplamento",
    "ultima_analise_financeira", "ultima_analise_financeira_config",
)


# Valores efetivos das Configurações quando o usuário ainda não abriu a página (os widgets de
# `views/configuracoes.py` só gravam `_persist_cfg_*` ao serem renderizados). Gravá-los no arquivo
# o torna reproduzível mesmo que os padrões do código mudem. Devem acompanhar os `value=` de
# configuracoes.py. Fora daqui (sem padrão fixo): `cfg_custo_fv` (vale só com o automático
# desligado, e então já foi persistido) e `cfg_curva_modelo` (só seleção de visualização).
_CONFIG_PADRAO = {
    "cfg_custo_bess": CUSTO_BESS_PADRAO_RS_KWH,
    "cfg_preco_diesel": 7.0,
    "cfg_tma": 5.0,
    "cfg_horizonte_anos": 25,
    "cfg_valor_saca": 120.0,
    "cfg_custo_fv_auto": True,
    "cfg_degradacao_fv": 0.6,
    "cfg_degradacao_bess_soh": 2.0,
    "cfg_geradores_catalogo": CATALOGO_GERADORES_DEFAULT,
    "cfg_inversores_catalogo": CATALOGO_INVERSORES_DEFAULT,
    "cfg_bess_catalogo": CATALOGO_BESS_DEFAULT,
}


def _ler_chave(chave):
    if chave in _CHAVES_DIRETAS:
        return st.session_state.get(chave)
    return st.session_state.get(f"_persist_{chave}")


def _coletar(esquema, padroes=None):
    padroes = padroes or {}
    valores = {}
    for chave in esquema:
        valor = _ler_chave(chave)
        valores[chave] = copy.deepcopy(padroes.get(chave)) if valor is None else valor
    return {chave: valor for chave, valor in valores.items() if valor is not None}


def _nome_arquivo():
    partes = [st.session_state.get("_persist_home_cliente") or "projeto", st.session_state.get("_persist_home_revisao") or ""]
    texto = "_".join(p for p in partes if p)
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^A-Za-z0-9]+", "_", texto).strip("_") or "projeto"
    return f"ConfigBESS_{texto}.json"


def _formatar_data(iso):
    """'2026-09-30T12:00:06' -> '30/09/2026 12:00' (None se ausente/inválida)."""
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return None


def _aplicar(carregado):
    blocos = [(CHAVES_PROJETO, carregado.projeto)]
    if carregado.configuracoes:  # arquivo sem Configurações (ex.: formato antigo): mantém as atuais
        blocos.append((CHAVES_CONFIG, carregado.configuracoes))

    for chave in _CHAVES_DERIVADAS:
        st.session_state.pop(chave, None)

    for esquema, valores in blocos:
        for chave, tipo in esquema.items():
            if chave in _CHAVES_DIRETAS:
                if chave in valores:
                    st.session_state[chave] = valores[chave]
                else:
                    st.session_state.pop(chave, None)
                continue
            if chave not in valores:
                st.session_state.pop(f"_persist_{chave}", None)
                continue
            st.session_state[f"_persist_{chave}"] = valores[chave]
            # Só o widget da página ativa ainda existe no session_state; ele precisa
            # ser sobrescrito também (mesmo motivo de `forcar_valor()` em _persist.py).
            if tipo != "catalogo" and chave in st.session_state:
                st.session_state[chave] = valores[chave]
            if tipo == "catalogo":
                st.session_state.pop(f"{chave}_editor", None)  # estado interno do st.data_editor


@st.dialog("Abrir projeto")
def _dialogo_abrir_projeto():
    contador = st.session_state.get("_projeto_upload_n", 0)
    arquivo = st.file_uploader("Selecione o arquivo do projeto", type="json", key=f"_projeto_upload_{contador}")
    if arquivo is None:
        return
    try:
        carregado = desserializar(arquivo.getvalue().decode("utf-8"))
    except (ProjetoInvalidoError, UnicodeDecodeError) as erro:
        st.error(str(erro) if isinstance(erro, ProjetoInvalidoError) else "Arquivo não é um texto UTF-8 válido.")
        return
    _aplicar(carregado)
    st.session_state["_projeto_aberto"] = arquivo.name.removesuffix(".json")
    st.session_state["_projeto_aberto_salvo_em"] = _formatar_data(carregado.salvo_em)
    st.session_state["_projeto_upload_n"] = contador + 1  # esvazia o uploader
    if carregado.avisos:
        st.toast(f"{len(carregado.avisos)} campo(s) do arquivo foram ignorados.", icon=":material/warning:")
    st.rerun()  # fecha o diálogo e recarrega a página com os dados aplicados


def renderizar_projeto_sidebar():
    """Botões de salvar e abrir projeto na sidebar; abrir (em diálogo) aplica o arquivo na hora."""
    st.download_button(
        "Salvar projeto", data=serializar(_coletar(CHAVES_PROJETO), _coletar(CHAVES_CONFIG, _CONFIG_PADRAO)),
        file_name=_nome_arquivo(), mime="application/json", icon=":material/download:", width="stretch",
    )
    if st.button("Abrir projeto", icon=":material/upload:", width="stretch"):
        _dialogo_abrir_projeto()

    if st.session_state.get("_projeto_aberto"):
        linhas = [":material/description: Projeto aberto:", st.session_state["_projeto_aberto"]]
        if st.session_state.get("_projeto_aberto_salvo_em"):
            linhas.append(f"(salvo em {st.session_state['_projeto_aberto_salvo_em']})")
        st.caption("  \n".join(linhas))  # uma só legenda: mesma fonte/tamanho, linhas coladas
