import streamlit as st
import os
import sys
import uuid
import json
import logging
import traceback
import hashlib
from urllib.parse import urlparse
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

try:
    CHAT_HISTORY_TURNS = max(0, int(os.getenv("CHAT_HISTORY_TURNS", "4")))
except Exception:
    CHAT_HISTORY_TURNS = 4


# --- Redis Session Management ---
def get_redis_client():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    def _build_client(url: str):
        return redis.from_url(
            url,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=False,
        )

    try:
        debug_log(f"Chat page: connecting to Redis at {redis_url}")
        client = _build_client(redis_url)
        client.ping()
        debug_log("Chat page: Redis ping successful")
        return client
    except Exception:
        parsed = urlparse(redis_url)
        if parsed.scheme == "redis":
            tls_url = redis_url.replace("redis://", "rediss://", 1)
            try:
                debug_log(f"Chat page: retrying Redis with TLS URL {tls_url}")
                client = _build_client(tls_url)
                client.ping()
                debug_log("Chat page: Redis TLS ping successful")
                return client
            except Exception:
                logger.exception("Chat page: Redis TLS retry failed")
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
    st.session_state.messages = []
    if r:
        try:
            if r.exists(redis_key):
                raw_history = r.get(redis_key)
                if isinstance(raw_history, (bytes, bytearray)):
                    raw_history = raw_history.decode("utf-8", errors="ignore")
                if isinstance(raw_history, str):
                    st.session_state.messages = json.loads(raw_history)
        except Exception:
            logger.exception(
                "Chat page: failed to load history from Redis key=%s", redis_key
            )


def save_history():
    if r:
        try:
            r.setex(redis_key, 86400 * 7, json.dumps(st.session_state.messages))
        except Exception:
            logger.exception(
                "Chat page: failed to save history to Redis key=%s", redis_key
            )


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

if "image_context_text" not in st.session_state:
    st.session_state.image_context_text = ""
if "image_context_hash" not in st.session_state:
    st.session_state.image_context_hash = ""
if "reuse_image_context" not in st.session_state:
    st.session_state.reuse_image_context = True

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

st.subheader("Image Question Context")
uploaded_image = st.file_uploader(
    "Upload question image (JPG/PNG/WebP)",
    type=["png", "jpg", "jpeg", "webp"],
    key="chat_image_uploader",
)
st.session_state.reuse_image_context = st.checkbox(
    "Reuse last image context for next questions",
    value=st.session_state.reuse_image_context,
)

if st.button("Clear Image Context"):
    st.session_state.image_context_text = ""
    st.session_state.image_context_hash = ""
    st.success("Image context cleared.")

if uploaded_image is not None:
    image_bytes = uploaded_image.getvalue()
    image_hash = hashlib.md5(image_bytes).hexdigest()
    if st.session_state.image_context_hash != image_hash:
        try:
            with st.spinner("Extracting question context from image..."):
                extracted = rag.llm_manager.extract_image_context(
                    image_bytes=image_bytes,
                    filename=uploaded_image.name,
                    session_id=session_id,
                    user_id=session_id,
                )
            st.session_state.image_context_text = extracted
            st.session_state.image_context_hash = image_hash
            st.success("Image context extracted and stored.")
        except Exception as e:
            logger.exception("Chat page: image context extraction failed")
            st.error(f"Image extraction failed: {e}")

if st.session_state.image_context_text:
    st.caption("Active image context preview")
    st.text(st.session_state.image_context_text[:700])

# User Input
if prompt := st.chat_input(
    "Ask a PYQ question and get its solution from your favourite teachers on youtube"
):
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
                retrieval_query = prompt
                if (
                    st.session_state.reuse_image_context
                    and st.session_state.image_context_text
                ):
                    retrieval_query = (
                        f"{prompt}\n\n"
                        "Image context from uploaded question image:\n"
                        f"{st.session_state.image_context_text}"
                    )

                history_pairs = []
                running_user = None
                for msg in st.session_state.messages[:-1]:
                    role = msg.get("role")
                    text = msg.get("content", "")
                    if role == "user":
                        running_user = text
                    elif role == "assistant" and running_user is not None:
                        history_pairs.append((running_user, text))
                        running_user = None

                if CHAT_HISTORY_TURNS > 0:
                    history_pairs = history_pairs[-CHAT_HISTORY_TURNS:]

                response = rag.query_with_history(
                    retrieval_query,
                    chat_history=history_pairs,
                    top_k=5,
                    session_id=session_id,
                    user_id=session_id,
                )
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
