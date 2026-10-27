import os
import requests
import streamlit as st
from supabase import create_client
from google import genai
from openai import OpenAI
st.set_page_config(
    page_title="VERITY V1",
    page_icon="🔎",
    layout="wide"
)

st.title("VERITY V1")
st.subheader("Plateforme d'évaluation des intelligences artificielles")
st.write("Posez une question, comparez deux réponses et votez pour la meilleure.")

# Secrets configurés dans l'environnement de l'hébergeur
SUPABASE_URL = os.getenv("VERITY_SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.getenv("VERITY_SUPABASE_KEY", "").strip()
GEMINI_KEY = os.getenv("VERITY_GEMINI_KEY", "").strip()
GROQ_KEY = os.getenv("VERITY_GROQ_KEY", "").strip()
if not SUPABASE_URL or not SUPABASE_KEY or not GEMINI_KEY:
    st.error(
        "Configuration incomplète. Les clés Supabase et Gemini "
        "doivent être ajoutées aux secrets de l'application."
    )
    st.stop()

sb = create_client(SUPABASE_URL, SUPABASE_KEY)
gemini = genai.Client(api_key=GEMINI_KEY)

groq = None
if GROQ_KEY:
    groq = OpenAI(
        api_key=GROQ_KEY,
        base_url="https://api.groq.com/openai/v1"
    )

if "access_token" not in st.session_state:
    st.session_state.access_token = None
if "user_email" not in st.session_state:
    st.session_state.user_email = ""
if "comparison" not in st.session_state:
    st.session_state.comparison = None

def auth_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {st.session_state.access_token}",
        "Content-Type": "application/json"
    }

def get_user_id():
    response = requests.get(
        SUPABASE_URL + "/auth/v1/user",
        headers=auth_headers(),
        timeout=20
    )
    response.raise_for_status()
    return response.json()["id"]

if not st.session_state.access_token:
    mode = st.radio("Compte", ["Se connecter", "Créer un compte"], horizontal=True)
    email = st.text_input("Adresse e-mail")
    password = st.text_input("Mot de passe", type="password")

    if mode == "Créer un compte":
        if st.button("Créer mon compte", type="primary"):
            try:
                result = sb.auth.sign_up({
                    "email": email.strip(),
                    "password": password
                })
                session = getattr(result, "session", None)
                if session and session.access_token:
                    st.session_state.access_token = session.access_token
                    st.session_state.user_email = email.strip()
                    st.rerun()
                else:
                    st.info(
                        "Compte créé. Si la confirmation par e-mail est activée, "
                        "confirmez votre adresse avant de vous connecter."
                    )
            except Exception as e:
                st.error(f"Inscription impossible : {e}")
    else:
        if st.button("Se connecter", type="primary"):
            try:
                result = sb.auth.sign_in_with_password({
                    "email": email.strip(),
                    "password": password
                })
                st.session_state.access_token = result.session.access_token
                st.session_state.user_email = email.strip()
                st.rerun()
            except Exception as e:
                st.error(f"Connexion impossible : {e}")
    st.stop()

try:
    user_id = get_user_id()
except Exception:
    st.session_state.access_token = None
    st.warning("Session expirée. Connectez-vous à nouveau.")
    st.stop()

st.caption(f"Connecté : {st.session_state.user_email}")
if st.button("Se déconnecter"):
    st.session_state.access_token = None
    st.session_state.user_email = ""
    st.session_state.comparison = None
    st.rerun()

st.divider()
st.header("Comparer deux réponses")
question = st.text_area("Votre question", placeholder="Écrivez votre question ici…")

if st.button("Générer les deux réponses", type="primary"):
    if not question.strip():
        st.warning("Écrivez une question avant de continuer.")
    else:
        try:
            with st.spinner("Génération des réponses…"):
                
                if groq is None:
                    st.error(
                        "Groq n'est pas configuré. "
                        "Ajoutez VERITY_GROQ_KEY dans les secrets "
                        "de l'application."
                    )
                    st.stop()

                prompt = (
                    "Réponds précisément et utilement à cette question. "
                    "Signale les incertitudes et réponds en français "
                    "si la question est en français.\n\n"
                    + question.strip()
                )

                response_a = gemini.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt
                )

                response_b = groq.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Tu es un assistant utile, précis et honnête. "
                                "Réponds en français si la question est en français. "
                                "Signale clairement les incertitudes."
                            )
                        },
                        {
                            "role": "user",
                            "content": question.strip()
                        }
                    ],
                    temperature=0.7,
                    max_tokens=1200
                )

                st.session_state.comparison = {
                    "question": question.strip(),
                    "response_a": (
                        response_a.text or "Aucune réponse générée."
                    ),
                    "response_b": (
                        response_b.choices[0].message.content
                        or "Aucune réponse générée."
                    ),
                    "provider_a": "Google Gemini",
                    "provider_b": "Groq — Llama 3.3 70B"
                }

        except Exception as e:
            st.error(f"Erreur lors de la génération : {e}")

comparison = st.session_state.comparison
if comparison:
    left, right = st.columns(2)
    with left:
        st.subheader("Réponse A")
        st.write(comparison["response_a"])
    with right:
        st.subheader("Réponse B")
        st.write(comparison["response_b"])

    st.subheader("Quelle réponse préférez-vous ?")
    choice = st.radio(
        "Votre vote",
        ["Réponse A", "Réponse B", "Égalité"],
        horizontal=True
    )

    if st.button("Enregistrer mon vote"):
        try:
            result = requests.post(
                SUPABASE_URL + "/functions/v1/save-evaluation",
                headers=auth_headers(),
                json={
                    "question": comparison["question"],
                    "response_a": comparison["response_a"],
                    "response_b": comparison["response_b"],
                    "choice": choice
                },
                timeout=30
            )
            if result.ok:
                st.success("Vote enregistré avec succès !")
            else:
                st.error(f"Enregistrement impossible ({result.status_code}) : {result.text}")
        except Exception as e:
            st.error(f"Erreur d'enregistrement : {e}")

st.divider()
st.header("Mon historique")
if st.button("Afficher mes évaluations"):
    try:
        result = requests.get(
            SUPABASE_URL + "/rest/v1/evaluations",
            headers={
                **auth_headers(),
                "Accept": "application/json"
            },
            params={
                "select": "id,question,choice,created_at",
                "user_id": f"eq.{user_id}",
                "order": "created_at.desc",
                "limit": "50"
            },
            timeout=20
        )
        if result.ok:
            rows = result.json()
            if rows:
                st.dataframe(rows, use_container_width=True)
            else:
                st.info("Aucune évaluation enregistrée pour le moment.")
        else:
            st.error(f"Historique indisponible ({result.status_code}) : {result.text}")
    except Exception as e:
        st.error(f"Erreur d'historique : {e}")
