"""Streamlit chat UI for the personal health assistant.

Run with: streamlit run app.py
"""

import os
import sys
from datetime import date
from pathlib import Path

import streamlit as st

# Bridge Streamlit secrets (used on Streamlit Community Cloud) into os.environ,
# so tools.py/agent.py can keep reading via os.environ the same way local dev
# does via .env -- one code path for both environments.
for _key in ("GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"):
    if not os.environ.get(_key):
        value = st.secrets.get(_key)
        if value:
            os.environ[_key] = value

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from agent import make_chat  # noqa: E402
from tools import get_log_for_date, get_profile  # noqa: E402

st.set_page_config(page_title="Health Assistant", page_icon="🧬")


def check_password() -> bool:
    """Simple password gate for the public-hosted version. Not needed for
    purely local use, but required once this app has a public URL -- it holds
    real personal health data and a live API key."""
    app_password = st.secrets.get("APP_PASSWORD")
    if not app_password:
        return True  # no password configured (e.g. local dev) -- skip the gate
    if st.session_state.get("authenticated"):
        return True

    st.title("🧬 Personal Health Assistant")
    pw = st.text_input("Password", type="password")
    if pw:
        if pw == app_password:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")
    return False


if not check_password():
    st.stop()

st.title("🧬 Personal Health Assistant")
st.caption("Grounded in your profile + a curated research corpus. Not medical advice.")

if "chat" not in st.session_state:
    try:
        # session_state must hold `client` too, not just `chat` -- google-genai
        # closes its HTTP connection once the Client object is garbage-collected.
        st.session_state.client, st.session_state.chat = make_chat()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

chat = st.session_state.chat

with st.sidebar:
    st.subheader("📊 Today")
    today = get_log_for_date(date.today().isoformat())
    targets = get_profile().get("current_targets", {})

    if today:
        def _metric(label, key, unit=""):
            value = today.get(key)
            if value is None:
                return
            target = targets.get(key)
            delta = f"{value - target:+.0f} vs target" if isinstance(target, (int, float)) else None
            st.metric(label, f"{value:.0f}{unit}", delta=delta, delta_color="off")

        _metric("Calories", "calories")
        _metric("Protein", "protein_g", "g")
        _metric("Fat", "fat_g", "g")
        _metric("Carbs", "carbs_g", "g")
        if today.get("weight_kg"):
            st.metric("Weight", f"{today['weight_kg']:.1f}kg")
        if today.get("workout"):
            st.caption(f"🏋️ {today['workout']}")
        if today.get("notes"):
            st.caption(f"📝 {today['notes']}")
    else:
        st.caption("Nothing logged today yet — just tell the assistant what you ate or did.")


def extract_text(content) -> str:
    return "".join(part.text or "" for part in (content.parts or []) if part.text)


for content in chat.get_history():
    if content.role not in ("user", "model"):
        continue
    text = extract_text(content)
    if text:
        with st.chat_message("assistant" if content.role == "model" else "user"):
            st.markdown(text)

if prompt := st.chat_input("Ask about your targets, tradeoffs, or log today's data..."):
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                response_text = chat.send_message(prompt).text
            except Exception as e:
                response_text = f"_(request failed: {e})_"
        st.markdown(response_text or "_(no text response)_")
