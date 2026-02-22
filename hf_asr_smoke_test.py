#!/usr/bin/env python3
"""Small smoke test for Hugging Face ASR model configuration.

Purpose:
- Verify HF token works
- Verify HF model id is accepted (e.g. openai/whisper-large-v3)
- Optionally run ASR on a real audio file
"""

import argparse
import os
import re
import struct
import sys
import tempfile
import wave
from typing import Any


def _is_model_id_valid(model_id: str) -> bool:
    if not model_id or ":" in model_id:
        return False
    return re.match(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", model_id) is not None


def _create_silent_wav(path: str, seconds: int = 1, sample_rate: int = 16000) -> None:
    total_samples = seconds * sample_rate
    with wave.open(path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        silence_frame = struct.pack("<h", 0)
        wav_file.writeframes(silence_frame * total_samples)


def _extract_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        text = payload.get("text")
        if isinstance(text, str):
            return text.strip()
    text_attr = getattr(payload, "text", None)
    if isinstance(text_attr, str):
        return text_attr.strip()
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Hugging Face ASR setup")
    parser.add_argument(
        "--audio",
        default=None,
        help="Path to audio file. If omitted, a 1-second silent WAV is generated.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("HF_ASR_MODEL", "openai/whisper-large-v3"),
        help="HF ASR model id (default from HF_ASR_MODEL or openai/whisper-large-v3)",
    )
    parser.add_argument(
        "--provider",
        default=os.getenv("HF_ASR_PROVIDER", "replicate"),
        help="Inference provider (default: replicate)",
    )
    args = parser.parse_args()

    hf_token = os.getenv("HF_TOKEN", "").strip()
    if not hf_token:
        print("FAIL: HF_TOKEN is not set")
        return 2

    if not _is_model_id_valid(args.model):
        print(f"FAIL: invalid HF model id: {args.model}")
        print("Hint: use repo id like 'openai/whisper-large-v3' (no ':fastest').")
        return 3

    try:
        from huggingface_hub import InferenceClient
    except Exception as e:
        print(f"FAIL: huggingface_hub import error: {e}")
        return 4

    audio_path = args.audio
    cleanup_path = None
    if not audio_path:
        tmpdir = tempfile.mkdtemp(prefix="hf_asr_smoke_")
        cleanup_path = os.path.join(tmpdir, "silence.wav")
        _create_silent_wav(cleanup_path)
        audio_path = cleanup_path

    if not os.path.exists(audio_path):
        print(f"FAIL: audio file not found: {audio_path}")
        return 5

    print(f"Testing HF ASR model={args.model} provider={args.provider}")
    print(f"Audio: {audio_path}")

    client = InferenceClient(provider=args.provider, api_key=hf_token)

    try:
        try:
            result = client.automatic_speech_recognition(
                audio_path,
                model=args.model,
                extra_body={"return_timestamps": True},
            )
        except TypeError:
            result = client.automatic_speech_recognition(audio_path, model=args.model)
    except Exception as e:
        print(f"FAIL: HF ASR request error: {e}")
        return 6

    text = _extract_text(result)
    print("PASS: HF ASR request succeeded")
    if text:
        preview = text if len(text) <= 240 else text[:240] + "..."
        print(f"Transcript preview: {preview}")
    else:
        print("Transcript preview: <empty or non-text payload>")

    if cleanup_path and os.path.exists(cleanup_path):
        try:
            os.remove(cleanup_path)
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
