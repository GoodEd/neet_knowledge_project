import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
import tempfile
import shutil


class TestProcessors(unittest.TestCase):
    def setUp(self):
        from src.processors import TextProcessor, MarkdownProcessor, HTMLProcessor

        self.text_processor = TextProcessor()
        self.markdown_processor = MarkdownProcessor()
        self.html_processor = HTMLProcessor()

        self.test_data_dir = os.path.join(os.path.dirname(__file__), "test_data")

    def test_text_processor(self):
        text_file = os.path.join(self.test_data_dir, "text/physics_notes.txt")

        if not os.path.exists(text_file):
            self.skipTest(f"Test file not found: {text_file}")

        result = self.text_processor.process(text_file)

        self.assertIn("documents", result)
        self.assertGreater(len(result["documents"]), 0)
        self.assertIn("source", result)

    def test_markdown_processor(self):
        md_file = os.path.join(self.test_data_dir, "text/chemistry_notes.md")

        if not os.path.exists(md_file):
            self.skipTest(f"Test file not found: {md_file}")

        result = self.markdown_processor.process(md_file)

        self.assertIn("documents", result)
        self.assertGreater(len(result["documents"]), 0)

    def test_html_processor(self):
        html_file = os.path.join(self.test_data_dir, "html/biology_cell.html")

        if not os.path.exists(html_file):
            self.skipTest(f"Test file not found: {html_file}")

        result = self.html_processor.process(html_file)

        self.assertIn("documents", result)
        self.assertGreater(len(result["documents"]), 0)
        self.assertIn("title", result)

    def test_text_raw_processing(self):
        result = self.text_processor.process_raw(
            "This is a test content about Newton's laws of motion.", "test_source"
        )

        self.assertIn("documents", result)
        self.assertEqual(
            result["documents"][0]["content"],
            "This is a test content about Newton's laws of motion.",
        )

    def test_content_chunker(self):
        from src.processors import DocumentChunker

        chunker = DocumentChunker(chunk_size=100, chunk_overlap=20)

        docs = [
            {
                "content": "This is a long piece of content that needs to be split into smaller chunks for better processing in the RAG system. "
                * 10,
                "source": "test.txt",
                "content_type": "text",
                "timestamp": "2024-01-01",
            }
        ]

        chunked = chunker.chunk_documents(docs)

        self.assertGreater(len(chunked), 1)
        for chunk in chunked:
            self.assertIn("content", chunk)
            self.assertIn("source", chunk)


class TestVectorStore(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_vectorstore_creation(self):
        from src.rag import VectorStoreManager
        from langchain_core.documents import Document

        manager = VectorStoreManager(
            persist_directory=self.test_dir,
            embedding_provider="huggingface",
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
        )

        docs = [
            Document(
                page_content="This is a test document about physics.",
                metadata={"source": "test.txt"},
            ),
            Document(
                page_content="This is about chemistry and atoms.",
                metadata={"source": "test2.txt"},
            ),
        ]

        vectorstore = manager.create_vectorstore(docs, "test_collection")

        self.assertIsNotNone(vectorstore)

    def test_similarity_search(self):
        from src.rag import VectorStoreManager
        from langchain_core.documents import Document

        manager = VectorStoreManager(
            persist_directory=self.test_dir,
            embedding_provider="huggingface",
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
        )

        docs = [
            Document(
                page_content="Newton's laws describe motion and forces.",
                metadata={"source": "physics.txt"},
            ),
            Document(
                page_content="Chemical bonds involve electron sharing.",
                metadata={"source": "chemistry.txt"},
            ),
        ]

        manager.create_vectorstore(docs, "test_search")

        results = manager.similarity_search("force and motion", k=1)

        self.assertGreater(len(results), 0)


class TestRAGSystem(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_rag_initialization(self):
        from src.rag import NEETRAG

        rag = NEETRAG(
            persist_directory=self.test_dir,
            embedding_provider="huggingface",
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            llm_provider="ollama",
            llm_model="llama3.2",
        )

        self.assertIsNotNone(rag.content_processor)
        self.assertIsNotNone(rag.vector_manager)

    def test_rag_stats(self):
        from src.rag import NEETRAG

        rag = NEETRAG(persist_directory=self.test_dir, embedding_provider="huggingface")

        stats = rag.get_stats()

        self.assertIn("llm", stats)


class TestPromptBuilder(unittest.TestCase):
    def test_build_prompt(self):
        from src.rag import RAGPromptBuilder
        from langchain_core.documents import Document

        builder = RAGPromptBuilder()

        docs = [
            Document(
                page_content="Photosynthesis is the process by which plants convert light energy into chemical energy.",
                metadata={"source": "biology.txt", "page": 1},
            )
        ]

        prompt = builder.build_prompt(
            query="What is photosynthesis?", context_docs=docs
        )

        self.assertIn("Photosynthesis", prompt)
        self.assertIn("What is photosynthesis?", prompt)

    def test_build_with_sources(self):
        from src.rag import RAGPromptBuilder
        from langchain_core.documents import Document

        builder = RAGPromptBuilder()

        docs = [
            Document(
                page_content="Mitochondria is the powerhouse of the cell.",
                metadata={"source": "bio.txt"},
            )
        ]

        prompt = builder.build_prompt(
            query="What is mitochondria?", context_docs=docs, include_sources=True
        )

        self.assertIn("bio.txt", prompt)


def run_tests():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestProcessors))
    suite.addTests(loader.loadTestsFromTestCase(TestVectorStore))
    suite.addTests(loader.loadTestsFromTestCase(TestRAGSystem))
    suite.addTests(loader.loadTestsFromTestCase(TestPromptBuilder))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
