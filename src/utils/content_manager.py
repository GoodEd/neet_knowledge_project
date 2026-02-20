import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict


@dataclass
class ContentSource:
    source_id: str
    url: str
    source_type: str  # youtube, html, pdf, text
    title: Optional[str] = None
    last_fetched: Optional[str] = None
    last_updated: Optional[str] = None
    fetch_interval_hours: int = 24
    status: str = "pending"  # pending, active, error, disabled
    error_message: Optional[str] = None
    metadata: Optional[Dict] = None


class ContentSourceManager:
    def __init__(self, storage_path: str = None):
        self.storage_path = storage_path or os.path.join(
            os.environ.get("DATA_DIR", "./data"), "sources.json"
        )
        self.sources: Dict[str, ContentSource] = {}
        self._load()

    def _load(self):
        if os.path.exists(self.storage_path):
            with open(self.storage_path, "r") as f:
                data = json.load(f)
                for source_id, source_data in data.items():
                    self.sources[source_id] = ContentSource(**source_data)

    def _save(self):
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        data = {source_id: asdict(src) for source_id, src in self.sources.items()}
        with open(self.storage_path, "w") as f:
            json.dump(data, f, indent=2)

    def add_source(
        self,
        url: str,
        source_type: str,
        title: Optional[str] = None,
        fetch_interval_hours: int = 24,
        metadata: Optional[Dict] = None,
    ) -> str:
        import hashlib

        source_id = hashlib.md5(url.encode()).hexdigest()[:12]

        self.sources[source_id] = ContentSource(
            source_id=source_id,
            url=url,
            source_type=source_type,
            title=title or url,
            fetch_interval_hours=fetch_interval_hours,
            status="pending",
            metadata=metadata,
        )
        self._save()
        return source_id

    def add_youtube(
        self,
        url: str,
        title: Optional[str] = None,
        fetch_interval_hours: int = 24,
        metadata: Optional[Dict] = None,
    ) -> str:
        return self.add_source(url, "youtube", title, fetch_interval_hours, metadata)

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
        if source_id in self.sources:
            del self.sources[source_id]
            self._save()
            return True
        return False

    def get_source(self, source_id: str) -> Optional[ContentSource]:
        return self.sources.get(source_id)

    def get_all_sources(self, source_type: Optional[str] = None) -> List[ContentSource]:
        sources = list(self.sources.values())
        if source_type:
            sources = [s for s in sources if s.source_type == source_type]
        return sources

    def get_sources_needing_update(self) -> List[ContentSource]:
        from datetime import timedelta

        sources = []
        now = datetime.now()

        for source in self.sources.values():
            if source.status == "disabled":
                continue
            if source.source_type == "pdf":
                continue  # PDFs are static

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
        if source_id in self.sources:
            self.sources[source_id].last_fetched = datetime.now().isoformat()
            if success:
                self.sources[source_id].status = "active"
                self.sources[source_id].last_updated = datetime.now().isoformat()
                self.sources[source_id].error_message = None
            else:
                self.sources[source_id].status = "error"
                self.sources[source_id].error_message = error
            self._save()

    def update_interval(self, source_id: str, hours: int):
        if source_id in self.sources:
            self.sources[source_id].fetch_interval_hours = hours
            self._save()

    def toggle_source(self, source_id: str, enabled: bool):
        if source_id in self.sources:
            self.sources[source_id].status = "active" if enabled else "disabled"
            self._save()

    def set_source_metadata(self, source_id: str, metadata: Dict[str, Any]):
        if source_id in self.sources:
            self.sources[source_id].metadata = metadata
            self._save()

    def get_stats(self) -> Dict[str, Any]:
        stats = {
            "total": len(self.sources),
            "by_type": {},
            "by_status": {},
            "needs_update": len(self.get_sources_needing_update()),
        }

        for source in self.sources.values():
            stats["by_type"][source.source_type] = (
                stats["by_type"].get(source.source_type, 0) + 1
            )
            stats["by_status"][source.status] = (
                stats["by_status"].get(source.status, 0) + 1
            )

        return stats


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
                if source.metadata and isinstance(source.metadata, dict):
                    s3_audio_uri = source.metadata.get("s3_audio_uri")
                result = self.rag.content_processor.process_youtube(
                    source.url, s3_audio_uri=s3_audio_uri
                )
            elif source.source_type == "html":
                result = self.rag.content_processor.process_html_content(
                    self._fetch_html(source.url), source.url
                )
            elif source.source_type == "pdf":
                result = self.rag.content_processor.process(source.url)
            else:
                result = self.rag.content_processor.process(source.url)

            # Re-ingest to vector store
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
