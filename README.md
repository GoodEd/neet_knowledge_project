# NEET Knowledge RAG

A comprehensive Retrieval-Augmented Generation (RAG) system for NEET aspirants in India. Supports multiple content types including PDFs, scanned PDFs, YouTube videos, regular videos, text notes, and HTML pages.

## Features

- **Multi-format Support**: Process PDFs, scanned PDFs, YouTube videos, audio/video files, text files, Markdown, and HTML
- **Flexible RAG Pipeline**: Uses LangChain for robust document processing and retrieval
- **Multiple Embedding Options**: HuggingFace (free), OpenAI (paid)
- **Multiple LLM Options**: Ollama (free/local), OpenAI, Anthropic
- **Vector Storage**: ChromaDB for efficient similarity search
- **Easy CLI**: Simple commands for ingestion, querying, and interaction

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Content        │────▶│  Processing      │────▶│  Vector Store   │
│  Sources        │     │  (Chunking)      │     │  (ChromaDB)     │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                           │
                                                           ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  User Query     │────▶│  Retrieval       │────▶│  LLM Response   │
│                 │     │  (Similarity)    │     │  (Generation)   │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd neet_knowledge_project

# Install dependencies
pip install -r requirements.txt

# Optional: Install additional dependencies
# For OCR support
pip install pytesseract

# For video transcription
pip install openai-whisper

# For YouTube support
pip install youtube-transcript-api

# For PDF support
pip install pymupdf pypdf
```

## Quick Start

### 1. Ingest Content

```bash
# Ingest a text file
python -m src.main ingest ./tests/test_data/text/physics_notes.txt

# Ingest multiple files
python -m src.main ingest ./notes/*.txt

# Ingest a YouTube video
python -m src.main ingest "https://www.youtube.com/watch?v=..."

# Ingest an HTML page
python -m src.main ingest ./notes/biology.html
```

### 2. Query the Knowledge Base

```bash
# Ask a question
python -m src.main query "What are Newton's laws of motion?"

# With custom top-k results
python -m src.main query "Explain photosynthesis" --top-k 3
```

### 3. Interactive Chat

```bash
# Start interactive chat mode
python -m src.main chat
```

### 4. Check Statistics

```bash
# View system statistics
python -m src.main stats
```

## Python API Usage

```python
from src.rag import NEETRAG

# Initialize RAG system
rag = NEETRAG(
    persist_directory="./data/chroma_db",
    embedding_provider="huggingface",
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    llm_provider="ollama",
    llm_model="llama3.2"
)

# Ingest content
rag.ingest_content([
    "./notes/physics.txt",
    "./notes/chemistry.md",
    "https://youtube.com/watch?v=..."
])

# Query
result = rag.query("What is the formula for kinetic energy?")
print(result["answer"])
```

## Supported Content Types

| Type | Extension | Processing |
|------|-----------|------------|
| Text | .txt | Direct text extraction |
| Markdown | .md, .markdown | Section-based extraction |
| HTML | .html, .htm | Main content extraction |
| PDF | .pdf | Text extraction + OCR |
| YouTube | URL | Transcript extraction |
| Video | .mp4, .avi, .mov | Audio transcription (with Whisper) |
| Audio | .mp3, .wav | Speech-to-text |

## Configuration

Edit `config.yaml` to customize:

```yaml
vector_db:
  type: chromadb
  persist_dir: ./data/chroma_db

embedding:
  provider: huggingface
  model: sentence-transformers/all-MiniLM-L6-v2

llm:
  provider: ollama
  model: llama3.2

processing:
  chunk_size: 1000
  chunk_overlap: 200

rag:
  retrieval_top_k: 5
  similarity_threshold: 0.7
```

## Provider Options

### Embeddings

| Provider | Cost | Quality | Setup |
|----------|------|---------|-------|
| HuggingFace | Free | Good | None |
| OpenAI | Paid | Excellent | API key |

### LLM

| Provider | Cost | Quality | Setup |
|----------|------|---------|-------|
| Ollama | Free | Good | Install locally |
| OpenAI | Paid | Excellent | API key |
| Anthropic | Paid | Excellent | API key |

## Running Tests

```bash
cd tests
python test_rag.py
```

## Project Structure

```
neet_knowledge_project/
├── config.yaml              # Configuration file
├── requirements.txt         # Dependencies
├── src/
│   ├── main.py             # CLI entry point
│   ├── processors/         # Content processors
│   │   ├── pdf_processor.py
│   │   ├── youtube_processor.py
│   │   ├── text_processor.py
│   │   ├── html_processor.py
│   │   ├── video_processor.py
│   │   └── unified.py
│   ├── rag/                # RAG system
│   │   ├── vector_store.py
│   │   ├── llm_manager.py
│   │   └── neet_rag.py
│   └── utils/
│       └── config.py
├── tests/
│   ├── test_rag.py
│   └── test_data/
│       ├── text/
│       ├── html/
│       └── pdf/
└── data/
    └── chroma_db/         # Vector database
```

## Environment Variables

```bash
# For OpenAI embeddings/LLM
export OPENAI_API_KEY=your_key_here

# For Anthropic
export ANTHROPIC_API_KEY=your_key_here

# For Ollama (if using custom URL)
export OLLAMA_BASE_URL=http://localhost:11434
```

## Troubleshooting

### No content found
- Ensure you've ingested content first using `ingest` command

### LLM not responding
- If using Ollama, ensure it's running: `ollama serve`
- If using OpenAI, check your API key

### Embedding errors
- Ensure sentence-transformers is installed
- For CPU, the default model works well

## License

MIT License

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.
