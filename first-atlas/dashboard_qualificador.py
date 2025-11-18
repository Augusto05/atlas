# dashboard_qualificador.py
import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, datetime
import calendar

# ---------------------------
# Configurações e helpers
# ---------------------------

TABELA_COLUNAS = [
    "DT_1º_CTT", "DT_ULTIMO_CTT", "CNPJ_CLIENTE", "NOME_CLIENTE", "DT_CONTA_CRIADA",
    "STATUS", "DATA_PROMESSA", "CHAVES_PIX_FORTE", "CASH_IN_ATUAL", "C6_PAY",
    "FL_QUALIFICADO", "CRITERIOS_MES_ATUAL", "1º_MES_MOV", "2º_MES_MOV", "3º_MES_MOV"
]

STATUS_QUALIFICADO = "QUALIFICADO"
STATUS_SALDO_MEDIO = "SALDO_MEDIO"
STATUS_PROMESSA = "PROMESSA"

# ---------------------------
# Leitura da planilha
# ---------------------------

@st.cache_data(show_spinner=False)
def carregar_planilha(url_arquivo: str) -> pd.DataFrame:
    """
    Carrega planilha do GitHub (Excel ou CSV).
    - Para Excel: requer 'openpyxl' no requirements.txt.
    """
    if url_arquivo.lower().endswith(".csv"):
        df = pd.read_csv(url_arquivo, dtype=str)
    else:
        # Excel: prioriza a primeira aba
        df = pd.read_excel(url_arquivo, dtype=str)
    # Limpa nomes de colunas (espaços, etc.)
    df.columns = [c.strip() for c in df.columns]
    return df

def to_numeric_safe(series, default=0.0):
    return pd.to_numeric(series, errors="coerce").fillna(default)

def to_date_safe(series):
    # Converte para datetime; aceita formato brasileiro, ISO, etc.
    return pd.to_datetime(series, errors="coerce", dayfirst=True)

# ---------------------------
# Cálculo de dias úteis e projeção
# ---------------------------

def dias_uteis_no_mes(referencia: date, feriados: set) -> int:
    ano = referencia.year
    mes = referencia.month
    _, ultimo_dia = calendar.monthrange(ano, mes)
    dias = [
        date(ano, mes, d)
        for d in range(1, ultimo_dia + 1)
        if date(ano, mes, d).weekday() < 5  # 0-4 = seg-sex
        and date(ano, mes, d) not in feriados
    ]
    return len(dias)

def dias_uteis_passados_no_mes(referencia: date, feriados: set) -> int:
    ano = referencia.year
    mes = referencia.month
    hoje = referencia
    dias = [
        date(ano, mes, d)
        for d in range(1, hoje.day + 1)
        if date(ano, mes, d).weekday() < 5
        and date(ano, mes, d) not in feriados
    ]
    return len(dias)

def calcular_projecao(qtd_qualificadas_so_far: int, referencia: date, feriados: set) -> float:
    uteis_totais = dias_uteis_no_mes(referencia, feriados)
    uteis_passados = dias_uteis_passados_no_mes(referencia, feriados)
    if uteis_passados == 0 or uteis_totais == 0:
        return float(qtd_qualificadas_so_far)
    ritmo_diario = qtd_qualificadas_so_far / uteis_passados
    return ritmo_diario * uteis_totais

# ---------------------------
# Estilo de tabelas
# ---------------------------

def estilizar_tabela(df: pd.DataFrame, cor_hex: str) -> pd.io.formats.style.Styler:
    return df.style.set_properties(**{
        'background-color': cor_hex
    }).set_table_styles([
        {'selector': 'th', 'props': [('background-color', cor_hex)]}
    ])

# ---------------------------
# Filtro por CONSULTOR
# ---------------------------

def filtrar_por_consultor(df: pd.DataFrame, consultor_nome: str) -> pd.DataFrame:
    if "CONSULTOR" not in df.columns:
        st.warning("Coluna 'CONSULTOR' não encontrada na planilha.")
        return df
    # padroniza espaços e case
    return df[df["CONSULTOR"].fillna("").str.strip().str.casefold() == consultor_nome.strip().casefold()]

# ---------------------------
# Seleção de colunas fixas
# ---------------------------

def selecionar_colunas_padrao(df: pd.DataFrame) -> pd.DataFrame:
    cols_existentes = [c for c in TABELA_COLUNAS if c in df.columns]
    return df[cols_existentes].copy()

# ---------------------------
# Dashboard principal
# ---------------------------

def exibir_dashboard(user_config: dict):
    st.title("📊 Dashboard - Equipe de Qualificação")

    # Config entrada: URL da planilha no GitHub
    st.sidebar.subheader("Fonte de dados")
    url_arquivo = st.sidebar.text_input(
        "URL da planilha (GitHub raw)",
        value="https://raw.githubusercontent.com/SEU_USER/SEU_REPO/main/qualificacao.xlsx"
    )

    # Config feriados
    st.sidebar.subheader("Feriados do mês")
    st.sidebar.caption("Adicione feriados manualmente (considerados como não úteis).")
    feriados_input = st.sidebar.date_input(
        "Selecione feriados",
        [],
        help="Você pode selecionar múltiplas datas."
    )
    feriados_set = set(feriados_input) if isinstance(feriados_input, list) else set([feriados_input])

    # Nome do consultor (do login/config.yaml)
    consultor_nome = user_config.get("name", "").strip()
    if not consultor_nome:
        st.warning("Nome do usuário não encontrado no config. Filtro por CONSULTOR pode não funcionar.")

    # Carregar dados
    if not url_arquivo:
        st.info("Informe a URL da planilha no GitHub para carregar os dados.")
        return

    try:
        df_raw = carregar_planilha(url_arquivo)
    except Exception as e:
        st.error(f"Erro ao carregar a planilha: {e}")
        return

    # Preparar campos
    df = df_raw.copy()

    # Normaliza tipos principais usados em filtros e cálculos
    df["STATUS"] = df["STATUS"].fillna("").str.strip().str.upper() if "STATUS" in df.columns else ""
    df["CASH_IN_ATUAL"] = to_numeric_safe(df.get("CASH_IN_ATUAL", pd.Series(dtype=float)), default=0.0)
    df["PREVISAO"] = to_numeric_safe(df.get("PREVISAO", pd.Series(dtype=float)), default=0.0)

    # Datas que podem aparecer nas KPIs/tabelas
    for col in ["DT_1º_CTT", "DT_ULTIMO_CTT", "DT_QUALIFICADA", "DT_CONTA_CRIADA", "DATA_PROMESSA", "DATA_PREVISTA"]:
        if col in df.columns:
            df[col] = to_date_safe(df[col])

    # Filtro por CONSULTOR
    df_consultor = filtrar_por_consultor(df, consultor_nome)

    # KPIs (Resumo rápido)
    st.subheader("Resumo rápido")

    # Contas qualificadas
    qtd_qualificadas = int((df_consultor["STATUS"] == STATUS_QUALIFICADO).sum())
    # Contas em saldo médio
    qtd_saldo_medio = int((df_consultor["STATUS"] == STATUS_SALDO_MEDIO).sum())
    # Promessas
    qtd_promessas = int((df_consultor["STATUS"] == STATUS_PROMESSA).sum())
    # Projeção (com dias úteis + feriados)
    proj = calcular_projecao(qtd_qualificadas, date.today(), feriados_set)
    # Faturamento total (somar PREVISAO onde STATUS = QUALIFICADO)
    faturamento_total = float(df_consultor.loc[df_consultor["STATUS"] == STATUS_QUALIFICADO, "PREVISAO"].sum())
    # Balde (total de clientes do consultor)
    balde_total = int(df_consultor.shape[0])

    # Exibir métricas
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Contas qualificadas", f"{qtd_qualificadas}")
    col2.metric("Saldo médio", f"{qtd_saldo_medio}")
    col3.metric("Promessas", f"{qtd_promessas}")
    col4.metric("Projeção (dias úteis)", f"{proj:.1f}")
    col5.metric("Faturamento total (R$)", f"{faturamento_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    col6.metric("Balde (clientes)", f"{balde_total}")

    st.divider()

    # Tabela 1: Prestes a qualificar (CASH_IN_ATUAL > 1000 e < 6000; não qualificadas)
    st.subheader("Clientes prestes a qualificar")
    df_prestes = df_consultor[
        (df_consultor["CASH_IN_ATUAL"] > 1000) &
        (df_consultor["CASH_IN_ATUAL"] < 6000) &
        (df_consultor["STATUS"] != STATUS_QUALIFICADO)
    ]
    df_prestes = selecionar_colunas_padrao(df_prestes)
    st.dataframe(
        estilizar_tabela(df_prestes, "#E7F0FF"),  # azul claro
        use_container_width=True
    )

    st.divider()

    # Tabela 2: Qualificadas
    st.subheader("Clientes qualificados")
    df_qual = df_consultor[df_consultor["STATUS"] == STATUS_QUALIFICADO]
    df_qual = selecionar_colunas_padrao(df_qual)
    st.dataframe(
        estilizar_tabela(df_qual, "#E9F7EF"),  # verde claro
        use_container_width=True
    )

    st.divider()

    # Tabela 3: Promessas (expandível)
    st.subheader("Promessas")
    with st.expander("Mostrar/ocultar promessas", expanded=False):
        df_prom = df_consultor[df_consultor["STATUS"] == STATUS_PROMESSA]
        df_prom = selecionar_colunas_padrao(df_prom)
        st.dataframe(
            estilizar_tabela(df_prom, "#FFF9E6"),  # amarelo claro
            use_container_width=True
        )

    st.divider()

    # Tabela 4: Balde completo
    st.subheader("Balde completo de clientes")
    df_balde = selecionar_colunas_padrao(df_consultor)
    st.dataframe(
        df_balde,  # balde sem fundo colorido para ficar neutro
        use_container_width=True
    )
