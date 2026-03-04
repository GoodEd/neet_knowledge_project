import sys
import os
import unittest
from dotenv import load_dotenv

# Ensure we can import from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Force test data directory
os.environ["DATA_DIR"] = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_data"))

from src.rag.neet_rag import NEETRAG

class TestNEETRAGPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Initialize RAG system once for all tests."""
        load_dotenv()
        print("\nInitializing RAG system for tests using ISOLATED storage...")
        
        # We suppress httpx logs so they don't clutter the test output
        import logging
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("sentence_transformers").setLevel(logging.WARNING)

        try:
            cls.rag = NEETRAG()
            # If the isolated vector store doesn't exist, we skip tests or we need to mock it.
            # For this test, we assume the test suite will ingest a small sample first or we 
            # fall back to the main data dir just for reading if test_data is empty (for testing logic without re-ingesting).
            
            # Note: Because the prompt asked to isolate it, if 'test_data/faiss_index' is empty,
            # this will initialize a fresh empty index. 
            cls.rag.vector_manager.load_vectorstore()
        except Exception as e:
            print(f"\nCRITICAL: Failed to load vector store. Error: {e}")
            sys.exit(1)

    def test_initialization(self):
        """Test if the isolated RAG pipeline initializes without crashing."""
        self.assertIsNotNone(self.rag)

if __name__ == '__main__':
    unittest.main(verbosity=2)
