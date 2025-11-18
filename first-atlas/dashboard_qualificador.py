# dashboard_qualificador.py
import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, datetime
import calendar
import plotly.express as px

# ---------------------------
# Configurações fixas
# ---------------------------

TABELA_COLUNAS = [
    "DT_1º_CTT", "DT_ULTIMO_CTT", "CNPJ_CLIENTE", "NOME_CLIENTE", "DT_CONTA_CRIADA",
    "STATUS", "DATA_PROMESSA", "CHAVES_PIX_FORTE", "CASH_IN_ATUAL", "C6_PAY",
    "FL_QUALIFICADO", "CRITERIOS_MES_ATUAL", "1º_MES_MOV", "2º_MES_MOV", "3º_MES_MOV"
]

STATUS_QUALIFICADO = "QUALIFICADO"
STATUS_SALDO_MEDIO = "SALDO_MEDIO"
STATUS_PROMESSA = "PROMESSA"

# Feriados nacionais fixos (exemplo Brasil 2025)
FERIADOS_FIXOS = {
    date(2026, 1, 1),   # Confraternização Universal
    date(2026, 1, 25),  # Aniversário de SP
    date(2026, 2, 17),  # Carnaval
    date(2026, 4, 21),  # Tiradentes
    date(2026, 5, 1),   # Dia do Trabalho
    date(2026, 7, 9),   # Revolução Constitucionalista
    date(2026, 9, 7),   # Independência
    date(2026, 10, 12), # Nossa Senhora Aparecida
    date(2026, 11, 2),  # Finados
    date(2026, 11, 15), # Proclamação da República
    date(2025, 11, 20), # Consciência Negra
    date(2025, 12, 25), # Natal
}

# ---------------------------
# Helpers
# ---------------------------

@st.cache_data(show_spinner=False)
def carregar_planilha(url_arquivo: str) -> pd.DataFrame:
    if url_arquivo.lower().endswith(".csv"):
        df = pd.read_csv(url_arquivo)
    else:
        df = pd.read_excel(url_arquivo)
    df.columns = [c.strip() for c in df.columns]
    return df

def to_numeric_safe(series, default=0.0):
    return pd.to_numeric(series, errors="coerce").fillna(default).round(2)

def to_date_safe(series):
    return pd.to_datetime(series, errors="coerce", dayfirst=True).dt.date

def dias_uteis_no_mes(referencia: date, feriados: set) -> int:
    ano, mes = referencia.year, referencia.month
    _, ultimo_dia = calendar.monthrange(ano, mes)
    dias = [
        date(ano, mes, d)
        for d in range(1, ultimo_dia + 1)
        if date(ano, mes, d).weekday() < 5 and date(ano, mes, d) not in feriados
    ]
    return len(dias)

def dias_uteis_passados_no_mes(referencia: date, feriados: set) -> int:
    ano, mes = referencia.year, referencia.month
    hoje = referencia
    dias = [
        date(ano, mes, d)
        for d in range(1, hoje.day)  # até ontem
        if date(ano, mes, d).weekday() < 5 and date(ano, mes, d) not in feriados
    ]
    return len(dias)

def calcular_projecao(qtd_qualificadas_so_far: int, referencia: date, feriados: set) -> float:
    uteis_totais = dias_uteis_no_mes(referencia, feriados)
    uteis_passados = dias_uteis_passados_no_mes(referencia, feriados)
    if uteis_passados == 0 or uteis_totais == 0:
        return float(qtd_qualificadas_so_far)
    ritmo_diario = qtd_qualificadas_so_far / uteis_passados
    return ritmo_diario * uteis_totais

def formatar_tabela(df: pd.DataFrame, cor_hex: str) -> pd.io.formats.style.Styler:
    df = df.copy().reset_index(drop=True)

    # Formata datas
    campos_data = [col for col in df.columns if "DT_" in col or "DATA_" in col or col == "C6_PAY"]
    for col in campos_data:
        if pd.api.types.is_datetime64_any_dtype(df[col]) or pd.api.types.is_object_dtype(df[col]):
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%d/%m/%Y")

    # Formata valores monetários e movimentações
    campos_valores = ["CASH_IN_ATUAL", "1º_MES_MOV", "2º_MES_MOV", "3º_MES_MOV"]
    for campo in campos_valores:
        if campo in df.columns:
            df[campo] = pd.to_numeric(df[campo], errors="coerce").fillna(0).round(2)
            df[campo] = df[campo].map(lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

    # Formata FL_QUALIFICADO como inteiro
    if "FL_QUALIFICADO" in df.columns:
        df["FL_QUALIFICADO"] = pd.to_numeric(df["FL_QUALIFICADO"], errors="coerce").fillna(0).astype(int)

    # Estilo com cor de fundo e índice pintado
    return df.style.set_properties(**{'background-color': cor_hex}).set_table_styles([
        {'selector': 'th', 'props': [('background-color', cor_hex)]},
        {'selector': 'tbody th', 'props': [('background-color', cor_hex)]}
    ])

def estilizar_tabela(df: pd.DataFrame, cor_hex: str) -> pd.io.formats.style.Styler:
    return df.style.set_properties(**{'background-color': cor_hex}).set_table_styles([
        {'selector': 'th', 'props': [('background-color', cor_hex)]},       # cabeçalho
        {'selector': 'tbody th', 'props': [('background-color', cor_hex)]} # índice
    ])

def filtrar_por_consultor(df: pd.DataFrame, consultor_nome: str) -> pd.DataFrame:
    if "CONSULTOR" not in df.columns:
        return df
    return df[df["CONSULTOR"].fillna("").str.strip().str.casefold() == consultor_nome.strip().casefold()]

def selecionar_colunas_padrao(df: pd.DataFrame) -> pd.DataFrame:
    cols_existentes = [c for c in TABELA_COLUNAS if c in df.columns]
    return df[cols_existentes].reset_index(drop=True)

# ---------------------------
# Dashboard principal
# ---------------------------
def exibir_dashboard(user_config: dict):
    
    st.title("📊 Dashboard - Qualificação")

    url_arquivo = "https://github.com/Augusto05/atlas/raw/refs/heads/main/first-atlas/balde_2025-11.xlsx"

    try:
        df_raw = carregar_planilha(url_arquivo)
    except Exception as e:
        st.error(f"Erro ao carregar a planilha: {e}")
        return

    df = df_raw.copy()

    # Normaliza campos
    if "STATUS" in df.columns:
        df["STATUS"] = df["STATUS"].fillna("").str.strip().str.upper()
    df["CASH_IN_ATUAL"] = to_numeric_safe(df.get("CASH_IN_ATUAL", pd.Series(dtype=float)))
    df["PREVISAO"] = to_numeric_safe(df.get("PREVISAO", pd.Series(dtype=float)))


    for col in ["DT_1º_CTT", "DT_ULTIMO_CTT", "DT_QUALIFICADA", "DT_CONTA_CRIADA", "DATA_PROMESSA", "DATA_PREVISTA"]:
        if col in df.columns:
            df[col] = to_date_safe(df[col])

    consultor_nome = user_config.get("name", "").strip()
    df_consultor = filtrar_por_consultor(df, consultor_nome)

    # KPIs
    qtd_qualificadas = int((df_consultor["STATUS"] == STATUS_QUALIFICADO).sum())
    qtd_saldo_medio = int((df_consultor["STATUS"] == STATUS_SALDO_MEDIO).sum())
    qtd_promessas = int((df_consultor["STATUS"] == STATUS_PROMESSA).sum())
    proj = calcular_projecao(qtd_qualificadas, date.today(), FERIADOS_FIXOS)
    faturamento_total = float(df_consultor.loc[df_consultor["STATUS"] == STATUS_QUALIFICADO, "PREVISAO"].sum())
    balde_total = int(df_consultor.shape[0])

    # ---------------------------
    # Sidebar com metas e indicadores
    st.sidebar.header("🎯 Metas e indicadores")
    META_PADRAO = 120

    # Meta atual
    equipe = user_config.get("equipe", "").upper()
    if equipe == "PERSONALIZADO":
        meta_atual = int(user_config.get("meta", META_PADRAO))  # meta definida no config.yaml
    else:
        meta_atual = META_PADRAO
    st.sidebar.text_input("Meta atual", value=str(meta_atual))

    # ICM (Índice de Cumprimento da Meta)
    icm = 0
    if meta_atual > 0:
        icm = (qtd_qualificadas / meta_atual) * 100
    st.sidebar.text_input("ICM", value=f"{icm:.1f}%")  # agora editável

    # Média de qualificação por dia
    dias_passados = dias_uteis_passados_no_mes(date.today(), FERIADOS_FIXOS)
    media_por_dia = 0
    if dias_passados > 0:
        media_por_dia = qtd_qualificadas / dias_passados
    st.sidebar.text_input("Média por dia", value=f"{media_por_dia:.2f}")  # agora editável



    st.subheader("Resumo Rápido")
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Contas qualificadas", f"{qtd_qualificadas}")
    col2.metric("Saldo médio", f"{qtd_saldo_medio}")
    col3.metric("Promessas", f"{qtd_promessas}")
    col4.metric("Projeção (dias úteis)", f"{proj:.1f}")
    col5.metric("Faturamento total (R$)", f"{faturamento_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    col6.metric("Balde (clientes)", f"{balde_total}")

    st.divider()

    # Tabela 1: Prestes a qualificar
    st.subheader("Clientes prestes a qualificar")
    df_prestes = df_consultor[
        (df_consultor["CASH_IN_ATUAL"] > 1000) &
        (df_consultor["CASH_IN_ATUAL"] < 6000) &
        (df_consultor["STATUS"] != STATUS_QUALIFICADO)
    ]
    df_prestes = df_prestes.sort_values(by="CASH_IN_ATUAL", ascending=False)
    df_prestes = selecionar_colunas_padrao(df_prestes)
    st.dataframe(formatar_tabela(df_prestes, "#E7F0FF"), use_container_width=True)


    st.divider()

    # Tabela 2: Qualificadas
    st.subheader("Clientes qualificados")
    df_qual = df_consultor[df_consultor["STATUS"] == STATUS_QUALIFICADO]
    df_qual = selecionar_colunas_padrao(df_qual)
    st.dataframe(formatar_tabela(df_qual, "#E9F7EF"), use_container_width=True)

    st.divider()

    # Tabela 3
        # Tabela 3: Promessas (expandível)
    st.subheader("Promessas")
    with st.expander("Mostrar/ocultar promessas", expanded=False):
        df_prom = df_consultor[df_consultor["STATUS"] == STATUS_PROMESSA]
        df_prom = selecionar_colunas_padrao(df_prom)
        st.dataframe(formatar_tabela(df_prom, "#FFF9E6"), use_container_width=True)

    # Tabela 4: Novos critérios (expandível)
    st.subheader("Novos critérios")
    with st.expander("Mostrar/ocultar novos critérios", expanded=False):
        df_novos = df_consultor[df_consultor["STATUS"].str.startswith("NOVO CRITÉRIO", na=False)]
        df_novos = selecionar_colunas_padrao(df_novos)
        st.dataframe(formatar_tabela(df_novos, "#F2F2F2"), use_container_width=True)

    st.divider()
    st.subheader(" Dashboards")

    # Colunas lado a lado
    col1, col2 = st.columns(2)

    # ---------------------------
    # 1. Distribuição por Status (gráfico de pizza em tons de azul)
    # ---------------------------
    with col1:
        status_counts = df_consultor["STATUS"].value_counts()
        status_df = pd.DataFrame({
            "STATUS": status_counts.index,
            "QTD": status_counts.values
        })
        fig_status = px.pie(
            status_df,
            names="STATUS",
            values="QTD",
            title="Distribuição por Status",
            color_discrete_sequence=px.colors.sequential.Blues  # tons progressivos de azul
        )
        st.plotly_chart(fig_status, use_container_width=True)

    # ---------------------------
    # 2. Perfis do balde (M0, M1, M2) - gráfico de barras em tons de azul
    # ---------------------------
    with col2:
        if "PERFIL M" in df_consultor.columns:
            perfil_counts = df_consultor["PERFIL M"].value_counts()
            perfil_df = pd.DataFrame({
                "PERFIL M": perfil_counts.index,
                "QTD": perfil_counts.values
            })
            fig_perfil = px.bar(
                perfil_df,
                x="PERFIL M",
                y="QTD",
                text="QTD",
                title="Perfis do balde",
                color="PERFIL M",
                color_discrete_sequence=px.colors.sequential.Blues  # tons progressivos de azul
            )
            fig_perfil.update_traces(textposition="outside")
            st.plotly_chart(fig_perfil, use_container_width=True)

    # ---------------------------
    # 3. PDU - Qualificadas por dia útil (linha azul)
    # ---------------------------
    if "DT_QUALIFICADA" in df_consultor.columns:
        df_pdu = df_consultor[df_consultor["STATUS"] == STATUS_QUALIFICADO].copy()
        df_pdu["DT_QUALIFICADA"] = pd.to_datetime(df_pdu["DT_QUALIFICADA"], errors="coerce").dt.date

        # Agrupa por dia útil
        pdu_counts = df_pdu.groupby("DT_QUALIFICADA").size().reset_index(name="Qualificadas")

        # Remove finais de semana e feriados
        pdu_counts = pdu_counts[
            pdu_counts["DT_QUALIFICADA"].apply(lambda d: d.weekday() < 5 and d not in FERIADOS_FIXOS)
        ]

        fig_pdu = px.line(
            pdu_counts,
            x="DT_QUALIFICADA",
            y="Qualificadas",
            title="Qualificadas por dia útil",
            markers=True,
            line_shape="linear",
            color_discrete_sequence=["#1f77b4"]  # azul padrão
        )
        st.plotly_chart(fig_pdu, use_container_width=True)
    
    # Tabela 5: Balde completo
    st.subheader("Balde completo de clientes")
    df_balde = selecionar_colunas_padrao(df_consultor)
    st.dataframe(formatar_tabela(df_balde, "#FFFFFF"), use_container_width=True)

