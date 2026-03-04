#!/usr/bin/env python3
import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


def extract_video_id(url: str) -> str:
    patterns = [
        r"[?&]v=([A-Za-z0-9_-]{11})",
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"youtube\.com/shorts/([A-Za-z0-9_-]{11})",
        r"youtube\.com/embed/([A-Za-z0-9_-]{11})",
        r"^([A-Za-z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, (url or "").strip())
        if match:
            return match.group(1)
    return ""


def normalize_youtube_url(url: str) -> str:
    video_id = extract_video_id(url)
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return (url or "").strip()


def is_weak_title(title: str) -> bool:
    normalized = (title or "").strip()
    lowered = normalized.lower()

    if not normalized:
        return True
    if lowered in {"unknown", "unknown video", "youtube video"}:
        return True
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return True
    if re.match(r"^youtube video \([0-9a-z_-]{11}\)$", lowered):
        return True
    return False


def fetch_youtube_metadata(url: str, timeout: float) -> Dict[str, str]:
    normalized_url = normalize_youtube_url(url)
    if not normalized_url:
        raise ValueError("Empty URL")

    endpoint = "https://www.youtube.com/oembed?format=json&url=" + quote_plus(
        normalized_url
    )
    req = Request(
        endpoint,
        headers={
            "User-Agent": "neet-youtube-metadata-util/1.0",
            "Accept": "application/json",
        },
    )

    with urlopen(req, timeout=timeout) as response:
        payload = response.read().decode("utf-8", errors="replace")

    data = json.loads(payload)
    title = str(data.get("title") or "").strip()
    channel_name = str(data.get("author_name") or "").strip()
    if not title:
        raise ValueError("oEmbed returned empty title")

    return {
        "url": (url or "").strip(),
        "normalized_url": normalized_url,
        "video_id": extract_video_id(normalized_url),
        "title": title,
        "channel_name": channel_name,
    }


def collect_urls(args: argparse.Namespace) -> List[str]:
    urls: List[str] = []
    for url in args.url or []:
        cleaned = (url or "").strip()
        if cleaned:
            urls.append(cleaned)

    if args.urls_file:
        with open(args.urls_file, "r", encoding="utf-8") as f:
            for line in f:
                cleaned = line.strip()
                if cleaned and not cleaned.startswith("#"):
                    urls.append(cleaned)

    deduped: List[str] = []
    seen = set()
    for url in urls:
        if url in seen:
            continue
        deduped.append(url)
        seen.add(url)

    return deduped


def write_json_report(path: str, data: Dict) -> None:
    report_dir = os.path.dirname(path)
    if report_dir:
        os.makedirs(report_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=True, indent=2)


def parse_metadata(raw_metadata: str) -> Dict:
    if not raw_metadata:
        return {}
    try:
        parsed = json.loads(raw_metadata)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def command_lookup(args: argparse.Namespace) -> int:
    urls = collect_urls(args)
    if not urls:
        print("Error: provide at least one --url or --urls-file")
        return 1

    results = []
    success = 0
    failed = 0

    for url in urls:
        try:
            metadata = fetch_youtube_metadata(url=url, timeout=args.timeout)
            results.append({"status": "success", **metadata})
            success += 1
        except (
            HTTPError,
            URLError,
            TimeoutError,
            ValueError,
            json.JSONDecodeError,
        ) as e:
            results.append(
                {
                    "status": "error",
                    "url": url,
                    "error": str(e),
                }
            )
            failed += 1

        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)

    report = {
        "mode": "lookup",
        "total": len(urls),
        "success": success,
        "failed": failed,
        "results": results,
    }

    print(json.dumps(report, ensure_ascii=True, indent=2))
    if args.report_path:
        write_json_report(args.report_path, report)
        print(f"Report written: {args.report_path}")

    return 0


def select_youtube_rows(
    conn: sqlite3.Connection,
    source_ids: List[str],
    limit: int,
) -> List[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    base_sql = "SELECT source_id, url, title, metadata FROM sources WHERE source_type='youtube'"
    params: List[str] = []

    if source_ids:
        placeholders = ",".join(["?"] * len(source_ids))
        sql = f"{base_sql} AND source_id IN ({placeholders}) ORDER BY updated_at DESC"
        params.extend(source_ids)
    else:
        sql = f"{base_sql} ORDER BY updated_at DESC"

    rows = conn.execute(sql, params).fetchall()
    if limit > 0:
        rows = rows[:limit]
    return rows


def command_sync_db(args: argparse.Namespace) -> int:
    db_path = args.db_path
    if not os.path.exists(db_path):
        print(f"Error: DB not found: {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    try:
        rows = select_youtube_rows(
            conn, source_ids=args.source_id or [], limit=args.limit
        )

        selected = 0
        skipped_strong = 0
        fetched_ok = 0
        fetched_failed = 0
        changed = 0
        updated = 0
        failed_updates = 0
        result_rows = []

        for row in rows:
            source_id = str(row["source_id"] or "")
            url = str(row["url"] or "")
            old_title = str(row["title"] or "")
            metadata = parse_metadata(row["metadata"])

            if (not args.include_healthy_titles) and (not is_weak_title(old_title)):
                skipped_strong += 1
                continue

            selected += 1

            try:
                fetched = fetch_youtube_metadata(url=url, timeout=args.timeout)
                fetched_ok += 1
            except (
                HTTPError,
                URLError,
                TimeoutError,
                ValueError,
                json.JSONDecodeError,
            ) as e:
                fetched_failed += 1
                result_rows.append(
                    {
                        "source_id": source_id,
                        "url": url,
                        "old_title": old_title,
                        "status": "fetch_error",
                        "error": str(e),
                    }
                )
                if args.sleep_ms > 0:
                    time.sleep(args.sleep_ms / 1000.0)
                continue

            new_title = fetched["title"]
            channel_name = fetched["channel_name"]

            new_metadata = dict(metadata)
            new_metadata["youtube_channel_name"] = channel_name
            new_metadata["youtube_title"] = new_title
            new_metadata["youtube_video_id"] = fetched.get("video_id", "")
            new_metadata["youtube_metadata_source"] = "oembed"
            new_metadata["youtube_metadata_synced_at"] = datetime.now(
                timezone.utc
            ).isoformat()

            metadata_changed = new_metadata != metadata
            title_changed = (new_title or "").strip() != (old_title or "").strip()
            has_change = metadata_changed or title_changed

            if has_change:
                changed += 1

            row_status = "no_change"
            row_error = None

            if args.apply and has_change:
                try:
                    conn.execute(
                        """
                        UPDATE sources
                        SET title = ?, metadata = ?, updated_at = ?
                        WHERE source_id = ?
                        """,
                        (
                            new_title,
                            json.dumps(new_metadata, ensure_ascii=True),
                            datetime.now().isoformat(),
                            source_id,
                        ),
                    )
                    updated += 1
                    row_status = "updated"
                except Exception as e:
                    failed_updates += 1
                    row_status = "update_error"
                    row_error = str(e)
            elif has_change:
                row_status = "would_update"

            result_rows.append(
                {
                    "source_id": source_id,
                    "url": url,
                    "old_title": old_title,
                    "new_title": new_title,
                    "channel_name": channel_name,
                    "status": row_status,
                    "error": row_error,
                }
            )

            if args.sleep_ms > 0:
                time.sleep(args.sleep_ms / 1000.0)

        if args.apply:
            conn.commit()

        report = {
            "mode": "sync-db",
            "db_path": db_path,
            "apply": bool(args.apply),
            "selected": selected,
            "skipped_strong_titles": skipped_strong,
            "fetched_ok": fetched_ok,
            "fetched_failed": fetched_failed,
            "changed": changed,
            "updated": updated,
            "failed_updates": failed_updates,
            "results": result_rows,
        }

        summary = {
            k: report[k]
            for k in [
                "db_path",
                "apply",
                "selected",
                "skipped_strong_titles",
                "fetched_ok",
                "fetched_failed",
                "changed",
                "updated",
                "failed_updates",
            ]
        }
        print(json.dumps(summary, ensure_ascii=True, indent=2))

        print_limit = max(0, int(args.print_limit))
        if print_limit > 0:
            print("Sample results:")
            for row in result_rows[:print_limit]:
                print(json.dumps(row, ensure_ascii=True))

        if args.report_path:
            write_json_report(args.report_path, report)
            print(f"Report written: {args.report_path}")

        return 0
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Utility to fetch YouTube title/channel and sync into sources.db"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    lookup = subparsers.add_parser(
        "lookup", help="Fetch title and channel for provided YouTube URL(s)"
    )
    lookup.add_argument(
        "--url",
        action="append",
        default=[],
        help="YouTube URL (repeat flag for multiple URLs)",
    )
    lookup.add_argument(
        "--urls-file",
        default=None,
        help="Text file with one YouTube URL per line",
    )
    lookup.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="HTTP timeout in seconds (default: 20)",
    )
    lookup.add_argument(
        "--sleep-ms",
        type=int,
        default=0,
        help="Delay between URL fetches in milliseconds",
    )
    lookup.add_argument(
        "--report-path",
        default=None,
        help="Optional JSON report output path",
    )
    lookup.set_defaults(func=command_lookup)

    sync_db = subparsers.add_parser(
        "sync-db", help="Fetch YouTube metadata and update sources.db"
    )
    sync_db.add_argument(
        "--db-path",
        default=os.path.join(os.environ.get("DATA_DIR", "./data"), "sources.db"),
        help="Path to sources.db (default: DATA_DIR/sources.db or ./data/sources.db)",
    )
    sync_db.add_argument(
        "--source-id",
        action="append",
        default=[],
        help="Limit to specific source_id(s), repeatable",
    )
    sync_db.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most N YouTube rows after filtering (0 = no limit)",
    )
    sync_db.add_argument(
        "--include-healthy-titles",
        action="store_true",
        help="Also process rows whose title already looks meaningful",
    )
    sync_db.add_argument(
        "--apply",
        action="store_true",
        help="Apply DB updates (default is dry-run)",
    )
    sync_db.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="HTTP timeout in seconds (default: 20)",
    )
    sync_db.add_argument(
        "--sleep-ms",
        type=int,
        default=50,
        help="Delay between requests in milliseconds (default: 50)",
    )
    sync_db.add_argument(
        "--print-limit",
        type=int,
        default=20,
        help="Number of result rows to print (default: 20)",
    )
    sync_db.add_argument(
        "--report-path",
        default=None,
        help="Optional JSON report output path",
    )
    sync_db.set_defaults(func=command_sync_db)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
