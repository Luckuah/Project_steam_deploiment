import streamlit as st

st.set_page_config(page_title="Question Page", layout="centered")

st.title("Question page")

st.write("### st.session_state.User on this page:")

if "User" in st.session_state:
    st.json(st.session_state.User)
else:
    st.warning("No `User` found in st.session_state.")

st.write("### Back to main or other page")
st.page_link("app.py", label="⬅️ Back to Main page")
st.page_link("pages/chatbot.py", label="💬 Go to Chatbot page")
