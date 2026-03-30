import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypedDict, cast
from unittest.mock import patch

import pytest

sys.path[:0] = [os.path.join(os.path.dirname(__file__), "..")]

import src.translation.transcript_translator as _translator_module
from src.translation.transcript_translator import OpenRouterTranslator
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
    assert config.get("translation.provider") == "openrouter"
    assert config.get("translation.model") == "google/gemma-3-12b-it"
    assert config.get("translation.base_url") == "https://openrouter.ai/api/v1"
    assert config.get("translation.api_key_env_var") == "TRANSLATION_API_KEY"
    assert config.get("translation.source_lang") == "hi"
    assert config.get("translation.target_lang") == "en"
    assert config.get("translation.max_chars_per_request") == 3000
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


# ---------------------------------------------------------------------------
# OpenRouterTranslator tests
# ---------------------------------------------------------------------------


@dataclass
class _FakeMessage:
    content: str


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeCompletionResponse:
    choices: list[_FakeChoice]


class _FakeCompletions:
    def __init__(self, response: _FakeCompletionResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> _FakeCompletionResponse:
        self.calls.append(kwargs)
        return self.response


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeOpenAIClient:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = _FakeChat(completions)
        self.init_kwargs: dict[str, object] = {}


def _make_openrouter_translator(
    response_text: str = "hello world",
    *,
    max_chars_per_request: int = 3000,
) -> tuple[OpenRouterTranslator, _FakeCompletions]:
    response = _FakeCompletionResponse(
        choices=[_FakeChoice(message=_FakeMessage(content=response_text))]
    )
    completions = _FakeCompletions(response)
    client = _FakeOpenAIClient(completions)

    def client_factory(**kwargs: object) -> _FakeOpenAIClient:
        client.init_kwargs = kwargs
        return client

    translator = OpenRouterTranslator(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        client_factory=client_factory,
        max_chars_per_request=max_chars_per_request,
    )
    return translator, completions


def test_openrouter_translate_text_returns_response_content():
    translator, completions = _make_openrouter_translator("hello world")

    result = translator.translate_text("namaste dosto")

    assert result == "hello world"
    assert len(completions.calls) == 1
    call = completions.calls[0]
    assert call["model"] == "google/gemma-3-12b-it"
    assert call["temperature"] == 0.1


def test_openrouter_translate_text_sends_user_message_with_prompt():
    translator, completions = _make_openrouter_translator("translated")

    _ = translator.translate_text("kya haal hai")

    messages = completions.calls[0]["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert "kya haal hai" in messages[0]["content"]
    # Gemma 3 caveat: no system message
    assert all(m["role"] != "system" for m in messages)


def test_openrouter_translate_text_empty_returns_empty():
    translator, completions = _make_openrouter_translator("should not be called")

    result = translator.translate_text("   ")

    assert result == ""
    assert len(completions.calls) == 0


def test_openrouter_translate_text_strips_whitespace():
    translator, _ = _make_openrouter_translator("  hello world  ")

    result = translator.translate_text("namaste")

    assert result == "hello world"


def test_openrouter_translate_text_chunks_long_input():
    call_count = 0

    def make_response() -> _FakeCompletionResponse:
        nonlocal call_count
        call_count += 1
        return _FakeCompletionResponse(
            choices=[_FakeChoice(message=_FakeMessage(content=f"chunk{call_count}"))]
        )

    class MultiCompletions:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def create(self, **kwargs: object) -> _FakeCompletionResponse:
            self.calls.append(kwargs)
            return make_response()

    completions = MultiCompletions()
    client = _FakeOpenAIClient(completions)

    translator = OpenRouterTranslator(
        api_key="test-key",
        client_factory=lambda **_: client,
        max_chars_per_request=10,
    )

    result = translator.translate_text("one two three four")

    assert len(completions.calls) == 2
    assert result == "chunk1 chunk2"


def test_openrouter_translate_text_raises_on_empty_choices():
    response = _FakeCompletionResponse(choices=[])
    completions = _FakeCompletions(response)
    client = _FakeOpenAIClient(completions)

    translator = OpenRouterTranslator(
        api_key="test-key",
        client_factory=lambda **_: client,
    )

    with pytest.raises(TranscriptTranslationError, match="no choices"):
        _ = translator.translate_text("namaste")


def test_openrouter_translate_text_raises_on_empty_content():
    translator, _ = _make_openrouter_translator("   ")

    with pytest.raises(TranscriptTranslationError, match="did not include text"):
        _ = translator.translate_text("namaste")


def test_openrouter_translate_text_raises_on_api_error():
    class FailingCompletions:
        def create(self, **kwargs: object) -> None:
            raise RuntimeError("connection refused")

    class FailingChat:
        def __init__(self) -> None:
            self.completions = FailingCompletions()

    class FailingClient:
        def __init__(self) -> None:
            self.chat = FailingChat()

    translator = OpenRouterTranslator(
        api_key="test-key",
        client_factory=lambda **_: FailingClient(),
    )

    with pytest.raises(TranscriptTranslationError, match="connection refused"):
        _ = translator.translate_text("namaste")


def test_openrouter_translate_text_raises_when_no_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TRANSLATION_API_KEY", raising=False)

    translator = OpenRouterTranslator(api_key=None)

    with pytest.raises(TranscriptTranslationError, match="TRANSLATION_API_KEY"):
        _ = translator.translate_text("namaste")


def test_openrouter_translator_satisfies_protocol():
    translator, _ = _make_openrouter_translator("test")

    assert hasattr(translator, "model_name")
    assert hasattr(translator, "source_lang_code")
    assert hasattr(translator, "target_lang_code")
    assert hasattr(translator, "translate_text")
    assert translator.model_name == "google/gemma-3-12b-it"
    assert translator.source_lang_code == "hi"
    assert translator.target_lang_code == "en"


def test_openrouter_translator_custom_prompt_template():
    translator, completions = _make_openrouter_translator(
        "translated",
    )
    translator._prompt_template = "CUSTOM: {text}"

    _ = translator.translate_text("test input")

    user_content = completions.calls[0]["messages"][0]["content"]
    assert user_content == "CUSTOM: test input"


def test_openrouter_client_factory_receives_api_key_and_base_url():
    received_kwargs: dict[str, object] = {}

    def capturing_factory(**kwargs: object) -> _FakeOpenAIClient:
        received_kwargs.update(kwargs)
        response = _FakeCompletionResponse(
            choices=[_FakeChoice(message=_FakeMessage(content="ok"))]
        )
        return _FakeOpenAIClient(_FakeCompletions(response))

    translator = OpenRouterTranslator(
        api_key="my-secret-key",
        base_url="https://custom.api/v1",
        client_factory=capturing_factory,
    )
    _ = translator.translate_text("test")

    assert received_kwargs["api_key"] == "my-secret-key"
    assert received_kwargs["base_url"] == "https://custom.api/v1"


def test_package_reexport_includes_openrouter_translator():
    import src.translation as translation_pkg

    OpenRouterCls = getattr(translation_pkg, "OpenRouterTranslator", None)
    assert OpenRouterCls is OpenRouterTranslator
