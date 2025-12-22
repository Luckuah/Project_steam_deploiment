import streamlit as st
from Library_fonctions import load_state_from_query,save_key_to_query,ensure_key_in_query
from library_api_connector import get_user_by_name, add_user
import time

load_state_from_query()
ensure_key_in_query("User")

st.set_page_config(page_title="Login", page_icon="🔐",layout="centered")

# --- Cacher la sidebar ---
hide_sidebar_style = """
    <style>
        [data-testid="stSidebarNav"] {display: none;}
        [data-testid="stSidebar"] {display: none;}
    </style>
"""
st.markdown(hide_sidebar_style, unsafe_allow_html=True)

# --- Titre principal ---
st.markdown("<h1 style='text-align:center;'>🔐 Connexion</h1>", unsafe_allow_html=True)

# --- Bouton retour Accueil ---
if st.button("🏠 Accueil"):
    st.switch_page("app.py")

st.markdown("<br>", unsafe_allow_html=True)

# --- Section Connexion ---
st.subheader("Se connecter")

username = st.text_input("Nom d'utilisateur", key="login_username")
if st.button("✅ Se connecter"):
    # TODO : Vérifier si l'utilisateur existe dans la base
    # TODO : Si oui, sauvegarder la session utilisateur (cookie ou session_state)
    # TODO : Rediriger vers la page d'accueil ou la bibliothèque
    if not username.strip():
        st.warning("⚠️ Merci d’entrer un nom d’utilisateur.")
    else:
        try:
            # --- Vérifie si l'utilisateur existe ---
            user_data = get_user_by_name(username)
            if user_data[0] != False :
                # --- Crée un cookie avec le nom de l'utilisateur ---
                st.session_state["User"] = username
                save_key_to_query("User")
                st.switch_page("./app.py")
            else:
                st.error("❌ Utilisateur introuvable. Vérifie le nom ou crée un compte.")
        
        except Exception as e:
            st.error(f"Erreur lors de la connexion : {e}")
            print(f"Erreur lors de la connexion : {e}")
    

st.markdown("<hr>", unsafe_allow_html=True)

# --- Section Création de compte ---
st.subheader("Créer un compte")

# Bouton pour afficher/masquer la création de compte
if "show_create" not in st.session_state:
    st.session_state.show_create = False

if st.button("🆕 Créer un compte"):
    st.session_state.show_create = not st.session_state.show_create

if st.session_state.show_create:
    new_username = st.text_input("Choisissez un nom d'utilisateur", key="create_username")
    
    if st.button("📘 Créer"):
        # TODO : Vérifier si le nom d'utilisateur est déjà pris
        # TODO : Si non, enregistrer le nouvel utilisateur
        # TODO : Afficher message de succès + rediriger éventuellement
        if not new_username.strip():
            st.warning("⚠️ Merci d’entrer un nom d’utilisateur.")
        else:
            try:
                # --- Vérifie si le nom existe déjà ---
                existing_user = get_user_by_name(new_username)

                if existing_user[0] == True:
                    st.error("❌ Ce nom d'utilisateur existe déjà. Choisis-en un autre.")
                else:
                    # --- Crée l'utilisateur ---
                    success, message = add_user(new_username)

                    if success:
                        st.session_state["User"] = username
                        save_key_to_query("User")

                        st.success(f"✅ Compte '{new_username}' créé avec succès !")
                        st.info("Redirection vers la bibliothèque...")

                        # --- Redirection automatique ---
                        st.switch_page("./app.py")
                    else:
                        st.error(f"❌ Échec de la création du compte : {message}")

            except Exception as e:
                st.error(f"Erreur lors de la création du compte : {e}")
