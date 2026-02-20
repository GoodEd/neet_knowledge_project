import sys
import os
import unittest
from dotenv import load_dotenv

# Ensure we can import from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.rag.neet_rag import NEETRAG

class TestNEETRAGPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Initialize RAG system once for all tests."""
        load_dotenv()
        print("\nInitializing RAG system for tests...")
        
        # We suppress httpx logs so they don't clutter the test output
        import logging
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("sentence_transformers").setLevel(logging.WARNING)

        try:
            cls.rag = NEETRAG()
            cls.rag.vector_manager.load_vectorstore()
        except Exception as e:
            print(f"\nCRITICAL: Failed to load vector store. Did you ingest data first? Error: {e}")
            sys.exit(1)

    def test_physics_retrieval(self):
        """Test if it can retrieve physics concepts correctly (e.g., Vernier callipers)."""
        query = "How do you calculate the measured diameter using Vernier callipers with zero error?"
        results = self.rag.vector_manager.similarity_search(query, k=3)
        
        # Check if we got results
        self.assertTrue(len(results) > 0, "No results returned for physics query.")
        
        # Check if the content contains relevant keywords
        content = " ".join([doc.page_content.lower() for doc in results])
        
        # We expect at least one of these words in a good chunk about vernier callipers
        keywords = ["vernier", "calliper", "scale", "zero", "error", "diameter", "least count", "reading"]
        matches = sum(1 for word in keywords if word in content)
        
        self.assertTrue(matches >= 2, f"Poor retrieval for Vernier callipers. Content found: {content[:200]}...")

    def test_biology_retrieval(self):
        """Test retrieval for biology concepts."""
        query = "What is the function of mitochondria?"
        results = self.rag.vector_manager.similarity_search(query, k=3)
        
        self.assertTrue(len(results) > 0)
        content = " ".join([doc.page_content.lower() for doc in results])
        
        # Sometimes transliterated as "माइटोकांड्रिया" (Mitochondria) in Hindi
        keywords = ["mitochondria", "cell", "energy", "atp", "powerhouse", "माइटोकांड्रिया"]
        matches = sum(1 for word in keywords if word in content)
        
        self.assertTrue(matches >= 1, "Failed to retrieve relevant biology content.")

    def test_hindi_multilingual_retrieval(self):
        """Test if the multilingual embedding model retrieves Hindi content accurately."""
        query = "हाइड्रोजन के समस्थानिक (Isotopes of Hydrogen)"
        results = self.rag.vector_manager.similarity_search(query, k=3)
        
        self.assertTrue(len(results) > 0)
        content = " ".join([doc.page_content for doc in results])
        
        # Check for Hindi keywords or related English terms
        keywords = ["हाइड्रोजन", "hydrogen", "isotope", "समस्थानिक", "tritium", "deuterium", "प्रोटियम"]
        matches = sum(1 for word in keywords if word in content.lower())
        
        self.assertTrue(matches >= 1, f"Failed multilingual retrieval. Found: {content[:200]}...")

    def test_end_to_end_generation(self):
        """Test the full RAG pipeline (Retrieval + LLM Generation)."""
        # This tests if the LLM is connected and can generate a response based on context
        query = "What is the formula for Force according to Newton's Second Law?"
        response = self.rag.query(query)
        
        self.assertIn("answer", response)
        self.assertIn("sources", response)
        
        answer = response["answer"].lower()
        self.assertTrue(len(answer) > 10, "LLM generated an empty or too short response.")
        
        # The LLM should mention F=ma or mass and acceleration
        self.assertTrue("f=ma" in answer.replace(" ", "") or ("mass" in answer and "acceleration" in answer), 
                        f"LLM answer did not contain expected physics logic. Answer: {answer}")

if __name__ == '__main__':
    unittest.main(verbosity=2)
