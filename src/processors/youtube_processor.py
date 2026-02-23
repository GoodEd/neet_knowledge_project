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

        prefer_yt_api = (
            os.getenv("PREFER_YT_API_FIRST", "false").strip().lower() == "true"
        )
        strict_yt_api_only = (track_id or "").startswith("yt_api")
        backup_track_id = (
            "backup_transcript" if strict_yt_api_only else (track_id or "yt_audio_asr")
        )

        if strict_yt_api_only and s3_transcript_json_uri:
            logger.info(
                "yt_api track with S3 transcript JSON; using S3 transcript directly before YouTube API"
            )
            try:
                transcript_data = self._load_transcript_from_s3_json(
                    s3_transcript_json_uri=s3_transcript_json_uri,
                    video_title=video_title,
                    track_id=track_id or "yt_api",
                )
                transcript_origin = "s3_transcript_json"
                self._persist_transcript_snapshot(
                    transcript_data=transcript_data,
                    url=url,
                    video_id=video_id,
                    origin=transcript_origin,
                )
                documents = self._create_documents(transcript_data, url, video_id)
                documents = self._maybe_add_backup_transcript_docs(
                    documents=documents,
                    url=url,
                    video_id=video_id,
                    video_title=video_title,
                    track_id=track_id,
                    s3_audio_uri=s3_audio_uri,
                )
                return {
                    "documents": documents,
                    "source": url,
                    "video_id": video_id,
                    "total_chunks": len(documents),
                    "processed_at": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.warning(
                    "S3 transcript JSON unavailable for yt_api track, skipping YouTube API and using backup transcript flow: %s",
                    e,
                )

        if prefer_yt_api:
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
                documents = self._maybe_add_backup_transcript_docs(
                    documents=documents,
                    url=url,
                    video_id=video_id,
                    video_title=video_title,
                    track_id=track_id,
                    s3_audio_uri=s3_audio_uri,
                )

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
                if strict_yt_api_only:
                    logger.info(
                        "yt_api transcript failed; proceeding to backup transcript flow"
                    )

        if s3_audio_uri and s3_transcript_json_uri:
            logger.info(
                "Both S3 audio and S3 transcript provided; trying S3 audio path after YT API attempt"
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
                documents = self._maybe_add_backup_transcript_docs(
                    documents=documents,
                    url=url,
                    video_id=video_id,
                    video_title=video_title,
                    track_id=track_id,
                    s3_audio_uri=s3_audio_uri,
                )
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

        enable_ytdlp_fallback = (
            os.getenv("ENABLE_YTDLP_FALLBACK", "false").strip().lower() == "true"
        )
        if (
            not s3_transcript_json_uri
            and not s3_audio_uri
            and not enable_ytdlp_fallback
        ):
            raise RuntimeError(
                "Failed to fetch transcript: missing S3 transcript/audio and yt-dlp fallback is disabled"
            )

        logger.info("Falling back to audio/transcript alternatives.")

        if enable_ytdlp_fallback:
            try:
                transcript_data = self._transcribe_from_ytdlp_audio(
                    url=url,
                    video_title=video_title,
                    track_id=backup_track_id,
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
            documents = self._maybe_add_backup_transcript_docs(
                documents=documents,
                url=url,
                video_id=video_id,
                video_title=video_title,
                track_id=track_id,
                s3_audio_uri=s3_audio_uri,
            )
            return {
                "documents": documents,
                "source": url,
                "video_id": video_id,
                "total_chunks": len(documents),
                "processed_at": datetime.now().isoformat(),
            }

        raise RuntimeError(f"Failed to fetch transcript: {error_msg}")

    def _maybe_add_backup_transcript_docs(
        self,
        documents: List[Document],
        url: str,
        video_id: str,
        video_title: str,
        track_id: Optional[str],
        s3_audio_uri: Optional[str],
    ) -> List[Document]:
        if not (track_id or "").startswith("yt_api"):
            return documents

        backup_entries: List[Dict[str, Any]] = []
        try:
            if s3_audio_uri:
                backup_entries = self._transcribe_from_s3_audio(
                    s3_audio_uri=s3_audio_uri,
                    video_title=video_title,
                    track_id="backup_transcript",
                )
            elif os.getenv("ENABLE_YTDLP_FALLBACK", "false").strip().lower() == "true":
                backup_entries = self._transcribe_from_ytdlp_audio(
                    url=url,
                    video_title=video_title,
                    track_id="backup_transcript",
                )
        except Exception as e:
            logger.warning("Backup transcript generation failed: %s", e)
            return documents

        if not backup_entries:
            return documents

        self._persist_transcript_snapshot(
            transcript_data=backup_entries,
            url=url,
            video_id=video_id,
            origin="backup_transcript",
        )
        backup_docs = self._create_documents(backup_entries, url, video_id)
        logger.info("Added backup transcript docs: %s", len(backup_docs))
        return documents + backup_docs

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

            segment_video_title = (
                segment.get("video_title")
                or segment.get("title")
                or video_title
                or "Unknown Video"
            )

            entries.append(
                {
                    "text": text,
                    "start": float(start or 0.0),
                    "duration": float(duration or 0.0),
                    "video_title": segment_video_title,
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
            return self._transcribe_audio_file(local_path, video_title, track_id)

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

            return self._transcribe_audio_file(final_audio_path, video_title, track_id)

    def _transcribe_audio_file(
        self, audio_path: str, video_title: str, track_id: str
    ) -> List[Dict[str, Any]]:
        return self._transcribe_audio_file_with_multimodal(
            audio_path=audio_path,
            video_title=video_title,
            track_id=track_id,
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

        system_prompt = (
            "You are an expert Audio Translator. "
            "Your task is to TRANSLATE spoken Hindi or Hinglish audio into pure English text. "
            "Listen to the audio. If the speaker is speaking Hindi or a mix of Hindi and English, TRANSLATE the entire meaning into 100% English words. "
            "ABSOLUTELY NO DEVANAGARI SCRIPT IS ALLOWED. NO HINDI WORDS. TRANSLATE EVERYTHING TO ENGLISH. "
            "Keep technical terms and math symbols intact. "
            "Output must be plain timestamped lines in this exact style: "
            "[00:01] The value of H is given as r / 3, so this is r / 3. "
            "[00:05] r cancels out with r, and this becomes the square of 1 / 3. "
            "Return ONLY the timestamped lines. No other text."
        )
        user_prompt = f"The context of this audio is: {video_title}. Please use appropriate terminology. Listen to this audio and TRANSLATE it entirely to English. Do NOT transcribe the original Hindi words. You MUST translate the meaning into English. ABSOLUTELY NO DEVANAGARI SCRIPT ALLOWED. Output MUST be timestamped lines only."

        max_chunk_seconds = int(os.getenv("AUDIO_TRANSCRIBE_CHUNK_SECONDS", "40"))
        overlap_seconds = int(os.getenv("AUDIO_TRANSCRIBE_CHUNK_OVERLAP_SECONDS", "10"))
        if overlap_seconds >= max_chunk_seconds:
            overlap_seconds = max(0, max_chunk_seconds - 1)
        step_seconds = max(1, max_chunk_seconds - overlap_seconds)
        transcript_entries: List[Dict[str, Any]] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            chunk_specs = []

            duration_seconds = 0.0
            try:
                probe = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        audio_path,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                duration_seconds = float((probe.stdout or "0").strip() or 0.0)
            except Exception:
                duration_seconds = 0.0

            chunk_index = 0

            if duration_seconds <= 0:
                chunk_path = os.path.join(tmpdir, f"chunk{chunk_index:03d}.mp3")
                subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        audio_path,
                        "-c:a",
                        "libmp3lame",
                        "-b:a",
                        "128k",
                        "-y",
                        chunk_path,
                    ],
                    check=True,
                )
                chunk_specs.append((chunk_path, 0.0, chunk_index))
            else:
                start_seconds = 0.0
                while start_seconds < duration_seconds:
                    end_seconds = min(
                        start_seconds + max_chunk_seconds, duration_seconds
                    )
                    chunk_path = os.path.join(tmpdir, f"chunk{chunk_index:03d}.mp3")
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-ss",
                            str(start_seconds),
                            "-t",
                            str(max(0.1, end_seconds - start_seconds)),
                            "-i",
                            audio_path,
                            "-c:a",
                            "libmp3lame",
                            "-b:a",
                            "128k",
                            "-y",
                            chunk_path,
                        ],
                        check=True,
                    )
                    chunk_specs.append((chunk_path, start_seconds, chunk_index))
                    if end_seconds >= duration_seconds:
                        break
                    start_seconds += step_seconds
                    chunk_index += 1

            for chunk_path, chunk_start_seconds, idx in chunk_specs:
                with open(chunk_path, "rb") as audio_file:
                    encoded_string = base64.b64encode(audio_file.read()).decode("utf-8")

                segments = self._request_transcript_segments(
                    client=client,
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    encoded_audio=encoded_string,
                )
                if isinstance(segments, list):
                    chunk_entries = self._normalize_transcript_entries(
                        segments, video_title, track_id
                    )
                    if overlap_seconds > 0 and idx > 0:
                        chunk_entries = [
                            e
                            for e in chunk_entries
                            if float(e.get("start", 0.0) or 0.0) >= overlap_seconds
                        ]
                    offset = chunk_start_seconds
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
        system_prompt: str,
        user_prompt: str,
        encoded_audio: str,
    ) -> List[Dict[str, Any]]:
        response = None
        input_audio_messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "input_audio",
                        "input_audio": {"data": encoded_audio, "format": "mp3"},
                    },
                ],
            },
        ]
        try:
            response = client.chat.completions.create(
                model=model,
                messages=input_audio_messages,
                temperature=0.2,
            )
        except Exception as first_err:
            file_url = f"data:audio/mp3;base64,{encoded_audio}"
            file_messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "file", "file_url": file_url},
                    ],
                },
            ]
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=file_messages,
                    temperature=0.2,
                )
            except Exception as second_err:
                logger.error(
                    "OpenRouter transcription request failed for both input_audio and file payloads. input_audio_error=%s file_error=%s",
                    first_err,
                    second_err,
                )
                raise

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
        segments = self._parse_timestamped_lines(content)
        if segments:
            return segments

        segments = self._parse_segments_json(content)
        if segments:
            return segments

        return self._parse_text_with_guessed_timestamps(content)

    def _parse_timestamped_lines(self, content: str) -> List[Dict[str, Any]]:
        text = content.strip()
        if text.startswith("```"):
            text = text.replace("```text", "").replace("```", "").strip()

        pattern = re.compile(
            r"\[(?P<mm>\d{1,2}):(?P<ss>\d{2})\]\s*(?P<txt>[^\n\r]+)",
            re.MULTILINE,
        )
        matches = list(pattern.finditer(text))
        if not matches:
            return []

        out: List[Dict[str, Any]] = []
        for i, m in enumerate(matches):
            mm = int(m.group("mm"))
            ss = int(m.group("ss"))
            start = float(mm * 60 + ss)
            txt = (m.group("txt") or "").strip()
            if not txt:
                continue
            if i + 1 < len(matches):
                nmm = int(matches[i + 1].group("mm"))
                nss = int(matches[i + 1].group("ss"))
                next_start = float(nmm * 60 + nss)
                duration = max(0.0, next_start - start)
            else:
                duration = max(2.0, len(txt.split()) * 0.45)
            out.append({"text": txt, "start": start, "duration": duration})
        return out

    def _parse_text_with_guessed_timestamps(self, content: str) -> List[Dict[str, Any]]:
        cleaned = re.sub(r"```(?:json|text)?", "", content, flags=re.IGNORECASE)
        cleaned = cleaned.replace("```", "").strip()
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in cleaned.splitlines()]
        lines = [ln for ln in lines if ln]
        if not lines:
            return []

        out: List[Dict[str, Any]] = []
        last_start = 0.0
        for line in lines:
            words = max(1, len(line.split()))
            duration = max(2.0, words * 0.45)
            out.append({"text": line, "start": last_start, "duration": duration})
            last_start += duration
        return out

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

        