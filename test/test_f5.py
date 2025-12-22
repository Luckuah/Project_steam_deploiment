import json
import uuid
import streamlit as st

st.set_page_config(page_title="Query Params + Session State Demo")

# ------------------ 1. Restore from query params (first run only) ------------------ #
def restore_from_query_params():
    qp = st.query_params
    raw = qp.get("state")

    if not raw:
        return

    # st.query_params can return str or list[str]
    if isinstance(raw, list):
        raw = raw[0]

    try:
        data = json.loads(raw)
        for k, v in data.items():
            # only set if not already set
            st.session_state.setdefault(k, v)
    except Exception as e:
        st.warning(f"Could not parse state from URL: {e}")

if "initialized_from_qp" not in st.session_state:
    restore_from_query_params()

    # If nothing was in the URL, create some default state
    st.session_state.setdefault("user_token", str(uuid.uuid4()))
    st.session_state.setdefault("counter", 0)

    st.session_state.initialized_from_qp = True

# ------------------ 2. Normal app UI using session_state ------------------ #
st.title("Query Params + Session State Demo")

st.markdown(
    """
    **How to test:**
    1. Click the buttons below to change the values.
    2. Look at the URL: it should contain a `?state=...` part.
    3. Press **F5** (hard reload): values should stay the same.
    4. Copy the URL, open it in another tab: it should load with the same values.
    """
)

st.subheader("Current state")

st.write("`user_token`:", st.session_state.user_token)
st.write("`counter`:", st.session_state.counter)

col1, col2 = st.columns(2)
with col1:
    if st.button("Increment counter"):
        st.session_state.counter += 1

with col2:
    if st.button("Generate new user_token"):
        st.session_state.user_token = str(uuid.uuid4())

if st.button("Reset EVERYTHING (clear query params & state)"):
    # Clear session_state (except the flag to avoid recursion)
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    # Clear query params completely
    st.query_params.clear()
    st.rerun()

# ------------------ 3. Sync (a subset of) session_state back to query params ------------------ #
def sync_state_to_query_params():
    export = {
        "user_token": st.session_state.user_token,
        "counter": st.session_state.counter,
    }

    new_state_str = json.dumps(export)
    current_qp_state = st.query_params.get("state")
    if isinstance(current_qp_state, list):
        current_qp_state = current_qp_state[0]

    # Only touch query params if the JSON actually changed -> avoids useless reruns
    if current_qp_state != new_state_str:
        st.query_params.from_dict({"state": new_state_str})

sync_state_to_query_params()

# ------------------ 4. Debug info ------------------ #
st.subheader("Debug")
st.write("Raw `st.session_state`:", dict(st.session_state))
st.write("Raw `st.query_params`:", dict(st.query_params))
