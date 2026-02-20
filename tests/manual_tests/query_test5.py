import sys, os
from src.rag.vector_store import VectorStoreManager

vs = VectorStoreManager()
vs.load_vectorstore()

results = vs.similarity_search("vernier callipers", k=20)
for doc in results:
    if "vernier" in doc.page_content.lower() or "calliper" in doc.page_content.lower():
        print("FOUND MATCH!")
        print(doc.page_content)
print("Finished searching 20 docs for keyword.")
