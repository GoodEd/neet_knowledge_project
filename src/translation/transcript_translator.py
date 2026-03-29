from __future__ import annotations

from collections.abc import Callable
from collections.abc import Sequence
from typing import Protocol, TypedDict, cast


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
        if not text:
            return []

        limit = max(1, self.max_chars_per_request)
        chunks: list[str] = []
        current = ""

        for word in text.split():
            if len(word) > limit:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(self._split_long_word(word, limit))
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


__all__ = ["TranscriptTranslationError", "TranscriptTranslator"]
