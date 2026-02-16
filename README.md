# NEET Knowledge RAG

A comprehensive Retrieval-Augmented Generation (RAG) system for NEET aspirants in India. Supports multiple content types including PDFs, YouTube videos, text notes, and HTML pages.

## Features

- **Multi-format Support**: Process PDFs, YouTube videos, audio/video files, text files, Markdown, and HTML
- **Flexible RAG Pipeline**: Uses LangChain for robust document processing and retrieval
- **Local Embeddings**: HuggingFace `all-MiniLM-L6-v2` (free, no API key needed)
- **LLM via OpenRouter**: Gemini Flash 2.0 (or any OpenAI-compatible provider)
- **Vector Storage**: FAISS for efficient similarity search
- **YouTube Audio Fallback**: When subtitles are blocked, downloads audio and transcribes via Gemini multimodal
- **Streamlit Frontend**: Web UI for managing sources and chatting with your knowledge base
- **CLI**: Full command-line interface for ingestion, querying, and source management

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Content         │────▶│  Processing      │────▶│  Vector Store   │
│  Sources         │     │  (Chunking)      │     │  (FAISS)        │
│  (YT/PDF/Text)   │     └──────────────────┘     └────────┬────────┘
└─────────────────┘                                         │
                                                            ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  User Query      │────▶│  Retrieval       │────▶│  LLM Response   │
│  (CLI/Streamlit) │     │  (Similarity)    │     │  (Generation)   │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd neet_knowledge_project

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys
```

## Configuration

Edit `.env` with your API keys:

```bash
# Required: OpenRouter or OpenAI API key
OPENAI_API_KEY=sk-or-v1-your-key-here
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL_NAME=google/gemini-2.0-flash-001

# Optional: YouTube Data API for better metadata
YOUTUBE_API_KEY=your-youtube-api-key
```

## Quick Start

### Option 1: Streamlit Web UI (Recommended for Demo)

```bash
streamlit run app.py
```

This opens a web interface where you can:
- Add YouTube URLs or PDF paths via the sidebar
- Click "Update/Ingest All Sources" to process them
- Chat with your knowledge base in the main panel

### Option 2: CLI

```bash
# Ingest test data (text files)
python -m src.main ingest ./tests/test_data/text/physics_notes.txt
python -m src.main ingest ./tests/test_data/text/chemistry_notes.md
python -m src.main ingest ./tests/test_data/html/biology_cell.html

# Ingest a YouTube video
python -m src.main ingest "https://www.youtube.com/watch?v=VIDEO_ID"

# Query the knowledge base
python -m src.main query "What are Newton's laws of motion?"

# Interactive chat
python -m src.main chat

# Check system stats
python -m src.main stats
```

### Source Management (CLI)

```bash
# Add a YouTube source for periodic updates
python -m src.main source add youtube "https://youtube.com/watch?v=..." --title "Physics Lecture"

# List all tracked sources
python -m src.main source list

# Update all sources that need refresh
python -m src.main source update

# Remove a source
python -m src.main source remove <source_id>
```

## Supported Content Types

| Type | Extension/Format | Processing |
|------|-----------------|------------|
| Text | .txt | Direct text extraction |
| Markdown | .md, .markdown | Section-based extraction |
| HTML | .html, .htm | Main content extraction |
| PDF | .pdf | Text extraction + OCR fallback |
| YouTube | URL | Subtitles → Audio download → Gemini transcription |
| Video | .mp4, .avi, .mov | Audio transcription |
| Audio | .mp3, .wav | Speech-to-text |

## Project Structure

```
neet_knowledge_project/
├── app.py                    # Streamlit web frontend
├── config.yaml               # Configuration file
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variable template
├── src/
│   ├── main.py              # CLI entry point
│   ├── processors/          # Content processors
│   │   ├── pdf_processor.py
│   │   ├── youtube_processor.py
│   │   ├── text_processor.py
│   │   ├── html_processor.py
│   │   ├── video_processor.py
│   │   └── unified.py       # ContentProcessor router
│   ├── rag/                 # RAG system
│   │   ├── vector_store.py  # FAISS vector store manager
│   │   ├── llm_manager.py   # LLM provider abstraction
│   │   └── neet_rag.py      # Main RAG orchestrator
│   └── utils/
│       ├── config.py        # YAML config loader
│       └── content_manager.py  # Source tracking + auto-updater
├── tests/
│   ├── test_rag.py          # Unit tests
│   └── test_data/           # Sample NEET content
│       ├── text/            # Physics & Chemistry notes
│       └── html/            # Biology notes
└── data/
    ├── sources.json         # Tracked content sources
    ├── faiss_index/         # FAISS vector database (generated)
    └── audio/               # Cached audio downloads (generated)
```

## Running Tests

```bash
python tests/test_rag.py
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenRouter or OpenAI API key |
| `OPENAI_BASE_URL` | No | API base URL (default: OpenRouter) |
| `OPENAI_MODEL_NAME` | No | LLM model (default: gemini-2.0-flash) |
| `YOUTUBE_API_KEY` | No | YouTube Data API v3 key for metadata |

## License

MIT License
