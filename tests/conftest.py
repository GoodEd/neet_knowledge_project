import os
import shutil

def pytest_configure(config):
    """Set up test environment variables to isolate storage before any tests run."""
    # Force the app to use the isolated test_data directory
    os.environ["DATA_DIR"] = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_data"))
    
    # Optional: ensure it's clean before starting
    test_faiss_dir = os.path.join(os.environ["DATA_DIR"], "faiss_index")
    if os.path.exists(test_faiss_dir):
        shutil.rmtree(test_faiss_dir)
