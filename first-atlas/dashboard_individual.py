import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
import pandas as pd
from datetime import date, datetime, timedelta
import calendar
import numpy as np
import plotly.express as px

# ---------- Estilo ----------
st.set_page_config(page_title="Dashboard de Produção", layout="wide")
st.markdown("""
    <style>
        .main {background-color: #f8f9fa;}
        .block-container {padding-top: 2rem;}
        .stRadio > div {flex-direction: column;}
        .metric-label {font-weight: bold;}
    </style>
""", unsafe_allow_html=True)

st.sidebar.markdown(
    "<h2 style='margin:0; padding:0'>ATLAS</h2>"
    "<div style='height:1.6rem'></div>",
    unsafe_allow_html=True
)

# ---------- Autenticação ----------
with open('config.yaml') as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

name, authentication_status, username = authenticator.login("Login", "main")

if authentication_status is False:
    st.error("Usuário ou senha incorretos")
elif authentication_status is None:
    st.warning("Por favor, insira suas credenciais")
elif authentication_status:
    st.sidebar.success(f"Logado como: {name}")
    user_role = config['credentials']['usernames'][username].get('role', 'operador')

    # ---------- Carregar dados do Excel hospedado no GitHub ----------
    EXCEL_URL = "https://github.com/devsb4b-web/atlas/raw/refs/heads/main/atlas/producao.xlsx"
    df = pd.read_excel(EXCEL_URL)
    df.columns = df.columns.str.strip().str.upper()
    df["DATA_BASE"] = pd.to_datetime(df["DATA_BASE"], errors="coerce")
    df["MES"] = df["DATA_BASE"].dt.to_period("M").astype(str)

    # ---------- Filtro por usuário e mês ----------
    df_user = df[df["CONSULTOR"].str.lower() == name.lower()].copy()
    meses_disponiveis = sorted(df_user["MES"].unique(), reverse=True)
    mes_selecionado = st.sidebar.selectbox("📅 Selecione o mês", options=meses_disponiveis)
    df_mes = df_user[df_user["MES"] == mes_selecionado]

    # ---------- Sidebar: meta e ranking ----------
    st.sidebar.markdown("## 📊 Projeções e Comissão")
    equipe = st.sidebar.selectbox("Equipe", options=["URA", "DISCADOR", "Outro"], index=0)
    meta_default = 80 if equipe == "URA" else 60
    meta_atual = st.sidebar.number_input("Meta atual (contas/mês)", min_value=1, value=meta_default, step=1)
    estou_no_ranking = st.sidebar.checkbox("Estou no ranking?", value=False)
    pos_ranking = st.sidebar.selectbox("Se sim, qual posição?", options=["1", "2", "3", "Outro"], index=0) if estou_no_ranking else None
    pos_ranking = pos_ranking if pos_ranking in ["1", "2", "3"] else None

    # ---------- Funções de projeção ----------
    VAL_80_90 = 5
    VAL_90_100 = 7
    VAL_100_PLUS = 9
    ACC_110 = 1.1
    ACC_120 = 1.2
    BONUS_POS = {"1": 700, "2": 500, "3": 350}

    def faixa_unitario(atingimento):
        if atingimento < 0.8: return 0
        elif atingimento < 0.9: return VAL_80_90
        elif atingimento < 1.0: return VAL_90_100
        else: return VAL_100_PLUS

    def multiplicador_acelerador(atingimento):
        if atingimento >= 1.2: return ACC_120
        elif atingimento >= 1.1: return ACC_110
        else: return 1.0

    def calcular_comissao(contas, meta, inclui_bonus=False, pos=None):
        meta_safe = meta if meta and meta > 0 else 1
        ating = contas / meta_safe
        unit = faixa_unitario(ating)
        acel = multiplicador_acelerador(ating)
        comissao = contas * unit * acel
        bonus = BONUS_POS.get(pos, 0) if inclui_bonus and pos in BONUS_POS else 0
        return {
            "comissao_total": comissao + bonus,
            "comissao_sem_bonus": comissao,
            "atingimento": ating,
            "unit": unit,
            "acel": acel,
            "bonus": bonus
        }

    def dias_uteis_inclusive(start_dt, end_dt, feriados=None):
        fer = feriados or []
        s = pd.to_datetime(start_dt).date()
        e = pd.to_datetime(end_dt).date()
        total = np.busday_count(s, e + timedelta(days=1))
        for f in fer:
            f = pd.to_datetime(f).date()
            if s <= f <= e and np.is_busday(f):
                total -= 1
        return max(total, 0)

    # ---------- Métricas ----------
    total_aprovadas = df_mes[df_mes["STATUS_ABERTURA"] == "Aprovada"].shape[0]
    analise_input = df_mes[df_mes["STATUS_ABERTURA"] == "Analise"].shape[0]
    hoje = date.today()
    if mes_selecionado:
        ano, mes = map(int, mes_selecionado.split("-"))
        inicio_mes = date(ano, mes, 1)
        fim_mes = date(ano, mes, calendar.monthrange(ano, mes)[1])
    else:
        st.warning("Nenhum mês disponível para visualização.")
        st.stop()
    inicio_mes = date(ano, mes, 1)
    fim_mes = date(ano, mes, calendar.monthrange(ano, mes)[1])
    dias_uteis_total = dias_uteis_inclusive(inicio_mes, fim_mes)
    dias_uteis_passados = dias_uteis_inclusive(inicio_mes, min(hoje, fim_mes))
    dias_uteis_restantes = max(dias_uteis_total - dias_uteis_passados, 0)
    elapsed_business = dias_uteis_passados if dias_uteis_passados > 0 else 1

    projecao_sem_bonus = total_aprovadas / elapsed_business * dias_uteis_total
    projecao_com_analise = (total_aprovadas + analise_input) / elapsed_business * dias_uteis_total
    inclui_bonus_flag = bool(estou_no_ranking)
    res_sem = calcular_comissao(projecao_sem_bonus, meta_atual, inclui_bonus_flag, pos_ranking)
    res_com_analise = calcular_comissao(projecao_com_analise, meta_atual, inclui_bonus_flag, pos_ranking)

    hoje_dt = pd.to_datetime(hoje)
    inicio_semana = hoje_dt - pd.Timedelta(days=hoje_dt.weekday())
    producao_hoje = df_mes[(df_mes["DATA_BASE"].dt.date == hoje) & df_mes["STATUS_ABERTURA"].isin(["Aprovada", "Analise"])].shape[0]
    producao_semana = df_mes[(df_mes["DATA_BASE"] >= inicio_semana) & (df_mes["DATA_BASE"] <= hoje_dt) & (df_mes["STATUS_ABERTURA"] == "Aprovada")].shape[0]

    # ---------- Resumo Rápido ----------
    st.title("📊 Dashboard de Produção")
    st.markdown("### Resumo Rápido")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Contas aprovadas", total_aprovadas)
    col2.metric("Produção de hoje", producao_hoje)
    col3.metric("Produção esta semana", producao_semana)
    col4.metric("Dias úteis restantes", dias_uteis_restantes)

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Projeção (sem análise)", f"{int(round(projecao_sem_bonus))} contas")
    col6.metric("Projeção (com análise)", f"{int(round(projecao_com_analise))} contas")
    col7.metric("Comissão estimada (R$)", f"R$ {res_sem['comissao_total']:,.2f}")
    col8.metric("Atingimento projetado", f"{res_sem['atingimento']*100:.1f}%")

    st.markdown("---")

    # ---------- Tabela de contas ----------
    st.subheader("Minhas Contas")
    st.dataframe(df_mes[["DATA_BASE", "CNPJ", "NOME_CLIENTE", "ORIGEM", "STATUS_ABERTURA"]], use_container_width=True)

    # ---------- Gráficos ----------
    st.markdown("### Análise rápida")
    origem_counts = df_mes["ORIGEM"].fillna("Desconhecida").value_counts()
    fig_origin = px.pie(
        names=origem_counts.index,
        values=origem_counts.values,
        title="Distribuição por Origem",
        hole=0.35,
        color_discrete_sequence=px.colors.sequential.Blues[4:]
    )
    fig_origin.update_traces(textposition="inside", textinfo="percent+label")

    aprovadas_cnt = total_aprovadas
    outras_cnt = df_mes[df_mes["STATUS_ABERTURA"] != "Aprovada"].shape[0]

    fig_conv = px.pie(
        names=["Aprovadas", "Outras"],
        values=[aprovadas_cnt, outras_cnt],
        title="Taxa de Conversão (Aprovadas / Total)",
        hole=0.4,
        color_discrete_sequence=px.colors.sequential.Blues[4:]
    )
    fig_conv.update_traces(textposition="inside", textinfo="percent+label")

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(fig_origin, use_container_width=True)
    with c2:
        st.plotly_chart(fig_conv, use_container_width=True)

    # ---------- Gráfico de ritmo vs meta ----------
    st.subheader("Gráfico de Ritmo vs Meta")
    days = np.arange(1, dias_uteis_total + 1)
    ritmo_atual = (total_aprovadas / elapsed_business) if elapsed_business > 0 else 0
    cumulativo_ritmo = ritmo_atual * days
    meta_line = np.linspace(0, meta_atual, num=len(days))
    df_line = pd.DataFrame({
        "Dia útil (índice)": days,
        "Ritmo Atual (cumulativo)": cumulativo_ritmo,
        "Meta (linha)": meta_line
    })
    fig_line = px.line(
        df_line,
        x="Dia útil (índice)",
        y=["Ritmo Atual (cumulativo)", "Meta (linha)"],
        labels={"value": "Contas acumuladas", "variable": "Série"},
        title="Ritmo atual vs Meta (cumulativo em dias úteis)",
        color_discrete_sequence=["#2b8cbe", "#bdd7e7"]
    )
    st.plotly_chart(fig_line, use_container_width=True)

    # ---------- Recomendações ----------
    st.markdown("---")
    st.subheader("O que você precisa fazer")
    if dias_uteis_restantes > 0:
        contas_faltantes = max(meta_atual - total_aprovadas, 0)
        contas_por_dia_necessarias = contas_faltantes / dias_uteis_restantes
        st.write(f"Você precisa abrir em média **{contas_por_dia_necessarias:.2f}** contas por dia útil até o fim do mês para atingir a meta.")
    else:
        st.write("Fim do mês (dias úteis). Verifique resultados finais.")

    st.markdown("Recomendações rápidas")
    recs = []
    if projecao_sem_bonus >= meta_atual:
        recs.append("Mantenha o ritmo — você está no caminho de bater a meta sem considerar em-análise.")
    else:
        recs.append("Aumente conversões ou pipeline; foque em casos que estão em análise para convertê-los.")
    if analise_input > 0:
        recs.append("Acompanhe rapidamente os casos em análise para convertê-los em aprovados.")
    if not estou_no_ranking:
        recs.append("Entrar no ranking aumenta suas chances de bônus; busque posição entre os 3 primeiros.")
    else:
        recs.append(f"Você indicou que está no ranking — bônus será aplicado automaticamente quando aplicável.")

    for r in recs:
        st.write("- " + r)

    # ---------- Exportação opcional ----------
    import io
    if user_role == "master" and not df_mes.empty:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_mes.to_excel(writer, index=False, sheet_name='Contas')
        output.seek(0)
        st.download_button(
            label="📥 Exportar minhas contas (Excel)",
            data=output,
            file_name="minhas_contas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    # ---------- Logout ----------
    authenticator.logout("Sair", "sidebar")
