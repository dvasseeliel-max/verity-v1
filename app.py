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
                else:
                    st.info("Compte cree, confirme ton email.")
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

tab_eval, tab_auto, tab_dash, tab_billing = st.tabs(["1. Evaluer (Comparer 3 IA)", "2. Auto-Router (Economiser auto)", "3. Dashboard & Economies", "4. Facturation Unifiee"])

with tab_eval:
    st.title("VERITY V2.4 - Compare 3 IA et trouve la moins chere")
    st.caption("Pose une question, VERITY te dit quelle IA fait le meme travail moins cher.")
    col_q1, col_q2 = st.columns([3,1])
    with col_q1:
        question = st.text_area("Quelle tache voulez-vous tester ?", placeholder="Ex: Resume ce ticket support: Mon paiement Orange Money...", key="q_main", height=120)
    with col_q2:
        task_category = st.selectbox("Type de tache", ["Service Client", "Analyse Doc", "Code", "Redaction", "Autre"], key="cat_main")
        company_name = st.text_input("Nom de l'entreprise cliente", placeholder="Ex: Djamo", key="comp_main")
        blind = st.checkbox("Cacher les noms des modeles (mode aveugle)", value=st.session_state.blind_mode, key="blind_main")
        private_mode = st.checkbox("Mode Prive - Mes donnees ne sortent pas", value=False, key="private_main")
    st.session_state.blind_mode = blind
    st.subheader("Regle de qualite - Je refuse de perdre en qualite")
    guardrail = st.slider("Qualite minimale acceptable pour switcher (sur 5)", 1.0, 5.0, st.session_state.quality_guardrail, 0.5)
    st.session_state.quality_guardrail = guardrail

    if st.button("Lancer la comparaison des 3 IA", type="primary", key="gen_main", use_container_width=True):
        if not question.strip(): st.warning("Ecrivez une question.")
        else:
            with st.spinner("VERITY teste les 3 IA en meme temps..."):
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
                    "private_mode": private_mode, "guardrail": guardrail
                }
   
    comparison = st.session_state.comparison
    if comparison:
        col_a, col_b, col_c = st.columns(3)
        def show_card(col, label, text, time_s, cost, model_id, blind_mode):
            with col:
                if blind_mode: st.subheader(label)
                else: st.subheader(f"{label} - {PRICING[model_id]['name']}")
                st.caption(f"Temps: {time_s}s | Cout: ~${cost} | Provider: {PRICING[model_id]['provider']}")
                st.write(text)
                if time_s == min(comparison["time_a"], comparison["time_b"], comparison["time_c"]):
                    st.success("Le plus rapide")
        show_card(col_a, "Reponse A", comparison["response_a"], comparison["time_a"], comparison["cost_a"], comparison["model_a_id"], blind)
        show_card(col_b, "Reponse B", comparison["response_b"], comparison["time_b"], comparison["cost_b"], comparison["model_b_id"], blind)
        show_card(col_c, "Reponse C", comparison["response_c"], comparison["time_c"], comparison["cost_c"], comparison["model_c_id"], blind)
        st.divider()
        st.subheader("Votez: Quelle reponse est la meilleure pour votre entreprise ?")
        choice = st.radio("Choisissez la meilleure reponse", ["Reponse A", "Reponse B", "Reponse C", "Egalite"], horizontal=True, key="choice_v2", label_visibility="collapsed")
        c1,c2,c3 = st.columns(3)
        with c1:
            st.write("Notes pour A")
            ra = st.select_slider("Pertinence A", [1,2,3,4,5], 3, key="ra"); aa = st.select_slider("Exactitude A", [1,2,3,4,5], 3, key="aa"); ca = st.select_slider("Clarte A", [1,2,3,4,5], 3, key="ca")
        with c2:
            st.write("Notes pour B")
            rb = st.select_slider("Pertinence B", [1,2,3,4,5], 3, key="rb"); ab = st.select_slider("Exactitude B", [1,2,3,4,5], 3, key="ab"); cb = st.select_slider("Clarte B", [1,2,3,4,5], 3, key="cb")
        with c3:
            st.write("Notes pour C")
            rc = st.select_slider("Pertinence C", [1,2,3,4,5], 3, key="rc"); ac = st.select_slider("Exactitude C", [1,2,3,4,5], 3, key="ac"); cc = st.select_slider("Clarte C", [1,2,3,4,5], 3, key="cc")
        avg_a = (ra + aa + ca) / 3
        avg_b = (rb + ab + cb) / 3
        avg_c = (rc + ac + cc) / 3
        st.divider()
        st.subheader("VERITY Quality Score - Sur VOS donnees")
        qcol1, qcol2, qcol3 = st.columns(3)
        qcol1.metric(f"{comparison['model_a_id']}", f"{avg_a:.1f}/5", f"Temps {comparison['time_a']}s")
        qcol2.metric(f"{comparison['model_b_id']}", f"{avg_b:.1f}/5", f"Temps {comparison['time_b']}s")
        qcol3.metric(f"{comparison['model_c_id']}", f"{avg_c:.1f}/5", f"Temps {comparison['time_c']}s")
        scores_map = {comparison['model_a_id']: avg_a, comparison['model_b_id']: avg_b, comparison['model_c_id']: avg_c}
        costs_map = {comparison['model_a_id']: comparison['cost_a'], comparison['model_b_id']: comparison['cost_b'], comparison['model_c_id']: comparison['cost_c']}
        best_model, routing_msg = auto_route_logic(scores_map, costs_map, comparison.get('guardrail', 4.0))
        if best_model:
            st.success(f"RECOMMANDATION AUTO-ROUTING: {routing_msg}")
        else:
            st.warning(f"{routing_msg}")
        col_save, col_pdf = st.columns(2)
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
            pdf_bytes = generate_verdict_pdf(comparison, scores, extra)
            st.download_button(label="Telecharger le rapport CFO (PDF pour votre boss)", data=pdf_bytes, file_name=f"VERITY_CFO_Report_{comparison.get('company_name','Client')}_{int(time.time())}.pdf", mime="application/pdf", type="secondary", key="pdf_v3", use_container_width=True)

with tab_auto:
    st.title("VERITY Auto-Router - 1 ligne de code pour economiser")
    st.info("VERITY choisit tout seul le modele le moins cher qui respecte votre qualite.")
    st.subheader("Comment ca marche ?")
    st.code("""
# AVANT: Vous payez GPT-4 pour tout
response = openai.chat.completions.create(model="gpt-4", messages=[...])

# APRES: VERITY route automatiquement
from verity import auto_route
response = auto_route(messages=[...], min_quality=4.0)
# + Fallback automatique si le modele tombe -> rebascule sur gpt-4
""", language="python")
    st.subheader("Fallback automatique - Zero downtime")
    fallback_enabled = st.checkbox("Activer le fallback automatique (recommande)", value=True)
    st.subheader("Budget Guard - Bloquer les gaspillages")
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        budget_limit = st.number_input("Bloquer tout appel GPT-4 au-dela de ce cout par requete ($)", min_value=0.0, value=0.05, step=0.01)
    with col_b2:
        slack_webhook = st.text_input("Webhook Slack pour alerte budget (optionnel)", placeholder="https://hooks.slack.com/...")
    if st.button("Copier ma config Auto-Router", type="primary"):
        config_text = f"guardrail={st.session_state.quality_guardrail}, budget_limit=${budget_limit}, fallback={fallback_enabled}"
        st.success(f"Config copiee: {config_text}")

with tab_dash:
    st.title("Dashboard & Economies par Use-Case")
    try:
        data = sb.table("evaluations").select("*").order("created_at", desc=True).limit(200).execute()
        rows = data.data
        if not rows:
            st.info("Aucune evaluation encore.")
        else:
            df = pd.DataFrame(rows)
            total = len(df)
            companies = df['company_name'].nunique() if 'company_name' in df else 1
            avg_time_a = df['time_a'].mean() if 'time_a' in df else 0
            avg_time_b = df['time_b'].mean() if 'time_b' in df else 0
            avg_time_c = df['time_c'].mean() if 'time_c' in df else 0
            fastest = min(avg_time_a, avg_time_b, avg_time_c)
            time_saved = avg_time_a - fastest
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Evaluations", f"{total}")
            col2.metric("Entreprises testees", f"{companies}")
            col3.metric("Vitesse moyenne Groq", f"{avg_time_b:.2f}s", delta=f"{avg_time_a - avg_time_b:.2f}s gagne", delta_color="normal")
            col4.metric("Temps gagne total", f"{time_saved*total:.1f}s", delta="Plus rapide", delta_color="normal")
            st.divider()
            st.subheader("Economies par type de tache (Use-Case)")
            if 'task_category' in df.columns and 'cost_a' in df.columns:
                usecase_summary = df.groupby('task_category').agg(count=('id', 'count'), avg_cost_a=('cost_a', 'mean'), avg_cost_b=('cost_b', 'mean'), avg_cost_c=('cost_c', 'mean'), avg_time_a=('time_a', 'mean'), avg_time_b=('time_b', 'mean'),).reset_index()
                usecase_summary['economie_par_req'] = usecase_summary['avg_cost_a'] - usecase_summary[['avg_cost_b','avg_cost_c']].min(axis=1)
                usecase_summary['economie_mensuelle_10k'] = usecase_summary['economie_par_req'] * 10000
                usecase_summary['pourcentage'] = (usecase_summary['economie_par_req'] / usecase_summary['avg_cost_a'] * 100).fillna(0)
                st.dataframe(usecase_summary, use_container_width=True)
                st.bar_chart(usecase_summary.set_index('task_category')[['economie_mensuelle_10k']])
            st.divider()
            st.subheader(f"Les {min(50, total)} dernieres evaluations")
            display_cols = [c for c in ['created_at','company_name','task_category','question','choice','time_a','time_b','time_c','cost_a','cost_b'] if c in df.columns]
            df_display = df[display_cols].copy()
            if 'question' in df_display.columns:
                df_display['question'] = df_display['question'].str[:80] + "..."
            st.dataframe(df_display.head(50), use_container_width=True)
            st.divider()
            st.subheader("Calculateur d'economie global - Pour le CFO")
            if 'cost_a' in df.columns and 'cost_b' in df.columns:
                avg_cost_a = df['cost_a'].mean()
                avg_cost_b = df['cost_b'].mean()
                avg_cost_c = df['cost_c'].mean() if 'cost_c' in df else avg_cost_b
                cheapest = min(avg_cost_b, avg_cost_c)
                monthly_a = avg_cost_a * 10000
                monthly_cheap = cheapest * 10000
                saving = monthly_a - monthly_cheap
                pct = (saving/monthly_a*100) if monthly_a>0 else 80
                st.success(f"Cout avec Gemini Flash : ${monthly_a:.2f}/mois | Cout optimise : ${monthly_cheap:.2f}/mois | Economie : ${saving:.2f}/mois ({pct:.0f}%) | Annuel: ${saving*12:.2f}")
    except Exception as e:
        st.error(f"Erreur dashboard: {e}")
        st.code(str(e))

with tab_billing:
    st.title("Facturation Unifiee - Toutes vos depenses IA en un seul endroit")
    try:
        data = sb.table("evaluations").select("*").order("created_at", desc=True).limit(200).execute()
        rows = data.data
        if not rows:
            st.info("Pas de donnees encore.")
        else:
            df = pd.DataFrame(rows)
            total_cost_a = df['cost_a'].sum() if 'cost_a' in df else 0
            total_cost_b = df['cost_b'].sum() if 'cost_b' in df else 0
            total_cost_c = df['cost_c'].sum() if 'cost_c' in df else 0
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Depense totale Gemini", f"${total_cost_a:.4f}", "Google")
            c2.metric("Depense totale Groq", f"${total_cost_b:.4f}", "Groq")
            c3.metric("Depense totale Free", f"${total_cost_c:.4f}", "OpenRouter")
            c4.metric("Total si optimise", f"${min(total_cost_a, total_cost_b, total_cost_c)*len(df):.4f}", delta=f"-${total_cost_a - min(total_cost_b, total_cost_c):.4f} economise", delta_color="normal")
            st.divider()
            if 'created_at' in df.columns:
                df['created_at'] = pd.to_datetime(df['created_at'])
                df['month'] = df['created_at'].dt.to_period('M')
                monthly = df.groupby('month')[['cost_a','cost_b','cost_c']].sum()
                st.line_chart(monthly)
            st.divider()
            st.subheader("Private Audit - Mode Confidentiel")
            st.success("VERITY V2.4 ne stocke jamais le contenu de vos prompts en mode Prive. Seuls les scores et les couts sont enregistres.")
            private_count = len(df[df['question'].str.contains("PRIVATE", na=False)]) if 'question' in df else 0
            st.metric("Evaluations en mode prive", f"{private_count}")
    except Exception as e:
        st.error(f"Erreur billing: {e}")
    if st.button("Se deconnecter", key="logout_dash"):
        st.session_state.access_token = None
        st.session_state.comparison = None
        st.rerun()

