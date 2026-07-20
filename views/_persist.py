"""Persistência de valores de widget entre páginas.

O Streamlit descarta ``st.session_state[key]`` de um widget assim que a
página que o declara deixa de ser renderizada (comportamento do
``st.navigation``/``st.Page`` usado em ``app.py`` — ver o comentário mais
detalhado em ``views/_staleness.py``). Ou seja, passar
``value=st.session_state.get(key, default)`` não é suficiente: quando o
usuário volta à página, ``session_state[key]`` já não existe mais e o
widget volta ao ``default`` hardcoded.

Este módulo guarda uma cópia do valor numa chave paralela (não ligada a
nenhum widget, portanto nunca descartada pelo Streamlit), atualizada a cada
rerun via ``persistir()``, e lida por ``valor_persistido()`` como o novo
default na próxima vez que o widget for recriado.
"""
import streamlit as st


def valor_persistido(chave_widget, default):
    """Default a usar em `value=`/`index=` ao (re)criar o widget `chave_widget`."""
    return st.session_state.get(f"_persist_{chave_widget}", default)


def persistir(chave_widget, valor):
    """Salva `valor` (retorno do widget) na cópia paralela e o repassa adiante,
    para poder ser encadeado em volta da própria chamada do widget:
    ``x = persistir("minha_key", st.number_input(..., key="minha_key"))``.
    """
    st.session_state[f"_persist_{chave_widget}"] = valor
    return valor


def indice_persistido(chave_widget, opcoes, default_index=0):
    """Índice (para `index=` de selectbox) a partir do último valor persistido,
    ou `default_index` se ainda não houver valor salvo ou ele não existir mais
    nas opções atuais (ex.: lista de opções mudou)."""
    valor_salvo = st.session_state.get(f"_persist_{chave_widget}")
    return opcoes.index(valor_salvo) if valor_salvo in opcoes else default_index


def forcar_valor(chave_widget, valor):
    """Define programaticamente o valor de um widget (ex.: preencher os campos
    de FV/BESS/gerador com o resultado da Otimização) antes de um `st.rerun()`.

    Precisa atualizar DUAS coisas: a cópia persistida (para
    `valor_persistido()` já nascer certa se o usuário navegar para outra
    página e voltar) e a própria chave do widget em `session_state` — só a
    cópia persistida não basta, porque se o widget já foi renderizado antes
    nesta mesma página (sem navegação), o frontend mantém seu próprio valor
    local e ignora um novo `value=` vindo do backend a menos que
    `session_state[chave_widget]` também seja escrito diretamente (é assim
    que o Streamlit sinaliza ao frontend para sobrescrever o valor exibido).

    Isso dispara o aviso do Streamlit "widget criado com um valor default mas
    também setado via a Session State API" — um alerta conhecido e esperado
    para este padrão (documentado pelo próprio Streamlit), por isso
    suprimido via `disableWidgetStateDuplicationWarning` em
    `.streamlit/config.toml`.
    """
    st.session_state[f"_persist_{chave_widget}"] = valor
    st.session_state[chave_widget] = valor
    return valor
