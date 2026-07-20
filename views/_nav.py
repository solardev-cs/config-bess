"""Definição única das páginas do app, compartilhada por ``app.py`` (registro
em ``st.navigation``) e por cada página do fluxo principal (``stepper()``),
para não duplicar path/título/ícone em vários lugares.

Não é uma página em si — não é passada para ``st.Page``.
"""
import streamlit as st

FLUXO = [
    {"path": "views/home.py", "title": "Home", "icon": ":material/home:", "url_path": "home"},
    {"path": "views/perfil_carga.py", "title": "Perfil de Carga", "icon": ":material/bar_chart:", "url_path": "perfil-de-carga"},
    {"path": "views/simulacao_tecnica.py", "title": "Simulação Técnica", "icon": ":material/battery_android_frame_bolt:", "url_path": "simulacao-tecnica"},
    {"path": "views/analise_financeira.py", "title": "Análise Financeira", "icon": ":material/currency_exchange:", "url_path": "analise-financeira"},
    {"path": "views/relatorio_viabilidade.py", "title": "Relatório de Viabilidade", "icon": ":material/assignment:", "url_path": "relatorio-viabilidade"},
]

CONFIGURACOES = {"path": "views/configuracoes.py", "title": "Configurações", "icon": ":material/settings:", "url_path": "configuracoes"}

# Chave em st.session_state cuja presença indica que a etapa já foi concluída
# (None = a etapa não tem um marco de conclusão próprio, ex. o Relatório).
_MARCO_CONCLUSAO = {
    "views/home.py": "mapa_lat",
    "views/perfil_carga.py": "carga_kw",
    "views/simulacao_tecnica.py": "ultima_simulacao",
    "views/analise_financeira.py": "ultima_analise_financeira",
    "views/relatorio_viabilidade.py": None,
}


def stepper(pagina_atual_path: str) -> None:
    """Indicador de progresso + navegação rápida entre as páginas do fluxo
    principal. Renderizado como o primeiro elemento de cada página do fluxo,
    antes até do título — mostra em que etapa o usuário está (com o ícone da
    página na etapa selecionada), quais etapas já têm dados salvos (✓, na cor
    primary do tema) e permite pular direto para qualquer uma delas
    (inclusive voltar e corrigir um input de uma etapa anterior) sem depender
    só da sidebar.
    """
    cols = st.columns(len(FLUXO))
    for col, pagina in zip(cols, FLUXO):
        with col:
            selecionada = pagina["path"] == pagina_atual_path
            marco = _MARCO_CONCLUSAO[pagina["path"]]
            concluida = marco is not None and st.session_state.get(marco) is not None

            rotulo = f"{pagina['icon']} {pagina['title']}" if selecionada else pagina["title"]
            if concluida:
                rotulo += " :primary[✓]"

            if selecionada:
                st.markdown(f"**{rotulo}**")
            else:
                st.page_link(pagina["path"], label=rotulo)
    st.divider()
