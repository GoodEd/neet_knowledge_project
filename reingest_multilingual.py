#!/usr/bin/env python3
"""
Re-ingest ALL documents (PDF + YouTube) with the multilingual embedding model.

Strategy: Extract all 4,535 documents from the existing FAISS docstore (which was
built with the English-only all-MiniLM-L6-v2 model), then rebuild the index using
paraphrase-multilingual-MiniLM-L12-v2 (384 dims, 50+ languages including Hindi).

This avoids re-fetching YouTube transcripts (which risks rate limiting).
"""

import sys
import os
import shutil
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langchain_core.documents import Document
from src.rag.vector_store import VectorStoreManager

OLD_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
NEW_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
INDEX_DIR = "./data/faiss_index"
BACKUP_DIR = "./data/faiss_index_backup_english"


def extract_all_docs_from_faiss(vs):
    """Extract all documents from a loaded FAISS vectorstore's docstore."""
    docstore = vs.vectorstore.docstore
    # FAISS docstore uses InMemoryDocstore with _dict
    all_docs = list(docstore._dict.values())
    return all_docs


def main():
    print("=" * 70)
    print("MULTILINGUAL RE-INGESTION")
    print(f"Old model: {OLD_MODEL}")
    print(f"New model: {NEW_MODEL}")
    print("=" * 70)

    # Step 1: Load old index with old model to extract documents
    print("\n[1/5] Loading old FAISS index with English model to extract documents...")
    old_vs = VectorStoreManager(
        persist_directory=INDEX_DIR,
        embedding_model=OLD_MODEL,
    )
    old_vs.load_vectorstore()
    old_total = old_vs.vectorstore.index.ntotal
    print(f"  Old index has {old_total} vectors")

    # Step 2: Extract all documents
    print("\n[2/5] Extracting all documents from docstore...")
    all_docs = extract_all_docs_from_faiss(old_vs)
    print(f"  Extracted {len(all_docs)} documents")

    # Classify docs
    pdf_docs = [d for d in all_docs if d.metadata.get("source_type") == "pdf"]
    yt_docs = [d for d in all_docs if d.metadata.get("source_type") == "youtube"]
    other_docs = [
        d for d in all_docs if d.metadata.get("source_type") not in ("pdf", "youtube")
    ]
    print(f"  PDF documents:     {len(pdf_docs)}")
    print(f"  YouTube documents: {len(yt_docs)}")
    if other_docs:
        print(f"  Other documents:   {len(other_docs)}")

    # Count unique videos
    unique_videos = set()
    for d in yt_docs:
        vid = d.metadata.get("video_id", "")
        if vid:
            unique_videos.add(vid)
    print(f"  Unique YouTube videos: {len(unique_videos)}")

    # Free old model from memory
    del old_vs

    # Step 3: Backup old index
    print(f"\n[3/5] Backing up old index to {BACKUP_DIR}...")
    if os.path.exists(BACKUP_DIR):
        shutil.rmtree(BACKUP_DIR)
    shutil.copytree(INDEX_DIR, BACKUP_DIR)
    print(f"  Backup complete")

    # Remove old index
    shutil.rmtree(INDEX_DIR)
    print(f"  Removed old index at {INDEX_DIR}")

    # Step 4: Create new index with multilingual model
    print(f"\n[4/5] Creating new FAISS index with multilingual model...")
    print(f"  Loading model: {NEW_MODEL}")
    t0 = time.time()
    new_vs = VectorStoreManager(
        persist_directory=INDEX_DIR,
        embedding_model=NEW_MODEL,
    )
    t1 = time.time()
    print(f"  Model loaded in {t1 - t0:.1f}s")

    # Ingest all docs in batches to show progress
    BATCH_SIZE = 500
    total = len(all_docs)
    print(f"  Embedding and indexing {total} documents (batch size {BATCH_SIZE})...")

    for i in range(0, total, BATCH_SIZE):
        batch = all_docs[i : i + BATCH_SIZE]
        if i == 0:
            new_vs.create_vectorstore(batch)
        else:
            new_vs.add_documents(batch)
        elapsed = time.time() - t1
        done = min(i + BATCH_SIZE, total)
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        print(
            f"    {done}/{total} docs indexed ({elapsed:.0f}s elapsed, ETA {eta:.0f}s)"
        )

    t2 = time.time()
    print(f"  Indexing complete in {t2 - t1:.1f}s")

    # Step 5: Verify
    print(f"\n[5/5] Verifying new index...")
    new_vs_check = VectorStoreManager(
        persist_directory=INDEX_DIR,
        embedding_model=NEW_MODEL,
    )
    new_vs_check.load_vectorstore()
    new_total = new_vs_check.vectorstore.index.ntotal
    print(f"  New index has {new_total} vectors (expected {total})")
    assert new_total == total, f"Mismatch! Expected {total}, got {new_total}"

    # Quick test: English query against Hindi transcripts
    print("\n  Quick cross-language test:")
    test_queries = [
        "Newton's laws of motion",
        "hydrogen atom wavelength transition",
        "mitochondrial electron transport chain",
        "acceleration due to gravity",
        "chemical bonding hybridization",
    ]
    for query in test_queries:
        results = new_vs_check.similarity_search_with_score(query, k=5)
        yt_results = [
            (d, float(s))
            for d, s in results
            if d.metadata.get("source_type") == "youtube"
        ]
        if yt_results:
            best_doc, best_score = yt_results[0]
            vid = best_doc.metadata.get("video_id", "?")
            title = best_doc.metadata.get("title", "?")[:40]
            snippet = best_doc.page_content[:60]
            print(f"    '{query}' -> score={best_score:.3f} | {title} | {snippet}...")
        else:
            pdf_best = results[0] if results else None
            if pdf_best:
                print(f"    '{query}' -> (PDF only, score={float(pdf_best[1]):.3f})")
            else:
                print(f"    '{query}' -> no results")

    print(f"\n{'=' * 70}")
    print("MULTILINGUAL RE-INGESTION COMPLETE")
    print(f"  Model:      {NEW_MODEL}")
    print(f"  Documents:  {new_total}")
    print(f"  Index:      {INDEX_DIR}")
    print(f"  Backup:     {BACKUP_DIR}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
