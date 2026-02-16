import streamlit as st
import os
import sys
from dotenv import load_dotenv

# Ensure we can import from src
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.rag.neet_rag import NEETRAG
from src.utils.content_manager import ContentSourceManager, AutoUpdater

# Load environment variables
load_dotenv()

# Page config
st.set_page_config(page_title="NEET Knowledge RAG", layout="wide")


# Initialize RAG System (Cached)
@st.cache_resource
def get_rag_system():
    # Use OpenAI/OpenRouter config from env
    llm_provider = "openai"  # Default to compatible provider
    llm_model = os.getenv("OPENAI_MODEL_NAME", "google/gemini-2.0-flash-001")
    base_url = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")

    return NEETRAG(
        llm_provider=llm_provider, llm_model=llm_model, llm_base_url=base_url
    )


rag = get_rag_system()
source_manager = ContentSourceManager()
updater = AutoUpdater(source_manager, rag)

# Sidebar - Manage Sources
with st.sidebar:
    st.header("Manage Sources")

    # Add new source
    st.subheader("Add Content")
    source_url = st.text_input("YouTube URL or PDF Path")
    source_title = st.text_input("Title (Optional)")

    col1, col2 = st.columns(2)
    if col1.button("Add YouTube"):
        if source_url:
            source_manager.add_youtube(source_url, source_title or None)
            st.success("YouTube source added!")

    if col2.button("Add PDF"):
        if source_url:
            source_manager.add_pdf(source_url, source_title or None)
            st.success("PDF source added!")

    st.divider()

    # Update button
    if st.button("🔄 Update/Ingest All Sources"):
        with st.status("Processing sources...", expanded=True) as status:
            results = updater.update_all()
            for res in results:
                if res.get("status") == "success":
                    st.write(f"✅ {res.get('source_id')}: Updated")
                else:
                    st.write(f"❌ {res.get('source_id')}: Failed - {res.get('error')}")
            status.update(label="Update Complete!", state="complete")

    # List sources
    st.subheader("Existing Sources")
    sources = source_manager.get_all_sources()
    for s in sources:
        status_icon = (
            "🟢" if s.status == "active" else "🔴" if s.status == "error" else "⚪"
        )
        with st.expander(f"{status_icon} {s.title}"):
            st.write(f"**URL:** {s.url}")
            st.write(f"**Type:** {s.source_type}")
            st.write(f"**Last Updated:** {s.last_updated}")
            if s.error_message:
                st.error(s.error_message)

# Main Chat Interface
st.title("📚 NEET Knowledge Assistant")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# User Input
if prompt := st.chat_input("Ask a question about NEET 2025..."):
    # Display user message
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Generate response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            response = rag.query(prompt)

            answer = response.get("answer", "No answer generated.")
            sources = response.get("sources", [])

            st.markdown(answer)

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
                                    f"**Source {idx + 1}** :tv: "
                                    f"[{display_title} @ {ts_label}]({src['timestamp_url']})"
                                )
                            else:
                                st.markdown(
                                    f"**Source {idx + 1}** :tv: "
                                    f"[{display_title}]({src['timestamp_url']})"
                                )
                        else:
                            st.markdown(
                                f"**Source {idx + 1} ({content_type}):** {source_url}"
                            )
                        st.text(src.get("content"))

    st.session_state.messages.append({"role": "assistant", "content": answer})
