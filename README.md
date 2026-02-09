## ⚡ Gerador de Perfil de Carga de Irrigação: Sistemas Híbridos Off-Grid

O **Gerador de Perfil de Carga** é uma ferramenta técnica desenvolvida para engenheiros e consultores de energia solar que precisam dimensionar sistemas híbridos off-grid.

O aplicativo gera um perfil de carga padrão para 1 ano de consumo, baseado na necessidade hídrica específica de uma região e cultura. O perfil pode ser utilizado em ferramentas de simulação e softwares como Homer Energy, garantindo maior precisão no dimensionamento e estudo de retorno econômico.

### 💡 Funcionalidades

O aplicativo permite:

1.  **Gestão de Banco de Dados Hídrico**: Interface interativa para gerenciar a fonte de dados (csv) de necessidades hídricas por estado e cultura.
2.  **Lógica de Sucessão de Culturas**: Possibilidade de combinar duas culturas no mesmo ciclo anual (ex: Soja + Milho Safrinha), com seleção automática da maior demanda mensal.
3.  **Dimensionamento de Janela Operacional**: Ajuste da janela de irrigação diária (h) para otimizar o uso da irradiação solar e reduzir o consumo de diesel.
4.  **Alternância de Carga**: Opção para simular dois grupos de carga (pivots, por ex.) operando em dias alternados (Ímpar/Par), para redução da potência do sistema.
5.  **Exportação do Perfil de Carga**: Geração automática de arquivo csv formatado para importação direta como perfil de carga sintético em softwares como Homer Energy.

### 🛠️ Tecnologias e Bibliotecas

Este projeto utiliza Python para engenharia de dados e interface:

| **Ferramenta** | **Objetivo** |
| :--- | :--- |
| Streamlit | Criação da interface web interativa. |
| Pandas | Processamento de séries temporais e arquivos csv. |
| Numpy | Operações vetoriais para balanço hídrico. |

### ℹ️ Como Executar Localmente

Siga os passos abaixo para rodar o aplicativo na sua máquina:

1.  Clone o repositório:
    ```bash
    git clone [https://github.com/solardev-cs/config-off.git](https://github.com/solardev-cs/config-off.git)
    cd config-off
    ```

2.  Crie e ative um ambiente virtual (recomendado):
    ```bash
    python -m venv venv
    source venv/bin/activate  # No Windows, use: .\venv\Scripts\activate
    ```

3.  Instale as dependências:
    ```bash
    pip install -r requirements.txt
    ```

4.  Inicie o aplicativo Streamlit:
    ```bash
    streamlit run app.py
    ```

### 📁 Estrutura de Dados

O app depende do arquivo data/ref_hidrica.csv para funcionar. Este arquivo contém os milímetros mensais necessários para cada cultura. O arquivo pode ser editado pelo modal "Gerenciar Tabela Hídrica" dentro da interface do usuário.

> **Dica de Uso**: Ao configurar a "Lâmina de Projeto", utilize o valor real de vazão do pivot (mm/21h) para que o cálculo de horas de bombeamento reflita a realidade do pivot projetado.