import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import plotly.express as px
import os
import json 
from datetime import datetime, date, timedelta
import calendar
import numpy as np
from PIL import Image 
import time

# ==============================================================================
# ⚙️ CONFIGURAÇÕES INICIAIS
# ==============================================================================
st.set_page_config(page_title="Sistema Integrado MIC", layout="wide", page_icon="🏢", initial_sidebar_state="collapsed")

ARQUIVO_DADOS = "lista.csv" 
ARQUIVO_LOGO = "logo.png"

# LINK DA PLANILHA MESTRA (ONDE ESTÃO AS ABAS 'Página1' (Vendas) e 'Expedicao')
# IMPORTANTE: O email do robô (secrets) TEM que ser EDITOR desta planilha.
URL_PLANILHA_MESTRA = "https://docs.google.com/spreadsheets/d/1x6p2koSoPRfs6yB2-8lT9JibgWL1cjlLriq0EnxUlj0/edit?gid=1148960899#gid=1148960899"

# CSS para visual limpo e ajustes
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        [data-testid="stSidebar"] {display: none;}
        .stApp {margin-top: -50px;}
        div[data-testid="column"] {background-color: transparent;}
        div[data-testid="stVerticalBlock"] > div {
            border-radius: 10px;
        }
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
# ☁️ BANCO DE DADOS
# ==============================================================================

conn = st.connection("gsheets", type=GSheetsConnection)

def limpar_dado(dado):
    if pd.isna(dado): return ""
    texto = str(dado).strip()
    if texto.endswith(".0"):
        texto = texto.replace(".0", "")
    return texto

# --- GESTÃO DE USUÁRIOS (Lê do secrets/planilha padrão) ---
def inicializar_e_carregar_usuarios():
    try:
        df = conn.read(ttl=0) 
        colunas_necessarias = ["Login", "Senha", "Meta", "Nome", "Meta_Rep", "Config_Layout", "Cargo"]
        
        if df.empty:
            df_init = pd.DataFrame([
                {"Login": "admin", "Senha": "123", "Meta": 10000.0, "Nome": "Administrador", "Meta_Rep": "{}", "Config_Layout": "", "Cargo": "ADM"},
                {"Login": "__GLOBAL__", "Senha": "***", "Meta": 100000.0, "Nome": "Meta da Empresa", "Meta_Rep": "{}", "Config_Layout": "", "Cargo": ""}
            ])
            conn.update(data=df_init)
            return df_init

        colunas_faltantes = [c for c in colunas_necessarias if c not in df.columns]
        if colunas_faltantes:
            for c in colunas_faltantes:
                valor_padrao = "{}" if "Meta_Rep" in c else ("Vendedor" if c == "Cargo" else "")
                df[c] = valor_padrao
            conn.update(data=df)
        
        return df
    except Exception as e:
        return pd.DataFrame(columns=["Login", "Senha", "Meta", "Nome", "Meta_Rep", "Config_Layout", "Cargo"])

# Carrega Usuários
df_usuarios = inicializar_e_carregar_usuarios()
META_GERAL_EMPRESA = 100000.0
usuarios_dict = {}

if not df_usuarios.empty:
    for index, row in df_usuarios.iterrows():
        login_limpo = limpar_dado(row["Login"])
        if login_limpo == "__GLOBAL__":
            META_GERAL_EMPRESA = float(row["Meta"]) if pd.notnull(row["Meta"]) else 100000.0
        elif login_limpo: 
            meta_rep_raw = row.get("Meta_Rep", "{}")
            try:
                if isinstance(meta_rep_raw, (int, float)): metas_reps_dict = {}
                else:
                    metas_reps_dict = json.loads(str(meta_rep_raw)) if meta_rep_raw else {}
                    if not isinstance(metas_reps_dict, dict): metas_reps_dict = {}
            except: metas_reps_dict = {}

            usuarios_dict[login_limpo] = {
                "senha": limpar_dado(row["Senha"]),
                "meta": float(row["Meta"]) if pd.notnull(row["Meta"]) else 0.0,
                "nome": str(row["Nome"]),
                "cargo": limpar_dado(row.get("Cargo", "Vendedor")),
                "metas_reps": metas_reps_dict, 
                "layout": str(row.get("Config_Layout", ""))
            }

# --- FUNÇÕES DE ATUALIZAÇÃO ---
def salvar_novo_usuario(login, senha, meta, nome):
    try:
        if login == "__GLOBAL__": return False
        novo_dado = pd.DataFrame([{
            "Login": str(login).strip(), "Senha": str(senha).strip(), "Meta": meta, "Nome": nome,
            "Meta_Rep": "{}", "Config_Layout": "", "Cargo": "Vendedor"
        }])
        df_atual = conn.read(ttl=0)
        df_final = pd.concat([df_atual, novo_dado], ignore_index=True)
        # Limpeza de NaN antes de salvar
        df_final = df_final.fillna("")
        conn.update(data=df_final)
        return True
    except: return False

def atualizar_campo(login, campo, novo_valor):
    try:
        df_atual = conn.read(ttl=0)
        df_atual["Login"] = df_atual["Login"].astype(str).str.strip()
        indices = df_atual.index[df_atual["Login"] == str(login).strip()].tolist()
        if indices:
            idx = indices[0]
            if isinstance(novo_valor, dict): novo_valor = json.dumps(novo_valor)
            df_atual.at[idx, campo] = novo_valor
            # Limpeza de NaN antes de salvar
            df_atual = df_atual.fillna("")
            conn.update(data=df_atual)
            return True
        return False
    except: return False

def excluir_usuario(login):
    try:
        df_atual = conn.read(ttl=0)
        df_atual["Login"] = df_atual["Login"].astype(str).str.strip()
        df_nova = df_atual[df_atual["Login"] != str(login).strip()]
        conn.update(data=df_nova)
        return True
    except: return False

# ==============================================================================
# 📦 LÓGICA DA EXPEDIÇÃO (WMS) - COM CORREÇÃO DE NaN
# ==============================================================================

def carregar_dados_expedicao(df_vendas_atual, col_pedido_vendas):
    try:
        df_exp = conn.read(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", ttl=0)
        colunas_exp = ['Pedido', 'Cliente', 'Vendedor', 'Status_Atual', 'Data_Emitido', 'Data_Separacao', 'Data_Separado', 'Data_Faturado', 'Data_Enviado']
        
        # Se vazia ou colunas erradas, recria
        if df_exp.empty or not set(['Pedido', 'Status_Atual']).issubset(df_exp.columns):
            df_exp = pd.DataFrame(columns=colunas_exp)
    except:
        df_exp = pd.DataFrame(columns=['Pedido', 'Cliente', 'Vendedor', 'Status_Atual', 'Data_Emitido', 'Data_Separacao', 'Data_Separado', 'Data_Faturado', 'Data_Enviado'])

    # Sincronização
    if df_vendas_atual is not None and not df_vendas_atual.empty:
        df_exp['Pedido'] = df_exp['Pedido'].astype(str).str.split('.').str[0].str.strip()
        pedidos_exp = set(df_exp['Pedido'].unique())
        
        df_vendas_atual[col_pedido_vendas] = df_vendas_atual[col_pedido_vendas].astype(str).str.split('.').str[0].str.strip()
        pedidos_vendas = set(df_vendas_atual[col_pedido_vendas].unique())
        
        novos = pedidos_vendas - pedidos_exp
        novos = [p for p in novos if p and p.lower() != 'nan' and p != '']
        
        if novos:
            novos_dados = []
            agora = datetime.now().strftime("%d/%m/%Y %H:%M")
            col_cli = next((c for c in df_vendas_atual.columns if 'Cliente' in c), 'Cliente')
            col_vend = next((c for c in df_vendas_atual.columns if 'Vendedor' in c), 'Vendedor')
            
            for p in novos:
                row_venda = df_vendas_atual[df_vendas_atual[col_pedido_vendas] == p].iloc[0]
                novos_dados.append({
                    'Pedido': str(p),
                    'Cliente': str(row_venda.get(col_cli, '')),
                    'Vendedor': str(row_venda.get(col_vend, '')),
                    'Status_Atual': 'Emitido',
                    'Data_Emitido': agora,
                    'Data_Separacao': '', 'Data_Separado': '', 'Data_Faturado': '', 'Data_Enviado': ''
                })
            
            if novos_dados:
                df_novo = pd.DataFrame(novos_dados)
                df_exp = pd.concat([df_exp, df_novo], ignore_index=True)
                
                # --- FIX CRUCIAL: Remove NaN antes de enviar para o Google ---
                df_exp = df_exp.fillna("") 
                
                conn.update(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", data=df_exp)
    
    return df_exp

def atualizar_status_expedicao(pedido, novo_status, coluna_data):
    try:
        df_exp = conn.read(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", ttl=0)
        df_exp['Pedido'] = df_exp['Pedido'].astype(str).str.split('.').str[0].str.strip()
        idx = df_exp.index[df_exp['Pedido'] == str(pedido)].tolist()
        
        if idx:
            i = idx[0]
            agora = datetime.now().strftime("%d/%m/%Y %H:%M")
            df_exp.at[i, 'Status_Atual'] = novo_status
            df_exp.at[i, coluna_data] = agora
            
            # --- FIX CRUCIAL: Remove NaN antes de enviar para o Google ---
            df_exp = df_exp.fillna("")
            
            conn.update(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", data=df_exp)
            return True
        return False
    except Exception as e:
        st.error(f"Erro ao atualizar: {e}")
        return False

# ==============================================================================
# 📥 CARGA DE DADOS VENDAS
# ==============================================================================
def carregar_dados_vendas():
    try:
        # Usa a URL Mestra definida no topo
        # Assumindo que a aba de vendas é a primeira (padrão) ou se chama 'Página1'
        # Se sua aba de vendas tiver outro nome, ajuste aqui
        df = conn.read(spreadsheet=URL_PLANILHA_MESTRA, ttl=0) 
        if df.empty: return None, None, [], None

        df.columns = [c.strip() for c in df.columns]
        cols = df.columns
        
        col_valor = next((c for c in cols if 'Valor' in c or 'Liq' in c), None)
        col_data = next((c for c in cols if 'Gera' in c or 'Data' in c or 'Emis' in c), None)
        col_nf = next((c for c in cols if 'NF' in c or 'Nota' in c), None)
        col_vend = next((c for c in cols if 'Vendedor' in c or 'Vend' in c), None)
        col_rep = next((c for c in cols if 'Representante' in c or 'Rep' in c), None)
        col_cnpj = next((c for c in cols if 'CNPJ' in c or 'CGC' in c), None)
        col_pedido = next((c for c in cols if 'Pedido' in c), None)

        if not col_valor or not col_data: return None, None, [], None

        if df[col_valor].dtype == 'O': 
            df['valor_final'] = df[col_valor].astype(str).str.replace('R$', '', regex=False).str.strip().str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
            df['valor_final'] = pd.to_numeric(df['valor_final'], errors='coerce').fillna(0)
        else: 
            df['valor_final'] = pd.to_numeric(df[col_valor], errors='coerce').fillna(0)

        df['data_final'] = pd.to_datetime(df[col_data], dayfirst=True, errors='coerce')
        
        if col_nf: df['status_ped'] = df[col_nf].apply(lambda x: 'Faturado' if pd.notnull(x) and str(x).strip() != '' else 'A Faturar')
        else: df['status_ped'] = 'Desconhecido'
            
        if col_cnpj: df[col_cnpj] = df[col_cnpj].astype(str)
        if not col_pedido and col_nf: col_pedido = col_nf 
        
        # Garante que id_pedido existe e trata NaN
        if col_pedido:
             df['id_pedido'] = df[col_pedido].fillna(0)
        else:
             df['id_pedido'] = df.index

        lista_reps = sorted(df[col_rep].dropna().unique().tolist()) if col_rep else []

        return df, col_vend, lista_reps, col_pedido 

    except Exception as e:
        print(f"Erro vendas: {e}") 
        return None, None, [], None

# --- VISUAL E UTILITÁRIOS ---
def calcular_dias_uteis_restantes_mes():
    hoje = date.today()
    ultimo = calendar.monthrange(hoje.year, hoje.month)[1]
    fim = date(hoje.year, hoje.month, ultimo)
    if hoje > fim: return 0
    return max(0, int(np.busday_count(hoje, fim + timedelta(days=1))))

def calcular_dias_uteis_passados():
    hoje = date.today()
    inicio = hoje.replace(day=1)
    if hoje == inicio: return 1
    return max(1, int(np.busday_count(inicio, hoje)))

def calcular_curva_abc(df_input):
    if df_input.empty: return df_input
    df_abc = df_input.copy().sort_values('valor_final', ascending=False)
    total = df_abc['valor_final'].sum()
    if total == 0: return df_abc
    df_abc['acumulado'] = df_abc['valor_final'].cumsum()
    df_abc['perc'] = df_abc['acumulado'] / total
    df_abc['Curva'] = df_abc['perc'].apply(lambda p: 'A' if p <= 0.8 else ('B' if p <= 0.95 else 'C'))
    return df_abc

def barra_progresso_linda(atual, meta, titulo="Progresso"):
    pct = (atual / meta * 100) if meta > 0 else 0
    vis = min(pct, 100) 
    grad = "linear-gradient(90deg, #ff4b4b 0%, #ffca28 50%, #21c354 100%)"
    st.markdown(f"""
    <div style="margin-bottom: 20px;">
        <div style="display: flex; justify-content: space-between; align-items: flex-end;">
            <span style="font-weight: bold; font-size: 1.1rem; color: #444;">{titulo}</span>
            <span style="font-weight: bold; font-size: 1.4rem; color: #333;">{pct:.1f}%</span>
        </div>
        <div style="width: 100%; background-color: #e6e6e6; border-radius: 20px; height: 25px;">
            <div style="width: {vis}%; background: {grad}; height: 100%; border-radius: 20px; transition: width 1s ease-in-out;"></div>
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 0.85rem; color: #666; margin-top: 5px;">
            <span>Realizado: R$ {atual:,.2f}</span><span>Meta: R$ {meta:,.2f}</span>
        </div>
    </div>""", unsafe_allow_html=True)

def converter_df_para_csv(df):
    return df.to_csv(index=False, sep=";").encode('utf-8')

# ==============================================================================
# 🎨 RENDERIZAÇÃO
# ==============================================================================

def render_dashboard_vendas(u_data, uid, df, col_vend_nome, lista_reps_disponiveis):
    # Só mostra gestão de metas se for ADM ou tiver permissão especial, ou deixa aberto para todos (user decision)
    # Aqui vou deixar visível para todos customizarem suas visões
    with st.expander("👥 Adicionar / Editar Representantes e Metas", expanded=False):
        c_add1, c_add2, c_add3 = st.columns([2, 1, 1])
        metas_reps = u_data['metas_reps']
        with c_add1:
            rep_opcoes = sorted(lista_reps_disponiveis)
            rep_selecionado = st.selectbox("Escolha o Representante:", [""] + rep_opcoes)
        with c_add2:
            valor_atual = metas_reps.get(rep_selecionado, 0.0) if rep_selecionado else 0.0
            nova_meta_rep = st.number_input("Meta (R$):", value=float(valor_atual))
        with c_add3:
            st.write(""); st.write("")
            c_b1, c_b2 = st.columns(2)
            if c_b1.button("💾", help="Salvar"):
                if rep_selecionado:
                    metas_reps[rep_selecionado] = nova_meta_rep
                    if atualizar_campo(uid, "Meta_Rep", metas_reps): st.success("Salvo!"); st.rerun()
            if c_b2.button("🗑️", help="Remover"):
                if rep_selecionado in metas_reps:
                    del metas_reps[rep_selecionado]
                    if atualizar_campo(uid, "Meta_Rep", metas_reps): st.rerun()

    st.divider()
    
    c1, c2 = st.columns(2)
    status_sel = c1.selectbox("Status", ["Todos", "Faturado", "A Faturar"])
    hoje = date.today()
    ultimo = calendar.monthrange(hoje.year, hoje.month)[1]
    periodo = c2.date_input("Período", [hoje.replace(day=1), date(hoje.year, hoje.month, ultimo)])
    
    df_filt = df.copy()
    if isinstance(periodo, list) and len(periodo) == 2:
        df_filt = df_filt[(df_filt['data_final'].dt.date >= periodo[0]) & (df_filt['data_final'].dt.date <= periodo[1])]
    if status_sel != "Todos":
        df_filt = df_filt[df_filt['status_ped'] == status_sel]
    
    dias_uteis = calcular_dias_uteis_restantes_mes()
    dias_passados = calcular_dias_uteis_passados()

    # --- RENDERIZAÇÃO DOS CARDS ---
    st.markdown("### 🏢 Meta MIC (Empresa)")
    tot = df_filt['valor_final'].sum()
    falta = max(0, META_GERAL_EMPRESA - tot)
    ticket = tot / df_filt['id_pedido'].nunique() if df_filt['id_pedido'].nunique() > 0 else 0
    media_nec = falta / dias_uteis if dias_uteis > 0 else 0
    media_atual = tot / dias_passados if dias_passados > 0 else 0
    delta = media_atual - media_nec
    barra_progresso_linda(tot, META_GERAL_EMPRESA, "Progresso Geral")
    if falta == 0: st.balloons()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Vendas", f"R$ {tot:,.2f}")
    k2.metric("Diária Nec.", f"R$ {media_nec:,.2f}", delta=f"{delta:,.2f}")
    k3.metric("Falta", f"R$ {falta:,.2f}")
    k4.metric("Ticket Médio", f"R$ {ticket:,.2f}")
    st.divider()

    if metas_reps:
        st.markdown("### 🤝 Supervisão de Representantes")
        abas = st.tabs(list(metas_reps.keys()))
        for i, (rep_nome, rep_meta) in enumerate(metas_reps.items()):
            with abas[i]:
                df_rep = df_filt[df_filt['Representante'] == rep_nome]
                tot_rep = df_rep['valor_final'].sum()
                falta_rep = max(0, rep_meta - tot_rep)
                pedidos_rep = df_rep['id_pedido'].nunique()
                ticket_rep = tot_rep / pedidos_rep if pedidos_rep > 0 else 0
                media_diaria_rep = tot_rep / dias_passados if dias_passados > 0 else 0
                media_nec_rep = falta_rep / dias_uteis if dias_uteis > 0 else 0
                delta_rep = media_diaria_rep - media_nec_rep
                
                st.caption(f"Meta: R$ {rep_meta:,.2f}")
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Vendas", f"R$ {tot_rep:,.2f}")
                r2.metric("Falta", f"R$ {falta_rep:,.2f}")
                r3.metric("Diária Nec.", f"R$ {media_nec_rep:,.2f}", delta=f"{delta_rep:,.2f}")
                r4.metric("Ticket", f"R$ {ticket_rep:,.2f}")
                barra_progresso_linda(tot_rep, rep_meta, rep_nome)
                
                st.write("**Top 10 Clientes (Rep):**")
                if not df_rep.empty:
                    top_10 = df_rep.groupby('Cliente')['valor_final'].sum().sort_values(ascending=False).head(10).reset_index()
                    st.plotly_chart(px.bar(top_10, x='valor_final', y='Cliente', orientation='h', text_auto=True), use_container_width=True)

    st.divider()
    st.markdown(f"### 👤 Performance Individual: {u_data['nome']}")
    if col_vend_nome:
        nome_busca = st.text_input("Filtrar meu nome:", value=u_data['nome'].split()[0])
        df_user = df_filt[df_filt[col_vend_nome].astype(str).str.contains(nome_busca, case=False, na=False)]
        tot_u = df_user['valor_final'].sum()
        meta_u = float(u_data['meta'])
        falta_u = max(0, meta_u - tot_u)
        
        ku1, ku2 = st.columns(2)
        ku1.metric("Minhas Vendas", f"R$ {tot_u:,.2f}")
        ku2.metric("Falta", f"R$ {falta_u:,.2f}")
        barra_progresso_linda(tot_u, meta_u, "Meu Progresso")
        
        with st.expander("Meus Clientes"):
            st.dataframe(df_user[['data_final', 'Cliente', 'valor_final', 'status_ped']].sort_values('data_final', ascending=False), use_container_width=True)

def render_expedicao(user_role, df_vendas, col_ped_vendas):
    st.markdown("## 📦 Controle de Expedição")
    
    pode_separar = user_role in ['Expedicao', 'ADM']
    pode_faturar = user_role in ['Vendedor', 'Expedicao', 'ADM']
    pode_enviar = user_role in ['Expedicao', 'ADM']

    with st.spinner("Sincronizando WMS..."):
        df_exp = carregar_dados_expedicao(df_vendas, col_ped_vendas)

    c_f1, c_f2 = st.columns([3, 1])
    termo = c_f1.text_input("🔎 Buscar Pedido, Cliente ou Vendedor")
    status_view = c_f2.multiselect("Status", df_exp['Status_Atual'].unique(), default=df_exp['Status_Atual'].unique())
    
    df_view = df_exp[df_exp['Status_Atual'].isin(status_view)]
    if termo:
        t = termo.lower()
        df_view = df_view[
            df_view['Pedido'].str.lower().str.contains(t) | 
            df_view['Cliente'].str.lower().str.contains(t) |
            df_view['Vendedor'].str.lower().str.contains(t)
        ]
    
    df_view = df_view.iloc[::-1] # Recentes primeiro

    st.divider()
    
    for i, row in df_view.iterrows():
        status = row['Status_Atual']
        ped = row['Pedido']
        cor = "gray"
        if status == "Emitido": cor = "blue"
        elif status == "Em Separação": cor = "orange"
        elif status == "Separado": cor = "purple"
        elif status == "Faturado": cor = "teal"
        elif status == "Enviado": cor = "green"
        
        with st.container():
            c1, c2, c3, c4 = st.columns([1.5, 2.5, 3, 2])
            with c1:
                st.markdown(f"### 📦 {ped}")
                st.caption(f"Vend: {row['Vendedor']}")
            with c2:
                st.markdown(f"**{row['Cliente']}**")
                st.markdown(f":{cor}[● {status}]")
            with c3:
                txt_time = ""
                if row['Data_Emitido']: txt_time += f"📅 {row['Data_Emitido']} "
                if row['Data_Separado']: txt_time += f"📦 {row['Data_Separado']} "
                if row['Data_Enviado']: txt_time += f"🚚 {row['Data_Enviado']}"
                st.caption(txt_time)
            with c4:
                if status == "Emitido":
                    if pode_separar:
                        if st.button("▶️ Separar", key=f"s1_{ped}"):
                            atualizar_status_expedicao(ped, "Em Separação", "Data_Separacao"); st.rerun()
                    else: st.info("Aguardando Estoque")
                elif status == "Em Separação":
                    if pode_separar:
                        if st.button("✅ Finalizar", key=f"s2_{ped}"):
                            atualizar_status_expedicao(ped, "Separado", "Data_Separado"); st.rerun()
                    else: st.warning("Em separação...")
                elif status == "Separado":
                    if pode_faturar:
                        if st.button("💲 Faturar", key=f"s3_{ped}"):
                            atualizar_status_expedicao(ped, "Faturado", "Data_Faturado"); st.rerun()
                elif status == "Faturado":
                    if pode_enviar:
                        if st.button("🚚 Enviar", key=f"s4_{ped}"):
                            atualizar_status_expedicao(ped, "Enviado", "Data_Enviado"); st.rerun()
                    else: st.success("Pronto p/ Envio")
                elif status == "Enviado":
                    st.success("Concluído")
            st.markdown("---")

# ==============================================================================
# 🏁 FLUXO PRINCIPAL
# ==============================================================================

if 'usuario_logado' not in st.session_state: st.session_state['usuario_logado'] = None
df, col_vend, lista_reps, col_ped = carregar_dados_vendas()

if st.session_state['usuario_logado'] is None:
    c1, c2, c3 = st.columns([3, 2, 3])
    with c2:
        st.write(""); st.write("")
        if os.path.exists(ARQUIVO_LOGO):
            img = carregar_imagem_segura(ARQUIVO_LOGO)
            if img: st.image(img, use_container_width=True)
        else: st.title("MIC System")
        t1, t2 = st.tabs(["Entrar", "Criar Conta"])
        with t1:
            u = st.text_input("Usuário").strip()
            p = st.text_input("Senha", type="password").strip()
            if st.button("Acessar", use_container_width=True):
                if u in usuarios_dict and usuarios_dict[u]['senha'] == p:
                    st.session_state['usuario_logado'] = u; st.rerun()
                else: st.error("Negado.")
            if st.button("🔄", help="Atualizar"): st.cache_data.clear(); st.rerun()
        with t2:
            nu = st.text_input("Novo Usuário").strip()
            np_ = st.text_input("Nova Senha", type="password").strip()
            nn = st.text_input("Nome")
            if st.button("Cadastrar", use_container_width=True):
                if nu and np_ and nu != "__GLOBAL__":
                    if nu not in usuarios_dict:
                        if salvar_novo_usuario(nu, np_, 10000.0, nn): st.success("OK! Logue."); 
                    else: st.error("Existe.")
else:
    uid = st.session_state['usuario_logado']
    if uid not in usuarios_dict: st.session_state['usuario_logado'] = None; st.rerun()
    u_data = usuarios_dict[uid]
    cargo = u_data['cargo']

    h1, h2 = st.columns([6, 1])
    with h1:
        if os.path.exists(ARQUIVO_LOGO):
            img = carregar_imagem_segura(ARQUIVO_LOGO)
            if img: st.image(img, width=120)
        else: st.title("MIC")
    with h2:
        st.write("")
        with st.popover("⚙️", use_container_width=True):
            st.markdown(f"**{u_data['nome']}**")
            st.caption(f"Cargo: {cargo}")
            if cargo == "ADM":
                with st.expander("👑 Admin: Alterar Cargos"):
                    usr_edit = st.selectbox("Usuário:", list(usuarios_dict.keys()))
                    cargo_edit = st.selectbox("Novo Cargo:", ["Vendedor", "Expedicao", "ADM"])
                    if st.button("Alterar Cargo"):
                        if atualizar_campo(usr_edit, "Cargo", cargo_edit): st.success("Atualizado!"); st.rerun()
            st.markdown("---")
            n_nome = st.text_input("Nome:", value=u_data['nome'])
            if st.button("Salvar Nome"): atualizar_campo(uid, "Nome", n_nome); st.rerun()
            n_senha = st.text_input("Nova Senha", type="password")
            if st.button("Salvar Senha"): atualizar_campo(uid, "Senha", n_senha); st.rerun()
            st.markdown("---")
            if st.button("Sair"): st.session_state['usuario_logado'] = None; st.rerun()

    if cargo == "Expedicao":
        render_expedicao(cargo, df, col_ped)
    else:
        tab_vendas, tab_exp = st.tabs(["📊 Dashboard Vendas", "📦 Expedição (WMS)"])
        with tab_vendas:
            render_dashboard_vendas(u_data, uid, df, col_vend, lista_reps)
        with tab_exp:
            render_expedicao(cargo, df, col_ped)