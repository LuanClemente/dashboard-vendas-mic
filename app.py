import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import plotly.express as px
import os
import json 
from datetime import date, timedelta
import calendar
import numpy as np
from PIL import Image 

# ==============================================================================
# ⚙️ CONFIGURAÇÕES INICIAIS
# ==============================================================================
st.set_page_config(page_title="Sistema Comercial MIC", layout="wide", page_icon="📊", initial_sidebar_state="collapsed")

ARQUIVO_DADOS = "lista.csv" 
ARQUIVO_LOGO = "logo.png"

# Esconde o menu padrão e rodapé para ficar "App Nativo"
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        [data-testid="stSidebar"] {display: none;}
        .stApp {margin-top: -80px;}
    </style>
""", unsafe_allow_html=True)

# --- FUNÇÃO SEGURA DE IMAGEM ---
def carregar_imagem_segura(caminho_imagem):
    try:
        img = Image.open(caminho_imagem)
        return img
    except Exception as e:
        return None

# ==============================================================================
# ☁️ BANCO DE DADOS (GOOGLE SHEETS)
# ==============================================================================

conn = st.connection("gsheets", type=GSheetsConnection)

def limpar_dado(dado):
    if pd.isna(dado): return ""
    texto = str(dado).strip()
    if texto.endswith(".0"):
        texto = texto.replace(".0", "")
    return texto

def inicializar_e_carregar_usuarios():
    try:
        df = conn.read(ttl=0)
        # Meta_Rep agora guardará um JSON: {"Rep A": 100, "Rep B": 200}
        # Config_Layout guardará a ordem: "Meta MIC,Supervisão,Top 10"
        colunas_necessarias = ["Login", "Senha", "Meta", "Nome", "Meta_Rep", "Config_Layout"]
        
        if df.empty:
            df_init = pd.DataFrame([
                {"Login": "admin", "Senha": "123", "Meta": 10000.0, "Nome": "Administrador", "Meta_Rep": "{}", "Config_Layout": ""},
                {"Login": "__GLOBAL__", "Senha": "***", "Meta": 100000.0, "Nome": "Meta da Empresa", "Meta_Rep": "{}", "Config_Layout": ""}
            ])
            conn.update(data=df_init)
            return df_init

        colunas_faltantes = [c for c in colunas_necessarias if c not in df.columns]
        if colunas_faltantes:
            for c in colunas_faltantes:
                # Meta_Rep padrão é JSON vazio, Layout vazio usa o padrão
                df[c] = "{}" if "Meta_Rep" in c else ""
            conn.update(data=df)
        
        if "__GLOBAL__" not in df["Login"].astype(str).values:
            linha_global = pd.DataFrame([{
                "Login": "__GLOBAL__", "Senha": "***", "Meta": 100000.0, "Nome": "Meta da Empresa",
                "Meta_Rep": "{}", "Config_Layout": ""
            }])
            df = pd.concat([df, linha_global], ignore_index=True)
            conn.update(data=df)
            
        return df
    except Exception as e:
        return pd.DataFrame(columns=["Login", "Senha", "Meta", "Nome", "Meta_Rep", "Config_Layout"])

# Carrega e Processa
df_usuarios = inicializar_e_carregar_usuarios()
META_GERAL_EMPRESA = 100000.0
usuarios_dict = {}

if not df_usuarios.empty:
    for index, row in df_usuarios.iterrows():
        login_limpo = limpar_dado(row["Login"])
        if login_limpo == "__GLOBAL__":
            META_GERAL_EMPRESA = float(row["Meta"]) if pd.notnull(row["Meta"]) else 100000.0
        elif login_limpo: 
            # Parse do JSON de Metas dos Representantes
            meta_rep_raw = row.get("Meta_Rep", "{}")
            try:
                metas_reps_dict = json.loads(str(meta_rep_raw)) if meta_rep_raw else {}
            except:
                metas_reps_dict = {}

            usuarios_dict[login_limpo] = {
                "senha": limpar_dado(row["Senha"]),
                "meta": float(row["Meta"]) if pd.notnull(row["Meta"]) else 0.0,
                "nome": str(row["Nome"]),
                "metas_reps": metas_reps_dict, # Dicionário {NomeRep: ValorMeta}
                "layout": str(row.get("Config_Layout", ""))
            }

# --- FUNÇÕES DE ATUALIZAÇÃO ---
def salvar_novo_usuario(login, senha, meta, nome):
    try:
        if login == "__GLOBAL__": return False
        novo_dado = pd.DataFrame([{
            "Login": str(login).strip(), "Senha": str(senha).strip(), "Meta": meta, "Nome": nome,
            "Meta_Rep": "{}", "Config_Layout": ""
        }])
        df_atual = conn.read(ttl=0)
        df_final = pd.concat([df_atual, novo_dado], ignore_index=True)
        conn.update(data=df_final)
        return True
    except Exception as e:
        st.error(f"Erro: {e}")
        return False

def atualizar_campo(login, campo, novo_valor):
    try:
        df_atual = conn.read(ttl=0)
        df_atual["Login"] = df_atual["Login"].astype(str).str.strip()
        indices = df_atual.index[df_atual["Login"] == str(login).strip()].tolist()
        if indices:
            idx = indices[0]
            # Se for dicionário (metas dos reps), vira JSON string
            if isinstance(novo_valor, dict):
                novo_valor = json.dumps(novo_valor)
            
            df_atual.at[idx, campo] = novo_valor
            conn.update(data=df_atual)
            return True
        return False
    except Exception as e:
        st.error(f"Erro: {e}")
        return False

def excluir_usuario(login):
    try:
        df_atual = conn.read(ttl=0)
        df_atual["Login"] = df_atual["Login"].astype(str).str.strip()
        df_nova = df_atual[df_atual["Login"] != str(login).strip()]
        conn.update(data=df_nova)
        return True
    except Exception as e:
        st.error(f"Erro: {e}")
        return False

# ==============================================================================
# 📥 CARGA DE DADOS (CSV)
# ==============================================================================
def carregar_dados_vendas():
    if not os.path.exists(ARQUIVO_DADOS): return None, None, []
    try:
        try: df = pd.read_csv(ARQUIVO_DADOS, sep=";", encoding="utf-8", on_bad_lines='skip', dtype={'NF': str})
        except: df = pd.read_csv(ARQUIVO_DADOS, sep=";", encoding="latin1", on_bad_lines='skip', dtype={'NF': str})

        df.columns = [c.strip() for c in df.columns]
        cols = df.columns
        col_valor = next((c for c in cols if 'Valor' in c or 'Liq' in c), None)
        col_data = next((c for c in cols if 'Gera' in c or 'Data' in c or 'Emis' in c), None)
        col_nf = next((c for c in cols if 'NF' in c or 'Nota' in c), None)
        col_vend = next((c for c in cols if 'Vendedor' in c or 'Vend' in c), None)
        col_rep = next((c for c in cols if 'Representante' in c or 'Rep' in c), None)
        col_cnpj = next((c for c in cols if 'CNPJ' in c or 'CGC' in c), None)
        col_pedido = next((c for c in cols if 'Pedido' in c), None)

        if not col_valor or not col_data: return None, None, []

        if df[col_valor].dtype == 'O':
            df[col_valor] = df[col_valor].astype(str).str.replace('R$', '').str.strip().str.replace('.', '').str.replace(',', '.')
        df['valor_final'] = pd.to_numeric(df[col_valor], errors='coerce').fillna(0)
        df['data_final'] = pd.to_datetime(df[col_data], dayfirst=True, errors='coerce')
        
        if col_nf:
            df['status_ped'] = df[col_nf].apply(lambda x: 'Faturado' if pd.notnull(x) and str(x).strip() != '' else 'A Faturar')
        else:
            df['status_ped'] = 'Desconhecido'
            
        if col_cnpj: df[col_cnpj] = df[col_cnpj].astype(str)
        if not col_pedido and col_nf: col_pedido = col_nf 
        df['id_pedido'] = df[col_pedido] if col_pedido else df.index

        lista_reps = sorted(df[col_rep].dropna().unique().tolist()) if col_rep else []

        return df, col_vend, lista_reps
    except: return None, None, []

# --- VISUAL E UTILITÁRIOS ---
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

def converter_df_para_csv(df):
    return df.to_csv(index=False, sep=";").encode('utf-8')

# ==============================================================================
# 🏁 FLUXO PRINCIPAL
# ==============================================================================

if 'usuario_logado' not in st.session_state: st.session_state['usuario_logado'] = None
df, col_vend_nome, lista_reps_disponiveis = carregar_dados_vendas()

# --- TELA DE LOGIN (Sem Sidebar) ---
if st.session_state['usuario_logado'] is None:
    # Layout centralizado
    col_vazia1, col_login, col_vazia2 = st.columns([1, 2, 1])
    
    with col_login:
        st.write("") # Espaço
        st.write("")
        if os.path.exists(ARQUIVO_LOGO):
            img = carregar_imagem_segura(ARQUIVO_LOGO)
            if img: st.image(img, use_container_width=True)
        else:
            st.title("MIC Comercial")
        
        tab_entrar, tab_cadastrar = st.tabs(["Acessar", "Criar Conta"])
        
        with tab_entrar:
            u_in = st.text_input("Usuário").strip()
            p_in = st.text_input("Senha", type="password").strip()
            if st.button("Entrar", use_container_width=True):
                if u_in in usuarios_dict and usuarios_dict[u_in]['senha'] == p_in:
                    st.session_state['usuario_logado'] = u_in
                    st.rerun()
                else: st.error("Acesso negado.")
            if st.button("🔄 Atualizar Sistema", use_container_width=True):
                st.cache_data.clear()
                st.rerun()

        with tab_cadastrar:
            new_user = st.text_input("Novo Usuário").strip()
            new_pass = st.text_input("Nova Senha", type="password").strip()
            new_name = st.text_input("Nome Completo")
            if st.button("Registrar", use_container_width=True):
                if new_user and new_pass and new_user != "__GLOBAL__":
                    if new_user not in usuarios_dict:
                        if salvar_novo_usuario(new_user, new_pass, 10000.0, new_name):
                            st.success("Criado! Faça login.")
                    else: st.error("Usuário já existe.")
                else: st.warning("Dados inválidos.")

# --- TELA DO SISTEMA (LOGADO) ---
else:
    uid = st.session_state['usuario_logado']
    
    # Validação de Segurança
    if uid not in usuarios_dict:
        st.session_state['usuario_logado'] = None
        st.rerun()
    
    u_data = usuarios_dict[uid]
    
    # --- CABEÇALHO COM LOGO E CONFIGURAÇÕES ---
    head1, head2 = st.columns([4, 1])
    with head1:
        if os.path.exists(ARQUIVO_LOGO):
            img = carregar_imagem_segura(ARQUIVO_LOGO)
            if img: st.image(img, width=150)
        else: st.title("MIC")
    
    with head2:
        st.write("") # Alinhamento
        # --- MENU DE CONFIGURAÇÕES (ENGRENAGEM) ---
        with st.popover("⚙️ Configurações", use_container_width=True):
            st.markdown(f"**Olá, {u_data['nome']}**")
            
            # 1. ORDEM DO DASHBOARD (Customização)
            st.markdown("---")
            st.caption("Customize seu Painel")
            opcoes_layout = ["Meta MIC (Empresa)", "Supervisão (Reps)", "Top 10 Clientes (Reps)", "Lista Clientes (Reps)", "Performance Individual", "Meus Top 10 Clientes", "Ranking Geral", "Evolução Diária"]
            
            # Carrega layout salvo ou usa padrão
            layout_salvo = u_data['layout'].split(',') if u_data['layout'] else opcoes_layout
            layout_salvo = [l for l in layout_salvo if l in opcoes_layout] # Limpa lixo
            if not layout_salvo: layout_salvo = opcoes_layout 

            novo_layout = st.multiselect("Ordem de Exibição:", opcoes_layout, default=layout_salvo)
            
            if st.button("Salvar Layout"):
                layout_str = ",".join(novo_layout)
                if atualizar_campo(uid, "Config_Layout", layout_str):
                    st.success("Layout Salvo!")
                    st.rerun()

            # 2. GESTÃO DE REPRESENTANTES (Adicionar/Remover)
            st.markdown("---")
            st.caption("Gerenciar Representantes e Metas")
            
            # Lista o que já tem
            metas_reps = u_data['metas_reps'] # Dict {'Rep': 100, 'Rep2': 200}
            
            # Adicionar/Editar
            rep_para_add = st.selectbox("Adicionar/Editar Rep:", [""] + lista_reps_disponiveis)
            meta_para_add = st.number_input("Meta deste Rep (R$):", value=0.0)
            
            if st.button("💾 Salvar Rep"):
                if rep_para_add:
                    metas_reps[rep_para_add] = meta_para_add
                    if atualizar_campo(uid, "Meta_Rep", metas_reps):
                        st.success(f"{rep_para_add} atualizado!")
                        st.rerun()
            
            # Remover
            st.markdown("---")
            st.caption("Remover Representante")
            rep_para_remover = st.selectbox("Remover da lista:", [""] + list(metas_reps.keys()))
            if st.button("🗑️ Remover Rep"):
                if rep_para_remover in metas_reps:
                    del metas_reps[rep_para_remover]
                    if atualizar_campo(uid, "Meta_Rep", metas_reps):
                        st.success("Removido!")
                        st.rerun()

            # 3. CONTA
            st.markdown("---")
            st.caption("Minha Conta")
            minha_meta = st.number_input("Minha Meta Pessoal:", value=float(u_data['meta']))
            if st.button("Salvar Minha Meta"):
                if atualizar_campo(uid, "Meta", minha_meta): st.rerun()
            
            senha_nova = st.text_input("Nova Senha", type="password")
            if st.button("Alterar Senha"):
                if atualizar_campo(uid, "Senha", senha_nova): st.success("Senha alterada!")
            
            # META GLOBAL (Só editável aqui para simplificar)
            st.markdown("---")
            meta_global_input = st.number_input("Meta Global Empresa:", value=float(META_GERAL_EMPRESA))
            if st.button("Salvar Meta Global"):
                if atualizar_campo("__GLOBAL__", "Meta", meta_global_input): st.rerun()

            if st.button("Sair da Conta", type="primary"):
                st.session_state['usuario_logado'] = None
                st.rerun()

    st.divider()
    
    # --- RENDERIZAÇÃO DO DASHBOARD ---
    if df is not None:
        # Filtros Globais
        c1, c2 = st.columns(2)
        status_sel = c1.selectbox("Status", ["Todos", "Faturado", "A Faturar"])
        hoje = date.today()
        ultimo_dia = calendar.monthrange(hoje.year, hoje.month)[1]
        periodo = c2.date_input("Período", [hoje.replace(day=1), date(hoje.year, hoje.month, ultimo_dia)])
        
        df_filt = df.copy()
        if isinstance(periodo, list) and len(periodo) == 2:
            df_filt = df_filt[(df_filt['data_final'].dt.date >= periodo[0]) & (df_filt['data_final'].dt.date <= periodo[1])]
        if status_sel != "Todos":
            df_filt = df_filt[df_filt['status_ped'] == status_sel]
        
        dias_uteis = calcular_dias_uteis_restantes_mes()

        # --- FUNÇÕES DE RENDERIZAÇÃO ---
        
        def render_meta_mic():
            st.markdown("### 🏢 Meta MIC (Empresa)")
            tot_geral = df_filt['valor_final'].sum()
            falta_emp = max(0, META_GERAL_EMPRESA - tot_geral)
            pedidos = df_filt['id_pedido'].nunique()
            ticket = tot_geral / pedidos if pedidos > 0 else 0
            
            barra_progresso_linda(tot_geral, META_GERAL_EMPRESA, "Progresso Geral")
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Vendas Totais", f"R$ {tot_geral:,.2f}")
            k2.metric("Diária (Restante)", f"R$ {(falta_emp / dias_uteis if dias_uteis > 0 else 0):,.2f}")
            k3.metric("Falta", f"R$ {falta_emp:,.2f}")
            k4.metric("Ticket Médio", f"R$ {ticket:,.2f}")
            st.divider()

        def render_supervisao():
            metas_reps = u_data['metas_reps'] # Dict {Nome: Meta}
            if metas_reps:
                st.markdown("### 🤝 Supervisão de Representantes")
                # Cria abas para cada representante
                abas = st.tabs(list(metas_reps.keys()))
                
                for i, (rep_nome, rep_meta) in enumerate(metas_reps.items()):
                    with abas[i]:
                        df_rep = df_filt[df_filt['Representante'] == rep_nome]
                        tot_rep = df_rep['valor_final'].sum()
                        falta_rep = max(0, rep_meta - tot_rep)
                        pedidos_rep = df_rep['id_pedido'].nunique()
                        ticket_rep = tot_rep / pedidos_rep if pedidos_rep > 0 else 0
                        
                        st.caption(f"Meta Definida: R$ {rep_meta:,.2f}")
                        r1, r2, r3, r4 = st.columns(4)
                        r1.metric("Vendas", f"R$ {tot_rep:,.2f}")
                        r2.metric("Falta", f"R$ {falta_rep:,.2f}")
                        r3.metric("Diária", f"R$ {(falta_rep / dias_uteis if dias_uteis > 0 else 0):,.2f}")
                        r4.metric("Ticket Médio", f"R$ {ticket_rep:,.2f}")
                        
                        barra_progresso_linda(tot_rep, rep_meta, f"Progresso {rep_nome}")
                        
                        # AREA DE DOWNLOAD
                        csv = converter_df_para_csv(df_rep)
                        st.download_button(f"📥 Baixar Relatório de {rep_nome}", csv, f"Relatorio_{rep_nome}.csv", "text/csv")

        def render_top10_reps():
            metas_reps = u_data['metas_reps']
            if metas_reps:
                lista_nomes_reps = list(metas_reps.keys())
                df_grupo = df_filt[df_filt['Representante'].isin(lista_nomes_reps)]
                
                if not df_grupo.empty:
                    st.markdown("### 🏆 Top 10 Clientes (Supervisão)")
                    top_10 = df_grupo.groupby('Cliente')['valor_final'].sum().sort_values(ascending=False).head(10).reset_index()
                    fig = px.bar(top_10, x='valor_final', y='Cliente', orientation='h', text_auto=True, color='valor_final', color_continuous_scale='Greens')
                    fig.update_layout(yaxis=dict(autorange="reversed"), showlegend=False)
                    st.plotly_chart(fig, use_container_width=True)
                    st.divider()

        def render_lista_reps():
            metas_reps = u_data['metas_reps']
            if metas_reps:
                st.markdown("### 📋 Carteira de Clientes (Supervisão)")
                lista_nomes_reps = list(metas_reps.keys())
                df_grupo = df_filt[df_filt['Representante'].isin(lista_nomes_reps)]
                
                with st.expander("🔎 Filtrar Carteira Supervisão", expanded=True):
                    busca = st.text_input("Buscar Cliente (Nome/CNPJ):", key="busca_super")
                    cols_grp = ['Cliente', 'CNPJ', 'Representante'] if 'CNPJ' in df_grupo.columns else ['Cliente', 'Representante']
                    df_lista = df_grupo.groupby(cols_grp)['valor_final'].sum().reset_index().sort_values('valor_final', ascending=False)
                    
                    if busca:
                        termo = busca.upper()
                        mask = df_lista['Cliente'].astype(str).str.upper().str.contains(termo)
                        if 'CNPJ' in df_lista.columns: mask |= df_lista['CNPJ'].astype(str).str.contains(termo)
                        df_lista = df_lista[mask]
                    
                    df_lista['Vendas'] = df_lista['valor_final'].apply(lambda x: f"R$ {x:,.2f}")
                    st.dataframe(df_lista, use_container_width=True, hide_index=True)
                st.divider()

        def render_individual():
            st.markdown(f"### 👤 Performance Individual: {u_logado['nome']}")
            nome_padrao = u_logado['nome'].split()[0]
            nome_busca = st.text_input("Filtrar meu nome na lista (se necessário):", value=nome_padrao)
            
            if col_vend_nome:
                df_user = df_filt[df_filt[col_vend_nome].astype(str).str.contains(nome_busca, case=False, na=False)]
                tot_u = df_user['valor_final'].sum()
                meta_u = float(u_logado['meta'])
                falta_u = max(0, meta_u - tot_u)
                pedidos_user = df_user['id_pedido'].nunique()
                ticket_u = tot_u / pedidos_user if pedidos_user > 0 else 0
                
                ku1, ku2, ku3, ku4 = st.columns(4)
                ku1.metric("Minhas Vendas", f"R$ {tot_u:,.2f}")
                ku2.metric("Minha Meta", f"R$ {meta_u:,.2f}")
                ku3.metric("Falta", f"R$ {falta_u:,.2f}")
                ku4.metric("Ticket Médio", f"R$ {ticket_u:,.2f}")
                barra_progresso_linda(tot_u, meta_u, "Meu Progresso")
                
                # Cache temporário para as próximas funções
                st.session_state['df_user_cache'] = df_user
            st.divider()

        def render_top10_individual():
            if 'df_user_cache' in st.session_state:
                df_user = st.session_state['df_user_cache']
                if not df_user.empty:
                    st.markdown("#### 🏆 Meus Top 10 Clientes")
                    top_10_u = df_user.groupby('Cliente')['valor_final'].sum().sort_values(ascending=False).head(10).reset_index()
                    fig_u = px.bar(top_10_u, x='valor_final', y='Cliente', orientation='h', text_auto=True, color='valor_final', color_continuous_scale='Greens')
                    fig_u.update_layout(yaxis=dict(autorange="reversed"), showlegend=False)
                    st.plotly_chart(fig_u, use_container_width=True)
                    
                    st.markdown("#### 📋 Meus Clientes (Busca)")
                    with st.expander("🔎 Pesquisar Meus Clientes", expanded=True):
                        busca_u = st.text_input("Filtrar meus clientes:", key="busca_user")
                        cols_grp_u = ['Cliente', 'CNPJ'] if 'CNPJ' in df_user.columns else ['Cliente']
                        df_lista_u = df_user.groupby(cols_grp_u)['valor_final'].sum().reset_index().sort_values('valor_final', ascending=False)
                        if busca_u:
                            termo_u = busca_u.upper()
                            mask_u = df_lista_u['Cliente'].astype(str).str.upper().str.contains(termo_u)
                            if 'CNPJ' in df_lista_u.columns: mask_u |= df_lista_u['CNPJ'].astype(str).str.contains(termo_u)
                            df_lista_u = df_lista_u[mask_u]
                        df_lista_u['Vendas'] = df_lista_u['valor_final'].apply(lambda x: f"R$ {x:,.2f}")
                        st.dataframe(df_lista_u, use_container_width=True, hide_index=True)
                    st.divider()

        def render_ranking():
            if col_vend_nome:
                st.markdown("### 🏆 Ranking Geral de Vendedores")
                rank = df_filt.groupby(col_vend_nome)['valor_final'].sum().sort_values(ascending=False).head(10).reset_index()
                fig_r = px.bar(rank, x='valor_final', y=col_vend_nome, orientation='h', text_auto=True)
                fig_r.update_layout(yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig_r, use_container_width=True)
                st.divider()

        def render_evolucao():
            st.markdown("### 📈 Evolução Diária")
            evol = df_filt.groupby('data_final')['valor_final'].sum().reset_index()
            fig_l = px.line(evol, x='data_final', y='valor_final', markers=True)
            st.plotly_chart(fig_l, use_container_width=True)
            st.divider()

        # --- MAPA DE SEÇÕES ---
        mapa_secoes = {
            "Meta MIC (Empresa)": render_meta_mic,
            "Supervisão (Reps)": render_supervisao,
            "Top 10 Clientes (Reps)": render_top10_reps,
            "Lista Clientes (Reps)": render_lista_reps,
            "Performance Individual": render_individual,
            "Meus Top 10 Clientes": render_top10_individual,
            "Ranking Geral": render_ranking,
            "Evolução Diária": render_evolucao
        }

        # --- LOOP DE RENDERIZAÇÃO ---
        layout_usuario = u_data['layout'].split(',') if u_data['layout'] else list(mapa_secoes.keys())
        for secao in layout_usuario:
            if secao in mapa_secoes:
                mapa_secoes[secao]()
                
    else:
        st.error(f"Arquivo '{ARQUIVO_DADOS}' não encontrado.")