import streamlit as st
from datetime import date
import sys
from pathlib import Path
SRC = Path(__file__).resolve().parents[1]  # ...\src
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from library_api_connector import get_unique_tags_categories,search_games_connector
from Library_fonctions import load_state_from_query,save_key_to_query,ensure_key_in_query

load_state_from_query()
ensure_key_in_query("User")
ensure_key_in_query("game_name_magasin")

st.set_page_config(page_title="Recherche", page_icon="🔍")
# CSS pour cacher le menu latéral
hide_sidebar_style = """
    <style>
        [data-testid="stSidebarNav"] {display: none;}
        [data-testid="stSidebar"] {display: none;}
    </style>
"""
st.markdown(hide_sidebar_style, unsafe_allow_html=True)
st.markdown("<h1 style='text-align:center;'>Page de recherche</h1>", unsafe_allow_html=True)

if st.button("🏠 Accueil"):
    st.switch_page("app.py")

data = get_unique_tags_categories()
tags_list = data["tags"]
categories_list = data["categories"]

col1,col2 = st.columns([0.8,0.2])
with col2:
    col2_containeur = st.container(border=True)
    with col2_containeur:
                # --- Basic search control ---
        n = st.number_input("Number of games to fetch", min_value=1, max_value=500, value=50, step=1)

        # --- Price ---
        max_price_val = st.number_input("Max price", min_value=0.0, value=9999.0, step=1.0)
        max_price = max_price_val if max_price_val > 0 else None

        # --- Reviews ---
        st.subheader("Reviews")
        neg_min, neg_max = st.slider(
            "Negative reviews range",
            min_value=0, max_value=100000, value=(0, 100000), step=100
        )
        pos_min, pos_max = st.slider(
            "Positive reviews range",
            min_value=0, max_value=1000000, value=(0, 1000000), step=1000
        )

        min_negative = neg_min or None
        max_negative = neg_max if neg_max > 0 else None
        min_positive = pos_min or None
        max_positive = pos_max if pos_max > 0 else None

        # --- Release date range ---
        st.subheader("Release date")
        col2_1, col2_2 = st.columns(2)
        with col2_1:
            date_from = st.date_input("From", value=None)
        with col2_2:
            date_to = st.date_input("To", value=None)

        def to_iso_start(d: date | None):
            return d.strftime("%Y-%m-%dT00:00:00") if d else None

        def to_iso_end(d: date | None):
            return d.strftime("%Y-%m-%dT23:59:59") if d else None

        release_date_from = to_iso_start(date_from)
        release_date_to = to_iso_end(date_to)

        # --- Age ---
        st.subheader("Required age")
        col2_1, col2_2 = st.columns(2)
        with col2_1:
            min_required_age_val = st.number_input("Min age", min_value=0, max_value=21, value=0)
        with col2_2:
            max_required_age_val = st.number_input("Max age", min_value=0, max_value=21, value=21)

        min_required_age = min_required_age_val or None
        max_required_age = max_required_age_val if max_required_age_val != 21 else None

        # --- Categories, genres, tags ---
        st.subheader("Categories")
        categories = st.multiselect("Categories", categories_list)

        st.subheader("Tags")
        required_tags = st.multiselect("Required tags", tags_list)

with col1:
    col1_containeur = st.container(border=True)
    with col1_containeur:
        game_name = st.text_input("Recherche",placeholder="Recherche",label_visibility="hidden")
        if game_name:
            games = search_games_connector(n=n,
                                   max_price=max_price,
                                   name_contains=game_name,
                                   categories=categories,
                                   min_negative=min_negative,
                                   max_negative=max_negative,
                                   min_positive=min_positive,
                                   max_positive=max_positive,
                                   release_date_from=release_date_from,
                                   release_date_to=release_date_to,
                                   min_required_age=min_required_age,
                                   max_required_age=max_required_age,
                                   required_tags=required_tags)[1]["games"]
            for game in games:
                with st.container(border=True):
                    col1,col2,col3 = st.columns([0.2,0.7,0.1])
                    with col1:
                        st.image(game["assets"]["main_capsule"])
                    with col2:
                        st.write(f"### {game["name"]}")
                        genre_text = "genre: "
                        for genre in game["genres"]:
                            genre_text = genre_text + f"{genre}, "
                        st.write(genre_text)
                        st.write(game["short_description"])
                    with col3:
                        st.write(f"### {game["price"]}€")
                        if st.button("view Page",key=game["_id"]):
                            st.session_state["game_name_magasin"] = game["_id"]
                            st.switch_page("pages/magasin.py")
