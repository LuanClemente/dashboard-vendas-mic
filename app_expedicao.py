import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import time

# Configurações básicas
st.set_page_config(page_title="Controle de Expedição MIC", layout="wide", page_icon="📦")

# Conexão
conn = st.connection("gsheets", type=GSheetsConnection)

# --- FUNÇÕES AUXILIARES ---

def carregar_dados():
    # 1. Carrega Vendas (Sua base original)
    df_vendas = conn.read(worksheet="Página1", ttl=0) # Ajuste o nome da aba se não for Página1
    # Limpeza básica (igual fizemos antes)
    df_vendas.columns = [c.strip() for c in df_vendas.columns]
    # Garante que temos a coluna Pedido como string
    col_pedido = next((c for c in df_vendas.columns if 'Pedido' in c or 'NF' in c), 'Pedido')
    df_vendas[col_pedido] = df_vendas[col_pedido].astype(str).str.split('.').str[0]
    
    # 2. Carrega Expedição (A nova aba)
    try:
        df_exp = conn.read(worksheet="Expedicao", ttl=0)
        if df_exp.empty:
            df_exp = pd.DataFrame(columns=['Pedido', 'Cliente', 'Vendedor', 'Status_Atual', 
                                         'Data_Emitido', 'Data_Separacao', 'Data_Separado', 
                                         'Data_Faturado', 'Data_Enviado'])
    except:
        # Se não existir, cria o DF vazio na memória
        df_exp = pd.DataFrame(columns=['Pedido', 'Cliente', 'Vendedor', 'Status_Atual', 
                                     'Data_Emitido', 'Data_Separacao', 'Data_Separado', 
                                     'Data_Faturado', 'Data_Enviado'])
    
    # Garante que Pedido é string para comparação
    df_exp['Pedido'] = df_exp['Pedido'].astype(str).str.split('.').str[0]
    
    return df_vendas, df_exp, col_pedido

def sincronizar_pedidos(df_vendas, df_exp, col_pedido_vendas):
    """Pega pedidos novos da venda e joga na expedição"""
    pedidos_vendas = set(df_vendas[col_pedido_vendas].unique())
    pedidos_exp = set(df_exp['Pedido'].unique())
    
    novos = pedidos_vendas - pedidos_exp
    novos = [p for p in novos if p and p != 'nan'] # Remove vazios
    
    if novos:
        novos_dados = []
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")
        
        for p in novos:
            # Pega dados do cliente/vendedor da base de vendas
            row_venda = df_vendas[df_vendas[col_pedido_vendas] == p].iloc[0]
            col_cli = next((c for c in df_vendas.columns if 'Cliente' in c), 'Cliente')
            col_vend = next((c for c in df_vendas.columns if 'Vendedor' in c), 'Vendedor')
            
            novos_dados.append({
                'Pedido': str(p),
                'Cliente': str(row_venda.get(col_cli, '')),
                'Vendedor': str(row_venda.get(col_vend, '')),
                'Status_Atual': 'Emitido',
                'Data_Emitido': agora,
                'Data_Separacao': '', 'Data_Separado': '', 
                'Data_Faturado': '', 'Data_Enviado': ''
            })
        
        if novos_dados:
            df_novo = pd.DataFrame(novos_dados)
            df_final = pd.concat([df_exp, df_novo], ignore_index=True)
            conn.update(worksheet="Expedicao", data=df_final)
            return df_final
            
    return df_exp

def atualizar_status(pedido, novo_status, coluna_data):
    df_exp = conn.read(worksheet="Expedicao", ttl=0)
    df_exp['Pedido'] = df_exp['Pedido'].astype(str).str.split('.').str[0]
    
    idx = df_exp.index[df_exp['Pedido'] == str(pedido)].tolist()
    
    if idx:
        i = idx[0]
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")
        df_exp.at[i, 'Status_Atual'] = novo_status
        df_exp.at[i, coluna_data] = agora
        conn.update(worksheet="Expedicao", data=df_exp)
        return True
    return False

# --- INTERFACE ---

st.title("📦 Controle de Expedição")

# Simulação de Login (Integre com seu sistema de login oficial)
# Aqui estou assumindo que você salvou o usuário na session_state no app principal
if 'usuario_logado' not in st.session_state:
    st.session_state['usuario_logado'] = st.text_input("Simular Login (digite 'expedicao' ou 'vendedor'):")

usuario = st.session_state['usuario_logado']
is_expedicao = (usuario == 'expedicao' or usuario == 'admin')

if usuario:
    st.info(f"Logado como: **{usuario}** | Perfil: {'👮‍♂️ Expedição' if is_expedicao else '👤 Vendas'}")
    
    # 1. Carga e Sincronização
    with st.spinner("Sincronizando pedidos..."):
        df_vendas, df_exp, col_ped = carregar_dados()
        df_exp = sincronizar_pedidos(df_vendas, df_exp, col_ped)

    # 2. Filtros
    status_filter = st.multiselect("Filtrar Status", df_exp['Status_Atual'].unique(), default=df_exp['Status_Atual'].unique())
    search = st.text_input("Buscar Pedido ou Cliente")
    
    df_view = df_exp[df_exp['Status_Atual'].isin(status_filter)]
    if search:
        df_view = df_view[
            df_view['Pedido'].str.contains(search, case=False) | 
            df_view['Cliente'].str.contains(search, case=False)
        ]

    # Ordenar: Mais recentes primeiro
    # (Conversão simples para sort, idealmente converter para datetime real)
    df_view = df_view.iloc[::-1] 

    st.divider()

    # 3. Lista de Cards (Estilo Kanban em Lista)
    for index, row in df_view.iterrows():
        status = row['Status_Atual']
        pedido = row['Pedido']
        cliente = row['Cliente']
        
        # Cor da borda baseada no status
        cor_status = "gray"
        if status == "Emitido": cor_status = "blue"
        elif status == "Em Separação": cor_status = "orange"
        elif status == "Separado": cor_status = "purple"
        elif status == "Faturado": cor_status = "teal"
        elif status == "Enviado": cor_status = "green"

        with st.container():
            # Layout do Card
            c1, c2, c3, c4, c5 = st.columns([1, 2, 2, 2, 2])
            
            with c1:
                st.markdown(f"### 📦 {pedido}")
                st.caption(f"{row['Vendedor']}")
            
            with c2:
                st.markdown(f"**{cliente}**")
                st.markdown(f":{cor_status}[● {status}]")
            
            with c3:
                # Mostra o histórico de datas preenchidas
                if row['Data_Emitido']: st.caption(f"📅 Emit: {row['Data_Emitido']}")
                if row['Data_Separacao']: st.caption(f"🖐️ Separação: {row['Data_Separacao']}")
                if row['Data_Separado']: st.caption(f"📦 Separado: {row['Data_Separado']}")
            
            with c4:
                if row['Data_Faturado']: st.caption(f"💲 Faturado: {row['Data_Faturado']}")
                if row['Data_Enviado']: st.caption(f"🚚 Enviado: {row['Data_Enviado']}")

            with c5:
                # --- LÓGICA DE BOTÕES (A Mágica) ---
                
                # Fase 1: Emitido -> Em Separação (Só Expedição)
                if status == "Emitido":
                    if is_expedicao:
                        if st.button("▶️ Iniciar Separação", key=f"btn1_{pedido}"):
                            atualizar_status(pedido, "Em Separação", "Data_Separacao")
                            st.rerun()
                    else:
                        st.info("Aguardando Expedição")

                # Fase 2: Em Separação -> Separado (Só Expedição)
                elif status == "Em Separação":
                    if is_expedicao:
                        if st.button("✅ Finalizar Separação", key=f"btn2_{pedido}"):
                            atualizar_status(pedido, "Separado", "Data_Separado")
                            st.rerun()
                    else:
                        st.warning("Em Separação...")

                # Fase 3: Separado -> Faturado (Qualquer um ou Só Vendedor)
                elif status == "Separado":
                    # Aqui você pediu pro Vendedor poder marcar.
                    # Vou liberar pra todos (Expedição também pode precisar marcar)
                    if st.button("💲 Marcar Faturado", key=f"btn3_{pedido}"):
                        atualizar_status(pedido, "Faturado", "Data_Faturado")
                        st.rerun()

                # Fase 4: Faturado -> Enviado (Só Expedição)
                elif status == "Faturado":
                    if is_expedicao:
                        if st.button("🚚 Despachar / Enviar", key=f"btn4_{pedido}"):
                            atualizar_status(pedido, "Enviado", "Data_Enviado")
                            st.rerun()
                    else:
                        st.success("Pronto para Envio")
                
                elif status == "Enviado":
                    st.success("Concluído! 🚀")

            st.markdown("---")

else:
    st.warning("Faça login para acessar.")