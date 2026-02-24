import streamlit as st
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.jobs.queue import IngestionQueue
from src.utils.rag_singleton import get_rag_system
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

rag = get_rag_system()
source_manager = ContentSourceManager()
updater = AutoUpdater(source_manager, rag)

try:
    ingestion_queue = IngestionQueue()
    queue_enabled = True
except Exception:
    ingestion_queue = None
    queue_enabled = False


def true_delete_source(src):
    track_id = None
    if src.metadata and isinstance(src.metadata, dict):
        track_id = src.metadata.get("track_id")

    try:
        removed_vectors = rag.vector_manager.delete_by_source(
            src.url, track_id=track_id
        )
    except FileNotFoundError:
        removed_vectors = 0
    except Exception as e:
        return False, 0, str(e)

    try:
        removed_source = source_manager.remove_source(src.source_id)
    except Exception as e:
        return False, removed_vectors, str(e)
    if not removed_source:
        return False, removed_vectors, "Failed to remove source metadata"

    return True, removed_vectors, None


def enqueue_source(src):
    if not (queue_enabled and ingestion_queue):
        return

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


def recreate_source(src):
    metadata = src.metadata if isinstance(src.metadata, dict) else None
    title = src.title
    fetch_interval_hours = src.fetch_interval_hours

    ok, removed_vectors, err = true_delete_source(src)
    if not ok:
        return False, None, removed_vectors, err

    if src.source_type == "youtube":
        new_id = source_manager.add_youtube(
            src.url,
            title,
            fetch_interval_hours=fetch_interval_hours,
            metadata=metadata,
        )
    elif src.source_type == "pdf":
        new_id = source_manager.add_pdf(src.url, title, metadata=metadata)
    elif src.source_type == "html":
        new_id = source_manager.add_html(
            src.url,
            title,
            fetch_interval_hours=fetch_interval_hours,
        )
    else:
        new_id = source_manager.add_source(
            src.url,
            src.source_type,
            title=title,
            fetch_interval_hours=fetch_interval_hours,
            metadata=metadata,
        )

    new_src = source_manager.get_source(new_id)
    return True, new_src, removed_vectors, None


st.title("⚙️ Content Management Admin")
st.markdown(
    "Use this panel to ingest and manage documents and videos in the RAG vector store."
)

col1, col2 = st.columns([1, 2])

with col1:
    st.header("Add New Source")
    
    tab1, tab2 = st.tabs(["Add YouTube", "Upload File (PDF/CSV)"])
    
    with tab1:
        with st.form("add_youtube_form"):
            source_url = st.text_input("YouTube URL")
            source_title = st.text_input("Video Title (Optional)")
            track_id = st.selectbox(
                "Transcript Track",
                ["yt_api", "hinglish_asr", "hindi_english_manual"],
                index=0,
            )
            s3_audio_uri = st.text_input("S3 Audio URI (Optional)")
            s3_transcript_json_uri = st.text_input("S3 Transcript JSON URI (Optional)")
            
            submit_yt = st.form_submit_button("Add YouTube", type="primary")
            
            if submit_yt and source_url:
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
                    metadata=metadata if metadata else None,
                )
                if queue_enabled and ingestion_queue:
                    src = source_manager.get_source(source_id)
                    if src:
                        enqueue_source(src)
                    st.success("YouTube source added to ingestion queue.")
                else:
                    st.warning("Queue is not configured; source saved as pending.")
                    
    with tab2:
        with st.form("upload_file_form"):
            uploaded_file = st.file_uploader("Upload PDF or CSV from your computer", type=["pdf", "csv"])
            file_title = st.text_input("Title (Optional)")
            
            # Show all fields as requested by user
            st.markdown("**(Optional) Remote Overrides**")
            file_track_id = st.text_input("Track ID Override")
            file_s3_audio_uri = st.text_input("S3 Audio URI Override")
            file_s3_transcript_json_uri = st.text_input("S3 Transcript JSON URI Override")
            
            submit_file = st.form_submit_button("Upload and Ingest", type="primary")
            
            if submit_file and uploaded_file:
                import tempfile
                import shutil
                
                # Save locally to shared EFS so worker can see it
                uploads_dir = "/shared/data/uploads"
                os.makedirs(uploads_dir, exist_ok=True)
                
                safe_filename = uploaded_file.name.replace(" ", "_")
                file_path = os.path.join(uploads_dir, safe_filename)
                
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                metadata = {}
                if file_track_id: metadata["track_id"] = file_track_id
                if file_s3_audio_uri: metadata["s3_audio_uri"] = file_s3_audio_uri
                if file_s3_transcript_json_uri: metadata["s3_transcript_json_uri"] = file_s3_transcript_json_uri
                
                source_type = "pdf" if safe_filename.lower().endswith(".pdf") else "csv"
                
                if source_type == "pdf":
                    source_id = source_manager.add_pdf(file_path, file_title or None, metadata=metadata if metadata else None)
                else:
                    source_id = source_manager.add_csv(file_path, file_title or None, metadata=metadata if metadata else None)
                    
                if queue_enabled and ingestion_queue:
                    # Enqueue using the physical filepath on the shared EFS
                    ingestion_queue.submit_job(
                        source_id=source_id,
                        url=file_path,
                        source_type=source_type,
                        s3_audio_uri=file_s3_audio_uri or None,
                        s3_transcript_json_uri=file_s3_transcript_json_uri or None,
                        track_id=file_track_id or None
                    )
                    st.success(f"{source_type.upper()} file uploaded and added to ingestion queue.")
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

    if "confirm_recreate_all" not in st.session_state:
        st.session_state.confirm_recreate_all = False
    if "confirm_remove_all" not in st.session_state:
        st.session_state.confirm_remove_all = False
    if "confirm_recreate_failed" not in st.session_state:
        st.session_state.confirm_recreate_failed = False

    top_a, top_b = st.columns(2)
    with top_a:
        if st.button("Recreate All Sources", type="secondary"):
            st.session_state.confirm_recreate_all = True

        if st.session_state.confirm_recreate_all:
            st.warning(
                "Confirm recreate all sources? This will delete existing vectors and metadata before re-ingestion."
            )
            c_confirm, c_cancel = st.columns(2)
            if c_confirm.button("Confirm Recreate All", key="confirm_recreate_all_btn"):
                st.session_state.confirm_recreate_all = False
                if queue_enabled and ingestion_queue:
                    recreated = 0
                    removed_vectors_total = 0
                    for src in sources:
                        ok, new_src, removed_vectors, err = recreate_source(src)
                        if ok and new_src:
                            enqueue_source(new_src)
                            recreated += 1
                            removed_vectors_total += removed_vectors
                    st.success(
                        f"Recreated {recreated} source(s), removed {removed_vectors_total} old vector chunks, and queued ingestion."
                    )
                else:
                    with st.status(
                        "Recreating all sources...", expanded=True
                    ) as status:
                        recreated = 0
                        removed_vectors_total = 0
                        for src in sources:
                            ok, new_src, removed_vectors, err = recreate_source(src)
                            if ok and new_src:
                                result = updater.update_source(new_src.source_id)
                                if result.get("status") == "success":
                                    recreated += 1
                                removed_vectors_total += removed_vectors
                        status.update(label="Recreate Complete", state="complete")
                    st.success(
                        f"Recreated {recreated}/{len(sources)} source(s) with {removed_vectors_total} old vector chunks removed."
                    )
            if c_cancel.button("Cancel", key="cancel_recreate_all_btn"):
                st.session_state.confirm_recreate_all = False
        elif False:
            if queue_enabled and ingestion_queue:
                recreated = 0
                removed_vectors_total = 0
                for src in sources:
                    ok, new_src, removed_vectors, err = recreate_source(src)
                    if ok and new_src:
                        enqueue_source(new_src)
                        recreated += 1
                        removed_vectors_total += removed_vectors
                st.success(
                    f"Recreated {recreated} source(s), removed {removed_vectors_total} old vector chunks, and queued ingestion."
                )
            else:
                with st.status("Recreating all sources...", expanded=True) as status:
                    recreated = 0
                    removed_vectors_total = 0
                    for src in sources:
                        ok, new_src, removed_vectors, err = recreate_source(src)
                        if ok and new_src:
                            result = updater.update_source(new_src.source_id)
                            if result.get("status") == "success":
                                recreated += 1
                            removed_vectors_total += removed_vectors
                    status.update(label="Recreate Complete", state="complete")
                st.success(
                    f"Recreated {recreated}/{len(sources)} source(s) with {removed_vectors_total} old vector chunks removed."
                )

    with top_b:
        if st.button("Remove All Sources", type="secondary"):
            st.session_state.confirm_remove_all = True

        if st.session_state.confirm_remove_all:
            st.warning(
                "Confirm remove all sources? This will permanently delete vectors and metadata."
            )
            c_confirm, c_cancel = st.columns(2)
            if c_confirm.button("Confirm Remove All", key="confirm_remove_all_btn"):
                st.session_state.confirm_remove_all = False
                removed = 0
                removed_vectors_total = 0
                failed = 0
                for src in sources:
                    ok, removed_vectors, err = true_delete_source(src)
                    if ok:
                        removed += 1
                        removed_vectors_total += removed_vectors
                    else:
                        failed += 1
                if failed:
                    st.warning(
                        f"Deleted {removed} source(s), failed for {failed}. Removed vectors: {removed_vectors_total}."
                    )
                else:
                    st.success(
                        f"Removed {removed} source(s) with {removed_vectors_total} vector chunks."
                    )
                st.rerun()
            if c_cancel.button("Cancel", key="cancel_remove_all_btn"):
                st.session_state.confirm_remove_all = False
        elif False:
            removed = 0
            removed_vectors_total = 0
            failed = 0
            for src in sources:
                ok, removed_vectors, err = true_delete_source(src)
                if ok:
                    removed += 1
                    removed_vectors_total += removed_vectors
                else:
                    failed += 1
            if failed:
                st.warning(
                    f"Deleted {removed} source(s), failed for {failed}. Removed vectors: {removed_vectors_total}."
                )
            else:
                st.success(
                    f"Removed {removed} source(s) with {removed_vectors_total} vector chunks."
                )
            st.rerun()

    error_sources = [s for s in sources if s.status == "error"]
    if error_sources:
        if st.button("Recreate All Failed Sources", type="secondary"):
            st.session_state.confirm_recreate_failed = True

        if st.session_state.confirm_recreate_failed:
            st.warning(
                "Confirm recreate all failed sources? This will delete old vectors and metadata before re-ingestion."
            )
            c_confirm, c_cancel = st.columns(2)
            if c_confirm.button(
                "Confirm Recreate Failed", key="confirm_recreate_failed_btn"
            ):
                st.session_state.confirm_recreate_failed = False
                if queue_enabled and ingestion_queue:
                    recreated = 0
                    removed_vectors_total = 0
                    for src in error_sources:
                        ok, new_src, removed_vectors, err = recreate_source(src)
                        if ok and new_src:
                            enqueue_source(new_src)
                            recreated += 1
                            removed_vectors_total += removed_vectors
                    st.success(
                        f"Recreated {recreated} failed source(s), removed {removed_vectors_total} old vector chunks, and queued ingestion."
                    )
                else:
                    with st.status(
                        "Recreating failed sources...", expanded=True
                    ) as status:
                        recreated = 0
                        removed_vectors_total = 0
                        for src in error_sources:
                            ok, new_src, removed_vectors, err = recreate_source(src)
                            if ok and new_src:
                                result = updater.update_source(new_src.source_id)
                                if result.get("status") == "success":
                                    recreated += 1
                                removed_vectors_total += removed_vectors
                        status.update(label="Recreate Complete", state="complete")
                    st.success(
                        f"Recreated {recreated}/{len(error_sources)} failed source(s) with {removed_vectors_total} old vector chunks removed."
                    )
            if c_cancel.button("Cancel", key="cancel_recreate_failed_btn"):
                st.session_state.confirm_recreate_failed = False
        elif False:
            if queue_enabled and ingestion_queue:
                recreated = 0
                removed_vectors_total = 0
                for src in error_sources:
                    ok, new_src, removed_vectors, err = recreate_source(src)
                    if ok and new_src:
                        enqueue_source(new_src)
                        recreated += 1
                        removed_vectors_total += removed_vectors
                st.success(
                    f"Recreated {recreated} failed source(s), removed {removed_vectors_total} old vector chunks, and queued ingestion."
                )
            else:
                with st.status("Recreating failed sources...", expanded=True) as status:
                    recreated = 0
                    removed_vectors_total = 0
                    for src in error_sources:
                        ok, new_src, removed_vectors, err = recreate_source(src)
                        if ok and new_src:
                            result = updater.update_source(new_src.source_id)
                            if result.get("status") == "success":
                                recreated += 1
                            removed_vectors_total += removed_vectors
                    status.update(label="Recreate Complete", state="complete")
                st.success(
                    f"Recreated {recreated}/{len(error_sources)} failed source(s) with {removed_vectors_total} old vector chunks removed."
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

            action_a, action_b = st.columns(2)
            with action_a:
                if st.button("Recreate This Source", key=f"recreate_{s.source_id}"):
                    st.session_state[f"confirm_recreate_{s.source_id}"] = True

                if st.session_state.get(f"confirm_recreate_{s.source_id}", False):
                    st.warning(
                        "Confirm recreate this source? This will delete old vectors and metadata first."
                    )
                    c_confirm, c_cancel = st.columns(2)
                    if c_confirm.button(
                        "Confirm Recreate", key=f"confirm_recreate_btn_{s.source_id}"
                    ):
                        st.session_state[f"confirm_recreate_{s.source_id}"] = False
                        if queue_enabled and ingestion_queue:
                            ok, new_src, removed_vectors, err = recreate_source(s)
                            if ok and new_src:
                                enqueue_source(new_src)
                                st.success(
                                    f"Source recreated with {removed_vectors} old vector chunks removed and re-queued."
                                )
                                st.rerun()
                            else:
                                st.error(f"Recreate failed: {err}")
                        else:
                            ok, new_src, removed_vectors, err = recreate_source(s)
                            if ok and new_src:
                                result = updater.update_source(new_src.source_id)
                                if result.get("status") == "success":
                                    st.success(
                                        f"Source recreated with {removed_vectors} old vector chunks removed."
                                    )
                                    st.rerun()
                                else:
                                    st.error(
                                        f"Recreate ingest failed: {result.get('error', 'Unknown error')}"
                                    )
                            else:
                                st.error(f"Recreate failed: {err}")
                    if c_cancel.button(
                        "Cancel", key=f"cancel_recreate_btn_{s.source_id}"
                    ):
                        st.session_state[f"confirm_recreate_{s.source_id}"] = False
                elif False:
                    if queue_enabled and ingestion_queue:
                        ok, new_src, removed_vectors, err = recreate_source(s)
                        if ok and new_src:
                            enqueue_source(new_src)
                            st.success(
                                f"Source recreated with {removed_vectors} old vector chunks removed and re-queued."
                            )
                            st.rerun()
                        else:
                            st.error(f"Recreate failed: {err}")
                    else:
                        ok, new_src, removed_vectors, err = recreate_source(s)
                        if ok and new_src:
                            result = updater.update_source(new_src.source_id)
                            if result.get("status") == "success":
                                st.success(
                                    f"Source recreated with {removed_vectors} old vector chunks removed."
                                )
                                st.rerun()
                            else:
                                st.error(
                                    f"Recreate ingest failed: {result.get('error', 'Unknown error')}"
                                )
                        else:
                            st.error(f"Recreate failed: {err}")

            with action_b:
                if st.button("Remove This Source", key=f"remove_{s.source_id}"):
                    st.session_state[f"confirm_remove_{s.source_id}"] = True

                if st.session_state.get(f"confirm_remove_{s.source_id}", False):
                    st.warning(
                        "Confirm remove this source? This will permanently delete vectors and metadata."
                    )
                    c_confirm, c_cancel = st.columns(2)
                    if c_confirm.button(
                        "Confirm Remove", key=f"confirm_remove_btn_{s.source_id}"
                    ):
                        st.session_state[f"confirm_remove_{s.source_id}"] = False
                        ok, removed_vectors, err = true_delete_source(s)
                        if ok:
                            st.success(
                                f"Source removed with {removed_vectors} vector chunks deleted."
                            )
                            st.rerun()
                        else:
                            st.error(f"Failed to remove source: {err}")
                    if c_cancel.button(
                        "Cancel", key=f"cancel_remove_btn_{s.source_id}"
                    ):
                        st.session_state[f"confirm_remove_{s.source_id}"] = False
                elif False:
                    ok, removed_vectors, err = true_delete_source(s)
                    if ok:
                        st.success(
                            f"Source removed with {removed_vectors} vector chunks deleted."
                        )
                        st.rerun()
                    else:
                        st.error(f"Failed to remove source: {err}")
