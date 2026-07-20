"""Ponto de entrada Streamlit: define a navegação multipage via ``st.Page``/
``st.navigation`` (em vez da convenção baseada em nome de arquivo da pasta
``pages/``), o que permite títulos com acentuação correta na barra lateral
e desacopla o rótulo exibido do nome do arquivo Python.

Fluxo principal: Home -> Perfil de Carga -> Simulação Técnica -> Análise
Financeira -> Relatório de Viabilidade. Cada etapa persiste seu resultado em
``st.session_state`` para a próxima etapa consumir. "Configurações" é uma
página à parte (parâmetros que raramente mudam), por isso o menu é montado
manualmente (``position="hidden"`` + ``st.page_link``) para poder separá-la
do fluxo principal com um divisor, algo que o menu automático do
``st.navigation`` não permite.

``views/_nav.py`` é a fonte única de path/título/ícone de cada página do
fluxo — reaproveitada aqui e pela trilha de navegação rápida (breadcrumb)
que cada página do fluxo renderiza no topo.
"""
import streamlit as st

from views._nav import CONFIGURACOES, FLUXO

st.set_page_config(page_title="Configurador BESS", page_icon="🗲", layout="wide")

paginas_fluxo = [
    st.Page(p["path"], title=p["title"], icon=p["icon"], url_path=p["url_path"], default=(p["path"] == FLUXO[0]["path"]))
    for p in FLUXO
]
pagina_configuracoes = st.Page(
    CONFIGURACOES["path"], title=CONFIGURACOES["title"], icon=CONFIGURACOES["icon"], url_path=CONFIGURACOES["url_path"]
)

pg = st.navigation([*paginas_fluxo, pagina_configuracoes], position="hidden")

# images/logo_app_{light,dark}.svg são logotipos ("CONFIG BESS" + ícone de
# bateria/raio) gerados sob medida — troque pelo arquivo definitivo quando
# houver um. As cores (ícone = primaryColor, texto = cor de texto padrão do
# tema) estão fixas em cada SVG; se mudar primaryColor no config.toml, edite
# o `fill` dos dois arquivos também para manter consistência. Streamlit não
# troca a imagem de st.logo sozinho por tema, então escolhemos o arquivo
# certo via st.context.theme.type (claro/escuro).
# st.context.theme.type pode vir desatualizado por uma execução logo após o
# usuário trocar o tema no menu Settings — limitação documentada do próprio
# Streamlit (github.com/streamlit/streamlit/issues/11920). Guardamos o
# último valor visto e, se ele mudou desde a última execução, forçamos mais
# um rerun imediato para pegar o valor já assentado o quanto antes, em vez
# de só corrigir na próxima interação do usuário (ex.: trocar de página).
tema_atual = st.context.theme.type
if tema_atual is not None:
    tema_anterior = st.session_state.get("_tema_logo_anterior")
    st.session_state["_tema_logo_anterior"] = tema_atual
    if tema_anterior is not None and tema_anterior != tema_atual:
        st.rerun()

LOGO_APP = "images/logo_app_dark.svg" if tema_atual == "dark" else "images/logo_app_light.svg"
# logo_fck_dark.png = versão clara (texto branco), para o rodapé no tema
# escuro; logo_fck_light.png = versão escura (texto preto), para o tema
# claro — nomeadas pelo tema em que são usadas, não pela própria cor.
LOGO_EMPRESA = "images/logo_fck_dark.png" if tema_atual == "dark" else "images/logo_fck_light.png"

with st.sidebar:
    # st.logo ocupa o slot reservado no topo da sidebar (mesma posição onde
    # ficava a marca da Fockink) — só uma imagem consegue alinhar ali,
    # st.markdown/st.image comuns renderizam mais abaixo, como conteúdo normal.
    st.logo(LOGO_APP)

    for pagina in paginas_fluxo:
        st.page_link(pagina)

    st.divider()
    st.page_link(pagina_configuracoes)

    # Empurra o bloco seguinte (rodapé) para o fim da sidebar: o contêiner de
    # conteúdo da sidebar já é um flex column no Streamlit 1.54; um elemento
    # com flex-grow:1 logo após "Configurações" consome o espaço vazio
    # restante, jogando só o rodapé (não o menu inteiro) para baixo.
    st.markdown(
        """
        <style>
        [data-testid="stSidebarContent"] {
            display: flex;
            flex-direction: column;
            height: 100%;
        }
        [data-testid="stSidebarUserContent"] {
            flex: 1 1 auto;
            min-height: 0;
            /* Reduz o respiro nativo de 96px do Streamlit no fim da sidebar,
            para o rodapé (logo + versão) ficar mais próximo do fim real. */
            padding-bottom: 24px !important;
        }
        [data-testid="stSidebarUserContent"] > div {
            height: 100%;
        }
        [data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] {
            display: flex;
            flex-direction: column;
            height: 100%;
        }
        [data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"]
            > [data-testid="stElementContainer"]:has(.espacador-rodape) {
            flex-grow: 1;
        }
        /* Alinha o topo do menu com a linha do stepper nas páginas do
        fluxo (que começa ~20px mais abaixo do que o menu por padrão). */
        [data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"]
            > [data-testid="stElementContainer"]:first-child {
            margin-top: 14px;
        }
        /* Centraliza a logo da empresa no rodapé: st.image é envolvido pelo
        wrapper do recurso de tela cheia (stFullScreenFrame), que ocupa a
        largura toda da sidebar — o stImage (110px) fica alinhado à
        esquerda dentro dele. Centralizar precisa ser DENTRO desse wrapper. */
        [data-testid="stSidebarUserContent"] [data-testid="stFullScreenFrame"] {
            display: flex;
            justify-content: center;
        }
        </style>
        <div class="espacador-rodape"></div>
        """,
        unsafe_allow_html=True,
    )

    st.divider()
    # Largura fixa (~80% do que "stretch" preenchia antes) — em "stretch" a
    # imagem encostava nas bordas da sidebar e cortava um pouco o canto
    # inferior esquerdo. Centralizada via CSS acima (regra stImage).
    st.image(LOGO_EMPRESA, width=110)
    st.markdown(
        "<div style='text-align: center; color: grey; font-size: 0.85rem; margin-top: -0.75rem;'>"
        "v1.0 (2026) · by CS</div>",
        unsafe_allow_html=True,
    )

pg.run()
