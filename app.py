import os
import time
import requests
import streamlit as st
import pandas as pd
from supabase import create_client
from google import genai
from openai import OpenAI
from fpdf import FPDF

st.set_page_config(page_title="VERITY V2.4 - Dashboard", page_icon="VERITY", layout="wide")

PRICING = {
    "gemini-2.5-flash": {"input": 0.30 / 1000000, "output": 2.50 / 1000000, "name": "Gemini 2.5 Flash", "provider": "Google"},
    "openai/gpt-oss-120b": {"input": 0.0, "output": 0.0, "name": "GPT-OSS 120B (Groq)", "provider": "Groq"},
    "openrouter/free": {"input": 0.0, "output": 0.0, "name": "Llama 3 Free", "provider": "OpenRouter"},
}
MODEL_A_ID = "gemini-2.5-flash"
MODEL_B_ID = "openai/gpt-oss-120b"
MODEL_C_ID = "openrouter/free"

def estimate_tokens(text):
    return max(1, int(len(text) / 4))

def calc_cost(model_id, input_text, output_text):
    p = PRICING.get(model_id, {"input": 0, "output": 0})
    in_tok = estimate_tokens(input_text)
    out_tok = estimate_tokens(output_text)
    cost = (in_tok * p["input"]) + (out_tok * p["output"])
    return in_tok, out_tok, round(cost, 6)

def read_secret(name):
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    if not value:
        value = os.getenv(name, "")
    return str(value).strip()

SUPABASE_URL = read_secret("VERITY_SUPABASE_URL").rstrip("/")
SUPABASE_KEY = read_secret("VERITY_SUPABASE_KEY")
GEMINI_KEY = read_secret("VERITY_GEMINI_KEY")
GROQ_KEY = read_secret("VERITY_GROQ_KEY")
OPENROUTER_KEY = read_secret("VERITY_OPENROUTER_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Configuration Supabase incomplete.")
    st.stop()
try:
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    gemini = genai.Client(api_key=GEMINI_KEY)
except Exception as e:
    st.error(f"Init impossible : {e}")
    st.stop()

groq = OpenAI(api_key=GROQ_KEY, base_url="https://api.groq.com/openai/v1") if GROQ_KEY else None
openrouter = OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1") if OPENROUTER_KEY else None

if "access_token" not in st.session_state: st.session_state.access_token = None
if "comparison" not in st.session_state: st.session_state.comparison = None
if "blind_mode" not in st.session_state: st.session_state.blind_mode = True
if "quality_guardrail" not in st.session_state: st.session_state.quality_guardrail = 4.0

def auth_headers():
    return {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {st.session_state.access_token}", "Content-Type": "application/json"}

def get_user_id():
    r = requests.get(SUPABASE_URL + "/auth/v1/user", headers=auth_headers(), timeout=20)
    r.raise_for_status()
    return r.json()["id"]

def auto_route_logic(avg_scores, costs, guardrail):
    eligible = {mid: score for mid, score in avg_scores.items() if score >= guardrail}
    if not eligible:
        return None, "Aucun modele ne respecte votre seuil de qualite"
    cheapest = min(eligible.items(), key=lambda x: costs.get(x[0], 999))
    return cheapest[0], f"Route vers {cheapest[0]} - respecte qualite >= {guardrail}/5 et cout le plus bas"

def generate_verdict_pdf(comparison, scores, extra_metrics):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Helvetica", "B", 22)
    pdf.cell(0, 12, "VERITY - Rapport d'evaluation LLM", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100,100,100)
    pdf.cell(0, 8, f"Entreprise: {comparison.get('company_name','N/A')} | Categorie: {comparison.get('task_category','')} | Date: {time.strftime('%d/%m/%Y')}", ln=True, align="C")
    pdf.ln(10)
    pdf.set_text_color(0,0,0)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_fill_color(240,240,240)
    pdf.cell(0, 10, " 1. Resume Executif - Pour le CFO", ln=True, fill=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 7, extra_metrics.get('cfo_text',''))
    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, " 2. Comparatif Technique + Vitesse", ln=True, fill=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(0,0,0)
    pdf.set_text_color(255,255,255)
    cols = ["Modele", "Temps", "Cout $", "Pert.", "Exact.", "Clarte", "Moyenne", "Quality Score"]
    w = [38, 12, 15, 15, 15, 15, 15, 28]
    for i, col in enumerate(cols):
        pdf.cell(w[i], 8, col, border=1, fill=True, align="C")
    pdf.ln()
    pdf.set_text_color(0,0,0)
    pdf.set_font("Helvetica", "", 8)
    for row in extra_metrics.get('rows',[]):
        for i, val in enumerate(row):
            pdf.cell(w[i], 8, str(val), border=1, align="C")
        pdf.ln()
    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, " 3. Recommandation Auto-Routing", ln=True, fill=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 7, extra_metrics.get('routing_text',''))
    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, " 4. Economies par Use-Case", ln=True, fill=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 7, extra_metrics.get('usecase_text',''))
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 5, "Rapport genere par VERITY V2.4 - Confidentiel | Private Audit Mode", align="C")
    return bytes(pdf.output())

if not st.session_state.access_token:
    mode = st.radio("Compte", ["Se connecter", "Creer un compte"], horizontal=True)
    email = st.text_input("Adresse e-mail")
    password = st.text_input("Mot de passe", type="password")
    if mode == "Creer un compte":
        if st.button("Creer mon compte", type="primary"):
            try:
                res = sb.auth.sign_up({"email": email.strip(), "password": password})
                if res.session and res.session.access_token:
                    st.session_state.access_token = res.session.access_token
                    st.rerun()
                else: st.info("Compte cree, confirme toncol_save, col_pdf = st.columns(2)
        with col_save:
            if st.button("Enregistrer cette evaluation dans mon dashboard", type="primary", key="save_v3", use_container_width=True):
                try:
                    payload = {
                        "user_id": user_id,
                        "question": "PRIVATE - Mode prive active" if comparison.get('private_mode') else comparison["question"],
                        "response_a": "PRIVATE" if comparison.get('private_mode') else comparison["response_a"],
                        "response_b": "PRIVATE" if comparison.get('private_mode') else comparison["response_b"],
                        "response_c": "PRIVATE" if comparison.get('private_mode') else comparison["response_c"],
                        "choice": choice,
                        "time_a": comparison["time_a"], "time_b": comparison["time_b"], "time_c": comparison["time_c"],
                        "relevance_a": ra, "accuracy_a": aa, "clarity_a": ca,
                        "relevance_b": rb, "accuracy_b": ab, "clarity_b": cb,
                        "relevance_c": rc, "accuracy_c": ac, "clarity_c": cc,
                        "model_a_id": comparison["model_a_id"], "model_b_id": comparison["model_b_id"], "model_c_id": comparison["model_c_id"],
                        "task_category": comparison["task_category"], "company_name": comparison["company_name"],
                        "cost_a": comparison["cost_a"], "cost_b": comparison["cost_b"], "cost_c": comparison["cost_c"],
                        "is_blind": blind
                    }
                    res = sb.table("evaluations").insert(payload).execute()
                    st.success("Enregistre ! Allez voir onglet 3. Dashboard")
                except Exception as e:
                    st.error(f"Erreur: {e}")
        with col_pdf:
            monthly_a = comparison['cost_a'] * 10000
            monthly_b = comparison['cost_b'] * 10000
            monthly_c = comparison['cost_c'] * 10000
            saving = monthly_a - min(monthly_b, monthly_c)
            pct = (saving/monthly_a*100) if monthly_a>0 else 80
            cfo_text = f"Pour 10,000 requetes/mois de type '{comparison['task_category']}'\n- Cout actuel ({comparison['model_a_id']}): ${monthly_a:.2f}/mois\n- Cout optimise ({comparison['model_b_id']}): ${monthly_b:.2f}/mois\n- Economie: ${saving:.2f}/mois soit {pct:.0f}%\n- Economie annuelle: ${saving*12:.2f}\n- Vitesse gagnee: {comparison['time_a'] - min(comparison['time_b'], comparison['time_c']):.2f}s par requete"
            routing_text = f"Modele recommande: {best_model or 'Garder actuel'} - Raison: {routing_msg}\nGuardrail qualite: >= {comparison.get('guardrail')}/5\nFallback automatique: Si {best_model} tombe, VERITY rebascule sur {comparison['model_a_id']} sans downtime."
            usecase_text = f"Categorie: {comparison['task_category']} | Entreprise: {comparison['company_name']}"
            rows = [
                [comparison['model_a_id'], f"{comparison['time_a']}s", f"${comparison['cost_a']}", ra, aa, ca, f"{avg_a:.1f}", f"{avg_a/5*100:.0f}%"],
                [comparison['model_b_id'], f"{comparison['time_b']}s", f"${comparison['cost_b']}", rb, ab, cb, f"{avg_b:.1f}", f"{avg_b/5*100:.0f}%"],
                [comparison['model_c_id'], f"{comparison['time_c']}s", f"${comparison['cost_c']}", rc, ac, cc, f"{avg_c:.1f}", f"{avg_c/5*100:.0f}%"],
            ]
            extra = {"cfo_text": cfo_text, "routing_text": routing_text, "usecase_text": usecase_text, "rows": rows}
            scores = {"ra":ra,"aa":aa,"ca":ca,"rb":rb,"ab":ab,"cb":cb,"rc":rc,"ac":ac,"cc":cc,"choice":choice}
            pdf_bytes =
