# 🚀 Sistema de Gestão Comercial & BI (MIC Dashboard)

![Status](https://img.shields.io/badge/Status-Concluído-success)
![Python](https://img.shields.io/badge/Python-3.11-blue)
![Streamlit](https://img.shields.io/badge/Framework-Streamlit-red)

> **Painel de Inteligência Comercial desenvolvido para otimizar a gestão de metas, representantes e performance de vendas em tempo real.**

## 🖼️ Visão Geral

Este projeto é uma aplicação web completa desenvolvida em **Python** utilizando o framework **Streamlit**. O objetivo foi substituir planilhas descentralizadas por um sistema robusto, seguro e acessível via nuvem, permitindo que vendedores e gestores acompanhem suas metas e resultados de qualquer lugar.

O sistema conecta-se a uma base de dados no **Google Sheets** via API segura, garantindo persistência de dados e facilidade de manutenção.

---

## 🎯 Funcionalidades Principais

### 🔐 1. Gestão de Acesso e Segurança
- Sistema de **Login e Senha** com autenticação criptografada.
- **Níveis de Acesso:** Visão de Vendedor (Individual) e Visão de Supervisão (Gestão de Time).
- Conexão segura via **Google Service Account** (sem exposição de dados públicos).

### 📊 2. Business Intelligence (BI)
- **KPIs em Tempo Real:** Vendas Totais, Falta Vender, Meta Diária Dinâmica e Ticket Médio.
- **Indicadores de Tendência:** Setas visuais (🟢/🔴) que indicam se o ritmo atual de vendas é suficiente para bater a meta.
- **Curva ABC de Clientes:** Algoritmo que classifica automaticamente os clientes em A (80%), B (15%) e C (5%) do faturamento.

### 🤝 3. Gestão de Representantes (Supervisão)
- Interface para **Adicionar/Editar Representantes** e suas metas diretamente pelo app.
- **Dashboard de Supervisão:** Permite ao gestor selecionar múltiplos representantes e visualizar a performance consolidada do grupo.
- Gráficos comparativos de Top 10 Clientes do grupo supervisionado.

### 📥 4. Relatórios e Exportação
- Geração automática de relatórios em **CSV** formatados para Excel (BR).
- Botões de download inteligentes para Vendedores e Gestores baixarem apenas os dados pertinentes à sua visão.

### ⚙️ 5. Customização (UX/UI)
- **Layout Flexível:** O usuário pode reordenar os gráficos e seções do dashboard (drag-and-drop logic) conforme sua preferência.
- Tema responsivo e limpo, focado na experiência do usuário móvel e desktop.

---

## 🛠️ Tecnologias Utilizadas

* **Linguagem:** Python 3.11
* **Frontend/Backend:** Streamlit
* **Visualização de Dados:** Plotly Express (Gráficos Interativos)
* **Manipulação de Dados:** Pandas & Numpy
* **Banco de Dados:** Google Sheets API (via `st-gsheets-connection`)
* **Deploy:** Streamlit Community Cloud

---

## 🚀 Como Rodar o Projeto Localmente

1.  **Clone o repositório:**
    ```bash
    git clone [https://github.com/SEU_USUARIO/dashboard-vendas-mic.git](https://github.com/SEU_USUARIO/dashboard-vendas-mic.git)
    cd dashboard-vendas-mic
    ```

2.  **Crie um ambiente virtual e instale as dependências:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # No Windows: venv\Scripts\activate
    pip install -r requirements.txt
    ```

3.  **Configure as Credenciais:**
    * Crie um arquivo `.streamlit/secrets.toml`.
    * Adicione suas credenciais do Google Cloud (Service Account) neste arquivo.
    * *Nota: Por segurança, as chaves não estão incluídas no repositório público.*

4.  **Execute a aplicação:**
    ```bash
    streamlit run app.py
    ```

---

## 📈 Impacto do Projeto

A implementação deste sistema permitiu:
* Redução de **100%** no uso de planilhas locais para acompanhamento de meta.
* Acesso **mobile** para vendedores em campo.
* Maior transparência e **gamificação** do processo de vendas (efeito visual de meta batida 🎉).

---

Developed by **[Seu Nome / Luan Clemente]** 💻
