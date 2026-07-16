"""Streamlit chat UI for the PRO FX agentic RAG assistant.

Run with:
    streamlit run ui/app.py

Each browser tab gets its own session_id (auto-created and persisted in
data/chat_state.sqlite3). Conversation memory lives entirely in the
LangGraph checkpointer, keyed by that session_id as the thread_id — this UI
is a thin view over it, not a second source of truth.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage

import config  # noqa: F401 -- importing triggers load_dotenv() + LangSmith env wiring
from agents import session_store
from agents.graph import build_graph, get_checkpointer, make_thread_config

LOGO_PATH = Path(__file__).resolve().parent.parent / "logo.png"
FAVICON_PATH = Path(__file__).resolve().parent.parent / "PROFXfavicon.png"

st.set_page_config(page_title="PRO FX Assistant", page_icon=str(FAVICON_PATH), layout="centered")

DISCLAIMER = "PRO FX Assistant can make mistakes. Please verify important details with our team."


@st.cache_resource
def _get_graph():
    checkpointer = get_checkpointer()
    return build_graph(checkpointer), checkpointer


graph, checkpointer = _get_graph()


def _format_timestamp(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw).strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return ""


def _render_message(msg):
    role = "user" if isinstance(msg, HumanMessage) else "assistant"
    with st.chat_message(role):
        st.markdown(msg.content)
        timestamp = _format_timestamp(msg.additional_kwargs.get("timestamp"))
        if timestamp:
            st.caption(timestamp)


def _switch_session(session_id: str):
    st.session_state.session_id = session_id


# ---- Sidebar: session list ----
with st.sidebar:
    st.image(str(LOGO_PATH), width="stretch")
    if st.button("+ New chat", width="stretch"):
        new_id = session_store.create_session()
        _switch_session(new_id)
        st.rerun()

    st.markdown("---")
    for s in session_store.list_sessions():
        col1, col2 = st.columns([5, 1])
        active = st.session_state.get("session_id") == s["id"]
        with col1:
            if st.button(("• " if active else "") + s["title"], key=f"switch-{s['id']}", width="stretch"):
                _switch_session(s["id"])
                st.rerun()
        with col2:
            if st.button("🗑", key=f"delete-{s['id']}"):
                session_store.delete_session(s["id"], checkpointer)
                if active:
                    st.session_state.pop("session_id", None)
                st.rerun()

# ---- Cold start: auto-create a session ----
if "session_id" not in st.session_state:
    sessions = session_store.list_sessions()
    st.session_state.session_id = sessions[0]["id"] if sessions else session_store.create_session()

session_id = st.session_state.session_id
thread_config = make_thread_config(session_id)

st.image(str(LOGO_PATH), width=280)
st.caption("Ask about products, brands, installation, pricing, or request a demo.")

# A toast set just before st.rerun() would otherwise be wiped out before the
# user ever sees it, since rerun() re-executes the script from the top — so
# it's stashed in session_state and shown once here instead. st.toast()
# (floating, bottom-of-screen) is used rather than st.warning/st.info since
# the chat auto-scrolls to the latest message, which would hide a banner
# placed at the top of the page.
pending_toast = st.session_state.pop("pending_toast", None)
if pending_toast:
    text, icon = pending_toast
    st.toast(text, icon=icon)

# ---- Render existing history from the checkpointer ----
state_values = graph.get_state(thread_config).values or {}
for msg in state_values.get("messages", []):
    if isinstance(msg, (HumanMessage, AIMessage)):
        _render_message(msg)

# ---- Handle new input ----
user_text = st.chat_input("Type your message...")
if user_text:
    with st.chat_message("user"):
        st.markdown(user_text)

    session_store.touch_session(session_id, first_message=user_text)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        with st.spinner("Processing..."):
            final_update = {}
            for update in graph.stream(
                {"user_input": user_text, "session_id": session_id},
                config=thread_config,
                stream_mode="updates",
            ):
                node_name = next(iter(update))
                final_update = update[node_name]
        answer = final_update.get("answer", "") or "Sorry, something went wrong generating a response."
        placeholder.markdown(answer)

    latest = graph.get_state(thread_config).values or {}
    if latest.get("guard_blocked"):
        st.session_state["pending_toast"] = ("Message blocked by the safety filter.", "🚫")
    elif latest.get("pii_redacted"):
        st.session_state["pending_toast"] = ("Personal information was redacted before processing.", "🔒")

    st.rerun()

st.caption(DISCLAIMER)
