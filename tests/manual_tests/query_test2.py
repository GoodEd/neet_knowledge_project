import sys, os
import logging

logging.getLogger('httpx').setLevel(logging.WARNING)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.rag.neet_rag import NEETRAG

rag = NEETRAG(llm_provider='openai', llm_model='google/gemini-2.0-flash-001')
res = rag.vector_store.similarity_search("vernier callipers", k=5)
print("RAW VECTOR SEARCH RESULTS:")
for i, doc in enumerate(res):
    print(f"\n--- Result {i+1} ---")
    print(f"Metadata: {doc.metadata}")
    print(f"Content: {doc.page_content[:200]}")
