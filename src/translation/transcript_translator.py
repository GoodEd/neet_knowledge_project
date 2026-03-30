from __future__ import annotations

import os
from collections.abc import Callable
from collections.abc import Sequence
from typing import Protocol, TypedDict, cast


class _ChatCompletionsProtocol(Protocol):
    """Minimal protocol for the openai chat.completions interface."""

    def create(self, **kwargs: object) -> object: ...


class _ChatProtocol(Protocol):
    completions: _ChatCompletionsProtocol


class _OpenAIClientProtocol(Protocol):
    chat: _ChatProtocol


class _PipelineProtocol(Protocol):
    def __call__(
        self,
        *,
        text: Sequence[dict[str, object]],
        max_new_tokens: int,
        do_sample: bool,
    ) -> list[dict[str, object]]: ...


class _GeneratedMessage(TypedDict, total=False):
    role: str
    content: str


class _PipelineResult(TypedDict, total=False):
    generated_text: str | list[_GeneratedMessage]


class TranscriptTranslationError(RuntimeError):
    pass


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Split *text* into word-boundary chunks of at most *max_chars* characters."""
    if not text:
        return []

    limit = max(1, max_chars)
    chunks: list[str] = []
    current = ""

    for word in text.split():
        if len(word) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(word[i : i + limit] for i in range(0, len(word), limit))
            continue

        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = word

    if current:
        chunks.append(current)

    return chunks


class TranscriptTranslator:
    pipeline_factory: Callable[..., _PipelineProtocol]
    model_name: str
    source_lang_code: str
    target_lang_code: str
    max_chars_per_request: int
    max_new_tokens: int
    _pipeline: _PipelineProtocol | None = None

    def __init__(
        self,
        *,
        pipeline_factory: Callable[..., _PipelineProtocol],
        model_name: str = "google/translategemma-12b-it",
        source_lang_code: str = "hi",
        target_lang_code: str = "en",
        max_chars_per_request: int = 1500,
        max_new_tokens: int = 256,
    ) -> None:
        self.pipeline_factory = pipeline_factory
        self.model_name = model_name
        self.source_lang_code = source_lang_code
        self.target_lang_code = target_lang_code
        self.max_chars_per_request = max_chars_per_request
        self.max_new_tokens = max_new_tokens

    def chunk_text(self, text: str) -> list[str]:
        return _chunk_text(text, self.max_chars_per_request)

    def translate_text(self, text: str) -> str:
        if not text.strip():
            return ""

        translated_chunks: list[str] = []
        for chunk in self.chunk_text(text):
            translated_chunks.append(self._translate_chunk(chunk))

        return " ".join(part for part in translated_chunks if part)

    def _get_pipeline(self) -> _PipelineProtocol:
        if self._pipeline is None:
            self._pipeline = self.pipeline_factory(
                task="image-text-to-text",
                model=self.model_name,
            )
        return self._pipeline

    def _translate_chunk(self, chunk: str) -> str:
        payload: list[dict[str, object]] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": chunk,
                        "source_lang_code": self.source_lang_code,
                        "target_lang_code": self.target_lang_code,
                    }
                ],
            }
        ]

        try:
            pipeline = self._get_pipeline()
            response = pipeline(
                text=payload,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
            )
            return self._extract_translated_text(response)
        except TranscriptTranslationError:
            raise
        except Exception as exc:
            raise TranscriptTranslationError(
                f"TranslateGemma translation failed: {exc}"
            ) from exc

    def _extract_translated_text(self, response: object) -> str:
        if not isinstance(response, list) or not response:
            raise TranscriptTranslationError("TranslateGemma returned no output")

        response_items = cast(list[object], response)
        first = cast(_PipelineResult, response_items[0])
        if "generated_text" not in first:
            raise TranscriptTranslationError(
                "TranslateGemma response did not include text"
            )

        generated = first["generated_text"]
        if isinstance(generated, str):
            text = generated.strip()
            if text:
                return text

        if isinstance(generated, list):
            generated_items = cast(list[object], generated)
            for raw_item in reversed(generated_items):
                if not isinstance(raw_item, dict):
                    continue

                item = cast(_GeneratedMessage, cast(object, raw_item))
                if "role" not in item or item["role"] != "assistant":
                    continue

                if "content" not in item:
                    continue

                content = item["content"]
                if content.strip():
                    return content.strip()

        raise TranscriptTranslationError("TranslateGemma response did not include text")

    @staticmethod
    def _split_long_word(word: str, limit: int) -> list[str]:
        return [word[i : i + limit] for i in range(0, len(word), limit)]


_DEFAULT_TRANSLATION_PROMPT = (
    "Translate the following Hinglish (Hindi-English mixed) text to clean, "
    "natural English. Output only the translated text, nothing else.\n\n"
    "Text: {text}"
)


class OpenRouterTranslator:
    """Translate text via an OpenAI-compatible API (e.g. OpenRouter).

    Satisfies :class:`TranslatorProtocol` from
    ``src.processors.youtube_processor``.
    """

    model_name: str
    source_lang_code: str
    target_lang_code: str
    max_chars_per_request: int
    max_new_tokens: int
    _client: _OpenAIClientProtocol | None

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://openrouter.ai/api/v1",
        model_name: str = "google/gemma-3-12b-it",
        source_lang_code: str = "hi",
        target_lang_code: str = "en",
        max_chars_per_request: int = 3000,
        max_new_tokens: int = 1024,
        prompt_template: str | None = None,
        client_factory: Callable[..., _OpenAIClientProtocol] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self.model_name = model_name
        self.source_lang_code = source_lang_code
        self.target_lang_code = target_lang_code
        self.max_chars_per_request = max_chars_per_request
        self.max_new_tokens = max_new_tokens
        self._prompt_template = prompt_template or _DEFAULT_TRANSLATION_PROMPT
        self._client_factory = client_factory
        self._client = None

    # ------------------------------------------------------------------
    # Public interface (TranslatorProtocol)
    # ------------------------------------------------------------------

    def translate_text(self, text: str) -> str:
        if not text.strip():
            return ""

        translated_chunks: list[str] = []
        for chunk in _chunk_text(text, self.max_chars_per_request):
            translated_chunks.append(self._translate_chunk(chunk))

        return " ".join(part for part in translated_chunks if part)

    def chunk_text(self, text: str) -> list[str]:
        return _chunk_text(text, self.max_chars_per_request)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_client(self) -> _OpenAIClientProtocol:
        if self._client is not None:
            return self._client

        if self._client_factory is not None:
            client = self._client_factory(
                api_key=self._api_key,
                base_url=self._base_url,
            )
        else:
            from openai import OpenAI

            resolved_key = self._api_key or os.environ.get("TRANSLATION_API_KEY", "")
            if not resolved_key:
                raise TranscriptTranslationError(
                    "TRANSLATION_API_KEY environment variable is not set"
                )
            # OpenAI client satisfies our protocol at runtime; cast through object
            # to satisfy basedpyright's strict overlap check.
            client = cast(_OpenAIClientProtocol, cast(object, OpenAI(api_key=resolved_key, base_url=self._base_url)))

        self._client = client
        return client

    def _build_user_prompt(self, chunk: str) -> str:
        return self._prompt_template.format(text=chunk)

    def _translate_chunk(self, chunk: str) -> str:
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": self._build_user_prompt(chunk)}],
                max_tokens=self.max_new_tokens,
                temperature=0.1,
            )
            return self._extract_content(response)
        except TranscriptTranslationError:
            raise
        except Exception as exc:
            raise TranscriptTranslationError(
                f"OpenRouter translation failed: {exc}"
            ) from exc

    @staticmethod
    def _extract_content(response: object) -> str:
        # response.choices[0].message.content
        choices = getattr(response, "choices", None)
        if not choices:
            raise TranscriptTranslationError("OpenRouter returned no choices")
        message = getattr(choices[0], "message", None)
        if message is None:
            raise TranscriptTranslationError("OpenRouter response missing message")
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise TranscriptTranslationError(
                "OpenRouter response did not include text content"
            )
        return content.strip()


__all__ = [
    "OpenRouterTranslator",
    "TranscriptTranslationError",
    "TranscriptTranslator",
]
