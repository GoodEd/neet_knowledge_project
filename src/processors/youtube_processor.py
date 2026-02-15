import re
from typing import Dict, Any, List, Optional
from datetime import datetime


class YouTubeProcessor:
    def __init__(self, language: str = "en"):
        self.language = language
        self._yt_api = None

    def _import_dependencies(self):
        if self._yt_api is None:
            try:
                from youtube_transcript_api import YouTubeTranscriptApi

                # Try to instantiate for v1.2.x+ support
                try:
                    self._yt_api = YouTubeTranscriptApi()
                except Exception:
                    # Fallback for older versions where it might be static only
                    self._yt_api = YouTubeTranscriptApi
            except ImportError:
                raise ImportError(
                    "youtube-transcript-api not installed. Run: pip install youtube-transcript-api"
                )

    def extract_video_id(self, url: str) -> Optional[str]:
        patterns = [
            r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([^&\n?#]+)",
            r"^([a-zA-Z0-9_-]{11})$",
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1) if match.lastindex else match.group(0)

        return None

    def process(self, video_url: str) -> Dict[str, Any]:
        self._import_dependencies()

        video_id = self.extract_video_id(video_url)
        if not video_id:
            raise ValueError(f"Invalid YouTube URL: {video_url}")

        try:
            if hasattr(self._yt_api, "list_transcripts"):
                transcript_list = self._yt_api.list_transcripts(video_id)
            elif hasattr(self._yt_api, "list"):
                transcript_list = self._yt_api.list(video_id)
            else:
                raise RuntimeError(
                    "YouTubeTranscriptApi does not have list_transcripts or list method"
                )

            transcript = None
            try:
                transcript = transcript_list.find_transcript([self.language])
            except Exception:
                try:
                    transcript = transcript_list.find_transcript(["en"])
                except Exception:
                    pass

            if transcript:
                transcript_data = transcript.fetch()

                # Helper to normalize transcript items
                def get_item_data(item):
                    if isinstance(item, dict):
                        return item["text"], item["start"], item.get("duration", 0)
                    else:
                        return item.text, item.start, item.duration

                full_text_parts = []
                timestamped_segments = []

                for item in transcript_data:
                    text, start, duration = get_item_data(item)
                    full_text_parts.append(text)
                    timestamped_segments.append(
                        {
                            "start": start,
                            "duration": duration,
                            "text": text,
                        }
                    )

                full_text = " ".join(full_text_parts)

                return {
                    "documents": [
                        {
                            "content": full_text,
                            "source": f"YouTube:{video_id}",
                            "video_url": video_url,
                            "video_id": video_id,
                            "content_type": "youtube_transcript",
                            "timestamp": datetime.now().isoformat(),
                        }
                    ],
                    "timestamped_segments": timestamped_segments,
                    "video_id": video_id,
                    "processed_at": datetime.now().isoformat(),
                }
            else:
                raise RuntimeError(f"No transcript available for video: {video_id}")

        except Exception as e:
            raise RuntimeError(f"Error processing YouTube video: {str(e)}")

    def process_with_timestamps(self, video_url: str) -> List[Dict[str, Any]]:
        self._import_dependencies()

        video_id = self.extract_video_id(video_url)
        if not video_id:
            raise ValueError(f"Invalid YouTube URL: {video_url}")

        try:
            if hasattr(self._yt_api, "list_transcripts"):
                transcript_list = self._yt_api.list_transcripts(video_id)
            elif hasattr(self._yt_api, "list"):
                transcript_list = self._yt_api.list(video_id)
            else:
                raise RuntimeError(
                    "YouTubeTranscriptApi does not have list_transcripts or list method"
                )

            transcript = None
            try:
                transcript = transcript_list.find_transcript([self.language])
            except Exception:
                try:
                    transcript = transcript_list.find_transcript(["en"])
                except Exception:
                    pass

            if not transcript:
                raise RuntimeError(f"No transcript available for video: {video_id}")

            transcript_data = transcript.fetch()

            # Helper to normalize transcript items
            def get_item_data(item):
                if isinstance(item, dict):
                    return item["text"], item["start"], item.get("duration", 0)
                else:
                    return item.text, item.start, item.duration

            documents = []
            for i, item in enumerate(transcript_data):
                text, start, duration = get_item_data(item)
                documents.append(
                    {
                        "content": text,
                        "source": f"YouTube:{video_id}",
                        "video_id": video_id,
                        "start_time": start,
                        "duration": duration,
                        "content_type": "youtube_segment",
                        "timestamp": datetime.now().isoformat(),
                    }
                )

            return documents

        except Exception as e:
            raise RuntimeError(f"Error processing YouTube video: {str(e)}")
