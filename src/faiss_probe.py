#!/usr/bin/env python3
import argparse
import os
import re
from typing import Any, Dict, List, Optional, Tuple


def score_to_similarity(score: float) -> float:
    try:
        return 1.0 / (1.0 + float(score))
    except Exception:
        return 0.0


def dedupe_docs(docs: List[Any]) -> List[Any]:
    deduped: List[Any] = []
    seen = set()
    for doc in docs:
        source_type = doc.metadata.get("source_type") or doc.metadata.get(
            "content_type", ""
        )
        if source_type == "youtube":
            video_id = doc.metadata.get("video_id", "")
            start_time = int(float(doc.metadata.get("start_time", 0) or 0))
            track_id = doc.metadata.get("track_id", "")
            key = ("youtube", video_id, start_time, track_id)
        else:
            key = (
                source_type,
                doc.metadata.get("source", ""),
                doc.page_content[:120],
            )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(doc)
    return deduped


def normalize_text(text: str, preview_chars: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= preview_chars:
        return compact
    return compact[:preview_chars] + "..."


def run_probe(args: argparse.Namespace) -> int:
    from src.rag.llm_manager import RAGPromptBuilder
    from src.rag.vector_store import VectorStoreManager
    from src.utils.config import Config

    config = Config()
    persist_dir = args.persist_dir or os.path.join(
        os.environ.get("DATA_DIR", "./data"), "faiss_index"
    )
    embedding_provider = args.embedding_provider or config.embedding_provider
    embedding_model = args.embedding_model or config.embedding_model
    threshold = (
        args.similarity_threshold
        if args.similarity_threshold is not None
        else config.similarity_threshold
    )

    vector = VectorStoreManager(
        persist_directory=persist_dir,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
    )
    vector.load_vectorstore()

    fetch_k = max(args.top_k * args.fetch_multiplier, args.top_k)
    metadata_filter: Optional[Dict[str, Any]] = None
    if args.source_type:
        metadata_filter = {"source_type": args.source_type}

    scored: List[Tuple[Any, float]] = vector.similarity_search_with_score(
        args.query, k=fetch_k, filter=metadata_filter
    )
    if not scored:
        print("No matches found.")
        return 0

    filtered_docs: List[Document] = []
    ranked: List[Tuple[Document, float, float]] = []
    for doc, score in scored:
        sim = score_to_similarity(score)
        if sim >= threshold:
            filtered_docs.append(doc)
            ranked.append((doc, score, sim))

    if not filtered_docs:
        for doc, score in scored[: args.top_k]:
            ranked.append((doc, score, score_to_similarity(score)))
        filtered_docs = [doc for doc, _, _ in ranked]

    deduped = dedupe_docs(filtered_docs)[: args.top_k]

    ranked_map = {id(doc): (score, sim) for doc, score, sim in ranked}
    ordered = []
    for doc in deduped:
        score, sim = ranked_map.get(id(doc), (None, None))
        ordered.append((doc, score, sim))

    print("=" * 72)
    print(f"Query: {args.query}")
    print(
        f"Persist dir: {persist_dir} | top_k={args.top_k} | fetch_k={fetch_k} | threshold={threshold}"
    )
    print("=" * 72)

    for idx, (doc, score, sim) in enumerate(ordered, 1):
        meta = doc.metadata or {}
        source = meta.get("source", "")
        source_type = meta.get("source_type") or meta.get("content_type", "")
        title = meta.get("title", "")
        start_time = meta.get("start_time", "")
        track_id = meta.get("track_id", "")
        snippet = normalize_text(doc.page_content or "", args.preview_chars)

        print(f"[{idx}] score={score} similarity={sim}")
        print(
            f"    type={source_type} title={title} track_id={track_id} start_time={start_time}"
        )
        print(f"    source={source}")
        print(f"    snippet={snippet}")

    if args.show_prompt:
        docs_for_prompt = [doc for doc, _, _ in ordered]
        prompt = RAGPromptBuilder().build_prompt(
            query=args.query,
            context_docs=docs_for_prompt,
            include_sources=True,
        )
        print("\n" + "-" * 72)
        print("Prompt sent to LLM (context section)")
        print("-" * 72)
        print(prompt)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe FAISS retrieval and print snippets used as RAG context"
    )
    parser.add_argument("query", help="Phrase/user input to retrieve against FAISS")
    parser.add_argument(
        "--top-k", type=int, default=5, help="Final number of snippets to print"
    )
    parser.add_argument(
        "--fetch-multiplier",
        type=int,
        default=4,
        help="Internal fetch multiplier before threshold + dedupe",
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=None,
        help="Override similarity threshold (default from config.yaml)",
    )
    parser.add_argument(
        "--persist-dir",
        default=None,
        help="FAISS index directory (default: $DATA_DIR/faiss_index)",
    )
    parser.add_argument(
        "--embedding-provider",
        default=None,
        choices=["huggingface", "openai", "fake"],
        help="Embedding provider used by the index",
    )
    parser.add_argument(
        "--embedding-model",
        default=None,
        help="Embedding model used by the index",
    )
    parser.add_argument(
        "--source-type",
        default=None,
        help="Optional metadata source_type filter (e.g. youtube, pdf)",
    )
    parser.add_argument(
        "--preview-chars",
        type=int,
        default=260,
        help="Snippet preview character length",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Also print constructed prompt context for this query",
    )

    args = parser.parse_args()
    return run_probe(args)


if __name__ == "__main__":
    raise SystemExit(main())
