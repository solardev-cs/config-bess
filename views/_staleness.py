"""Detecção de resultados desatualizados.

As páginas de Simulação Técnica e Análise Financeira só recalculam quando o
usuário clica em "Simular"/"Calcular" — se ele mudar um input depois disso
sem clicar de novo, o resultado exibido passa a não corresponder mais à
configuração atual, sem nenhum aviso. Este módulo tira uma "foto" (snapshot)
dos inputs relevantes no momento do clique e permite comparar com o estado
atual em qualquer rerun futuro — inclusive a partir de outra página, já que
``st.session_state`` é compartilhado por todas (usado no Relatório para
avisar que a simulação ou a análise financeira mostradas ali ficaram
desatualizadas em relação às respectivas páginas de origem).

Pegadinha do Streamlit que motivou o design abaixo: o valor de um widget
associado a ``key=`` só existe em ``st.session_state`` enquanto a página que
declara aquele widget estiver rodando — assim que o usuário navega para
outra página, o Streamlit descarta essas chaves. Ou seja, recalcular
``snapshot_simulacao()``/``snapshot_financeiro()`` a partir do Relatório
sempre lê ``None`` para tudo (widgets de outra página) e o aviso dispara
sempre, mesmo sem nada ter mudado. Por isso cada página "dona" dos widgets
publica sua própria foto atual em uma chave comum (não ligada a widget,
então sobrevive à navegação) a cada rerun, via ``publicar_snapshot_atual()``
— e é essa cópia publicada que as outras páginas comparam, nunca um recálculo
ao vivo feito de fora da página de origem.
"""
import streamlit as st

from views._persist import valor_persistido


def snapshot_simulacao(carga_kw, mapa_lat, mapa_lon) -> dict:
    """Inputs que determinam o resultado da Simulação Técnica.

    Só produz valores completos quando chamada durante a própria execução de
    ``views/simulacao_tecnica.py`` (widgets ainda instanciados nesta rodada).
    ``degradacao_bess_am_ano`` é a exceção: é um widget de Configurações, não
    desta página, então é lido via ``valor_persistido`` (sobrevive à
    navegação) em vez de ``session_state`` direto — ver ``views/_persist.py``.
    """
    s = st.session_state
    return {
        "pot_inv_kw": s.get("fv_pot_inv"),
        "ilr": s.get("fv_ilr"),
        "modelo_inversor": s.get("fv_modelo"),
        "capacidade_kwh": s.get("bess_capacidade"),
        "dod": s.get("bess_dod"),
        "modelo_bess": s.get("bess_modelo"),
        "degradacao_bess_am_ano": valor_persistido("cfg_degradacao_bess_soh", None),
        "nr_maquinas": s.get("ger_nr"),
        "nr_min_maquinas": s.get("ger_nr_min"),
        "modelo_gerador": s.get("ger_modelo"),
        # Listas completas dos catálogos (não só o modelo escolhido): editar
        # em Configurações os dados de QUALQUER modelo já usado numa
        # simulação anterior também deve disparar o aviso de desatualização.
        "catalogo_geradores": valor_persistido("cfg_geradores_catalogo", None),
        "catalogo_inversores": valor_persistido("cfg_inversores_catalogo", None),
        "catalogo_bess": valor_persistido("cfg_bess_catalogo", None),
        "modo": s.get("ger_modo"),
        "carga_kw_hash": carga_kw.tobytes() if carga_kw is not None else None,
        "mapa_lat": mapa_lat,
        "mapa_lon": mapa_lon,
    }


def snapshot_financeiro(resultado_tecnico) -> dict:
    """Inputs que determinam o resultado da Análise Financeira.

    Só produz valores completos quando chamada durante a própria execução de
    ``views/analise_financeira.py`` (widgets ainda instanciados nesta rodada).
    Inclui ``id(resultado_tecnico)`` para também detectar o caso em que a
    simulação técnica foi refeita (novo objeto de resultado) sem que a
    análise financeira tenha sido recalculada em cima dela.
    """
    s = st.session_state
    return {
        "custo_fv_rs_kwp": s.get("cfg_custo_fv"),
        "custo_bateria_rs_kwh": s.get("cfg_custo_bess"),
        "preco_diesel_rs_litro": s.get("cfg_preco_diesel"),
        "tma_am": s.get("cfg_tma"),
        "economia_por_saca_rs": s.get("cfg_valor_saca"),
        "horizonte_anos": s.get("cfg_horizonte_anos"),
        "degradacao_fv_am_ano": s.get("cfg_degradacao_fv"),
        "om_pct_am": s.get("fin_om"),
        "inflacao_diesel_am": s.get("fin_diesel_inflacao"),
        "tipo_pagamento": s.get("fin_tipo_pagto"),
        "pct_financiado": s.get("fin_pct_financ"),
        "tipo_financiamento": s.get("fin_tipo_financ"),
        "prazo_anos": s.get("fin_prazo"),
        "carencia_anos": s.get("fin_carencia"),
        "taxa_juros_am": s.get("fin_taxa_juros"),
        "simulacao_id": id(resultado_tecnico) if resultado_tecnico is not None else None,
    }


def publicar_snapshot_atual(chave: str, snapshot: dict) -> None:
    """Salva ``snapshot`` numa chave comum de ``session_state`` (não ligada a
    nenhum widget), para outras páginas conseguirem comparar mesmo depois que
    os widgets de origem somem de ``session_state`` ao navegar para outra
    página. Chamar a cada rerun da página dona dos widgets — não só quando o
    botão de calcular é clicado — para a cópia publicada nunca ficar velha.
    """
    st.session_state[chave] = snapshot


def aviso_se_desatualizado(chave_snapshot: str, snapshot_atual: dict | None, mensagem: str) -> bool:
    """Mostra um `st.warning` se o snapshot salvo em `chave_snapshot` divergir
    de `snapshot_atual`. Retorna True se o aviso foi exibido (desatualizado).

    `snapshot_atual` deve ser lido de uma chave publicada por
    `publicar_snapshot_atual()` (ou, se chamado a partir da própria página
    dona dos widgets, pode ser o resultado ao vivo de `snapshot_simulacao()`/
    `snapshot_financeiro()`). Se `snapshot_atual` for `None` — página de
    origem ainda não publicou nada nesta sessão —, não há como saber se está
    desatualizado, então nenhum aviso é mostrado.
    """
    snapshot_salvo = st.session_state.get(chave_snapshot)
    if snapshot_salvo is not None and snapshot_atual is not None and snapshot_salvo != snapshot_atual:
        st.warning(mensagem, icon="⚠️")
        return True
    return False
