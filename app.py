import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import numpy as np
import json
import calendar
import re
import datetime
from datetime import date, timedelta

# ==============================================================================
# CONFIGURAÇÕES
# ==============================================================================
st.set_page_config(page_title="Dashboard MIC", layout="wide")

# ==============================================================================
# CONEXÃO COM GOOGLE SHEETS (streamlit_gsheets)
# ==============================================================================
# OBS: No seu projeto, a URL/ID da planilha está sendo usada diretamente.
# Se você alterou o nome da planilha/worksheet, ajuste aqui.
URL_PLANILHA_MESTRA = "https://docs.google.com/spreadsheets/d/1y7y0X_1eXzz_7ySBQw2f0wF2u5wN1gKQGJwR9vCjVQk/edit#gid=0"

# Conexão
conn = st.connection("gsheets", type=GSheetsConnection)

# ==============================================================================
# UTILITÁRIOS
# ==============================================================================
def limpar_dado(x):
    """
    Normaliza valores para string "limpa".
    Remove .0 do final (muito comum quando vem de planilha como float).
    """
    if x is None:
        return ""
    s = str(x).strip()
    if s.lower() == "nan":
        return ""
    # tira o ".0" do fim (ex: "123.0" -> "123")
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    return s


# ==============================================================================
# --- CARGA DE VENDAS (CACHEADO POR 10 MINUTOS) ---
# ==============================================================================
@st.cache_data(ttl=600)
def carregar_dados_vendas_cache():
    """
    Lê a aba principal da planilha mestra (vendas) usando cache.
    TTL 600s (10min) para não estourar cota da API.
    """
    try:
        df = conn.read(spreadsheet=URL_PLANILHA_MESTRA, ttl=600)
        if df is None or df.empty:
            return None
        return df
    except Exception as e:
        print(f"Erro Cache Vendas: {e}")
        return None


# ==============================================================================
# --- GESTÃO DE USUÁRIOS ---
# ==============================================================================
def inicializar_e_carregar_usuarios():
    """
    Garante a estrutura mínima de usuários e retorna df.
    """
    try:
        df = conn.read(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Usuarios", ttl=10)
        if df is None or df.empty:
            df = pd.DataFrame(columns=["Login", "Senha", "Meta", "Nome", "Meta_Rep", "Config_Layout", "Cargo"])
            conn.update(data=df, spreadsheet=URL_PLANILHA_MESTRA, worksheet="Usuarios")
            return df

        # Garantir colunas
        changed = False
        cols_need = ["Login", "Senha", "Meta", "Nome", "Meta_Rep", "Config_Layout", "Cargo"]
        for c in cols_need:
            if c not in df.columns:
                df[c] = "{}" if "Meta" in c else ""
                changed = True
        if changed:
            conn.update(data=df, spreadsheet=URL_PLANILHA_MESTRA, worksheet="Usuarios")
        return df
    except Exception:
        return pd.DataFrame(columns=["Login", "Senha", "Meta", "Nome", "Meta_Rep", "Config_Layout", "Cargo"])


df_usuarios = inicializar_e_carregar_usuarios()
META_GERAL_EMPRESA = 100000.0
usuarios_dict = {}

if df_usuarios is not None and not df_usuarios.empty:
    for _, row in df_usuarios.iterrows():
        login = limpar_dado(row.get("Login", ""))
        if not login or login == "__G":  # ignora lixo / linha inválida
            continue

        usuarios_dict[login] = {
            "senha": limpar_dado(row.get("Senha", "")),
            "meta": float(str(row.get("Meta", "0")).replace(",", ".") or 0),
            "nome": limpar_dado(row.get("Nome", login)),
            "meta_rep": row.get("Meta_Rep", "{}"),
            "config_layout": row.get("Config_Layout", "{}"),
            "cargo": limpar_dado(row.get("Cargo", "")),
        }


# ==============================================================================
# EXPEDIÇÃO (usa aba Expedicao, e cruza com Pedidos/NF de vendas)
# ==============================================================================
def carregar_dados_expedicao(df_vendas_atual, col_pedido_vendas, col_nf_vendas):
    """
    Mantém a aba de expedição atualizada com base nas vendas.
    """
    cols_exp = [
        "Pedido", "Cliente", "Vendedor", "Status_Atual",
        "Data_Emitido", "Data_Separacao", "Data_Separado", "Data_Faturado", "Data_Enviado",
        "User_Separacao", "User_Separado", "User_Faturado", "User_Enviado", "Log_Historico"
    ]

    try:
        df_exp = conn.read(spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao", ttl=10)
        if df_exp is None or df_exp.empty or ("Pedido" not in df_exp.columns):
            df_exp = pd.DataFrame(columns=cols_exp)
        else:
            for c in cols_exp:
                if c not in df_exp.columns:
                    df_exp[c] = ""
            df_exp = df_exp.astype(str)
    except Exception:
        df_exp = pd.DataFrame(columns=cols_exp)

    # Se não tem vendas ou coluna pedido, retorna expedição como está
    if df_vendas_atual is None or df_vendas_atual.empty or not col_pedido_vendas:
        return df_exp

    # Monta set de pedidos atuais nas vendas
    pedidos_vendas = set(df_vendas_atual[col_pedido_vendas].astype(str).str.strip())

    # Monta set de pedidos já existentes na expedição
    pedidos_exp = set(df_exp["Pedido"].astype(str).str.strip()) if not df_exp.empty else set()

    # Adiciona os pedidos que estão nas vendas e não estão na expedição
    novos = pedidos_vendas - pedidos_exp
    if not novos:
        return df_exp

    agora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

    novos_dados = []
    for p in sorted(novos):
        try:
            row_venda = df_vendas_atual[df_vendas_atual[col_pedido_vendas].astype(str).str.strip() == p].iloc[0]

            tem_nf = False
            if col_nf_vendas and (col_nf_vendas in df_vendas_atual.columns):
                nf_val = str(row_venda.get(col_nf_vendas, "")).strip()
                # Corrigido: 0/0.0/vazio/nan NÃO conta como NF
                tem_nf = nf_val not in ("", "0", "0.0", "nan", "NaN", "None")

            status_ini = "Faturado" if tem_nf else "Emitido"
            data_fat = agora if tem_nf else ""
            log_ini = f"[{agora}] Pedido importado como {status_ini}"

            novos_dados.append({
                "Pedido": str(p),
                "Cliente": str(row_venda.get("Cliente", "")),
                "Vendedor": str(row_venda.get("Vendedor", "")),
                "Status_Atual": status_ini,
                "Data_Emitido": agora,
                "Data_Separacao": "",
                "Data_Separado": "",
                "Data_Faturado": data_fat,
                "Data_Enviado": "",
                "User_Separacao": "",
                "User_Separado": "",
                "User_Faturado": "",
                "User_Enviado": "",
                "Log_Historico": log_ini
            })
        except Exception as e:
            print(f"Erro ao importar pedido {p}: {e}")

    if novos_dados:
        df_novos = pd.DataFrame(novos_dados)
        df_exp = pd.concat([df_exp, df_novos], ignore_index=True)

        # Salva de volta na planilha
        try:
            conn.update(data=df_exp, spreadsheet=URL_PLANILHA_MESTRA, worksheet="Expedicao")
        except Exception as e:
            print(f"Erro ao atualizar Expedicao: {e}")

    return df_exp


# ==============================================================================
# 📥 PROCESSAMENTO DE DADOS VENDAS (PADRONIZAÇÃO BLINDADA)
# ------------------------------------------------------------------------------
# Objetivo:
# - Aceitar dados vindos do Google Sheets (streamlit_gsheets) OU CSV exportado do Excel.
# - Normalizar:
#   * data (dd/mm/aaaa) -> datetime normalizado
#   * valor (1.234,56) / (1234.56) / (R$ 1.234,56) -> float
#   * NF / Pedido (floats tipo 123.0) -> string "123"
# - Criar colunas padrão usadas no dashboard:
#   data_processada, valor_final, status_ped, id_pedido
# ==============================================================================
def processar_dados_vendas(df):
    if df is None or df.empty:
        return None, None, [], None, None

    def _norm_str(x) -> str:
        """Normaliza qualquer coisa para string limpinha."""
        if x is None:
            return ""
        s = str(x).strip()
        if s.lower() == "nan":
            return ""
        return s

    def _normalizar_id(x) -> str:
        """Transforma 123.0 -> '123' e mantém strings."""
        s = _norm_str(x)
        if not s:
            return ""
        # Alguns conectores/CSV trazem como float: '123.0'
        if re.fullmatch(r"\d+\.0", s):
            return s[:-2]
        # Às vezes vem '123,0' dependendo da origem
        if re.fullmatch(r"\d+,0", s):
            return s[:-2]
        return s

    def _parse_valor_brl(v) -> float:
        """Converte valores no padrão BR (1.234,56) para float."""
        if v is None:
            return 0.0
        # já é número?
        if isinstance(v, (int, float)) and not pd.isna(v):
            return float(v)

        s = _norm_str(v)
        if not s:
            return 0.0

        # remove moeda e espaços
        s = s.replace("R$", "").strip()

        # Se tem vírgula, assumimos padrão BR: '.' milhar e ',' decimal
        # Ex: 2.773,79 -> 2773.79
        s = s.replace(".", "").replace(",", ".")

        try:
            return float(s)
        except:
            return 0.0

    def _parse_data(x):
        """Converte dd/mm/aaaa (ou variações) em datetime (normalizado)."""
        if pd.isna(x):
            return pd.NaT

        # Se já for datetime, mantém
        if isinstance(x, (pd.Timestamp, datetime.datetime)):
            return pd.to_datetime(x).normalize()

        # Alguns conectores trazem date puro
        if isinstance(x, datetime.date):
            return pd.to_datetime(x).normalize()

        s = _norm_str(x)
        if not s:
            return pd.NaT

        # tenta dd/mm/aaaa primeiro (seu padrão)
        dt = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
        if pd.isna(dt):
            # fallback geral (dayfirst=True ajuda muito no BR)
            dt = pd.to_datetime(s, dayfirst=True, errors="coerce")

        if pd.isna(dt):
            return pd.NaT
        return pd.to_datetime(dt).normalize()

    def _tem_nf(x) -> bool:
        """Define se um pedido está faturado. Trata 0/0.0/vazio como sem NF."""
        s = _normalizar_id(x)
        if not s:
            return False
        if s in {"0", "0.0", "0,0"}:
            return False
        return True

    try:
        # ----------------------------------------------------------------------
        # 1) Limpeza básica de colunas
        # ----------------------------------------------------------------------
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]

        # Remove colunas lixo do Excel (ex.: "Unnamed: 11")
        df = df.loc[:, ~df.columns.str.contains(r"^Unnamed", na=False)]

        cols = list(df.columns)

        # ----------------------------------------------------------------------
        # 2) Descobrir colunas importantes (com prioridade bem definida)
        # ----------------------------------------------------------------------
        def _pick_col(candidates):
            for cand in candidates:
                for c in cols:
                    if cand.lower() in c.lower():
                        return c
            return None

        # Data: prioridade máxima para Geração/Geracao
        col_data = _pick_col(["Geração", "Geracao", "Emissão", "Emissao", "Data"])
        # Valor: seu modelo usa "Valor Líquido"
        col_valor = _pick_col(["Valor Líquido", "Valor Liquido", "Valor", "Liq"])
        col_nf = _pick_col(["NF", "Nota"])
        col_pedido = _pick_col(["Pedido"])
        col_vend_orig = _pick_col(["Vendedor", "Vend"])
        col_rep_orig = _pick_col(["Representante", "Rep"])
        col_cnpj_orig = _pick_col(["CNPJ", "CGC"])
        col_cli_orig = _pick_col(["Cliente", "Cli"])

        if not col_valor or not col_data:
            # Sem essas duas, não tem como montar o dashboard
            return None, None, [], None, None

        # Padroniza nomes “sociais”
        rename_map = {}
        if col_cnpj_orig: rename_map[col_cnpj_orig] = "CNPJ"
        if col_rep_orig: rename_map[col_rep_orig] = "Representante"
        if col_cli_orig: rename_map[col_cli_orig] = "Cliente"
        if col_vend_orig: rename_map[col_vend_orig] = "Vendedor"
        if col_pedido: rename_map[col_pedido] = "Pedido"
        if col_nf: rename_map[col_nf] = "NF"

        df.rename(columns=rename_map, inplace=True)

        # ----------------------------------------------------------------------
        # 3) Garantir colunas essenciais com defaults (evita drop/KeyError)
        # ----------------------------------------------------------------------
        if "CNPJ" not in df.columns: df["CNPJ"] = "-"
        df["CNPJ"] = df["CNPJ"].fillna("-").astype(str)

        if "Representante" not in df.columns: df["Representante"] = "Geral"
        df["Representante"] = df["Representante"].fillna("Geral").astype(str)

        if "Cliente" not in df.columns: df["Cliente"] = "Consumidor"
        df["Cliente"] = df["Cliente"].fillna("Consumidor").astype(str)

        if "Vendedor" not in df.columns: df["Vendedor"] = "Geral"
        df["Vendedor"] = df["Vendedor"].fillna("Geral").astype(str)

        col_vend = "Vendedor"

        # ----------------------------------------------------------------------
        # 4) Normalização de VALOR e DATA
        # ----------------------------------------------------------------------
        df["valor_final"] = df[col_valor].apply(_parse_valor_brl)

        df["data_processada"] = df[col_data].apply(_parse_data)
        df = df.dropna(subset=["data_processada"])  # remove linhas sem data válida

        # ----------------------------------------------------------------------
        # 5) Status e ID do pedido (para contagem e ticket médio)
        # ----------------------------------------------------------------------
        if "NF" in df.columns:
            df["status_ped"] = df["NF"].apply(lambda x: "Faturado" if _tem_nf(x) else "A Faturar")
        else:
            df["status_ped"] = "Desconhecido"

        # Se não tiver Pedido, cai para NF; se não tiver nenhum, usa índice
        if "Pedido" in df.columns:
            df["id_pedido"] = df["Pedido"].apply(_normalizar_id)
        elif "NF" in df.columns:
            df["id_pedido"] = df["NF"].apply(_normalizar_id)
        else:
            df["id_pedido"] = df.index.astype(str)

        # Remove vazios do id_pedido (evita nunique=0 quando deveria contar)
        df["id_pedido"] = df["id_pedido"].replace("", pd.NA).fillna(df.index.astype(str))

        # Lista reps para as abas
        lista_reps = sorted([r for r in df["Representante"].dropna().unique().tolist() if str(r).strip()])

        # Retorna colunas detectadas (pra integrar com expedição)
        col_pedido_out = "Pedido" if "Pedido" in df.columns else ("NF" if "NF" in df.columns else None)
        col_nf_out = "NF" if "NF" in df.columns else None

        return df, col_vend, lista_reps, col_pedido_out, col_nf_out

    except Exception as e:
        print(f"Erro processamento vendas: {e}")
        return None, None, [], None, None


# ==============================================================================
# --- VISUAL E UTILITÁRIOS ---
# ==============================================================================
def calcular_dias_uteis_restantes_mes():
    hoje = date.today()
    ultimo = calendar.monthrange(hoje.year, hoje.month)[1]
    fim = date(hoje.year, hoje.month, ultimo)
    if hoje > fim:
        return 0
    return max(0, int(np.busday_count(hoje, fim + timedelta(days=1))))


def calcular_dias_uteis_passados_mes():
    hoje = date.today()
    inicio = date(hoje.year, hoje.month, 1)
    if hoje < inicio:
        return 0
    return max(1, int(np.busday_count(inicio, hoje + timedelta(days=1))))


def barra_progresso_linda(atual, meta, titulo="Progresso"):
    pct = (atual / meta * 100) if meta > 0 else 0
    vis = min(pct, 100)
    st.markdown(f"**{titulo}**")
    st.progress(vis / 100)
    st.caption(f"{pct:.1f}% | Realizado: R$ {atual:,.2f} | Meta: R$ {meta:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))


# ==============================================================================
# APP PRINCIPAL
# ==============================================================================
def main():
    st.markdown("## 📊 Dashboard Vendas MIC")

    # --------------------------------------------------------------------------
    # Carrega dados
    # --------------------------------------------------------------------------
    df_raw = carregar_dados_vendas_cache()
    df_proc, col_vend, lista_reps, col_pedido, col_nf = processar_dados_vendas(df_raw)

    if df_proc is None or df_proc.empty:
        st.warning("Não encontrei dados válidos de vendas. Verifique a planilha/aba e o formato das colunas.")
        return

    # --------------------------------------------------------------------------
    # Filtros
    # --------------------------------------------------------------------------
    colA, colB = st.columns([2, 2])

    with colA:
        status_sel = st.selectbox("Status", ["Todos", "Faturado", "A Faturar", "Desconhecido"], index=0)

    with colB:
        # Streamlit pode retornar tuple (data_ini, data_fim) em versões novas
        periodo = st.date_input(
            "Período",
            value=(df_proc["data_processada"].min().date(), df_proc["data_processada"].max().date())
        )

    df_filt = df_proc.copy()

    # Filtro status
    if status_sel != "Todos":
        df_filt = df_filt[df_filt["status_ped"] == status_sel]

    # Filtro período (CORRIGIDO: aceita list OU tuple)
    if isinstance(periodo, (list, tuple)) and len(periodo) == 2:
        dt_ini = pd.to_datetime(periodo[0]).normalize()
        dt_fim = pd.to_datetime(periodo[1]).normalize()
        df_filt = df_filt[(df_filt["data_processada"] >= dt_ini) & (df_filt["data_processada"] <= dt_fim)]

    # --------------------------------------------------------------------------
    # Métricas gerais
    # --------------------------------------------------------------------------
    meta_geral = 5488637.60  # seu valor da tela (ajuste se vem do usuário/meta)
    total = float(df_filt["valor_final"].sum())
    pedidos = int(df_filt["id_pedido"].nunique())
    ticket = total / pedidos if pedidos > 0 else 0.0

    dias_uteis = calcular_dias_uteis_restantes_mes()
    dias_passados = calcular_dias_uteis_passados_mes()
    falta = max(0.0, meta_geral - total)
    diaria_nec = falta / dias_uteis if dias_uteis > 0 else falta

    st.markdown("### 🏢 Meta MIC (Empresa)")
    barra_progresso_linda(total, meta_geral, "Progresso Geral")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Vendas Totais", f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c2.metric("Diária Nec.", f"R$ {diaria_nec:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c3.metric("Falta", f"R$ {falta:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c4.metric("Ticket Médio", f"R$ {ticket:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

    st.divider()

    # --------------------------------------------------------------------------
    # Performance individual (exemplo: filtro por nome)
    # --------------------------------------------------------------------------
    st.markdown("### 👤 Performance Individual")
    nome = st.text_input("Filtrar meu nome:", "")

    df_ind = df_filt.copy()
    if nome.strip():
        df_ind = df_ind[df_ind[col_vend].astype(str).str.contains(nome, case=False, na=False)]

    total_ind = float(df_ind["valor_final"].sum())
    pedidos_ind = int(df_ind["id_pedido"].nunique())
    ticket_ind = total_ind / pedidos_ind if pedidos_ind > 0 else 0.0

    falta_ind = max(0.0, 610336.50 - total_ind)  # exemplo/meta individual fixa (ajuste conforme seu sistema)
    diaria_nec_ind = falta_ind / dias_uteis if dias_uteis > 0 else falta_ind

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Minhas Vendas", f"R$ {total_ind:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c2.metric("Falta", f"R$ {falta_ind:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c3.metric("Diária Nec.", f"R$ {diaria_nec_ind:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c4.metric("Ticket Médio", f"R$ {ticket_ind:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

    # --------------------------------------------------------------------------
    # Debug opcional (ajuda MUITO quando dá zero e você quer ver o porquê)
    # --------------------------------------------------------------------------
    with st.expander("🔍 Debug (ver dados filtrados)"):
        st.write("Linhas após filtro:", len(df_filt))
        st.dataframe(df_filt.head(200))


if __name__ == "__main__":
    main()
