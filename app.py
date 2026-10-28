
import os
import time
import requests
import streamlit as st
from supabase import create_client
from google import genai
from openai import OpenAI


st.set_page_config(
    page_title="VERITY V1",
    page_icon="🔎",
    layout="wide",
)


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

st.title("VERITY V1")
st.subheader("Plateforme d'évaluation des intelligences artificielles")
st.write(
    "Comparez deux réponses d'IA, évaluez leur qualité "
    "et consultez les résultats."
)

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Configuration Supabase incomplète. Vérifiez les secrets.")
    st.stop()

if not GEMINI_KEY:
    st.error("La clé Gemini est absente. Vérifiez VERITY_GEMINI_KEY.")
    st.stop()

try:
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    gemini = genai.Client(api_key=GEMINI_KEY)
except Exception as e:
    st.error(f"Initialisation impossible : {e}")
    st.stop()

groq = None
if GROQ_KEY:
    groq = OpenAI(
        api_key=GROQ_KEY,
        base_url="https://api.groq.com/openai/v1",
    )


# SESSION
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
        "Content-Type": "application/json",
    }


def get_user_id():
    response = requests.get(
        SUPABASE_URL + "/auth/v1/user",
        headers=auth_headers(),
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["id"]


# INSCRIPTION ET CONNEXION
if not st.session_state.access_token:
    mode = st.radio(
        "Compte",
        ["Se connecter", "Créer un compte"],
        horizontal=True,
    )
    email = st.text_input("Adresse e-mail")
    password = st.text_input("Mot de passe", type="password")

    if mode == "Créer un compte":
        if st.button("Créer mon compte", type="primary"):
            try:
                result = sb.auth.sign_up({
                    "email": email.strip(),
                    "password": password,
                })
                session = getattr(result, "session", None)

                if session and session.access_token:
                    st.session_state.access_token = session.access_token
                    st.session_state.user_email = email.strip()
                    st.rerun()
                else:
                    st.info(
                        "Compte créé. Si une confirmation par e-mail "
                        "est demandée, confirmez votre adresse avant "
                        "de vous connecter."
                    )
            except Exception as e:
                st.error(f"Inscription impossible : {e}")
    else:
        if st.button("Se connecter", type="primary"):
            try:
                result = sb.auth.sign_in_with_password({
                    "email": email.strip(),
                    "password": password,
                })
                st.session_state.access_token = result.session.access_token
                st.session_state.user_email = email.strip()
                st.rerun()
            except Exception as e:
                st.error(f"Connexion impossible : {e}")

    st.stop()


# VERIFICATION DE SESSION
try:
    user_id = get_user_id()
except Exception:
    st.session_state.access_token = None
    st.session_state.user_email = ""
    st.session_state.comparison = None
    st.warning("Session expirée. Connectez-vous à nouveau.")
    st.stop()

st.caption(f"Connecté : {st.session_state.user_email}")

if st.button("Se déconnecter"):
    st.session_state.access_token = None
    st.session_state.user_email = ""
    st.session_state.comparison = None
    st.rerun()


# COMPARAISON DES IA
st.divider()
st.header("Comparer deux réponses")

question = st.text_area(
    "Votre question",
    placeholder="Écrivez votre question ici…",
)

if st.button("Générer les deux réponses", type="primary"):
    if not question.strip():
        st.warning("Écrivez une question avant de continuer.")
    elif groq is None:
        st.error("Groq n'est pas configuré. Vérifiez VERITY_GROQ_KEY.")
    else:
        try:
            with st.spinner("Génération des réponses…"):
                prompt = (
                    "Réponds précisément et utilement à cette question. "
                    "Signale les incertitudes et réponds en français si "
                    "la question est en français.\n\n"
                    + question.strip()
                )

                # Réponse A : Gemini
                start_a = time.perf_counter()
                response_a = gemini.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                )
                time_a = round(time.perf_counter() - start_a, 2)

                # Réponse B : Groq
                start_b = time.perf_counter()
                response_b = groq.chat.completions.create(
                    model="openai/gpt-oss-120b",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Tu es un assistant utile, précis et honnête. "
                                "Réponds en français si la question est en "
                                "français. Signale clairement les incertitudes."
                            ),
                        },
                        {
                            "role": "user",
                            "content": question.strip(),
                        },
                    ],
                    temperature=0.7,
                    max_tokens=1200,
                )
                time_b = round(time.perf_counter() - start_b, 2)

                st.session_state.comparison = {
                    "question": question.strip(),
                    "response_a": (
                        response_a.text or "Aucune réponse générée."
                    ),
                    "response_b": (
                        response_b.choices[0].message.content
                        or "Aucune réponse générée."
                    ),
                    "time_a": time_a,
                    "time_b": time_b,
                }
        except Exception as e:
            st.error(f"Erreur lors de la génération : {e}")


# AFFICHAGE ET EVALUATION
comparison = st.session_state.comparison

if comparison:
    left, right = st.columns(2)

    with left:
        st.subheader("Réponse A — Gemini")
        st.caption(f"Temps de génération : {comparison['time_a']} secondes")
        st.write(comparison["response_a"])

    with right:
        st.subheader("Réponse B — Groq")
        st.caption(f"Temps de génération : {comparison['time_b']} secondes")
        st.write(comparison["response_b"])

    st.divider()
    st.subheader("1. Votre vote")

    choice = st.radio(
        "Quelle réponse préférez-vous ?",
        ["Réponse A", "Réponse B", "Égalité"],
        horizontal=True,
        key="vote_choice",
    )

    st.subheader("2. Évaluez la qualité des réponses")
    st.caption("Pour chaque critère, choisissez une note de 1 à 5.")

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("### Réponse A — Gemini")
        relevance_a = st.select_slider(
            "Pertinence — A",
            options=[1, 2, 3, 4, 5],
            value=3,
            key="relevance_a",
            help="La réponse répond-elle vraiment à la question ?",
        )
        accuracy_a = st.select_slider(
            "Exactitude — A",
            options=[1, 2, 3, 4, 5],
            value=3,
            key="accuracy_a",
            help="Les informations semblent-elles correctes ?",
        )
        clarity_a = st.select_slider(
            "Clarté — A",
            options=[1, 2, 3, 4, 5],
            value=3,
            key="clarity_a",
            help="La réponse est-elle claire et compréhensible ?",
        )

    with col_b:
        st.markdown("### Réponse B — Groq")
        relevance_b = st.select_slider(
            "Pertinence — B",
            options=[1, 2, 3, 4, 5],
            value=3,
            key="relevance_b",
            help="La réponse répond-elle vraiment à la question ?",
        )
        accuracy_b = st.select_slider(
            "Exactitude — B",
            options=[1, 2, 3, 4, 5],
            value=3,
            key="accuracy_b",
            help="Les informations semblent-elles correctes ?",
        )
        clarity_b = st.select_slider(
            "Clarté — B",
            options=[1, 2, 3, 4, 5],
            value=3,
            key="clarity_b",
            help="La réponse est-elle claire et compréhensible ?",
        )

    if st.button("Enregistrer mon vote et mes notes", type="primary"):
        try:
            payload = {
                "question": comparison["question"],
                "response_a": comparison["response_a"],
                "response_b": comparison["response_b"],
                "choice": choice,
                "time_a": comparison["time_a"],
                "time_b": comparison["time_b"],
                "relevance_a": relevance_a,
                "accuracy_a": accuracy_a,
                "clarity_a": clarity_a,
                "relevance_b": relevance_b,
                "accuracy_b": accuracy_b,
                "clarity_b": clarity_b,
            }

            result = requests.post(
                SUPABASE_URL + "/functions/v1/save-evaluation",
                headers=auth_headers(),
                json=payload,
                timeout=30,
            )

            if result.ok:
                st.success(
                    "Vote, temps de génération et six notes enregistrés !"
                )
                st.json(result.json().get("evaluation", {}))
            else:
                st.error(
                    f"Enregistrement impossible ({result.status_code}) : "
                    f"{result.text}"
                )
        except Exception as e:
            st.error(f"Erreur d'enregistrement : {e}")


# TABLEAU DE BORD
st.divider()
st.header("Tableau de bord des évaluations")

try:
    stats_result = requests.get(
        SUPABASE_URL + "/rest/v1/evaluations",
        headers={**auth_headers(), "Accept": "application/json"},
        params={
            "select": "choice",
            "user_id": f"eq.{user_id}",
            "order": "created_at.desc",
            "limit": "1000",
        },
        timeout=20,
    )

    if stats_result.ok:
        stats_rows = stats_result.json()
        total_votes = len(stats_rows)
        votes_a = sum(
            1 for row in stats_rows if row.get("choice") == "Réponse A"
        )
        votes_b = sum(
            1 for row in stats_rows if row.get("choice") == "Réponse B"
        )
        egalites = sum(
            1 for row in stats_rows if row.get("choice") == "Égalité"
        )

        taux_a = round(votes_a / total_votes * 100, 1) if total_votes else 0
        taux_b = round(votes_b / total_votes * 100, 1) if total_votes else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Évaluations", total_votes)
        c2.metric("Votes A", votes_a, f"{taux_a}%")
        c3.metric("Votes B", votes_b, f"{taux_b}%")
        c4.metric("Égalités", egalites)
    else:
        st.error(f"Statistiques indisponibles : {stats_result.status_code}")
except Exception as e:
    st.error(f"Erreur du tableau de bord : {e}")


# HISTORIQUE
st.divider()
st.header("Mon historique")

if st.button("Afficher mes évaluations"):
    try:
        result = requests.get(
            SUPABASE_URL + "/rest/v1/evaluations",
            headers={**auth_headers(), "Accept": "application/json"},
            params={
                "select": (
                    "id,question,response_a,response_b,choice,created_at,"
                    "time_a,time_b,relevance_a,accuracy_a,clarity_a,"
                    "relevance_b,accuracy_b,clarity_b"
                ),
                "user_id": f"eq.{user_id}",
                "order": "created_at.desc",
                "limit": "50",
            },
            timeout=20,
        )

        if result.ok:
            rows = result.json()
            if rows:
                st.dataframe(rows, use_container_width=True)
            else:
                st.info("Aucune évaluation enregistrée pour le moment.")
        else:
            st.error(
                f"Historique indisponible ({result.status_code}) : "
                f"{result.text}"
            )
    except Exception as e:
        st.error(f"Erreur d'historique : {e}")
