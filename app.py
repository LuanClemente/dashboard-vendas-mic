import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import plotly.express as px
import os
import json 
from datetime import datetime, date, timedelta
import calendar
import numpy as np
import unicodedata
from PIL import Image 
import pytz 
import time
import re # Importante para limpeza pesada

# ==============================================================================
# ⚙️ CONFIGURAÇÕES
# ==============================================================================
st.set_page_config(page_title="Sistema MIC", layout="wide", page_icon="🏢", initial_sidebar_state="collapsed")

ARQUIVO_LOGO = "logo.png"
FUSO_SP = pytz.timezone('America/Sao_Paulo')
URL_PLANILHA_MESTRA = "https://docs.google.com/spreadsheets/d/1x6p2koSoPRfs6yB2-8lT9JibgWL1cjlLriq0EnxUlj0/edit?gid=1148960899#gid=1148960899"

# Estilo Clean
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        .stApp {margin-top: -30px;}
        div[data-testid="stVerticalBlock"] > div {
            padding-top: 5px;
            padding-bottom: 5px;
        }
    </style>
""", unsafe_allow_html=True)

def carregar_imagem_segura(caminho):
    try: return Image.open(caminho)
    except: return None

def get_data_hora_sp():
    return datetime.now(FUSO_SP).strftime("%d/%m/%Y %H:%M")

def barra_progresso_linda(atual, meta, titulo="Progresso"):
    pct = (atual / meta * 100) if meta > 0 else 0
    vis = min(pct, 100) 
    grad = "linear-gradient(90deg, #ff4b4b 0%, #ffca28 50%, #21c354 100%)"
    st.markdown(f"""<div style="margin-bottom: 15px;"><div style="display: flex; justify-content: space-between; align-items: flex-end;"><span style="font-weight: bold; font-size: 1rem; color: #444;">{titulo}</span><span style="font-weight: bold; font-size: 1.2rem; color: #333;">{pct:.1f}%</span></div><div style="width: 100%; background-color: #e6e6e6; border-radius: 20px; height: 18px;"><div style="width: {vis}%; background: {grad}; height: 100%; border-radius: 20px; transition: width 1s ease-in-out;"></div></div><div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: #666; margin-top: 2px;"><span>R$ {atual:,.2f}</span><span>Meta: R$ {meta:,.2f}</span></div></div>""", unsafe_allow_html=True)

# ==============================================================================
# 💾 CARGA DE DADOS BLINDADA
# ==============================================================================
conn = st.connection("gsheets", type=GSheetsConnection)

def inicializar_usuarios():
    try:
        df = conn.read(ttl=5)
        cols = ["Login", "Senha", "Meta", "Nome", "Meta_Rep", "Config_Layout", "Cargo"]
        if df.empty: return pd.DataFrame(columns=cols)
        changed = False
        for c in cols:
            if c not in df.columns: 
                df[c] = "{}" if "Meta" in c else ""
                changed = True
        if changed: conn.update(data=df)
        return df
    except: return pd.DataFrame(columns=["Login", "Senha", "Meta", "Nome", "Meta_Rep", "Config_Layout", "Cargo"])

df_usuarios = inicializar_usuarios()
usuarios_dict = {}
META_GLOBAL = 100000.0

if not df_usuarios.empty:
    for _, row in df_usuarios.iterrows():
        login = str(row["Login"]).strip()
        if login == "__GLOBAL__":
            META_GLOBAL = float(row["Meta"]) if pd.notnull(row["Meta"]) else 100000.0
        elif login:
            try: metas = json.loads(str(row.get("Meta_Rep", "{}")))
            except: metas = {}
            if not isinstance(metas, dict): metas = {}
            usuarios_dict[login] = {
                "senha": str(row["Senha"]).strip().replace(".0", ""),
                "meta": float(row["Meta"]) if pd.notnull(row["Meta"]) else 0.0,
                "nome": str(row["Nome"]),
                "cargo": str(row.get("Cargo", "Vendedor")).strip(),
                "metas_reps": metas,
                "layout": str(row.get("Config_Layout", ""))
            }

@st.cache_data(ttl=60, show_spinner="Lendo dados...")
def carregar_dados_vendas():
    try:
        df = conn.read(spreadsheet=URL_PLANILHA_MESTRA, ttl=0)
        if df.empty: return None, None, [], None, None
        
        # 1. Normalização de Colunas (Remove acentos e espaços)
        def normalizar(s):
            return "".join(c for c in unicodedata.normalize('NFD', str(s)) if unicodedata.category(c) != 'Mn').lower().strip()
        
        mapa_cols = {normalizar(c): c for c in df.columns}
        
        # 2. Busca Inteligente de Colunas
        def achar(termos):
            for t in termos:
                for k, v in mapa_cols.items():
                    if t in k: return v
            return None

        c_val = achar(['valor', 'liq'])
        c_dat = achar(['gera', 'data', 'emis'])
        c_ped = achar(['pedido'])
        c_nf  = achar(['nf', 'nota'])
        c_vnd = achar(['vend', 'vendedor'])
        c_rep = achar(['rep', 'representante'])
        c_cli = achar(['cli', 'cliente'])
        c_cnpj= achar(['cnpj'])

        if not c_val or not c_dat:
            st.error("❌ Erro: Não encontrei colunas de VALOR ou DATA. Verifique os nomes na planilha.")
            return None, None, [], None, None

        # 3. Limpeza DESTRUTIVA de Valor (Regex)
        # Mantém apenas números, pontos e vírgulas. Remove R$, espaços, letras.
        def limpar_valor_bruto(v):
            if pd.isna(v): return 0.0
            s = str(v)
            # Remove tudo que NÃO for digito, ponto, virgula ou sinal de menos
            s_clean = re.sub(r'[^\d,.-]', '', s)
            if not s_clean: return 0.0
            # Formato BR: remove ponto de milhar, troca virgula por ponto
            s_clean = s_clean.replace('.', '').replace(',', '.')
            try: return float(s_clean)
            except: return 0.0

        df['valor_final'] = df[c_val].apply(limpar_valor_bruto)

        # 4. Limpeza de Data (Force DayFirst)
        df['data_str'] = df[c_dat].astype(str).str.strip()
        # Tenta formato DD/MM/YYYY primeiro
        df['data_final'] = pd.to_datetime(df['data_str'], dayfirst=True, errors='coerce')
        
        # Se falhar e a data for numérica (Excel Serial), tenta converter
        mask_nat = df['data_final'].isna()
        if mask_nat.any():
            # Tenta converter número serial do Excel
            df.loc[mask_nat, 'data_final'] = pd.to_datetime(pd.to_numeric(df.loc[mask_nat, 'data_str'], errors='coerce'), unit='D', origin='1899-12-30')

        # Remove linhas sem data válida
        df = df.dropna(subset=['data_final'])

        # 5. Outros Campos
        if c_nf: 
            df['status_ped'] = df[c_nf].apply(lambda x: 'Faturado' if pd.notnull(x) and str(x).strip() not in ['','0','nan'] else 'A Faturar')
        else: df['status_ped'] = 'Desconhecido'

        if not c_ped and c_nf: c_ped = c_nf
        df['id_pedido'] = df[c_ped].fillna(0) if c_ped else df.index
        df['Cliente'] = df[c_cli] if c_cli else 'Consumidor'
        df['Representante'] = df[c_rep] if c_rep else 'Direto'
        
        l_reps = sorted(df['Representante'].dropna().unique().tolist())
        
        return df, c_vnd, l_reps, c_ped, c_nf

    except Exception as e:
        st.error(f"Erro Crítico na Carga: {e}")
        return None, None, [], None, None

def carregar_dados_expedicao(dfv, cped, cnf):
    cols = ['Pedido','Cliente','Vendedor','Status_Atual','Data_Emitido','Data_Separacao','Data_Separado','Data_Faturado','Data_Enviado','User_Separacao','User_Separado','User_Faturado','User_Enviado','Log_Historico']
    try:
        dfe = conn.read(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", ttl=2)
        if dfe.empty: dfe = pd.DataFrame(columns=cols)
        else:
            for c in cols: 
                if c not in dfe.columns: dfe[c] = ""
    except: dfe = pd.DataFrame(columns=cols)

    try:
        if dfv is not None and not dfv.empty:
            dfe['Pedido'] = dfe['Pedido'].astype(str).str.split('.').str[0].str.strip()
            dfv['id_match'] = dfv['id_pedido'].astype(str).str.split('.').str[0].str.strip()
            
            p_exp = set(dfe['Pedido'].unique())
            p_vnd = set(dfv['id_match'].unique())
            novos = [p for p in (p_vnd - p_exp) if p and p != 'nan']
            
            changed = False
            if novos:
                rows = []
                agora = get_data_hora_sp()
                col_c = next((c for c in dfv.columns if 'Cliente' in c), 'Cliente')
                col_v = next((c for c in dfv.columns if 'Vendedor' in c), 'Vendedor')
                
                for p in novos:
                    rv = dfv[dfv['id_match'] == p].iloc[0]
                    tem_nf = False
                    if cnf:
                        val = str(rv.get(cnf,'')).strip()
                        tem_nf = val and val.lower() not in ['nan','','0']
                    
                    stt = 'Faturado' if tem_nf else 'Emitido'
                    rows.append({
                        'Pedido': str(p),
                        'Cliente': str(rv.get(col_c,'')),
                        'Vendedor': str(rv.get(col_v,'')),
                        'Status_Atual': stt,
                        'Data_Emitido': agora,
                        'Data_Faturado': agora if tem_nf else '',
                        'User_Faturado': 'Sistema' if tem_nf else '',
                        'Log_Historico': f"[{agora}] Importado como {stt}"
                    })
                if rows:
                    dfe = pd.concat([dfe, pd.DataFrame(rows)], ignore_index=True)
                    changed = True
            
            if changed:
                try: conn.update(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", data=dfe.fillna(""))
                except: pass
    except: pass
    return dfe

def atualizar_status(ped, sts, c_dat, c_usr, usr, log):
    try:
        try: df = conn.read(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", ttl=0)
        except: time.sleep(1); df = conn.read(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", ttl=0)
        
        df['Pedido'] = df['Pedido'].astype(str).str.split('.').str[0].str.strip()
        idx = df.index[df['Pedido'] == str(ped)].tolist()
        if idx:
            i = idx[0]
            agora = get_data_hora_sp()
            df.at[i, 'Status_Atual'] = sts
            if c_dat: df.at[i, c_dat] = agora
            if c_usr: df.at[i, c_usr] = usr
            lant = str(df.at[i, 'Log_Historico'])
            if lant == 'nan': lant = ""
            df.at[i, 'Log_Historico'] = lant + f" | [{agora}-{usr}] {log}"
            conn.update(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", data=df.fillna(""))
            return True
        return False
    except: return False

# ==============================================================================
# 📊 DASHBOARD
# ==============================================================================
def render_dash(u_data, uid, df_f, c_vend, l_reps):
    l_padrao = ["Meta MIC (Empresa)", "Supervisão (Reps)", "Top 10 Clientes (Reps)", "Lista Clientes (Reps)", "Performance Individual", "Meus Top 10 Clientes", "Ranking Geral", "Evolução Diária"]
    l_user = u_data.get('layout','').split(',')
    l_user = [x for x in l_user if x] if l_user else l_padrao

    with st.expander("⚙️ Configurar Metas Representantes"):
        c1, c2, c3 = st.columns([2,1,1])
        rep = c1.selectbox("Representante", [""] + sorted(l_reps))
        m_reps = u_data['metas_reps']
        val = m_reps.get(rep, 0.0) if rep else 0.0
        n_val = c2.number_input("Meta R$", value=float(val))
        if c3.button("Salvar Meta"):
            if rep: 
                m_reps[rep] = n_val
                if atualizar_campo(uid, "Meta_Rep", m_reps): st.success("OK"); st.rerun()
    st.divider()

    # Se vazio
    if df_f.empty:
        st.warning("⚠️ Nenhum dado encontrado para o período/filtros selecionados.")
        return

    def w_meta():
        st.markdown("### 🏢 Meta MIC (Empresa)")
        tot = df_f['valor_final'].sum()
        barra_progresso_linda(tot, META_GLOBAL, "Geral")
        c1, c2 = st.columns(2)
        c1.metric("Total", f"R$ {tot:,.2f}")
        c2.metric("Pedidos", df_f['id_pedido'].nunique())

    def w_sup():
        st.markdown("### 🤝 Supervisão")
        if m_reps:
            tabs = st.tabs(list(m_reps.keys()))
            for i, (rn, rm) in enumerate(m_reps.items()):
                with tabs[i]:
                    dfr = df_f[df_f['Representante'] == rn]
                    tr = dfr['valor_final'].sum()
                    barra_progresso_linda(tr, rm, rn)
                    st.metric("Venda", f"R$ {tr:,.2f}")

    def w_top():
        st.markdown("### 🏆 Top 10 Clientes")
        if 'Cliente' in df_f.columns:
            top = df_f.groupby('Cliente')['valor_final'].sum().sort_values(ascending=False).head(10).reset_index()
            st.dataframe(top, use_container_width=True)

    def w_lista():
        st.markdown("### 📋 Lista Clientes")
        with st.expander("Ver Lista"):
            st.dataframe(df_f[['Cliente','valor_final']].sort_values('valor_final', ascending=False), use_container_width=True)

    def w_indiv():
        st.markdown(f"### 👤 {u_data['nome']}")
        if c_vend:
            nome_busca = u_data['nome'].split()[0]
            dfu = df_f[df_f[c_vend].astype(str).str.contains(nome_busca, case=False, na=False)]
            tu = dfu['valor_final'].sum()
            mu = float(u_data['meta'])
            barra_progresso_linda(tu, mu, "Meu Resultado")
            st.metric("Minhas Vendas", f"R$ {tu:,.2f}")

    def w_meustop():
         st.markdown("### Meus Top 10")
         if c_vend:
            nome_busca = u_data['nome'].split()[0]
            dfu = df_f[df_f[c_vend].astype(str).str.contains(nome_busca, case=False, na=False)]
            top = dfu.groupby('Cliente')['valor_final'].sum().sort_values(ascending=False).head(10).reset_index()
            st.dataframe(top, use_container_width=True)

    def w_rank():
        st.markdown("### Ranking Vendedores")
        if c_vend:
            rk = df_f.groupby(c_vend)['valor_final'].sum().sort_values(ascending=False).reset_index()
            st.dataframe(rk, use_container_width=True)

    def w_evol():
        st.markdown("### 📈 Evolução")
        if not df_f.empty:
            evo = df_f.copy()
            evo['Dia'] = evo['data_final'].dt.date
            df_g = evo.groupby('Dia')['valor_final'].sum().reset_index()
            st.plotly_chart(px.line(df_g, x='Dia', y='valor_final', markers=True), use_container_width=True)

    mapa = {"Meta MIC (Empresa)":w_meta, "Supervisão (Reps)":w_sup, "Top 10 Clientes (Reps)":w_top,
            "Lista Clientes (Reps)":w_lista, "Performance Individual":w_indiv, "Meus Top 10 Clientes":w_meustop,
            "Ranking Geral":w_rank, "Evolução Diária":w_evol}
    
    for m in l_user:
        if m in mapa: mapa[m](); st.divider()

# ==============================================================================
# 📦 EXPEDIÇÃO
# ==============================================================================
def render_exp(urole, uname, dfv, cped, cnf, p_dates):
    st.markdown("## 📦 Expedição")
    roles = {'sep': ['Expedicao','ADM'], 'fat': ['Vendedor','Expedicao','ADM'], 'env': ['Expedicao','ADM']}
    
    with st.spinner("Sincronizando..."):
        dfe = carregar_dados_expedicao(dfv, cped, cnf)

    if not dfe.empty and p_dates and len(p_dates) == 2:
        dfe['dt_obj'] = pd.to_datetime(dfe['Data_Emitido'], format="%d/%m/%Y %H:%M", errors='coerce').dt.date
        dfe = dfe[(dfe['dt_obj'] >= p_dates[0]) & (dfe['dt_obj'] <= p_dates[1])]

    c1, c2 = st.columns([3,1])
    txt = c1.text_input("🔎 Buscar Pedido")
    stt = c2.selectbox("Status", ["Todos","Emitidos","Separando","Faturados","Enviados"], key='fstexp')

    mask = [True] * len(dfe)
    if stt == "Emitidos": mask = dfe['Status_Atual'] == "Emitido"
    elif stt == "Separando": mask = dfe['Status_Atual'].isin(["Em Separação","Separado"])
    elif stt == "Faturados": mask = dfe['Status_Atual'] == "Faturado"
    elif stt == "Enviados": mask = dfe['Status_Atual'] == "Enviado"
    
    view = dfe[mask]
    if txt: 
        t = txt.lower()
        view = view[view['Pedido'].str.contains(t, case=False) | view['Cliente'].str.lower().str.contains(t)]
    
    st.info(f"Pedidos listados: {len(view)}")
    
    for i, r in view.iloc[::-1].iterrows():
        s = r['Status_Atual']
        p = r['Pedido']
        with st.container():
            k1, k2, k3, k4 = st.columns([1.5, 3, 2, 2])
            k1.markdown(f"**{p}**"); k1.caption(r['Vendedor'])
            k2.markdown(f"**{r['Cliente']}**"); k2.write(f"Status: **{s}**")
            k3.caption(f"📅 {r['Data_Emitido']}")
            
            if s == "Emitido" and urole in roles['sep']:
                if k4.button("Separar", key=f"b1{p}"): atualizar_status(p,"Em Separação","Data_Separacao","User_Separacao",uname,"Iniciou Sep"); st.rerun()
            elif s == "Em Separação" and urole in roles['sep']:
                if k4.button("Finalizar", key=f"b2{p}"): atualizar_status(p,"Separado","Data_Separado","User_Separado",uname,"Fim Sep"); st.rerun()
            elif s == "Separado" and urole in roles['fat']:
                if k4.button("Faturar", key=f"b3{p}"): atualizar_status(p,"Faturado","Data_Faturado","User_Faturado",uname,"Faturou"); st.rerun()
            elif s == "Faturado" and urole in roles['env']:
                if k4.button("Enviar", key=f"b4{p}"): atualizar_status(p,"Enviado","Data_Enviado","User_Enviado",uname,"Enviou"); st.rerun()
            st.markdown("---")

# ==============================================================================
# 🚀 MAIN
# ==============================================================================
if 'usuario_logado' not in st.session_state: st.session_state['usuario_logado'] = None

# Carga de dados inicial
df, cvend, lreps, cped, cnf = carregar_dados_vendas()
if df is None: df = pd.DataFrame()

# LOGIN
if not st.session_state['usuario_logado']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        if os.path.exists(ARQUIVO_LOGO): st.image(carregar_imagem_segura(ARQUIVO_LOGO), width=200)
        else: st.title("MIC System")
        u = st.text_input("Usuário").strip()
        p = st.text_input("Senha", type="password").strip()
        if st.button("Entrar", use_container_width=True):
            if u in usuarios_dict and usuarios_dict[u]['senha'] == p:
                st.session_state['usuario_logado'] = u; st.rerun()
            else: st.error("Acesso Negado")
else:
    # LOGADO
    uid = st.session_state['usuario_logado']
    udata = usuarios_dict.get(uid, {})
    cargo = udata.get('cargo', 'Vendedor')

    # Header
    c_h1, c_h2 = st.columns([6,1])
    with c_h1: 
        if os.path.exists(ARQUIVO_LOGO): st.image(carregar_imagem_segura(ARQUIVO_LOGO), width=100)
        else: st.title("MIC System")
    with c_h2:
        if st.button("Sair"): st.session_state['usuario_logado'] = None; st.rerun()

    # --- INSPETOR DE DADOS (PARA RESOLVER O BUG DE UMA VEZ) ---
    if not df.empty:
        min_d = df['data_final'].min().date()
        max_d = df['data_final'].max().date()
        st.success(f"✅ Dados Carregados! Período na Planilha: **{min_d.strftime('%d/%m/%Y')}** até **{max_d.strftime('%d/%m/%Y')}**. Total: {len(df)} registros.")
    else:
        st.error("⚠️ Planilha vazia ou erro na leitura das datas.")
        min_d, max_d = date.today(), date.today()

    st.divider()
    
    # Filtros
    cf1, cf2 = st.columns(2)
    st_filtro = cf1.selectbox("Status Venda", ["Todos","Faturado","A Faturar"], key='fstglob')
    
    # O filtro agora já nasce com a data da planilha
    dates = cf2.date_input("📅 Período de Análise", [min_d, max_d])

    # Aplica Filtros
    df_filt = df.copy()
    if not df_filt.empty and isinstance(dates, list) and len(dates) == 2:
        df_filt = df_filt[(df_filt['data_final'].dt.date >= dates[0]) & (df_filt['data_final'].dt.date <= dates[1])]
    
    if st_filtro != "Todos":
        df_filt = df_filt[df_filt['status_ped'] == st_filtro]

    # Render
    if cargo == "Expedicao":
        render_exp(cargo, udata['nome'], df, cped, cnf, dates)
    else:
        t1, t2 = st.tabs(["📊 Dashboard", "📦 Expedição"])
        with t1: render_dash(udata, uid, df_filt, cvend, lreps)
        with t2: render_exp(cargo, udata['nome'], df, cped, cnf, dates)