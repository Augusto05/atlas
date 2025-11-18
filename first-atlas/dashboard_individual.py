import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
import pandas as pd
from datetime import date, datetime, timedelta
import calendar
import numpy as np
import plotly.express as px
import dashboard_qualificador 

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

    if user_role == "qualificador":
        # se for qualificador, renderiza o outro dashboard
        dashboard_qualificador.exibir_dashboard(config['credentials']['usernames'][username])
    else:
        
        # ---------- Lista de meses disponíveis ----------
        meses_disponiveis = [
            "2025-10",
            "2025-11",
        ]

        # ---------- Lista de feriados ----------
        def _to_date_obj(dt):
            if pd.isna(dt):
                return None
            if isinstance(dt, date) and not isinstance(dt, datetime):
                return dt
            if isinstance(dt, datetime):
                return dt.date()
            if isinstance(dt, pd.Timestamp):
                return dt.to_pydatetime().date()
            try:
                return pd.to_datetime(dt).date()
            except Exception:
                return None

        # Função principal para cálculo de dias úteis incluindo o último dia
        def dias_uteis_inclusive(start_dt, end_dt, feriados=None):
            fer = feriados or []
            s = _to_date_obj(start_dt)
            e = _to_date_obj(end_dt)
            if s is None or e is None or s > e:
                return 0
            start_np = np.datetime64(s)
            end_next_np = np.datetime64(e) + np.timedelta64(1, "D")
            total = int(np.busday_count(start_np, end_next_np))
            for f in fer:
                f_date = _to_date_obj(f)
                if f_date and s <= f_date <= e and np.is_busday(np.datetime64(f_date)):
                    total -= 1
            return max(total, 0)

        # Feriados fixos válidos para São Paulo
        FERIADOS = [
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
        ]


        # ---------- Seleção de mês ----------
        mes_atual = datetime.today().strftime("%Y-%m")
        mes_selecionado = st.sidebar.selectbox(
            "📅 Selecione o mês",
            options=meses_disponiveis,
            index=meses_disponiveis.index(mes_atual) if mes_atual in meses_disponiveis else 0
        )
        mes_eh_atual = mes_selecionado == mes_atual



        # ---------- Carregar dados do Excel correspondente ----------
        EXCEL_URL_BASE = "https://github.com/Augusto05/atlas/raw/refs/heads/main/first-atlas/"
        EXCEL_URL = f"{EXCEL_URL_BASE}producao_{mes_selecionado}.xlsx"

        try:
            df = pd.read_excel(EXCEL_URL, dtype={"CNPJ": str})
        except Exception as e:
            st.error(f"Erro ao carregar o arquivo do mês selecionado: {e}")
            st.stop()

        df.columns = df.columns.str.strip().str.upper()
        df["DATA_BASE"] = pd.to_datetime(df["DATA_BASE"], errors="coerce")
        df["MES"] = df["DATA_BASE"].dt.to_period("M").astype(str)

        # ---------- Filtro por usuário e mês ----------
        if user_role == "master":
            df_mes = df[df["MES"] == mes_selecionado].copy()
        else:
            df_user = df[df["CONSULTOR"].str.strip().str.lower() == name.strip().lower()].copy()
            df_mes = df_user[df_user["MES"] == mes_selecionado]

        def normalizar_status(valor):
            v = str(valor).strip().upper()
            if v == "APROVADA":
                return "Aprovada"
            elif v in ["ANÁLISE", "PENDÊNCIA DOC", "AINDA NAO INICIOU A ABERTURA DE CONTA"]:
                return "Analise"
            elif v in ["CARIMBADA", "REPROVADA", "INVÁLIDA"]:
                return "Outras"
            else:
                return "Outras"

        df_mes["STATUS_PADRONIZADO"] = df_mes["STATUS_ABERTURA"].apply(normalizar_status)


        # ---------- Sidebar: meta e ranking ----------
        st.sidebar.markdown("## 📊 Projeções e Comissão")

        user_config = config["credentials"]["usernames"][username]
        user_role = user_config.get("role", "operador")
        equipe_default = user_config.get("equipe", "URA")

        # Metas padrão definidas no código
        meta_padrao = {"URA": 80, "DISCADOR": 60}

        # Se for OUTRO, pega meta do YAML; senão usa padrão
        meta_default = (
            user_config.get("meta", 60) if equipe_default == "PERSONALIZADO"
            else meta_padrao.get(equipe_default, 60)
        )

        if user_role == "master":
            meta_atual = st.sidebar.number_input(
                "Meta atual (contas/mês)",
                min_value=1,
                value=1600,
                step=1
            )
        else:
            equipe = st.sidebar.selectbox(
                "Equipe",
                options=["URA", "DISCADOR", "PERSONALIZADO"],
                index=["URA","DISCADOR","PERSONALIZADO"].index(equipe_default)
            )

            # Sempre exibe o campo de meta
            meta_atual = st.sidebar.number_input(
                "Meta atual (contas/mês)",
                min_value=1,
                value=(
                    user_config.get("meta", 60) if equipe == "PERSONALIZADO"
                    else meta_padrao.get(equipe, 60)
                ),
                step=1
            )


                
        estou_no_ranking = False
        pos_ranking = None
        if(user_role != "master"):
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
            contas_real = int(contas)  # força inteiro
            comissao = contas_real * unit * acel
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
        total_aprovadas = df_mes[df_mes["STATUS_PADRONIZADO"] == "Aprovada"].shape[0]
        if user_role == "master":
            analise_input = df_mes[df_mes["STATUS_ABERTURA"].str.upper().str.strip() == "ANÁLISE"].shape[0]
        else:
            analise_input = df_mes[df_mes["STATUS_PADRONIZADO"] == "Analise"].shape[0]

        nao_iniciadas = df_mes[df_mes["STATUS_ABERTURA"].str.upper().str.strip() == "AINDA NAO INICIOU A ABERTURA DE CONTA"].shape[0]
        pendencias_doc = df_mes[df_mes["STATUS_ABERTURA"].str.upper().str.strip() == "PENDÊNCIA DOC"].shape[0]
        contas_invalidas = df_mes[
            df_mes["STATUS_ABERTURA"].str.upper().str.strip().isin(["INVÁLIDA", "REPROVADA", "AINDA NAO INICIOU A ABERTURA DE CONTA"])
        ].shape[0]

        avisos = []
        if user_role != "master":
            if nao_iniciadas > 0:
                if nao_iniciadas == 1:
                    avisos.append(f"Você possui **{nao_iniciadas}** conta que ainda não iniciou a abertura.")
                else:
                    avisos.append(f"Você possui **{nao_iniciadas}** contas que ainda não iniciaram a abertura.")
            if pendencias_doc > 0:
                if pendencias_doc == 1:
                    avisos.append(f"Você possui **{pendencias_doc}** conta em pendência de documentação.")
                else:
                    avisos.append(f"Você possui **{pendencias_doc}** contas em pendência de documentação.")

        if avisos:
            st.info("  \n".join(avisos))
        hoje = date.today() - timedelta(days=1)
        if mes_selecionado:
            ano, mes = map(int, mes_selecionado.split("-"))
            inicio_mes = date(ano, mes, 1)
            fim_mes = date(ano, mes, calendar.monthrange(ano, mes)[1])
        else:
            st.warning("Nenhum mês disponível para visualização.")
            st.stop()

        ano = datetime.today().year
        mes = datetime.today().month
        inicio_mes = date(ano, mes, 1)
        fim_mes = date(ano, mes, calendar.monthrange(ano, mes)[1])
        hoje_date = date.today() - timedelta(days=1)


        # Cálculo dos dias úteis
        dias_uteis_total = dias_uteis_inclusive(inicio_mes, fim_mes, FERIADOS)
        dias_uteis_passados = dias_uteis_inclusive(inicio_mes, min(hoje_date, fim_mes), FERIADOS)
        dias_uteis_restantes = max(dias_uteis_total - dias_uteis_passados, 0)
        elapsed_business = dias_uteis_passados if dias_uteis_passados > 0 else 1

        projecao_sem_bonus = total_aprovadas / elapsed_business * dias_uteis_total
        projecao_com_analise = (total_aprovadas + analise_input) / elapsed_business * dias_uteis_total
        inclui_bonus_flag = bool(estou_no_ranking)
        res_sem = calcular_comissao(projecao_sem_bonus, meta_atual, inclui_bonus_flag, pos_ranking)
        res_com_analise = calcular_comissao(projecao_com_analise, meta_atual, inclui_bonus_flag, pos_ranking)

        hoje_dt = pd.to_datetime(hoje)
        inicio_semana = hoje_dt - pd.Timedelta(days=hoje_dt.weekday())
        producao_hoje = df_mes[(df_mes["DATA_BASE"].dt.date == hoje) & df_mes["STATUS_PADRONIZADO"].isin(["Aprovada", "Analise"])].shape[0]
        producao_semana = df_mes[(df_mes["DATA_BASE"] >= inicio_semana) & (df_mes["DATA_BASE"] <= hoje_dt) & (df_mes["STATUS_PADRONIZADO"] == "Aprovada")].shape[0]

        # ---------- Resumo Rápido ----------
        st.title("📊 Dashboard de Produção")
        st.markdown("### Resumo Rápido")

        col1, col2, col3, col4 = st.columns(4)
        if user_role == "master":
            col1.metric("Contas aprovadas", total_aprovadas)
            col2.metric("Contas em análise", analise_input)
            col3.metric("Contas com pendência", f"{int(round(pendencias_doc))}")
            col4.metric("Contas inválidas", contas_invalidas)
        else:
            col1.metric("Contas aprovadas", total_aprovadas)
            col2.metric("Contas em análise", analise_input)
            col3.metric("Produção esta semana", producao_semana if mes_eh_atual else "-")
            col4.metric("Dias úteis restantes", dias_uteis_restantes if mes_eh_atual else "-")

        col5, col6, col7, col8 = st.columns(4)
        if user_role == "master":
            col5.metric("Projeção (com análise)", f"{int(round(projecao_com_analise))} contas" if mes_eh_atual else "-")
            col6.metric("Atingimento projetado", f"{res_sem['atingimento']*100:.1f}%" if mes_eh_atual else "-")
            col7.metric("Dias úteis restantes", dias_uteis_restantes if mes_eh_atual else "-")
            col8.metric("Produção esta semana", producao_semana if mes_eh_atual else "-")
        
        else:
            col5.metric("Projeção (sem análise)", f"{int(round(projecao_sem_bonus))} contas" if mes_eh_atual else "-")
            col6.metric("Projeção (com análise)", f"{int(round(projecao_com_analise))} contas" if mes_eh_atual else "-")
            col7.metric("Comissão estimada (R$)", f"R$ {res_sem['comissao_total']:,.2f}" if mes_eh_atual else "-") 
            col8.metric("Atingimento projetado", f"{res_sem['atingimento']*100:.1f}%" if mes_eh_atual else "-")

        st.markdown("---")

        #----------- Ranking de Contas Aprovadas ----------
        
        if user_role == "master":
            st.subheader("Ranking")

            # Filtra apenas contas com status APROVADA ou ANÁLISE
            df_abertas = df_mes[
                df_mes["STATUS_ABERTURA"].str.upper().str.strip().isin(["APROVADA"])
            ]

            # Agrupa por consultor e conta
            ranking_abertas = (
                df_abertas.groupby("CONSULTOR")
                .size()
                .reset_index(name="Contas Abertas")
                .sort_values(by="Contas Abertas", ascending=False)
                .reset_index(drop=True)
            )

            ranking_abertas.index = ranking_abertas.index + 1  # Começa em 1

            st.dataframe(
                ranking_abertas.style.hide(axis="index"),
                use_container_width=True,
                height=250  # ajuste conforme necessário
            )

            st.markdown("---")

        # ---------- Tabela de contas ----------
        
        st.subheader("Minhas Contas" if user_role != "master" else "Todas as Contas")
        if user_role == "master":
            df_exibicao = df_mes.copy()
        else:
            df_exibicao = df_mes[df_mes["CONSULTOR"] == name].copy()

    # Formatação da coluna de data
        df_exibicao["DATA_BASE"] = pd.to_datetime(df_exibicao["DATA_BASE"], errors="coerce")
        df_exibicao["DATA_BASE"] = df_exibicao["DATA_BASE"].dt.strftime("%d/%m/%Y")

        # Selecionar colunas para exibição
        if user_role == "master":
            colunas_exibidas = [ "DATA_BASE", "CNPJ", "NOME_CLIENTE", "CONSULTOR", "ORIGEM", "STATUS_ABERTURA"]
        else:
            colunas_exibidas = ["DATA_BASE", "CNPJ", "NOME_CLIENTE", "ORIGEM", "STATUS_ABERTURA"]
        df_display = df_exibicao[colunas_exibidas].copy()

        # Resetar índice e ocultar visualmente
        df_display.reset_index(drop=True, inplace=True)
        df_display.index = df_display.index + 1

        # Exibir tabela
        if user_role == "master":
            estilo_colunas = {
                "NOME_CLIENTE": [{"selector": "td", "props": [("max-width", "90px"), ("white-space", "nowrap"), ("overflow", "hidden"), ("text-overflow", "ellipsis")]}],
                "CONSULTOR": [{"selector": "td", "props": [("max-width", "120px"), ("white-space", "nowrap"), ("overflow", "hidden"), ("text-overflow", "ellipsis")]}],  
            }
            st.dataframe(
                df_display.style.set_table_styles(estilo_colunas, overwrite=False).hide(axis="index"),
                use_container_width=True
            )
        else:
            st.dataframe(df_display.style.hide(axis="index"), use_container_width=True)

        st.markdown("---")

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
        fig_origin.update_traces(
            textposition="inside", 
            textinfo="percent+label",
            hovertemplate="<b>Origem:</b> %{label}<br><b>Contas:</b> %{value}<extra></extra>"
        )

        aprovadas_cnt = total_aprovadas
        outras_cnt = df_mes[df_mes["STATUS_PADRONIZADO"] != "Aprovada"].shape[0]

        fig_conv = px.pie(
            names=["Aprovadas", "Outras"],
            values=[aprovadas_cnt, outras_cnt],
            title="Taxa de Conversão (Aprovadas / Total)",
            hole=0.4,
            color_discrete_sequence=px.colors.sequential.Blues[4:]
        )
        fig_conv.update_traces(
            textposition="inside",
            textinfo="percent+label",
            hovertemplate="<b>Status:</b> %{label}<br><b>Contas:</b> %{value}<extra></extra>"
        )

        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(fig_origin, use_container_width=True)
        with c2:
            st.plotly_chart(fig_conv, use_container_width=True)

        # ---------- Gráfico PDU -----------
        df_aprovadas = df_mes[df_mes["STATUS_PADRONIZADO"] == "Aprovada"]
        df_aprovadas["DIA_UTIL"] = df_aprovadas["DATA_BASE"].dt.strftime("%d/%m")
        if user_role != "master":
            df_aprovadas = df_aprovadas[df_aprovadas["CONSULTOR"] == name]
        pdu_diario = (
            df_aprovadas.groupby("DIA_UTIL")
            .size()
            .reset_index(name="Contas Aprovadas")
            .sort_values("DIA_UTIL")
        )
        st.subheader("PDU – Contas Aprovadas por Dia Útil")

        fig_pdu = px.bar(
            pdu_diario,
            x="DIA_UTIL",
            y="Contas Aprovadas",
            labels={"DIA_UTIL": "Dia útil", "Contas Aprovadas": "Contas"},
            title="Produção diária",
            color_discrete_sequence=["#2b8cbe"]
        )
        st.plotly_chart(fig_pdu, use_container_width=True)

        # ---------- Gráfico de ritmo vs meta ----------
        st.subheader("Gráfico de Ritmo vs Meta")
        days = np.arange(1, dias_uteis_total + 1)
        ritmo_atual = ((total_aprovadas + analise_input) / elapsed_business) if elapsed_business > 0 else 0
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
