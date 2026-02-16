#!/usr/bin/env python3
"""
Re-ingest NEET 2025 PDF with correct subject classification.
Physics: Q1-45, Chemistry: Q46-90, Biology: Q91-180
"""

import re
import sys
import os
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langchain_core.documents import Document
from src.rag.vector_store import VectorStoreManager

SUBJECT_RANGES = [
    (1, 45, "PHYSICS"),
    (46, 90, "CHEMISTRY"),
    (91, 180, "BIOLOGY"),
]


def get_subject(q_num: int) -> str:
    for start, end, subject in SUBJECT_RANGES:
        if start <= q_num <= end:
            return subject
    return "UNKNOWN"


def extract_questions(text: str) -> list[dict]:
    header_pattern = (
        r"VETRII NEET GATEWAY\s*\n.*?NEET UG.*?\n.*?\d{10}\|\d{10}\|\d{10}\s*\n?"
    )
    text = re.sub(header_pattern, "\n", text)
    text = re.sub(r"\n\s*PHYSICS\s*\n", "\n", text)
    text = re.sub(r"\n\s*CHEMISTRY\s*\n", "\n", text)
    text = re.sub(r"\n\s*BIOLOGY\s*\n", "\n", text)

    q_positions = []
    for m in re.finditer(r"(?:^|\n)\s*(\d{1,3})\.\s", text):
        q_num = int(m.group(1))
        if 1 <= q_num <= 180:
            q_positions.append((q_num, m.start()))

    seen = set()
    unique_positions = []
    for q_num, pos in q_positions:
        if q_num not in seen:
            seen.add(q_num)
            unique_positions.append((q_num, pos))

    unique_positions.sort(key=lambda x: x[1])

    questions = []
    for idx, (q_num, start_pos) in enumerate(unique_positions):
        if idx + 1 < len(unique_positions):
            end_pos = unique_positions[idx + 1][1]
        else:
            end_pos = len(text)

        q_text = text[start_pos:end_pos].strip()
        q_text = re.sub(r"^\d{1,3}\.\s*", "", q_text).strip()

        if q_text:
            questions.append(
                {
                    "number": q_num,
                    "text": q_text,
                    "subject": get_subject(q_num),
                }
            )

    return questions


def main():
    text_path = "data/neet_2025_paper_text.txt"
    if not os.path.exists(text_path):
        print(f"ERROR: {text_path} not found")
        sys.exit(1)

    with open(text_path, "r") as f:
        raw_text = f.read()

    questions = extract_questions(raw_text)
    print(f"Extracted {len(questions)} questions")

    subject_counts = {}
    for q in questions:
        subject_counts[q["subject"]] = subject_counts.get(q["subject"], 0) + 1
    print(f"Subject distribution: {subject_counts}")

    documents = []
    for q in questions:
        content = f"NEET 2025 Question {q['number']} ({q['subject']})\n\n{q['text']}"
        doc = Document(
            page_content=content,
            metadata={
                "source": "neet_2025_paper.pdf",
                "source_type": "pdf",
                "exam": "NEET 2025",
                "question_number": q["number"],
                "subject": q["subject"],
                "paper_code": "45 Narmada",
            },
        )
        documents.append(doc)

    index_dir = "./data/faiss_index"
    if os.path.exists(index_dir):
        shutil.rmtree(index_dir)
        print(f"Cleared old FAISS index at {index_dir}")

    vs = VectorStoreManager()
    vs.create_vectorstore(documents)
    print(f"Created new FAISS index with {len(documents)} documents")

    test_queries = [
        ("Newton's laws", "PHYSICS"),
        ("hydrogen wavelength", "CHEMISTRY"),
        ("mitochondrial electron transport", "BIOLOGY"),
    ]

    for query, expected_subject in test_queries:
        results = vs.similarity_search(query, k=1)
        if results:
            doc = results[0]
            actual = doc.metadata.get("subject", "?")
            q_num = doc.metadata.get("question_number", "?")
            status = "OK" if actual == expected_subject else "WRONG"
            print(f"  [{status}] '{query}' -> Q{q_num} ({actual})")
        else:
            print(f"  [FAIL] '{query}' -> no results")

    print("\nPDF re-ingestion complete.")


if __name__ == "__main__":
    main()
