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
import pytz 
import time

# ==============================================================================
# ⚙️ CONFIGURAÇÕES INICIAIS
# ==============================================================================
st.set_page_config(page_title="Sistema Integrado MIC", layout="wide", page_icon="🏢", initial_sidebar_state="collapsed")

ARQUIVO_LOGO = "logo.png"
FUSO_SP = pytz.timezone('America/Sao_Paulo')

# URL DA PLANILHA MESTRA
URL_PLANILHA_MESTRA = "https://docs.google.com/spreadsheets/d/1x6p2koSoPRfs6yB2-8lT9JibgWL1cjlLriq0EnxUlj0/edit?gid=1148960899#gid=1148960899"

st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        [data-testid="stSidebar"] {display: none;}
        .stApp {margin-top: -50px;}
        div[data-testid="column"] {background-color: transparent;}
        div[data-testid="stVerticalBlock"] > div {
            border-radius: 10px;
            padding: 5px;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.5rem !important;
        }
    </style>
""", unsafe_allow_html=True)

def carregar_imagem_segura(caminho_imagem):
    try:
        img = Image.open(caminho_imagem)
        return img
    except: return None

# ==============================================================================
# ☁️ BANCO DE DADOS (COM CACHE INTELIGENTE)
# ==============================================================================

conn = st.connection("gsheets", type=GSheetsConnection)

def get_data_hora_sp():
    return datetime.now(FUSO_SP).strftime("%d/%m/%Y %H:%M")

def limpar_dado(dado):
    if pd.isna(dado): return ""
    return str(dado).strip().replace(".0", "")

# --- CARGA DE VENDAS (CACHEADO POR 10 MINUTOS) ---
@st.cache_data(ttl=600) 
def carregar_dados_vendas_cache():
    try:
        df = conn.read(spreadsheet=URL_PLANILHA_MESTRA, ttl=600) 
        if df.empty: return None
        return df
    except Exception as e:
        print(f"Erro Cache Vendas: {e}")
        return None

# --- GESTÃO DE USUÁRIOS ---
def inicializar_e_carregar_usuarios():
    try:
        df = conn.read(ttl=60)
        colunas_necessarias = ["Login", "Senha", "Meta", "Nome", "Meta_Rep", "Config_Layout", "Cargo"]
        if df.empty: return pd.DataFrame(columns=colunas_necessarias)
        
        changed = False
        for c in colunas_necessarias:
            if c not in df.columns:
                df[c] = "{}" if "Meta" in c else ""
                changed = True
        if changed: conn.update(data=df)
        return df
    except: return pd.DataFrame(columns=["Login", "Senha", "Meta", "Nome", "Meta_Rep", "Config_Layout", "Cargo"])

df_usuarios = inicializar_e_carregar_usuarios()
META_GERAL_EMPRESA = 100000.0
usuarios_dict = {}

if not df_usuarios.empty:
    for index, row in df_usuarios.iterrows():
        login = limpar_dado(row["Login"])
        if login == "__GLOBAL__":
            META_GERAL_EMPRESA = float(row["Meta"]) if pd.notnull(row["Meta"]) else 100000.0
        elif login: 
            meta_rep_raw = row.get("Meta_Rep", "{}")
            try: metas_reps_dict = json.loads(str(meta_rep_raw)) if meta_rep_raw else {}
            except: metas_reps_dict = {}
            if not isinstance(metas_reps_dict, dict): metas_reps_dict = {}

            usuarios_dict[login] = {
                "senha": limpar_dado(row["Senha"]),
                "meta": float(row["Meta"]) if pd.notnull(row["Meta"]) else 0.0,
                "nome": str(row["Nome"]),
                "cargo": limpar_dado(row.get("Cargo", "Vendedor")),
                "metas_reps": metas_reps_dict, 
                "layout": str(row.get("Config_Layout", ""))
            }

def atualizar_campo(login, campo, novo_valor):
    try:
        df = conn.read(ttl=0)
        df["Login"] = df["Login"].astype(str).str.strip()
        idx = df.index[df["Login"] == str(login).strip()].tolist()
        if idx:
            if isinstance(novo_valor, dict): novo_valor = json.dumps(novo_valor)
            df.at[idx[0], campo] = novo_valor
            conn.update(data=df.fillna(""))
            return True
        return False
    except: return False

def salvar_novo_usuario(login, senha, meta, nome):
    try:
        if login == "__GLOBAL__": return False
        df = conn.read(ttl=0)
        novo = pd.DataFrame([{"Login": login, "Senha": senha, "Meta": meta, "Nome": nome, "Meta_Rep": "{}", "Config_Layout": "", "Cargo": "Vendedor"}])
        conn.update(data=pd.concat([df, novo], ignore_index=True).fillna(""))
        return True
    except: return False

def excluir_usuario(login):
    try:
        df = conn.read(ttl=0)
        df = df[df["Login"].astype(str).str.strip() != str(login).strip()]
        conn.update(data=df)
        return True
    except: return False

# ==============================================================================
# 📦 LÓGICA DA EXPEDIÇÃO (WMS)
# ==============================================================================

def carregar_dados_expedicao(df_vendas_atual, col_pedido_vendas, col_nf_vendas):
    cols_exp = ['Pedido', 'Cliente', 'Vendedor', 'Status_Atual', 
                'Data_Emitido', 'Data_Separacao', 'Data_Separado', 'Data_Faturado', 'Data_Enviado',
                'User_Separacao', 'User_Separado', 'User_Faturado', 'User_Enviado', 'Log_Historico']
    
    try:
        df_exp = conn.read(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", ttl=5)
        if df_exp.empty or not set(['Pedido']).issubset(df_exp.columns):
            df_exp = pd.DataFrame(columns=cols_exp)
        else:
            for c in cols_exp:
                if c not in df_exp.columns: df_exp[c] = ""
            df_exp = df_exp.astype(str)
    except:
        df_exp = pd.DataFrame(columns=cols_exp)

    # SINCRONIZAÇÃO
    if df_vendas_atual is not None and not df_vendas_atual.empty:
        df_exp['Pedido'] = df_exp['Pedido'].str.split('.').str[0].str.strip()
        df_vendas_atual[col_pedido_vendas] = df_vendas_atual[col_pedido_vendas].astype(str).str.split('.').str[0].str.strip()
        
        pedidos_exp = set(df_exp['Pedido'].unique())
        pedidos_vendas = set(df_vendas_atual[col_pedido_vendas].unique())
        novos = [p for p in (pedidos_vendas - pedidos_exp) if p and p.lower() != 'nan' and p != '']
        
        mudou_algo = False
        
        if novos:
            novos_dados = []
            agora = get_data_hora_sp()
            col_cli = next((c for c in df_vendas_atual.columns if 'Cliente' in c), 'Cliente')
            col_vend = next((c for c in df_vendas_atual.columns if 'Vendedor' in c), 'Vendedor')
            
            for p in novos:
                try:
                    row_venda = df_vendas_atual[df_vendas_atual[col_pedido_vendas] == p].iloc[0]
                    tem_nf = False
                    if col_nf_vendas:
                        nf_val = str(row_venda.get(col_nf_vendas, '')).strip()
                        tem_nf = nf_val and nf_val.lower() != 'nan'
                    
                    status_ini = 'Faturado' if tem_nf else 'Emitido'
                    data_fat = agora if tem_nf else ''
                    log_ini = f"[{agora}] Pedido importado como {status_ini}"

                    novos_dados.append({
                        'Pedido': str(p),
                        'Cliente': str(row_venda.get(col_cli, '')),
                        'Vendedor': str(row_venda.get(col_vend, '')),
                        'Status_Atual': status_ini,
                        'Data_Emitido': agora,
                        'Data_Separacao': '', 'Data_Separado': '', 
                        'Data_Faturado': data_fat, 'Data_Enviado': '',
                        'User_Separacao': '', 'User_Separado': '', 'User_Faturado': 'Sistema' if tem_nf else '', 'User_Enviado': '',
                        'Log_Historico': log_ini
                    })
                except: continue
            
            if novos_dados:
                df_novo = pd.DataFrame(novos_dados)
                df_exp = pd.concat([df_exp, df_novo], ignore_index=True)
                mudou_algo = True

        if col_nf_vendas:
            vendas_com_nf = df_vendas_atual[df_vendas_atual[col_nf_vendas].notna() & (df_vendas_atual[col_nf_vendas].astype(str).str.strip() != '')]
            lista_pedidos_com_nf = set(vendas_com_nf[col_pedido_vendas].unique())
            
            for i, row in df_exp.iterrows():
                ped = row['Pedido']
                status = row['Status_Atual']
                if ped in lista_pedidos_com_nf and status in ['Emitido', 'Em Separação', 'Separado']:
                    agora = get_data_hora_sp()
                    df_exp.at[i, 'Status_Atual'] = 'Faturado'
                    if not df_exp.at[i, 'Data_Faturado']: df_exp.at[i, 'Data_Faturado'] = agora
                    df_exp.at[i, 'User_Faturado'] = 'Sistema (Auto)'
                    df_exp.at[i, 'Log_Historico'] = str(row.get('Log_Historico','')) + f" | [{agora}] Auto-Faturado por NF detectada"
                    mudou_algo = True

        if mudou_algo:
            try:
                conn.update(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", data=df_exp.fillna(""))
            except Exception as e:
                st.warning(f"Aviso: Não foi possível sincronizar o WMS agora (Limite API). Tente em instantes.")
    
    return df_exp

def atualizar_status_expedicao(pedido, novo_status, coluna_data, coluna_user, usuario_nome, log_msg):
    try:
        df_exp = conn.read(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", ttl=0)
        df_exp['Pedido'] = df_exp['Pedido'].astype(str).str.split('.').str[0].str.strip()
        idx = df_exp.index[df_exp['Pedido'] == str(pedido)].tolist()
        
        if idx:
            i = idx[0]
            agora = get_data_hora_sp()
            df_exp.at[i, 'Status_Atual'] = novo_status
            if coluna_data: df_exp.at[i, coluna_data] = agora
            if coluna_user: df_exp.at[i, coluna_user] = usuario_nome
            
            log_antigo = str(df_exp.at[i, 'Log_Historico']) if pd.notnull(df_exp.at[i, 'Log_Historico']) else ""
            if log_antigo == "nan": log_antigo = ""
            
            novo_log = f" | [{agora} - {usuario_nome}] {log_msg}"
            df_exp.at[i, 'Log_Historico'] = log_antigo + novo_log
            
            conn.update(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", data=df_exp.fillna(""))
            return True
        return False
    except Exception as e:
        st.error(f"Erro ao atualizar: {e}")
        return False

# ==============================================================================
# 📥 PROCESSAMENTO DE DADOS VENDAS
# ==============================================================================
def processar_dados_vendas(df):
    if df is None or df.empty: return None, None, [], None, None

    try:
        df.columns = [c.strip() for c in df.columns]
        cols = df.columns
        
        col_valor = next((c for c in cols if 'Valor' in c or 'Liq' in c), None)
        col_data = next((c for c in cols if 'Gera' in c or 'Data' in c or 'Emis' in c), None)
        col_nf = next((c for c in cols if 'NF' in c or 'Nota' in c), None)
        col_vend = next((c for c in cols if 'Vendedor' in c or 'Vend' in c), None)
        col_rep = next((c for c in cols if 'Representante' in c or 'Rep' in c), None)
        col_cnpj = next((c for c in cols if 'CNPJ' in c or 'CGC' in c), None)
        col_pedido = next((c for c in cols if 'Pedido' in c), None)

        if not col_valor or not col_data: return None, None, [], None, None

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
        
        df['id_pedido'] = df[col_pedido].fillna(0) if col_pedido else df.index
        lista_reps = sorted(df[col_rep].dropna().unique().tolist()) if col_rep else []

        return df, col_vend, lista_reps, col_pedido, col_nf

    except Exception as e:
        print(f"Erro processamento vendas: {e}") 
        return None, None, [], None, None

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
    st.markdown(f"""<div style="margin-bottom: 20px; font-family: sans-serif;"><div style="display: flex; justify-content: space-between; margin-bottom: 5px; align-items: flex-end;"><span style="font-weight: bold; font-size: 1.1rem; color: #444;">{titulo}</span><span style="font-weight: bold; font-size: 1.4rem; color: #333;">{pct:.1f}%</span></div><div style="width: 100%; background-color: #e6e6e6; border-radius: 20px; height: 25px; box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);"><div style="width: {vis}%; background: {grad}; height: 100%; border-radius: 20px; transition: width 1s ease-in-out; box-shadow: 2px 0 5px rgba(0,0,0,0.2);"></div></div><div style="display: flex; justify-content: space-between; font-size: 0.85rem; color: #666; margin-top: 5px;"><span>Realizado: R$ {atual:,.2f}</span><span>Meta: R$ {meta:,.2f}</span></div></div>""", unsafe_allow_html=True)

def converter_df_para_csv(df):
    return df.to_csv(index=False, sep=";").encode('utf-8')

def render_bolinhas_status(status):
    mapa = {
        'Emitido':      ['🔵','⚪','⚪','⚪','⚪'],
        'Em Separação': ['🔵','🟠','⚪','⚪','⚪'],
        'Separado':     ['🔵','🟠','🟣','⚪','⚪'],
        'Faturado':     ['🔵','🟠','🟣','🟤','⚪'],
        'Enviado':      ['🔵','🟠','🟣','🟤','🟢']
    }
    bolas = mapa.get(status, ['⚪','⚪','⚪','⚪','⚪'])
    return " ".join(bolas)

# ==============================================================================
# 🎨 RENDERIZAÇÃO
# ==============================================================================

def render_dashboard_vendas(u_data, uid, df, col_vend_nome, lista_reps_disponiveis):
    if df is None:
        st.error("⚠️ Dados indisponíveis no momento (Limite API Google). Tente recarregar em 1 minuto.")
        return

    layout_padrao = ["Meta MIC (Empresa)", "Supervisão (Reps)", "Top 10 Clientes (Reps)", "Lista Clientes (Reps)", "Performance Individual", "Meus Top 10 Clientes", "Ranking Geral", "Evolução Diária"]
    layout_user = u_data.get('layout', '').split(',')
    layout_user = [l for l in layout_user if l] if layout_user else layout_padrao

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
    status_sel = c1.selectbox("Status", ["Todos", "Faturado", "A Faturar"], key="filtro_status_dashboard")
    
    hoje = date.today()
    ultimo = calendar.monthrange(hoje.year, hoje.month)[1]
    
    periodo = c2.date_input(
        "Período", 
        [hoje.replace(day=1), date(hoje.year, hoje.month, ultimo)], 
        format="DD/MM/YYYY", 
        key="data_input_dashboard" 
    )
    
    df_filt = df.copy()
    
    # 🩹 CORREÇÃO DO ERRO TYPE ERROR (DATA): NORMALIZAR PARA TIMESTAMP PANDAS
    if isinstance(periodo, list) and len(periodo) == 2:
        inicio = pd.to_datetime(periodo[0])
        fim = pd.to_datetime(periodo[1])
        # Filtra convertendo a coluna para normalizada (00:00:00)
        df_filt = df_filt[
            (df_filt['data_final'].dt.normalize() >= inicio) & 
            (df_filt['data_final'].dt.normalize() <= fim)
        ]
    elif isinstance(periodo, list) and len(periodo) == 1:
        inicio = pd.to_datetime(periodo[0])
        df_filt = df_filt[df_filt['data_final'].dt.normalize() >= inicio]

    if status_sel != "Todos":
        df_filt = df_filt[df_filt['status_ped'] == status_sel]
    
    dias_uteis = calcular_dias_uteis_restantes_mes()
    dias_passados = calcular_dias_uteis_passados()

    def render_meta_mic():
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
        k1.metric("Vendas Totais", f"R$ {tot:,.2f}")
        k2.metric("Diária Nec.", f"R$ {media_nec:,.2f}", delta=f"{delta:,.2f}")
        k3.metric("Falta", f"R$ {falta:,.2f}")
        k4.metric("Ticket Médio", f"R$ {ticket:,.2f}")
        st.divider()

    def render_supervisao():
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
                    
                    st.caption(f"Meta Definida: R$ {rep_meta:,.2f}")
                    r1, r2, r3, r4 = st.columns(4)
                    r1.metric("Vendas", f"R$ {tot_rep:,.2f}")
                    r2.metric("Falta", f"R$ {falta_rep:,.2f}")
                    r3.metric("Diária Nec.", f"R$ {media_nec_rep:,.2f}", delta=f"{delta_rep:,.2f}")
                    r4.metric("Ticket", f"R$ {ticket_rep:,.2f}")
                    barra_progresso_linda(tot_rep, rep_meta, f"Progresso {rep_nome}")
                    if falta_rep == 0: st.balloons()

                    csv = converter_df_para_csv(df_rep)
                    st.download_button(f"📥 Baixar Relatório de {rep_nome}", csv, f"Relatorio_{rep_nome}.csv", "text/csv")
                    st.divider()

    def render_top10_reps():
        if metas_reps:
            lista_reps = list(metas_reps.keys())
            df_grupo = df_filt[df_filt['Representante'].isin(lista_reps)]
            if not df_grupo.empty:
                st.markdown("### 🏆 Top 10 Clientes (Supervisão)")
                top_10 = df_grupo.groupby('Cliente')['valor_final'].sum().sort_values(ascending=False).head(10).sort_values(ascending=True).reset_index()
                fig = px.bar(top_10, x='valor_final', y='Cliente', orientation='h', text_auto=True, color='valor_final', color_continuous_scale='Greens')
                fig.update_layout(showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
            st.divider()

    def render_lista_clientes_reps():
        if metas_reps:
            st.markdown("### 📋 Carteira (Grupo)")
            lista_reps = list(metas_reps.keys())
            df_grupo = df_filt[df_filt['Representante'].isin(lista_reps)]
            with st.expander("🔎 Filtrar Carteira", expanded=False):
                busca = st.text_input("Buscar:", key="b_sup")
                df_abc = calcular_curva_abc(df_grupo.groupby(['Cliente', 'CNPJ'])['valor_final'].sum().reset_index())
                if busca:
                    df_abc = df_abc[df_abc['Cliente'].str.contains(busca, case=False)]
                df_abc['Vendas'] = df_abc['valor_final'].apply(lambda x: f"R$ {x:,.2f}")
                st.dataframe(df_abc[['Curva', 'Cliente', 'CNPJ', 'Vendas']], use_container_width=True)
            st.divider()

    def render_individual():
        st.markdown(f"### 👤 Performance Individual: {u_data['nome']}")
        if col_vend_nome:
            nome_busca = st.text_input("Filtrar meu nome:", value=u_data['nome'].split()[0])
            df_user = df_filt[df_filt[col_vend_nome].astype(str).str.contains(nome_busca, case=False, na=False)]
            tot_u = df_user['valor_final'].sum()
            meta_u = float(u_data['meta'])
            falta_u = max(0, meta_u - tot_u)
            
            pedidos_u = df_user['id_pedido'].nunique()
            ticket_u = tot_u / pedidos_u if pedidos_u > 0 else 0
            
            media_atual_u = tot_u / dias_passados if dias_passados > 0 else 0
            media_nec_u = falta_u / dias_uteis if dias_uteis > 0 else 0
            delta_u = media_atual_u - media_nec_u

            ku1, ku2, ku3, ku4 = st.columns(4)
            ku1.metric("Minhas Vendas", f"R$ {tot_u:,.2f}")
            ku2.metric("Falta", f"R$ {falta_u:,.2f}")
            ku3.metric("Diária Nec.", f"R$ {media_nec_u:,.2f}", delta=f"{delta_u:,.2f}")
            ku4.metric("Ticket Médio", f"R$ {ticket_u:,.2f}")
            
            barra_progresso_linda(tot_u, meta_u, "Meu Progresso")
            st.session_state['df_user_cache'] = df_user 
            st.divider()

    def render_meus_top10():
        if 'df_user_cache' in st.session_state and not st.session_state['df_user_cache'].empty:
            st.write("**Meus Top 10:**")
            df_u = st.session_state['df_user_cache']
            top_10 = df_u.groupby('Cliente')['valor_final'].sum().sort_values(ascending=False).head(10).sort_values(ascending=True).reset_index()
            fig = px.bar(top_10, x='valor_final', y='Cliente', orientation='h', text_auto=True, color='valor_final', color_continuous_scale='Greens')
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
            st.divider()

    def render_ranking():
        if col_vend_nome:
            st.markdown("### 🏆 Ranking Geral")
            rank = df_filt.groupby(col_vend_nome)['valor_final'].sum().sort_values(ascending=False).head(10).sort_values(ascending=True).reset_index()
            st.plotly_chart(px.bar(rank, x='valor_final', y=col_vend_nome, orientation='h', text_auto=True), use_container_width=True)
            st.divider()

    def render_evolucao():
        st.markdown("### 📈 Evolução Diária")
        df_ev = df_filt.copy()
        
        # Garante que a coluna seja data e remove NaTs (Erros de conversão)
        df_ev['data_final'] = pd.to_datetime(df_ev['data_final'], errors='coerce')
        df_ev = df_ev.dropna(subset=['data_final'])
        
        if not df_ev.empty:
            evol = df_ev.groupby(df_ev['data_final'].dt.normalize())['valor_final'].sum().reset_index()
            evol.columns = ['Data', 'Valor'] 
            evol = evol.sort_values('Data')
            
            fig = px.line(evol, x='Data', y='Valor', markers=True, text='Valor')
            fig.update_traces(textposition="top center", texttemplate='R$ %{y:.2s}')
            fig.update_layout(xaxis_tickformat='%d/%m')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sem dados válidos para o período selecionado.")
        st.divider()

    mapa = {
        "Meta MIC (Empresa)": render_meta_mic,
        "Supervisão (Reps)": render_supervisao,
        "Top 10 Clientes (Reps)": render_top10_reps,
        "Lista Clientes (Reps)": render_lista_clientes_reps,
        "Performance Individual": render_individual,
        "Meus Top 10 Clientes": render_meus_top10,
        "Ranking Geral": render_ranking,
        "Evolução Diária": render_evolucao
    }

    for item in layout_user:
        if item in mapa: mapa[item]()

# ==============================================================================
# 📦 RENDERIZAÇÃO EXPEDIÇÃO
# ==============================================================================

def render_expedicao(user_role, user_name, df_vendas, col_ped_vendas, col_nf_vendas):
    st.markdown("## 📦 Controle de Expedição")
    
    pode_separar = user_role in ['Expedicao', 'ADM']
    pode_faturar = user_role in ['Vendedor', 'Expedicao', 'ADM']
    pode_enviar = user_role in ['Expedicao', 'ADM']
    pode_voltar = user_role in ['ADM', 'Expedicao'] 

    with st.spinner("Sincronizando WMS..."):
        df_exp = carregar_dados_expedicao(df_vendas, col_ped_vendas, col_nf_vendas)

    c_date1, c_date2 = st.columns([1, 2])
    with c_date1:
        st.caption("Filtrar por Data de Emissão")
        hoje = date.today()
        ultimo = calendar.monthrange(hoje.year, hoje.month)[1]
        
        data_filtro = st.date_input(
            "Período", 
            [hoje.replace(day=1), date(hoje.year, hoje.month, ultimo)], 
            format="DD/MM/YYYY", 
            key="data_input_expedicao"
        )

    # 🩹 CORREÇÃO DO ERRO TYPE ERROR (DATA) NA EXPEDIÇÃO TAMBÉM
    if isinstance(data_filtro, list) and len(data_filtro) == 2:
        df_exp['dt_obj'] = pd.to_datetime(df_exp['Data_Emitido'], dayfirst=True, errors='coerce').dt.normalize()
        inicio = pd.to_datetime(data_filtro[0])
        fim = pd.to_datetime(data_filtro[1])
        df_exp = df_exp[(df_exp['dt_obj'] >= inicio) & (df_exp['dt_obj'] <= fim)]

    # --- KPI: MÉTRICAS ---
    qtd_emitidos = len(df_exp[df_exp['Status_Atual'] == 'Emitido'])
    qtd_separacao = len(df_exp[df_exp['Status_Atual'] == 'Em Separação'])
    qtd_separados = len(df_exp[df_exp['Status_Atual'] == 'Separado']) # Para Faturar
    qtd_faturados = len(df_exp[df_exp['Status_Atual'] == 'Faturado']) # Aguardando Envio
    qtd_finalizados = len(df_exp[df_exp['Status_Atual'] == 'Enviado']) # Finalizados

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("🆕 Aguardando", qtd_emitidos)
    k2.metric("🖐️ Em Separação", qtd_separacao)
    k3.metric("💲 Para Faturar", qtd_separados)
    k4.metric("🧾 Faturados", qtd_faturados)
    k5.metric("🚚 Finalizados", qtd_finalizados)
    
    st.divider()

    c_f1, c_f2 = st.columns([3, 1])
    termo = c_f1.text_input("🔎 Buscar Pedido, Cliente ou Vendedor")
    
    opcoes_filtro = [
        "Todos",
        "🆕 Aguardando (Emitidos)",
        "🖐️ Em Separação",
        "💲 Para Faturar (Separados)",
        "🧾 Faturado (Aguardando envio)",
        "🚚 Finalizados (Enviados)"
    ]
    
    filtro_status_display = c_f2.selectbox("Filtrar Status", opcoes_filtro)
    
    map_display_to_db = {
        "🆕 Aguardando (Emitidos)": "Emitido",
        "🖐️ Em Separação": "Em Separação",
        "💲 Para Faturar (Separados)": "Separado",
        "🧾 Faturado (Aguardando envio)": "Faturado",
        "🚚 Finalizados (Enviados)": "Enviado"
    }

    mask_status = [True] * len(df_exp)
    if filtro_status_display != "Todos":
        status_interno = map_display_to_db.get(filtro_status_display)
        mask_status = df_exp['Status_Atual'] == status_interno
    
    df_view = df_exp[mask_status]

    if termo:
        t = termo.lower()
        df_view = df_view[
            df_view['Pedido'].astype(str).str.lower().str.contains(t) | 
            df_view['Cliente'].astype(str).str.lower().str.contains(t) |
            df_view['Vendedor'].astype(str).str.lower().str.contains(t)
        ]
    
    df_view = df_view.iloc[::-1]

    st.divider()
    
    for i, row in df_view.iterrows():
        status = row['Status_Atual']
        ped = row['Pedido']
        bolinhas = render_bolinhas_status(status)
        
        with st.container():
            c1, c2, c3, c4 = st.columns([1.5, 3, 2.5, 2])
            with c1:
                st.markdown(f"### 📦 {ped}")
                st.caption(f"Vend: {row['Vendedor']}")
            with c2:
                st.markdown(f"**{row['Cliente']}**")
                st.write(f"{bolinhas} **{status}**")
            with c3:
                txt_time = ""
                if row['Data_Emitido']: txt_time += f"📅 Emit: {row['Data_Emitido']}\n"
                if row['Data_Separado']: txt_time += f"📦 Sep: {row['Data_Separado']} ({row['User_Separado']})\n"
                if row['Data_Faturado']: txt_time += f"💲 Fat: {row['Data_Faturado']} ({row['User_Faturado']})\n"
                if row['Data_Enviado']: txt_time += f"🚚 Env: {row['Data_Enviado']} ({row['User_Enviado']})"
                st.caption(txt_time)
                
                log_txt = str(row['Log_Historico']) if pd.notnull(row['Log_Historico']) else ""
                if log_txt:
                    with st.popover("📜 Ver Histórico"):
                        st.text(log_txt.replace(" | ", "\n"))

            with c4:
                if status == "Emitido":
                    if pode_separar:
                        if st.button("▶️ Separar", key=f"s1_{ped}"):
                            atualizar_status_expedicao(ped, "Em Separação", "Data_Separacao", "User_Separacao", user_name, "Iniciou Separação"); st.rerun()
                    else: st.info("Aguardando Estoque")
                
                elif status == "Em Separação":
                    if pode_separar:
                        if st.button("✅ Finalizar Sep.", key=f"s2_{ped}"):
                            atualizar_status_expedicao(ped, "Separado", "Data_Separado", "User_Separado", user_name, "Finalizou Separação (Pronto p/ Faturar)"); st.rerun()
                        if pode_voltar and st.button("↩️ Voltar", key=f"v1_{ped}"):
                             atualizar_status_expedicao(ped, "Emitido", "", "", user_name, "Voltou para Emitido"); st.rerun()
                    else: st.warning("Separando...")
                
                elif status == "Separado": 
                    if pode_faturar:
                        if st.button("💲 Marcar Faturado", key=f"s3_{ped}"):
                            atualizar_status_expedicao(ped, "Faturado", "Data_Faturado", "User_Faturado", user_name, "Faturou (Aguardando Envio)"); st.rerun()
                    if pode_voltar and st.button("↩️ Voltar Sep.", key=f"v2_{ped}"):
                         atualizar_status_expedicao(ped, "Em Separação", "", "", user_name, "Voltou para Separação"); st.rerun()
                
                elif status == "Faturado": 
                    if pode_enviar:
                        if st.button("🚚 Enviar (Finalizar)", key=f"s4_{ped}"):
                            atualizar_status_expedicao(ped, "Enviado", "Data_Enviado", "User_Enviado", user_name, "Despachou / Finalizou"); st.rerun()
                    else: st.success("Pronto p/ Envio")
                    if pode_voltar and st.button("↩️ Voltar Fat.", key=f"v3_{ped}"):
                         atualizar_status_expedicao(ped, "Separado", "", "", user_name, "Cancelou Faturamento (Voltou)"); st.rerun()
                
                elif status == "Enviado":
                    st.success("Concluído")
                    if pode_voltar and st.button("↩️ Voltar Envio", key=f"v4_{ped}"):
                         atualizar_status_expedicao(ped, "Faturado", "", "", user_name, "Cancelou Envio (Voltou)"); st.rerun()

            st.markdown("---")

# ==============================================================================
# 🏁 FLUXO PRINCIPAL
# ==============================================================================

if 'usuario_logado' not in st.session_state: st.session_state['usuario_logado'] = None

# CARGA DE DADOS OTIMIZADA
raw_vendas = carregar_dados_vendas_cache()
df, col_vend, lista_reps, col_ped, col_nf = processar_dados_vendas(raw_vendas)

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

            opcoes_layout = ["Meta MIC (Empresa)", "Supervisão (Reps)", "Top 10 Clientes (Reps)", "Lista Clientes (Reps)", "Performance Individual", "Meus Top 10 Clientes", "Ranking Geral", "Evolução Diária"]
            layout_salvo = u_data['layout'].split(',') if u_data['layout'] else opcoes_layout
            layout_salvo = [l for l in layout_salvo if l in opcoes_layout]
            if not layout_salvo: layout_salvo = opcoes_layout
            
            st.caption("Ordem do Dashboard:")
            novo_layout = st.multiselect("Layout:", opcoes_layout, default=layout_salvo)
            if st.button("Salvar Layout"):
                layout_str = ",".join(novo_layout)
                if atualizar_campo(uid, "Config_Layout", layout_str): st.success("Salvo!"); st.rerun()

            st.markdown("---")
            
            with st.expander("Zona de Perigo"):
                check_del = st.checkbox("Confirmo exclusão da conta")
                if st.button("Excluir Conta", type="primary", disabled=not check_del):
                    if excluir_usuario(uid): st.session_state['usuario_logado'] = None; st.rerun()

            if st.button("Sair"): st.session_state['usuario_logado'] = None; st.rerun()

    if cargo == "Expedicao":
        render_expedicao(cargo, u_data['nome'], df, col_ped, col_nf)
    else:
        tab_vendas, tab_exp = st.tabs(["📊 Dashboard Vendas", "📦 Expedição (WMS)"])
        with tab_vendas:
            render_dashboard_vendas(u_data, uid, df, col_vend, lista_reps)
        with tab_exp:
            render_expedicao(cargo, u_data['nome'], df, col_ped, col_nf)