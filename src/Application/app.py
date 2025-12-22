#### = sessionstate used... might need to reset it later
import streamlit as st
from st_clickable_images import clickable_images
from pathlib import Path
from streamlit_option_menu import option_menu
import sys
from st_click_detector import click_detector
SRC = Path(__file__).resolve().parents[1]  # ...\src
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from library_api_connector import get_default_game_reco,get_user_recommendation
from Library_fonctions import load_state_from_web_storage, save_state_to_web_storage
from Library_fonctions import load_state_from_query,save_key_to_query,ensure_key_in_query
from library_api_connector import gensar_recommendation_connector,recomandation_genral_connector
import traceback
load_state_from_query()
ensure_key_in_query("User")
ensure_key_in_query("game_name_magasin")

## --- Local Storage for session persistence ---
STORAGE_KEY = "App_Page"
PERSIST_KEYS = ["game_reco"]

load_state_from_web_storage(STORAGE_KEY,PERSIST_KEYS,max_age_seconds=180)

st.set_page_config(page_title="Accueil", page_icon="🏠", layout="wide")
# Masquer la sidebar automatique
hide_sidebar_style = """
    <style>
        [data-testid="stSidebarNav"] {display: none;}
        [data-testid="stSidebar"] {display: none;}
    </style>
"""
st.markdown(hide_sidebar_style, unsafe_allow_html=True)
logo_src = ""
st.markdown(
    """
    <style>
        /* This targets the main container of the page */
        .block-container {
            padding-top: 1rem !important; /* Adjust this value to move it up/down */
            padding-bottom: 0rem !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    f"""
    <div style="
        display: flex;
        align-items: center;
        background-color: transparent;
        padding: 1rem;
        border-radius: 10px;
        margin-bottom: 2rem;
    ">
        <img src="{logo_src}" style="
            height: 50px;
            margin-right: 15px;
        " />
        <div style="
            font-size: 2rem;
            font-weight: 600;
            color: #ffffff;         /* Dark text color */
        ">
            Steam Recommender
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


selected = option_menu(
    menu_title=None,
    options=[
        "Accueil",
        "Login",
        "Recherche",
        "Bibliothèque",
    ],
    icons=[
        "house",           
        "box-arrow-in-right",
        "search",
        "book",
    ],
    orientation="horizontal",
    default_index=0,
    styles={
        "container": {
            "width": "45%",
            "padding": "0px",
            # "background-color": "transparent",
        },
        "icon": {
            "font-size": "14px",
        },
        "nav-link": {
            "font-size": "12px",
            "padding": "4px 8px",
            "margin": "0px 2px",
        },
        "nav-link-selected": {
            "font-size": "12px",
            "padding": "4px 8px",
        },
    },
)

if selected == "Accueil":
    pass
elif selected == "Login":
    st.switch_page("pages/login.py")
elif selected == "Recherche":
    st.switch_page("pages/recherche.py")
elif selected == "Bibliothèque":
    st.switch_page("pages/bibliotheque.py")

# ---- Récupération des recommandations de jeux ----
try:

    if "User" in st.session_state:
        st.session_state.game_reco = get_user_recommendation(st.session_state["User"],topk=1000)[1]
    else:
        st.session_state.game_reco = get_default_game_reco()
    st.session_state.default_reco = get_default_game_reco()
    message =  st.session_state.game_reco
except Exception as e:
    st.error(f"Erreur lors du chargement des jeux : {e}")
    st.error(traceback.format_exc())
    message = []

st.markdown("<br><hr><h2 style='text-align:center;'> À la une</h2><br>", unsafe_allow_html=True)
with st.container(border=True):
    try:
        carousel_items = st.session_state.default_reco[:5]
    except:
        carousel_items = []

    if len(carousel_items) >= 3:

        # Index actuel dans la session
        if "carousel_index" not in st.session_state:
            st.session_state.carousel_index = 2  # centre

        center = st.session_state.carousel_index
        left = (center - 1) % len(carousel_items)
        right = (center + 1) % len(carousel_items)

        # IMAGES DU CARROUSEL
        imgs = [
            carousel_items[left].get("assets", {}).get("main_capsule", ""),
            carousel_items[center].get("assets", {}).get("main_capsule", ""),
            carousel_items[right].get("assets", {}).get("main_capsule", "")
        ]

        # Cliques possibles : 0 = gauche, 1 = centre, 2 = droite
        clicked = clickable_images(
            imgs,
            titles=["left", "center", "right"],
            div_style={"display": "flex", "justify-content": "center", "gap": "25px"},
            img_style={"border-radius": "14px", "height": "260px"}
        )

        # LOGIQUE DES CLICS
        if clicked == 0:   # image gauche → carrousel vers la gauche
            st.session_state.carousel_index = left

        elif clicked == 2: # image droite → carrousel vers la droite
            st.session_state.carousel_index = right

        elif clicked == 1:  # image centrale → ouvrir magasin
            game_id = carousel_items[center].get("_id", "")
            st.session_state["game_name_magasin"] = game_id
            save_key_to_query("game_name_magasin")
            st.switch_page("pages/magasin.py")

    else:
        st.info("Pas assez de jeux pour afficher le carrousel.")



# ---- Gallery with overlapping targets (image open + heart favorite) ----
if message:
    st.subheader(" Jeux recommandés")

    # Récupère les 8 premiers éléments
    items = [game if "main_capsule" in game.get("assets", {}) else None for game in message]
    items = [x for x in items if x is not None]
    imgs = [game.get("assets", {}).get("main_capsule", "") for game in items]
    
    imgs = imgs[:12] if len(imgs) >= 12 else imgs


    idx = clickable_images(
        imgs,
        titles=[f"Image {i}" for i in range(len(imgs))],
        div_style={
            "display": "flex",
            "justify-content": "center",
            "flex-wrap": "wrap",
            "gap": "12px"
        },
        img_style={"border-radius": "12px", "height": "160px"},
    )

    # 👉 Si une image est cliquée → on va DIRECTEMENT au magasin
    if idx > -1:
        selected_game = items[idx]
        game_id = selected_game.get("_id", None)

        # set cookie / query
        st.session_state["game_name_magasin"] = game_id
        save_key_to_query("game_name_magasin")

        # redirection instantanée
        st.switch_page("pages/magasin.py")

    items = items[12:]

    if "nbGame" not in st.session_state:
        st.session_state.nbGame = 10
    col = st.columns([1,1,1])
    with col[1]:
        with st.container(border=True):
            
            html_content = ""
            
            for game in items[:st.session_state.nbGame]:
                
                # 1. THE ANCHOR WRAPPER (<a href='#' ...>)
                # We add 'display: block' so the link behaves like a box, not text.
                # We add 'text-decoration: none' to remove the underline.
                # We add 'color: inherit' so the text doesn't turn blue.
                
                html_content += f"""
                <a href='#' id='{game["_id"]}' style='text-decoration: none; color: inherit; display: block; margin-bottom: 10px;'>
                    
                    <div style="
                        display: flex; 
                        align-items: center; 
                        background-color: #262730; 
                        border: 1px solid #464b5f; 
                        border-radius: 10px; 
                        padding: 10px; 
                        transition: all 0.2s ease-in-out;
                        "
                        onmouseover="this.style.backgroundColor='#3b3d4a'; this.style.borderColor='#ff4b4b'; this.style.transform='scale(1.01)';"
                        onmouseout="this.style.backgroundColor='#262730'; this.style.borderColor='#464b5f'; this.style.transform='scale(1.0)';"
                        >
                        
                        <div style="flex: 0 0 170px; margin-right: 15px;">
                            <img src="{game['assets']['main_capsule']}" style="width: 100%; border-radius: 5px;">
                        </div>
                        
                        <div style="flex: 1; color: white;">
                            <div style="font-size: 1.2rem; font-weight: 600;">{game['name']}</div>
                            <div style="font-size: 0.85rem; color: #b0b0b0;">
                                genre: {', '.join(game['genres'])}
                            </div>
                        </div>
                        
                        <div style="flex: 0 0 auto; font-size: 1.2rem; font-weight: bold; color: #eee; padding-left: 10px;">
                            {game['price']}€
                        </div>
                    </div>
                </a>
                """
            # 2. DETECTOR
            clicked_id = click_detector(html_content, key="game_list_detector")
            if button := st.button("Voir plus de jeux"):
                if st.session_state.nbGame + 10 <= len(items) or st.session_state.nbGame +10 <=50:
                    st.session_state.nbGame += 10
                else:
                    st.warning("Pas plus de jeux disponibles pour le moment.")
                st.rerun()
            # 3. LOGIC
            if clicked_id:
                st.session_state["game_name_magasin"] = clicked_id
                st.switch_page("pages/magasin.py")


else:
    st.warning("Aucun jeu trouvé pour le moment.")

