# pyright: reportUnknownMemberType=none, reportUnknownParameterType=none, reportUnusedParameter=none, reportUnannotatedClassAttribute=none, reportUnknownArgumentType=none, reportUnknownVariableType=none, reportUnknownLambdaType=none
import os
import sys
from pathlib import Path

import pytest
from langchain_core.documents import Document

sys.path[:0] = [os.path.join(os.path.dirname(__file__), "..")]

from src.utils.content_manager import ContentSource


def _build_source(
    *,
    source_id: str,
    source_type: str = "youtube",
    s3_uri: str | None = "s3://bucket/transcript.json",
    track_id: str | None = None,
) -> ContentSource:
    metadata: dict[str, str] = {}
    if s3_uri:
        metadata["s3_transcript_json_uri"] = s3_uri
    if track_id:
        metadata["track_id"] = track_id
    return ContentSource(
        source_id=source_id,
        url=f"https://www.youtube.com/watch?v={source_id[:11].ljust(11, 'x')}",
        source_type=source_type,
        title=f"title-{source_id}",
        metadata=metadata,
    )


def _run_main(argv: list[str]) -> int:
    import src.main as main_module

    return main_module.main(argv)


def test_cli_requires_exactly_one_of_source_id_or_all():
    with pytest.raises(SystemExit) as exc_info:
        _ = _run_main(
            [
                "translate-s3-transcripts",
                "--target-index-name",
                "translated-index",
            ]
        )

    assert exc_info.value.code == 2


def test_cli_rejects_both_source_id_and_all_together():
    with pytest.raises(SystemExit) as exc_info:
        _ = _run_main(
            [
                "translate-s3-transcripts",
                "--source-id",
                "src-1",
                "--all",
                "--target-index-name",
                "translated-index",
            ]
        )

    assert exc_info.value.code == 2


def test_cli_requires_target_index_name_for_translate_s3_transcripts():
    with pytest.raises(SystemExit) as exc_info:
        _ = _run_main(
            [
                "translate-s3-transcripts",
                "--source-id",
                "src-1",
            ]
        )

    assert exc_info.value.code == 2


def test_translation_model_is_forwarded_to_translator(monkeypatch: pytest.MonkeyPatch):
    import src.main as main_module

    selected_sources = {"src-1": _build_source(source_id="src-1")}
    translator_models: list[str] = []
    loaded_uris: list[str] = []
    added_docs: list[Document] = []

    class FakeSourceManager:
        def get_source(self, source_id: str):
            return selected_sources.get(source_id)

        def get_all_sources(self):
            return list(selected_sources.values())

    class FakeProcessor:
        def _extract_video_id(self, url: str):
            return "video1234567"

        def _load_transcript_from_s3_json(
            self, s3_transcript_json_uri: str, video_title: str, track_id: str
        ):
            loaded_uris.append(s3_transcript_json_uri)
            return [
                {
                    "text": "namaste",
                    "start": 0.0,
                    "duration": 1.0,
                    "video_title": video_title,
                    "track_id": track_id,
                }
            ]

        def prepare_translated_documents(self, **kwargs: object) -> dict[str, object]:
            return {
                "status": "success",
                "documents": [Document(page_content="hello", metadata={})],
                "error": None,
            }

    class FakeVectorStore:
        def __init__(self, **_: object):
            self.persist_directory = "unused"

        def load_vectorstore(self):
            raise FileNotFoundError("no index yet")

        def has_documents_for_source_id(self, source_id: str) -> bool:
            _ = source_id
            return False

        def add_documents(self, documents: list[Document]) -> None:
            added_docs.extend(documents)

    def fake_build_translator(*, model_name: str):
        translator_models.append(model_name)

        class _Translator:
            source_lang_code = "hi"
            target_lang_code = "en"

            def __init__(self):
                self.model_name = model_name

            def translate_text(self, text: str) -> str:
                return f"translated:{text}"

        return _Translator()

    monkeypatch.setattr(main_module, "ContentSourceManager", FakeSourceManager)
    monkeypatch.setattr(main_module, "YouTubeProcessor", FakeProcessor)
    monkeypatch.setattr(main_module, "VectorStoreManager", FakeVectorStore)
    monkeypatch.setattr(
        main_module, "build_translation_translator", fake_build_translator
    )
    monkeypatch.setattr(
        main_module,
        "resolve_index_directory",
        lambda **_: str(Path("/tmp/index-target")),
    )
    monkeypatch.setattr(main_module, "set_active_index", lambda **_: {"ok": True})

    exit_code = _run_main(
        [
            "translate-s3-transcripts",
            "--source-id",
            "src-1",
            "--target-index-name",
            "translated-index",
            "--translation-model",
            "google/translategemma-27b-it",
        ]
    )

    assert exit_code == 0
    assert translator_models == ["google/translategemma-27b-it"]
    assert loaded_uris == ["s3://bucket/transcript.json"]
    assert added_docs[0].metadata["source_id"] == "src-1"


def test_all_mode_applies_limit_after_eligibility_filter_in_deterministic_order(
    monkeypatch: pytest.MonkeyPatch,
):
    import src.main as main_module

    src_eligible_b = _build_source(source_id="src-b", track_id="src-b")
    src_ineligible_type = _build_source(source_id="src-c", source_type="html")
    src_ineligible_no_s3 = _build_source(source_id="src-d", s3_uri=None)
    src_eligible_a = _build_source(source_id="src-a", track_id="src-a")
    all_sources = [
        src_eligible_b,
        src_ineligible_type,
        src_ineligible_no_s3,
        src_eligible_a,
    ]
    translated_source_ids: list[str] = []

    class FakeSourceManager:
        def get_source(self, source_id: str):
            return None

        def get_all_sources(self):
            return all_sources

    class FakeProcessor:
        def _extract_video_id(self, url: str):
            return "video1234567"

        def _load_transcript_from_s3_json(
            self, s3_transcript_json_uri: str, video_title: str, track_id: str
        ):
            return [
                {
                    "text": "hindi line",
                    "start": 0.0,
                    "duration": 1.0,
                    "video_title": "vt",
                    "track_id": track_id,
                }
            ]

        def prepare_translated_documents(
            self,
            *,
            transcript_entries: list[dict[str, object]],
            **_: object,
        ) -> dict[str, object]:
            source_id = transcript_entries[0]["track_id"]
            assert isinstance(source_id, str)
            translated_source_ids.append(source_id)
            return {
                "status": "success",
                "documents": [Document(page_content="ok", metadata={})],
                "error": None,
            }

    class FakeVectorStore:
        def __init__(self, **_: object):
            pass

        def load_vectorstore(self):
            raise FileNotFoundError

        def has_documents_for_source_id(self, source_id: str) -> bool:
            _ = source_id
            return False

        def add_documents(self, documents: list[Document]) -> None:
            _ = documents

    class FakeTranslator:
        model_name = "m"
        source_lang_code = "hi"
        target_lang_code = "en"

        def translate_text(self, text: str) -> str:
            return text

    monkeypatch.setattr(main_module, "ContentSourceManager", FakeSourceManager)
    monkeypatch.setattr(main_module, "YouTubeProcessor", FakeProcessor)
    monkeypatch.setattr(main_module, "VectorStoreManager", FakeVectorStore)
    monkeypatch.setattr(
        main_module,
        "build_translation_translator",
        lambda **_: FakeTranslator(),
    )
    monkeypatch.setattr(
        main_module,
        "resolve_index_directory",
        lambda **_: str(Path("/tmp/index-target")),
    )

    exit_code = _run_main(
        [
            "translate-s3-transcripts",
            "--all",
            "--limit",
            "1",
            "--target-index-name",
            "translated-index",
        ]
    )

    assert exit_code == 0
    assert translated_source_ids == ["src-a"]


def test_activate_runs_only_when_zero_failures_and_at_least_one_success(
    monkeypatch: pytest.MonkeyPatch,
):
    import src.main as main_module

    source = _build_source(source_id="src-1")
    activated_calls: list[dict[str, object]] = []

    class FakeSourceManager:
        def get_source(self, source_id: str):
            return source if source_id == "src-1" else None

        def get_all_sources(self):
            return [source]

    class FakeProcessor:
        def _extract_video_id(self, url: str):
            return "video1234567"

        def _load_transcript_from_s3_json(self, **_: object):
            return [
                {
                    "text": "hi",
                    "start": 0.0,
                    "duration": 1.0,
                    "video_title": "v",
                    "track_id": "t",
                }
            ]

        def prepare_translated_documents(self, **kwargs: object) -> dict[str, object]:
            return {
                "status": "success",
                "documents": [Document(page_content="ok", metadata={})],
                "error": None,
            }

    class FakeVectorStore:
        def __init__(self, **_: object):
            pass

        def load_vectorstore(self):
            raise FileNotFoundError

        def has_documents_for_source_id(self, source_id: str) -> bool:
            _ = source_id
            return False

        def add_documents(self, documents: list[Document]) -> None:
            _ = documents

    class FakeTranslator:
        model_name = "m"
        source_lang_code = "hi"
        target_lang_code = "en"

        def translate_text(self, text: str) -> str:
            return text

    monkeypatch.setattr(main_module, "ContentSourceManager", FakeSourceManager)
    monkeypatch.setattr(main_module, "YouTubeProcessor", FakeProcessor)
    monkeypatch.setattr(main_module, "VectorStoreManager", FakeVectorStore)
    monkeypatch.setattr(
        main_module,
        "build_translation_translator",
        lambda **_: FakeTranslator(),
    )
    monkeypatch.setattr(
        main_module,
        "resolve_index_directory",
        lambda **_: str(Path("/tmp/index-target")),
    )
    monkeypatch.setattr(
        main_module,
        "set_active_index",
        lambda **kwargs: activated_calls.append(kwargs) or kwargs,
    )

    exit_code = _run_main(
        [
            "translate-s3-transcripts",
            "--source-id",
            "src-1",
            "--target-index-name",
            "translated-index",
            "--activate",
        ]
    )

    assert exit_code == 0
    assert len(activated_calls) == 1


def test_failure_path_returns_non_zero_and_does_not_activate(
    monkeypatch: pytest.MonkeyPatch,
):
    import src.main as main_module

    source = _build_source(source_id="src-1")
    activated_calls: list[dict[str, object]] = []

    class FakeSourceManager:
        def get_source(self, source_id: str):
            return source if source_id == "src-1" else None

        def get_all_sources(self):
            return [source]

    class FakeProcessor:
        def _extract_video_id(self, url: str):
            return "video1234567"

        def _load_transcript_from_s3_json(self, **_: object):
            raise RuntimeError("s3 broken")

        def prepare_translated_documents(self, **kwargs: object) -> dict[str, object]:
            raise AssertionError("should not be called when S3 load fails")

    class FakeVectorStore:
        def __init__(self, **_: object):
            pass

        def load_vectorstore(self):
            raise FileNotFoundError

        def has_documents_for_source_id(self, source_id: str) -> bool:
            _ = source_id
            return False

        def add_documents(self, documents: list[Document]) -> None:
            _ = documents

    class FakeTranslator:
        model_name = "m"
        source_lang_code = "hi"
        target_lang_code = "en"

        def translate_text(self, text: str) -> str:
            return text

    monkeypatch.setattr(main_module, "ContentSourceManager", FakeSourceManager)
    monkeypatch.setattr(main_module, "YouTubeProcessor", FakeProcessor)
    monkeypatch.setattr(main_module, "VectorStoreManager", FakeVectorStore)
    monkeypatch.setattr(
        main_module,
        "build_translation_translator",
        lambda **_: FakeTranslator(),
    )
    monkeypatch.setattr(
        main_module,
        "resolve_index_directory",
        lambda **_: str(Path("/tmp/index-target")),
    )
    monkeypatch.setattr(
        main_module,
        "set_active_index",
        lambda **kwargs: activated_calls.append(kwargs) or kwargs,
    )

    exit_code = _run_main(
        [
            "translate-s3-transcripts",
            "--source-id",
            "src-1",
            "--target-index-name",
            "translated-index",
            "--activate",
        ]
    )

    assert exit_code != 0
    assert activated_calls == []


def test_single_ineligible_source_is_reported_as_skipped_not_failed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    import src.main as main_module

    ineligible_source = _build_source(source_id="src-1", source_type="html")

    class FakeSourceManager:
        def get_source(self, source_id: str):
            return ineligible_source if source_id == "src-1" else None

        def get_all_sources(self):
            return [ineligible_source]

    class FakeProcessor:
        def _extract_video_id(self, url: str):
            raise AssertionError("ineligible source should not hit processor path")

        def _load_transcript_from_s3_json(self, **_: object):
            raise AssertionError("ineligible source should not load transcript")

        def prepare_translated_documents(self, **kwargs: object) -> dict[str, object]:
            raise AssertionError("ineligible source should not translate")

    def fail_vector_store_creation(**_: object):
        raise AssertionError("vector store should not be created for no-op run")

    def fail_translator_creation(**_: object):
        raise AssertionError("translator should not be created for no-op run")

    monkeypatch.setattr(main_module, "ContentSourceManager", FakeSourceManager)
    monkeypatch.setattr(main_module, "YouTubeProcessor", FakeProcessor)
    monkeypatch.setattr(main_module, "VectorStoreManager", fail_vector_store_creation)
    monkeypatch.setattr(
        main_module, "build_translation_translator", fail_translator_creation
    )
    monkeypatch.setattr(
        main_module,
        "resolve_index_directory",
        lambda **_: str(Path("/tmp/index-target")),
    )

    exit_code = _run_main(
        [
            "translate-s3-transcripts",
            "--source-id",
            "src-1",
            "--target-index-name",
            "translated-index",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "src-1: skipped (ineligible)" in output
    assert "Summary: success=0 skipped=1 failed=0" in output


def test_skipped_existing_by_default_when_target_has_docs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    import src.main as main_module

    source = _build_source(source_id="src-1")
    translated_calls: list[str] = []
    translator_create_calls: list[str] = []

    class FakeSourceManager:
        def get_source(self, source_id: str):
            return source if source_id == "src-1" else None

        def get_all_sources(self):
            return [source]

    class FakeProcessor:
        def _extract_video_id(self, url: str):
            translated_calls.append(f"extract:{url}")
            return "video1234567"

        def _load_transcript_from_s3_json(self, **_: object):
            translated_calls.append("load")
            return []

        def prepare_translated_documents(self, **kwargs: object) -> dict[str, object]:
            translated_calls.append("prepare")
            _ = kwargs
            return {"status": "failed", "documents": [], "error": "unexpected"}

    class FakeVectorStore:
        def __init__(self, **_: object):
            self.persist_directory = "unused"

        def load_vectorstore(self):
            return None

        def has_documents_for_source_id(self, source_id: str) -> bool:
            assert source_id == "src-1"
            return True

        def delete_by_source_id(self, source_id: str) -> int:
            raise AssertionError(f"should not delete without --force for {source_id}")

        def add_documents(self, documents: list[Document]) -> None:
            raise AssertionError(f"should not add docs: {documents}")

    def fake_build_translator(*, model_name: str):
        translator_create_calls.append(model_name)

        class FakeTranslator:
            model_name = "m"
            source_lang_code = "hi"
            target_lang_code = "en"

            def translate_text(self, text: str) -> str:
                return text

        return FakeTranslator()

    monkeypatch.setattr(main_module, "ContentSourceManager", FakeSourceManager)
    monkeypatch.setattr(main_module, "YouTubeProcessor", FakeProcessor)
    monkeypatch.setattr(main_module, "VectorStoreManager", FakeVectorStore)
    monkeypatch.setattr(
        main_module,
        "build_translation_translator",
        fake_build_translator,
    )
    monkeypatch.setattr(
        main_module,
        "resolve_index_directory",
        lambda **_: str(Path("/tmp/index-target")),
    )

    exit_code = _run_main(
        [
            "translate-s3-transcripts",
            "--source-id",
            "src-1",
            "--target-index-name",
            "translated-index",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert translated_calls == []
    assert translator_create_calls == []
    assert "src-1: skipped (skipped_existing)" in output
    assert "Summary: success=0 skipped=1 failed=0" in output


def test_force_deletes_target_source_docs_and_rebuilds(
    monkeypatch: pytest.MonkeyPatch,
):
    import src.main as main_module

    source = _build_source(source_id="src-1")
    delete_calls: list[str] = []
    add_counts: list[int] = []

    class FakeSourceManager:
        def get_source(self, source_id: str):
            return source if source_id == "src-1" else None

        def get_all_sources(self):
            return [source]

    class FakeProcessor:
        def _extract_video_id(self, url: str):
            return "video1234567"

        def _load_transcript_from_s3_json(self, **_: object):
            return [
                {
                    "text": "namaste",
                    "start": 0.0,
                    "duration": 1.0,
                    "video_title": "title",
                    "track_id": "track",
                }
            ]

        def prepare_translated_documents(self, **kwargs: object) -> dict[str, object]:
            _ = kwargs
            return {
                "status": "success",
                "documents": [Document(page_content="hello", metadata={})],
                "error": None,
            }

    class FakeVectorStore:
        def __init__(self, **_: object):
            self.persist_directory = "unused"

        def load_vectorstore(self):
            return None

        def has_documents_for_source_id(self, source_id: str) -> bool:
            assert source_id == "src-1"
            return True

        def delete_by_source_id(self, source_id: str) -> int:
            delete_calls.append(source_id)
            return 2

        def add_documents(self, documents: list[Document]) -> None:
            add_counts.append(len(documents))

    class FakeTranslator:
        model_name = "m"
        source_lang_code = "hi"
        target_lang_code = "en"

        def translate_text(self, text: str) -> str:
            return text

    monkeypatch.setattr(main_module, "ContentSourceManager", FakeSourceManager)
    monkeypatch.setattr(main_module, "YouTubeProcessor", FakeProcessor)
    monkeypatch.setattr(main_module, "VectorStoreManager", FakeVectorStore)
    monkeypatch.setattr(
        main_module,
        "build_translation_translator",
        lambda **_: FakeTranslator(),
    )
    monkeypatch.setattr(
        main_module,
        "resolve_index_directory",
        lambda **_: str(Path("/tmp/index-target")),
    )

    exit_code = _run_main(
        [
            "translate-s3-transcripts",
            "--source-id",
            "src-1",
            "--target-index-name",
            "translated-index",
            "--force",
        ]
    )

    assert exit_code == 0
    assert delete_calls == ["src-1"]
    assert add_counts == [1]


def test_force_only_deletes_in_target_index_not_current_default(
    monkeypatch: pytest.MonkeyPatch,
):
    import src.main as main_module

    source = _build_source(source_id="src-1")
    delete_calls: list[tuple[str, str]] = []
    resolved_target_dirs: list[str] = []

    class FakeSourceManager:
        def get_source(self, source_id: str):
            return source if source_id == "src-1" else None

        def get_all_sources(self):
            return [source]

    class FakeProcessor:
        def _extract_video_id(self, url: str):
            return "video1234567"

        def _load_transcript_from_s3_json(self, **_: object):
            return [
                {
                    "text": "namaste",
                    "start": 0.0,
                    "duration": 1.0,
                    "video_title": "title",
                    "track_id": "track",
                }
            ]

        def prepare_translated_documents(self, **kwargs: object) -> dict[str, object]:
            _ = kwargs
            return {
                "status": "success",
                "documents": [Document(page_content="hello", metadata={})],
                "error": None,
            }

    class FakeVectorStore:
        def __init__(self, **kwargs: object):
            self.persist_directory = str(kwargs["persist_directory"])

        def load_vectorstore(self):
            return None

        def has_documents_for_source_id(self, source_id: str) -> bool:
            assert source_id == "src-1"
            return True

        def delete_by_source_id(self, source_id: str) -> int:
            delete_calls.append((self.persist_directory, source_id))
            return 1

        def add_documents(self, documents: list[Document]) -> None:
            _ = documents

    class FakeTranslator:
        model_name = "m"
        source_lang_code = "hi"
        target_lang_code = "en"

        def translate_text(self, text: str) -> str:
            return text

    def fake_resolve_index_directory(**kwargs: object) -> str:
        _ = kwargs
        target = str(Path("/tmp/index-target"))
        resolved_target_dirs.append(target)
        return target

    monkeypatch.setattr(main_module, "ContentSourceManager", FakeSourceManager)
    monkeypatch.setattr(main_module, "YouTubeProcessor", FakeProcessor)
    monkeypatch.setattr(main_module, "VectorStoreManager", FakeVectorStore)
    monkeypatch.setattr(
        main_module,
        "build_translation_translator",
        lambda **_: FakeTranslator(),
    )
    monkeypatch.setattr(
        main_module,
        "resolve_index_directory",
        fake_resolve_index_directory,
    )

    exit_code = _run_main(
        [
            "translate-s3-transcripts",
            "--source-id",
            "src-1",
            "--target-index-name",
            "translated-index",
            "--force",
        ]
    )

    assert exit_code == 0
    assert resolved_target_dirs == [str(Path("/tmp/index-target"))]
    assert delete_calls == [(str(Path("/tmp/index-target")), "src-1")]


def test_force_rebuild_atomic_when_prepare_fails_does_not_delete_or_add_docs(
    monkeypatch: pytest.MonkeyPatch,
):
    import src.main as main_module

    source = _build_source(source_id="src-1")
    delete_calls: list[str] = []
    add_calls: list[int] = []

    class FakeSourceManager:
        def get_source(self, source_id: str):
            return source if source_id == "src-1" else None

        def get_all_sources(self):
            return [source]

    class FakeProcessor:
        def _extract_video_id(self, url: str):
            return "video1234567"

        def _load_transcript_from_s3_json(self, **_: object):
            return [
                {
                    "text": "namaste",
                    "start": 0.0,
                    "duration": 1.0,
                    "video_title": "title",
                    "track_id": "track",
                }
            ]

        def prepare_translated_documents(self, **kwargs: object) -> dict[str, object]:
            _ = kwargs
            return {
                "status": "failed",
                "documents": [],
                "error": "translation failed",
            }

    class FakeVectorStore:
        def __init__(self, **_: object):
            self.persist_directory = "unused"

        def load_vectorstore(self):
            return None

        def has_documents_for_source_id(self, source_id: str) -> bool:
            assert source_id == "src-1"
            return True

        def delete_by_source_id(self, source_id: str) -> int:
            delete_calls.append(source_id)
            return 2

        def add_documents(self, documents: list[Document]) -> None:
            add_calls.append(len(documents))

    class FakeTranslator:
        model_name = "m"
        source_lang_code = "hi"
        target_lang_code = "en"

        def translate_text(self, text: str) -> str:
            return text

    monkeypatch.setattr(main_module, "ContentSourceManager", FakeSourceManager)
    monkeypatch.setattr(main_module, "YouTubeProcessor", FakeProcessor)
    monkeypatch.setattr(main_module, "VectorStoreManager", FakeVectorStore)
    monkeypatch.setattr(
        main_module,
        "build_translation_translator",
        lambda **_: FakeTranslator(),
    )
    monkeypatch.setattr(
        main_module,
        "resolve_index_directory",
        lambda **_: str(Path("/tmp/index-target")),
    )

    exit_code = _run_main(
        [
            "translate-s3-transcripts",
            "--source-id",
            "src-1",
            "--target-index-name",
            "translated-index",
            "--force",
        ]
    )

    assert exit_code == 1
    assert delete_calls == []
    assert add_calls == []


def test_force_rebuild_atomic_when_prepare_raises_does_not_delete_or_add_docs(
    monkeypatch: pytest.MonkeyPatch,
):
    import src.main as main_module

    source = _build_source(source_id="src-1")
    delete_calls: list[str] = []
    add_calls: list[int] = []

    class FakeSourceManager:
        def get_source(self, source_id: str) -> ContentSource | None:
            return source if source_id == "src-1" else None

        def get_all_sources(self) -> list[ContentSource]:
            return [source]

    class FakeProcessor:
        def _extract_video_id(self, url: str) -> str:
            _ = url
            return "video1234567"

        def _load_transcript_from_s3_json(self, **_: object) -> list[dict[str, object]]:
            return [
                {
                    "text": "namaste",
                    "start": 0.0,
                    "duration": 1.0,
                    "video_title": "title",
                    "track_id": "track",
                }
            ]

        def prepare_translated_documents(self, **kwargs: object) -> dict[str, object]:
            _ = kwargs
            raise RuntimeError("translation crashed")

    class FakeVectorStore:
        def __init__(self, **_: object):
            self.persist_directory = "unused"

        def load_vectorstore(self) -> None:
            return None

        def has_documents_for_source_id(self, source_id: str) -> bool:
            assert source_id == "src-1"
            return True

        def delete_by_source_id(self, source_id: str) -> int:
            delete_calls.append(source_id)
            return 2

        def add_documents(self, documents: list[Document]) -> None:
            add_calls.append(len(documents))

    class FakeTranslator:
        model_name = "m"
        source_lang_code = "hi"
        target_lang_code = "en"

        def translate_text(self, text: str) -> str:
            return text

    monkeypatch.setattr(main_module, "ContentSourceManager", FakeSourceManager)
    monkeypatch.setattr(main_module, "YouTubeProcessor", FakeProcessor)
    monkeypatch.setattr(main_module, "VectorStoreManager", FakeVectorStore)
    monkeypatch.setattr(
        main_module,
        "build_translation_translator",
        lambda **_: FakeTranslator(),
    )
    monkeypatch.setattr(
        main_module,
        "resolve_index_directory",
        lambda **_: str(Path("/tmp/index-target")),
    )

    exit_code = _run_main(
        [
            "translate-s3-transcripts",
            "--source-id",
            "src-1",
            "--target-index-name",
            "translated-index",
            "--force",
        ]
    )

    assert exit_code == 1
    assert delete_calls == []
    assert add_calls == []


def test_translation_model_rerun_respects_skipped_existing_and_force(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    import src.main as main_module

    source = _build_source(source_id="src-1")
    translator_models: list[str] = []
    prepare_calls: list[str] = []
    delete_calls: list[str] = []

    class FakeSourceManager:
        def get_source(self, source_id: str):
            return source if source_id == "src-1" else None

        def get_all_sources(self):
            return [source]

    class FakeProcessor:
        def _extract_video_id(self, url: str):
            return "video1234567"

        def _load_transcript_from_s3_json(self, **_: object):
            return [
                {
                    "text": "namaste",
                    "start": 0.0,
                    "duration": 1.0,
                    "video_title": "title",
                    "track_id": "track",
                }
            ]

        def prepare_translated_documents(self, **kwargs: object) -> dict[str, object]:
            _ = kwargs
            prepare_calls.append("prepare")
            return {
                "status": "success",
                "documents": [Document(page_content="hello", metadata={})],
                "error": None,
            }

    class FakeVectorStore:
        def __init__(self, **_: object):
            self.persist_directory = "unused"

        def load_vectorstore(self):
            return None

        def has_documents_for_source_id(self, source_id: str) -> bool:
            assert source_id == "src-1"
            return True

        def delete_by_source_id(self, source_id: str) -> int:
            delete_calls.append(source_id)
            return 1

        def add_documents(self, documents: list[Document]) -> None:
            _ = documents

    def fake_build_translator(*, model_name: str):
        translator_models.append(model_name)

        class FakeTranslator:
            source_lang_code = "hi"
            target_lang_code = "en"

            def translate_text(self, text: str) -> str:
                return text

        return FakeTranslator()

    monkeypatch.setattr(main_module, "ContentSourceManager", FakeSourceManager)
    monkeypatch.setattr(main_module, "YouTubeProcessor", FakeProcessor)
    monkeypatch.setattr(main_module, "VectorStoreManager", FakeVectorStore)
    monkeypatch.setattr(
        main_module,
        "build_translation_translator",
        fake_build_translator,
    )
    monkeypatch.setattr(
        main_module,
        "resolve_index_directory",
        lambda **_: str(Path("/tmp/index-target")),
    )

    skipped_exit_code = _run_main(
        [
            "translate-s3-transcripts",
            "--source-id",
            "src-1",
            "--target-index-name",
            "translated-index",
            "--translation-model",
            "google/translategemma-27b-it",
        ]
    )
    skipped_output = capsys.readouterr().out
    assert translator_models == []

    forced_exit_code = _run_main(
        [
            "translate-s3-transcripts",
            "--source-id",
            "src-1",
            "--target-index-name",
            "translated-index",
            "--translation-model",
            "google/translategemma-27b-it",
            "--force",
        ]
    )

    assert skipped_exit_code == 0
    assert "src-1: skipped (skipped_existing)" in skipped_output
    assert forced_exit_code == 0
    assert translator_models == ["google/translategemma-27b-it"]
    assert prepare_calls == ["prepare"]
    assert delete_calls == ["src-1"]
