import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import plotly.express as px
import os
from datetime import date, timedelta
import calendar
import numpy as np
from PIL import Image 

# ==============================================================================
# ⚙️ CONFIGURAÇÕES INICIAIS
# ==============================================================================
st.set_page_config(page_title="Sistema Comercial MIC", layout="wide", page_icon="📊")

ARQUIVO_DADOS = "lista.csv" 
ARQUIVO_LOGO = "logo.png"

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
        colunas_necessarias = ["Login", "Senha", "Meta", "Nome", "Rep_Selecionado", "Meta_Rep"]
        
        # Cria estrutura se vazia
        if df.empty:
            df_init = pd.DataFrame([
                {"Login": "admin", "Senha": "123", "Meta": 10000.0, "Nome": "Administrador", "Rep_Selecionado": "", "Meta_Rep": 0.0},
                {"Login": "__GLOBAL__", "Senha": "***", "Meta": 100000.0, "Nome": "Meta da Empresa", "Rep_Selecionado": "", "Meta_Rep": 0.0}
            ])
            conn.update(data=df_init)
            return df_init

        # Atualiza colunas faltantes
        colunas_faltantes = [c for c in colunas_necessarias if c not in df.columns]
        if colunas_faltantes:
            for c in colunas_faltantes:
                df[c] = 0.0 if "Meta" in c else ""
            conn.update(data=df)
        
        # Garante linha global
        if "__GLOBAL__" not in df["Login"].astype(str).values:
            linha_global = pd.DataFrame([{
                "Login": "__GLOBAL__", "Senha": "***", "Meta": 100000.0, "Nome": "Meta da Empresa",
                "Rep_Selecionado": "", "Meta_Rep": 0.0
            }])
            df = pd.concat([df, linha_global], ignore_index=True)
            conn.update(data=df)
            
        return df
    except Exception as e:
        # Fallback offline
        return pd.DataFrame(columns=["Login", "Senha", "Meta", "Nome", "Rep_Selecionado", "Meta_Rep"])

df_usuarios = inicializar_e_carregar_usuarios()
META_GERAL_EMPRESA = 100000.0
usuarios_dict = {}

if not df_usuarios.empty:
    for index, row in df_usuarios.iterrows():
        login_limpo = limpar_dado(row["Login"])
        if login_limpo == "__GLOBAL__":
            META_GERAL_EMPRESA = float(row["Meta"]) if pd.notnull(row["Meta"]) else 100000.0
        elif login_limpo: 
            usuarios_dict[login_limpo] = {
                "senha": limpar_dado(row["Senha"]),
                "meta": float(row["Meta"]) if pd.notnull(row["Meta"]) else 0.0,
                "nome": str(row["Nome"]),
                # Agora tratamos como string pura, vamos separar por vírgula depois
                "rep_selecionado": limpar_dado(row.get("Rep_Selecionado", "")),
                "meta_rep": float(row.get("Meta_Rep", 0.0)) if pd.notnull(row.get("Meta_Rep")) else 0.0
            }

# --- FUNÇÕES DE ATUALIZAÇÃO ---
def salvar_novo_usuario(login, senha, meta, nome):
    try:
        if login == "__GLOBAL__": return False
        novo_dado = pd.DataFrame([{
            "Login": str(login).strip(), "Senha": str(senha).strip(), "Meta": meta, "Nome": nome,
            "Rep_Selecionado": "", "Meta_Rep": 0.0
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
            # Se for lista (multiselect), converte pra string antes de salvar
            if isinstance(novo_valor, list):
                novo_valor = ",".join(novo_valor)
            
            df_atual.at[idx, campo] = novo_valor
            conn.update(data=df_atual)
            return True
        return False
    except Exception as e:
        st.error(f"Erro: {e}")
        return False

# ==============================================================================
# 📥 CARGA DE DADOS (CSV VENDAS)
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

        if not col_valor or not col_data: return None, None, []

        if df[col_valor].dtype == 'O':
            df[col_valor] = df[col_valor].astype(str).str.replace('R$', '').str.strip().str.replace('.', '').str.replace(',', '.')
        df['valor_final'] = pd.to_numeric(df[col_valor], errors='coerce').fillna(0)
        df['data_final'] = pd.to_datetime(df[col_data], dayfirst=True, errors='coerce')
        
        if col_nf:
            df['status_ped'] = df[col_nf].apply(lambda x: 'Faturado' if pd.notnull(x) and str(x).strip() != '' else 'A Faturar')
        else:
            df['status_ped'] = 'Desconhecido'
            
        if col_cnpj:
            df[col_cnpj] = df[col_cnpj].astype(str)

        lista_reps = sorted(df[col_rep].dropna().unique().tolist()) if col_rep else []

        return df, col_vend, lista_reps
    except: return None, None, []

# --- VISUAL ---
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
# 🔐 BARRA LATERAL
# ==============================================================================
if os.path.exists(ARQUIVO_LOGO):
    img_logo = carregar_imagem_segura(ARQUIVO_LOGO)
    if img_logo: st.sidebar.image(img_logo, use_container_width=True)
else: st.sidebar.title("MIC")

st.sidebar.markdown("---")
st.sidebar.subheader("🔐 Acesso Restrito (Nuvem)")

if 'usuario_logado' not in st.session_state: st.session_state['usuario_logado'] = None
df, col_vend_nome, lista_reps_disponiveis = carregar_dados_vendas()

if st.session_state['usuario_logado'] is None:
    tab_login, tab_cadastro = st.sidebar.tabs(["Entrar", "Cadastrar"])
    with tab_login:
        if st.button("🔄 Atualizar Lista"):
            st.cache_data.clear()
            st.rerun()
        u_in = st.text_input("Usuário").strip()
        p_in = st.text_input("Senha", type="password").strip()
        if st.button("Entrar"):
            if u_in in usuarios_dict and usuarios_dict[u_in]['senha'] == p_in:
                st.session_state['usuario_logado'] = u_in
                st.rerun()
            else: st.error("Erro no login.")
    with tab_cadastro:
        new_user = st.text_input("Novo Usuário").strip()
        new_pass = st.text_input("Nova Senha", type="password").strip()
        new_name = st.text_input("Nome Completo")
        new_meta = st.number_input("Meta Inicial", value=10000.0)
        if st.button("Criar Vendedor"):
            if new_user and new_pass and new_user != "__GLOBAL__":
                if new_user not in usuarios_dict:
                    if salvar_novo_usuario(new_user, new_pass, new_meta, new_name):
                        st.success("Cadastrado!")
                else: st.error("Já existe.")
else:
    uid = st.session_state['usuario_logado']
    if uid in usuarios_dict:
        u_data = usuarios_dict[uid]
        st.sidebar.success(f"Olá, {u_data['nome']}")
        
        # === GESTÃO DE REPRESENTANTE (AGORA COM MULTI-SELECT) ===
        with st.sidebar.expander("🤝 Gestão de Representantes", expanded=False):
            st.info("Selecione um ou mais representantes para supervisionar.")
            
            # Recupera a string salva "Rep1,Rep2" e transforma em lista ["Rep1", "Rep2"]
            rep_atual_str = u_data.get('rep_selecionado', '')
            reps_atuais_lista = [r.strip() for r in rep_atual_str.split(',') if r.strip()]
            
            # Filtra apenas os que ainda existem na lista de disponiveis para evitar erro
            reps_validos = [r for r in reps_atuais_lista if r in lista_reps_disponiveis]
            
            meta_rep_atual = u_data.get('meta_rep', 0.0)
            
            # Multi-Select
            sel_reps = st.multiselect("Representantes:", lista_reps_disponiveis, default=reps_validos)
            val_meta_rep = st.number_input("Meta do Grupo (R$):", value=meta_rep_atual, help="Meta somada para todos os selecionados")
            
            if st.button("Salvar Configuração Rep"):
                with st.spinner("Salvando vínculo..."):
                    # A função atualizar_campo já converte a lista pra string
                    ok1 = atualizar_campo(uid, "Rep_Selecionado", sel_reps)
                    ok2 = atualizar_campo(uid, "Meta_Rep", val_meta_rep)
                    if ok1 and ok2:
                        st.success("Configuração Salva!")
                        st.rerun()
                    else:
                        st.error("Erro ao salvar.")

        with st.sidebar.expander("🎯 Metas Individuais"):
            nm = st.number_input("Minha Meta (R$)", value=float(u_data['meta']))
            if st.button("Salvar Meta"):
                if atualizar_campo(uid, "Meta", nm): st.success("Salvo!"); st.rerun()
            st.markdown("---")
            ng = st.number_input("Meta Empresa (R$)", value=float(META_GERAL_EMPRESA))
            if st.button("Salvar Meta Geral"):
                if atualizar_campo("__GLOBAL__", "Meta", ng): st.success("Salvo!"); st.rerun()

        with st.sidebar.expander("⚙️ Conta"):
            s_nova = st.text_input("Nova Senha", type="password")
            if st.button("Mudar Senha"):
                if atualizar_campo(uid, "Senha", s_nova): st.success("Senha alterada!")
            if st.button("Sair"):
                st.session_state['usuario_logado'] = None
                st.rerun()

# ==============================================================================
# 📊 DASHBOARD
# ==============================================================================
st.title("🚀 Painel de Controle de Vendas")

if df is not None:
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
    st.divider()

    # --- META GERAL ---
    st.markdown("## 🏢 META MIC")
    tot_geral = df_filt['valor_final'].sum()
    falta_emp = max(0, META_GERAL_EMPRESA - tot_geral)
    barra_progresso_linda(tot_geral, META_GERAL_EMPRESA, "Progresso Geral")
    
    k1, k2, k3 = st.columns(3)
    k1.metric("Vendas Totais", f"R$ {tot_geral:,.2f}")
    k2.metric("Meta Diária (Restante)", f"R$ {(falta_emp / dias_uteis if dias_uteis > 0 else 0):,.2f}", help=f"{dias_uteis} dias úteis")
    k3.metric("Falta Vender", f"R$ {falta_emp:,.2f}")

    if st.session_state['usuario_logado']:
        st.divider()
        uid = st.session_state['usuario_logado']
        if uid in usuarios_dict:
            u_logado = usuarios_dict[uid]
            
            # === DASHBOARD DOS REPRESENTANTES (SELECIONADOS) ===
            rep_str = u_logado.get('rep_selecionado', '')
            meta_rep = u_logado.get('meta_rep', 0.0)
            
            # Converte string de volta pra lista
            reps_selecionados = [r.strip() for r in rep_str.split(',') if r.strip()]
            
            if reps_selecionados:
                # Mostra título com os nomes (se forem muitos, resume)
                titulo_reps = ", ".join(reps_selecionados) if len(reps_selecionados) < 4 else f"{len(reps_selecionados)} Representantes Selecionados"
                st.markdown(f"### 🤝 SUPERVISÃO: {titulo_reps}")
                
                # Filtra se o Representante está NA LISTA de selecionados
                df_rep = df_filt[df_filt['Representante'].isin(reps_selecionados)]
                
                tot_rep = df_rep['valor_final'].sum()
                falta_rep = max(0, meta_rep - tot_rep)
                
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Vendas Totais (Grupo)", f"R$ {tot_rep:,.2f}")
                r2.metric("Meta do Grupo", f"R$ {meta_rep:,.2f}")
                r3.metric("Falta", f"R$ {falta_rep:,.2f}")
                r4.metric("Diária Necessária", f"R$ {(falta_rep / dias_uteis if dias_uteis > 0 else 0):,.2f}")
                barra_progresso_linda(tot_rep, meta_rep, "Progresso do Grupo")

                # NOVO LAYOUT: TOP 10 (Full Width) e LISTA (Full Width)
                st.markdown("#### 🏆 Top 10 Clientes (Grupo)")
                if not df_rep.empty:
                    top_10 = df_rep.groupby('Cliente')['valor_final'].sum().sort_values(ascending=False).head(10).reset_index()
                    fig = px.bar(top_10, x='valor_final', y='Cliente', orientation='h', text_auto=True, color='valor_final', color_continuous_scale='Greens')
                    fig.update_layout(yaxis=dict(autorange="reversed"), showlegend=False)
                    st.plotly_chart(fig, use_container_width=True)
                else: st.warning("Sem vendas no período para este grupo.")
                
                st.markdown("#### 📋 Carteira de Clientes (Busca e Filtro)")
                with st.expander("🔎 Pesquisar na Carteira do Grupo", expanded=True):
                    busca = st.text_input("Digite Nome ou CNPJ:", placeholder="Ex: Auto Peças ou 00.000.000", key="busca_rep")
                    
                    cols_grp = ['Cliente', 'CNPJ'] if 'CNPJ' in df_rep.columns else ['Cliente']
                    df_lista = df_rep.groupby(cols_grp)['valor_final'].sum().reset_index().sort_values('valor_final', ascending=False)
                    
                    if busca:
                        termo = busca.upper()
                        mask = df_lista['Cliente'].astype(str).str.upper().str.contains(termo)
                        if 'CNPJ' in df_lista.columns:
                            mask |= df_lista['CNPJ'].astype(str).str.contains(termo)
                        df_lista = df_lista[mask]
                    
                    df_lista['Vendas (R$)'] = df_lista['valor_final'].apply(lambda x: f"R$ {x:,.2f}")
                    st.dataframe(df_lista[['Cliente', 'CNPJ', 'Vendas (R$)']] if 'CNPJ' in df_lista.columns else df_lista, use_container_width=True, hide_index=True)

                st.divider()

            # === DASHBOARD DO VENDEDOR ===
            st.markdown(f"### 👤 PERFORMANCE INDIVIDUAL: {u_logado['nome']}")
            nome_padrao = u_logado['nome'].split()[0]
            nome_busca = st.text_input("Filtrar meu nome na lista:", value=nome_padrao)
            
            if col_vend_nome:
                df_user = df_filt[df_filt[col_vend_nome].astype(str).str.contains(nome_busca, case=False, na=False)]
                tot_u = df_user['valor_final'].sum()
                meta_u = float(u_logado['meta'])
                falta_u = max(0, meta_u - tot_u)
                
                ku1, ku2, ku3, ku4 = st.columns(4)
                ku1.metric("Minhas Vendas", f"R$ {tot_u:,.2f}")
                ku2.metric("Minha Meta", f"R$ {meta_u:,.2f}")
                ku3.metric("Falta", f"R$ {falta_u:,.2f}")
                ku4.metric("Minha Diária", f"R$ {(falta_u / dias_uteis if dias_uteis > 0 else 0):,.2f}")
                barra_progresso_linda(tot_u, meta_u, "Meu Progresso")

                # TOP 10 INDIVIDUAL (Full Width)
                st.markdown("#### 🏆 Meus Top 10 Clientes")
                if not df_user.empty:
                    top_10_u = df_user.groupby('Cliente')['valor_final'].sum().sort_values(ascending=False).head(10).reset_index()
                    fig_u = px.bar(top_10_u, x='valor_final', y='Cliente', orientation='h', text_auto=True, color='valor_final', color_continuous_scale='Greens')
                    fig_u.update_layout(yaxis=dict(autorange="reversed"), showlegend=False)
                    st.plotly_chart(fig_u, use_container_width=True)
                else: st.warning("Sem vendas.")

                # LISTA INDIVIDUAL (Full Width)
                st.markdown("#### 📋 Meus Clientes (Busca e Filtro)")
                with st.expander("🔎 Pesquisar Meus Clientes", expanded=True):
                    busca_u = st.text_input("Digite Nome ou CNPJ:", placeholder="Filtrar minha carteira...", key="busca_user")
                    cols_grp_u = ['Cliente', 'CNPJ'] if 'CNPJ' in df_user.columns else ['Cliente']
                    df_lista_u = df_user.groupby(cols_grp_u)['valor_final'].sum().reset_index().sort_values('valor_final', ascending=False)
                    if busca_u:
                        termo_u = busca_u.upper()
                        mask_u = df_lista_u['Cliente'].astype(str).str.upper().str.contains(termo_u)
                        if 'CNPJ' in df_lista_u.columns:
                            mask_u |= df_lista_u['CNPJ'].astype(str).str.contains(termo_u)
                        df_lista_u = df_lista_u[mask_u]
                    df_lista_u['Vendas (R$)'] = df_lista_u['valor_final'].apply(lambda x: f"R$ {x:,.2f}")
                    st.dataframe(df_lista_u[['Cliente', 'CNPJ', 'Vendas (R$)']] if 'CNPJ' in df_lista_u.columns else df_lista_u, use_container_width=True, hide_index=True)

                with st.expander("Ver pedidos detalhados (Linha a Linha)"):
                    cols_show = ['data_final', 'valor_final', 'status_ped']
                    if 'Cliente' in df_user.columns: cols_show.insert(1, 'Cliente')
                    st.dataframe(df_user[cols_show].sort_values('data_final', ascending=False))
            else: st.warning("Coluna de vendedor não encontrada.")

    st.divider()
    g1, g2 = st.columns(2)
    if col_vend_nome:
        rank = df_filt.groupby(col_vend_nome)['valor_final'].sum().sort_values(ascending=False).head(10).reset_index()
        fig_r = px.bar(rank, x='valor_final', y=col_vend_nome, orientation='h', title="🏆 Top Vendedores Geral", text_auto=True)
        fig_r.update_layout(yaxis=dict(autorange="reversed"))
        g1.plotly_chart(fig_r, use_container_width=True)
    
    evol = df_filt.groupby('data_final')['valor_final'].sum().reset_index()
    fig_l = px.line(evol, x='data_final', y='valor_final', markers=True, title="📈 Evolução Diária Geral")
    g2.plotly_chart(fig_l, use_container_width=True)

else:
    st.error(f"Arquivo '{ARQUIVO_DADOS}' não encontrado.")