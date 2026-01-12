import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import plotly.express as px
import os
import json
from datetime import date, timedelta
import calendar
import numpy as np
from PIL import Image # Para lidar com imagens grandes

# ==============================================================================
# ⚙️ CONFIGURAÇÕES INICIAIS
# ==============================================================================
st.set_page_config(page_title="Sistema Comercial MIC", layout="wide", page_icon="📊")

ARQUIVO_DADOS = "lista.csv" 
ARQUIVO_LOGO = "logo.png"

# --- FUNÇÕES AUXILIARES ---

# Função para redimensionar imagens grandes e evitar o DecompressionBombError
def carregar_imagem_segura(caminho_imagem, max_pixels=80000000): # Limite seguro padrão
    try:
        # Abre a imagem
        img = Image.open(caminho_imagem)
        
        # Verifica o tamanho em pixels
        pixels = img.width * img.height
        
        if pixels > max_pixels:
            st.warning(f"A imagem {caminho_imagem} é muito grande e foi redimensionada para exibição.")
            # Redimensiona mantendo a proporção (thumbnail)
            img.thumbnail((1024, 1024)) 
            return img
        else:
            return img
    except Exception as e:
        st.error(f"Erro ao carregar imagem: {e}")
        return None

# --- BANCO DE DADOS (GOOGLE SHEETS) ---
# Função para buscar usuários na planilha
def get_users_from_sheets(conn):
    try:
        # Lê a planilha. ttl=0 garante que os dados não fiquem em cache eternamente
        # e sejam atualizados a cada recarga ou ação.
        df_users = conn.read(ttl=0)
        # Retorna um dicionário fácil de usar: {login: {senha, meta, nome}}
        # Assume colunas: Login, Senha, Meta, Nome
        users_dict = {}
        if not df_users.empty:
             for index, row in df_users.iterrows():
                 # Garante que os campos existem para evitar KeyErrors
                 if all(col in df_users.columns for col in ['Login', 'Senha', 'Meta', 'Nome']):
                     users_dict[str(row['Login'])] = {
                         "senha": str(row['Senha']),
                         "meta": float(row['Meta']),
                         "nome": str(row['Nome'])
                     }
        return users_dict, df_users
    except Exception as e:
        st.error(f"Erro ao conectar com Google Sheets: {e}")
        return {}, pd.DataFrame()

# Função para salvar novo usuário na planilha
def save_user_to_sheets(conn, df_antigo, novo_login, nova_senha, nova_meta, novo_nome):
    try:
        novo_dado = pd.DataFrame([{
            "Login": novo_login,
            "Senha": nova_senha,
            "Meta": nova_meta,
            "Nome": novo_nome
        }])
        
        # Concatena com os dados existentes
        df_atualizado = pd.concat([df_antigo, novo_dado], ignore_index=True)
        
        # Atualiza a planilha na nuvem
        conn.update(data=df_atualizado)
        return True
    except Exception as e:
        st.error(f"Erro ao salvar no Google Sheets: {e}")
        return False

# Função para atualizar usuário existente (ex: mudar senha ou meta)
def update_user_in_sheets(conn, df_atual, login, campo, novo_valor):
    try:
        # Localiza o índice onde o Login bate
        idx = df_atual.index[df_atual['Login'] == login].tolist()
        
        if not idx:
            return False
            
        # Atualiza o valor no DataFrame local
        df_atual.at[idx[0], campo] = novo_valor
        
        # Envia a tabela atualizada para a nuvem
        conn.update(data=df_atual)
        return True
    except Exception as e:
        st.error(f"Erro ao atualizar dados: {e}")
        return False

# Função para excluir usuário
def delete_user_from_sheets(conn, df_atual, login):
    try:
        # Filtra removendo o usuário
        df_novo = df_atual[df_atual['Login'] != login]
        
        # Atualiza na nuvem
        conn.update(data=df_novo)
        return True
    except Exception as e:
        st.error(f"Erro ao excluir usuário: {e}")
        return False


# --- INICIALIZAÇÃO DA CONEXÃO ---
# Conecta ao Google Sheets usando as credenciais do secrets.toml
conn_sheets = st.connection("gsheets", type=GSheetsConnection)

# Carrega os usuários no início
usuarios_dict, df_usuarios_raw = get_users_from_sheets(conn_sheets)

# Meta Geral da Empresa (ainda pode ficar local ou ir para uma aba separada da planilha)
# Para simplificar, vou manter fixo aqui ou usar um valor padrão, já que o foco é o login.
META_GERAL_EMPRESA = 100000.0


# --- CÁLCULO DE DIAS ÚTEIS ---
def calcular_dias_uteis_restantes_mes():
    hoje = date.today()
    ultimo_dia_numero = calendar.monthrange(hoje.year, hoje.month)[1]
    data_fim_mes = date(hoje.year, hoje.month, ultimo_dia_numero)
    
    if hoje > data_fim_mes: return 0
    
    dias = np.busday_count(hoje, data_fim_mes + timedelta(days=1))
    return max(0, int(dias))

# --- BARRA DE PROGRESSO CUSTOMIZADA ---
def barra_progresso_linda(atual, meta, titulo="Progresso"):
    porcentagem = (atual / meta * 100) if meta > 0 else 0
    porcentagem_visual = min(porcentagem, 100) 
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
# 📥 CARGA DE DADOS (CSV de Vendas)
# ==============================================================================
def carregar_dados_vendas():
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
# 🔐 BARRA LATERAL (LOGIN, CADASTRO E GERENCIAMENTO)
# ==============================================================================
if os.path.exists(ARQUIVO_LOGO):
    # Usa a função segura para evitar o erro de bomba de descompressão
    img_logo = carregar_imagem_segura(ARQUIVO_LOGO)
    if img_logo:
        st.sidebar.image(img_logo, use_container_width=True)
else:
    st.sidebar.title("MIC")

st.sidebar.markdown("---")
st.sidebar.subheader("🔐 Acesso Restrito")

if 'usuario_logado' not in st.session_state: st.session_state['usuario_logado'] = None

if st.session_state['usuario_logado'] is None:
    # --- ÁREA DESLOGADA ---
    tab_login, tab_cadastro = st.sidebar.tabs(["Entrar", "Cadastrar"])
    
    with tab_login:
        u_in = st.text_input("Usuário")
        p_in = st.text_input("Senha", type="password")
        if st.button("Entrar"):
            # Recarrega usuários para garantir dados frescos
            usuarios_dict, df_usuarios_raw = get_users_from_sheets(conn_sheets)
            
            if u_in in usuarios_dict and str(usuarios_dict[u_in]['senha']) == p_in:
                st.session_state['usuario_logado'] = u_in
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos.")
                
    with tab_cadastro:
        new_user = st.text_input("Novo Usuário (Login)")
        new_pass = st.text_input("Nova Senha", type="password")
        new_name = st.text_input("Nome Completo")
        new_meta = st.number_input("Meta Inicial", value=10000.0)
        
        if st.button("Criar Vendedor"):
            if new_user and new_pass:
                # Recarrega para checar se já existe
                usuarios_dict, df_usuarios_raw = get_users_from_sheets(conn_sheets)
                
                if new_user not in usuarios_dict:
                    sucesso = save_user_to_sheets(conn_sheets, df_usuarios_raw, new_user, new_pass, new_meta, new_name)
                    if sucesso:
                        st.success("Cadastrado com sucesso! Faça login.")
                    else:
                        st.error("Erro ao salvar no banco.")
                else:
                    st.error("Usuário já existe.")
            else:
                st.warning("Preencha todos os campos.")
else:
    # --- ÁREA LOGADA ---
    uid = st.session_state['usuario_logado']
    
    # Verifica se usuário ainda existe
    if uid in usuarios_dict:
        u_data = usuarios_dict[uid]
        st.sidebar.success(f"Olá, {u_data['nome']}")
        
        # 1. METAS
        with st.sidebar.expander("🎯 Metas"):
            nm = st.number_input("Minha Meta (R$)", value=float(u_data['meta']))
            if st.button("Salvar Meta Individual"):
                sucesso = update_user_in_sheets(conn_sheets, df_usuarios_raw, uid, 'Meta', nm)
                if sucesso:
                    st.success("Meta atualizada!")
                    st.rerun()
            
            st.markdown("---")
            # Meta Geral (Simulada ou fixa por enquanto, já que não está na tabela de usuários)
            st.info(f"Meta Geral da Empresa: R$ {META_GERAL_EMPRESA:,.2f}")

        # 2. GERENCIAR CONTA
        with st.sidebar.expander("⚙️ Gerenciar Conta"):
            st.markdown("**Alterar Senha**")
            senha_antiga = st.text_input("Senha Atual", type="password", key="p1")
            senha_nova = st.text_input("Nova Senha", type="password", key="p2")
            
            if st.button("Atualizar Senha"):
                if senha_antiga == u_data['senha']:
                    sucesso = update_user_in_sheets(conn_sheets, df_usuarios_raw, uid, 'Senha', senha_nova)
                    if sucesso:
                        st.success("Senha atualizada!")
                    else:
                        st.error("Erro ao atualizar.")
                else:
                    st.error("Senha atual incorreta!")
            
            st.divider()
            st.markdown("**Zona de Perigo**")
            confirmar_exclusao = st.checkbox("Quero excluir minha conta")
            if st.button("🗑️ Excluir Conta", disabled=not confirmar_exclusao):
                sucesso = delete_user_from_sheets(conn_sheets, df_usuarios_raw, uid)
                if sucesso:
                    st.session_state['usuario_logado'] = None
                    st.rerun()
                else:
                    st.error("Erro ao excluir.")

        # 3. LOGOUT
        if st.sidebar.button("Sair"):
            st.session_state['usuario_logado'] = None
            st.rerun()
    else:
        st.session_state['usuario_logado'] = None
        st.rerun()

# ==============================================================================
# 📊 DASHBOARD
# ==============================================================================
st.title("🚀 Painel de Controle de Vendas")

df, col_vend_nome = carregar_dados_vendas()

if df is not None:
    # --- FILTROS ---
    c1, c2 = st.columns(2)
    status_sel = c1.selectbox("Status", ["Todos", "Faturado", "A Faturar"])
    
    hoje = date.today()
    ultimo_dia = calendar.monthrange(hoje.year, hoje.month)[1]
    data_inicio_padrao = hoje.replace(day=1)
    data_fim_padrao = date(hoje.year, hoje.month, ultimo_dia)
    
    periodo = c2.date_input("Período", [data_inicio_padrao, data_fim_padrao])
    
    df_filt = df.copy()
    if isinstance(periodo, list) and len(periodo) == 2:
        df_filt = df_filt[(df_filt['data_final'].dt.date >= periodo[0]) & (df_filt['data_final'].dt.date <= periodo[1])]
    
    if status_sel != "Todos":
        df_filt = df_filt[df_filt['status_ped'] == status_sel]

    dias_uteis_restantes = calcular_dias_uteis_restantes_mes()

    st.divider()

    # --- META MIC (GERAL) ---
    st.markdown("## 🏢 META MIC")
    tot_geral = df_filt['valor_final'].sum()
    meta_emp = META_GERAL_EMPRESA
    falta_emp = max(0, meta_emp - tot_geral)
    
    barra_progresso_linda(tot_geral, meta_emp, titulo="Progresso Geral")

    k1, k2, k3 = st.columns(3)
    k1.metric("Vendas Totais", f"R$ {tot_geral:,.2f}")
    
    if dias_uteis_restantes > 0 and falta_emp > 0:
        diaria_geral = falta_emp / dias_uteis_restantes
        k2.metric("Meta Diária (Restante)", f"R$ {diaria_geral:,.2f}", help=f"{dias_uteis_restantes} dias úteis restantes no mês")
    elif falta_emp > 0:
        k2.metric("Meta Diária (Restante)", f"R$ {falta_emp:,.2f}", help="Prazo esgotado ou último dia!")
    else:
        k2.metric("Meta Diária (Restante)", "R$ 0,00", "Meta Batida! 🚀")

    k3.metric("Falta Vender", f"R$ {falta_emp:,.2f}")

    # --- PERFORMANCE INDIVIDUAL ---
    if st.session_state['usuario_logado']:
        st.divider()
        # Busca dados atualizados do usuário logado
        if st.session_state['usuario_logado'] in usuarios_dict:
             u_logado = usuarios_dict[st.session_state['usuario_logado']]
             st.markdown(f"### 👤 PERFORMANCE: {u_logado['nome']}")
             
             # Tenta filtrar pelo nome do usuário automaticamente
             nome_busca = st.text_input("Filtrar nome (apague se não aparecer nada):", value=u_logado['nome'].split()[0])
             
             if col_vend_nome:
                 df_user = df_filt[df_filt[col_vend_nome].astype(str).str.contains(nome_busca, case=False, na=False)]
                 
                 tot_u = df_user['valor_final'].sum()
                 meta_u = float(u_logado['meta'])
                 falta_u = max(0, meta_u - tot_u)
                 
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

                 barra_progresso_linda(tot_u, meta_u, titulo="Meu Progresso")

                 with st.expander("Ver meus pedidos detalhados"):
                     if 'Cliente' in df_user.columns:
                        st.dataframe(df_user[['data_final', 'Cliente', 'valor_final', 'status_ped']].sort_values('data_final', ascending=False))
                     else:
                        st.dataframe(df_user[['data_final', 'valor_final', 'status_ped']].sort_values('data_final', ascending=False))

             else:
                 st.warning("Coluna de vendedor não encontrada no arquivo CSV.")
        else:
            st.error("Usuário logado não encontrado na base.")

    # --- RANKING ---
    st.divider()
    g1, g2 = st.columns(2)
    if col_vend_nome:
        # Top 10 Vendedores
        rank = df_filt.groupby(col_vend_nome)['valor_final'].sum().sort_values(ascending=False).head(10).reset_index()
        fig_r = px.bar(rank, x='valor_final', y=col_vend_nome, orientation='h', title="🏆 Top Vendedores", text_auto=True)
        fig_r.update_layout(yaxis=dict(autorange="reversed"))
        g1.plotly_chart(fig_r, use_container_width=True)
    
    # Evolução de Vendas
    evol = df_filt.groupby('data_final')['valor_final'].sum().reset_index()
    fig_l = px.line(evol, x='data_final', y='valor_final', markers=True, title="📈 Evolução Diária")
    g2.plotly_chart(fig_l, use_container_width=True)

else:
    st.error(f"Arquivo '{ARQUIVO_DADOS}' não encontrado.")