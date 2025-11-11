import streamlit as st
import pandas as pd
import numpy as np
from datetime import date
import calendar
import plotly.express as px

st.set_page_config(page_title="Calculadora de Comissão", layout="wide")
st.title("Cálculo de Comissão e Projeções")

# ---------- Constantes internas (fixas) ----------
VAL_80_90 = 5
VAL_90_100 = 7
VAL_100_PLUS = 9

ACC_110 = 1.1
ACC_120 = 1.2

BONUS_POS = {"1": 700, "2": 500, "3": 350}

# ---------- Entradas do operador (SIDEBAR) ----------
st.sidebar.header("Entradas do Operador")

nome = st.sidebar.text_input("Seu nome", value="")
equipe = st.sidebar.selectbox("Equipe", options=["URA", "DISCADOR", "Outro"], index=0)
meta_atual = st.sidebar.number_input(
    "Meta atual (contas/mês)", min_value=0,
    value=80 if equipe == "URA" else 60, step=1
)
aprovadas_ate_agora = st.sidebar.number_input(
    "Contas aprovadas até agora", min_value=0, value=0, step=1
)
em_analise = st.sidebar.number_input(
    "Contas em análise (pendentes)", min_value=0, value=0, step=1
)
estou_no_ranking = st.sidebar.checkbox("Estou no ranking?", value=False)

pos_ranking = None
if estou_no_ranking:
    pos_choice = st.sidebar.selectbox("Se sim, qual posição?", options=["1", "2", "3", "Outro"], index=0)
    pos_ranking = pos_choice if pos_choice in ["1", "2", "3"] else None

# Simulador rápido in sidebar
st.sidebar.markdown("---")
st.sidebar.subheader("Simulador Rápido")
sim_add_aprovadas = st.sidebar.number_input("Adicionar aprovadas hipotéticas", min_value=0, value=0, step=1, key="sim_apr")
sim_add_analise = st.sidebar.number_input("Adicionar em análise hipotéticas", min_value=0, value=0, step=1, key="sim_ana")
sim_pos = st.sidebar.selectbox("Simular posição (opcional)", options=["Nenhuma", "1", "2", "3"], index=0, key="sim_pos")

# ---------- Cálculo de dias úteis e projeções ----------
# configura feriados opcionais (adicione date(YYYY, M, D) conforme necessário)
FERIADOS = [
    date(2025, 11, 20)
    # Exemplo: date(2025, 1, 1), date(2025, 4, 21)
]

# datas do mês (hoje)
hoje_date = date.today()
first_day = date(hoje_date.year, hoje_date.month, 1)
last_day = date(hoje_date.year, hoje_date.month, calendar.monthrange(hoje_date.year, hoje_date.month)[1])

# helper: conta dias úteis inclusive (usa numpy.busday_count que conta [start, end))
def dias_uteis_inclusive(start_dt: date, end_dt: date, feriados=None):
    fer = feriados or []
    # numpy.busday_count aceita numpy datetime64 or strings
    start_np = np.datetime64(start_dt)
    end_next_np = np.datetime64(end_dt) + np.timedelta64(1, 'D')
    total = int(np.busday_count(start_np, end_next_np))
    # subtrai feriados úteis dentro do intervalo
    for f in fer:
        if start_dt <= f <= end_dt:
            if np.is_busday(np.datetime64(f)):
                total -= 1
    return max(total, 0)

dias_uteis_total = dias_uteis_inclusive(first_day, last_day, FERIADOS)
dias_uteis_passados = dias_uteis_inclusive(first_day, hoje_date, FERIADOS)
dias_uteis_restantes = max(dias_uteis_total - dias_uteis_passados, 0)

# protege divisão por zero: pelo menos 1 dia útil considerado passado
elapsed_business = dias_uteis_passados if dias_uteis_passados > 0 else 1

def projecao_linear_uteis(atual, elapsed_business_days, total_business_days):
    ritmo_por_dia = atual / elapsed_business_days if elapsed_business_days > 0 else 0
    proj = ritmo_por_dia * total_business_days
    return proj

projecao_sem_bonus = projecao_linear_uteis(aprovadas_ate_agora, elapsed_business, dias_uteis_total)
projecao_com_analise = projecao_linear_uteis(aprovadas_ate_agora + em_analise, elapsed_business, dias_uteis_total)
projecao_potencial = projecao_com_analise

# ---------- Funções de comissão ----------
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

# ---------- Cálculos principais (aplica bônus automaticamente se pos informado) ----------
res_sem = calcular_comissao(projecao_sem_bonus, meta_atual, inclui_bonus=bool(pos_ranking), pos=pos_ranking)
res_com_analise = calcular_comissao(projecao_com_analise, meta_atual, inclui_bonus=bool(pos_ranking), pos=pos_ranking)
res_potencial = calcular_comissao(projecao_potencial, meta_atual, inclui_bonus=bool(pos_ranking), pos=pos_ranking)

# cenário principal: usamos projeção com análise (mais completa); bônus já aplicado quando pos informado
proj_principal_contas = projecao_com_analise
proj_principal = res_com_analise

# ---------- Aplicar simulação (se houver) ----------
if sim_add_aprovadas or sim_add_analise or sim_pos != "Nenhuma":
    sim_ap = aprovadas_ate_agora + sim_add_aprovadas
    sim_an = em_analise + sim_add_analise
    sim_pos_val = sim_pos if sim_pos in ["1", "2", "3"] else None
    sim_proj_contas = projecao_linear_uteis(sim_ap + sim_an, elapsed_business, dias_uteis_total)
    sim_res = calcular_comissao(sim_proj_contas, meta_atual, inclui_bonus=bool(sim_pos_val), pos=sim_pos_val)
else:
    sim_res = None

# ---------- Resumo rápido (inclui Comissão Final) ----------
st.header("Resumo rápido")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Meta Atual", f"{int(meta_atual)} contas")
k2.metric("Aprovadas até agora", int(aprovadas_ate_agora))
k3.metric("Em análise", int(em_analise))
k4.metric("Dias úteis restantes no mês", int(dias_uteis_restantes))

comissao_final_val = res_sem["comissao_total"]
comissao_sem_bonus_val = res_sem["comissao_sem_bonus"]
bonus_aplicado = res_sem["bonus"]
projecao_aprovadas_val = int(round(projecao_sem_bonus))



k1, k2, k3, k4 = st.columns(4)

k1.metric("Projeção de Contas", f"{projecao_aprovadas_val} contas")
k1.caption("Sem considerar contas em análise")

k2.metric("Comissão Final Estimada (R$)", f"R$ {comissao_final_val:,.2f}")
k2.caption(
    f"Sem bônus: R$ {comissao_sem_bonus_val:,.2f}" +
    (f" — Bônus: R$ {bonus_aplicado:,.2f}" if bonus_aplicado else "")
)

st.markdown("---")

# ---------- Projeções detalhadas ----------
st.subheader("Projeções e detalhes")
colA, colB = st.columns(2)

with colA:
    st.markdown("**Projeção sem considerar em análise**")
    st.write(f"Projeção estimada (dias úteis): **{projecao_sem_bonus:.1f}** contas")
    st.write(f"Atingimento projetado: **{res_sem['atingimento']*100:.2f}%**")
    st.write(f"Comissão estimada (sem bônus): **R$ {res_sem['comissao_sem_bonus']:,.2f}**")
    if projecao_sem_bonus >= meta_atual:
        st.success("Ritmo atual suficiente para bater a meta (sem considerar em análise).")
    else:
        faltam = max(meta_atual - projecao_sem_bonus, 0)
        st.warning(f"Faltam {faltam:.1f} contas para atingir a meta no ritmo atual (dias úteis).")

with colB:
    st.markdown("**Projeção considerando contas em análise**")
    st.write(f"Projeção potencial (dias úteis): **{projecao_com_analise:.1f}** contas")
    st.write(f"Atingimento projetado (com análise): **{res_com_analise['atingimento']*100:.2f}%**")
    st.write(f"Comissão estimada (com análise): **R$ {res_com_analise['comissao_total']:,.2f}**")
    if projecao_com_analise >= meta_atual:
        st.success("Com as contas em análise, você projeta bater a meta.")
    else:
        faltam2 = max(meta_atual - projecao_com_analise, 0)
        st.info(f"Ainda faltam {faltam2:.1f} contas (considerando em análise).")

st.markdown("---")

# ---------- Gráficos ----------
st.subheader("Gráficos de apoio")

# linha cumulativa usando dias úteis num eixo artificial (1..dias_uteis_total)
days = np.arange(1, dias_uteis_total + 1)
ritmo_atual = (aprovadas_ate_agora / elapsed_business) if elapsed_business > 0 else 0
cumulativo_ritmo = ritmo_atual * days
# meta representada como linha horizontal no total de dias úteis
meta_line = np.full_like(days, fill_value=meta_atual / dias_uteis_total * dias_uteis_total if dias_uteis_total > 0 else meta_atual)
df_line = pd.DataFrame({
    "Dia útil (índice)": days,
    "Ritmo Atual (cumulativo)": cumulativo_ritmo,
    "Meta (linha)": meta_line
})
fig_line = px.line(df_line, x="Dia útil (índice)", y=["Ritmo Atual (cumulativo)", "Meta (linha)"],
                   labels={"value": "Contas acumuladas", "variable": "Série"},
                   title="Ritmo atual vs Meta (cumulativo em dias úteis)")
st.plotly_chart(fig_line, use_container_width=True)


# ---------- O que fazer para comissionar mais ----------
st.subheader("O que você precisa fazer")
if dias_uteis_restantes > 0:
    contas_faltantes = max(meta_atual - aprovadas_ate_agora, 0)
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
if em_analise > 0:
    recs.append("Acompanhe rapidamente os casos em análise para convertê-los em aprovados.")
if not pos_ranking:
    recs.append("Entrar no ranking aumenta suas chances de bônus; busque posição entre os 3 primeiros.")
else:
    recs.append(f"Você indicou posição {pos_ranking} no ranking — isso foi considerado nos cálculos.")

for r in recs:
    st.write("- " + r)

st.markdown("---")

# ---------- Exportação leve (resumo) ----------
if st.button("Gerar resumo (copiar/colar)"):
    resumo = {
        "nome": nome,
        "meta_atual": meta_atual,
        "aprovadas_ate_agora": aprovadas_ate_agora,
        "em_analise": em_analise,
        "projecao_principal_contas": round(proj_principal_contas, 2),
        "comissao_principal": round(comissao_final_val, 2),
        "comissao_sem_bonus": round(comissao_sem_bonus_val, 2),
        "pos_ranking": pos_ranking or "Nenhuma",
        "dias_uteis_restantes": int(dias_uteis_restantes)
    }
    st.code(pd.Series(resumo).to_json(orient="columns"))

st.caption("Projeção linear em dias úteis — ajuste metas ou feriados conforme operação.")
