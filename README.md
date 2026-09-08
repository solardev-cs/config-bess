## ⚡ Config BESS: Dimensionador de Sistemas Híbridos Off-Grid (Diesel + FV + BESS)

O **Config BESS** é uma ferramenta técnica desenvolvida para engenheiros e consultores de energia solar que precisam dimensionar, simular e avaliar a viabilidade econômica de sistemas híbridos off-grid — Gerador Diesel + Usina Fotovoltaica + BESS (banco de baterias) —, com foco inicial no agronegócio irrigante.

Nasceu como um substituto em Python de um dimensionador feito em planilha Excel, e evoluiu para um motor de simulação horária completo (8760h/ano), capaz de reproduzir — e em alguns pontos superar — o nível de detalhe técnico de ferramentas de referência do mercado, como o **HOMER Pro**, com um método de otimização próprio e uma modelagem pensada para as particularidades do agro brasileiro (perfil de carga a partir de necessidade hídrica por cultura/região, análise por hectare irrigado, catálogos reais de equipamentos).

O objetivo final é um SaaS, com o motor de cálculo (`engine/`) desacoplado da interface e reutilizável para múltiplas aplicações de BESS além do off-grid.

### 🎯 Config BESS x HOMER Pro

O app cobre o mesmo núcleo técnico que faz do HOMER Pro o padrão da indústria para dimensionamento off-grid — simulação horária de 8760h com física completa de carga/descarga do BESS (limite de potência **e** de energia, eficiência round-trip), despacho do gerador respeitando piso de carga mínima, KPIs de confiabilidade (LOLP, energia não suprida) e otimização automática do dimensionamento — mas com diferenciais pensados para o mercado agro brasileiro:

- **Perfil de carga derivado da necessidade hídrica real da cultura** (mm/mês por estado/cultura, com lógica de sucessão de culturas), em vez de um perfil de carga genérico importado manualmente.
- **Dois modelos físicos de acoplamento do BESS** — CA (BESS com PCS próprio, a solar cobre a carga direto e só a sobra carrega a bateria) e **CC** (BESS e inversor solar no mesmo equipamento, comum em unidades "tudo-em-um" off-grid, onde toda a energia solar carrega o BESS antes de chegar à carga) — cada um com sua própria estratégia de despacho, escolhida automaticamente pelo modelo de catálogo selecionado.
- **Relatório de viabilidade com economia por hectare irrigado** — a métrica que realmente importa para o produtor rural, além de VPL/TIR/LCOE.
- **Catálogos de equipamentos reais** (gerador, inversor, BESS) cadastráveis pelo usuário, com todas as potências derivadas automaticamente a partir dos dados de placa do fabricante — o dimensionamento sempre reflete equipamentos comerciais reais, não uma potência arbitrária contínua.

### 🧮 Método de Otimização

O dimensionamento ótimo de FV e BESS é resolvido via `scipy.optimize`, sem depender de nenhum Solver externo:

- **Acoplamento CA**: busca sequencial em 1 variável por vez (`minimize_scalar`, método `bounded`) — 1º dimensiona a potência do inversor FV, 2º (com o FV já definido) dimensiona a capacidade do BESS. Reproduz o fluxo de trabalho do Solver do Excel original.
- **Acoplamento CC**: como toda a energia solar precisa passar pelo BESS antes de chegar à carga, FV e BESS deixam de ser independentes — a busca sequencial ficaria presa num ótimo degenerado. Nesse caso, os dois são otimizados **simultaneamente** (busca 2D, Nelder-Mead), com o resultado da busca sequencial usado como estimativa inicial para acelerar a convergência.
- **Métrica de otimização**: **VPL** (maximizado diretamente) ou **LCOE** (minimizado via um critério equivalente e não degenerado — a razão clássica do LCOE é invariante de escala numa larga faixa de dimensionamento, então o critério de busca real maximiza o benefício econômico total não descontado, matematicamente equivalente a minimizar o LCOE sem o problema de convergir para um ponto arbitrário). TIR foi removida de propósito do dimensionamento pelo mesmo motivo de invariância de escala.
- Cada avaliação roda uma simulação horária completa de 8760h + o fluxo de caixa financeiro; a busca típica converge em segundos, sem paralelismo.

### 💡 Funcionalidades

O aplicativo cobre o fluxo completo de um estudo de viabilidade, em 5 etapas sequenciais mais uma página de parâmetros de referência:

1.  **Identificação do Projeto e Localização**: dados do cliente/projeto e seleção da localização no mapa (lat/lon), usada para buscar o recurso solar real do local.
2.  **Perfil de Carga de Irrigação**: geração automática do perfil horário de 1 ano a partir da necessidade hídrica mensal por cultura/estado, com lógica de sucessão de culturas (ex.: Soja + Trigo, usando o maior valor mensal entre as duas), janela de operação diária configurável e alternância entre dois grupos de carga (pivôs em dias pares/ímpares) para reduzir a potência instalada necessária.
3.  **Simulação Técnica**: dimensionamento (manual ou via otimização automática) do gerador diesel, usina FV e BESS a partir de catálogos de equipamentos reais; simulação horária completa de 8760h com KPIs de fração solar/renovável, energia por fonte, LOLP e curtailment, e gráficos do fluxo de energia entre as fontes.
4.  **Análise Financeira**: fluxo de caixa completo (CAPEX, O&M, economia de diesel, degradação de FV e BESS/SOH ao longo do horizonte), com suporte a financiamento (SAC/PRICE) e cálculo de VPL, TIR, LCOE e Payback.
5.  **Relatório de Viabilidade**: consolida todas as etapas anteriores num relatório único, com métricas de economia por hectare irrigado, e permite exportar tudo em PDF pronto para apresentar ao cliente.
6.  **Configurações**: parâmetros de referência (custos, TMA, degradação) e catálogos de gerador/inversor/BESS cadastrados uma vez e reaproveitados em todas as simulações.

### 🛠️ Tecnologias e Bibliotecas

| **Ferramenta** | **Objetivo** |
| :--- | :--- |
| Streamlit | Interface web interativa (multi-página, via `st.navigation`). |
| SciPy | Otimização do dimensionamento (`scipy.optimize`). |
| Pandas / NumPy | Processamento de séries temporais horárias (8760h) e cálculo vetorizado. |
| Requests | Consulta ao recurso solar real via API NSRDB/NREL. |
| Folium / streamlit-folium | Mapa interativo para seleção da localização do projeto. |
| fpdf2 / Matplotlib | Geração do Relatório de Viabilidade em PDF, com gráficos. |
| Pytest | Suíte de testes (regressão contra a planilha original + testes unitários do motor). |

### ℹ️ Como Executar Localmente

Siga os passos abaixo para rodar o aplicativo na sua máquina:

1.  Clone o repositório:
    ```bash
    git clone https://github.com/solardev-cs/config-bess.git
    cd config-bess
    ```

2.  Crie e ative um ambiente virtual (recomendado):
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # No Windows, use: .venv\Scripts\activate
    ```

3.  Instale as dependências:
    ```bash
    pip install -r requirements.txt
    ```

4.  Configure a chave de API do recurso solar (NSRDB/NREL), necessária para simular:
    ```bash
    cp .streamlit/secrets.toml.example .streamlit/secrets.toml
    # edite .streamlit/secrets.toml com sua api_key e email da NSRDB/NREL
    ```

5.  Inicie o aplicativo Streamlit:
    ```bash
    streamlit run app.py
    ```

> **Nota**: a suíte de testes (`pytest`) roda 100% offline (a chamada à API é mockada) — não é necessária uma chave de API real para rodar os testes, só para usar o app de verdade.
