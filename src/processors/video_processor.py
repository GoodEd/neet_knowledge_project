from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import subprocess
import tempfile
import os


class VideoProcessor:
    def __init__(self):
        self._whisper = None

    def _import_dependencies(self):
        if self._whisper is None:
            try:
                import whisper

                self._whisper = whisper
            except ImportError:
                pass

    def process(self, file_path: str, language: str = "en") -> Dict[str, Any]:
        file_path_obj = Path(file_path)

        if not file_path_obj.exists():
            raise FileNotFoundError(f"Video/Audio file not found: {file_path}")

        self._import_dependencies()

        if self._whisper is None:
            return self._process_with_ffmpeg(file_path_obj)

        try:
            model = self._whisper.load_model("base")
            result = model.transcribe(str(file_path_obj), language=language)

            return {
                "documents": [
                    {
                        "content": result["text"],
                        "source": str(file_path_obj.name),
                        "duration": result.get("segments", [{}])[-1].get("end", 0)
                        if result.get("segments")
                        else 0,
                        "content_type": "video_transcript",
                        "timestamp": datetime.now().isoformat(),
                    }
                ],
                "source": str(file_path_obj.name),
                "processed_at": datetime.now().isoformat(),
            }
        except Exception as e:
            return self._process_with_ffmpeg(file_path_obj)

    def _process_with_ffmpeg(self, file_path: Path) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration:stream=codec_name,codec_type",
                    "-of",
                    "default=noprint_wrappers=1",
                    str(file_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            duration = 0
            has_audio = False

            for line in result.stdout.split("\n"):
                if line.startswith("duration="):
                    try:
                        duration = float(line.split("=")[1])
                    except (IndexError, ValueError):
                        pass
                elif "audio" in line.lower():
                    has_audio = True

            return {
                "documents": [
                    {
                        "content": f"Video file: {file_path.name}. Duration: {duration:.2f} seconds. "
                        f"Audio stream available: {has_audio}. "
                        f"Install whisper for transcript extraction.",
                        "source": str(file_path.name),
                        "duration": duration,
                        "has_audio": has_audio,
                        "content_type": "video_info",
                        "timestamp": datetime.now().isoformat(),
                    }
                ],
                "source": str(file_path.name),
                "duration": duration,
                "processed_at": datetime.now().isoformat(),
            }
        except Exception as e:
            raise RuntimeError(f"Error processing video: {str(e)}")

    def extract_audio(self, file_path: str, output_path: str = None) -> str:
        file_path_obj = Path(file_path)

        if not file_path_obj.exists():
            raise FileNotFoundError(f"Video file not found: {file_path}")

        if output_path is None:
            output_path = str(file_path_obj.with_suffix(".wav"))

        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    str(file_path),
                    "-vn",
                    "-acodec",
                    "pcm_s16le",
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    output_path,
                    "-y",
                ],
                capture_output=True,
                check=True,
                timeout=300,
            )
            return output_path
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Error extracting audio: {str(e)}")
        except FileNotFoundError:
            raise RuntimeError(
                "ffmpeg not found. Install ffmpeg to extract audio from videos."
            )


class AudioProcessor(VideoProcessor):
    def __init__(self):
        super().__init__()

    def process(self, file_path: str, language: str = "en") -> Dict[str, Any]:
        return super().process(file_path, language)
