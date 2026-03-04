import sys, os
import logging

# Mute noisy logs
logging.getLogger('httpx').setLevel(logging.ERROR)
logging.getLogger('sentence_transformers').setLevel(logging.ERROR)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.rag.neet_rag import NEETRAG

print("Loading RAG and testing 'vernier callipers'...")
rag = NEETRAG()
rag.vector_manager.load_vectorstore()
res = rag.vector_manager.similarity_search('vernier callipers', k=5)

print('\n+++ SEARCH RESULTS +++')
for i, doc in enumerate(res):
    print(f'\n--- Result {i+1} ---')
    print(f'Metadata: {doc.metadata}')
    print(f'Content: {doc.page_content[:300]}')
