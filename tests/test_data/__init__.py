import os

TEST_DATA_DIR = os.path.dirname(os.path.abspath(__file__))

TEXT_FILES = [
    os.path.join(TEST_DATA_DIR, "text/physics_notes.txt"),
    os.path.join(TEST_DATA_DIR, "text/chemistry_notes.md"),
]

HTML_FILES = [
    os.path.join(TEST_DATA_DIR, "html/biology_cell.html"),
]

YOUTUBE_URLS = [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
]

CONFIG = {
    "test_chunk_size": 500,
    "test_chunk_overlap": 100,
    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
    "collection_name": "neet_test",
}
