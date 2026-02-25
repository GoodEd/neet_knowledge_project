from pathlib import Path
from typing import Dict, Any, List, Optional, Union
import re

from .pdf_processor import PDFProcessor, DocumentChunker
from .youtube_processor import YouTubeProcessor
from .text_processor import TextProcessor, MarkdownProcessor
from .html_processor import HTMLProcessor
from .video_processor import VideoProcessor, AudioProcessor


class ContentProcessor:
    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        ocr_enabled: bool = True,
        ocr_language: str = "eng+hin",
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        self.pdf_processor = PDFProcessor(ocr_enabled, ocr_language)
        self.youtube_processor = YouTubeProcessor()
        self.text_processor = TextProcessor()
        self.markdown_processor = MarkdownProcessor()
        self.html_processor = HTMLProcessor()
        self.video_processor = VideoProcessor()
        self.audio_processor = AudioProcessor()

        self.chunker = DocumentChunker(chunk_size, chunk_overlap)

    def process(self, file_path: str) -> Dict[str, Any]:
        file_path_obj = Path(file_path)
        extension = file_path_obj.suffix.lower()

        processor_map = {
            ".pdf": self.pdf_processor,
            ".txt": self.text_processor,
            ".md": self.markdown_processor,
            ".markdown": self.markdown_processor,
            ".html": self.html_processor,
            ".htm": self.html_processor,
            ".mp4": self.video_processor,
            ".avi": self.video_processor,
            ".mov": self.video_processor,
            ".mkv": self.video_processor,
            ".webm": self.video_processor,
            ".mp3": self.audio_processor,
            ".wav": self.audio_processor,
            ".flac": self.audio_processor,
            ".m4a": self.audio_processor,
        }

        processor = processor_map.get(extension)

        if processor is None and not self._is_url(file_path):
            raise ValueError(f"Unsupported file type: {extension}")

        if self._is_url(file_path):
            if "youtube.com" in file_path or "youtu.be" in file_path:
                result = self.youtube_processor.process(file_path)
            elif file_path.startswith("http"):
                result = self.html_processor.process_url(file_path)
            else:
                raise ValueError(f"Unsupported URL: {file_path}")
        else:
            result = processor.process(file_path)

        if result.get("documents"):
            chunked = self.chunker.chunk_documents(result["documents"])
            result["chunked_documents"] = chunked
            result["total_chunks"] = len(chunked)

        return result

    def process_youtube(
        self,
        video_url: str,
        s3_audio_uri: Optional[str] = None,
        s3_transcript_json_uri: Optional[str] = None,
        track_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = self.youtube_processor.process(
            video_url,
            s3_audio_uri=s3_audio_uri,
            s3_transcript_json_uri=s3_transcript_json_uri,
            track_id=track_id,
        )

        # YoutubeProcessor already returns chunked documents effectively,
        # but if we want to apply standard chunker:
        # Note: YoutubeProcessor returns a dict now

        if result.get("documents"):
            # If documents are already chunked/processed, we might skip re-chunking
            # or we can pass them through if needed.
            # Currently YouTubeProcessor chunks them.
            result["chunked_documents"] = self._doc_to_dict(result["documents"])
            result["total_chunks"] = len(result["documents"])

        return result

    def _doc_to_dict(self, docs):
        """Helper to convert LangChain Documents to list of dicts."""
        return [
            {
                "content": doc.page_content,
                "source": doc.metadata.get("source", ""),
                "content_type": doc.metadata.get("source_type", "youtube"),
                "source_type": doc.metadata.get("source_type", "youtube"),
                "start_time": doc.metadata.get("start_time", 0),
                "timestamp": doc.metadata.get("start_time", 0),
                "track_id": doc.metadata.get("track_id", ""),
                "title": doc.metadata.get("title", ""),
                "video_id": doc.metadata.get("video_id", ""),
                "source_id": doc.metadata.get("source_id", ""),
            }
            for doc in docs
        ]

    def process_text(self, text: str, source: str = "raw") -> Dict[str, Any]:
        result = self.text_processor.process_raw(text, source)

        if result.get("documents"):
            chunked = self.chunker.chunk_documents(result["documents"])
            result["chunked_documents"] = chunked
            result["total_chunks"] = len(chunked)

        return result

    def process_html_content(self, html: str, source: str = "html") -> Dict[str, Any]:
        result = self.html_processor.extract_main_content(html, source)

        if result.get("documents"):
            chunked = self.chunker.chunk_documents(result["documents"])
            result["chunked_documents"] = chunked
            result["total_chunks"] = len(chunked)

        return result

    def _is_url(self, path: str) -> bool:
        url_pattern = re.compile(
            r"^https?://"
            r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"
            r"localhost|"
            r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
            r"(?::\d+)?"
            r"(?:/?|[/?]\S+)$",
            re.IGNORECASE,
        )

        return bool(url_pattern.match(path))

    def get_supported_types(self) -> Dict[str, List[str]]:
        return {
            "documents": [".pdf"],
            "text": [".txt", ".md", ".markdown"],
            "web": [".html", ".htm"],
            "video": [".mp4", ".avi", ".mov", ".mkv", ".webm"],
            "audio": [".mp3", ".wav", ".flac", ".m4a"],
            "url": ["YouTube URLs", "HTTP/HTTPS URLs"],
        }
