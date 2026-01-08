import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
import json
from datetime import datetime, date, timedelta
import calendar
import numpy as np

# ==============================================================================
# ⚙️ CONFIGURAÇÕES INICIAIS
# ==============================================================================
st.set_page_config(page_title="Sistema Comercial MIC", layout="wide", page_icon="📊")

ARQUIVO_DADOS = "lista.csv" 
ARQUIVO_CONFIG = "usuarios.json"
ARQUIVO_LOGO = "logo.png"

# --- FUNÇÕES AUXILIARES ---
def carregar_config():
    dados_padrao = {
        "meta_geral": 100000,
        "usuarios": {
            "luan": {"senha": "123", "meta": 20000, "nome": "Luan Clemente"},
            "vendedor": {"senha": "123", "meta": 15000, "nome": "Vendedor Padrão"}
        }
    }
    if not os.path.exists(ARQUIVO_CONFIG) or os.stat(ARQUIVO_CONFIG).st_size == 0:
        with open(ARQUIVO_CONFIG, "w") as f: json.dump(dados_padrao, f)
        return dados_padrao
    try:
        with open(ARQUIVO_CONFIG, "r") as f: return json.load(f)
    except: return dados_padrao

def salvar_config(dados):
    with open(ARQUIVO_CONFIG, "w") as f: json.dump(dados, f)

config = carregar_config()

# --- CÁLCULO DE DIAS ÚTEIS (CORRIGIDO PARA O FINAL DO MÊS) ---
def calcular_dias_uteis_restantes_mes():
    hoje = date.today()
    
    # Descobre o último dia do mês ATUAL
    ultimo_dia_numero = calendar.monthrange(hoje.year, hoje.month)[1]
    data_fim_mes = date(hoje.year, hoje.month, ultimo_dia_numero)
    
    # Se já passou do mês (ex: bug de virada de ano), retorna 0
    if hoje > data_fim_mes:
        return 0
    
    # np.busday_count conta dias úteis (Seg-Sex)
    # Adicionamos +1 no fim porque o numpy exclui a data final da contagem
    dias = np.busday_count(hoje, data_fim_mes + timedelta(days=1))
    return max(0, int(dias))

# --- BARRA DE PROGRESSO CUSTOMIZADA (LOADING BAR) ---
def barra_progresso_linda(atual, meta, titulo="Progresso"):
    porcentagem = (atual / meta * 100) if meta > 0 else 0
    porcentagem_visual = min(porcentagem, 100) # Trava visualmente em 100%
    
    # Gradiente Vermelho -> Amarelo -> Verde
    cor_barra = "linear-gradient(90deg, #ff4b4b 0%, #ffca28 50%, #21c354 100%)"
    
    html = f"""
    <div style="margin-bottom: 20px; font-family: sans-serif;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 5px; align-items: flex-end;">
            <span style="font-weight: bold; font-size: 1.1rem; color: #444;">{titulo}</span>
            <span style="font-weight: bold; font-size: 1.4rem; color: #333;">{porcentagem:.1f}%</span>
        </div>
        <div style="width: 100%; background-color: #e6e6e6; border-radius: 20px; height: 25px; box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);">
            <div style="width: {porcentagem_visual}%; 
                        background: {cor_barra}; 
                        height: 100%; 
                        border-radius: 20px; 
                        transition: width 1s ease-in-out;
                        box-shadow: 2px 0 5px rgba(0,0,0,0.2);">
            </div>
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 0.85rem; color: #666; margin-top: 5px;">
            <span>Realizado: R$ {atual:,.2f}</span>
            <span>Meta: R$ {meta:,.2f}</span>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

# ==============================================================================
# 📥 CARGA DE DADOS
# ==============================================================================
def carregar_dados():
    if not os.path.exists(ARQUIVO_DADOS): return None, None
    try:
        try: df = pd.read_csv(ARQUIVO_DADOS, sep=";", encoding="utf-8", on_bad_lines='skip', dtype={'NF': str})
        except: df = pd.read_csv(ARQUIVO_DADOS, sep=";", encoding="latin1", on_bad_lines='skip', dtype={'NF': str})

        df.columns = [c.strip() for c in df.columns]
        cols = df.columns
        col_valor = next((c for c in cols if 'Valor' in c or 'Liq' in c), None)
        col_data = next((c for c in cols if 'Gera' in c or 'Data' in c or 'Emis' in c), None)
        col_nf = next((c for c in cols if 'NF' in c or 'Nota' in c), None)
        col_vend = next((c for c in cols if 'Vendedor' in c or 'Vend' in c), None)

        if not col_valor or not col_data: return None, None

        if df[col_valor].dtype == 'O':
            df[col_valor] = df[col_valor].astype(str).str.replace('R$', '').str.strip().str.replace('.', '').str.replace(',', '.')
        df['valor_final'] = pd.to_numeric(df[col_valor], errors='coerce').fillna(0)
        df['data_final'] = pd.to_datetime(df[col_data], dayfirst=True, errors='coerce')
        
        if col_nf:
            df['status_ped'] = df[col_nf].apply(lambda x: 'Faturado' if pd.notnull(x) and str(x).strip() != '' else 'A Faturar')
        else:
            df['status_ped'] = 'Desconhecido'

        return df, col_vend
    except: return None, None

# ==============================================================================
# 🔐 BARRA LATERAL
# ==============================================================================
if os.path.exists(ARQUIVO_LOGO):
    st.sidebar.image(ARQUIVO_LOGO, use_container_width=True)
else:
    st.sidebar.title("MIC")

st.sidebar.markdown("---")
st.sidebar.subheader("🔐 Acesso Restrito")

if 'usuario_logado' not in st.session_state: st.session_state['usuario_logado'] = None

if st.session_state['usuario_logado'] is None:
    tab_login, tab_cadastro = st.sidebar.tabs(["Entrar", "Cadastrar"])
    with tab_login:
        u_in = st.text_input("Usuário")
        p_in = st.text_input("Senha", type="password")
        if st.button("Entrar"):
            if u_in in config['usuarios'] and config['usuarios'][u_in]['senha'] == p_in:
                st.session_state['usuario_logado'] = u_in
                st.rerun()
            else: st.error("Erro no login")
    with tab_cadastro:
        new_user = st.text_input("Novo Usuário (Login)")
        new_pass = st.text_input("Nova Senha", type="password")
        new_name = st.text_input("Nome Completo")
        new_meta = st.number_input("Meta Inicial", value=10000.0)
        if st.button("Criar Vendedor"):
            if new_user and new_pass:
                if new_user not in config['usuarios']:
                    config['usuarios'][new_user] = {"senha": new_pass, "meta": new_meta, "nome": new_name}
                    salvar_config(config)
                    st.success("Cadastrado!")
                else: st.error("Já existe.")
else:
    uid = st.session_state['usuario_logado']
    if uid in config['usuarios']:
        u_data = config['usuarios'][uid]
        st.sidebar.success(f"Olá, {u_data['nome']}")
        with st.sidebar.expander("🎯 Minha Meta"):
            nm = st.number_input("Meta (R$)", value=float(u_data['meta']))
            if st.button("Salvar Meta"):
                config['usuarios'][uid]['meta'] = nm
                salvar_config(config)
                st.rerun()
        with st.sidebar.expander("🏢 Meta MIC"):
            ng = st.number_input("Meta Geral (R$)", value=float(config['meta_geral']))
            if st.button("Salvar Geral"):
                config['meta_geral'] = ng
                salvar_config(config)
                st.rerun()
        if st.sidebar.button("Sair"):
            st.session_state['usuario_logado'] = None
            st.rerun()

# ==============================================================================
# 📊 DASHBOARD
# ==============================================================================
st.title("🚀 Painel de Controle de Vendas")

df, col_vend_nome = carregar_dados()

if df is not None:
    # --- FILTROS ---
    c1, c2 = st.columns(2)
    status_sel = c1.selectbox("Status", ["Todos", "Faturado", "A Faturar"])
    
    # Filtro Data: Padrão 01 até Último dia do Mês
    hoje = date.today()
    ultimo_dia = calendar.monthrange(hoje.year, hoje.month)[1]
    data_inicio_padrao = hoje.replace(day=1)
    data_fim_padrao = date(hoje.year, hoje.month, ultimo_dia)
    
    # Usuário pode mudar, mas o padrão já vem certo
    periodo = c2.date_input("Período", [data_inicio_padrao, data_fim_padrao])
    
    # Aplica Filtros
    df_filt = df.copy()
    if isinstance(periodo, list) and len(periodo) == 2:
        df_filt = df_filt[(df_filt['data_final'].dt.date >= periodo[0]) & (df_filt['data_final'].dt.date <= periodo[1])]
    
    if status_sel != "Todos":
        df_filt = df_filt[df_filt['status_ped'] == status_sel]

    # CÁLCULO DE DIAS ÚTEIS (SEMPRE ATE O FIM DO MES)
    dias_uteis_restantes = calcular_dias_uteis_restantes_mes()

    st.divider()

    # ==========================================================================
    # 🏢 META MIC (LOADING BAR)
    # ==========================================================================
    st.markdown("## 🏢 META MIC")
    
    tot_geral = df_filt['valor_final'].sum()
    meta_emp = config['meta_geral']
    falta_emp = max(0, meta_emp - tot_geral)
    
    # Barra de Progresso Estilosa
    barra_progresso_linda(tot_geral, meta_emp, titulo="Progresso Geral")

    # KPIs Abaixo da Barra
    k1, k2, k3 = st.columns(3)
    k1.metric("Vendas Totais", f"R$ {tot_geral:,.2f}")
    
    # Meta Diária Geral (Divisão correta pelos dias úteis)
    if dias_uteis_restantes > 0 and falta_emp > 0:
        diaria_geral = falta_emp / dias_uteis_restantes
        k2.metric("Meta Diária (Restante)", f"R$ {diaria_geral:,.2f}", help=f"Considerando {dias_uteis_restantes} dias úteis até o fim do mês")
    elif falta_emp > 0:
        # Se dias úteis acabaram mas meta não foi batida
        k2.metric("Meta Diária (Restante)", f"R$ {falta_emp:,.2f}", help="Vender tudo HOJE!")
    else:
        k2.metric("Meta Diária (Restante)", "R$ 0,00", "Meta Batida! 🚀")

    k3.metric("Falta Vender", f"R$ {falta_emp:,.2f}")

    if st.session_state['usuario_logado']:
        st.divider()
        u_logado = config['usuarios'][st.session_state['usuario_logado']]
        
        # Título ajustado
        st.markdown(f"### 👤 Peformance: {u_logado['nome']}")
        
        nome_busca = st.text_input("Filtrar nome (apague se não aparecer nada):", value=u_logado['nome'].split()[0])
        
        if col_vend_nome:
            df_user = df_filt[df_filt[col_vend_nome].astype(str).str.contains(nome_busca, case=False, na=False)]
            
            tot_u = df_user['valor_final'].sum()
            meta_u = float(u_logado['meta'])
            falta_u = max(0, meta_u - tot_u)
            
            # Cálculo Diário Individual
            if dias_uteis_restantes > 0 and falta_u > 0:
                diaria_u = falta_u / dias_uteis_restantes
            elif falta_u > 0:
                diaria_u = falta_u
            else:
                diaria_u = 0

            ku1, ku2, ku3, ku4 = st.columns(4)
            ku1.metric("Minhas Vendas", f"R$ {tot_u:,.2f}")
            ku2.metric("Minha Meta", f"R$ {meta_u:,.2f}")
            ku3.metric("Falta", f"R$ {falta_u:,.2f}")
            
            if diaria_u > 0:
                ku4.metric("Meta Diária (Restante)", f"R$ {diaria_u:,.2f}", delta=f"{dias_uteis_restantes} dias úteis")
            else:
                ku4.metric("Status", "Meta Batida! 🎉" if falta_u == 0 else "Mês Fechado")

            # Barra Individual
            barra_progresso_linda(tot_u, meta_u, titulo="Meu Progresso")

            with st.expander("Ver meus pedidos detalhados"):
                st.dataframe(df_user[['data_final', 'Cliente', 'valor_final', 'status_ped']].sort_values('data_final', ascending=False))
        else:
            st.warning("Coluna de vendedor não encontrada.")

    # ==========================================================================
    # 🏆 RANKING
    # ==========================================================================
    st.divider()
    g1, g2 = st.columns(2)
    
    if col_vend_nome:
        rank = df_filt.groupby(col_vend_nome)['valor_final'].sum().sort_values(ascending=False).head(10).reset_index()
        fig_r = px.bar(rank, x='valor_final', y=col_vend_nome, orientation='h', title="🏆 Top Vendedores", text_auto=True)
        fig_r.update_layout(yaxis=dict(autorange="reversed"))
        g1.plotly_chart(fig_r, use_container_width=True)
    
    evol = df_filt.groupby('data_final')['valor_final'].sum().reset_index()
    fig_l = px.line(evol, x='data_final', y='valor_final', markers=True, title="📈 Evolução Diária")
    g2.plotly_chart(fig_l, use_container_width=True)

else:
    st.error(f"Arquivo '{ARQUIVO_DADOS}' não encontrado.")