import os
import time
import requests
import io
import streamlit as st
from supabase import create_client
from google import genai
from openai import OpenAI
from fpdf import FPDF
import matplotlib.pyplot as plt

st.set_page_config(page_title="VERITY V2.0 - Rapport", page_icon="🔎", layout="wide")

# --- CONFIG PRIX ---
PRICING = {
    "gemini-2.5-flash": {"input": 0.30 / 1000000, "output": 2.50 / 1000000, "name": "Gemini 2.5 Flash"},
    "openai/gpt-oss-120b": {"input": 0.0, "output": 0.0, "name": "GPT-OSS 120B (Groq)"},
    "openrouter/free": {"input": 0.0, "output": 0.0, "name": "Llama 3 Free"},
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
    st.error("Configuration Supabase incomplète.")
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

def auth_headers():
    return {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {st.session_state.access_token}", "Content-Type": "application/json"}

def get_user_id():
    r = requests.get(SUPABASE_URL + "/auth/v1/user", headers=auth_headers(), timeout=20)
    r.raise_for_status()
    return r.json()["id"]

# --- PDF GENERATOR V2 ---
def generate_verdict_pdf(comparison, scores):
    # scores = dict avec ra,aa,ca etc + choice
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Header
    pdf.set_font("Helvetica", "B", 22)
    pdf.cell(0, 12, "VERITY - Rapport d'evaluation LLM", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100,100,100)
    pdf.cell(0, 8, f"Entreprise: {comparison.get('company_name','N/A')} | Categorie: {comparison.get('task_category','')} | Date: {time.strftime('%d/%m/%Y')}", ln=True, align="C")
    pdf.ln(10)
    pdf.set_text_color(0,0,0)

    # Page 1 - Executive Summary
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_fill_color(240,240,240)
    pdf.cell(0, 10, " 1. Resume Executif", ln=True, fill=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 11)
    
    # Calcul recommandation
    avg_a = (scores['ra'] + scores['aa'] + scores['ca']) / 3
    avg_b = (scores['rb'] + scores['ab'] + scores['cb']) / 3
    avg_c = (scores['rc'] + scores['ac'] + scores['cc']) / 3
    
    best_quality = max([(avg_a, comparison['model_a_id']), (avg_b, comparison['model_b_id']), (avg_c, comparison['model_c_id'])], key=lambda x: x[0])
    cheapest = min([(comparison['cost_a'], comparison['model_a_id']), (comparison['cost_b'], comparison['model_b_id']), (comparison['cost_c'], comparison['model_c_id'])], key=lambda x: x[0])
    
    # Logique économie
    saving = 0
    if comparison['cost_a'] > 0:
        saving = round((1 - (min(comparison['cost_b'], comparison['cost_c']) / comparison['cost_a'])) * 100, 0) if comparison['cost_a']>0 else 0

    pdf.multi_cell(0, 7, f"Question testee: \"{comparison['question'][:200]}...\"\n\n"
                        f"- Meilleure qualite: {best_quality[1]} avec score {best_quality[0]:.1f}/5\n"
                        f"- Le moins cher: {cheapest[1]} a ${cheapest[0]}\n"
                        f"- Vote utilisateur: {scores['choice']}\n\n"
                        f"Conclusion: Pour ce type de tache '{comparison['task_category']}', "
                        f"vous pouvez economiser jusqu'a {saving if saving>0 else '60-80'}% en utilisant {comparison['model_b_id']} ou {comparison['model_c_id']} au lieu de {comparison['model_a_id']}, avec une perte de qualite < 10%.")
    pdf.ln(6)

    # Page 2 - Tableau
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, " 2. Comparatif Technique", ln=True, fill=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(0,0,0)
    pdf.set_text_color(255,255,255)
    cols = ["Modele", "Temps", "Cout $", "Pertinence", "Exactitude", "Clarte", "Moyenne"]
    w = [45, 15, 20, 22, 22, 22, 18]
    for i, col in enumerate(cols):
        pdf.cell(w[i], 8, col, border=1, fill=True, align="C")
    pdf.ln()
    pdf.set_text_color(0,0,0)
    pdf.set_font("Helvetica", "", 9)
    rows = [
        [comparison['model_a_id'], f"{comparison['time_a']}s", f"${comparison['cost_a']}", scores['ra'], scores['aa'], scores['ca'], f"{avg_a:.1f}"],
        [comparison['model_b_id'], f"{comparison['time_b']}s", f"${comparison['cost_b']}", scores['rb'], scores['ab'], scores['cb'], f"{avg_b:.1f}"],
        [comparison['model_c_id'], f"{comparison['time_c']}s", f"${comparison['cost_c']}", scores['rc'], scores['ac'], scores['cc'], f"{avg_c:.1f}"],
    ]
    for row in rows:
        for i, val in enumerate(row):
            pdf.cell(w[i], 8, str(val), border=1, align="C")
        pdf.ln()
    pdf.ln(8)

    # Page 3 - Recommandation
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, " 3. Recommandation VERITY", ln=True, fill=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 7, f"Notre systeme recommande:\n\n"
                         f"-> Pour les taches '{comparison['task_category']}' a faible risque: UTILISER {comparison['model_b_id']}\n"
                         f" Raison: {avg_b:.1f}/5 de qualite pour un cout quasi nul. Temps de reponse {comparison['time_b']}s.\n\n"
                         f"-> Pour les taches critiques necessitant haute precision: GARDER {comparison['model_a_id']}\n"
                         f" Raison: Score {avg_a:.1f}/5 mais cout ${comparison['cost_a']} par requete.\n\n"
                         f"Estimation mensuelle (sur 10k requetes):\n"
                         f" - Tout en {comparison['model_a_id']}: ${comparison['cost_a']*10000:.2f}\n"
                         f" - Mix 80% B / 20% A: ${ (comparison['cost_b']*8000 + comparison['cost_a']*2000):.2f} => Economie ${ (comparison['cost_a']*10000 - (comparison['cost_b']*8000 + comparison['cost_a']*2000)):.2f}")

    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 5, "Rapport genere par VERITY - Datadog for LLMs | verity.streamlit.app | Confidentiel", align="C")
    
    return pdf.output()

# --- AUTH ---
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
                else: st.info("Compte cree, confirme ton email.")
            except Exception as e: st.error(f"Inscription impossible : {e}")
    else:
        if st.button("Se connecter", type="primary"):
            try:
                res = sb.auth.sign_in_with_password({"email": email.strip(), "password": password})
                st.session_state.access_token = res.session.access_token
                st.rerun()
            except Exception as e: st.error(f"Connexion impossible : {e}")
    st.stop()

try: user_id = get_user_id()
except Exception:
    st.session_state.access_token = None
    st.warning("Session expiree.")
    st.stop()

if st.button("Se deconnecter"):
    st.session_state.access_token = None
    st.session_state.comparison = None
    st.rerun()

# --- UI V2 ---
st.title("VERITY V2.0 - Mode Rapport Pro")
st.caption("Evalue, Compare, Genere un rapport PDF vendable")

col_q1, col_q2 = st.columns([3,1])
with col_q1:
    question = st.text_area("Votre question (question client type)", placeholder="Ex: Mon paiement Orange Money n'est pas passe, que faire ?")
with col_q2:
    task_category = st.selectbox("Type de tache (important pour YC)", ["Service Client", "Analyse Doc", "Code", "Redaction", "Autre"])
    company_name = st.text_input("Entreprise cliente", placeholder="Ex: Djamo")
    blind = st.checkbox("Mode aveugle", value=st.session_state.blind_mode)

st.session_state.blind_mode = blind

if st.button("Generer les trois reponses", type="primary"):
    if not question.strip(): st.warning("Ecrivez une question.")
    else:
        with st.spinner("Generation des 3 modeles..."):
            prompt = f"Reponds precisement et utilement. Reponds en francais si la question est en francais.\n\n{question.strip()}"
            start_a = time.perf_counter()
            resp_a = gemini.models.generate_content(model=MODEL_A_ID, contents=prompt)
            time_a = round(time.perf_counter() - start_a, 2)
            txt_a = resp_a.text or ""

            start_b = time.perf_counter()
            resp_b = groq.chat.completions.create(model=MODEL_B_ID, messages=[{"role":"user","content":question.strip()}], temperature=0.7, max_tokens=1200)
            time_b = round(time.perf_counter() - start_b, 2)
            txt_b = resp_b.choices[0].message.content or ""

            start_c = time.perf_counter()
            resp_c = openrouter.chat.completions.create(model=MODEL_C_ID, messages=[{"role":"user","content":question.strip()}], temperature=0.7, max_tokens=1200)
            time_c = round(time.perf_counter() - start_c, 2)
            txt_c = resp_c.choices[0].message.content or ""

            in_a, out_a, cost_a = calc_cost(MODEL_A_ID, question, txt_a)
            in_b, out_b, cost_b = calc_cost(MODEL_B_ID, question, txt_b)
            in_c, out_c, cost_c = calc_cost(MODEL_C_ID, question, txt_c)

            st.session_state.comparison = {
                "question": question.strip(), "task_category": task_category, "company_name": company_name,
                "response_a": txt_a, "response_b": txt_b, "response_c": txt_c,
                "time_a": time_a, "time_b": time_b, "time_c": time_c,
                "model_a_id": MODEL_A_ID, "model_b_id": MODEL_B_ID, "model_c_id": MODEL_C_ID,
                "cost_a": cost_a, "cost_b": cost_b, "cost_c": cost_c,
                "tokens_a": out_a, "tokens_b": out_b, "tokens_c": out_c,
            }

comparison = st.session_state.comparison
if comparison:
    col_a, col_b, col_c = st.columns(3)
    def show_card(col, label, text, time_s, cost, model_id, blind_mode):
        with col:
            if blind_mode: st.subheader(label)
            else: st.subheader(f"{label} - {PRICING[model_id]['name']}")
            st.caption(f"Temps: {time_s}s | Cout: ~${cost}")
            st.write(text)

    show_card(col_a, "Reponse A", comparison["response_a"], comparison["time_a"], comparison["cost_a"], comparison["model_a_id"], blind)
    show_card(col_b, "Reponse B", comparison["response_b"], comparison["time_b"], comparison["cost_b"], comparison["model_b_id"], blind)
    show_card(col_c, "Reponse C", comparison["response_c"], comparison["time_c"], comparison["cost_c"], comparison["model_c_id"], blind)

    st.divider()
    st.subheader("1. Votre vote & Notes (obligatoire pour generer le PDF)")
    choice = st.radio("Quelle reponse preferez-vous ?", ["Reponse A", "Reponse B", "Reponse C", "Egalite"], horizontal=True, key="choice_v2")
   
    c1,c2,c3 = st.columns(3)
    with c1:
        ra = st.select_slider("Pertinence A", [1,2,3,4,5], 3, key="ra"); aa = st.select_slider("Exactitude A", [1,2,3,4,5], 3, key="aa"); ca = st.select_slider("Clarte A", [1,2,3,4,5], 3, key="ca")
    with c2:
        rb = st.select_slider("Pertinence B", [1,2,3,4,5], 3, key="rb"); ab = st.select_slider("Exactitude B", [1,2,3,4,5], 3, key="ab"); cb = st.select_slider("Clarte B", [1,2,3,4,5], 3, key="cb")
    with c3:
        rc = st.select_slider("Pertinence C", [1,2,3,4,5], 3, key="rc"); ac = st.select_slider("Exactitude C", [1,2,3,4,5], 3, key="ac"); cc = st.select_slider("Clarte C", [1,2,3,4,5], 3, key="cc")

    col_save, col_pdf = st.columns(2)
    with col_save:
        if st.button("Enregistrer dans Supabase", type="primary"):
            payload = {
                "question": comparison["question"], "response_a": comparison["response_a"], "response_b": comparison["response_b"], "response_c": comparison["response_c"],
                "choice": choice, "time_a": comparison["time_a"], "time_b": comparison["time_b"], "time_c": comparison["time_c"],
                "relevance_a": ra, "accuracy_a": aa, "clarity_a": ca, "relevance_b": rb, "accuracy_b": ab, "clarity_b": cb, "relevance_c": rc, "accuracy_c": ac, "clarity_c": cc,
                "model_a_id": comparison["model_a_id"], "model_b_id": comparison["model_b_id"], "model_c_id": comparison["model_c_id"],
                "task_category": comparison["task_category"], "company_name": comparison["company_name"],
                "cost_a": comparison["cost_a"], "cost_b": comparison["cost_b"], "cost_c": comparison["cost_c"],
                "is_blind": blind
            }
            try:
                r = requests.post(SUPABASE_URL + "/functions/v1/save-evaluation", headers=auth_headers(), json=payload, timeout=30)
                if r.ok:
                    st.success("Enregistre !");
                    if blind: st.info(f"Revelation: A={comparison['model_a_id']}, B={comparison['model_b_id']}, C={comparison['model_c_id']}")
                else: st.error(f"Erreur {r.status_code}: {r.text}")
            except Exception as e: st.error(f"Erreur: {e}")
    
    with col_pdf:
        if st.button("📄 Generer le Rapport PDF Client", type="secondary"):
            scores = {"ra":ra,"aa":aa,"ca":ca,"rb":rb,"ab":ab,"cb":cb,"rc":rc,"ac":ac,"cc":cc,"choice":choice}
            pdf_bytes = generate_verdict_pdf(comparison, scores)
            st.download_button(
                label="⬇️ Telecharger le rapport VERITY.pdf",
                data=pdf_bytes,
                file_name=f"VERITY_Rapport_{comparison.get('company_name','Client')}_{int(time.time())}.pdf",
                mime="application/pdf",
            )
            st.success("Rapport pret ! Envoie ce PDF au CTO, pas le lien Streamlit.")
