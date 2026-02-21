import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ContentSource:
    source_id: str
    url: str
    source_type: str
    title: Optional[str] = None
    last_fetched: Optional[str] = None
    last_updated: Optional[str] = None
    fetch_interval_hours: int = 24
    status: str = "pending"
    error_message: Optional[str] = None
    metadata: Optional[Dict] = None


class ContentSourceManager:
    def __init__(self, storage_path: Optional[str] = None):
        data_dir = os.environ.get("DATA_DIR", "./data")
        self.storage_path = storage_path or os.path.join(data_dir, "sources.db")
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        self.conn = sqlite3.connect(
            self.storage_path, timeout=30, check_same_thread=False
        )
        self.conn.row_factory = sqlite3.Row
        self._init_db()
        self._migrate_from_json()

    def _init_db(self):
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                source_type TEXT NOT NULL,
                title TEXT,
                last_fetched TEXT,
                last_updated TEXT,
                fetch_interval_hours INTEGER NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(source_type)"
        )
        self.conn.commit()

    def _migrate_from_json(self):
        row = self.conn.execute("SELECT COUNT(1) AS c FROM sources").fetchone()
        if row and int(row["c"]) > 0:
            return

        json_path = os.path.join(os.path.dirname(self.storage_path), "sources.json")
        if not os.path.exists(json_path):
            return

        with open(json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        now = datetime.now().isoformat()
        for source_id, src in payload.items():
            metadata = src.get("metadata")
            metadata_json = json.dumps(metadata) if metadata is not None else None
            self.conn.execute(
                """
                INSERT OR REPLACE INTO sources (
                    source_id, url, source_type, title, last_fetched, last_updated,
                    fetch_interval_hours, status, error_message, metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    src.get("url", ""),
                    src.get("source_type", ""),
                    src.get("title"),
                    src.get("last_fetched"),
                    src.get("last_updated"),
                    int(src.get("fetch_interval_hours", 24) or 24),
                    src.get("status", "pending"),
                    src.get("error_message"),
                    metadata_json,
                    now,
                    now,
                ),
            )
        self.conn.commit()

    def _row_to_source(self, row: sqlite3.Row) -> ContentSource:
        metadata = row["metadata"]
        parsed_metadata = None
        if metadata:
            try:
                parsed_metadata = json.loads(metadata)
            except Exception:
                parsed_metadata = None

        return ContentSource(
            source_id=row["source_id"],
            url=row["url"],
            source_type=row["source_type"],
            title=row["title"],
            last_fetched=row["last_fetched"],
            last_updated=row["last_updated"],
            fetch_interval_hours=int(row["fetch_interval_hours"]),
            status=row["status"],
            error_message=row["error_message"],
            metadata=parsed_metadata,
        )

    def add_source(
        self,
        url: str,
        source_type: str,
        title: Optional[str] = None,
        fetch_interval_hours: int = 24,
        metadata: Optional[Dict] = None,
        source_key: Optional[str] = None,
    ) -> str:
        import hashlib

        hash_input = source_key or url
        source_id = hashlib.md5(hash_input.encode()).hexdigest()[:12]
        now = datetime.now().isoformat()
        metadata_json = json.dumps(metadata) if metadata is not None else None

        self.conn.execute(
            """
            INSERT OR REPLACE INTO sources (
                source_id, url, source_type, title, last_fetched, last_updated,
                fetch_interval_hours, status, error_message, metadata, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                url,
                source_type,
                title or url,
                None,
                None,
                int(fetch_interval_hours),
                "pending",
                None,
                metadata_json,
                now,
                now,
            ),
        )
        self.conn.commit()
        return source_id

    def add_youtube(
        self,
        url: str,
        title: Optional[str] = None,
        fetch_interval_hours: int = 24,
        metadata: Optional[Dict] = None,
    ) -> str:
        track_id = None
        if metadata and isinstance(metadata, dict):
            track_id = metadata.get("track_id")
        source_key = f"{url}::{track_id}" if track_id else url
        return self.add_source(
            url,
            "youtube",
            title,
            fetch_interval_hours,
            metadata,
            source_key=source_key,
        )

    def add_html(
        self, url: str, title: Optional[str] = None, fetch_interval_hours: int = 24
    ) -> str:
        return self.add_source(url, "html", title, fetch_interval_hours)

    def add_pdf(
        self,
        file_path: str,
        title: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> str:
        return self.add_source(
            file_path, "pdf", title, fetch_interval_hours=0, metadata=metadata
        )

    def remove_source(self, source_id: str) -> bool:
        cur = self.conn.execute("DELETE FROM sources WHERE source_id = ?", (source_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def get_source(self, source_id: str) -> Optional[ContentSource]:
        row = self.conn.execute(
            "SELECT * FROM sources WHERE source_id = ?", (source_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_source(row)

    def get_all_sources(self, source_type: Optional[str] = None) -> List[ContentSource]:
        if source_type:
            rows = self.conn.execute(
                "SELECT * FROM sources WHERE source_type = ? ORDER BY updated_at DESC",
                (source_type,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM sources ORDER BY updated_at DESC"
            ).fetchall()
        return [self._row_to_source(r) for r in rows]

    def get_sources_needing_update(self) -> List[ContentSource]:
        from datetime import timedelta

        now = datetime.now()
        candidates = self.get_all_sources()
        sources = []

        for source in candidates:
            if source.status == "disabled":
                continue
            if source.source_type == "pdf":
                continue

            if source.last_fetched:
                last_fetch = datetime.fromisoformat(source.last_fetched)
                hours_since = (now - last_fetch).total_seconds() / 3600
                if hours_since >= source.fetch_interval_hours:
                    sources.append(source)
            else:
                sources.append(source)

        return sources

    def mark_fetched(
        self, source_id: str, success: bool = True, error: Optional[str] = None
    ):
        now = datetime.now().isoformat()
        if success:
            self.conn.execute(
                """
                UPDATE sources
                SET last_fetched = ?, last_updated = ?, status = 'active', error_message = NULL, updated_at = ?
                WHERE source_id = ?
                """,
                (now, now, now, source_id),
            )
        else:
            self.conn.execute(
                """
                UPDATE sources
                SET last_fetched = ?, status = 'error', error_message = ?, updated_at = ?
                WHERE source_id = ?
                """,
                (now, error, now, source_id),
            )
        self.conn.commit()

    def update_interval(self, source_id: str, hours: int):
        self.conn.execute(
            "UPDATE sources SET fetch_interval_hours = ?, updated_at = ? WHERE source_id = ?",
            (int(hours), datetime.now().isoformat(), source_id),
        )
        self.conn.commit()

    def toggle_source(self, source_id: str, enabled: bool):
        status = "active" if enabled else "disabled"
        self.conn.execute(
            "UPDATE sources SET status = ?, updated_at = ? WHERE source_id = ?",
            (status, datetime.now().isoformat(), source_id),
        )
        self.conn.commit()

    def set_source_metadata(self, source_id: str, metadata: Dict[str, Any]):
        self.conn.execute(
            "UPDATE sources SET metadata = ?, updated_at = ? WHERE source_id = ?",
            (json.dumps(metadata), datetime.now().isoformat(), source_id),
        )
        self.conn.commit()

    def get_stats(self) -> Dict[str, Any]:
        rows_type = self.conn.execute(
            "SELECT source_type, COUNT(1) AS c FROM sources GROUP BY source_type"
        ).fetchall()
        rows_status = self.conn.execute(
            "SELECT status, COUNT(1) AS c FROM sources GROUP BY status"
        ).fetchall()
        total = self.conn.execute("SELECT COUNT(1) AS c FROM sources").fetchone()

        by_type = {r["source_type"]: int(r["c"]) for r in rows_type}
        by_status = {r["status"]: int(r["c"]) for r in rows_status}

        return {
            "total": int(total["c"]) if total else 0,
            "by_type": by_type,
            "by_status": by_status,
            "needs_update": len(self.get_sources_needing_update()),
        }


class AutoUpdater:
    def __init__(self, source_manager: ContentSourceManager, rag_system):
        self.source_manager = source_manager
        self.rag = rag_system

    def update_source(self, source_id: str) -> Dict[str, Any]:
        source = self.source_manager.get_source(source_id)
        if not source:
            return {"error": "Source not found"}

        try:
            if source.source_type == "youtube":
                s3_audio_uri = None
                s3_transcript_json_uri = None
                track_id = None
                if source.metadata and isinstance(source.metadata, dict):
                    s3_audio_uri = source.metadata.get("s3_audio_uri")
                    s3_transcript_json_uri = source.metadata.get(
                        "s3_transcript_json_uri"
                    )
                    track_id = source.metadata.get("track_id")
                result = self.rag.content_processor.process_youtube(
                    source.url,
                    s3_audio_uri=s3_audio_uri,
                    s3_transcript_json_uri=s3_transcript_json_uri,
                    track_id=track_id,
                )
            elif source.source_type == "html":
                result = self.rag.content_processor.process_html_content(
                    self._fetch_html(source.url), source.url
                )
            elif source.source_type == "pdf":
                result = self.rag.content_processor.process(source.url)
            else:
                result = self.rag.content_processor.process(source.url)

            if result.get("chunked_documents"):
                self.rag.ingest_processed_content(result)

            self.source_manager.mark_fetched(source_id, success=True)

            return {
                "status": "success",
                "source_id": source_id,
                "documents_updated": result.get("total_chunks", 0),
            }

        except Exception as e:
            self.source_manager.mark_fetched(source_id, success=False, error=str(e))
            return {"status": "error", "source_id": source_id, "error": str(e)}

    def update_all(self) -> List[Dict[str, Any]]:
        sources = self.source_manager.get_sources_needing_update()
        results = []
        for source in sources:
            result = self.update_source(source.source_id)
            results.append(result)
        return results

    def _fetch_html(self, url: str) -> str:
        import requests

        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.text
