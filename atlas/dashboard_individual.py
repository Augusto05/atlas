import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
import sqlite3
import pandas as pd
from datetime import date, datetime, timedelta
import calendar
import numpy as np
import plotly.express as px
import os
from pathlib import Path

# caminho absoluto para o DB (evita criar DBs diferentes por cwd)
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "comissao.db")

# ---------- Estilo ----------
st.set_page_config(page_title="Dashboard de Contas", layout="wide")
st.markdown("""
    <style>
        .main {background-color: #f8f9fa;}
        .block-container {padding-top: 2rem;}
        .stRadio > div {flex-direction: column;}
        .metric-label {font-weight: bold;}
    </style>
""", unsafe_allow_html=True)

# Reduz padding do topo da sidebar para que o título fique mais acima
st.markdown(
    """
    <style>
    section[data-testid="stSidebar"] > div:first-child {
        padding-top: 0rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Cabeçalho fixo no topo da sidebar
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

    # ✅ Agora é seguro acessar username
    user_role = config['credentials']['usernames'][username].get('role', 'operador')

    # ---------- Banco de dados ----------
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS contas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT NOT NULL,
        nome TEXT NOT NULL,
        cnpj TEXT,
        telefone TEXT,
        email TEXT,
        data TEXT NOT NULL,
        origem TEXT,
        status TEXT CHECK(status IN ('Analise', 'Aprovada', 'Negada')) NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS metas_gerais (
        mes TEXT PRIMARY KEY,
        meta INTEGER NOT NULL
    )
    """)
    conn.commit()

    # garantir coluna 'origem' em DB existente
    cursor.execute("PRAGMA table_info(contas)")
    existing_cols = [r[1] for r in cursor.fetchall()]
    if "origem" not in existing_cols:
        cursor.execute("ALTER TABLE contas ADD COLUMN origem TEXT")
        conn.commit()

    # ---------- Página única: Visualização e edição (inserção via tabela) ----------
    st.title("📊 Visualização de contas")

    if user_role == "master":
        cursor.execute("SELECT DISTINCT strftime('%Y-%m', data) FROM contas")
    else:
        cursor.execute("SELECT DISTINCT strftime('%Y-%m', data) FROM contas WHERE usuario = ?", (name,))

    meses_disponiveis = [row[0] for row in cursor.fetchall()]

    if meses_disponiveis:
        mes_selecionado = st.sidebar.selectbox(
            "📅 Selecione o mês",
            options=meses_disponiveis,
            index=0,
            key="mes_selecionado"
        )
    else:
        mes_selecionado = None

    # Carregar dados do mês selecionado (mantemos ID no df, mas NÃO exibimos ao usuário)
    if mes_selecionado:
        if user_role == "master":
            cursor.execute("""
                SELECT id, usuario, nome, cnpj, telefone, email, data, origem, status
                FROM contas
                WHERE strftime('%Y-%m', data) = ?
                ORDER BY data, id
            """, (mes_selecionado,))
        else:
            cursor.execute("""
                SELECT id, nome, cnpj, telefone, email, data, origem, status
                FROM contas
                WHERE usuario = ? AND strftime('%Y-%m', data) = ?
                ORDER BY data, id
            """, (name, mes_selecionado))
        dados = cursor.fetchall()
        colunas = ["ID", "Usuario", "Nome", "CNPJ", "Telefone", "Email", "Data", "Origem", "Status"] if user_role == "master" else ["ID", "Nome", "CNPJ", "Telefone", "Email", "Data", "Origem", "Status"]
        df = pd.DataFrame(dados, columns=colunas)
        df["Data"] = pd.to_datetime(df["Data"], errors="coerce")
    else:
        df = pd.DataFrame(columns=["ID", "Nome", "CNPJ", "Telefone", "Email", "Data", "Origem", "Status"])

    # Variáveis derivadas necessárias para o Resumo Rápido
    total_aprovadas = int(df[df["Status"] == "Aprovada"].shape[0]) if not df.empty else 0
    analise_input = int(df[df["Status"] == "Analise"].shape[0]) if not df.empty else 0

    # determinar início/fim do mês selecionado para cálculos de dias úteis
    if mes_selecionado:
        ano_sel, mes_sel = map(int, mes_selecionado.split("-"))
        inicio_mes = pd.to_datetime(datetime(ano_sel, mes_sel, 1))
        fim_mes = pd.to_datetime(datetime(ano_sel, mes_sel, calendar.monthrange(ano_sel, mes_sel)[1]))
    else:
        hoje_dt = datetime.today()
        inicio_mes = pd.to_datetime(datetime(hoje_dt.year, hoje_dt.month, 1))
        fim_mes = inicio_mes

    # preparar lista de dias úteis do mês (pode ser usada por projeções)
    dias_uteis_mes = pd.date_range(inicio_mes, fim_mes, freq="B")

    # ---------- Funções utilitárias e constantes usadas nas projeções ----------
    FERIADOS = []

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

    def projecao_linear_uteis(atual, elapsed_business_days, total_business_days):
        ritmo_por_dia = atual / elapsed_business_days if elapsed_business_days > 0 else 0
        return ritmo_por_dia * total_business_days

    VAL_80_90 = 5
    VAL_90_100 = 7
    VAL_100_PLUS = 9
    ACC_110 = 1.1
    ACC_120 = 1.2
    BONUS_POS = {"1": 700, "2": 500, "3": 350}

    def faixa_unitario(atingimento):
        if atingimento < 0.8:
            return 0
        elif atingimento < 0.9:
            return VAL_80_90
        elif atingimento < 1.0:
            return VAL_90_100
        else:
            return VAL_100_PLUS

    def multiplicador_acelerador(atingimento):
        if atingimento >= 1.2:
            return ACC_120
        elif atingimento >= 1.1:
            return ACC_110
        else:
            return 1.0

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

    # ---------- Sidebar: configurações mínimas ----------
    st.sidebar.markdown("## 📊 Projeções e Comissão")
    if user_role == "master":
        meta_atual = st.sidebar.number_input("Meta geral do mês", min_value=1, value=1340, step=1)
        if mes_selecionado:
            if st.sidebar.button("Salvar meta do mês"):
                cursor.execute("""
                    INSERT INTO metas_gerais (mes, meta)
                    VALUES (?, ?)
                    ON CONFLICT(mes) DO UPDATE SET meta=excluded.meta
                """, (mes_selecionado, meta_atual))
                conn.commit()
                st.sidebar.success("Meta salva com sucesso.")
        else:
            st.sidebar.info("Selecione um mês para definir a meta.")
    else:
        equipe = st.sidebar.selectbox("Equipe", options=["URA", "DISCADOR", "Outro"], index=0)
        meta_default = 80 if equipe == "URA" else 60
        meta_atual = st.sidebar.number_input("Meta atual (contas/mês)", min_value=1, value=meta_default, step=1)

    estou_no_ranking = st.sidebar.checkbox("Estou no ranking?", value=False)

    pos_ranking = None
    if estou_no_ranking:
        pos_choice = st.sidebar.selectbox("Se sim, qual posição?", options=["1", "2", "3", "Outro"], index=0)
        pos_ranking = pos_choice if pos_choice in ["1", "2", "3"] else None

    # ---------- Resumo Rápido ----------
    st.markdown("### Resumo Rápido")
    aprovadas_input = total_aprovadas
    analise_input = int(df[df["Status"] == "Analise"].shape[0])

    first_day = inicio_mes.to_pydatetime().date()
    last_day = fim_mes.to_pydatetime().date()
    hoje_date = date.today()

    dias_uteis_total = dias_uteis_inclusive(first_day, last_day, FERIADOS)
    dias_uteis_passados = dias_uteis_inclusive(first_day, min(hoje_date, last_day), FERIADOS)
    dias_uteis_restantes = max(dias_uteis_total - dias_uteis_passados, 0)
    elapsed_business = dias_uteis_passados if dias_uteis_passados > 0 else 1

    projecao_sem_bonus = projecao_linear_uteis(aprovadas_input, elapsed_business, dias_uteis_total)
    projecao_com_analise = projecao_linear_uteis(aprovadas_input + analise_input, elapsed_business, dias_uteis_total)

    inclui_bonus_flag = bool(estou_no_ranking)
    res_sem = calcular_comissao(projecao_sem_bonus, meta_atual, inclui_bonus=inclui_bonus_flag, pos=pos_ranking)
    res_com_analise = calcular_comissao(projecao_com_analise, meta_atual, inclui_bonus=inclui_bonus_flag, pos=pos_ranking)

    hoje_dt = pd.to_datetime(date.today())
    inicio_semana = hoje_dt - pd.Timedelta(days=hoje_dt.weekday())
    if not df.empty:
        producao_hoje = int(df[(df["Data"].dt.date == date.today()) & df["Status"].isin(["Aprovada", "Analise"])].shape[0])
        producao_semana = int(df[(df["Data"] >= inicio_semana) & (df["Data"] <= hoje_dt) & (df["Status"] == "Aprovada")].shape[0])
    else:
        producao_hoje = 0
        producao_semana = 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Contas aprovadas", int(total_aprovadas))
    col2.metric("Produção de hoje", int(producao_hoje))
    col3.metric("Produção esta semana", int(producao_semana))
    col4.metric("Dias úteis restantes", int(dias_uteis_restantes))

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Projeção (sem análise)", f"{int(round(projecao_sem_bonus))} contas")
    col6.metric("Projeção (com análise)", f"{int(round(projecao_com_analise))} contas")
    col7.metric("Comissão estimada (R$)", f"R$ {res_sem['comissao_total']:,.2f}")
    col8.metric("Atingimento projetado", f"{res_sem['atingimento']*100:.1f}%")

    st.markdown("---")

    # ---------- Após resumo rápido: mostrar tabela de contas ----------
    st.subheader("Todas as Contas" if user_role == "master" else "Minhas Contas")

    # ---------- Tabela editável ----------
    df["Data"] = pd.to_datetime(df["Data"], errors="coerce")

    # Preparar DataFrame para o editor (NÃO incluir ID coluna no que o usuário vê)
    df_display = df.reset_index(drop=True).copy()
    df_display["_data_iso"] = df_display["Data"].dt.strftime("%Y-%m-%d")

    # ids_map: lista posicional de ids que correspondem às linhas mostradas
    ids_map = []
    if "ID" in df_display.columns and len(df_display) > 0:
        for v in df_display["ID"].tolist():
            try:
                ids_map.append(int(v))
            except Exception:
                ids_map.append(None)
    st.session_state["editor_ids"] = ids_map  # usado ao salvar

    if user_role == "master" and "Usuario" in df_display.columns:
        editor_df = df_display[["Usuario", "Nome", "CNPJ", "Telefone", "Email", "Data", "Origem", "Status"]].copy()
    else:
        editor_df = df_display[["Nome", "CNPJ", "Telefone", "Email", "Data", "Origem", "Status"]].copy()

    # incluir Origem imediatamente após Data para o usuário
    #if "Origem" in df_display.columns:
        #editor_df = df_display[["Nome", "CNPJ", "Telefone", "Email", "Data", "Origem", "Status"]].copy()

    edited_obj = st.data_editor(
        editor_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Status": st.column_config.SelectboxColumn("Status", options=["Analise", "Aprovada", "Negada"]),
            "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY")
        },
        key="minhas_contas_editor"
    )

    # Função para normalizar payload do data_editor em DataFrame
    def _edited_to_df(edited_obj):
        if edited_obj is None:
            return pd.DataFrame()
        if isinstance(edited_obj, list):
            return pd.DataFrame.from_records(edited_obj)
        if isinstance(edited_obj, dict):
            vals = list(edited_obj.values())
            # caso col -> dict (indexado)
            if all(isinstance(v, dict) for v in vals):
                idx_keys = set()
                for v in vals:
                    idx_keys.update(v.keys())
                try:
                    idx_sorted = sorted(idx_keys, key=lambda x: int(x))
                except Exception:
                    idx_sorted = sorted(idx_keys, key=str)
                rows = []
                for k in idx_sorted:
                    row = {}
                    for col, coldict in edited_obj.items():
                        if k in coldict:
                            val = coldict[k]
                        elif str(k) in coldict:
                            val = coldict[str(k)]
                        else:
                            val = None
                        row[col] = val
                    rows.append(row)
                return pd.DataFrame.from_records(rows)
            # caso col -> list/iterable
            lengths = []
            for v in vals:
                if hasattr(v, "__len__") and not isinstance(v, (str, bytes, bytearray)):
                    lengths.append(len(v))
                else:
                    lengths.append(1)
            maxlen = max(lengths) if lengths else 0
            rows = []
            for i in range(maxlen):
                row = {}
                for k, v in edited_obj.items():
                    if hasattr(v, "__len__") and not isinstance(v, (str, bytes, bytearray)):
                        row[k] = v[i] if i < len(v) else None
                    else:
                        row[k] = v
                rows.append(row)
            return pd.DataFrame.from_records(rows)
        return pd.DataFrame(edited_obj)

    # Salvar alterações ao clicar (botão único)
    def _save_changes(edited_payload):
        # usar diretamente o payload retornado por st.data_editor (evita discrepâncias no session_state)
        edited_df_local = _edited_to_df(edited_payload)
        if edited_df_local is None or edited_df_local.empty:
            st.warning("Nada a salvar.")
            return

        # abrir conexão usando caminho absoluto
        local_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        local_cursor = local_conn.cursor()
        try:
            ids = st.session_state.get("editor_ids", [])
            n_original = len(ids)

            for pos, row in edited_df_local.reset_index(drop=True).iterrows():
                nome = str(row.get("Nome", "") or "").strip()
                # normalizar data -> ISO string; se inválida, usar None (não deixar NULL no DB)
                try:
                    parsed = pd.to_datetime(row.get("Data", None), errors="coerce")
                    data_iso = parsed.strftime("%Y-%m-%d") if not pd.isna(parsed) else None
                except Exception:
                    data_iso = None

                status = row.get("Status", "Analise") or "Analise"
                if status not in ("Analise", "Aprovada", "Negada"):
                    status = "Analise"

                cnpj = str(row.get("CNPJ", "") or "")
                telefone = str(row.get("Telefone", "") or "")
                email = str(row.get("Email", "") or "")
                origem = str(row.get("Origem", "") or "")

                if pos < n_original:
                    rec_id = ids[pos]
                    if rec_id is None:
                        # não havia ID — inserir (mas exigimos nome não vazio)
                        if not nome:
                            continue
                        # fallback data para hoje se ausente
                        if not data_iso:
                            data_iso = date.today().strftime("%Y-%m-%d")
                        local_cursor.execute("""
                            INSERT INTO contas (usuario, nome, cnpj, telefone, email, data, origem, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (name, nome, cnpj, telefone, email, data_iso, origem, status))
                        local_conn.commit()
                    else:
                        # atualizar registro existente
                        if data_iso:
                            local_cursor.execute("""
                                UPDATE contas SET nome = ?, cnpj = ?, telefone = ?, email = ?, data = ?, origem = ?, status = ?
                                WHERE id = ?
                            """, (nome, cnpj, telefone, email, data_iso, origem, status, rec_id))
                        else:
                            local_cursor.execute("""
                                UPDATE contas SET nome = ?, cnpj = ?, telefone = ?, email = ?, origem = ?, status = ?
                                WHERE id = ?
                            """, (nome, cnpj, telefone, email, origem, status, rec_id))
                        local_conn.commit()
                else:
                    # nova linha (pos >= n_original): inserir se pelo menos Nome preenchido
                    if not nome:
                        continue
                    if not data_iso:
                        data_iso = date.today().strftime("%Y-%m-%d")
                    local_cursor.execute("""
                        INSERT INTO contas (usuario, nome, cnpj, telefone, email, data, origem, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (name, nome, cnpj, telefone, email, data_iso, origem, status))
                    local_conn.commit()

            # após salvar, forçar rerun para recarregar dados do DB (compatível)
            import time as _time
            # usar a API atual para definir query params
            st.query_params = {"_saved": str(int(_time.time()))}
            st.success("Alterações salvas.")
        finally:
            local_conn.close()

    # passar o objeto retornado por st.data_editor como argumento para a callback
    st.button("Salvar alterações", key="salvar_alteracoes", on_click=_save_changes, args=(edited_obj,))

    # Remover contas — expander compacto para economizar espaço
    with st.expander("🗑️ Remover contas (clique para abrir)", expanded=False):
        if df.empty:
            st.write("Sem contas para remover neste mês.")
        else:
            # criar lista compacta de opções visíveis ao usuário
            opts = []
            ids = []
            for _, r in df.reset_index(drop=True).iterrows():
                data_display = r["Data"].strftime("%d/%m/%Y") if not pd.isna(r["Data"]) else "sem data"
                opts.append(f"{r['Nome']} — {data_display} — {r.get('Status','')}")
                ids.append(r["ID"])

            choice = st.selectbox("Selecione a conta", options=[""] + opts, key="remover_select")
            if choice:
                sel_idx = opts.index(choice)
                sel_id = ids[sel_idx]
                st.markdown(f"**Selecionado:** {choice}")
                cols = st.columns([4,1])
                with cols[1]:
                    if st.button("Remover", key=f"confirm_remover_{sel_id}"):
                        cursor.execute("DELETE FROM contas WHERE id = ?", (sel_id,))
                        conn.commit()
                        st.success("Conta removida.")
                        # forçar recarregamento para atualizar a tabela
                        import time as _time
                        st.query_params = {"_removed": str(int(_time.time()))}
    import io

    import io

    if authentication_status and user_role == "master" and not df.empty:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Contas')
        output.seek(0)

        st.download_button(
            label="📥 Exportar todas as contas (Excel)",
            data=output,
            file_name="contas_completas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


    # Título da seção de projeções
    st.subheader("Projeções e detalhes")
    # Colunas para projeções detalhadas
    colA, colB = st.columns(2)

    with colA:
        st.markdown("**Projeção sem considerar em análise**")
        st.write(f"Projeção estimada (dias úteis): **{projecao_sem_bonus:.1f}** contas")
        st.write(f"Atingimento projetado: **{res_sem['atingimento']*100:.2f}%**")
        st.write(f"Comissão estimada (inclui bônus se aplicável): **R$ {res_sem['comissao_sem_bonus']:,.2f}**")
        if projecao_sem_bonus >= meta_atual:
            st.success("Ritmo atual suficiente para bater a meta (sem considerar em-análise).")
        else:
            faltam = max(meta_atual - projecao_sem_bonus, 0)
            st.warning(f"Faltam {faltam:.1f} contas para atingir a meta no ritmo atual (dias úteis).")

    with colB:
        st.markdown("**Projeção considerando contas em análise**")
        st.write(f"Projeção potencial (dias úteis): **{projecao_com_analise:.1f}** contas")
        st.write(f"Atingimento projetado (com análise): **{res_com_analise['atingimento']*100:.2f}%**")
        st.write(f"Comissão estimada (com análise, inclui bônus se aplicável): **R$ {res_com_analise['comissao_total']:,.2f}**")
        if projecao_com_analise >= meta_atual:
            st.success("Com as contas em análise, você projeta bater a meta.")
        else:
            faltam2 = max(meta_atual - projecao_com_analise, 0)
            st.info(f"Ainda faltam {faltam2:.1f} contas (considerando em análise).")

    st.markdown("---")
    # ---------- Gráficos: Origem (pizza) e Conversão (aprovadas vs total) ----------
    st.markdown("### Análise rápida")
    if df.empty:
        st.info("Sem dados para gerar gráficos neste mês.")
    else:
        # Origem: distribuição percentual (tons progressivos de azul)
        origin_series = df["Origem"].fillna("Desconhecida").astype(str)
        origin_counts = origin_series.value_counts()
        fig_origin = px.pie(
            names=origin_counts.index,
            values=origin_counts.values,
            title="Distribuição por Origem",
            hole=0.35,
            color_discrete_sequence=px.colors.sequential.Blues[4:]
        )
        fig_origin.update_traces(textposition="inside", textinfo="percent+label")

        aprovadas_cnt = total_aprovadas
        outras_cnt = int(df[df["Status"] != "Aprovada"].shape[0]) if not df.empty else 0

        # Conversão: usar dois tons de azul
        conv_colors = ["#6baed6", "#08306b"]
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

    if user_role == "master" and mes_selecionado:
        cursor.execute("""
            SELECT usuario, COUNT(*) as aprovadas
            FROM contas
            WHERE status = 'Aprovada' AND strftime('%Y-%m', data) = ?
            GROUP BY usuario
            ORDER BY aprovadas DESC
        """, (mes_selecionado,))
        ranking_dados = cursor.fetchall()
        df_ranking = pd.DataFrame(ranking_dados, columns=["Usuário", "Contas Aprovadas"])

        # Redefinir o índice para começar em 1
        df_ranking.index = range(1, len(df_ranking) + 1)

        # Exibir sem índice visual
        st.subheader("Ranking de Contas Aprovadas")
        st.dataframe(df_ranking, use_container_width=True)

    st.subheader("Gráfico de Ritmo vs Meta")
    days = np.arange(1, dias_uteis_total + 1)
    ritmo_atual = (aprovadas_input / elapsed_business) if elapsed_business > 0 else 0
    cumulativo_ritmo = ritmo_atual * days
    meta_line = np.linspace(0, meta_atual, num=len(days))
    df_line = pd.DataFrame({
        "Dia útil (índice)": days,
        "Ritmo Atual (cumulativo)": cumulativo_ritmo,
        "Meta (linha)": meta_line
    })
    # linha com cores em tons de azul
    fig_line = px.line(
        df_line,
        x="Dia útil (índice)",
        y=["Ritmo Atual (cumulativo)", "Meta (linha)"],
        labels={"value": "Contas acumuladas", "variable": "Série"},
        title="Ritmo atual vs Meta (cumulativo em dias úteis)",
        color_discrete_sequence=["#2b8cbe", "#bdd7e7"]
    )
    st.plotly_chart(fig_line, use_container_width=True)
    
    st.markdown("---")
    # ---------- Recomendações ("O que você precisa fazer") ----------
    st.subheader("O que você precisa fazer")
    if dias_uteis_restantes > 0:
        contas_faltantes = max(meta_atual - aprovadas_input, 0)
        contas_por_dia_necessarias = contas_faltantes / dias_uteis_restantes if dias_uteis_restantes > 0 else contas_faltantes
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

    # botão Sair no final da sidebar
    authenticator.logout("Sair", "sidebar")


    conn.close()
