from __future__ import annotations

import os
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path[:0] = [os.path.join(os.path.dirname(__file__), "..")]

from src.processors.youtube_processor import (
    TranslatedDocumentResult,
    YouTubeProcessor,
)
from src.translation.transcript_translator import (
    TranscriptTranslationError,
    TranscriptTranslator,
)


def _make_entries(
    texts: list[str],
    *,
    video_title: str = "Test Video",
    track_id: str = "yt_api",
) -> list[dict[str, Any]]:
    return [
        {
            "text": t,
            "start": float(i * 10),
            "duration": 10.0,
            "video_title": video_title,
            "track_id": track_id,
        }
        for i, t in enumerate(texts)
    ]


def _fake_translator(
    translations: dict[str, str] | None = None,
    *,
    fail_on: str | None = None,
) -> MagicMock:
    mapping = translations or {}

    def _translate(text: str) -> str:
        if fail_on and fail_on in text:
            raise TranscriptTranslationError(f"Simulated failure on '{fail_on}'")
        return mapping.get(text, f"[translated] {text}")

    translator = MagicMock(spec=TranscriptTranslator)
    translator.translate_text = MagicMock(side_effect=_translate)
    translator.model_name = "google/translategemma-12b-it"
    translator.source_lang_code = "hi"
    translator.target_lang_code = "en"
    return translator


def _call(processor: YouTubeProcessor, **kwargs: Any) -> TranslatedDocumentResult:
    return processor.prepare_translated_documents(**kwargs)


@pytest.fixture()
def processor() -> YouTubeProcessor:
    with patch.dict("os.environ", {"YOUTUBE_API_KEY": ""}, clear=False):
        p = YouTubeProcessor()
        p.youtube_client = None
        return p


class TestPrepareTranslatedDocumentsBasic:
    def test_success_status(self, processor: YouTubeProcessor) -> None:
        entries = _make_entries(["नमस्ते दुनिया"])
        translator = _fake_translator({"नमस्ते दुनिया": "Hello world"})

        result = _call(
            processor,
            transcript_entries=entries,
            translator=translator,
            url="https://youtube.com/watch?v=abc123",
            video_id="abc123",
            transcript_source="s3_transcript_json",
        )

        assert result["status"] == "success"
        assert len(result["documents"]) >= 1
        assert result["documents"][0].page_content == "Hello world"
        assert result["error"] is None

    def test_original_text_in_metadata(self, processor: YouTubeProcessor) -> None:
        entries = _make_entries(["नमस्ते दुनिया"])
        translator = _fake_translator({"नमस्ते दुनिया": "Hello world"})

        result = _call(
            processor,
            transcript_entries=entries,
            translator=translator,
            url="https://youtube.com/watch?v=abc123",
            video_id="abc123",
            transcript_source="s3_transcript_json",
        )

        assert result["documents"][0].metadata["original_text"] == "नमस्ते दुनिया"


class TestTranslationMetadataFields:
    REQUIRED_META_KEYS = {
        "original_text",
        "translation_applied",
        "translation_status",
        "translation_model",
        "translation_source",
        "translated_from_lang",
        "translated_to_lang",
    }

    def test_all_translation_metadata_present(
        self, processor: YouTubeProcessor
    ) -> None:
        entries = _make_entries(["कुछ पाठ"])
        translator = _fake_translator({"कुछ पाठ": "Some text"})

        result = _call(
            processor,
            transcript_entries=entries,
            translator=translator,
            url="https://youtube.com/watch?v=vid1",
            video_id="vid1",
            transcript_source="s3_transcript_json",
        )

        meta = result["documents"][0].metadata
        for key in self.REQUIRED_META_KEYS:
            assert key in meta, f"Missing metadata key: {key}"

    def test_translation_metadata_values(self, processor: YouTubeProcessor) -> None:
        entries = _make_entries(["कुछ पाठ"])
        translator = _fake_translator({"कुछ पाठ": "Some text"})

        result = _call(
            processor,
            transcript_entries=entries,
            translator=translator,
            url="https://youtube.com/watch?v=vid1",
            video_id="vid1",
            transcript_source="s3_transcript_json",
        )

        meta = result["documents"][0].metadata
        assert meta["translation_applied"] is True
        assert meta["translation_status"] == "success"
        assert meta["translation_model"] == "google/translategemma-12b-it"
        assert meta["translation_source"] == "s3_transcript_json"
        assert meta["translated_from_lang"] == "hi"
        assert meta["translated_to_lang"] == "en"

    def test_source_metadata_preserved(self, processor: YouTubeProcessor) -> None:
        entries = _make_entries(
            ["text"], video_title="My Video", track_id="s3_transcript"
        )
        translator = _fake_translator()

        result = _call(
            processor,
            transcript_entries=entries,
            translator=translator,
            url="https://youtube.com/watch?v=xyz",
            video_id="xyz",
            transcript_source="s3_transcript_json",
        )

        meta = result["documents"][0].metadata
        assert meta["source"] == "https://youtube.com/watch?v=xyz"
        assert meta["video_id"] == "xyz"
        assert meta["title"] == "My Video"
        assert meta["source_type"] == "youtube"
        assert meta["track_id"] == "s3_transcript"


class TestTranslationFailureAllOrNothing:
    def test_failure_status_and_empty_docs(self, processor: YouTubeProcessor) -> None:
        entries = _make_entries(["good text", "bad text that fails"])
        translator = _fake_translator(fail_on="bad text")

        result = _call(
            processor,
            transcript_entries=entries,
            translator=translator,
            url="https://youtube.com/watch?v=fail1",
            video_id="fail1",
            transcript_source="s3_transcript_json",
        )

        assert result["status"] == "failed"
        assert result["documents"] == []
        assert result["error"] is not None

    def test_no_partial_documents_on_mid_failure(
        self, processor: YouTubeProcessor
    ) -> None:
        entries = _make_entries(["ok one", "ok two", "BOOM fails"])
        translator = _fake_translator(fail_on="BOOM")

        result = _call(
            processor,
            transcript_entries=entries,
            translator=translator,
            url="https://youtube.com/watch?v=fail2",
            video_id="fail2",
            transcript_source="s3_transcript_json",
        )

        assert result["status"] == "failed"
        assert result["documents"] == []

    def test_atomic_prepare_contract_returns_no_documents_on_failure(
        self, processor: YouTubeProcessor
    ) -> None:
        entries = _make_entries(["entry one", "entry two", "entry three"])
        translator = _fake_translator(fail_on="entry two")

        result = _call(
            processor,
            transcript_entries=entries,
            translator=translator,
            url="https://youtube.com/watch?v=atomic1",
            video_id="atomic1",
            transcript_source="s3_transcript_json",
        )

        assert result["status"] == "failed"
        assert result["documents"] == []
        assert result["error"] is not None


class TestMultipleEntries:
    def test_multiple_entries_all_translated(self, processor: YouTubeProcessor) -> None:
        entries = _make_entries(["पहला", "दूसरा", "तीसरा"])
        translator = _fake_translator(
            {
                "पहला": "First",
                "दूसरा": "Second",
                "तीसरा": "Third",
            }
        )

        result = _call(
            processor,
            transcript_entries=entries,
            translator=translator,
            url="https://youtube.com/watch?v=multi",
            video_id="multi",
            transcript_source="s3_transcript_json",
        )

        assert result["status"] == "success"
        all_content = " ".join(d.page_content for d in result["documents"])
        assert "First" in all_content
        assert "Second" in all_content
        assert "Third" in all_content
        assert "पहला" not in all_content

    def test_translator_called_per_entry(self, processor: YouTubeProcessor) -> None:
        entries = _make_entries(["a", "b", "c"])
        translator = _fake_translator()

        _call(
            processor,
            transcript_entries=entries,
            translator=translator,
            url="https://youtube.com/watch?v=count",
            video_id="count",
            transcript_source="s3_transcript_json",
        )

        assert translator.translate_text.call_count == 3


class TestSkippedEmpty:
    def test_skipped_empty_status(self, processor: YouTubeProcessor) -> None:
        translator = _fake_translator()

        result = _call(
            processor,
            transcript_entries=[],
            translator=translator,
            url="https://youtube.com/watch?v=empty",
            video_id="empty",
            transcript_source="s3_transcript_json",
        )

        assert result["status"] == "skipped_empty"
        assert result["documents"] == []
        assert result["error"] is None

    def test_translator_not_called_for_empty(self, processor: YouTubeProcessor) -> None:
        translator = _fake_translator()

        _call(
            processor,
            transcript_entries=[],
            translator=translator,
            url="https://youtube.com/watch?v=empty",
            video_id="empty",
            transcript_source="s3_transcript_json",
        )

        translator.translate_text.assert_not_called()


class TestS3TranscriptEligibility:
    def test_yt_api_source_skipped_ineligible(
        self, processor: YouTubeProcessor
    ) -> None:
        entries = _make_entries(["some text"], track_id="yt_api")
        translator = _fake_translator()

        result = _call(
            processor,
            transcript_entries=entries,
            translator=translator,
            url="https://youtube.com/watch?v=yt1",
            video_id="yt1",
            transcript_source="youtube_transcript_api",
        )

        assert result["status"] == "skipped_ineligible"
        assert result["documents"] == []

    def test_s3_audio_source_skipped_ineligible(
        self, processor: YouTubeProcessor
    ) -> None:
        entries = _make_entries(["some text"], track_id="s3_audio_asr")
        translator = _fake_translator()

        result = _call(
            processor,
            transcript_entries=entries,
            translator=translator,
            url="https://youtube.com/watch?v=aud1",
            video_id="aud1",
            transcript_source="s3_audio_asr",
        )

        assert result["status"] == "skipped_ineligible"
        assert result["documents"] == []

    def test_ytdlp_source_skipped_ineligible(self, processor: YouTubeProcessor) -> None:
        entries = _make_entries(["some text"], track_id="yt_dlp_audio_asr")
        translator = _fake_translator()

        result = _call(
            processor,
            transcript_entries=entries,
            translator=translator,
            url="https://youtube.com/watch?v=dlp1",
            video_id="dlp1",
            transcript_source="yt_dlp_audio_asr",
        )

        assert result["status"] == "skipped_ineligible"
        assert result["documents"] == []

    def test_translator_not_called_for_ineligible(
        self, processor: YouTubeProcessor
    ) -> None:
        entries = _make_entries(["some text"], track_id="yt_api")
        translator = _fake_translator()

        _call(
            processor,
            transcript_entries=entries,
            translator=translator,
            url="https://youtube.com/watch?v=skip1",
            video_id="skip1",
            transcript_source="youtube_transcript_api",
        )

        translator.translate_text.assert_not_called()

    def test_s3_transcript_json_accepted(self, processor: YouTubeProcessor) -> None:
        entries = _make_entries(["eligible text"])
        translator = _fake_translator()

        result = _call(
            processor,
            transcript_entries=entries,
            translator=translator,
            url="https://youtube.com/watch?v=s3ok",
            video_id="s3ok",
            transcript_source="s3_transcript_json",
        )

        assert result["status"] == "success"
        assert len(result["documents"]) >= 1


class TestDefaultCreateDocumentsUnchanged:
    def test_no_translation_metadata_in_default_path(
        self, processor: YouTubeProcessor
    ) -> None:
        entries = _make_entries(["plain english text"])

        docs = processor._create_documents(
            entries, "https://youtube.com/watch?v=plain", "plain"
        )

        meta = docs[0].metadata
        assert "original_text" not in meta
        assert "translation_applied" not in meta
        assert "translation_status" not in meta
