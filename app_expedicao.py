
import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import pytz
import time

# ===================== CONFIG =====================
st.set_page_config(page_title="CRM - Expedição", layout="wide", page_icon="📦")
FUSO_SP = pytz.timezone("America/Sao_Paulo")
URL_PLANILHA_MESTRA = st.secrets.get("URL_PLANILHA_MESTRA")

WS_EXPEDICAO = "Expedicao"
WS_LOG = "Expedicao_Log"

# ===================== HELPERS =====================
def agora():
    return datetime.now(FUSO_SP)

def retry(fn, tentativas=3, espera=1):
    for i in range(tentativas):
        try:
            return fn()
        except Exception:
            if i == tentativas - 1:
                raise
            time.sleep(espera)

def ensure_columns(df, cols):
    for c, default in cols.items():
        if c not in df.columns:
            df[c] = default
    return df

def read_sheet(conn, worksheet):
    return retry(lambda: conn.read(spreadsheet=URL_PLANILHA_MESTRA, worksheet=worksheet))

def write_sheet(conn, worksheet, df):
    retry(lambda: conn.update(spreadsheet=URL_PLANILHA_MESTRA, worksheet=worksheet, data=df))

def append_log(conn, row):
    try:
        df = read_sheet(conn, WS_LOG)
    except Exception:
        df = pd.DataFrame(columns=row.keys())
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    write_sheet(conn, WS_LOG, df)

# ===================== APP =====================
st.title("📦 Expedição - Fluxo Operacional")

conn = st.connection("gsheets", type=GSheetsConnection)

df = read_sheet(conn, WS_EXPEDICAO)

df = ensure_columns(df, {
    "Pedido": "",
    "Status": "Emitido",
    "Versao": 0,
    "Separado_Em": "",
    "Faturado_Em": "",
    "Enviado_Em": "",
    "Ultimo_Usuario": "",
})

pedido = st.selectbox("Pedido", sorted(df["Pedido"].astype(str).unique()))

linha = df[df["Pedido"].astype(str) == str(pedido)].iloc[0]
idx = df[df["Pedido"].astype(str) == str(pedido)].index[0]

st.write("### Status atual:", linha["Status"])

col1, col2, col3 = st.columns(3)

def transicionar(novo_status, campo_data):
    atual = read_sheet(conn, WS_EXPEDICAO)
    atual_linha = atual.loc[idx]
    if atual_linha["Versao"] != linha["Versao"]:
        st.warning("Esse pedido foi atualizado por outra pessoa. Recarregando...")
        st.rerun()

    atual.loc[idx, "Status"] = novo_status
    atual.loc[idx, campo_data] = agora().strftime("%d/%m/%Y %H:%M:%S")
    atual.loc[idx, "Versao"] = int(atual_linha["Versao"]) + 1
    atual.loc[idx, "Ultimo_Usuario"] = "usuario_logado"

    write_sheet(conn, WS_EXPEDICAO, atual)

    append_log(conn, {
        "Quando": agora().strftime("%d/%m/%Y %H:%M:%S"),
        "Pedido": pedido,
        "Usuario": "usuario_logado",
        "Acao": novo_status,
        "Status_De": linha["Status"],
        "Status_Para": novo_status
    })

    st.success(f"Pedido {pedido} → {novo_status}")
    st.rerun()

with col1:
    if st.button("Separar"):
        transicionar("Separado", "Separado_Em")

with col2:
    if st.button("Faturar"):
        transicionar("Faturado", "Faturado_Em")

with col3:
    if st.button("Enviar"):
        transicionar("Enviado", "Enviado_Em")

st.divider()
st.subheader("📜 Log de Expedição")
try:
    st.dataframe(read_sheet(conn, WS_LOG))
except Exception:
    st.info("Nenhum log ainda.")
