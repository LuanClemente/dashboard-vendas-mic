import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import plotly.express as px
import os
import json # Mantido apenas para compatibilidade, não usado para salvar
from datetime import date, timedelta
import calendar
import numpy as np
from PIL import Image 

# ==============================================================================
# ⚙️ CONFIGURAÇÕES INICIAIS
# ==============================================================================
st.set_page_config(page_title="Sistema Comercial MIC", layout="wide", page_icon="📊")

# Nomes dos arquivos
ARQUIVO_DADOS = "lista.csv" 
ARQUIVO_LOGO = "logo.png"

# --- FUNÇÃO DE IMAGEM SEGURA (Mantida por precaução) ---
def carregar_imagem_segura(caminho_imagem):
    try:
        img = Image.open(caminho_imagem)
        # Se quiser garantir, forçamos um resize visual no Streamlit depois
        return img
    except Exception as e:
        st.error(f"Erro ao carregar logo: {e}")
        return None

# ==============================================================================
# ☁️ BANCO DE DADOS (GOOGLE SHEETS)
# ==============================================================================

# Conecta usando as credenciais que você salvou nos Secrets
conn = st.connection("gsheets", type=GSheetsConnection)

def inicializar_e_carregar_usuarios():
    """
    Lê a planilha do Google. Se estiver vazia, cria o cabeçalho e um admin padrão.
    """
    try:
        # ttl=0 obriga a ler do Google agora, sem usar memória velha (cache)
        df = conn.read(ttl=0)
        
        # Se a planilha estiver vazia ou com colunas erradas, vamos consertar
        colunas_necessarias = ["Login", "Senha", "Meta", "Nome"]
        
        # Verifica se as colunas existem
        if df.empty or not set(colunas_necessarias).issubset(df.columns):
            # Recria a estrutura
            df_init = pd.DataFrame(columns=colunas_necessarias)
            
            # Se estiver vazia mesmo, cria o Admin
            if df.empty:
                df_init = pd.DataFrame([{
                    "Login": "admin", 
                    "Senha": "123", 
                    "Meta": 100000.0, 
                    "Nome": "Administrador"
                }])
            
            # Salva na nuvem
            conn.update(data=df_init)
            return df_init
        
        return df
    except Exception as e:
        # Se der erro crítico (ex: planilha zerada), reseta
        st.warning("Inicializando banco de dados na nuvem...")
        df_init = pd.DataFrame(columns=["Login", "Senha", "Meta", "Nome"])
        conn.update(data=df_init)
        return df_init

# Carrega os dados frescos da nuvem
df_usuarios = inicializar_e_carregar_usuarios()

# Cria um dicionário rápido pra login: {'admin': {'senha': '123', ...}}
usuarios_dict = {}
if not df_usuarios.empty and "Login" in df_usuarios.columns:
    # Garante que Login é texto
    df_usuarios["Login"] = df_usuarios["Login"].astype(str)
    
    for index, row in df_usuarios.iterrows():
        usuarios_dict[row["Login"]] = {
            "senha": str(row["Senha"]),
            "meta": float(row["Meta"]) if pd.notnull(row["Meta"]) else 0.0,
            "nome": str(row["Nome"])
        }

# --- FUNÇÕES PARA SALVAR NA NUVEM ---

def salvar_novo_usuario(login, senha, meta, nome):
    try:
        # Cria a linha nova
        novo_dado = pd.DataFrame([{
            "Login": login,
            "Senha": senha,
            "Meta": meta,
            "Nome": nome
        }])
        # Lê o que tem lá agora
        df_atual = conn.read(ttl=0)
        # Junta o velho com o novo
        df_final = pd.concat([df_atual, novo_dado], ignore_index=True)
        # Manda pro Google
        conn.update(data=df_final)
        return True
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")
        return False

def atualizar_usuario(login, campo, novo_valor):
    try:
        df_atual = conn.read(ttl=0)
        df_atual["Login"] = df_atual["Login"].astype(str)
        
        # Acha a linha do usuário
        indices = df_atual.index[df_atual["Login"] == login].tolist()
        if indices:
            idx = indices[0]
            df_atual.at[idx, campo] = novo_valor # Atualiza a célula
            conn.update(data=df_atual) # Salva
            return True
        return False
    except Exception as e:
        st.error(f"Erro ao atualizar: {e}")
        return False

def excluir_usuario(login):
    try:
        df_atual = conn.read(ttl=0)
        df_atual["Login"] = df_atual["Login"].astype(str)
        # Filtra todo mundo MENOS o usuário que queremos excluir
        df_nova = df_atual[df_atual["Login"] != login]
        conn.update(data=df_nova)
        return True
    except Exception as e:
        st.error(f"Erro ao excluir: {e}")
        return False

# ==============================================================================
# 📥 CARGA DE DADOS (CSV VENDAS - Mantido igual)
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

# --- FUNÇÕES VISUAIS ---
def calcular_dias_uteis_restantes_mes():
    hoje = date.today()
    ultimo_dia_numero = calendar.monthrange(hoje.year, hoje.month)[1]
    data_fim_mes = date(hoje.year, hoje.month, ultimo_dia_numero)
    if hoje > data_fim_mes: return 0
    dias = np.busday_count(hoje, data_fim_mes + timedelta(days=1))
    return max(0, int(dias))

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
# 🔐 BARRA LATERAL (LOGIN, CADASTRO NA NUVEM)
# ==============================================================================
if os.path.exists(ARQUIVO_LOGO):
    img_logo = carregar_imagem_segura(ARQUIVO_LOGO)
    if img_logo:
        st.sidebar.image(img_logo, use_container_width=True)
else:
    st.sidebar.title("MIC")

st.sidebar.markdown("---")
st.sidebar.subheader("🔐 Acesso Restrito (Nuvem)")

if 'usuario_logado' not in st.session_state: st.session_state['usuario_logado'] = None

if st.session_state['usuario_logado'] is None:
    # --- ÁREA DESLOGADA ---
    tab_login, tab_cadastro = st.sidebar.tabs(["Entrar", "Cadastrar"])
    
    with tab_login:
        u_in = st.text_input("Usuário")
        p_in = st.text_input("Senha", type="password")
        if st.button("Entrar"):
            # Verifica no dicionário que veio do Google Sheets
            if u_in in usuarios_dict and usuarios_dict[u_in]['senha'] == p_in:
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
                if new_user not in usuarios_dict:
                    with st.spinner("Salvando na nuvem..."):
                        if salvar_novo_usuario(new_user, new_pass, new_meta, new_name):
                            st.success("Cadastrado! Faça login.")
                            # Não damos rerun aqui pro usuário ver a mensagem de sucesso
                        else:
                            st.error("Erro ao conectar com Google Sheets.")
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
                with st.spinner("Atualizando nuvem..."):
                    if atualizar_usuario(uid, "Meta", nm):
                        st.success("Meta salva!")
                        st.rerun()
            
            st.markdown("---")
            # Meta Geral (Valor fixo pra simplificar)
            st.info("Meta Geral: R$ 100.000,00")

        # 2. GERENCIAR CONTA
        with st.sidebar.expander("⚙️ Gerenciar Conta"):
            st.markdown("**Alterar Senha**")
            senha_antiga = st.text_input("Senha Atual", type="password", key="p1")
            senha_nova = st.text_input("Nova Senha", type="password", key="p2")
            
            if st.button("Atualizar Senha"):
                if senha_antiga == u_data['senha']:
                    with st.spinner("Atualizando..."):
                        if atualizar_usuario(uid, "Senha", senha_nova):
                            st.success("Senha atualizada!")
                else:
                    st.error("Senha atual incorreta!")
            
            st.divider()
            st.markdown("**Zona de Perigo**")
            confirmar_exclusao = st.checkbox("Quero excluir minha conta")
            if st.button("🗑️ Excluir Conta", disabled=not confirmar_exclusao):
                with st.spinner("Excluindo..."):
                    if excluir_usuario(uid):
                        st.session_state['usuario_logado'] = None
                        st.rerun()

        # 3. LOGOUT
        if st.sidebar.button("Sair"):
            st.session_state['usuario_logado'] = None
            st.rerun()
    else:
        st.session_state['usuario_logado'] = None
        st.rerun()

# ==============================================================================
# 📊 DASHBOARD PRINCIPAL
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

    # --- META MIC ---
    st.markdown("## 🏢 META MIC")
    tot_geral = df_filt['valor_final'].sum()
    meta_emp = 100000.0
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
        uid = st.session_state['usuario_logado']
        if uid in usuarios_dict:
            u_logado = usuarios_dict[uid]
            st.markdown(f"### 👤 PERFORMANCE: {u_logado['nome']}")
            
            # Filtro inteligente de nome
            nome_padrao = u_logado['nome'].split()[0]
            nome_busca = st.text_input("Filtrar nome (apague se não aparecer nada):", value=nome_padrao)
            
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
                    cols_show = ['data_final', 'valor_final', 'status_ped']
                    if 'Cliente' in df_user.columns: cols_show.insert(1, 'Cliente')
                    st.dataframe(df_user[cols_show].sort_values('data_final', ascending=False))
            else:
                st.warning("Coluna de vendedor não encontrada no CSV.")

    # --- RANKING ---
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