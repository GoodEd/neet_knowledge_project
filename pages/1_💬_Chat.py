import streamlit as st
import os
import sys
import uuid
import json
import redis
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rag.neet_rag import NEETRAG
from src.utils.config import Config
from src.utils.ui_helpers import hide_admin_and_toolbar

load_dotenv()

st.set_page_config(page_title="NEET Chat", layout="wide")

hide_admin_and_toolbar()


# --- Redis Session Management ---
def get_redis_client():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        return redis.from_url(redis_url)
    except Exception as e:
        st.warning("Redis not connected. History will not be saved across sessions.")
        return None


r = get_redis_client()

# Generate or retrieve session ID
if "session_id" not in st.session_state:
    # Use query params if passed (for history links), otherwise create new
    query_params = st.query_params
    if "session_id" in query_params:
        st.session_state.session_id = query_params["session_id"]
    else:
        st.session_state.session_id = str(uuid.uuid4())

session_id = st.session_state.session_id
redis_key = f"chat_history:{session_id}"

# Load history from Redis if it exists
if "messages" not in st.session_state:
    if r and r.exists(redis_key):
        st.session_state.messages = json.loads(r.get(redis_key))
    else:
        st.session_state.messages = []


def save_history():
    if r:
        r.setex(
            redis_key, 86400 * 7, json.dumps(st.session_state.messages)
        )  # Save for 7 days


# --- RAG Setup ---
@st.cache_resource
def get_rag_system():
    llm_provider = "openai"
    llm_model = os.getenv("OPENAI_MODEL_NAME", "google/gemini-2.0-flash-001")
    base_url = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    return NEETRAG(
        llm_provider=llm_provider, llm_model=llm_model, llm_base_url=base_url
    )


rag = get_rag_system()

# --- UI ---
st.title("💬 NEET Knowledge Assistant")
st.caption(f"Session ID: `{session_id}` (Save this to restore your chat later!)")

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

        # Display sources if assistant message has them
        if (
            message["role"] == "assistant"
            and "sources" in message
            and message["sources"]
        ):
            with st.expander("View Sources"):
                for idx, src in enumerate(message["sources"]):
                    content_type = src.get("content_type", "text")
                    source_url = src.get("source", "Unknown")
                    title = src.get("title", "")

                    if content_type == "youtube" and src.get("timestamp_url"):
                        ts_label = src.get("timestamp_label", "")
                        display_title = title or source_url
                        if ts_label:
                            st.markdown(
                                f"**Source {idx + 1}** 📺 [{display_title} @ {ts_label}]({src['timestamp_url']})"
                            )
                        else:
                            st.markdown(
                                f"**Source {idx + 1}** 📺 [{display_title}]({src['timestamp_url']})"
                            )
                    else:
                        st.markdown(
                            f"**Source {idx + 1} ({content_type}):** {source_url}"
                        )

                    st.text(src.get("content", ""))

# User Input
if prompt := st.chat_input("Ask a question about NEET 2025..."):
    # 1. Add and display user message
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})
    save_history()

    # 2. Generate and display assistant response
    with st.chat_message("assistant"):
        with st.spinner("Searching knowledge base..."):
            response = rag.query(prompt)
            answer = response.get("answer", "No answer generated.")
            sources = response.get("sources", [])

            st.markdown(answer)

            # Save assistant response to state
            assistant_msg = {"role": "assistant", "content": answer, "sources": sources}
            st.session_state.messages.append(assistant_msg)
            save_history()

            # Show sources
            if sources:
                with st.expander("View Sources"):
                    for idx, src in enumerate(sources):
                        content_type = src.get("content_type", "text")
                        source_url = src.get("source", "Unknown")
                        title = src.get("title", "")

                        if content_type == "youtube" and src.get("timestamp_url"):
                            ts_label = src.get("timestamp_label", "")
                            display_title = title or source_url
                            if ts_label:
                                st.markdown(
                                    f"**Source {idx + 1}** 📺 [{display_title} @ {ts_label}]({src['timestamp_url']})"
                                )
                            else:
                                st.markdown(
                                    f"**Source {idx + 1}** 📺 [{display_title}]({src['timestamp_url']})"
                                )
                        else:
                            st.markdown(
                                f"**Source {idx + 1} ({content_type}):** {source_url}"
                            )
                        st.text(src.get("content"))
