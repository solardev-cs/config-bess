# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Config BESS — Dimensionador de Sistemas Híbridos (Diesel + FV + BESS)

## Comandos

Este projeto usa a venv em `.venv/` (não `venv/`, apesar do que o README sugere) — sempre
use o Python dela, nunca o do sistema.

```bash
# Rodar o app Streamlit (app.py é só o router st.navigation; páginas em views/)
.venv/Scripts/python.exe -m streamlit run app.py     # Windows
.venv/bin/python -m streamlit run app.py             # macOS/Linux

# Instalar dependências
.venv/Scripts/pip.exe install -r requirements.txt

# Rodar a suíte completa de testes (baseline atual: 114/114 passando)
.venv/Scripts/python.exe -m pytest

# Rodar um arquivo de teste específico
.venv/Scripts/python.exe -m pytest tests/test_regression_excel.py

# Rodar um único teste
.venv/Scripts/python.exe -m pytest tests/test_optimizer.py::test_nome_do_teste -v
```

Não há linter configurado no projeto (sem `ruff.toml`, `.flake8` ou seção `[tool.ruff]`/
`[tool.black]` em `pyproject.toml`).

`tests/test_nsrdb_provider.py` mocka `requests` — a suíte inteira roda offline, sem
precisar de chave de API real (`.streamlit/secrets.toml`, com `[nlr_api]`, só é
necessária para rodar o app de verdade contra a API NSRDB/NLR).

## O que é o projeto
Web app (Streamlit, migrando para arquitetura desacoplada) que recalcula em Python
um dimensionador originalmente feito em Excel (`history/Config_OFF.xlsx`).
Modela sistemas híbridos off-grid/zero-grid: gerador diesel + usina solar + BESS,
com foco inicial no agronegócio irrigante (perfil de carga a partir de necessidade
hídrica mm/mês por cultura/região). Objetivo final: SaaS, com o motor de cálculo
reutilizável para múltiplas aplicações de BESS (não só off-grid).

## Arquitetura — regra de ouro
`engine/` é Python puro, SEM import de streamlit. Deve poder ser importado por uma
futura API REST sem reescrita. Toda a UI (`views/*.py`) é consumidora fina do engine.

```
app.py                   # router: define st.navigation([st.Page(...), ...]) e chama pg.run()
                          # (NÃO usa mais a convenção "pages/" do Streamlit — títulos de
                          # navegação vêm do parâmetro title= de st.Page, não do nome do
                          # arquivo, o que permite acentuação correta na sidebar)
views/                    # uma página por arquivo, cada uma consumidora fina do engine
├── home.py               # 1. Identificação do projeto + mapa de localização (lat/lon)
├── perfil_carga.py       # 2. Perfil de Carga: cargas de irrigação -> 8760h
├── simulacao_tecnica.py  # 3. Simulação Técnica: FV+BESS+Diesel, otimização, KPIs
├── analise_financeira.py # 4. Análise Financeira: VPL/TIR/LCOE/Payback
├── relatorio_viabilidade.py # 5. Relatório de Viabilidade: consolida tudo + exporta PDF
├── configuracoes.py      # Parâmetros de referência (cfg_*) fora do fluxo principal —
│                          # ver seção "Navegação" abaixo
├── _nav.py               # NÃO é uma página (não vai em st.Page). Fonte única de
│                          # path/título/ícone das 5 páginas do fluxo, usada por
│                          # app.py e por stepper() (indicador de progresso +
│                          # navegação rápida que cada página do fluxo renderiza
│                          # como primeiro elemento, antes do título)
├── _staleness.py          # NÃO é uma página. snapshot_simulacao()/snapshot_financeiro()
│                           # + aviso_se_desatualizado() — ver "Fluxo entre páginas" abaixo
├── _dados_hidricos.py      # NÃO é uma página. carregar_dados() do CSV de referência
│                            # hídrica (data/ref_hidrica.csv) — usado por Perfil de Carga
│                            # (calcula o perfil) e por Configurações (exibe a tabela)
├── _persist.py             # NÃO é uma página. persistir()/valor_persistido()/indice_persistido()
│                            # — ver "Persistência entre páginas" abaixo
└── _gerador_catalogo.py    # NÃO é uma página. catalogo_para_modelos(): converte as linhas do
                             # st.data_editor de Configurações (dict com colunas em português)
                             # em engine.generator_catalog.ModeloGerador — usado por Simulação
                             # Técnica para popular o selectbox "Modelo do Gerador"

engine/
├── models.py           # dataclasses de input (Solar/Generator/BatteryConfig etc.)
├── generator_catalog.py # ModeloGerador (dados de catálogo do fabricante: kVA nominal,
│                         # consumo L/h, FP, piso de carga mínima) + fórmulas de derivação
│                         # (nominal/prime/contínua em kW e kVA, eficiência kWh/L) +
│                         # generator_config_from_modelo() — ver "Decisões de arquitetura"
├── load_profile.py     # perfil de carga a partir de mm/mês + potência
├── formatting.py        # formatar_numero()/formatar_brl() — única fonte de formatação
│                         # pt-BR (milhar '.', decimal ','), usada por todo `views/*.py`
├── solar/
│   ├── base.py          # interface SolarProfileProvider
│   ├── static_tmy.py    # provider atual: CSVs TMY fixos (RS/MT/BA)
│   └── nsrdb_api.py     # provider dinâmico (NSRDB/NREL) — ver "Fonte solar" abaixo
├── battery.py           # charge()/discharge() com limite de kW E kWh + eficiência RT
├── generator.py         # clamp de potência máxima + piso de carga mínima (ON/OFF vs Sempre ON)
├── dispatch/
│   ├── base.py           # interface DispatchStrategy (contrato comum)
│   └── load_following.py # única estratégia implementada hoje
├── simulator.py         # loop horário 8760h, stateful (SOC), KPIs de confiabilidade
├── financial.py         # VPL/TIR/LCOE/Payback, amortização SAC/PRICE
├── costs.py             # CAPEX/OPEX FV+BESS(kWh e kW)+diesel, custo de geração diesel
│                         # (R$/kWh) a partir da eficiência do gerador (kWh/litro)
├── report_pdf.py        # geração do PDF do Relatório de Viabilidade (fpdf2)
└── optimizer.py         # substitui o Solver do Excel via scipy.optimize

tests/                   # pytest, venv já configurado no projeto
history/Config_OFF.xlsx  # planilha original — fonte de verdade para regressão
```

Fluxo entre páginas (via `st.session_state`): Home define `mapa_lat`/`mapa_lon` e
`home_*` (dados do cliente) -> Perfil de Carga define `carga_kw`/`carga_grupos` ->
Simulação Técnica consome carga+localização e define `ultima_simulacao` -> Análise
Financeira consome a simulação e define `ultima_analise_financeira` -> Relatório de
Viabilidade só lê o que já está em `session_state`, sem recalcular nada. Em paralelo,
`configuracoes.py` define os parâmetros `cfg_*` (custo FV/BESS, preço diesel, TMA,
horizonte, valor da saca, degradação FV/BESS) lidos por Simulação Técnica (Otimização)
e Análise Financeira — página fora do fluxo sequencial, não bloqueia nem é bloqueada
pelas outras.

Simulação Técnica e Análise Financeira salvam, junto do resultado, um snapshot dos
inputs usados (`ultima_simulacao_config`/`ultima_analise_financeira_config`, via
`views/_staleness.py`). Em qualquer rerun — inclusive ao navegar para outra página,
já que `session_state` é global — o snapshot salvo é comparado com um novo snapshot
lido dos mesmos widgets; se divergir, aparece um aviso de que o resultado exibido
está desatualizado. O Relatório de Viabilidade usa a mesma comparação (somente
leitura, sem botão de cálculo próprio) para avisar se a simulação técnica ou a
análise financeira que ele está exibindo ficaram desatualizadas em relação às
páginas de origem.

Persistência entre páginas (`views/_persist.py`): o Streamlit descarta
`st.session_state[key]` de um widget assim que a página que o declarou deixa
de ser a página ativa (comportamento do `st.navigation`/`st.Page` usado em
`app.py` — ver comentário detalhado em `views/_staleness.py`). Por isso,
passar `value=st.session_state.get(key, default)` não é suficiente: quando o
usuário volta à página, a chave já não existe mais e o widget volta ao
default hardcoded, perdendo o valor digitado. `persistir()`/`valor_persistido()`
guardam uma cópia em uma chave paralela (`_persist_<key>`, nunca ligada a
nenhum widget, portanto nunca descartada) — todo widget cujo valor precisa
sobreviver à navegação segue o padrão
`x = persistir("minha_key", st.algum_widget(..., value=valor_persistido("minha_key", default), key="minha_key"))`.
`indice_persistido()` faz o mesmo para o `index=` de um `st.selectbox`.

Estratégias futuras (`time_shifting.py`, `peak_shaving.py`, `backup.py`) devem
reaproveitar `battery.py`/`generator.py`/`solar/` sem duplicar a física do sistema.

## Bugs confirmados na planilha original — status da correção no engine
| # | Bug | Status no engine |
|---|---|---|
| 1a | BESS sem limite de potência (só energia) | ✅ Corrigido — `battery.py` limita por kW e kWh |
| 1c | Sem eficiência round-trip | ✅ Corrigido em `battery.py` |
| 1d | Sem degradação do BESS em 25 anos | ✅ Corrigido — `BatteryConfig.degradacao_capacidade_am_ano`, aplicada em `financial.py` |
| 1e | Perfil de carga 6 = total do Perfil 5 | N/A — app novo não herda essa estrutura de perfis |
| 1f | `/0` latente na amortização PRICE | ✅ Corrigido (motor novo, sem essa fórmula) |
| 1g | Gerador sem clamp de potência máxima horária | ✅ Corrigido em `generator.py` |
| 1h | Potência BESS hardcoded no relatório | N/A — relatório novo calcula tudo via engine |
| 2.2 | Curtailment do BESS não vira "dump load" visível | Verificar se `simulator.py` já reporta |
| 2.3 | Sem KPI de loss-of-load no modo off-grid | ✅ `simulator.py` reporta KPIs de confiabilidade |

## Decisões de arquitetura já tomadas (não reabrir sem motivo)
- **CAPEX do BESS só em R$/kWh (sem custo separado de PCS em R$/kW)**: decisão
  deliberada, não pendência. No mercado, o custo por kWh de BESS de curta duração
  (C-rate típico 0,25–1C) já reflete o custo total do pack, incluindo o PCS/inversor
  da bateria — ver docstrings de `EconomicConfig`/`calcular_capex` em
  `engine/models.py`/`engine/costs.py`.
- **BESS potência x capacidade**: C-rate é INPUT do usuário (ex. 0,5C). O otimizador
  ajusta só a capacidade (kWh); potência (kW) é derivada: `potencia_kw = capacidade_kwh * c_rate`.
  Mantém compatibilidade com o fluxo sequencial de 1 variável do Solver original.
- **Catálogo de geradores (`engine/generator_catalog.py`)**: substitui os antigos inputs
  manuais de Potência Prime (kVA), Fator de Potência e Potência Contínua (kW) — soltos e
  sem vínculo com um gerador real — por um catálogo cadastrado em `views/configuracoes.py`
  (`st.data_editor`, persistido em `cfg_geradores_catalogo`) com apenas os 4 dados de
  placa/catálogo do fabricante: modelo, potência nominal (kVA), consumo de combustível a
  plena carga (L/h) e FP. Em Simulação Técnica, o usuário só escolhe o modelo por nome
  (`ModeloGerador`, via `views/_gerador_catalogo.py::catalogo_para_modelos()`); todas as
  demais potências e a eficiência de consumo (kWh/litro, usada por
  `costs.py::custo_geracao_diesel_rs_kwh` para o custo de geração a diesel em R$/kWh) são
  derivadas automaticamente por `generator_config_from_modelo()`:
  `pot_nominal_kw = pot_nominal_kva * fp`; `pot_prime_kva = 0,9 * pot_nominal_kva`;
  `pot_prime_kw = pot_prime_kva * fp`; `pot_continua_kw = 0,56 * pot_nominal_kva` (note:
  a partir do kVA nominal, não do kW nominal); `pot_continua_kva = pot_continua_kw / fp`;
  `eficiencia_kwh_por_litro = pot_continua_kw / consumo_l_h`. O piso de carga mínima
  ("Potência Mínima Permitida (%)") também passou a vir do catálogo por modelo, em vez de
  um slider manual em Simulação Técnica.
- **Fonte de dados solar**: schema real da planilha é **NSRDB/NREL** (PSM3/TMY), não
  PVGIS — confirmado pelo Power Query decodificado do Excel original. Provider
  dinâmico fica em `engine/solar/nsrdb_api.py`, atrás da interface `solar/base.py`.
- **Otimizador (`optimizer.py`)**: `scipy.optimize.minimize_scalar` (bounded), busca
  1D sequencial: 1º dimensiona FV (`otimizar_potencia_fv`), 2º dimensiona BESS
  (`otimizar_capacidade_bess`). Réplica do comportamento do Solver do Excel.
- **Métricas de otimização — só VPL e LCOE.** TIR foi **removida** de propósito.
  Motivo (não reabrir): quando CAPEX e energia evitada são proporcionais ao
  tamanho do sistema sem termo fixo, TIR e LCOE médios ficam matematicamente
  constantes (invariantes de escala) numa larga faixa — o otimizador escolhe um
  ponto arbitrário/ruído nesse platô. VPL não tem esse problema (cresce
  estritamente com o tamanho até a saturação/curtailment). Para LCOE, a correção
  aplicada foi trocar "minimizar LCOE médio" por "buscar o cruzamento entre
  custo marginal e preço do diesel evitado nivelado" (equivalente a dVPL/dx=0).
  TIR foi simplesmente descartada como critério de otimização (decisão do usuário).
- **Relatório de viabilidade** (`views/relatorio_viabilidade.py` +
  `engine/report_pdf.py`, biblioteca `fpdf2`): reaproveita 100% do que já está em
  `st.session_state` (`ultima_simulacao`, `ultima_analise_financeira`,
  `carga_kw`, `home_*`). Inclui bloco de **economia por hectare** (input "Área
  irrigada (ha)" por grupo de carga em `views/perfil_carga.py`) — pensado para a
  mentalidade do cliente do agro. PDF gerado via `fpdf2` (pure-Python), gráficos em
  matplotlib reaproveitados entre tela e PDF.
- **Navegação (`app.py`)**: usa `st.Page`/`st.navigation` (Streamlit ≥1.36) em vez da
  convenção de arquivo `pages/NN_Nome.py`. Motivo (não reabrir): nomes de arquivo Python
  não podem ter acentos, então o título exibido na sidebar ficava sem acentuação
  ("Simulacao_Tecnica"). Com `st.Page(path, title=..., icon=..., url_path=...)` o
  título vem de `title=` (acentos ok) e a URL de `url_path=` (ASCII, estável),
  desacoplados do nome do arquivo/função. O menu é montado manualmente com
  `st.navigation(..., position="hidden")` + `st.page_link()` por página (em vez do
  menu automático). Motivo: o menu automático não aceita um `st.divider()` inserido
  entre páginas — como "Configurações" precisa aparecer visualmente separada do fluxo
  principal (Home...Relatório), a única forma de ter um divisor real ali é desistir do
  menu automático e desenhar a lista de links à mão em `with st.sidebar:`.
- **Parâmetros de referência (`views/configuracoes.py`)**: custo FV/BESS, preço diesel,
  TMA, horizonte, valor da saca e degradação FV/BESS ficam centralizados aqui
  (`st.session_state["cfg_*"]`) em vez de repetidos em Simulação Técnica e Análise
  Financeira. Motivo (não reabrir): antes cada página tinha sua própria cópia desses
  inputs com o mesmo valor padrão, sem nada impedindo o usuário de otimizar com um
  custo e analisar a viabilidade com outro. `cfg_degradacao_bess_soh` alimenta
  `BatteryConfig.degradacao_capacidade_am_ano` (construído em
  `views/simulacao_tecnica.py`, tanto no "Cálculo Técnico" quanto na
  "Otimização") e é consumido por `engine/financial.py`, que degrada a
  parcela de energia evitada atribuída à bateria separadamente da degradação
  do FV (`cfg_degradacao_fv`) — ver docstring de `calcular_fluxo_de_caixa`.
  A Tabela de Referência Hídrica (consulta somente leitura do
  `data/ref_hidrica.csv`, via `views/_dados_hidricos.py`) também mora aqui — antes
  era um botão que abria um modal em `views/perfil_carga.py`, deslocado no meio dos
  inputs de operação; como é dado de referência estática (não um input da carga em
  si), faz mais sentido junto dos outros parâmetros de referência.
- **Stepper (`views/_nav.py::stepper()`)**: cada página do fluxo principal chama
  `stepper(seu_próprio_path)` como primeiro elemento renderizado — antes até do
  título da página. Motivo (não reabrir): "indicador de progresso entre etapas" e
  "atalho para voltar a uma etapa anterior sem depender da sidebar" nasceram como
  dois itens de melhoria separados, mas são o mesmo componente de UI — um só
  elemento evita duas barras de navegação na mesma página. Mostra as 5 etapas
  numeradas (`1. Home`, `2. Perfil de Carga`, ...), sem ícone; marca com `✓` as que
  já têm um marco salvo em `session_state` (`_MARCO_CONCLUSAO` em `_nav.py`); a
  etapa atual aparece em negrito (não clicável), as demais são `st.page_link`. Não
  inclui "Configurações" (não é uma etapa sequencial).
- **Formatação numérica (`engine/formatting.py`)**: `formatar_numero()`/`formatar_brl()`
  são a única forma de formatar números para exibição em `views/*.py` — não usar
  `f"{x:,.Nf}".replace(...)` ad hoc de novo. Motivo (não reabrir): o padrão antigo de
  `.replace(",", ".")` isolado (sem swap completo) corrompe o separador decimal
  sempre que o valor formatado tem casas decimais (ex.: `"1,234.5"` vira `"1.234.5"`
  em vez de `"1.234,5"`) — bug real, presente em `relatorio_viabilidade.py`
  ("Potência Total", "Diesel Evitado por Hectare"). Além disso, `analise_financeira.py`
  e `simulacao_tecnica.py` não aplicavam nenhuma formatação pt-BR (usavam o separador
  de milhar americano `,` cru).

## Testes
- Baseline verificada (2026-07-17): 114/114 testes passando — ver seção "Comandos" acima.
- `tests/test_regression_excel.py` compara saída do engine com valores conhecidos
  da planilha original (ex. células E8766, S8766) — não quebrar essa regressão.
- Ao mudar `optimizer.py` ou `financial.py`, sempre rodar a suíte completa antes
  de considerar a tarefa concluída.

## Convenções
- Nomes de variáveis/funções em português (`capacidade_kwh`, `otimizar_potencia_fv`),
  seguindo o padrão já estabelecido no repositório — manter consistência.
- Dataclasses para todo input estruturado (ver `engine/models.py`).
- Nenhuma lógica de negócio dentro de `views/*.py` — se uma página está calculando
  algo, isso é sinal de que deveria estar em `engine/`.
