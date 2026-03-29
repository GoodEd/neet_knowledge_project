# S3 Transcript Translation Index Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an opt-in stored-source workflow that translates `s3_transcript_json_uri` YouTube transcripts into English with TranslateGemma, writes translated embeddings to a separate FAISS index, and supports CLI backfill for existing stored sources.

**Architecture:** Keep the current default ingestion and active index untouched. Add a translation-aware stored-source command in `src/main.py`, route eligible sources through a translation-capable `YouTubeProcessor` path, and write translated documents only to a target index chosen by `index_name`. Preserve original transcript text in metadata and enforce all-or-nothing indexing per source.

**Tech Stack:** Python, argparse, SQLite-backed `ContentSourceManager`, existing `NEETRAG`/FAISS vector store pipeline, Hugging Face `transformers`, TranslateGemma (`google/translategemma-12b-it`), pytest.

---

## File Structure

**Modify**
- `config.yaml` — add disabled-by-default translation config defaults
- `src/utils/config.py` — expose translation config accessors
- `src/processors/youtube_processor.py` — add translation-aware S3 transcript handling and translated metadata shaping
- `src/main.py` — add `translate-s3-transcripts` subcommand and activation/exit semantics

**Create**
- `src/translation/transcript_translator.py` — focused TranslateGemma adapter and chunk-safe translation helpers
- `tests/test_transcript_translator.py` — unit tests for request shaping, chunking, and error handling
- `tests/test_translate_s3_transcripts_cli.py` — CLI behavior tests for source filtering, skip/force, activation, and failures
- `tests/test_youtube_processor_translation.py` — processor-level tests for translated document metadata and atomic source preparation

**Potentially Modify**
- `src/rag/vector_store.py` — only if a small helper is needed for source-scoped existence/deletion checks in the target index
- `tests/conftest.py` — only if shared fixtures for fake sources or fake vector stores simplify the new tests

## Chunk 1: Translation Configuration and Adapter

### Task 1: Add translation config defaults

**Files:**
- Modify: `config.yaml`
- Modify: `src/utils/config.py`
- Test: `tests/test_transcript_translator.py`

- [ ] **Step 1: Write the failing config-access test**

```python
from src.utils.config import Config


def test_translation_config_defaults_present(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")

    config = Config(str(config_path))

    assert config.get("translation.enabled", False) is False
    assert config.get("translation.model") == "google/translategemma-12b-it"
    assert config.get("translation.source_lang") == "hi"
    assert config.get("translation.target_lang") == "en"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_transcript_translator.py::test_translation_config_defaults_present -v`
Expected: FAIL because translation defaults/accessors do not exist yet.

- [ ] **Step 3: Add translation defaults to config files**

Implement:
- a `translation:` section in `config.yaml`
- `Config` accessors or `get()`-based defaults for:
  - enabled
  - provider
  - model
  - source_lang
  - target_lang
  - max_chars_per_request
  - apply_only_to_s3_transcript

Keep defaults disabled.

- [ ] **Step 4: Re-run the config test**

Run: `pytest tests/test_transcript_translator.py::test_translation_config_defaults_present -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config.yaml src/utils/config.py tests/test_transcript_translator.py
git commit -m "feat: add translation config defaults"
```

### Task 2: Create the TranslateGemma adapter

**Files:**
- Create: `src/translation/transcript_translator.py`
- Test: `tests/test_transcript_translator.py`

- [ ] **Step 1: Write failing tests for the adapter contract**

Cover:
- request shape uses `source_lang_code`/`target_lang_code`
- long input is chunked before translation
- model/inference errors raise a translator-specific exception or structured failure

Example skeleton:

```python
from src.translation.transcript_translator import TranscriptTranslator


def test_translate_text_builds_translategemma_message(monkeypatch):
    captured = {}

    class FakePipeline:
        def __call__(self, *, text, max_new_tokens):
            captured["text"] = text
            return [{"generated_text": text + [{"role": "assistant", "content": "hello"}]}]

    translator = TranscriptTranslator(pipeline_factory=lambda **_: FakePipeline())
    out = translator.translate_text("namaste dosto")

    payload = captured["text"][0]["content"][0]
    assert payload["source_lang_code"] == "hi"
    assert payload["target_lang_code"] == "en"
    assert out == "hello"
```

- [ ] **Step 2: Run the translator tests to verify they fail**

Run: `pytest tests/test_transcript_translator.py -v`
Expected: FAIL because the module/class does not exist yet.

- [ ] **Step 3: Implement the minimal adapter**

Implement a focused module that:
- lazily creates the Hugging Face pipeline or model wrapper
- translates plain text using the official TranslateGemma message format
- chunks large text safely using `max_chars_per_request`
- returns deterministic English text
- does not mutate source text

Keep this logic out of `YouTubeProcessor` so the processor only coordinates transcript flow.

- [ ] **Step 4: Re-run the translator tests**

Run: `pytest tests/test_transcript_translator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/translation/transcript_translator.py tests/test_transcript_translator.py
git commit -m "feat: add translategemma transcript adapter"
```

## Chunk 2: Translation-Aware YouTube Processing

### Task 3: Add translated S3 transcript document preparation

**Files:**
- Modify: `src/processors/youtube_processor.py`
- Test: `tests/test_youtube_processor_translation.py`

- [ ] **Step 1: Write failing tests for translated document preparation**

Cover:
- only S3 transcript-backed sources are eligible
- translated documents use English text as content
- metadata preserves `original_text`, `translation_applied`, `translation_status`, `translation_model`, `translation_source`, `translated_from_lang`, `translated_to_lang`, and existing source metadata
- translation failures do not yield partial source documents

Example skeleton:

```python
def test_prepare_translated_s3_transcript_documents_preserves_original_text(monkeypatch):
    processor = YouTubeProcessor()
    entries = [
        {"text": "aaj hum bonding padh rahe hain", "start": 0.0, "duration": 4.0, "video_title": "Demo", "track_id": "s3_transcript"}
    ]

    monkeypatch.setattr(processor, "_load_transcript_from_s3_json", lambda **_: entries)
    monkeypatch.setattr(processor, "_translate_transcript_entries", lambda transcript_entries, **_: [dict(entries[0], translated_text="today we are studying bonding")])

    docs = processor._create_documents(
        [{**entries[0], "translated_text": "today we are studying bonding"}],
        "https://www.youtube.com/watch?v=abcdefghijk",
        "abcdefghijk",
    )

    assert docs[0].page_content == "today we are studying bonding"
    assert docs[0].metadata["original_text"] == "aaj hum bonding padh rahe hain"
    assert docs[0].metadata["translation_applied"] is True
    assert docs[0].metadata["translation_model"] == "google/translategemma-12b-it"
    assert docs[0].metadata["translation_source"] == "s3_transcript_json"
    assert docs[0].metadata["translated_from_lang"] == "hi"
    assert docs[0].metadata["translated_to_lang"] == "en"
```

- [ ] **Step 2: Run the new processor tests to verify they fail**

Run: `pytest tests/test_youtube_processor_translation.py -v`
Expected: FAIL because the translation-aware path and metadata do not exist yet.

- [ ] **Step 3: Implement translation-aware document preparation**

Implement:
- a focused helper in `YouTubeProcessor` for translated S3 transcript preparation
- translation hooks that only run for explicit translated-index flows
- document creation that uses translated text when available and preserves original text in metadata
- all-or-nothing source preparation before any target index mutation

Do **not** alter current default `process()` behavior for non-translation flows.

- [ ] **Step 4: Re-run the processor tests**

Run: `pytest tests/test_youtube_processor_translation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/processors/youtube_processor.py tests/test_youtube_processor_translation.py
git commit -m "feat: prepare translated s3 transcript docs"
```

## Chunk 3: Stored-Source CLI and Target Index Semantics

### Task 4: Add the `translate-s3-transcripts` CLI subcommand

**Files:**
- Modify: `src/main.py`
- Modify: `src/utils/content_manager.py` (only if a small helper for filtered source enumeration improves clarity)
- Test: `tests/test_translate_s3_transcripts_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Cover:
- `--source-id` xor `--all`
- `--translation-model` overrides the default translation model passed to the translated ingestion path
- `--limit` restricts `--all` processing to at most N eligible stored sources in deterministic order
- ineligible source becomes handled `skipped`
- `--activate` only runs with zero failures and at least one success
- exit code is non-zero on failures

Example skeleton:

```python
def test_translate_s3_transcripts_requires_source_id_or_all():
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "translate-s3-transcripts", "--target-index-name", "translated"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "source-id" in result.stderr or "--all" in result.stderr
```

- [ ] **Step 2: Run the CLI tests to verify they fail**

Run: `pytest tests/test_translate_s3_transcripts_cli.py -v`
Expected: FAIL because the subcommand does not exist yet.

- [ ] **Step 3: Implement the subcommand**

Implement command behavior that:
- loads stored sources via `ContentSourceManager`
- selects one source or all eligible sources
- applies `--limit` after eligibility filtering for `--all` runs
- passes `--translation-model` through to the translation adapter / translated processing path
- routes each eligible source through translated S3 transcript preparation
- writes docs to the target index selected by `--target-index-name`
- prints per-source result rows and a final summary
- returns non-zero if any source fails

Keep `translate-s3-transcripts` scoped to stored-source YouTube records only.

- [ ] **Step 4: Re-run the CLI tests**

Run: `pytest tests/test_translate_s3_transcripts_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/main.py src/utils/content_manager.py tests/test_translate_s3_transcripts_cli.py
git commit -m "feat: add s3 transcript translation backfill command"
```

### Task 5: Enforce target-index idempotency and `--force`

**Files:**
- Modify: `src/main.py`
- Modify: `src/rag/vector_store.py` (only if needed for source-scoped checks/deletion)
- Test: `tests/test_translate_s3_transcripts_cli.py`

- [ ] **Step 1: Write failing idempotency tests**

Cover:
- existing translated docs in the target index produce `skipped_existing` by default
- `--force` deletes target-index docs for that `source_id` and rebuilds them
- default/current index is untouched
- explicit `--translation-model` reruns still follow the same `skipped_existing` vs `--force` semantics

- [ ] **Step 2: Run the focused idempotency tests to verify they fail**

Run: `pytest tests/test_translate_s3_transcripts_cli.py -k "force or skipped_existing" -v`
Expected: FAIL.

- [ ] **Step 3: Implement target-index rerun semantics**

Implement the exact approved behavior:
- detect whether target index already contains docs for the `source_id`
- if present and `--force` is false, skip with `skipped_existing`
- if present and `--force` is true, delete only that source from the **target** index, then rebuild
- never delete from the current active index as part of this command

- [ ] **Step 4: Re-run the idempotency tests**

Run: `pytest tests/test_translate_s3_transcripts_cli.py -k "force or skipped_existing" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/main.py src/rag/vector_store.py tests/test_translate_s3_transcripts_cli.py
git commit -m "feat: make translated index backfill idempotent"
```

## Chunk 4: End-to-End Validation and Documentation Sync

### Task 6: Add end-to-end source-level atomicity tests

**Files:**
- Modify: `tests/test_youtube_processor_translation.py`
- Modify: `tests/test_translate_s3_transcripts_cli.py`

- [ ] **Step 1: Write a failing atomicity test**

Cover the case where translation succeeds for an early chunk but fails later in the same source. Assert that no documents for that source are written to the target index.

- [ ] **Step 2: Run the atomicity tests to verify they fail**

Run: `pytest tests/test_youtube_processor_translation.py tests/test_translate_s3_transcripts_cli.py -k atomic -v`
Expected: FAIL.

- [ ] **Step 3: Implement the minimal atomic write behavior**

Ensure:
- document preparation finishes before source deletion/rewrite in target index
- per-source write happens only after successful preparation
- failure leaves prior target-index state unchanged unless `--force` deletion is explicitly deferred until after preparation succeeds

- [ ] **Step 4: Re-run the atomicity tests**

Run: `pytest tests/test_youtube_processor_translation.py tests/test_translate_s3_transcripts_cli.py -k atomic -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_youtube_processor_translation.py tests/test_translate_s3_transcripts_cli.py src/main.py src/processors/youtube_processor.py
git commit -m "fix: make translated source writes atomic"
```

### Task 7: Run full verification for the feature slice

**Files:**
- Modify: any files touched above only as needed to fix failures
- Test: `tests/test_transcript_translator.py`
- Test: `tests/test_youtube_processor_translation.py`
- Test: `tests/test_translate_s3_transcripts_cli.py`

- [ ] **Step 1: Run the targeted test suite**

Run: `pytest tests/test_transcript_translator.py tests/test_youtube_processor_translation.py tests/test_translate_s3_transcripts_cli.py -v`
Expected: PASS.

- [ ] **Step 2: Run the existing related vector-store regression test**

Run: `pytest tests/test_composite_vector_store.py -v`
Expected: PASS.

- [ ] **Step 3: Run diagnostics / type-aware checks on touched files**

Run language-server diagnostics or the repo’s preferred static check on:
- `src/main.py`
- `src/processors/youtube_processor.py`
- `src/utils/config.py`
- `src/translation/transcript_translator.py`

Expected: zero new errors.

- [ ] **Step 4: Run any repo-level targeted command that exercises CLI importability**

Run: `python -m src.main --help`
Expected: exit code 0 and includes `translate-s3-transcripts`.

- [ ] **Step 5: Commit**

```bash
git add config.yaml src/main.py src/utils/config.py src/processors/youtube_processor.py src/translation/transcript_translator.py tests/test_transcript_translator.py tests/test_youtube_processor_translation.py tests/test_translate_s3_transcripts_cli.py
git commit -m "feat: add translated s3 transcript indexing workflow"
```
