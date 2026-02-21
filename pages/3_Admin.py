import streamlit as st
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rag.neet_rag import NEETRAG
from src.jobs.queue import IngestionQueue
from src.utils.content_manager import ContentSourceManager, AutoUpdater

load_dotenv()

st.set_page_config(page_title="Content Admin | NEET RAG", layout="wide")

# Simple Authentication
if "admin_logged_in" not in st.session_state:
    st.session_state.admin_logged_in = False

if not st.session_state.admin_logged_in:
    st.title("Admin Access Required 🔒")
    password = st.text_input("Enter Admin Password", type="password")

    correct_password = os.getenv("ADMIN_PASSWORD", "ihoZfDDpMhARpPjW")

    if st.button("Login"):
        if password == correct_password:
            st.session_state.admin_logged_in = True
            st.rerun()
        else:
            st.error("Incorrect password")
    st.stop()

# --- Authenticated Admin Area ---


@st.cache_resource
def get_rag_system():
    llm_provider = "openai"
    llm_model = os.getenv("OPENAI_MODEL_NAME", "google/gemini-2.0-flash-001")
    base_url = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    return NEETRAG(
        llm_provider=llm_provider, llm_model=llm_model, llm_base_url=base_url
    )


rag = get_rag_system()
source_manager = ContentSourceManager()
updater = AutoUpdater(source_manager, rag)

try:
    ingestion_queue = IngestionQueue()
    queue_enabled = True
except Exception:
    ingestion_queue = None
    queue_enabled = False

st.title("⚙️ Content Management Admin")
st.markdown(
    "Use this panel to ingest and manage documents and videos in the RAG vector store."
)

col1, col2 = st.columns([1, 2])

with col1:
    st.header("Add New Source")
    with st.form("add_source_form"):
        source_url = st.text_input("YouTube URL or PDF Path")
        source_title = st.text_input("Title (Optional)")
        track_id = st.selectbox(
            "Transcript Track",
            ["yt_api", "hinglish_asr", "hindi_english_manual"],
            index=0,
        )
        s3_audio_uri = st.text_input("S3 Audio URI (Optional, for YouTube fallback)")
        s3_transcript_json_uri = st.text_input("S3 Transcript JSON URI (Optional)")

        c1, c2 = st.columns(2)
        submit_yt = c1.form_submit_button("Add YouTube")
        submit_pdf = c2.form_submit_button("Add PDF")

        if submit_yt and source_url:
            metadata = None
            if s3_audio_uri or s3_transcript_json_uri or track_id:
                metadata = {}
                if track_id:
                    metadata["track_id"] = track_id
                if s3_audio_uri:
                    metadata["s3_audio_uri"] = s3_audio_uri
                if s3_transcript_json_uri:
                    metadata["s3_transcript_json_uri"] = s3_transcript_json_uri
            source_id = source_manager.add_youtube(
                source_url,
                source_title or None,
                metadata=metadata,
            )
            if queue_enabled and ingestion_queue:
                ingestion_queue.submit_job(
                    source_id,
                    source_url,
                    "youtube",
                    s3_audio_uri=s3_audio_uri or None,
                    s3_transcript_json_uri=s3_transcript_json_uri or None,
                    track_id=track_id or None,
                )
                st.success("YouTube source added to ingestion queue.")
            else:
                st.warning("Queue is not configured; source saved as pending.")

        if submit_pdf and source_url:
            source_id = source_manager.add_pdf(source_url, source_title or None)
            if queue_enabled and ingestion_queue:
                ingestion_queue.submit_job(source_id, source_url, "pdf")
                st.success("PDF source added to ingestion queue.")
            else:
                st.warning("Queue is not configured; source saved as pending.")

    st.divider()

    st.header("Process Queue")
    if st.button("🔄 Update/Ingest All Pending Sources", type="primary"):
        if queue_enabled and ingestion_queue:
            pending_sources = source_manager.get_sources_needing_update()
            for src in pending_sources:
                s3_uri = None
                s3_transcript_uri = None
                src_track_id = None
                if src.metadata and isinstance(src.metadata, dict):
                    s3_uri = src.metadata.get("s3_audio_uri")
                    s3_transcript_uri = src.metadata.get("s3_transcript_json_uri")
                    src_track_id = src.metadata.get("track_id")
                ingestion_queue.submit_job(
                    src.source_id,
                    src.url,
                    src.source_type,
                    s3_audio_uri=s3_uri,
                    s3_transcript_json_uri=s3_transcript_uri,
                    track_id=src_track_id,
                )
            st.success(
                f"Queued {len(pending_sources)} source(s) for background ingestion."
            )
        else:
            with st.status("Processing sources...", expanded=True) as status:
                results = updater.update_all()
                for res in results:
                    if res.get("status") == "success":
                        st.write(f"✅ {res.get('source_id')}: Updated")
                    else:
                        st.write(
                            f"❌ {res.get('source_id')}: Failed - {res.get('error')}"
                        )
                status.update(label="Update Complete!", state="complete")

with col2:
    st.header("Existing Sources Database")
    sources = source_manager.get_all_sources()

    error_sources = [s for s in sources if s.status == "error"]
    if error_sources:
        if st.button("Retry All Failed Sources", type="secondary"):
            if queue_enabled and ingestion_queue:
                for src in error_sources:
                    s3_uri = None
                    s3_transcript_uri = None
                    src_track_id = None
                    if src.metadata and isinstance(src.metadata, dict):
                        s3_uri = src.metadata.get("s3_audio_uri")
                        s3_transcript_uri = src.metadata.get("s3_transcript_json_uri")
                        src_track_id = src.metadata.get("track_id")
                    ingestion_queue.submit_job(
                        src.source_id,
                        src.url,
                        src.source_type,
                        s3_audio_uri=s3_uri,
                        s3_transcript_json_uri=s3_transcript_uri,
                        track_id=src_track_id,
                    )
                st.success(f"Queued {len(error_sources)} failed source(s) for retry.")
            else:
                with st.status("Retrying failed sources...", expanded=True) as status:
                    retried = 0
                    for src in error_sources:
                        result = updater.update_source(src.source_id)
                        if result.get("status") == "success":
                            retried += 1
                    status.update(label="Retry Complete", state="complete")
                st.success(
                    f"Retried {len(error_sources)} failed source(s), {retried} succeeded."
                )

    if not sources:
        st.info("No sources found in the database.")

    for s in sources:
        status_icon = (
            "🟢" if s.status == "active" else "🔴" if s.status == "error" else "⚪"
        )
        with st.expander(f"{status_icon} {s.title or s.url}"):
            st.write(f"**URL:** {s.url}")
            st.write(f"**Type:** {s.source_type}")
            st.write(f"**Status:** {s.status}")
            st.write(f"**Last Updated:** {s.last_updated}")
            if (
                s.metadata
                and isinstance(s.metadata, dict)
                and s.metadata.get("track_id")
            ):
                st.write(f"**Track ID:** {s.metadata.get('track_id')}")
            if hasattr(s, "error_message") and s.error_message:
                st.error(f"Error: {s.error_message}")

            if s.status == "error":
                if st.button("Retry This Source", key=f"retry_{s.source_id}"):
                    if queue_enabled and ingestion_queue:
                        s3_uri = None
                        s3_transcript_uri = None
                        src_track_id = None
                        if s.metadata and isinstance(s.metadata, dict):
                            s3_uri = s.metadata.get("s3_audio_uri")
                            s3_transcript_uri = s.metadata.get("s3_transcript_json_uri")
                            src_track_id = s.metadata.get("track_id")
                        ingestion_queue.submit_job(
                            s.source_id,
                            s.url,
                            s.source_type,
                            s3_audio_uri=s3_uri,
                            s3_transcript_json_uri=s3_transcript_uri,
                            track_id=src_track_id,
                        )
                        st.success("Source re-queued for ingestion.")
                    else:
                        result = updater.update_source(s.source_id)
                        if result.get("status") == "success":
                            st.success("Source retried successfully.")
                        else:
                            st.error(
                                f"Retry failed: {result.get('error', 'Unknown error')}"
                            )
