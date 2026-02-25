import streamlit as st
import os
import sys
import uuid
import json
import logging
import traceback
import redis
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.rag_singleton import get_rag_system
from src.utils.ui_helpers import hide_admin_and_toolbar

load_dotenv()
logger = logging.getLogger(__name__)


def debug_log(message: str):
    logger.info(message)
    print(message)


st.set_page_config(page_title="NEET Chat", layout="wide")

hide_admin_and_toolbar()


# --- Redis Session Management ---
def get_redis_client():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        debug_log(f"Chat page: connecting to Redis at {redis_url}")
        return redis.from_url(redis_url)
    except Exception as e:
        logger.exception("Chat page: Redis connection failed")
        st.warning("Redis not connected. History will not be saved across sessions.")
        return None


r = get_redis_client()

# Generate or retrieve session ID
if "session_id" not in st.session_state:
    # Use query params if passed (for history links), otherwise create new
    query_params = st.query_params
    if "session_id" in query_params:
        st.session_state.session_id = str(query_params["session_id"])
    else:
        st.session_state.session_id = str(uuid.uuid4())

session_id = st.session_state.session_id
redis_key = f"chat_history:{session_id}"

# Load history from Redis if it exists
if "messages" not in st.session_state:
    if r and r.exists(redis_key):
        try:
            raw_history = r.get(redis_key)
            if isinstance(raw_history, (bytes, bytearray)):
                raw_history = raw_history.decode("utf-8", errors="ignore")
            if isinstance(raw_history, str):
                st.session_state.messages = json.loads(raw_history)
            else:
                st.session_state.messages = []
        except Exception:
            logger.exception(
                "Chat page: failed to parse history from Redis key=%s", redis_key
            )
            st.session_state.messages = []
    else:
        st.session_state.messages = []


def save_history():
    if r:
        r.setex(
            redis_key, 86400 * 7, json.dumps(st.session_state.messages)
        )  # Save for 7 days


try:
    debug_log(f"Chat page: initializing RAG singleton for session_id={session_id}")
    rag = get_rag_system()
    debug_log("Chat page: RAG initialized successfully")
except Exception as e:
    logger.exception("Chat page: get_rag_system failed")
    st.error(f"Chat initialization failed: {e}")
    st.code(traceback.format_exc())
    st.stop()

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
            try:
                debug_log(f"Chat page: executing rag.query for session_id={session_id}")
                response = rag.query(prompt)
            except Exception as e:
                logger.exception("Chat page: rag.query failed")
                st.error(f"Query failed: {e}")
                st.code(traceback.format_exc())
                st.stop()
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
