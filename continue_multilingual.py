#!/usr/bin/env python3
"""
Continue the multilingual re-ingestion that was interrupted at 3500/4535.
Extracts remaining docs from backup, adds to partial new index.
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.rag.vector_store import VectorStoreManager

OLD_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
NEW_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
INDEX_DIR = "./data/faiss_index"
BACKUP_DIR = "./data/faiss_index_backup_english"


def main():
    print("=" * 70)
    print("CONTINUING MULTILINGUAL RE-INGESTION")
    print("=" * 70)

    # 1. Check current partial index
    print("\n[1] Loading current partial multilingual index...")
    new_vs = VectorStoreManager(persist_directory=INDEX_DIR, embedding_model=NEW_MODEL)
    new_vs.load_vectorstore()
    current_count = new_vs.vectorstore.index.ntotal
    print(f"  Current index has {current_count} vectors")

    # 2. Load backup to extract ALL docs
    print("\n[2] Loading backup English index to get all docs...")
    old_vs = VectorStoreManager(persist_directory=BACKUP_DIR, embedding_model=OLD_MODEL)
    old_vs.load_vectorstore()
    all_docs = list(old_vs.vectorstore.docstore._dict.values())
    total = len(all_docs)
    print(f"  Backup has {total} documents total")

    # Free old model memory
    del old_vs

    # 3. Add remaining docs
    remaining = all_docs[current_count:]
    print(
        f"\n[3] Adding {len(remaining)} remaining documents (from {current_count} to {total})..."
    )

    BATCH_SIZE = 500
    t0 = time.time()
    for i in range(0, len(remaining), BATCH_SIZE):
        batch = remaining[i : i + BATCH_SIZE]
        new_vs.add_documents(batch)
        done = min(i + BATCH_SIZE, len(remaining))
        elapsed = time.time() - t0
        print(
            f"    {current_count + done}/{total} docs total ({done}/{len(remaining)} remaining, {elapsed:.0f}s)"
        )

    # 4. Verify
    final_count = new_vs.vectorstore.index.ntotal
    print(f"\n[4] VERIFICATION: Index now has {final_count} vectors (expected {total})")
    assert final_count == total, f"Mismatch! {final_count} != {total}"

    # 5. Quick test
    print("\n[5] Quick cross-language search test:")
    test_queries = [
        "Newton's laws of motion",
        "hydrogen atom wavelength transition",
        "mitochondrial electron transport chain",
    ]
    for query in test_queries:
        results = new_vs.similarity_search_with_score(query, k=5)
        yt_results = [
            (d, float(s))
            for d, s in results
            if d.metadata.get("source_type") == "youtube"
        ]
        if yt_results:
            best_doc, best_score = yt_results[0]
            title = best_doc.metadata.get("title", "?")[:40]
            snippet = best_doc.page_content[:80]
            print(f"  '{query}' -> score={best_score:.3f} | {title}")
            print(f"    snippet: {snippet}...")
        else:
            print(f"  '{query}' -> (no YouTube matches in top 5)")

    print(f"\n{'=' * 70}")
    print(f"DONE — Index complete: {final_count} docs with multilingual embeddings")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
