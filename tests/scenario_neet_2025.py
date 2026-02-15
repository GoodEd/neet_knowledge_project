import os
import re
from src.rag.neet_rag import NEETRAG
from dotenv import load_dotenv

load_dotenv()


def run_test():
    rag = NEETRAG(
        llm_provider="openai",
        llm_base_url=os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
        llm_model=os.getenv("OPENAI_MODEL_NAME", "google/gemini-2.0-flash-001"),
        embedding_provider="huggingface",
    )

    # Read questions
    with open("neet_2025_questions.txt", "r") as f:
        content = f.read()

    # Extract questions (simple regex for Q1, Q2 etc)
    questions = re.findall(r"(Q\d+\..*?)(?=\nQ\d|\Z)", content, re.DOTALL)

    print(f"Found {len(questions)} questions in the paper.")

    print("\n--- Starting Search for Question Locations ---\n")

    for q_block in questions:
        # Extract just the first line as the query
        q_lines = q_block.strip().split("\n")
        query = q_lines[0]  # e.g., "Q1. A body of mass..."

        print(f"Searching for: {query[:50]}...")

        try:
            # We want to find *where* this is discussed.
            # Using rag.query will generate an answer, but we want the source metadata.
            # So we will use the retriever directly if exposed, or parse the result.

            # Since the current CLI/RAG implementation returns a string answer which *should* include citations,
            # we will run the query and check the output.

            result = rag.query(query)

            answer_text = result.get("answer", "")
            print(f"Answer: {answer_text[:200]}...")  # Print first 200 chars of answer

            # In a real system, we'd inspect rag.retriever.get_relevant_documents(query)
            # Let's do that to get exact timestamps.
            docs = rag.vector_manager.similarity_search(query, k=3)

            print("  Found in Sources:")

            for doc in docs:
                meta = doc.metadata
                source_type = meta.get("source_type", "unknown")
                title = meta.get("title", "No Title")

                if source_type == "youtube":
                    start_time = meta.get("start_time", 0)
                    url = meta.get("url", "unknown")
                    # Construct timestamped URL
                    ts_url = f"{url}&t={int(start_time)}s"
                    print(f"    - [YouTube] {title}: {ts_url} (Time: {start_time}s)")
                else:
                    print(f"    - [{source_type}] {title}")

        except Exception as e:
            print(f"    Error processing question: {e}")

        print("-" * 30)


if __name__ == "__main__":
    run_test()
