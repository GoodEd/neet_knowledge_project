import sys
import os
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.rag.neet_rag import NEETRAG

load_dotenv()
rag = NEETRAG(llm_provider='openai', llm_model='google/gemini-2.0-flash-001')

print("Executing query: 'vernier callipers'")
results = rag.query("vernier callipers")

print("\n--- Answer ---")
print(results.get("answer", ""))

print("\n--- Sources ---")
for idx, src in enumerate(results.get("sources", [])):
    print(f"\nSource {idx+1}: {src.get('source')} ({src.get('content_type')})")
    print(f"Timestamp: {src.get('timestamp_label', 'N/A')}")
    print(f"Content: {src.get('content')[:150]}...")
