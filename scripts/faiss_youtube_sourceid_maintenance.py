#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from typing import Dict, Tuple
from urllib.parse import parse_qs, urlparse


sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def extract_video_id(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path or ""

    if "youtu.be" in host:
        candidate = path.strip("/").split("/")[0]
        return candidate[:11] if len(candidate) >= 11 else ""

    if "youtube.com" in host:
        query = parse_qs(parsed.query or "")
        video_values = query.get("v") or []
        if video_values:
            candidate = (video_values[0] or "").strip()
            return candidate[:11] if len(candidate) >= 11 else ""

        path_parts = [part for part in path.strip("/").split("/") if part]
        if len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed", "v"}:
            candidate = (path_parts[1] or "").strip()
            return candidate[:11] if len(candidate) >= 11 else ""

    return ""


def read_youtube_sources(sqlite_path: str) -> list:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT source_id, url, metadata FROM sources WHERE source_type = 'youtube'"
        ).fetchall()
        return rows
    finally:
        conn.close()


def build_source_lookup(
    rows: list,
) -> Tuple[Dict[Tuple[str, str], str], Dict[str, str], set]:
    by_video_track: Dict[Tuple[str, str], str] = {}
    by_video_unique: Dict[str, str] = {}
    by_video_all = {}

    for row in rows:
        source_id = (row["source_id"] or "").strip()
        url = (row["url"] or "").strip()
        metadata_raw = row["metadata"]
        metadata = {}
        if metadata_raw:
            try:
                metadata = json.loads(metadata_raw)
            except Exception:
                metadata = {}

        video_id = extract_video_id(url)
        if not video_id or not source_id:
            continue

        track_id = ""
        if isinstance(metadata, dict):
            track_id = str(metadata.get("track_id") or "").strip()

        if track_id:
            by_video_track[(video_id, track_id)] = source_id

        by_video_all.setdefault(video_id, set()).add(source_id)

    ambiguous_video_ids = set()
    for video_id, source_ids in by_video_all.items():
        if len(source_ids) == 1:
            by_video_unique[video_id] = next(iter(source_ids))
        else:
            ambiguous_video_ids.add(video_id)

    return by_video_track, by_video_unique, ambiguous_video_ids


def resolve_source_id(
    video_id: str,
    track_id: str,
    by_video_track: Dict[Tuple[str, str], str],
    by_video_unique: Dict[str, str],
    ambiguous_video_ids: set,
) -> Tuple[str, str]:
    if not video_id:
        return "", "missing_video_id"

    if track_id:
        sid = by_video_track.get((video_id, track_id), "")
        if sid:
            return sid, "video_track"

    if video_id in ambiguous_video_ids:
        return "", "ambiguous_video_id"

    sid = by_video_unique.get(video_id, "")
    if sid:
        return sid, "video_unique"

    return "", "video_not_found"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit and optionally backfill missing source_id for YouTube docs in FAISS index.pkl"
    )
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("DATA_DIR", "./data"),
        help="Base data directory (default: DATA_DIR or ./data)",
    )
    parser.add_argument(
        "--persist-dir",
        default=None,
        help="Explicit FAISS index dir; overrides index resolution",
    )
    parser.add_argument(
        "--index-name",
        default=None,
        help="Logical index name if persist-dir is not passed",
    )
    parser.add_argument(
        "--embedding-provider",
        default=None,
        choices=["huggingface", "openai", "fake"],
        help="Embedding provider used for this index",
    )
    parser.add_argument(
        "--embedding-model",
        default=None,
        help="Embedding model used for this index",
    )
    parser.add_argument(
        "--sqlite-path",
        default=None,
        help="Path to sources DB (default: <data-dir>/sources.db)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply backfill updates and save index.pkl",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Disable index.pkl backup before write when --apply is set",
    )
    parser.add_argument(
        "--report-path",
        default=None,
        help="Optional report file path",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=20,
        help="Max unresolved sample entries to print",
    )
    args = parser.parse_args()

    try:
        try:
            from langchain_core.documents import Document
            from src.rag.index_registry import resolve_runtime_index
            from src.rag.vector_store import VectorStoreManager
            from src.utils.config import Config
        except Exception as import_error:
            print(
                "Error: missing runtime dependencies for FAISS maintenance script "
                f"({import_error})"
            )
            print(
                "Tip: run this in the project runtime environment where "
                "langchain/openai dependencies are installed."
            )
            return 1

        config = Config()
        embedding_provider = args.embedding_provider or config.embedding_provider
        embedding_model = args.embedding_model or config.embedding_model

        _, _, persist_dir = resolve_runtime_index(
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            persist_directory=args.persist_dir,
            index_name=args.index_name,
            data_dir=args.data_dir,
        )

        sqlite_path = args.sqlite_path or os.path.join(args.data_dir, "sources.db")
        index_pkl = os.path.join(persist_dir, "index.pkl")
        index_faiss = os.path.join(persist_dir, "index.faiss")

        if not os.path.exists(sqlite_path):
            print(f"Error: SQLite DB not found: {sqlite_path}")
            return 1
        if not os.path.exists(index_pkl) or not os.path.exists(index_faiss):
            print(f"Error: FAISS index files missing in: {persist_dir}")
            print("Expected files: index.pkl and index.faiss")
            return 1

        rows = read_youtube_sources(sqlite_path)
        by_video_track, by_video_unique, ambiguous_video_ids = build_source_lookup(rows)

        vector = VectorStoreManager(
            persist_directory=persist_dir,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
        )
        vector.load_vectorstore()

        doc_map = getattr(vector.vectorstore.docstore, "_dict", {})

        youtube_total = 0
        with_source_before = 0
        missing_before = 0
        updated_docs = 0
        unresolved_docs = 0
        resolve_reasons = Counter()
        unresolved_samples = []

        for key, doc in doc_map.items():
            if not isinstance(doc, Document):
                continue

            source_type = doc.metadata.get("source_type") or doc.metadata.get(
                "content_type", ""
            )
            if source_type != "youtube":
                continue

            youtube_total += 1

            current_source_id = str(doc.metadata.get("source_id") or "").strip()
            if current_source_id:
                with_source_before += 1
                continue

            missing_before += 1
            video_id = str(doc.metadata.get("video_id") or "").strip()
            if not video_id:
                video_id = extract_video_id(str(doc.metadata.get("source") or ""))
            track_id = str(doc.metadata.get("track_id") or "").strip()

            resolved_source_id, reason = resolve_source_id(
                video_id=video_id,
                track_id=track_id,
                by_video_track=by_video_track,
                by_video_unique=by_video_unique,
                ambiguous_video_ids=ambiguous_video_ids,
            )
            resolve_reasons[reason] += 1

            if not resolved_source_id:
                unresolved_docs += 1
                if len(unresolved_samples) < args.sample_limit:
                    unresolved_samples.append(
                        {
                            "doc_id": key,
                            "video_id": video_id,
                            "track_id": track_id,
                            "source": str(doc.metadata.get("source") or ""),
                            "reason": reason,
                        }
                    )
                continue

            doc.metadata["source_id"] = resolved_source_id
            updated_docs += 1

        with_source_after = with_source_before + updated_docs
        missing_after = missing_before - updated_docs

        backup_path = ""
        if args.apply and updated_docs > 0:
            if not args.no_backup:
                ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
                backup_path = f"{index_pkl}.bak_{ts}"
                shutil.copy2(index_pkl, backup_path)
            vector.vectorstore.save_local(persist_dir)

        report_lines = [
            f"PERSIST_DIR={persist_dir}",
            f"SQLITE_PATH={sqlite_path}",
            f"APPLY_MODE={'1' if args.apply else '0'}",
            f"BACKUP_CREATED={backup_path or 'NONE'}",
            f"YOUTUBE_DOCS_TOTAL={youtube_total}",
            f"YOUTUBE_WITH_SOURCE_ID_BEFORE={with_source_before}",
            f"YOUTUBE_MISSING_SOURCE_ID_BEFORE={missing_before}",
            f"UPDATED_DOCS={updated_docs}",
            f"UNRESOLVED_DOCS={unresolved_docs}",
            f"YOUTUBE_WITH_SOURCE_ID_AFTER={with_source_after}",
            f"YOUTUBE_MISSING_SOURCE_ID_AFTER={missing_after}",
        ]

        for reason in sorted(resolve_reasons.keys()):
            report_lines.append(
                f"RESOLVE_REASON_{reason.upper()}={resolve_reasons[reason]}"
            )

        if unresolved_samples:
            report_lines.append("UNRESOLVED_SAMPLES_BEGIN")
            for sample in unresolved_samples:
                report_lines.append(json.dumps(sample, ensure_ascii=True))
            report_lines.append("UNRESOLVED_SAMPLES_END")

        report = "\n".join(report_lines)
        print(report)

        if args.report_path:
            report_dir = os.path.dirname(args.report_path)
            if report_dir:
                os.makedirs(report_dir, exist_ok=True)
            with open(args.report_path, "w", encoding="utf-8") as f:
                f.write(report + "\n")
            print(f"Report written: {args.report_path}")

        if not args.apply:
            print("Dry-run complete. Re-run with --apply to persist updates.")
        elif updated_docs == 0:
            print("Apply mode complete. No updates were needed.")
        else:
            print("Apply mode complete. Updates persisted to FAISS index.")

        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
