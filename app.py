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
from gspread.exceptions import APIError

# ==============================================================================
# ⚙️ CONFIGURAÇÕES E ESTILO
# ==============================================================================
st.set_page_config(page_title="Sistema MIC", layout="wide", page_icon="🏢", initial_sidebar_state="collapsed")

ARQUIVO_LOGO = "logo.png"
FUSO_SP = pytz.timezone('America/Sao_Paulo')
URL_PLANILHA_MESTRA = "https://docs.google.com/spreadsheets/d/1x6p2koSoPRfs6yB2-8lT9JibgWL1cjlLriq0EnxUlj0/edit?gid=1148960899#gid=1148960899"

st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        [data-testid="stSidebar"] {display: none;}
        .stApp {margin-top: -40px;}
        div[data-testid="stVerticalBlock"] > div {
            border-radius: 8px;
            padding: 4px;
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
    st.markdown(f"""<div style="margin-bottom: 15px;"><div style="display: flex; justify-content: space-between; align-items: flex-end;"><span style="font-weight: bold; font-size: 1rem; color: #444;">{titulo}</span><span style="font-weight: bold; font-size: 1.2rem; color: #333;">{pct:.1f}%</span></div><div style="width: 100%; background-color: #e6e6e6; border-radius: 20px; height: 20px;"><div style="width: {vis}%; background: {grad}; height: 100%; border-radius: 20px; transition: width 1s ease-in-out;"></div></div><div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: #666; margin-top: 3px;"><span>R$ {atual:,.2f}</span><span>Meta: R$ {meta:,.2f}</span></div></div>""", unsafe_allow_html=True)

# ==============================================================================
# 💾 CARGA DE DADOS (CORE)
# ==============================================================================
conn = st.connection("gsheets", type=GSheetsConnection)

def inicializar_usuarios():
    try:
        df = conn.read(ttl=5)
        cols = ["Login", "Senha", "Meta", "Nome", "Meta_Rep", "Config_Layout", "Cargo"]
        if df.empty: return pd.DataFrame(columns=cols)
        # Garante colunas
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

def atualizar_campo(login, campo, valor):
    try:
        df = conn.read(ttl=0)
        df["Login"] = df["Login"].astype(str).str.strip()
        idx = df.index[df["Login"] == str(login).strip()].tolist()
        if idx:
            if isinstance(valor, dict): valor = json.dumps(valor)
            df.at[idx[0], campo] = valor
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

# ------------------------------------------------------------------------------
# 📦 CARGA DE DADOS BLINDADA
# ------------------------------------------------------------------------------
@st.cache_data(ttl=60, show_spinner="Lendo planilha...")
def carregar_dados_vendas():
    try:
        df = conn.read(spreadsheet=URL_PLANILHA_MESTRA, ttl=0)
        if df.empty: return None, None, [], None, None
        
        # Limpeza de colunas
        df.columns = [c.strip() for c in df.columns]
        
        # Identificação de Colunas
        c_val = next((c for c in df.columns if 'Valor' in c or 'Liq' in c), None)
        c_dat = next((c for c in df.columns if 'Gera' in c or 'Data' in c), None)
        c_nf  = next((c for c in df.columns if 'NF' in c or 'Nota' in c), None)
        c_vnd = next((c for c in df.columns if 'Vendedor' in c or 'Vend' in c), None)
        c_rep = next((c for c in df.columns if 'Representante' in c or 'Rep' in c), None)
        c_ped = next((c for c in df.columns if 'Pedido' in c), None)
        c_cli = next((c for c in df.columns if 'Cliente' in c), None)
        c_cnpj= next((c for c in df.columns if 'CNPJ' in c), None)

        if not c_val or not c_dat: return None, None, [], None, None

        # Tratamento Valor
        if df[c_val].dtype == 'O':
            df['valor_final'] = df[c_val].astype(str).str.replace('R$', '', regex=False).str.strip().str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
            df['valor_final'] = pd.to_numeric(df['valor_final'], errors='coerce').fillna(0)
        else:
            df['valor_final'] = pd.to_numeric(df[c_val], errors='coerce').fillna(0)

        # Tratamento Data (A CORREÇÃO DO FILTRO TÁ AQUI)
        # O Pandas as vezes se confunde. Vamos forçar DD/MM/AAAA
        df['data_str'] = df[c_dat].astype(str).str.strip()
        df['data_final'] = pd.to_datetime(df['data_str'], format="%d/%m/%Y", errors='coerce')
        
        # Fallback se der erro
        mask_nat = df['data_final'].isna()
        if mask_nat.any():
            df.loc[mask_nat, 'data_final'] = pd.to_datetime(df.loc[mask_nat, 'data_str'], dayfirst=True, errors='coerce')

        # Status
        if c_nf: 
            df['status_ped'] = df[c_nf].apply(lambda x: 'Faturado' if pd.notnull(x) and str(x).strip() != '' else 'A Faturar')
        else: 
            df['status_ped'] = 'Desconhecido'

        # IDs e Reps
        if not c_ped and c_nf: c_ped = c_nf
        df['id_pedido'] = df[c_ped].fillna(0) if c_ped else df.index
        
        # Renomear colunas essenciais pra facilitar
        df['Cliente'] = df[c_cli] if c_cli else 'Consumidor'
        df['Representante'] = df[c_rep] if c_rep else 'Direto'
        if c_cnpj: df['CNPJ'] = df[c_cnpj]
        
        lista_reps = sorted(df['Representante'].dropna().unique().tolist())
        
        return df, c_vnd, lista_reps, c_ped, c_nf

    except Exception as e:
        print(f"Erro Vendas: {e}")
        return None, None, [], None, None

def carregar_dados_expedicao(df_vendas, c_ped_v, c_nf_v):
    cols = ['Pedido','Cliente','Vendedor','Status_Atual','Data_Emitido','Data_Separacao','Data_Separado','Data_Faturado','Data_Enviado','User_Separacao','User_Separado','User_Faturado','User_Enviado','Log_Historico']
    try:
        df_exp = conn.read(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", ttl=2)
        if df_exp.empty: df_exp = pd.DataFrame(columns=cols)
        else:
            for c in cols: 
                if c not in df_exp.columns: df_exp[c] = ""
    except: df_exp = pd.DataFrame(columns=cols)

    try:
        # Sincronia
        if df_vendas is not None and not df_vendas.empty:
            df_exp['Pedido'] = df_exp['Pedido'].astype(str).str.split('.').str[0].str.strip()
            df_vendas['id_match'] = df_vendas['id_pedido'].astype(str).str.split('.').str[0].str.strip()
            
            p_exp = set(df_exp['Pedido'].unique())
            p_vnd = set(df_vendas['id_match'].unique())
            novos = [p for p in (p_vnd - p_exp) if p and p != 'nan']
            
            changed = False
            if novos:
                rows = []
                agora = get_data_hora_sp()
                col_c = next((c for c in df_vendas.columns if 'Cliente' in c), 'Cliente')
                col_v = next((c for c in df_vendas.columns if 'Vendedor' in c), 'Vendedor')
                
                for p in novos:
                    rv = df_vendas[df_vendas['id_match'] == p].iloc[0]
                    tem_nf = False
                    if c_nf_v:
                        val = str(rv.get(c_nf_v,'')).strip()
                        tem_nf = val and val.lower()!='nan'
                    
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
                    df_exp = pd.concat([df_exp, pd.DataFrame(rows)], ignore_index=True)
                    changed = True
            
            # Atualiza NF auto
            if c_nf_v:
                v_com_nf = df_vendas[df_vendas[c_nf_v].notna() & (df_vendas[c_nf_v].astype(str).str.strip()!='')]
                l_nf = set(v_com_nf['id_match'].unique())
                for i, r in df_exp.iterrows():
                    if r['Pedido'] in l_nf and r['Status_Atual'] in ['Emitido','Em Separação','Separado']:
                        df_exp.at[i,'Status_Atual'] = 'Faturado'
                        if not df_exp.at[i,'Data_Faturado']: df_exp.at[i,'Data_Faturado'] = get_data_hora_sp()
                        df_exp.at[i,'User_Faturado'] = 'Sistema'
                        changed = True
            
            if changed:
                try: conn.update(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", data=df_exp.fillna(""))
                except APIError as e: 
                    if "429" not in str(e): pass

    except Exception as e: print(e)
    return df_exp

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
# 📊 DASHBOARD VENDAS
# ==============================================================================
def render_dash(u_data, uid, df_f, c_vend, l_reps):
    # Layout simplificado
    l_padrao = ["Meta MIC (Empresa)", "Supervisão (Reps)", "Top 10 Clientes (Reps)", "Lista Clientes (Reps)", "Performance Individual", "Ranking Geral"]
    l_user = u_data.get('layout','').split(',')
    l_user = [x for x in l_user if x] if l_user else l_padrao

    # Editor Metas
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
    
    # Cálculos Tempo
    hoje = date.today()
    ult_dia = calendar.monthrange(hoje.year, hoje.month)[1]
    fim_mes = date(hoje.year, hoje.month, ult_dia)
    dias_uteis = max(0, int(np.busday_count(hoje, fim_mes + timedelta(days=1)))) if hoje <= fim_mes else 0
    dias_pass = max(1, int(np.busday_count(hoje.replace(day=1), hoje))) if hoje >= hoje.replace(day=1) else 1

    def w_meta_mic():
        st.markdown("### 🏢 Meta MIC (Empresa)")
        tot = df_f['valor_final'].sum()
        falta = max(0, META_GLOBAL - tot)
        m_nec = falta / dias_uteis if dias_uteis > 0 else 0
        tick = tot / df_f['id_pedido'].nunique() if df_f['id_pedido'].nunique() > 0 else 0
        
        barra_progresso_linda(tot, META_GLOBAL, "Geral")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Vendido", f"R$ {tot:,.2f}")
        k2.metric("Meta Diária Nec.", f"R$ {m_nec:,.2f}")
        k3.metric("Falta", f"R$ {falta:,.2f}")
        k4.metric("Ticket Médio", f"R$ {tick:,.2f}")
        st.divider()

    def w_supervisao():
        if m_reps:
            st.markdown("### 🤝 Supervisão")
            tabs = st.tabs(list(m_reps.keys()))
            for i, (rn, rm) in enumerate(m_reps.items()):
                with tabs[i]:
                    dfr = df_f[df_f['Representante'] == rn]
                    tr = dfr['valor_final'].sum()
                    fr = max(0, rm - tr)
                    mnr = fr / dias_uteis if dias_uteis > 0 else 0
                    barra_progresso_linda(tr, rm, rn)
                    c1, c2 = st.columns(2)
                    c1.metric("Venda", f"R$ {tr:,.2f}")
                    c2.metric("Diária Nec.", f"R$ {mnr:,.2f}")
            st.divider()

    def w_top10():
        if m_reps:
            st.write("**Top 10 (Grupo)**")
            dfg = df_f[df_f['Representante'].isin(m_reps.keys())]
            if not dfg.empty:
                top = dfg.groupby('Cliente')['valor_final'].sum().sort_values(ascending=False).head(10).sort_values(ascending=True).reset_index()
                st.plotly_chart(px.bar(top, x='valor_final', y='Cliente', orientation='h', text_auto=True), use_container_width=True)
            st.divider()

    def w_lista():
        if m_reps:
            st.markdown("### 📋 Carteira")
            dfg = df_f[df_f['Representante'].isin(m_reps.keys())]
            with st.expander("Ver Lista"):
                busca = st.text_input("Filtrar Cliente")
                gp = dfg.groupby(['Cliente','CNPJ'])['valor_final'].sum().reset_index().sort_values('valor_final', ascending=False)
                if busca: gp = gp[gp['Cliente'].str.contains(busca, case=False)]
                gp['Valor'] = gp['valor_final'].apply(lambda x: f"R$ {x:,.2f}")
                st.dataframe(gp[['Cliente','CNPJ','Valor']], use_container_width=True)
            st.divider()

    def w_individual():
        st.markdown(f"### 👤 Performance: {u_data['nome']}")
        if c_vend:
            # Filtro Inteligente: Pega primeiro nome do usuario e busca na coluna vendedor
            nome_parts = u_data['nome'].split()
            nome_chave = nome_parts[0] if nome_parts else ""
            
            dfu = df_f[df_f[c_vend].astype(str).str.contains(nome_chave, case=False, na=False)]
            tu = dfu['valor_final'].sum()
            mu = float(u_data['meta'])
            fu = max(0, mu - tu)
            mnu = fu / dias_uteis if dias_uteis > 0 else 0
            tiku = tu / dfu['id_pedido'].nunique() if dfu['id_pedido'].nunique() > 0 else 0
            
            barra_progresso_linda(tu, mu, "Meu Resultado")
            
            # AGORA IGUAL AO META MIC
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Minhas Vendas", f"R$ {tu:,.2f}")
            k2.metric("Diária Nec.", f"R$ {mnu:,.2f}")
            k3.metric("Falta", f"R$ {fu:,.2f}")
            k4.metric("Ticket Médio", f"R$ {tiku:,.2f}")
            
            st.divider()

    def w_ranking():
        if c_vend:
            st.markdown("### 🏆 Ranking")
            rk = df_f.groupby(c_vend)['valor_final'].sum().sort_values(ascending=False).head(10).sort_values(ascending=True).reset_index()
            st.plotly_chart(px.bar(rk, x='valor_final', y=c_vend, orientation='h', text_auto=True), use_container_width=True)

    mapa = {
        "Meta MIC (Empresa)": w_meta_mic, "Supervisão (Reps)": w_supervisao,
        "Top 10 Clientes (Reps)": w_top10, "Lista Clientes (Reps)": w_lista,
        "Performance Individual": w_individual, "Ranking Geral": w_ranking
    }
    
    for item in l_user:
        if item in mapa: mapa[item]()

# ==============================================================================
# 📦 EXPEDIÇÃO
# ==============================================================================
def render_exp(urole, uname, dfv, cped, cnf, p_dates):
    st.markdown("## 📦 Expedição")
    roles = {'sep': ['Expedicao','ADM'], 'fat': ['Vendedor','Expedicao','ADM'], 'env': ['Expedicao','ADM']}
    
    with st.spinner("Sincronizando..."):
        dfe = carregar_dados_expedicao(dfv, cped, cnf)

    # FILTRO DATA
    if not dfe.empty and p_dates and len(p_dates) == 2:
        dfe['dt_obj'] = pd.to_datetime(dfe['Data_Emitido'], format="%d/%m/%Y %H:%M", errors='coerce').dt.date
        dfe = dfe[(dfe['dt_obj'] >= p_dates[0]) & (dfe['dt_obj'] <= p_dates[1])]

    c1, c2 = st.columns([3,1])
    txt = c1.text_input("🔎 Buscar Pedido")
    # key='f_st_exp' impede o conflito de abas!
    stt = c2.selectbox("Status", ["Todos","Emitidos","Separando","Faturados","Enviados"], key='f_st_exp')

    mask = [True] * len(dfe)
    if stt == "Emitidos": mask = dfe['Status_Atual'] == "Emitido"
    elif stt == "Separando": mask = dfe['Status_Atual'].isin(["Em Separação","Separado"])
    elif stt == "Faturados": mask = dfe['Status_Atual'] == "Faturado"
    elif stt == "Enviados": mask = dfe['Status_Atual'] == "Enviado"
    
    view = dfe[mask]
    if txt: 
        t = txt.lower()
        view = view[view['Pedido'].str.contains(t, case=False) | view['Cliente'].str.lower().str.contains(t)]
    
    st.caption(f"Pedidos: {len(view)}")
    st.divider()

    for i, r in view.iterrows():
        s = r['Status_Atual']
        p = r['Pedido']
        with st.container():
            k1, k2, k3, k4 = st.columns([1.5, 3, 2, 2])
            k1.markdown(f"**{p}**"); k1.caption(r['Vendedor'])
            k2.markdown(f"**{r['Cliente']}**"); k2.write(f"Status: **{s}**")
            k3.caption(f"📅 {r['Data_Emitido']}")
            
            # Botões
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

df, cvend, lreps, cped, cnf = carregar_dados_vendas()
if df is None: df = pd.DataFrame()

# LOGIN
if not st.session_state['usuario_logado']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        if os.path.exists(ARQUIVO_LOGO): st.image(carregar_imagem_segura(ARQUIVO_LOGO), width=200)
        else: st.title("MIC System")
        
        tab_ent, tab_cad = st.tabs(["Login", "Cadastro"])
        with tab_ent:
            u = st.text_input("User").strip()
            p = st.text_input("Pass", type="password").strip()
            if st.button("Entrar", use_container_width=True):
                if u in usuarios_dict and usuarios_dict[u]['senha'] == p:
                    st.session_state['usuario_logado'] = u; st.rerun()
                else: st.error("Erro")
        with tab_cad:
            nu = st.text_input("Novo User").strip()
            np_ = st.text_input("Nova Pass", type="password").strip()
            nn = st.text_input("Nome")
            if st.button("Criar", use_container_width=True):
                if nu and nu != "__GLOBAL__" and nu not in usuarios_dict:
                    salvar_novo_usuario(nu, np_, 10000.0, nn); st.success("Criado!"); time.sleep(1); st.rerun()
else:
    # LOGADO
    uid = st.session_state['usuario_logado']
    udata = usuarios_dict.get(uid, {})
    cargo = udata.get('cargo', 'Vendedor')

    # Header
    c_h1, c_h2 = st.columns([6,1])
    with c_h1: 
        if os.path.exists(ARQUIVO_LOGO): st.image(carregar_imagem_segura(ARQUIVO_LOGO), width=100)
        else: st.title("MIC")
    with c_h2:
        if st.button("Sair"): st.session_state['usuario_logado'] = None; st.rerun()

    # FILTROS GLOBAIS
    st.markdown("---")
    cf1, cf2 = st.columns(2)
    st_filtro = cf1.selectbox("Status Venda", ["Todos","Faturado","A Faturar"], key='f_st_glob')
    
    hj = date.today()
    ult = calendar.monthrange(hj.year, hj.month)[1]
    
    # ⚠️ AQUI: Filtro padrão do dia 1 até o último dia do mês ATUAL
    dates = cf2.date_input("📅 Período de Análise", [hj.replace(day=1), date(hj.year, hj.month, ult)])

    # APLICA FILTRO
    df_filt = df.copy()
    if not df_filt.empty and isinstance(dates, list) and len(dates) == 2:
        df_filt = df_filt[(df_filt['data_final'].dt.date >= dates[0]) & (df_filt['data_final'].dt.date <= dates[1])]
        # DEBUG VISUAL PARA VOCÊ VER SE ESTÁ FUNCIONANDO
        st.caption(f"📊 Filtrando de **{dates[0].strftime('%d/%m/%Y')}** até **{dates[1].strftime('%d/%m/%Y')}**. Pedidos encontrados: {len(df_filt)}")
    
    if st_filtro != "Todos":
        df_filt = df_filt[df_filt['status_ped'] == st_filtro]

    # RENDERIZAÇÃO
    if cargo == "Expedicao":
        render_exp(cargo, udata['nome'], df, cped, cnf, dates)
    else:
        # TABS fixas
        t1, t2 = st.tabs(["📊 Dashboard", "📦 Expedição"])
        with t1: render_dash(udata, uid, df_filt, cvend, lreps)
        with t2: render_exp(cargo, udata['nome'], df, cped, cnf, dates)