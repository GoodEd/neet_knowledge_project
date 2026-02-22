import os
import re
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from langchain_core.documents import Document

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class YouTubeProcessor:
    """
    Processor for YouTube videos using transcript APIs.
    Can optionally use Google API Key for metadata if available.
    """

    def __init__(self):
        """Initialize the YouTube processor."""
        self.api_key = os.getenv("YOUTUBE_API_KEY")
        self.youtube_client = None
        if self.api_key:
            try:
                from googleapiclient.discovery import build

                self.youtube_client = build("youtube", "v3", developerKey=self.api_key)
                logger.info("YouTube Data API client initialized.")
            except Exception as e:
                logger.warning(f"Failed to initialize YouTube Data API: {e}")

    def process(
        self,
        url: str,
        s3_audio_uri: Optional[str] = None,
        s3_transcript_json_uri: Optional[str] = None,
        track_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a YouTube video URL and return a result dictionary.

        Args:
            url: The YouTube video URL

        Returns:
            Dict[str, Any]: Dictionary containing 'documents', 'source', etc.
        """
        video_id = self._extract_video_id(url)
        if not video_id:
            raise ValueError(f"Invalid YouTube URL: {url}")

        logger.info(f"Processing YouTube video: {video_id}")

        # 1. Fetch Metadata (Prefer API if available)
        video_title = "Unknown Video"
        if self.youtube_client:
            metadata = self._get_metadata_from_api(video_id)
            if metadata:
                video_title = metadata.get("title", video_title)

        transcript_data = []
        transcript_origin = ""
        error_msg = "No transcript produced"

        if s3_audio_uri and s3_transcript_json_uri:
            logger.info(
                "Both S3 audio and S3 transcript provided; skipping YouTube transcript/download paths and using S3 audio transcription only"
            )
            try:
                transcript_data = self._transcribe_from_s3_audio(
                    s3_audio_uri=s3_audio_uri,
                    video_title=video_title,
                    track_id=track_id or "s3_audio_asr",
                )
                transcript_origin = "s3_audio_forced"
                self._persist_transcript_snapshot(
                    transcript_data=transcript_data,
                    url=url,
                    video_id=video_id,
                    origin=transcript_origin,
                )
                documents = self._create_documents(transcript_data, url, video_id)
                return {
                    "documents": documents,
                    "source": url,
                    "video_id": video_id,
                    "total_chunks": len(documents),
                    "processed_at": datetime.now().isoformat(),
                }
            except Exception as e:
                error_msg = str(e)
                logger.error(f"S3 audio transcription failed: {e}")
                raise RuntimeError(f"Failed to fetch transcript: {error_msg}")
        else:
            try:
                transcript_data = self._get_transcript_with_api(
                    video_id,
                    video_title,
                    track_id=track_id or "yt_api",
                )
                transcript_origin = "youtube_transcript_api"

                if self.youtube_client and video_title != "Unknown Video":
                    for entry in transcript_data:
                        entry["video_title"] = video_title

                if not transcript_data:
                    raise RuntimeError(f"No transcript available for video: {video_id}")

                self._persist_transcript_snapshot(
                    transcript_data=transcript_data,
                    url=url,
                    video_id=video_id,
                    origin=transcript_origin,
                )

                documents = self._create_documents(transcript_data, url, video_id)

                return {
                    "documents": documents,
                    "source": url,
                    "video_id": video_id,
                    "total_chunks": len(documents),
                    "processed_at": datetime.now().isoformat(),
                }

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error processing YouTube video {url}: {error_msg}")

        logger.info("Falling back to audio/transcript alternatives.")

        try:
            transcript_data = self._transcribe_from_ytdlp_audio(
                url=url,
                video_title=video_title,
                track_id=track_id or "yt_audio_asr",
            )
            if transcript_data:
                transcript_origin = "yt_dlp_audio_asr"
        except Exception as e:
            logger.error(f"yt-dlp audio fallback failed: {e}")

        if not transcript_data and s3_transcript_json_uri:
            try:
                transcript_data = self._load_transcript_from_s3_json(
                    s3_transcript_json_uri=s3_transcript_json_uri,
                    video_title=video_title,
                    track_id=track_id or "s3_transcript",
                )
                if transcript_data:
                    transcript_origin = "s3_transcript_json"
            except Exception as e:
                logger.error(f"S3 transcript JSON fallback failed: {e}")

        if not transcript_data and s3_audio_uri:
            try:
                transcript_data = self._transcribe_from_s3_audio(
                    s3_audio_uri=s3_audio_uri,
                    video_title=video_title,
                    track_id=track_id or "s3_audio_asr",
                )
                if transcript_data:
                    transcript_origin = "s3_audio_asr"
            except Exception as e:
                logger.error(f"S3 audio fallback failed: {e}")

        if transcript_data:
            self._persist_transcript_snapshot(
                transcript_data=transcript_data,
                url=url,
                video_id=video_id,
                origin=transcript_origin or "fallback_unknown",
            )
            documents = self._create_documents(transcript_data, url, video_id)
            return {
                "documents": documents,
                "source": url,
                "video_id": video_id,
                "total_chunks": len(documents),
                "processed_at": datetime.now().isoformat(),
            }

        raise RuntimeError(f"Failed to fetch transcript: {error_msg}")

    def _persist_transcript_snapshot(
        self,
        transcript_data: List[Dict[str, Any]],
        url: str,
        video_id: str,
        origin: str,
    ) -> Optional[str]:
        if not transcript_data:
            return None

        data_dir = os.environ.get("DATA_DIR", "./data")
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S_%fZ")
        safe_origin = re.sub(r"[^A-Za-z0-9_.-]+", "_", origin or "unknown")
        snapshot_dir = os.path.join(
            data_dir,
            "content",
            "youtube_transcripts",
            video_id,
            timestamp,
        )
        os.makedirs(snapshot_dir, exist_ok=True)

        payload = {
            "video_id": video_id,
            "source": url,
            "origin": origin,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "segment_count": len(transcript_data),
            "segments": transcript_data,
        }

        output_path = os.path.join(snapshot_dir, f"{safe_origin}.json")
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info(
                "Saved transcript snapshot to %s (segments=%s)",
                output_path,
                len(transcript_data),
            )
            return output_path
        except Exception as e:
            logger.warning("Failed to persist transcript snapshot: %s", e)
            return None

    def _load_transcript_from_s3_json(
        self, s3_transcript_json_uri: str, video_title: str, track_id: str
    ) -> List[Dict[str, Any]]:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            local_name = os.path.basename(s3_transcript_json_uri.split("?")[0])
            local_path = os.path.join(tmpdir, local_name or "transcript.json")
            self._download_remote_file(s3_transcript_json_uri, local_path)
            with open(local_path, "r", encoding="utf-8") as f:
                payload = json.load(f)

        if isinstance(payload, dict):
            segments = payload.get("segments") or payload.get("transcript") or []
        elif isinstance(payload, list):
            segments = payload
        else:
            segments = []

        transcript_entries = self._normalize_transcript_entries(
            segments, video_title, track_id
        )
        if not transcript_entries:
            raise RuntimeError("No transcript segments found in S3 JSON")

        return transcript_entries

    def _normalize_transcript_entries(
        self, segments: List[Dict[str, Any]], video_title: str, track_id: str
    ) -> List[Dict[str, Any]]:
        entries = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            text = (
                segment.get("text")
                or segment.get("content")
                or segment.get("caption")
                or ""
            )
            text = text.strip()
            if not text:
                continue
            start = segment.get("start")
            if start is None:
                start = segment.get("start_time", 0.0)
            duration = segment.get("duration")
            if duration is None:
                end = segment.get("end")
                if end is None:
                    end = segment.get("end_time")
                if end is not None:
                    duration = float(end) - float(start or 0.0)
                else:
                    duration = 0.0

            entries.append(
                {
                    "text": text,
                    "start": float(start or 0.0),
                    "duration": float(duration or 0.0),
                    "video_title": video_title,
                    "track_id": track_id,
                }
            )
        return entries

    def _get_transcript_with_api(
        self, video_id: str, video_title: str, track_id: str
    ) -> List[Dict[str, Any]]:
        preferred_languages = ["en", "en-IN", "hi", "hi-IN"]

        try:
            transcript_list = YouTubeTranscriptApi().list(video_id)
        except Exception as e:
            logger.error(f"YouTube transcript list failed: {e}")
            raise RuntimeError(f"Failed to fetch transcript for video: {video_id}")

        selected = None
        for lang in preferred_languages:
            try:
                selected = transcript_list.find_transcript([lang])
                break
            except Exception:
                pass
            try:
                selected = transcript_list.find_generated_transcript([lang])
                break
            except Exception:
                pass

        if selected is None:
            try:
                selected = next(iter(transcript_list))
            except Exception:
                selected = None

        if selected is None:
            raise RuntimeError(f"No transcript available for video: {video_id}")

        try:
            raw_segments = selected.fetch()
        except Exception as e:
            logger.error(f"Transcript fetch failed: {e}")
            raise RuntimeError(f"Failed to fetch transcript for video: {video_id}")

        transcript_entries = []
        for segment in raw_segments:
            text = (getattr(segment, "text", "") or "").strip()
            if not text:
                continue
            start = float(getattr(segment, "start", 0.0) or 0.0)
            duration = float(getattr(segment, "duration", 0.0) or 0.0)
            transcript_entries.append(
                {
                    "text": text,
                    "start": start,
                    "duration": duration,
                    "video_title": video_title,
                    "track_id": track_id,
                }
            )

        if not transcript_entries:
            raise RuntimeError(f"Empty transcript for video: {video_id}")

        return transcript_entries

    def _transcribe_from_s3_audio(
        self, s3_audio_uri: str, video_title: str, track_id: str
    ) -> List[Dict[str, Any]]:
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = os.path.join(tmpdir, "audio.mp3")
            self._download_remote_file(s3_audio_uri, local_path)
            return self._transcribe_audio_file_with_multimodal(
                local_path, video_title, track_id
            )

    def _download_remote_file(self, uri: str, local_path: str):
        from urllib.parse import urlparse, unquote

        def _download_s3(bucket: str, key: str):
            import boto3

            s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION"))
            s3.download_file(bucket, key, local_path)

        if uri.startswith("s3://"):
            match = re.match(r"^s3://([^/]+)/(.+)$", uri)
            if not match:
                raise ValueError(f"Invalid S3 URI: {uri}")
            bucket = match.group(1)
            key = match.group(2)
            _download_s3(bucket, key)
            return

        if uri.startswith("http://") or uri.startswith("https://"):
            parsed = urlparse(uri)
            host = parsed.netloc
            path = parsed.path.lstrip("/")

            # Handle S3 virtual-hosted style and path-style URLs via IAM auth
            vh_match = re.match(r"^([^.]+)\.s3[.-][^.]+\.amazonaws\.com$", host)
            if vh_match and path:
                bucket = vh_match.group(1)
                decoded_path = unquote(path)
                try:
                    _download_s3(bucket, decoded_path)
                except Exception:
                    _download_s3(bucket, path)
                return

            if host.startswith("s3.") and ".amazonaws.com" in host and "/" in path:
                parts = path.split("/", 1)
                if len(parts) == 2 and parts[0] and parts[1]:
                    bucket = unquote(parts[0])
                    decoded_key = unquote(parts[1])
                    try:
                        _download_s3(bucket, decoded_key)
                    except Exception:
                        _download_s3(bucket, parts[1])
                    return

            import requests

            response = requests.get(uri, timeout=120)
            response.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(response.content)
            return

        raise ValueError(f"Unsupported URI format: {uri}")

    def _transcribe_from_ytdlp_audio(
        self, url: str, video_title: str, track_id: str
    ) -> List[Dict[str, Any]]:
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "audio")
            ydl_opts = {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "128",
                    }
                ],
                "outtmpl": audio_path,
                "quiet": True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            final_audio_path = audio_path + ".mp3"
            if not os.path.exists(final_audio_path):
                raise RuntimeError("Audio file not found after yt-dlp download")

            return self._transcribe_audio_file_with_multimodal(
                final_audio_path, video_title, track_id
            )

    def _transcribe_audio_file_with_multimodal(
        self, audio_path: str, video_title: str, track_id: str
    ) -> List[Dict[str, Any]]:
        import base64
        import subprocess
        import tempfile
        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
        model = os.getenv("OPENAI_MODEL_NAME", "google/gemini-2.0-flash-001")

        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for audio transcription")

        client = OpenAI(api_key=api_key, base_url=base_url)

        prompt = (
            "Transcribe this Hinglish/English/Hindi audio verbatim and return ONLY valid JSON array "
            'with keys "text", "start", "duration". '
            "Do not translate content. Keep technical NEET terms, formulas, symbols, units, and Latin letters in English script. "
            "Examples to keep in English: work done, pressure, delta V, radius, ratio, displacement, cross-sectional area, pi r^2, F=ma. "
            "Do not wrap output in markdown fences."
        )

        max_chunk_seconds = int(os.getenv("AUDIO_TRANSCRIBE_CHUNK_SECONDS", "480"))
        transcript_entries: List[Dict[str, Any]] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            chunk_pattern = os.path.join(tmpdir, "chunk%03d.mp3")
            try:
                subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        audio_path,
                        "-f",
                        "segment",
                        "-segment_time",
                        str(max_chunk_seconds),
                        "-c",
                        "copy",
                        chunk_pattern,
                    ],
                    check=True,
                )
                chunk_paths = sorted(
                    [
                        os.path.join(tmpdir, p)
                        for p in os.listdir(tmpdir)
                        if p.startswith("chunk") and p.endswith(".mp3")
                    ]
                )
            except Exception:
                chunk_paths = []

            if not chunk_paths:
                chunk_paths = [audio_path]

            for idx, chunk_path in enumerate(chunk_paths):
                with open(chunk_path, "rb") as audio_file:
                    encoded_string = base64.b64encode(audio_file.read()).decode("utf-8")

                segments = self._request_transcript_segments(
                    client=client,
                    model=model,
                    prompt=prompt,
                    encoded_audio=encoded_string,
                )
                if isinstance(segments, list):
                    chunk_entries = self._normalize_transcript_entries(
                        segments, video_title, track_id
                    )
                    offset = float(idx * max_chunk_seconds)
                    for entry in chunk_entries:
                        entry["start"] = float(entry.get("start", 0.0)) + offset
                    transcript_entries.extend(chunk_entries)

        if not transcript_entries:
            raise RuntimeError("No transcript segments produced from audio")

        if os.getenv("NORMALIZE_TECH_TERMS", "true").lower() == "true":
            for entry in transcript_entries:
                entry["text"] = self._normalize_technical_text(entry.get("text", ""))

        return transcript_entries

    def _normalize_technical_text(self, text: str) -> str:
        if not text:
            return text

        replacements = [
            (r"\bवर्क\s*डन\b", "work done"),
            (r"\bफॉर्मूला\b", "formula"),
            (r"\bप्रोसेस\b", "process"),
            (r"\bप्रेशर\b", "pressure"),
            (r"\bकांस्टेंट\s*प्रेशर\b", "constant pressure"),
            (r"\bडेल्टा\s*v\b", "delta v"),
            (r"\bरेडियस\b", "radius"),
            (r"\bरेशियो\b", "ratio"),
            (r"\bडिस्प्लेसमेंट\b", "displacement"),
            (r"\bक्रॉस\s*सेक्शन\s*एरिया\b", "cross-sectional area"),
            (r"\bपिस्टन\b", "piston"),
            (r"\bवॉल्यूम\b", "volume"),
            (r"\bप्रपोर्शनल\b", "proportional"),
        ]

        out = text
        for pattern, repl in replacements:
            out = re.sub(pattern, repl, out, flags=re.IGNORECASE)

        out = re.sub(r"\bpi\s*r\s*\^?\s*2\b", "pi r^2", out, flags=re.IGNORECASE)
        return out

    def _request_transcript_segments(
        self,
        client,
        model: str,
        prompt: str,
        encoded_audio: str,
    ) -> List[Dict[str, Any]]:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "input_audio",
                            "input_audio": {"data": encoded_audio, "format": "mp3"},
                        },
                    ],
                }
            ],
        )

        content = response.choices[0].message.content
        if not content:
            return []

        if not isinstance(content, str):
            try:
                content = json.dumps(content, ensure_ascii=False)
            except Exception:
                content = str(content)

        logger.info(
            "Transcription model raw output (len=%s): %s", len(content), content[:4000]
        )
        return self._parse_segments_json(content)

    def _parse_segments_json(self, content: str) -> List[Dict[str, Any]]:
        text = content.strip()
        if text.startswith("```json"):
            text = text.replace("```json", "").replace("```", "").strip()
        elif text.startswith("```"):
            text = text.replace("```", "").strip()

        candidates = [text]

        left = text.find("[")
        right = text.rfind("]")
        if left != -1 and right != -1 and right > left:
            candidates.append(text[left : right + 1])

        cleaned = "".join(ch for ch in text if ord(ch) >= 32 or ch in "\n\r\t")
        candidates.append(cleaned)

        if left != -1 and right != -1 and right > left:
            chunk = cleaned[left : right + 1]
            candidates.append(chunk)

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict):
                    maybe = parsed.get("segments") or parsed.get("transcript")
                    if isinstance(maybe, list):
                        return maybe
            except Exception:
                continue

        # Fallback: treat model output as plain transcript text
        fallback_text = re.sub(r"\s+", " ", text).strip()
        if fallback_text:
            return [{"text": fallback_text, "start": 0, "duration": 0}]

        raise RuntimeError("Unable to parse transcript JSON from model output")

    def _get_metadata_from_api(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Fetch video metadata using official YouTube Data API."""
        if not self.youtube_client:
            return None
        try:
            request = self.youtube_client.videos().list(
                part="snippet,contentDetails", id=video_id
            )
            response = request.execute()

            if "items" in response and len(response["items"]) > 0:
                snippet = response["items"][0]["snippet"]
                return {
                    "title": snippet.get("title"),
                    "description": snippet.get("description"),
                    "channel": snippet.get("channelTitle"),
                    "published_at": snippet.get("publishedAt"),
                }
        except Exception as e:
            logger.warning(f"YouTube API metadata fetch failed: {e}")
        return None

    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from YouTube URL."""
        # Handle various YouTube URL formats
        patterns = [
            r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
            r"(?:embed\/|v\/|youtu.be\/)([0-9A-Za-z_-]{11})",
            r"^([0-9A-Za-z_-]{11})$",
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def _get_mock_transcript(self, video_id: str) -> List[Dict[str, Any]]:
        """Return mock transcript for testing when YT is blocked."""
        # Mock for Khan Academy Newton's Laws - keeping only one ID for testing if needed
        if video_id in ["8mO00wEKKTE"]:
            return [
                {
                    "text": "Hello everyone, welcome to this video on Newton's Laws of Motion.",
                    "start": 0.0,
                    "duration": 5.0,
                    "video_title": "NEET Physics - Newtons Laws",
                },
                {
                    "text": "Let's start with the Second Law of Motion.",
                    "start": 5.0,
                    "duration": 4.0,
                    "video_title": "NEET Physics - Newtons Laws",
                },
                {
                    "text": "Newton's second law states that Force equals mass times acceleration. F = ma.",
                    "start": 9.0,
                    "duration": 6.0,
                    "video_title": "NEET Physics - Newtons Laws",
                },
                {
                    "text": "So if you have a body of mass 10kg and you apply a force of 100N,",
                    "start": 15.0,
                    "duration": 5.0,
                    "video_title": "NEET Physics - Newtons Laws",
                },
                {
                    "text": "the acceleration produced will be Force divided by mass.",
                    "start": 20.0,
                    "duration": 4.0,
                    "video_title": "NEET Physics - Newtons Laws",
                },
                {
                    "text": "100 Newtons divided by 10 kg gives us 10 meters per second squared.",
                    "start": 24.0,
                    "duration": 5.0,
                    "video_title": "NEET Physics - Newtons Laws",
                },
                {
                    "text": "Now, what happens if we double the mass while keeping the force constant?",
                    "start": 30.0,
                    "duration": 5.0,
                    "video_title": "NEET Physics - Newtons Laws",
                },
                {
                    "text": "Since acceleration is inversely proportional to mass (a = F/m),",
                    "start": 35.0,
                    "duration": 5.0,
                    "video_title": "NEET Physics - Newtons Laws",
                },
                {
                    "text": "doubling the mass will result in the acceleration being halved.",
                    "start": 40.0,
                    "duration": 4.0,
                    "video_title": "NEET Physics - Newtons Laws",
                },
                {
                    "text": "This is a very important concept for NEET 2025.",
                    "start": 44.0,
                    "duration": 3.0,
                    "video_title": "NEET Physics - Newtons Laws",
                },
            ]
        return []

    def _create_documents(
        self, transcript_data: List[Dict[str, Any]], url: str, video_id: str
    ) -> List[Document]:
        documents = []
        if not transcript_data:
            return documents

        from src.utils.config import Config

        config = Config()
        chunk_size = config.get("processing.chunk_size", 1000)
        chunk_overlap = config.get("processing.chunk_overlap", 200)

        video_title = transcript_data[0].get("video_title", "Unknown Video")

        i = 0
        while i < len(transcript_data):
            chunk_text_parts = []
            chunk_start_time = transcript_data[i]["start"]
            chunk_length = 0

            j = i
            while j < len(transcript_data):
                text = transcript_data[j]["text"]
                text_len = len(text)

                if chunk_length + text_len > chunk_size and chunk_text_parts:
                    break

                chunk_text_parts.append(text)
                chunk_length += text_len
                j += 1

            chunk_text = " ".join(chunk_text_parts)
            meta = {
                "source": url,
                "video_id": video_id,
                "title": video_title,
                "start_time": chunk_start_time,
                "source_type": "youtube",
                "track_id": transcript_data[i].get("track_id", ""),
            }
            documents.append(Document(page_content=chunk_text, metadata=meta))

            if j == len(transcript_data):
                break

            chars_to_advance = max(1, chunk_length - chunk_overlap)

            advanced_chars = 0
            next_i = i
            while next_i < j and advanced_chars < chars_to_advance:
                advanced_chars += len(transcript_data[next_i]["text"])
                next_i += 1

            if next_i == i:
                next_i += 1

            i = next_i

        return documents

        # Get chunk settings from config or defaults
        from src.utils.config import Config

        config = Config()
        chunk_size = config.get("processing.chunk_size", 1000)
        chunk_overlap = config.get("processing.chunk_overlap", 200)

        video_title = transcript_data[0].get("video_title", "Unknown Video")

        # Accumulate full text with mapping to timestamps
        full_text_segments = []
        full_text = ""

        # Build a single string but keep track of start times for each segment
        # This is a simplification; for precise timestamps per chunk, we need better mapping.
        # Strategy:
        # 1. Iterate through transcript segments.
        # 2. Accumulate text.
        # 3. Use RecursiveCharacterTextSplitter on the full text (best for semantic context).
        # 4. Map chunk start index back to timestamp (approximate but workable).

        # Better Strategy for Audio:
        # Accumulate segments until chunk_size is reached, but maintain an overlap window.

        current_chunk_segments = []
        current_chunk_len = 0

        # We need a sliding window approach over segments
        # But segments vary in length.
        # Let's stick to the current logic but add overlap capability.

        i = 0
        while i < len(transcript_data):
            chunk_text_parts = []
            chunk_start_time = transcript_data[i]["start"]
            chunk_length = 0

            # Start a new chunk from index i
            j = i
            while j < len(transcript_data):
                text = transcript_data[j]["text"]
                text_len = len(text)

                # If adding this segment exceeds chunk_size AND we have at least one segment
                if chunk_length + text_len > chunk_size and chunk_text_parts:
                    break

                chunk_text_parts.append(text)
                chunk_length += text_len
                j += 1

            # Create document for this window
            chunk_text = " ".join(chunk_text_parts)
            meta = {
                "source": url,
                "video_id": video_id,
                "title": video_title,
                "start_time": chunk_start_time,
                "source_type": "youtube",
            }
            documents.append(Document(page_content=chunk_text, metadata=meta))

            # Advance i.
            # If no overlap, we'd set i = j.
            # With overlap, we want to start the next chunk 'chunk_overlap' characters *before* the end of this chunk.
            # But we are working with discrete segments.
            # Let's find the segment index that starts closest to (chunk_length - overlap) from the current start.

            if j == len(transcript_data):
                break  # Done processing

            # Calculate where the next chunk should conceptually start to satisfy overlap
            chars_to_advance = max(1, chunk_length - chunk_overlap)

            # Find how many segments cover 'chars_to_advance'
            advanced_chars = 0
            next_i = i
            while next_i < j and advanced_chars < chars_to_advance:
                advanced_chars += len(transcript_data[next_i]["text"])
                next_i += 1

            # Ensure we always advance at least one segment to avoid infinite loops if segments are huge
            if next_i == i:
                next_i += 1

            i = next_i

        return documents
