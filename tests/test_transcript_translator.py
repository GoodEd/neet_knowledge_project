import os
import sys
from pathlib import Path
from typing import Protocol, TypedDict, cast

import pytest

sys.path[:0] = [os.path.join(os.path.dirname(__file__), "..")]

import src.translation.transcript_translator as _translator_module
from src.utils.config import Config


class _TranslatedContent(TypedDict):
    type: str
    text: str
    source_lang_code: str
    target_lang_code: str


class _UserMessage(TypedDict):
    role: str
    content: list[_TranslatedContent]


class _PipelineCall(TypedDict):
    text: list[_UserMessage]
    max_new_tokens: int
    do_sample: bool


class _PipelineProtocol(Protocol):
    def __call__(
        self,
        *,
        text: list[_UserMessage],
        max_new_tokens: int,
        do_sample: bool,
    ) -> list[dict[str, object]]: ...


class _TranslatorInstance(Protocol):
    def translate_text(self, text: str) -> str: ...


class _TranslatorFactory(Protocol):
    def __call__(
        self,
        *,
        pipeline_factory: object,
        model_name: str = "google/translategemma-12b-it",
        source_lang_code: str = "hi",
        target_lang_code: str = "en",
        max_chars_per_request: int = 1500,
        max_new_tokens: int = 256,
    ) -> _TranslatorInstance: ...


class _TranscriptTranslatorModule(Protocol):
    TranscriptTranslationError: type[Exception]
    TranscriptTranslator: _TranslatorFactory


class _FakePipeline:
    def __init__(self, response: list[dict[str, object]]) -> None:
        self.response: list[dict[str, object]] = response
        self.calls: list[_PipelineCall] = []

    def __call__(
        self,
        *,
        text: list[_UserMessage],
        max_new_tokens: int,
        do_sample: bool,
    ) -> list[dict[str, object]]:
        self.calls.append(
            {
                "text": text,
                "max_new_tokens": max_new_tokens,
                "do_sample": do_sample,
            }
        )
        return self.response


_translator_module_obj: object = _translator_module
_TRANSLATOR_MODULE = cast(_TranscriptTranslatorModule, _translator_module_obj)  # pyright: ignore[reportInvalidCast]
TranscriptTranslationError = _TRANSLATOR_MODULE.TranscriptTranslationError
TranscriptTranslator = _TRANSLATOR_MODULE.TranscriptTranslator


def _make_translator(
    response: list[dict[str, object]],
) -> tuple[_TranslatorInstance, _FakePipeline]:
    pipeline = _FakePipeline(response)

    def pipeline_factory(**_: object) -> _PipelineProtocol:
        return pipeline

    return TranscriptTranslator(pipeline_factory=pipeline_factory), pipeline


def test_translation_config_defaults_present(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    _ = config_path.write_text("{}\n", encoding="utf-8")

    config = Config(str(config_path))

    assert config.get("translation.enabled", False) is False
    assert config.get("translation.provider") == "transformers"
    assert config.get("translation.model") == "google/translategemma-12b-it"
    assert config.get("translation.source_lang") == "hi"
    assert config.get("translation.target_lang") == "en"
    assert config.get("translation.max_chars_per_request") == 1500
    assert config.get("translation.apply_only_to_s3_transcript") is True


def test_translate_text_builds_translategemma_chat_template_and_returns_text():
    pipeline_factory_calls: list[dict[str, object]] = []

    class CapturingPipelineFactory:
        def __call__(self, **kwargs: object) -> _PipelineProtocol:
            pipeline_factory_calls.append(dict(kwargs))
            return pipeline

    translator, pipeline = _make_translator(
        [
            {
                "generated_text": [
                    {
                        "role": "assistant",
                        "content": "hello world",
                    }
                ]
            }
        ]
    )

    translator = TranscriptTranslator(pipeline_factory=CapturingPipelineFactory())

    result = translator.translate_text("namaste dosto")

    assert result == "hello world"
    assert pipeline_factory_calls == [
        {
            "task": "image-text-to-text",
            "model": "google/translategemma-12b-it",
        }
    ]
    assert pipeline.calls[0]["max_new_tokens"] == 256
    assert pipeline.calls[0]["do_sample"] is False
    payload = pipeline.calls[0]["text"][0]["content"][0]
    assert pipeline.calls[0]["text"][0]["role"] == "user"
    assert payload["source_lang_code"] == "hi"
    assert payload["target_lang_code"] == "en"
    assert payload["text"] == "namaste dosto"


def test_translate_text_chunks_by_max_chars_per_request():
    responses: list[list[dict[str, object]]] = [
        [{"generated_text": [{"role": "assistant", "content": "translated:one two"}]}],
        [
            {
                "generated_text": [
                    {"role": "assistant", "content": "translated:three four"}
                ]
            }
        ],
    ]

    class ChunkingPipeline:
        def __init__(self) -> None:
            self.calls: list[_PipelineCall] = []

        def __call__(
            self,
            *,
            text: list[_UserMessage],
            max_new_tokens: int,
            do_sample: bool,
        ) -> list[dict[str, object]]:
            self.calls.append(
                {
                    "text": text,
                    "max_new_tokens": max_new_tokens,
                    "do_sample": do_sample,
                }
            )
            return responses[len(self.calls) - 1]

    pipeline = ChunkingPipeline()

    def pipeline_factory(**_: object) -> ChunkingPipeline:
        return pipeline

    translator = TranscriptTranslator(
        max_chars_per_request=10,
        pipeline_factory=pipeline_factory,
    )

    result = translator.translate_text("one two three four")

    assert len(pipeline.calls) == 2
    assert all(call["do_sample"] is False for call in pipeline.calls)
    assert result == "translated:one two translated:three four"


def test_translate_text_raises_on_empty_pipeline_output():
    translator, _ = _make_translator([])

    with pytest.raises(TranscriptTranslationError, match="returned no output"):
        _ = translator.translate_text("namaste dosto")


def test_translate_text_raises_when_generated_text_missing():
    translator, _ = _make_translator([{}])

    with pytest.raises(TranscriptTranslationError, match="did not include text"):
        _ = translator.translate_text("namaste dosto")


def test_translate_text_returns_stripped_string_output():
    translator, _ = _make_translator([{"generated_text": "  hello world  "}])

    result = translator.translate_text("namaste dosto")

    assert result == "hello world"


def test_package_reexport_matches_transcript_translator_module():
    import src.translation as translation_pkg

    PackageError = cast(
        type[Exception], getattr(translation_pkg, "TranscriptTranslationError")
    )
    PackageTranslator = cast(
        _TranslatorFactory, getattr(translation_pkg, "TranscriptTranslator")
    )

    assert PackageTranslator is TranscriptTranslator
    assert PackageError is TranscriptTranslationError


def test_translate_text_returns_latest_assistant_message_from_mixed_generated_text_list():
    translator, _ = _make_translator(
        [
            {
                "generated_text": [
                    {"role": "system", "content": "ignore me"},
                    {"role": "assistant", "content": "first assistant"},
                    {"role": "user", "content": "also ignore me"},
                    {"role": "assistant", "content": "  final answer  "},
                ]
            }
        ]
    )

    result = translator.translate_text("namaste dosto")

    assert result == "final answer"


def test_translate_text_raises_when_generated_text_list_has_no_usable_assistant_content():
    translator, _ = _make_translator(
        [
            {
                "generated_text": [
                    {"role": "system", "content": "ignored"},
                    {"role": "assistant", "content": "   "},
                ]
            }
        ]
    )

    with pytest.raises(TranscriptTranslationError, match="did not include text"):
        _ = translator.translate_text("namaste dosto")


def test_pipeline_errors_raise_transcript_translation_error():
    class FailingPipeline:
        def __call__(
            self,
            *,
            text: list[_UserMessage],
            max_new_tokens: int,
            do_sample: bool,
        ) -> list[dict[str, object]]:
            assert do_sample is False
            raise RuntimeError("boom")

    def pipeline_factory(**_: object) -> FailingPipeline:
        return FailingPipeline()

    translator = TranscriptTranslator(
        pipeline_factory=pipeline_factory,
    )

    with pytest.raises(TranscriptTranslationError, match="boom"):
        _ = translator.translate_text("namaste dosto")
