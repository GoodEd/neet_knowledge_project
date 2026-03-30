#!/usr/bin/env python3
"""
NEET Knowledge RAG - Main Entry Point
Usage: python -m src.main [command] [options]
"""

import sys
import os
import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence, cast
from dotenv import load_dotenv
from langchain_core.documents import Document

from src.processors.youtube_processor import (
    TranscriptEntry,
    TranslatorProtocol,
    YouTubeProcessor,
)
from src.rag.index_registry import resolve_index_directory, set_active_index
from src.rag.vector_store import VectorStoreManager
from src.utils.config import Config
from src.utils.content_manager import ContentSource, ContentSourceManager

_ = load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def build_translation_translator(*, model_name: str) -> TranslatorProtocol:
    cfg = Config()
    provider = cfg.translation_provider

    if provider == "openrouter":
        from src.translation import OpenRouterTranslator

        api_key_env = cfg.translation_api_key_env_var
        api_key = os.environ.get(api_key_env, "")
        return OpenRouterTranslator(
            api_key=api_key or None,
            base_url=cfg.translation_base_url,
            model_name=model_name,
            source_lang_code=cfg.translation_source_lang,
            target_lang_code=cfg.translation_target_lang,
            max_chars_per_request=cfg.translation_max_chars_per_request,
        )

    # Fallback: local transformers pipeline (requires GPU)
    from transformers import pipeline
    from src.translation import TranscriptTranslator

    return TranscriptTranslator(
        pipeline_factory=pipeline,
        model_name=model_name,
    )


def _is_s3_transcript_eligible(source: ContentSource) -> bool:
    metadata = source.metadata if isinstance(source.metadata, dict) else {}
    s3_uri = metadata.get("s3_transcript_json_uri")
    return bool(source.source_type == "youtube" and s3_uri)


@dataclass(frozen=True)
class TranslateSourceResult:
    status: Literal["success", "skipped", "failed"]
    doc_count: int
    reason: str | None
    documents: list[Document]


def _translate_source_from_s3(
    *,
    source: ContentSource,
    translator: TranslatorProtocol,
    youtube_processor: YouTubeProcessor,
) -> TranslateSourceResult:
    metadata = source.metadata if isinstance(source.metadata, dict) else {}
    s3_uri = metadata.get("s3_transcript_json_uri")
    track_id = metadata.get("track_id") or "s3_transcript_json"

    if not s3_uri:
        return TranslateSourceResult(
            status="skipped",
            doc_count=0,
            reason="missing_s3_transcript_json_uri",
            documents=[],
        )

    video_id = youtube_processor._extract_video_id(source.url)
    if not video_id:
        raise RuntimeError(
            f"Invalid YouTube URL for source {source.source_id}: {source.url}"
        )

    transcript_entries = cast(
        list[TranscriptEntry],
        youtube_processor._load_transcript_from_s3_json(
            s3_transcript_json_uri=s3_uri,
            video_title=source.title or source.url,
            track_id=track_id,
        ),
    )
    translated = youtube_processor.prepare_translated_documents(
        transcript_entries=transcript_entries,
        translator=translator,
        url=source.url,
        video_id=video_id,
        transcript_source="s3_transcript_json",
    )

    status = translated.get("status", "failed")
    if status == "success":
        docs = translated.get("documents", [])
        for doc in docs:
            doc.metadata["source_id"] = source.source_id
        return TranslateSourceResult(
            status="success",
            doc_count=len(docs),
            reason=None,
            documents=docs,
        )

    if status in {"skipped_ineligible", "skipped_empty"}:
        return TranslateSourceResult(
            status="skipped",
            doc_count=0,
            reason=status,
            documents=[],
        )

    return TranslateSourceResult(
        status="failed",
        doc_count=0,
        reason=translated.get("error") or "translation_failed",
        documents=[],
    )


def cmd_translate_s3_transcripts(args: argparse.Namespace) -> int:
    source_manager = ContentSourceManager()
    data_dir = os.environ.get("DATA_DIR", "./data")

    all_skipped_sources: list[ContentSource] = []
    eligible_sources: list[ContentSource] = []
    if args.source_id:
        source = source_manager.get_source(args.source_id)
        if not source:
            print(f"✗ {args.source_id}: source not found")
            print("Summary: success=0 skipped=0 failed=1")
            return 1
        if _is_s3_transcript_eligible(source):
            eligible_sources = [source]
        else:
            all_skipped_sources = [source]
    else:
        all_sources = sorted(
            source_manager.get_all_sources(), key=lambda s: s.source_id
        )
        for source in all_sources:
            if _is_s3_transcript_eligible(source):
                eligible_sources.append(source)
            else:
                all_skipped_sources.append(source)
        if args.limit is not None:
            eligible_sources = eligible_sources[: args.limit]

    success_count = 0
    skipped_count = 0
    failed_count = 0

    for source in all_skipped_sources:
        skipped_count += 1
        print(f"- {source.source_id}: skipped (ineligible)")

    if not eligible_sources:
        print(
            f"Summary: success={success_count} skipped={skipped_count} failed={failed_count}"
        )
        return 0

    target_persist_dir = resolve_index_directory(
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
        index_name=args.target_index_name,
        data_dir=data_dir,
    )
    vector_manager = VectorStoreManager(
        persist_directory=target_persist_dir,
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
    )
    try:
        vector_manager.load_vectorstore()
    except FileNotFoundError:
        pass

    translator: TranslatorProtocol | None = None
    youtube_processor = YouTubeProcessor()

    for source in eligible_sources:
        try:
            source_exists = vector_manager.has_documents_for_source_id(source.source_id)
            should_skip_existing = source_exists and not args.force
            should_rebuild_existing = source_exists and args.force

            if should_skip_existing:
                skipped_count += 1
                print(f"- {source.source_id}: skipped (skipped_existing)")
                continue

            if translator is None:
                model = args.translation_model or Config().translation_model
                translator = build_translation_translator(model_name=model)

            source_result = _translate_source_from_s3(
                source=source,
                translator=translator,
                youtube_processor=youtube_processor,
            )
            if source_result.status == "success":
                if should_rebuild_existing:
                    vector_manager.delete_by_source_id(source.source_id)
                if source_result.documents:
                    vector_manager.add_documents(source_result.documents)
                success_count += 1
                print(f"✓ {source.source_id}: success ({source_result.doc_count} docs)")
            elif source_result.status == "skipped":
                skipped_count += 1
                reason = source_result.reason or "ineligible"
                print(f"- {source.source_id}: skipped ({reason})")
            else:
                failed_count += 1
                print(
                    f"✗ {source.source_id}: failed ({source_result.reason or 'unknown_error'})"
                )
        except Exception as exc:
            failed_count += 1
            print(f"✗ {source.source_id}: failed ({exc})")

    print(
        f"Summary: success={success_count} skipped={skipped_count} failed={failed_count}"
    )

    if args.activate and failed_count == 0 and success_count > 0:
        active = set_active_index(
            embedding_provider=args.embedding_provider,
            embedding_model=args.embedding_model,
            index_name=args.target_index_name,
            data_dir=data_dir,
        )
        print("Activated target index:")
        print(active)

    return 1 if failed_count > 0 else 0


def cmd_ingest(args: argparse.Namespace) -> None:
    from src.rag import NEETRAG

    rag = NEETRAG(
        persist_directory=args.persist_dir,
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
        index_name=args.index_name,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
        llm_base_url=args.llm_base_url,
    )

    sources = args.sources if isinstance(args.sources, list) else [args.sources]

    result = rag.ingest_content(sources)

    print(f"Processed {result['total_processed']} sources successfully")
    print(f"Failed: {result['total_failed']}")

    for r in result.get("results", []):
        status = r.get("status", "unknown")
        source = r.get("source", "")
        if status == "success":
            docs = r.get("documents_processed", 0)
            print(f"  ✓ {source}: {docs} documents")
        else:
            error = r.get("error", "Unknown error")
            print(f"  ✗ {source}: {error}")


def cmd_query(args: argparse.Namespace) -> None:
    from src.rag import NEETRAG

    rag = NEETRAG(
        persist_directory=args.persist_dir,
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
        index_name=args.index_name,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
        llm_base_url=args.llm_base_url,
    )

    result = rag.query(args.question, top_k=args.top_k)

    print("\n" + "=" * 50)
    print(f"Question: {result['question']}")
    print("=" * 50)
    print(f"\nAnswer:\n{result['answer']}")

    if result.get("sources"):
        print("\nSources:")
        for i, src in enumerate(result["sources"], 1):
            content_type = src.get("content_type", "text")
            if content_type == "youtube" and src.get("timestamp_url"):
                title = src.get("title", "")
                ts_label = src.get("timestamp_label", "")
                display = title or src.get("source", "Unknown")
                if ts_label:
                    print(f"  {i}. [YouTube] {display} @ {ts_label}")
                else:
                    print(f"  {i}. [YouTube] {display}")
                print(f"     Link: {src['timestamp_url']}")
            else:
                print(f"  {i}. {src.get('source', 'Unknown')}")
                print(f"     Type: {content_type}")


def cmd_stats(args: argparse.Namespace) -> None:
    from src.rag import NEETRAG

    rag = NEETRAG(
        persist_directory=args.persist_dir,
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
        index_name=args.index_name,
    )
    stats = rag.get_stats()

    print("NEET RAG Statistics:")
    print("-" * 30)
    if "error" in stats:
        print(f"Error: {stats['error']}")
    else:
        if "llm" in stats:
            print(f"LLM Provider: {stats['llm']['provider']}")
            print(f"LLM Model: {stats['llm']['model']}")
        if "vectorstore" in stats:
            vs = stats["vectorstore"]
            print(f"Vector Store: {vs.get('embedding_model', 'N/A')}")
            print(f"Collection: {vs.get('collection_name', 'N/A')}")


def cmd_interactive(args: argparse.Namespace) -> None:
    from src.rag import NEETRAG

    print("NEET Knowledge RAG - Interactive Mode")
    print("=" * 50)
    print("Loading RAG system...")

    rag = NEETRAG(
        persist_directory=args.persist_dir,
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
        index_name=args.index_name,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
        llm_base_url=args.llm_base_url,
    )

    print("Ready! Type 'quit' or 'exit' to end the session.")
    print("Type 'stats' to see system statistics.\n")

    chat_history = []

    while True:
        try:
            question = input("You: ").strip()

            if question.lower() in ["quit", "exit"]:
                print("Goodbye!")
                break

            if question.lower() == "stats":
                stats = rag.get_stats()
                print(f"\nStats: {stats}\n")
                continue

            if not question:
                continue

            result = rag.query_with_history(question, chat_history)

            print(f"\nAssistant: {result['answer']}\n")

            chat_history.append((question, result["answer"]))

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}\n")


def cmd_source_add(args: argparse.Namespace) -> None:
    from src.utils import ContentSourceManager

    manager = ContentSourceManager()

    if args.type == "youtube":
        source_id = manager.add_youtube(args.url, args.title, args.interval)
    elif args.type == "html":
        source_id = manager.add_html(args.url, args.title, args.interval)
    else:
        print(f"Unknown source type: {args.type}")
        return

    print(f"Added {args.type} source: {args.url}")
    print(f"Source ID: {source_id}")
    print(f"Update interval: {args.interval} hours")


def cmd_source_list(args: argparse.Namespace) -> None:
    from src.utils import ContentSourceManager

    manager = ContentSourceManager()
    sources = manager.get_all_sources(args.type)

    print(f"\nStored Sources ({len(sources)} total)")
    print("=" * 70)

    for s in sources:
        status_icon = {
            "active": "✓",
            "pending": "○",
            "error": "✗",
            "disabled": "⊘",
        }.get(s.status, "?")
        print(f"{status_icon} [{s.source_type.upper()}] {s.title or s.url}")
        print(f"   ID: {s.source_id}")
        print(f"   URL: {s.url}")
        print(
            f"   Interval: {s.fetch_interval_hours}h | Last: {s.last_fetched or 'Never'}"
        )
        if s.error_message:
            print(f"   Error: {s.error_message}")
        print()


def cmd_source_update(args: argparse.Namespace) -> None:
    from src.utils import ContentSourceManager, AutoUpdater
    from src.rag import NEETRAG

    manager = ContentSourceManager()
    rag = NEETRAG(
        persist_directory=args.persist_dir,
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
        index_name=args.index_name,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
        llm_base_url=args.llm_base_url,
    )
    updater = AutoUpdater(manager, rag)

    if args.source_id:
        result = updater.update_source(args.source_id)
        print(f"Update result: {result}")
    else:
        print("Updating all sources needing refresh...")
        results = updater.update_all()
        for r in results:
            print(f"  {r.get('status', 'unknown')}: {r.get('source_id', 'N/A')}")


def cmd_source_remove(args: argparse.Namespace) -> None:
    from src.utils import ContentSourceManager

    manager = ContentSourceManager()
    if manager.remove_source(args.source_id):
        print(f"Removed source: {args.source_id}")
    else:
        print(f"Source not found: {args.source_id}")


def cmd_index(args: argparse.Namespace) -> None:
    from src.rag.index_registry import (
        active_index_file,
        get_active_index,
        index_root,
        resolve_index_directory,
        set_active_index,
    )

    data_dir = os.environ.get("DATA_DIR", "./data")
    if args.index_command == "show":
        active = get_active_index(data_dir=data_dir)
        if not active:
            print("No active index configured yet.")
            print(f"Active file: {active_index_file(data_dir)}")
            return
        print("Active index:")
        print(active)
        return

    if args.index_command == "list":
        root = Path(index_root(data_dir))
        if not root.exists():
            print(f"No index root found at {root}")
            return
        print(f"Index root: {root}")
        for p in sorted(root.glob("*/*/*")):
            if (p / "index.faiss").exists() and (p / "index.pkl").exists():
                print(f"- {p}")
        return

    if args.index_command == "activate":
        payload = set_active_index(
            embedding_provider=args.embedding_provider,
            embedding_model=args.embedding_model,
            index_name=args.index_name,
            data_dir=data_dir,
        )
        print("Active index updated:")
        print(payload)
        return

    print("Unknown index command")


def cmd_reindex(args: argparse.Namespace) -> None:
    from langchain_core.documents import Document
    from src.rag.index_registry import resolve_runtime_index, set_active_index
    from src.rag.vector_store import VectorStoreManager

    data_dir = os.environ.get("DATA_DIR", "./data")

    src_provider, src_model, src_dir = resolve_runtime_index(
        embedding_provider=args.source_embedding_provider,
        embedding_model=args.source_embedding_model,
        persist_directory=args.source_persist_dir,
        index_name=args.source_index_name,
        data_dir=data_dir,
    )
    dst_provider, dst_model, dst_dir = resolve_runtime_index(
        embedding_provider=args.target_embedding_provider,
        embedding_model=args.target_embedding_model,
        persist_directory=args.target_persist_dir,
        index_name=args.target_index_name,
        data_dir=data_dir,
    )

    src_store = VectorStoreManager(
        persist_directory=src_dir,
        embedding_provider=src_provider,
        embedding_model=src_model,
    )
    src_store.load_vectorstore()
    vectorstore = src_store.vectorstore
    assert vectorstore is not None

    doc_map = getattr(vectorstore.docstore, "_dict", {})
    docs = [doc for doc in doc_map.values() if isinstance(doc, Document)]
    if not docs:
        print("No documents found in source index; aborting reindex.")
        return

    dst_store = VectorStoreManager(
        persist_directory=dst_dir,
        embedding_provider=dst_provider,
        embedding_model=dst_model,
    )
    dst_store.create_vectorstore(docs)

    print(f"Reindexed {len(docs)} docs")
    print(f"Source: {src_dir} ({src_provider} / {src_model})")
    print(f"Target: {dst_dir} ({dst_provider} / {dst_model})")

    if args.activate:
        active = set_active_index(
            embedding_provider=dst_provider,
            embedding_model=dst_model,
            index_name=args.target_index_name,
            data_dir=data_dir,
        )
        print("Activated target index:")
        print(active)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NEET Knowledge RAG - Multi-format content RAG system"
    )

    parser.add_argument(
        "--persist-dir",
        default=None,
        help="Vector database directory (optional; if omitted, active/index-derived path is used)",
    )
    parser.add_argument(
        "--index-name",
        default=None,
        help="Logical index name under faiss_indexes/<provider>/<model>/<index_name>",
    )
    parser.add_argument(
        "--embedding-provider",
        default="huggingface",
        choices=["huggingface", "openai", "fake"],
        help="Embedding provider",
    )
    parser.add_argument(
        "--embedding-model",
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="Embedding model name",
    )
    parser.add_argument(
        "--llm-provider",
        default="openai",
        choices=["ollama", "openai", "anthropic"],
        help="LLM provider (default: openai for OpenRouter compatibility)",
    )
    parser.add_argument(
        "--llm-model",
        default=os.getenv("OPENAI_MODEL_NAME", "google/gemini-2.0-flash-001"),
        help="LLM model name",
    )
    parser.add_argument(
        "--llm-base-url",
        default=os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
        help="LLM base URL (default: from OPENAI_BASE_URL env var)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    ingest_parser = subparsers.add_parser("ingest", help="Ingest content")
    ingest_parser.add_argument("sources", nargs="+", help="Source files/URLs")

    query_parser = subparsers.add_parser("query", help="Query the RAG")
    query_parser.add_argument("question", help="Question to ask")
    query_parser.add_argument("--top-k", type=int, default=5, help="Number of results")

    stats_parser = subparsers.add_parser("stats", help="Show statistics")

    interactive_parser = subparsers.add_parser("chat", help="Interactive chat mode")

    # Source management subparser
    source_parser = subparsers.add_parser("source", help="Manage content sources")
    source_subparsers = source_parser.add_subparsers(
        dest="source_command", help="Source commands"
    )

    # source add
    add_parser = source_subparsers.add_parser("add", help="Add a content source")
    add_parser.add_argument("type", choices=["youtube", "html"], help="Source type")
    add_parser.add_argument("url", help="Source URL")
    add_parser.add_argument("--title", default=None, help="Source title")
    add_parser.add_argument(
        "--interval", type=int, default=24, help="Update interval in hours"
    )

    # source list
    list_parser = source_subparsers.add_parser("list", help="List content sources")
    list_parser.add_argument(
        "--type",
        choices=["youtube", "html", "all"],
        default="all",
        help="Filter by type",
    )

    # source update
    update_parser = source_subparsers.add_parser(
        "update", help="Update content sources"
    )
    update_parser.add_argument(
        "--source-id", default=None, help="Source ID to update (default: all)"
    )

    # source remove
    remove_parser = source_subparsers.add_parser(
        "remove", help="Remove a content source"
    )
    remove_parser.add_argument("source_id", help="Source ID to remove")

    index_parser = subparsers.add_parser("index", help="Manage multi-index selection")
    index_subparsers = index_parser.add_subparsers(
        dest="index_command", help="Index commands"
    )

    index_subparsers.add_parser("show", help="Show current active index")
    index_subparsers.add_parser("list", help="List discovered FAISS indexes")
    activate_parser = index_subparsers.add_parser(
        "activate", help="Set active index for runtime"
    )
    activate_parser.add_argument(
        "--embedding-provider",
        required=True,
        choices=["huggingface", "openai", "fake"],
        help="Embedding provider for active index",
    )
    activate_parser.add_argument(
        "--embedding-model",
        required=True,
        help="Embedding model for active index",
    )
    activate_parser.add_argument(
        "--index-name",
        default=None,
        help="Optional logical index name",
    )

    reindex_parser = subparsers.add_parser(
        "reindex", help="Rebuild a new index from documents in an existing index"
    )
    reindex_parser.add_argument(
        "--source-persist-dir",
        default=None,
        help="Source index directory (optional)",
    )
    reindex_parser.add_argument(
        "--source-index-name",
        default=None,
        help="Source index logical name (uses active if omitted)",
    )
    reindex_parser.add_argument(
        "--source-embedding-provider",
        default="huggingface",
        choices=["huggingface", "openai", "fake"],
        help="Source embedding provider",
    )
    reindex_parser.add_argument(
        "--source-embedding-model",
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        help="Source embedding model",
    )
    reindex_parser.add_argument(
        "--target-persist-dir",
        default=None,
        help="Target index directory (optional)",
    )
    reindex_parser.add_argument(
        "--target-index-name",
        default=None,
        help="Target logical index name",
    )
    reindex_parser.add_argument(
        "--target-embedding-provider",
        required=True,
        choices=["huggingface", "openai", "fake"],
        help="Target embedding provider",
    )
    reindex_parser.add_argument(
        "--target-embedding-model",
        required=True,
        help="Target embedding model",
    )
    reindex_parser.add_argument(
        "--activate",
        action="store_true",
        help="Activate target index after reindex completes",
    )

    translate_s3_parser = subparsers.add_parser(
        "translate-s3-transcripts",
        help="Translate stored S3 transcript JSONs and index translated docs",
    )
    translate_scope_group = translate_s3_parser.add_mutually_exclusive_group(
        required=True
    )
    translate_scope_group.add_argument(
        "--source-id",
        default=None,
        help="Process one stored source by source_id",
    )
    translate_scope_group.add_argument(
        "--all",
        action="store_true",
        help="Process all eligible stored sources",
    )
    translate_s3_parser.add_argument(
        "--target-index-name",
        required=True,
        help="Target logical index name for translated documents",
    )
    translate_s3_parser.add_argument(
        "--translation-model",
        default=None,
        help="Translation model override (default: from config.yaml)",
    )
    translate_s3_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of eligible sources to process in --all mode",
    )
    translate_s3_parser.add_argument(
        "--activate",
        action="store_true",
        help="Activate target index only when all processed sources succeed",
    )
    translate_s3_parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild existing translated docs for selected sources in target index",
    )

    args = parser.parse_args(argv)

    if args.command == "ingest":
        cmd_ingest(args)
        return 0
    elif args.command == "query":
        cmd_query(args)
        return 0
    elif args.command == "stats":
        cmd_stats(args)
        return 0
    elif args.command == "chat":
        cmd_interactive(args)
        return 0
    elif args.command == "source":
        if args.source_command == "add":
            cmd_source_add(args)
        elif args.source_command == "list":
            cmd_source_list(args)
        elif args.source_command == "update":
            cmd_source_update(args)
        elif args.source_command == "remove":
            cmd_source_remove(args)
        else:
            source_parser.print_help()
            return 1
        return 0
    elif args.command == "index":
        cmd_index(args)
        return 0
    elif args.command == "reindex":
        cmd_reindex(args)
        return 0
    elif args.command == "translate-s3-transcripts":
        return cmd_translate_s3_transcripts(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
