import streamlit as st

st.set_page_config(page_title="Questionnaire", page_icon="❓", layout="wide")
# CSS pour cacher le menu latéral
hide_sidebar_style = """
    <style>
        [data-testid="stSidebarNav"] {display: none;}
        [data-testid="stSidebar"] {display: none;}
    </style>
"""
st.markdown(hide_sidebar_style, unsafe_allow_html=True)
st.markdown("<h1 style='text-align:center;'>Page du Questionnaire</h1>", unsafe_allow_html=True)

col1, col2 = st.columns(2)

with col1:
    if st.button("🏠 Accueil"):
        st.switch_page("app.py")

with col2:
    if st.button("📦 Envoyer"):
        st.switch_page("pages/magasin.py")
