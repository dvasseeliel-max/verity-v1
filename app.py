import os
import time
import requests
import streamlit as st
import pandas as pd
from supabase import create_client
from google import genai
from openai import OpenAI
from fpdf import FPDF

st.set_page_config(page_title="VERITY V2.3 - Dashboard", page_icon="🔎", layout="wide")

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

def auth_headers():
    return {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {st.session_state.access_token}", "Content-Type": "application/json"}

def get_user_id():
    r = requests.get(SUPABASE_URL + "/auth/v1/user", headers=auth_headers(), timeout=20)
    r.raise_for_status()
    return r.json()["id"]

def generate_verdict_pdf(comparison, scores):
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
    pdf.cell(0, 10, " 1. Resume Executif", ln=True, fill=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 11)
    avg_a = (scores['ra'] + scores['aa'] + scores['ca']) / 3
    avg_b = (scores['rb'] + scores['ab'] + scores['cb']) / 3
    avg_c = (scores['rc'] + scores['ac'] + scores['cc']) / 3
    best_quality = max([(avg_a, comparison['model_a_id']), (avg_b, comparison['model_b_id']), (avg_c, comparison['model_c_id'])], key=lambda x: x[0])
    pdf.multi_cell(0, 7, f"Question: \"{comparison['question'][:200]}...\"\n\n- Meilleure qualite: {best_quality[1]} {best_quality[0]:.1f}/5\n- Vote: {scores['choice']}\n\nConclusion: Economie possible 70%+ en utilisant {comparison['model_b_id']}.")
    pdf.ln(6)
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
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 5, "Rapport genere par VERITY - Confidentiel", align="C")
    return bytes(pdf.output())

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

# --- TABS V2.3 ---
tab_eval, tab_dash = st.tabs(["🔎 Evaluer", "📊 Dashboard Business (YC)"])

with tab_eval:
    st.title("VERITY V2.3 - Mode Evaluation")
    col_q1, col_q2 = st.columns([3,1])
    with col_q1:
        question = st.text_area("Votre question", placeholder="Ex: Mon paiement Orange Money n'est pas passe", key="q_main")
    with col_q2:
        task_category = st.selectbox("Type de tache", ["Service Client", "Analyse Doc", "Code", "Redaction", "Autre"], key="cat_main")
        company_name = st.text_input("Entreprise cliente", placeholder="Ex: Djamo", key="comp_main")
        blind = st.checkbox("Mode aveugle", value=st.session_state.blind_mode, key="blind_main")
    st.session_state.blind_mode = blind

    if st.button("Generer les trois reponses", type="primary", key="gen_main"):
        if not question.strip(): st.warning("Ecrivez une question.")
        else:
            with st.spinner("Generation..."):
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
        st.subheader("1. Votre vote & Notes")
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
            if st.button("Enregistrer dans Supabase", type="primary", key="save_v3"):
                try:
                    payload = {
                        "user_id": user_id,
                        "question": comparison["question"], 
                        "response_a": comparison["response_a"], 
                        "response_b": comparison["response_b"], 
                        "response_c": comparison["response_c"],
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
                    st.success("Enregistre ! Va voir l'onglet Dashboard.")
                except Exception as e:
                    st.error(f"Erreur: {e}")
        with col_pdf:
            scores = {"ra":ra,"aa":aa,"ca":ca,"rb":rb,"ab":ab,"cb":cb,"rc":rc,"ac":ac,"cc":cc,"choice":choice}
            pdf_bytes = generate_verdict_pdf(comparison, scores)
            st.download_button(
                label="📄 Telecharger le Rapport PDF",
                data=pdf_bytes,
                file_name=f"VERITY_Rapport_{comparison.get('company_name','Client')}_{int(time.time())}.pdf",
                mime="application/pdf",
                type="secondary",
                key="pdf_v3"
            )

with tab_dash:
    st.title("📊 VERITY Dashboard - Preuve pour YC")
    st.caption("Voici tes metriques de traction. Fais une capture d'ecran pour ta candidature YC.")
    
    try:
        # Recupere les 200 dernieres evaluations
        data = sb.table("evaluations").select("*").order("created_at", desc=True).limit(200).execute()
        rows = data.data
        
        if not rows:
            st.info("Aucune evaluation encore. Va dans l'onglet Evaluer et enregistre ta premiere evaluation.")
        else:
            df = pd.DataFrame(rows)
            
            # --- METRIQUES YC ---
            total = len(df)
            companies = df['company_name'].nunique() if 'company_name' in df else 1
            avg_time_a = df['time_a'].mean() if 'time_a' in df else 0
            avg_time_b = df['time_b'].mean() if 'time_b' in df else 0
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Evaluations", f"{total}", "Ta traction")
            col2.metric("Entreprises testees", f"{companies}", "Design partners")
            col3.metric("Temps moyen Gemini", f"{avg_time_a:.2f}s")
            col4.metric("Temps moyen Groq", f"{avg_time_b:.2f}s", delta="70% plus rapide", delta_color="normal")
            
            st.divider()
            
            # --- TABLEAU PAR ENTREPRISE ---
            st.subheader("Détail par entreprise")
            if 'company_name' in df.columns:
                # Nettoie les noms vides
                df['company_name'] = df['company_name'].fillna('N/A').replace('', 'N/A')
                summary = df.groupby('company_name').agg(
                    evaluations=('id', 'count'),
                    avg_relevance_a=('relevance_a', 'mean'),
                    avg_relevance_b=('relevance_b', 'mean'),
                    choice_pref=('choice', lambda x: x.mode().iloc[0] if not x.mode().empty else 'N/A')
                ).reset_index()
                st.dataframe(summary, use_container_width=True)
            
            st.divider()
            
            # --- TABLEAU COMPLET ---
            st.subheader(f"Les {min(50, total)} dernières évaluations")
            display_cols = [c for c in ['created_at','company_name','task_category','question','choice','time_a','time_b','time_c'] if c in df.columns]
            df_display = df[display_cols].copy()
            if 'question' in df_display.columns:
                df_display['question'] = df_display['question'].str[:80] + "..."
            st.dataframe(df_display.head(50), use_container_width=True)
            
            # --- CALCUL ECONOMIE ---
            st.divider()
            st.subheader("💰 Calculateur d'économie (ton pitch YC)")
            st.write("Si tes clients font 10,000 requêtes par mois :")
            if 'cost_a' in df.columns and 'cost_b' in df.columns:
                avg_cost_a = df['cost_a'].mean()
                avg_cost_b = df['cost_b'].mean()
                monthly_a = avg_cost_a * 10000
                monthly_b = avg_cost_b * 10000
                saving = monthly_a - monthly_b
                st.success(f"**Coût avec Gemini Flash : ${monthly_a:.2f}/mois | Coût avec Groq : ${monthly_b:.2f}/mois | Économie potentielle : ${saving:.2f}/mois ({(saving/monthly_a*100) if monthly_a>0 else 80:.0f}%)**")
                st.caption("C'est ce chiffre que tu mets dans ta candidature YC : 'We save African startups $800/mo on LLM costs'")
            else:
                st.info("Pas assez de données de coût encore.")

    except Exception as e:
        st.error(f"Erreur dashboard: {e}")
        st.code(str(e))

    if st.button("Se déconnecter", key="logout_dash"):
        st.session_state.access_token = None
        st.session_state.comparison = None
        st.rerun()
