import streamlit as st

st.set_page_config(page_title="Chatbot Page", layout="centered")

st.title("Chatbot page")

st.write("### st.session_state.User on this page:")

if "User" in st.session_state:
    st.json(st.session_state.User)
else:
    st.warning("No `User` found in st.session_state.")

st.write("### Back to main or other page")
st.page_link("app.py", label="⬅️ Back to Main page")
st.page_link("pages/question.py", label="❓ Go to Question page")
