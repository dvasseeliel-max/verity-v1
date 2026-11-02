import os
import time
import requests
import streamlit as st
from supabase import create_client
from google import genai
from openai import OpenAI

st.set_page_config(page_title="VERITY V1.5", page_icon="🔎", layout="wide")

# --- CONFIG PRIX ---
PRICING = {
    "gemini-2.5-flash": {"input": 0.30 / 1000000, "output": 2.50 / 1000000},
    "openai/gpt-oss-120b": {"input": 0.0, "output": 0.0}, # Groq gratuit pour l'instant, on met 0
    "openrouter/free": {"input": 0.0, "output": 0.0},
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

# --- INIT CLIENTS ---
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

# --- SESSION ---
if "access_token" not in st.session_state: st.session_state.access_token = None
if "comparison" not in st.session_state: st.session_state.comparison = None
if "blind_mode" not in st.session_state: st.session_state.blind_mode = True

def auth_headers():
    return {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {st.session_state.access_token}", "Content-Type": "application/json"}

def get_user_id():
    r = requests.get(SUPABASE_URL + "/auth/v1/user", headers=auth_headers(), timeout=20)
    r.raise_for_status()
    return r.json()["id"]

# --- AUTH (inchangé) ---
if not st.session_state.access_token:
    mode = st.radio("Compte", ["Se connecter", "Créer un compte"], horizontal=True)
    email = st.text_input("Adresse e-mail")
    password = st.text_input("Mot de passe", type="password")
    if mode == "Créer un compte":
        if st.button("Créer mon compte", type="primary"):
            try:
                res = sb.auth.sign_up({"email": email.strip(), "password": password})
                if res.session and res.session.access_token:
                    st.session_state.access_token = res.session.access_token
                    st.rerun()
                else: st.info("Compte créé, confirme ton email.")
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
    st.warning("Session expirée.")
    st.stop()

if st.button("Se déconnecter"):
    st.session_state.access_token = None
    st.session_state.comparison = None
    st.rerun()

# --- COMPARAISON V1.5 ---
st.title("VERITY V1.5 - Mode Pro")
st.caption(f"Connecté : {st.session_state.get('user_email','')} | Mode aveugle: {'ON' if st.session_state.blind_mode else 'OFF'}")

col_q1, col_q2 = st.columns([3,1])
with col_q1:
    question = st.text_area("Votre question", placeholder="Écrivez votre question ici…")
with col_q2:
    task_category = st.selectbox("Type de tâche (important pour YC)", ["Service Client", "Analyse Doc", "Code", "Rédaction", "Autre"])
    company_name = st.text_input("Entreprise (optionnel)", placeholder="Ex: Djamo")
    blind = st.checkbox("Mode aveugle (recommandé)", value=st.session_state.blind_mode)

st.session_state.blind_mode = blind

if st.button("Générer les trois réponses", type="primary"):
    if not question.strip(): st.warning("Écrivez une question.")
    else:
        with st.spinner("Génération…"):
            prompt = f"Réponds précisément et utilement. Réponds en français si la question est en français.\n\n{question.strip()}"
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
            else: st.subheader(f"{label} - {model_id}")
            st.caption(f"Temps: {time_s}s | Coût: ~${cost} | Tokens: ~{estimate_tokens(text)}")
            st.write(text)

    show_card(col_a, "Réponse A", comparison["response_a"], comparison["time_a"], comparison["cost_a"], comparison["model_a_id"], blind)
    show_card(col_b, "Réponse B", comparison["response_b"], comparison["time_b"], comparison["cost_b"], comparison["model_b_id"], blind)
    show_card(col_c, "Réponse C", comparison["response_c"], comparison["time_c"], comparison["cost_c"], comparison["model_c_id"], blind)

    st.divider()
    st.subheader("1. Votre vote")
    choice = st.radio("Quelle réponse préférez-vous ?", ["Réponse A", "Réponse B", "Réponse C", "Égalité"], horizontal=True)
    
    st.subheader("2. Notes qualité (1-5)")
    c1,c2,c3 = st.columns(3)
    with c1:
        ra = st.select_slider("Pertinence A", [1,2,3,4,5], 3, key="ra"); aa = st.select_slider("Exactitude A", [1,2,3,4,5], 3, key="aa"); ca = st.select_slider("Clarté A", [1,2,3,4,5], 3, key="ca")
    with c2:
        rb = st.select_slider("Pertinence B", [1,2,3,4,5], 3, key="rb"); ab = st.select_slider("Exactitude B", [1,2,3,4,5], 3, key="ab"); cb = st.select_slider("Clarté B", [1,2,3,4,5], 3, key="cb")
    with c3:
        rc = st.select_slider("Pertinence C", [1,2,3,4,5], 3, key="rc"); ac = st.select_slider("Exactitude C", [1,2,3,4,5], 3, key="ac"); cc = st.select_slider("Clarté C", [1,2,3,4,5], 3, key="cc")

    if st.button("Enregistrer", type="primary"):
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
                st.success("Enregistré en mode pro !"); 
                if blind: st.info(f"Révélation: A={comparison['model_a_id']}, B={comparison['model_b_id']}, C={comparison['model_c_id']}")
            else: st.error(f"Erreur {r.status_code}: {r.text}")
        except Exception as e: st.error(f"Erreur: {e}")
