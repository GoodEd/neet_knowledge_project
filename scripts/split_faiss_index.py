#!/usr/bin/env python3
"""Split a combined FAISS index into separate youtube/ and csv/ sub-indexes.

Usage:
    # Dry-run (audit only, no writes):
    python scripts/split_faiss_index.py --source data/prod_faiss_index

    # Actual split:
    python scripts/split_faiss_index.py --source data/prod_faiss_index --execute

    # Custom output directory:
    python scripts/split_faiss_index.py --source data/prod_faiss_index --output data/split_index --execute
"""

import argparse
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from langchain_community.docstore.in_memory import InMemoryDocstore
from src.rag.vector_store import VectorStoreManager


def load_combined_index(source_dir: str) -> VectorStoreManager:
    mgr = VectorStoreManager(persist_directory=source_dir)
    mgr.load_vectorstore()
    return mgr


def audit_source_types(mgr: VectorStoreManager) -> Counter:
    doc_map = getattr(mgr.vectorstore.docstore, "_dict", {})
    return Counter(
        doc.metadata.get("source_type", "MISSING")
        for doc in doc_map.values()
        if isinstance(doc, Document)
    )


def partition_with_vectors(mgr: VectorStoreManager) -> dict:
    vs = mgr.vectorstore
    faiss_index = vs.index
    doc_map = getattr(vs.docstore, "_dict", {})
    index_to_docstore = vs.index_to_docstore_id

    total_vectors = faiss_index.ntotal
    all_vectors = faiss_index.reconstruct_n(0, total_vectors)

    buckets = {"youtube": [], "csv": [], "other": []}

    for faiss_idx in range(total_vectors):
        docstore_id = index_to_docstore.get(faiss_idx)
        if docstore_id is None:
            continue
        doc = doc_map.get(docstore_id)
        if not isinstance(doc, Document):
            continue

        vector = all_vectors[faiss_idx]
        st = doc.metadata.get("source_type", "")
        bucket_key = st if st in ("youtube", "csv") else "other"
        buckets[bucket_key].append((doc, vector))

    return buckets


def build_sub_index_from_vectors(
    doc_vector_pairs: list, output_dir: str, embeddings
) -> int:
    if not doc_vector_pairs:
        return 0

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    import faiss as faiss_lib

    dimension = doc_vector_pairs[0][1].shape[0]
    index = faiss_lib.IndexFlatL2(dimension)

    vectors = np.array([v for _, v in doc_vector_pairs], dtype=np.float32)
    index.add(vectors)

    docstore_dict = {}
    index_to_docstore_id = {}
    for i, (doc, _) in enumerate(doc_vector_pairs):
        doc_id = str(i)
        docstore_dict[doc_id] = doc
        index_to_docstore_id[i] = doc_id

    vs = FAISS(
        embedding_function=embeddings,
        index=index,
        docstore=InMemoryDocstore(docstore_dict),
        index_to_docstore_id=index_to_docstore_id,
    )
    vs.save_local(output_dir)

    verify = FAISS.load_local(
        output_dir, embeddings, allow_dangerous_deserialization=True
    )
    actual = len(getattr(verify.docstore, "_dict", {}))
    expected = len(doc_vector_pairs)
    assert actual == expected, f"Verification failed: expected {expected}, got {actual}"
    return actual


def main():
    parser = argparse.ArgumentParser(
        description="Split combined FAISS index into youtube + csv sub-indexes"
    )
    parser.add_argument(
        "--source", required=True, help="Path to combined FAISS index directory"
    )
    parser.add_argument(
        "--output", help="Output base directory (default: same as source)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the split (default: dry-run audit only)",
    )
    args = parser.parse_args()

    output_dir = args.output or args.source

    print(f"Loading combined index from: {args.source}")
    mgr = load_combined_index(args.source)

    print("\n=== Audit ===")
    counts = audit_source_types(mgr)
    total = sum(counts.values())
    for st, count in counts.most_common():
        print(f"  {st}: {count}")
    print(f"  total: {total}")

    other_count = sum(c for st, c in counts.items() if st not in ("youtube", "csv"))
    if other_count > 0:
        print(
            f"\nWARNING: {other_count} docs with unexpected source_type will be DROPPED."
        )
        print(
            "Source types:",
            {st: c for st, c in counts.items() if st not in ("youtube", "csv")},
        )

    if not args.execute:
        print("\nDry-run complete. Pass --execute to perform the split.")
        return

    print("\n=== Partitioning (with vector extraction) ===")
    t0 = time.time()
    buckets = partition_with_vectors(mgr)
    print(f"  youtube: {len(buckets['youtube'])} docs")
    print(f"  csv: {len(buckets['csv'])} docs")
    if buckets["other"]:
        print(f"  other (dropped): {len(buckets['other'])} docs")
    print(f"  Partition time: {time.time() - t0:.1f}s")

    youtube_dir = os.path.join(output_dir, "youtube")
    csv_dir = os.path.join(output_dir, "csv")

    print(f"\n=== Building YouTube index → {youtube_dir} ===")
    t0 = time.time()
    yt_count = build_sub_index_from_vectors(
        buckets["youtube"], youtube_dir, mgr.embeddings
    )
    print(f"  Done: {yt_count} docs in {time.time() - t0:.1f}s")

    print(f"\n=== Building CSV index → {csv_dir} ===")
    t0 = time.time()
    csv_count = build_sub_index_from_vectors(buckets["csv"], csv_dir, mgr.embeddings)
    print(f"  Done: {csv_count} docs in {time.time() - t0:.1f}s")

    print(f"\n=== Verification ===")
    expected_total = counts.get("youtube", 0) + counts.get("csv", 0)
    actual_total = yt_count + csv_count
    status = "PASS" if actual_total == expected_total else "FAIL"
    print(
        f"  Expected: {expected_total} (youtube={counts.get('youtube', 0)}, csv={counts.get('csv', 0)})"
    )
    print(f"  Actual:   {actual_total} (youtube={yt_count}, csv={csv_count})")
    print(f"  Status:   {status}")

    if status == "FAIL":
        sys.exit(1)

    print("\nSplit complete. Original index is untouched.")


if __name__ == "__main__":
    main()
