import streamlit as st
import os
import sys
import uuid
import json
import re
import logging
import traceback
import hashlib
from urllib.parse import parse_qs, urlparse
import redis
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.rag_singleton import get_rag_system
from src.utils.ui_helpers import setup_public_page_chrome

load_dotenv()
logger = logging.getLogger(__name__)


def _latex_to_streamlit(text: str) -> str:
    text = re.sub(r"\\\[(.+?)\\\]", r"$$\1$$", text, flags=re.DOTALL)
    text = re.sub(r"\\\((.+?)\\\)", r"$\1$", text, flags=re.DOTALL)
    return text


def debug_log(message: str):
    logger.info(message)
    print(message)


st.set_page_config(
    page_title="NEET Chat", layout="wide", initial_sidebar_state="collapsed"
)

setup_public_page_chrome()

try:
    CHAT_HISTORY_TURNS = max(0, int(os.getenv("CHAT_HISTORY_TURNS", "4")))
except Exception:
    CHAT_HISTORY_TURNS = 4

SHOW_MORE_ENABLED = os.getenv("SHOW_MORE_ENABLED", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

SHOW_QUESTION_SOURCES = os.getenv("SHOW_QUESTION_SOURCES", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

ASK_ASSISTANT_ENABLED = os.getenv("ASK_ASSISTANT_ENABLED", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

try:
    SHOW_MORE_LIMIT = max(1, int(os.getenv("SHOW_MORE_LIMIT", "10")))
except Exception:
    SHOW_MORE_LIMIT = 10


_NK_MODAL_JS = """
(function(){
  var pw = window.parent;
  var pd = pw.document;
  if (pd.getElementById('nk-modal-overlay')) return;
  var css = pd.createElement('style');
  css.textContent = `
    #nk-modal-overlay {
      display:none; position:fixed; inset:0; z-index:999999;
      background:rgba(0,0,0,0.6); align-items:center; justify-content:center;
    }
    #nk-modal-overlay .nk-box {
      background:#fff; border-radius:12px; width:90vw; max-width:800px;
      max-height:90vh; display:flex; flex-direction:column;
      box-shadow:0 8px 32px rgba(0,0,0,0.3); overflow:hidden;
    }
    #nk-modal-overlay .nk-hdr {
      display:flex; justify-content:space-between; align-items:center;
      padding:12px 16px; border-bottom:1px solid #e0e0e0;
      position:relative; z-index:2;
    }
    #nk-modal-overlay .nk-close {
      background:none; border:none; font-size:28px; cursor:pointer;
      color:#666; padding:4px 8px; line-height:1; position:relative; z-index:3;
    }
    #nk-modal-overlay .nk-close:hover { color:#333; }
    #nk-modal-iframe { border:none; flex:1; min-height:480px; position:relative; z-index:1; }
    #nk-modal-footer {
      padding:8px 16px; border-top:1px solid #e0e0e0;
      text-align:center; font-size:13px;
    }
  `;
  pd.head.appendChild(css);
  var d = pd.createElement('div');
  d.id = 'nk-modal-overlay';
  d.innerHTML = '<div class="nk-box">'
    + '<div class="nk-hdr"><span id="nk-modal-title" style="font-weight:600;font-size:16px"></span>'
    + '<button class="nk-close" id="nk-modal-close-btn" onclick="window.closeNKModal&&window.closeNKModal()">\\u00d7</button></div>'
    + '<iframe id="nk-modal-iframe" allow="autoplay; encrypted-media" allowfullscreen></iframe>'
    + '<div id="nk-modal-footer"></div></div>';
  pd.body.appendChild(d);

  function doClose() {
    pd.getElementById('nk-modal-overlay').style.display = 'none';
    pd.getElementById('nk-modal-iframe').src = '';
  }

  d.addEventListener('click', function(e){ if(e.target===d) doClose(); });

  pw.openNKModal = function(src, title, linkUrl, linkText) {
    pd.getElementById('nk-modal-title').textContent = title || '';
    pd.getElementById('nk-modal-iframe').src = src;
    var f = pd.getElementById('nk-modal-footer');
    if (linkUrl) {
      f.innerHTML = '<a href="'+linkUrl+'" target="_blank" rel="noopener">'+(linkText||linkUrl)+'</a>';
      f.style.display = 'block';
    } else { f.style.display = 'none'; }
    pd.getElementById('nk-modal-overlay').style.display = 'flex';
  };
  pw.closeNKModal = doClose;
})();
"""


def _ensure_modal_js():
    import streamlit.components.v1 as components

    components.html(f"<script>{_NK_MODAL_JS}</script>", height=0)


def _parse_youtube_timestamp(raw_value: str) -> int:
    value = str(raw_value or "").strip().lower()
    if not value:
        return 0

    if value.startswith("t="):
        value = value[2:]

    if value.isdigit():
        return int(value)

    if value.endswith("s") and value[:-1].isdigit():
        return int(value[:-1])

    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?", value)
    if not match:
        return 0

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return (hours * 3600) + (minutes * 60) + seconds


def _extract_youtube_video_id(parsed_url) -> str:
    host = parsed_url.netloc.lower().replace("www.", "")
    path = parsed_url.path.strip("/")
    query = parse_qs(parsed_url.query)

    if host in {"youtube.com", "m.youtube.com", "youtube-nocookie.com"}:
        if path == "watch":
            return (query.get("v") or [""])[0]
        if path.startswith("embed/"):
            return path.split("/", 1)[1]
        if path.startswith("shorts/"):
            return path.split("/", 1)[1]
        if path.startswith("live/"):
            return path.split("/", 1)[1]

    if host == "youtu.be" and path:
        return path.split("/", 1)[0]

    return ""


def _extract_start_seconds(parsed_url) -> int:
    query = parse_qs(parsed_url.query)

    for key in ("start", "t", "time_continue"):
        values = query.get(key)
        if values:
            seconds = _parse_youtube_timestamp(values[0])
            if seconds > 0:
                return seconds

    fragment = parsed_url.fragment
    if not fragment:
        return 0

    seconds = _parse_youtube_timestamp(fragment)
    if seconds > 0:
        return seconds

    if "=" in fragment:
        seconds = _parse_youtube_timestamp(fragment.split("=", 1)[1])
        if seconds > 0:
            return seconds

    return 0


def build_youtube_embed_url(video_url: str) -> str:
    # Build an embed URL so sources open in-app, while keeping original start timestamp.
    if not video_url:
        return ""

    parsed_url = urlparse(video_url)
    video_id = _extract_youtube_video_id(parsed_url)
    if not video_id:
        return ""

    start_seconds = _extract_start_seconds(parsed_url)
    embed_url = f"https://www.youtube.com/embed/{video_id}?rel=0"
    if start_seconds > 0:
        embed_url = f"{embed_url}&start={start_seconds}"

    return embed_url


def _js_open_video_button(embed_url: str, title: str):
    import streamlit.components.v1 as components

    safe_title = (
        title.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    safe_url = embed_url.replace("\\", "\\\\").replace("'", "\\'")
    components.html(
        f"""<button onclick="window.parent.openNKModal('{safe_url}','{safe_title}','','')"
         style="padding:6px 16px;border:1px solid #ddd;border-radius:6px;
         background:#f8f8f8;cursor:pointer;font-size:14px;color:#333">Open Video</button>""",
        height=42,
    )


def _js_open_question_button(question_id: str):
    import streamlit.components.v1 as components

    q_url = f"https://www.neetprep.com/epubQuestion/{question_id}"
    components.html(
        f"""<button onclick="window.parent.openNKModal('{q_url}','Question','{q_url}','Open on NeetPrep')"
         style="padding:6px 16px;border:1px solid #ddd;border-radius:6px;
         background:#f8f8f8;cursor:pointer;font-size:14px;color:#333">Open Question</button>""",
        height=42,
    )


def _extract_question_text(content: str) -> str:
    """Extract only the question portion from CSV page_content.

    CSV docs store content as:
      Question:
      <markdown>

      Official Solution/Explanation:
      <markdown>

    Returns the question markdown (without the 'Question:' prefix) or the
    full content if the expected structure is not found.
    """
    separator = "Official Solution/Explanation:"
    parts = content.split(separator, 1)
    question_part = parts[0].strip()
    if question_part.lower().startswith("question:"):
        question_part = question_part[len("question:") :].strip()
    return question_part or content.strip()


def render_source_item(src: dict, idx: int, key_prefix: str):
    content_type = src.get("content_type", "text")
    source_url = src.get("source", "Unknown")
    title = src.get("title", "")

    if content_type == "youtube":
        timestamp_url = src.get("timestamp_url") or source_url
        ts_label = src.get("timestamp_label", "")
        channel_name = ""
        for channel_key in ("channel", "channel_name", "channel_title", "uploader"):
            candidate = str(src.get(channel_key, "") or "").strip()
            if candidate:
                channel_name = candidate
                break

        display_title = title or channel_name or source_url
        display_text = f"**Source {idx + 1}** 📺 {display_title}"
        if ts_label:
            display_text = f"{display_text} @ {ts_label}"

        st.markdown(display_text)

        embed_url = build_youtube_embed_url(timestamp_url)
        if embed_url:
            _js_open_video_button(embed_url, display_title)
        else:
            st.caption("Unable to parse YouTube URL for embedded playback.")

        if isinstance(timestamp_url, str) and timestamp_url.startswith(
            ("http://", "https://")
        ):
            link_label = display_title
            if channel_name and channel_name.lower() not in link_label.lower():
                link_label = f"{link_label} - {channel_name}"
            if ts_label:
                link_label = f"{link_label} @ {ts_label}"

            safe_link_label = (
                link_label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
            )
            st.markdown(f"[{safe_link_label}](<{timestamp_url}>)")
    else:
        st.markdown(f"**Source {idx + 1} ({content_type}):** {source_url}")

    st.text(src.get("content", ""))


def _js_ask_assistant_button(question_text: str):
    import streamlit.components.v1 as components

    escaped = (
        question_text.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("$", "\\$")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    components.html(
        f"""<button onclick="(function(){{
          var ta=window.parent.document.querySelector('textarea[data-testid=stChatInputTextArea]');
          if(!ta)return;
          var set=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
          set.call(ta,`{escaped}`);
          ta.dispatchEvent(new Event('input',{{bubbles:true}}));
          ta.focus();
        }})()"
         style="padding:6px 16px;border:1px solid #ddd;border-radius:6px;
         background:#f8f8f8;cursor:pointer;font-size:14px;color:#333">Ask Assistant</button>""",
        height=42,
    )


def render_question_item(
    src: dict, idx: int, key_prefix: str, show_ask_assistant: bool = False
):
    question_id = src.get("question_id", "")
    question_url = f"https://www.neetprep.com/epubQuestion/{question_id}"
    content_preview = src.get("content", "")
    full_content = src.get("full_content", content_preview)

    st.markdown(f"**Question {idx + 1}**")
    if content_preview:
        st.text(content_preview)

    _js_open_question_button(question_id)

    if show_ask_assistant and full_content:
        question_text = _extract_question_text(full_content)
        _js_ask_assistant_button(question_text)

    st.markdown(f"[Open on NeetPrep]({question_url})")


def _collect_video_ids(sources: list) -> list:
    ids = []
    for src in sources:
        vid = src.get("video_id", "")
        if vid and vid not in ids:
            ids.append(vid)
    return ids


def _on_show_more(message_idx: int, query: str, current_sources: list):
    rag = get_rag_system()
    exclude = _collect_video_ids(current_sources)
    extra = rag.get_more_youtube_sources(
        question=query,
        exclude_video_ids=exclude,
        limit=SHOW_MORE_LIMIT,
    )
    if extra:
        st.session_state.messages[message_idx]["sources"].extend(extra)
        save_history()
    st.session_state[f"show_more_done_{message_idx}"] = True


def render_sources_block(
    sources: list,
    key_prefix: str,
    message_idx: int = -1,
    query: str = "",
    question_sources=None,
):
    if sources:
        with st.expander("Show Videos", expanded=True):
            for idx, src in enumerate(sources):
                render_source_item(src, idx, key_prefix)

            if SHOW_MORE_ENABLED and message_idx >= 0:
                done_key = f"show_more_done_{message_idx}"
                if not st.session_state.get(done_key, False):
                    st.divider()
                    st.button(
                        "Show More Videos",
                        key=f"{key_prefix}_show_more",
                        on_click=_on_show_more,
                        args=(message_idx, query, sources),
                    )

    if SHOW_QUESTION_SOURCES and question_sources:
        with st.expander("Show Questions", expanded=False):
            for idx, src in enumerate(question_sources):
                render_question_item(
                    src,
                    idx,
                    f"{key_prefix}_q",
                    show_ask_assistant=ASK_ASSISTANT_ENABLED,
                )


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
st.title("💬 NEET PYQ Assistant")

if "image_context_text" not in st.session_state:
    st.session_state.image_context_text = ""
if "image_context_hash" not in st.session_state:
    st.session_state.image_context_hash = ""
if "image_context_pending" not in st.session_state:
    st.session_state.image_context_pending = False

last_user_query = ""
for message_idx, message in enumerate(st.session_state.messages):
    if message["role"] == "user":
        last_user_query = message["content"]

    with st.chat_message(message["role"]):
        st.markdown(_latex_to_streamlit(message["content"]))

        if message["role"] == "assistant" and (
            message.get("sources") or message.get("question_sources")
        ):
            render_sources_block(
                message.get("sources", []),
                key_prefix=f"history_msg_{message_idx}",
                message_idx=message_idx,
                query=last_user_query,
                question_sources=message.get("question_sources"),
            )

if st.session_state.image_context_text:
    st.caption("Image context (used only for the next reply)")
    st.text_area(
        "",
        value=st.session_state.image_context_text,
        height=220,
        disabled=True,
        key="image_context_preview",
    )
    if st.button("Clear Image Context"):
        st.session_state.image_context_text = ""
        st.session_state.image_context_hash = ""
        st.session_state.image_context_pending = False
        st.success("Image context cleared.")

chat_payload = st.chat_input(
    "Ask a PYQ question and get its solution from your favourite teachers on youtube",
    accept_file=True,
    file_type=["png", "jpg", "jpeg", "webp"],
    max_upload_size=5,
)

if chat_payload:
    prompt = ""
    uploaded_image = None
    if isinstance(chat_payload, str):
        prompt = chat_payload.strip()
    else:
        prompt = str(getattr(chat_payload, "text", "") or "").strip()
        files = list(getattr(chat_payload, "files", []) or [])
        if not files and isinstance(chat_payload, dict):
            files = list(chat_payload.get("files", []) or [])
            maybe_file = chat_payload.get("file")
            if maybe_file is not None:
                files = [maybe_file]
        if files:
            uploaded_image = files[0]

    if uploaded_image is not None:
        image_bytes = uploaded_image.getvalue()
        if len(image_bytes) > 5 * 1024 * 1024:
            st.error("Image is too large. Please upload an image up to 5 MB.")
        else:
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
                    st.session_state.image_context_pending = True
                    st.success(
                        "Image context extracted and will be used for the next reply."
                    )
                except Exception as e:
                    logger.exception("Chat page: image context extraction failed")
                    st.error(f"Image extraction failed: {e}")
            elif st.session_state.image_context_text:
                if not st.session_state.image_context_pending:
                    st.session_state.image_context_pending = True
                    st.success(
                        "Image context reused and will be used for the next reply."
                    )
                else:
                    st.info("Image context is already queued for the next reply.")

    if not prompt:
        st.info("Please enter a question along with the uploaded image.")
    else:
        # 1. Add and display user message
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        save_history()

        # 2. Generate and display assistant response
        with st.chat_message("assistant"):
            with st.spinner("Searching knowledge base..."):
                try:
                    debug_log(
                        f"Chat page: executing rag.query for session_id={session_id}"
                    )
                    retrieval_query = prompt
                    if (
                        st.session_state.image_context_pending
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
                    if st.session_state.image_context_pending:
                        st.session_state.image_context_pending = False
                except Exception as e:
                    logger.exception("Chat page: rag.query failed")
                    response = {
                        "answer": "Knowledge base is empty or unavailable. Please ingest content first.",
                        "sources": [],
                        "error": str(e),
                    }
                answer = response.get("answer", "No answer generated.")
                sources = response.get("sources", [])

            st.markdown(_latex_to_streamlit(answer))

            question_sources = response.get("question_sources", [])

            assistant_msg = {
                "role": "assistant",
                "content": answer,
                "sources": sources,
                "question_sources": question_sources,
            }
            st.session_state.messages.append(assistant_msg)
            save_history()

            if sources or question_sources:
                render_sources_block(
                    sources,
                    key_prefix=f"live_response_{len(st.session_state.messages)}",
                    message_idx=len(st.session_state.messages) - 1,
                    query=prompt,
                    question_sources=question_sources,
                )

_ensure_modal_js()
