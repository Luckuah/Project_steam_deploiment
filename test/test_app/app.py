import streamlit as st

st.set_page_config(page_title="Session State Test", layout="centered")

st.title("Main page – Session State Test")

st.write("### Step 1 – Define your User")

# Simple mock User object: a dict
if "User" not in st.session_state:
    st.session_state.User = {"name": None, "favorite_game": None}

with st.form("user_form"):
    name = st.text_input("Name", value=st.session_state.User.get("name") or "")
    favorite_game = st.text_input("Favorite game", value=st.session_state.User.get("favorite_game") or "")
    submitted = st.form_submit_button("Save user")

if submitted:
    st.session_state.User = {
        "name": name or None,
        "favorite_game": favorite_game or None,
    }
    st.success("User saved into st.session_state.User")

st.write("### Current st.session_state.User")
st.json(st.session_state.User)

st.write("### Navigate to other pages")

col1, col2 = st.columns(2)
with col1:
    st.page_link("pages/question.py", label="➡️ Go to Question page")
with col2:
    st.page_link("pages/chatbot.py", label="💬 Go to Chatbot page")

st.write(
    """
    On the other pages, we will just read `st.session_state.User`
    and display it. If it shows up there, session_state is shared across pages.
    """
)
