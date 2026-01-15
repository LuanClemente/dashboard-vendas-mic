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
from gspread.exceptions import APIError

# ==============================================================================
# ⚙️ CONFIGURAÇÕES INICIAIS
# ==============================================================================
st.set_page_config(
    page_title="Sistema Integrado MIC",
    layout="wide",
    page_icon="🏢",
    initial_sidebar_state="collapsed"
)

ARQUIVO_LOGO = "logo.png"
FUSO_SP = pytz.timezone('America/Sao_Paulo')
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
    </style>
""", unsafe_allow_html=True)

def carregar_imagem_segura(caminho_imagem):
    """Carrega imagem com segurança."""
    try:
        return Image.open(caminho_imagem)
    except:
        return None

# ==============================================================================
# ☁️ BANCO DE DADOS
# ==============================================================================
conn = st.connection("gsheets", type=GSheetsConnection)

def get_data_hora_sp():
    """Data/hora no fuso de SP."""
    return datetime.now(FUSO_SP).strftime("%d/%m/%Y %H:%M")

def limpar_dado(dado):
    """Limpa valores NaN e remove .0."""
    if pd.isna(dado):
        return ""
    return str(dado).strip().replace(".0", "")

def normalizar_nome_coluna(nome):
    """
    Normaliza nomes de coluna:
    - remove acentos
    - converte para minúsculas
    - remove espaços extras
    """
    texto = unicodedata.normalize("NFKD", str(nome))
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return texto.lower().strip()

# ==============================================================================
# 👥 GESTÃO DE USUÁRIOS
# ==============================================================================
def inicializar_e_carregar_usuarios():
    """Carrega usuários da planilha principal e garante colunas mínimas."""
    try:
        df = conn.read(ttl=5)
        colunas_necessarias = ["Login", "Senha", "Meta", "Nome", "Meta_Rep", "Config_Layout", "Cargo"]
        if df.empty:
            return pd.DataFrame(columns=colunas_necessarias)

        changed = False
        for c in colunas_necessarias:
            if c not in df.columns:
                df[c] = "{}" if "Meta" in c else ""
                changed = True
        if changed:
            conn.update(data=df)
        return df
    except:
        return pd.DataFrame(columns=["Login", "Senha", "Meta", "Nome", "Meta_Rep", "Config_Layout", "Cargo"])

df_usuarios = inicializar_e_carregar_usuarios()
META_GERAL_EMPRESA = 100000.0
usuarios_dict = {}

if not df_usuarios.empty:
    for _, row in df_usuarios.iterrows():
        login = limpar_dado(row["Login"])
        if login == "__GLOBAL__":
            META_GERAL_EMPRESA = float(row["Meta"]) if pd.notnull(row["Meta"]) else 100000.0
        elif login:
            meta_rep_raw = row.get("Meta_Rep", "{}")
            try:
                metas_reps_dict = json.loads(str(meta_rep_raw)) if meta_rep_raw else {}
            except:
                metas_reps_dict = {}
            if not isinstance(metas_reps_dict, dict):
                metas_reps_dict = {}

            usuarios_dict[login] = {
                "senha": limpar_dado(row["Senha"]),
                "meta": float(row["Meta"]) if pd.notnull(row["Meta"]) else 0.0,
                "nome": str(row["Nome"]),
                "cargo": limpar_dado(row.get("Cargo", "Vendedor")),
                "metas_reps": metas_reps_dict,
                "layout": str(row.get("Config_Layout", ""))
            }

def atualizar_campo(login, campo, novo_valor):
    """Atualiza um campo específico do usuário."""
    try:
        df = conn.read(ttl=0)
        df["Login"] = df["Login"].astype(str).str.strip()
        idx = df.index[df["Login"] == str(login).strip()].tolist()
        if idx:
            if isinstance(novo_valor, dict):
                novo_valor = json.dumps(novo_valor)
            df.at[idx[0], campo] = novo_valor
            conn.update(data=df.fillna(""))
            return True
        return False
    except:
        return False

def salvar_novo_usuario(login, senha, meta, nome):
    """Cria um novo usuário."""
    try:
        if login == "__GLOBAL__":
            return False
        df = conn.read(ttl=0)
        novo = pd.DataFrame([{
            "Login": login, "Senha": senha, "Meta": meta, "Nome": nome,
            "Meta_Rep": "{}", "Config_Layout": "", "Cargo": "Vendedor"
        }])
        conn.update(data=pd.concat([df, novo], ignore_index=True).fillna(""))
        return True
    except:
        return False

# ==============================================================================
# 📦 EXPEDIÇÃO (WMS)
# ==============================================================================
def carregar_dados_expedicao(df_vendas_atual, col_pedido_vendas, col_nf_vendas):
    """Sincroniza pedidos da planilha de vendas com a planilha de expedição."""
    cols_exp = [
        'Pedido', 'Cliente', 'Vendedor', 'Status_Atual',
        'Data_Emitido', 'Data_Separacao', 'Data_Separado',
        'Data_Faturado', 'Data_Enviado',
        'User_Separacao', 'User_Separado', 'User_Faturado',
        'User_Enviado', 'Log_Historico'
    ]

    try:
        df_exp = conn.read(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", ttl=2)
        if df_exp.empty or not set(['Pedido']).issubset(df_exp.columns):
            df_exp = pd.DataFrame(columns=cols_exp)
        else:
            for c in cols_exp:
                if c not in df_exp.columns:
                    df_exp[c] = ""
    except:
        df_exp = pd.DataFrame(columns=cols_exp)

    try:
        if df_vendas_atual is not None and not df_vendas_atual.empty:
            df_exp['Pedido'] = df_exp['Pedido'].astype(str).str.split('.').str[0].str.strip()
            df_vendas_atual[col_pedido_vendas] = df_vendas_atual[col_pedido_vendas].astype(str).str.split('.').str[0].str.strip()

            pedidos_exp = set(df_exp['Pedido'].unique())
            pedidos_vendas = set(df_vendas_atual[col_pedido_vendas].unique())
            novos = [p for p in (pedidos_vendas - pedidos_exp) if p and p.lower() != 'nan']

            mudou_algo = False

            # Parte 1: Inserir pedidos novos
            if novos:
                novos_dados = []
                agora = get_data_hora_sp()
                col_cli = next((c for c in df_vendas_atual.columns if 'Cliente' in c), 'Cliente')
                col_vend = next((c for c in df_vendas_atual.columns if 'Vendedor' in c), 'Vendedor')

                for p in novos:
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
                        'User_Separacao': '', 'User_Separado': '',
                        'User_Faturado': 'Sistema' if tem_nf else '', 'User_Enviado': '',
                        'Log_Historico': log_ini
                    })

                if novos_dados:
                    df_exp = pd.concat([df_exp, pd.DataFrame(novos_dados)], ignore_index=True)
                    mudou_algo = True

            # Parte 2: Auto-faturar pedidos com NF
            if col_nf_vendas:
                vendas_com_nf = df_vendas_atual[
                    df_vendas_atual[col_nf_vendas].notna() &
                    (df_vendas_atual[col_nf_vendas].astype(str).str.strip() != '')
                ]
                lista_pedidos_com_nf = set(vendas_com_nf[col_pedido_vendas].unique())

                for i, row in df_exp.iterrows():
                    ped = row['Pedido']
                    status = row['Status_Atual']
                    if ped in lista_pedidos_com_nf and status in ['Emitido', 'Em Separação', 'Separado']:
                        agora = get_data_hora_sp()
                        df_exp.at[i, 'Status_Atual'] = 'Faturado'
                        if not df_exp.at[i, 'Data_Faturado']:
                            df_exp.at[i, 'Data_Faturado'] = agora
                        df_exp.at[i, 'User_Faturado'] = 'Sistema (Auto)'
                        df_exp.at[i, 'Log_Historico'] = str(row.get('Log_Historico', '')) + f" | [{agora}] Auto-Faturado por NF detectada"
                        mudou_algo = True

            if mudou_algo:
                conn.update(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", data=df_exp.fillna(""))
            return df_exp
        return df_exp
    except:
        return df_exp

def atualizar_status_expedicao(pedido, novo_status, coluna_data, coluna_user, usuario_nome, log_msg):
    """Atualiza o status e registra log."""
    try:
        df_exp = conn.read(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", ttl=0)
        if df_exp.empty:
            return False
        df_exp['Pedido'] = df_exp['Pedido'].astype(str).str.split('.').str[0].str.strip()
        idx = df_exp.index[df_exp['Pedido'] == str(pedido)].tolist()
        if idx:
            i = idx[0]
            agora = get_data_hora_sp()
            df_exp.at[i, 'Status_Atual'] = novo_status
            if coluna_data:
                df_exp.at[i, coluna_data] = agora
            if coluna_user:
                df_exp.at[i, coluna_user] = usuario_nome
            df_exp.at[i, 'Log_Historico'] = str(df_exp.at[i, 'Log_Historico']) + f" | [{agora}] {log_msg}"
            conn.update(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", data=df_exp.fillna(""))
            return True
        return False
    except Exception as e:
        st.error(f"Erro ao atualizar status: {e}. Tente novamente em alguns segundos.")
        return False

# ==============================================================================
# 📥 CARGA DE DADOS VENDAS
# ==============================================================================
@st.cache_data(ttl=60, show_spinner="Carregando dados de vendas...")
def carregar_dados_vendas():
    """Carrega a planilha principal e identifica colunas por nome normalizado."""
    try:
        df = conn.read(spreadsheet=URL_PLANILHA_MESTRA, ttl=0)
        if df.empty:
            return None, None, [], None, None

        df.columns = [c.strip() for c in df.columns]
        cols = df.columns
        cols_norm = {normalizar_nome_coluna(c): c for c in cols}

        def encontrar_coluna(palavras):
            for nome_norm, original in cols_norm.items():
                if any(palavra in nome_norm for palavra in palavras):
                    return original
            return None

        col_valor = encontrar_coluna(["valor", "liq", "liquido"])
        col_data = encontrar_coluna(["gera", "data", "emis"])
        col_nf = encontrar_coluna(["nf", "nota"])
        col_vend = encontrar_coluna(["vendedor", "vend"])
        col_rep = encontrar_coluna(["representante", "rep"])
        col_cnpj = encontrar_coluna(["cnpj", "cgc"])
        col_pedido = encontrar_coluna(["pedido"])

        if not col_valor or not col_data:
            return None, None, [], None, None

        # Tratamento de valor (R$ com vírgula/ponto)
        if df[col_valor].dtype == 'O':
            df['valor_final'] = (
                df[col_valor]
                .astype(str)
                .str.replace('R$', '', regex=False)
                .str.strip()
                .str.replace('.', '', regex=False)
                .str.replace(',', '.', regex=False)
            )
            df['valor_final'] = pd.to_numeric(df['valor_final'], errors='coerce').fillna(0)
        else:
            df['valor_final'] = pd.to_numeric(df[col_valor], errors='coerce').fillna(0)

        # Datas
        df['data_str_temp'] = df[col_data].astype(str).str.strip()
        df['data_final'] = pd.to_datetime(df['data_str_temp'], format="%d/%m/%Y", errors='coerce')
        mask_erro = df['data_final'].isna()
        if mask_erro.any():
            df.loc[mask_erro, 'data_final'] = pd.to_datetime(df.loc[mask_erro, 'data_str_temp'], dayfirst=True, errors='coerce')

        # Status
        if col_nf:
            df['status_ped'] = df[col_nf].apply(lambda x: 'Faturado' if pd.notnull(x) and str(x).strip() != '' else 'A Faturar')
        else:
            df['status_ped'] = 'Desconhecido'

        if col_cnpj:
            df[col_cnpj] = df[col_cnpj].astype(str)
        if not col_pedido and col_nf:
            col_pedido = col_nf

        df['id_pedido'] = df[col_pedido].fillna(0) if col_pedido else df.index
        lista_reps = sorted(df[col_rep].dropna().unique().tolist()) if col_rep else []

        return df, col_vend, lista_reps, col_pedido, col_nf

    except Exception as e:
        print(f"Erro vendas: {e}")
        return None, None, [], None, None

# ==============================================================================
# 📊 UTILITÁRIOS
# ==============================================================================
def calcular_dias_uteis_restantes_mes():
    hoje = date.today()
    ultimo = calendar.monthrange(hoje.year, hoje.month)[1]
    fim = date(hoje.year, hoje.month, ultimo)
    if hoje > fim:
        return 0
    return max(0, int(np.busday_count(hoje, fim + timedelta(days=1))))

def calcular_dias_uteis_passados():
    hoje = date.today()
    inicio = hoje.replace(day=1)
    if hoje == inicio:
        return 1
    return max(1, int(np.busday_count(inicio, hoje)))

def calcular_curva_abc(df_input):
    if df_input.empty:
        return df_input
    df_abc = df_input.copy().sort_values('valor_final', ascending=False)
    total = df_abc['valor_final'].sum()
    if total == 0:
        return df_abc
    df_abc['acumulado'] = df_abc['valor_final'].cumsum()
    df_abc['perc'] = df_abc['acumulado'] / total
    df_abc['Curva'] = df_abc['perc'].apply(lambda p: 'A' if p <= 0.8 else ('B' if p <= 0.95 else 'C'))
    return df_abc

def barra_progresso_linda(atual, meta, titulo="Progresso"):
    pct = (atual / meta * 100) if meta > 0 else 0
    vis = min(pct, 100)
    grad = "linear-gradient(90deg, #ff4b4b 0%, #ffca28 50%, #21c354 100%)"
    st.markdown(
        f"""
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
        </div>
        """,
        unsafe_allow_html=True
    )

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

def extrair_periodo(periodo):
    """Normaliza o retorno do date_input para Timestamp."""
    if isinstance(periodo, (list, tuple)) and len(periodo) == 2:
        inicio, fim = periodo
        if inicio and fim:
            inicio_ts = pd.to_datetime(inicio).normalize()
            fim_ts = pd.to_datetime(fim).normalize()
            return inicio_ts, fim_ts
    return None

# ==============================================================================
# 🎨 RENDERIZAÇÃO
# ==============================================================================
def render_dashboard_vendas(u_data, uid, df_filt, col_vend_nome, lista_reps_disponiveis):
    layout_padrao = [
        "Meta MIC (Empresa)", "Supervisão (Reps)", "Top 10 Clientes (Reps)",
        "Lista Clientes (Reps)", "Performance Individual", "Meus Top 10 Clientes",
        "Ranking Geral", "Evolução Diária"
    ]
    layout_user = u_data.get('layout', '').split(',')
    layout_user = [l for l in layout_user if l] if layout_user else layout_padrao

    # -- Config de metas dos reps
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
                    if atualizar_campo(uid, "Meta_Rep", metas_reps):
                        st.success("Salvo!"); st.rerun()
            if c_b2.button("🗑️", help="Remover"):
                if rep_selecionado in metas_reps:
                    del metas_reps[rep_selecionado]
                    if atualizar_campo(uid, "Meta_Rep", metas_reps):
                        st.rerun()

    st.divider()

    def render_meta_mic():
        meta = META_GERAL_EMPRESA
        total = df_filt['valor_final'].sum()
        st.subheader("Meta MIC (Empresa)")
        barra_progresso_linda(total, meta)

    def render_supervisao():
        st.subheader("Supervisão (Reps)")
        metas_reps = u_data['metas_reps']
        df_rep = df_filt.groupby(col_vend_nome)['valor_final'].sum().reset_index() if col_vend_nome else pd.DataFrame()
        if not df_rep.empty:
            for _, r in df_rep.iterrows():
                rep = r[col_vend_nome]
                valor = r['valor_final']
                meta = float(metas_reps.get(rep, 0.0))
                barra_progresso_linda(valor, meta, titulo=rep)
        else:
            st.info("Sem dados de reps.")

    def render_top_clientes():
        st.subheader("Top 10 Clientes (Reps)")
        if 'Cliente' in df_filt.columns:
            top = df_filt.groupby('Cliente')['valor_final'].sum().reset_index().sort_values('valor_final', ascending=False).head(10)
            st.dataframe(top, use_container_width=True)
        else:
            st.info("Coluna Cliente não encontrada.")

    def render_lista_clientes():
        st.subheader("Lista Clientes (Reps)")
        if 'Cliente' in df_filt.columns:
            lista = df_filt.groupby('Cliente')['valor_final'].sum().reset_index().sort_values('valor_final', ascending=False)
            st.dataframe(lista, use_container_width=True)
        else:
            st.info("Coluna Cliente não encontrada.")

    def render_performance_individual():
        st.subheader("Performance Individual")
        nome_busca = st.text_input("Filtrar meu nome:", value=u_data['nome'].split()[0])
        if col_vend_nome:
            df_ind = df_filt[df_filt[col_vend_nome].str.contains(nome_busca, case=False, na=False)]
            total = df_ind['valor_final'].sum()
            meta_u = float(u_data['meta'])
            barra_progresso_linda(total, meta_u)
        else:
            st.info("Coluna de vendedor não encontrada.")

    def render_meus_top_clientes():
        st.subheader("Meus Top 10 Clientes")
        if col_vend_nome and 'Cliente' in df_filt.columns:
            nome_busca = st.text_input("Nome vendedor (Top 10 clientes):", value=u_data['nome'].split()[0])
            df_ind = df_filt[df_filt[col_vend_nome].str.contains(nome_busca, case=False, na=False)]
            top = df_ind.groupby('Cliente')['valor_final'].sum().reset_index().sort_values('valor_final', ascending=False).head(10)
            st.dataframe(top, use_container_width=True)
        else:
            st.info("Colunas necessárias não encontradas.")

    def render_ranking():
        st.subheader("Ranking Geral")
        if col_vend_nome:
            ranking = df_filt.groupby(col_vend_nome)['valor_final'].sum().reset_index().sort_values('valor_final', ascending=False)
            st.dataframe(ranking, use_container_width=True)
        else:
            st.info("Coluna de vendedor não encontrada.")

    def render_evolucao():
        st.subheader("Evolução Diária")
        if 'data_final' in df_filt.columns:
            df_evol = df_filt.copy()
            df_evol['data_plot'] = df_evol['data_final'].dt.date
            evol = df_evol.groupby('data_plot')['valor_final'].sum().reset_index().sort_values('data_plot')
            st.plotly_chart(px.line(evol, x='data_plot', y='valor_final', markers=True, title="Evolução Diária"), use_container_width=True)
        else:
            st.info("Coluna data_final não encontrada.")

    mapa = {
        "Meta MIC (Empresa)": render_meta_mic,
        "Supervisão (Reps)": render_supervisao,
        "Top 10 Clientes (Reps)": render_top_clientes,
        "Lista Clientes (Reps)": render_lista_clientes,
        "Performance Individual": render_performance_individual,
        "Meus Top 10 Clientes": render_meus_top_clientes,
        "Ranking Geral": render_ranking,
        "Evolução Diária": render_evolucao
    }

    for item in layout_user:
        if item in mapa:
            mapa[item]()

def render_expedicao(user_role, user_name, df_vendas, col_ped_vendas, col_nf_vendas, periodo_selecionado):
    st.markdown("## 📦 Controle de Expedição")

    pode_separar = user_role in ['Expedicao', 'ADM']
    pode_faturar = user_role in ['Vendedor', 'Expedicao', 'ADM']
    pode_enviar = user_role in ['Expedicao', 'ADM']
    pode_voltar = user_role in ['ADM', 'Expedicao']

    with st.spinner("Sincronizando WMS..."):
        df_exp = carregar_dados_expedicao(df_vendas, col_ped_vendas, col_nf_vendas)

    # Filtro de período
    if not df_exp.empty:
        df_exp['data_obj'] = pd.to_datetime(df_exp['Data_Emitido'], format="%d/%m/%Y %H:%M", errors='coerce').dt.normalize()
        periodo = extrair_periodo(periodo_selecionado)
        if periodo:
            inicio, fim = periodo
            df_exp = df_exp[(df_exp['data_obj'] >= inicio) & (df_exp['data_obj'] <= fim)]

    c_f1, c_f2 = st.columns([3, 1])
    termo = c_f1.text_input("🔎 Buscar Pedido, Cliente ou Vendedor")
    filtro_status = c_f2.selectbox("Filtrar Status", ["Todos", "Emitidos", "Separando", "Faturados", "Enviados"])

    mask_status = [True] * len(df_exp)
    if filtro_status == "Emitidos":
        mask_status = df_exp['Status_Atual'] == "Emitido"
    elif filtro_status == "Separando":
        mask_status = df_exp['Status_Atual'].isin(["Em Separação", "Separado"])
    elif filtro_status == "Faturados":
        mask_status = df_exp['Status_Atual'] == "Faturado"
    elif filtro_status == "Enviados":
        mask_status = df_exp['Status_Atual'] == "Enviado"

    df_view = df_exp[mask_status]

    if termo:
        t = termo.lower()
        df_view = df_view[
            df_view['Pedido'].str.lower().str.contains(t) |
            df_view['Cliente'].str.lower().str.contains(t) |
            df_view['Vendedor'].str.lower().str.contains(t)
        ]

    df_view = df_view.iloc[::-1]

    st.info(f"Mostrando {len(df_view)} pedidos no período selecionado.")
    st.divider()

    for _, row in df_view.iterrows():
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
                            atualizar_status_expedicao(ped, "Em Separação", "Data_Separacao", "User_Separacao", user_name, "Iniciou Separação")
                            st.rerun()
                    else:
                        st.info("Aguardando Estoque")

                elif status == "Em Separação":
                    if pode_separar:
                        if st.button("✅ Finalizar Sep.", key=f"s2_{ped}"):
                            atualizar_status_expedicao(ped, "Separado", "Data_Separado", "User_Separado", user_name, "Finalizou Separação")
                            st.rerun()
                        if pode_voltar and st.button("↩️ Voltar", key=f"v1_{ped}"):
                            atualizar_status_expedicao(ped, "Emitido", "", "", user_name, "Voltou para Emitido")
                            st.rerun()
                    else:
                        st.warning("Separando...")

                elif status == "Separado":
                    if pode_faturar:
                        if st.button("💲 Marcar Faturado", key=f"s3_{ped}"):
                            atualizar_status_expedicao(ped, "Faturado", "Data_Faturado", "User_Faturado", user_name, "Marcou Faturado")
                            st.rerun()
                    if pode_voltar and st.button("↩️ Voltar Sep.", key=f"v2_{ped}"):
                        atualizar_status_expedicao(ped, "Em Separação", "", "", user_name, "Voltou para Separação")
                        st.rerun()

                elif status == "Faturado":
                    if pode_enviar:
                        if st.button("🚚 Enviar", key=f"s4_{ped}"):
                            atualizar_status_expedicao(ped, "Enviado", "Data_Enviado", "User_Enviado", user_name, "Despachou")
                            st.rerun()
                    else:
                        st.success("Pronto p/ Envio")
                    if pode_voltar and st.button("↩️ Voltar Fat.", key=f"v3_{ped}"):
                        atualizar_status_expedicao(ped, "Separado", "", "", user_name, "Cancelou Faturamento (Voltou)")
                        st.rerun()

                elif status == "Enviado":
                    st.success("Concluído")
                    if pode_voltar and st.button("↩️ Voltar Envio", key=f"v4_{ped}"):
                        atualizar_status_expedicao(ped, "Faturado", "", "", user_name, "Cancelou Envio (Voltou)")
                        st.rerun()

            st.markdown("---")

# ==============================================================================
# 🏁 FLUXO PRINCIPAL
# ==============================================================================
if 'usuario_logado' not in st.session_state:
    st.session_state['usuario_logado'] = None

df, col_vend, lista_reps, col_ped, col_nf = carregar_dados_vendas()
if df is None:
    df = pd.DataFrame(columns=["valor_final", "data_final", "status_ped", "id_pedido"])
    lista_reps = []

if st.session_state['usuario_logado'] is None:
    c1, c2, c3 = st.columns([3, 2, 3])
    with c2:
        st.write(""); st.write("")
        if os.path.exists(ARQUIVO_LOGO):
            img = carregar_imagem_segura(ARQUIVO_LOGO)
            if img:
                st.image(img, use_container_width=True)
        else:
            st.title("MIC System")
        t1, t2 = st.tabs(["Entrar", "Criar Conta"])
        with t1:
            u = st.text_input("Usuário").strip()
            p = st.text_input("Senha", type="password").strip()
            if st.button("Acessar", use_container_width=True):
                if u in usuarios_dict and usuarios_dict[u]['senha'] == p:
                    st.session_state['usuario_logado'] = u
                    st.rerun()
                else:
                    st.error("Negado.")
            if st.button("🔄", help="Atualizar"):
                st.cache_data.clear()
                st.rerun()
        with t2:
            nu = st.text_input("Novo Usuário").strip()
            np_ = st.text_input("Nova Senha", type="password").strip()
            nn = st.text_input("Nome")
            if st.button("Cadastrar", use_container_width=True):
                if nu and np_ and nu != "__GLOBAL__":
                    if nu not in usuarios_dict:
                        if salvar_novo_usuario(nu, np_, 10000.0, nn):
                            st.success("OK! Logue.")
                    else:
                        st.error("Existe.")
else:
    uid = st.session_state['usuario_logado']
    if uid not in usuarios_dict:
        st.session_state['usuario_logado'] = None
        st.rerun()
    u_data = usuarios_dict[uid]
    cargo = u_data['cargo']

    h1, h2 = st.columns([6, 1])
    with h1:
        if os.path.exists(ARQUIVO_LOGO):
            img = carregar_imagem_segura(ARQUIVO_LOGO)
            if img:
                st.image(img, width=120)
        else:
            st.title("MIC")
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
                        if atualizar_campo(usr_edit, "Cargo", cargo_edit):
                            st.success("Atualizado!"); st.rerun()
            st.markdown("---")
            n_nome = st.text_input("Nome:", value=u_data['nome'])
            if st.button("Salvar Nome"):
                atualizar_campo(uid, "Nome", n_nome)
                st.rerun()
            n_senha = st.text_input("Nova Senha", type="password")
            if st.button("Salvar Senha"):
                atualizar_campo(uid, "Senha", n_senha)
                st.rerun()
            st.markdown("---")
            if st.button("Sair"):
                st.session_state['usuario_logado'] = None
                st.rerun()

    with st.expander("🕵️ Debug Dados (Apenas para verificação)"):
        st.write("Amostra dos dados carregados:")
        st.write(df[['data_final', 'valor_final']].head())
        st.write("Tipos:")
        st.write(df.dtypes)

    st.divider()
    c_global1, c_global2 = st.columns(2)
    status_sel_global = c_global1.selectbox("Status Vendas", ["Todos", "Faturado", "A Faturar"])

    hoje = date.today()
    ultimo = calendar.monthrange(hoje.year, hoje.month)[1]
    periodo_global = c_global2.date_input("Período de Análise", [hoje.replace(day=1), date(hoje.year, hoje.month, ultimo)])

    # Filtro Global
    df_filt_vendas = df.copy()
    periodo = extrair_periodo(periodo_global)
    if periodo:
        inicio, fim = periodo
        df_filt_vendas = df_filt_vendas[
            (df_filt_vendas['data_final'].dt.normalize() >= inicio) &
            (df_filt_vendas['data_final'].dt.normalize() <= fim)
        ]

    if status_sel_global != "Todos":
        df_filt_vendas = df_filt_vendas[df_filt_vendas['status_ped'] == status_sel_global]

    if cargo == "Expedicao":
        render_expedicao(cargo, u_data['nome'], df, col_ped, col_nf, periodo_global)
    else:
        tab1, tab2 = st.tabs(["📊 Dashboard Vendas", "📦 Expedição (WMS)"])
        with tab1:
            render_dashboard_vendas(u_data, uid, df_filt_vendas, col_vend, lista_reps)
        with tab2:
            render_expedicao(cargo, u_data['nome'], df, col_ped, col_nf, periodo_global)
