# On-Demand S3 Transcript Translation Index Design

## Goal

Add an opt-in path that translates `s3_transcript_json_uri` YouTube transcripts into English with `google/translategemma-12b-it`, embeds the translated text into a separate FAISS index, and preserves the original transcript text for traceability. Also provide a CLI workflow to backfill translated embeddings for existing S3 transcript sources already stored in the source database.

## Why this design

The current runtime embeds whatever text reaches `Document.page_content`. For Hinglish transcripts coming from S3 transcript JSON, English retrieval quality improves only if the translated English text is embedded before indexing. At the same time, the current index must remain untouched so operators can compare behavior, roll back safely, and avoid duplicate mixed-language vectors in the active index.

Using a separate index matches the repository's existing multi-index controls in `src/main.py`, keeps the current corpus stable, and gives a clean A/B path between the default multilingual corpus and the translated-English corpus.

## Scope

### In scope

- On-demand translation for YouTube ingestion when the source uses `s3_transcript_json_uri`
- Translation only when explicitly requested
- Separate translated-English FAISS index
- Preservation of original transcript text in document metadata
- CLI backfill for existing S3 transcript-backed sources in the database
- Per-source failure handling so one bad transcript does not abort the entire backfill

### Out of scope

- Always-on translation for all YouTube transcript sources
- Translation for `yt_api`, `yt_dlp`, or audio ASR paths unless they are routed through the same future workflow intentionally
- Replacing the active/default index automatically
- Changing the retrieval algorithm, reranking, or answer generation flow
- Translating query text at runtime

## Current repo shape

The relevant current flow is:

1. `NEETRAG.ingest_content()` routes YouTube URLs to `ContentProcessor.process_youtube()`.
2. `ContentProcessor` calls `YouTubeProcessor.process()`.
3. `YouTubeProcessor` fetches transcript entries from YouTube API, S3 transcript JSON, S3 audio ASR, or yt-dlp audio fallback.
4. `YouTubeProcessor._create_documents()` turns transcript entries into `langchain_core.documents.Document` instances.
5. `NEETRAG.ingest_processed_content()` converts those to LangChain docs and sends them to `VectorStoreManager.add_documents()`.
6. Search later uses FAISS similarity over the embedded `Document.page_content`.

This means translation must happen before or during document creation, and index separation should be handled at the ingestion/CLI layer rather than by mixing original and translated docs in one store.

## Recommended architecture

### 1. Opt-in translation mode for `s3_transcript_json_uri`

Add an explicit translation mode that is only activated when the caller requests translated indexing and the source has `s3_transcript_json_uri` metadata available.

The control surface should be explicit in both runtime and CLI flows:

- runtime ingestion receives a boolean-style translated-index flag plus a required target index name
- CLI backfill exposes the same translated-index behavior through a dedicated subcommand
- if the translated-index flag is absent, the current ingestion path is unchanged

Expected behavior:

- Default ingestion remains unchanged.
- If translation mode is disabled, `YouTubeProcessor` behaves exactly as it does today.
- If translation mode is enabled but the source is not backed by `s3_transcript_json_uri`, translation is skipped with a clear status message or result field.
- If translation mode is enabled and `s3_transcript_json_uri` exists, the processor loads the transcript JSON, translates the transcript text to English, chunks it, and produces documents for the translated index.

This keeps the feature intentionally narrow and avoids accidental translation of tracks that already have other normalization paths.

For the first version, the runtime control surface is intentionally limited to **stored-source ingestion flows** rather than arbitrary URL ingestion:

- the new translated path is entered through a dedicated CLI command for stored sources
- it operates on sources already known to `ContentSourceManager`
- it is keyed by `source_id` and source metadata, not by adding translation flags to the generic `ingest` command
- future expansion into generic `ingest` or `source update` flows is out of scope for this version

This constraint avoids threading new translation options through unrelated ingestion entrypoints and keeps the behavior aligned with the CLI backfill requirement.

### 2. Translation occurs before embedding, but only for translated-index ingestion

For eligible S3 transcript sources, TranslateGemma should run after transcript JSON is normalized into transcript entries and before final `Document` objects are produced for embedding.

Recommended internal shape:

- Normalize transcript entries as usual
- Translate entry text or chunk text into English
- Build a single document per translated chunk
- Use translated English as `page_content`
- Preserve original source text in metadata

Do not produce both original and translated documents for the same chunk in the same index.

### 3. Separate index is the isolation boundary

The translated corpus must live in a separate FAISS index selected by `index_name` / index activation rather than by creating a synthetic translation-only `track_id`.

Rationale:

- Keeps original active corpus untouched
- Avoids duplicate retrieval in a shared index
- Supports canary rollout and A/B testing
- Fits the existing `src.main index show|list|activate` model

`track_id` continues to represent transcript provenance, not index choice.

### 4. Per-source indexing must be atomic

Translated indexing is all-or-nothing at the source level.

Required rule:

- a source's translated documents are prepared fully in memory first
- the target index is modified only after translation and document construction complete successfully for that source
- if translation or chunk preparation fails partway through a source, no translated chunks for that source are written to the target index

This prevents mixed partial coverage for one source inside the translated corpus.

## Metadata design

Each translated document remains a single document, with translated English in `page_content` and original transcript text preserved in metadata.

Recommended metadata additions:

- `translation_applied: true`
- `translation_model: "google/translategemma-12b-it"`
- `translation_source: "s3_transcript_json"`
- `translation_status: "success" | "failed" | "skipped"`
- `translated_from_lang: "hi"`
- `translated_to_lang: "en"`
- `original_text: <raw chunk text before translation>`

Existing metadata such as `track_id`, `video_id`, `source`, `title`, and `start_time` should remain intact.

If translation is skipped or fails for a source in translated-index mode, the code should surface that explicitly rather than silently mixing untranslated docs into the translated index. In this first version, failed translation means the source is reported as failed or skipped for the translated index build, not embedded in untranslated form.

## Operational modes

### Mode A: On-demand translated ingestion for a single source

This mode is for manually requested ingestion when the operator wants translated embeddings for a specific **stored** S3 transcript source.

Expected flow:

1. Caller provides `--source-id` and a target translated index name
2. Source is loaded from `ContentSourceManager` and validated to ensure it has `s3_transcript_json_uri`
3. Transcript JSON is loaded from S3
4. Transcript is translated to English
5. Documents are written to a target translated index selected by the provided `index_name`
6. Default active index remains unchanged unless explicitly activated later

If the source exists but lacks `metadata.s3_transcript_json_uri`, the command should return a handled `skipped` result for that `source_id`, not a parser or usage error.

### Mode B: CLI backfill for existing sources

This mode is for building the translated corpus from already registered sources in the database.

Expected flow:

1. Enumerate existing sources from `ContentSourceManager`
2. Filter to YouTube sources with `metadata.s3_transcript_json_uri`
3. For each eligible source, run translated ingestion logic into the target index
4. Report per-source success/failure/skip results
5. Optionally activate the translated index after backfill completes

Backfill should use the existing `source_id` from the database as the stable unit of processing and reporting.

Default rerun behavior for existing target-index content must be explicit:

- if translated docs for a `source_id` are already present in the target index and `--force` is **not** set, that source is reported as `skipped_existing`
- if `--force` **is** set, existing translated docs for that `source_id` in the target index are deleted and rebuilt from scratch
- rerun behavior applies only to the target translated index and must never affect the current active/default index

## CLI design

The best fit is a new `src/main.py` subcommand rather than a one-off external script, because:

- this repo already centralizes index operations there
- the command can reuse current embedding/index arguments
- operators already have a mental model for `index` and `reindex`

Recommended command family:

```bash
python -m src.main translate-s3-transcripts \
  --target-index-name translated_s3_transcript_en \
  --source-id <source_id> \
  --translation-model google/translategemma-12b-it
```

and for batch backfill:

```bash
python -m src.main translate-s3-transcripts \
  --target-index-name translated_s3_transcript_en \
  --all \
  --activate
```

Recommended flags:

- `--source-id <id>`: translate one stored source
- `--all`: backfill all eligible stored sources
- `--target-index-name <name>`: required logical index name for translated corpus
- `--translation-model <name>`: defaults to `google/translategemma-12b-it`
- `--activate`: optional, switch active index after successful completion
- `--limit <n>`: optional canary/backfill throttle
- `--force`: optional, reprocess even if source appears already present in target index

`--source-id` and `--all` should be mutually exclusive.

If neither `--source-id` nor `--all` is provided, argument parsing should fail with a clear usage error.

Activation and exit semantics must also be explicit:

- `--activate` updates the active index **only if the command completes with zero `failed` sources**
- `skipped` and `skipped_existing` sources do not block activation
- if there is at least one success and zero failures, activation may proceed
- if there are zero successes, activation must not occur
- command exit code is non-zero when one or more sources fail; otherwise zero

## Config design

Add a dedicated translation config section so the new behavior is explicit and disabled by default.

Recommended shape in `config.yaml`:

```yaml
translation:
  enabled: false
  provider: transformers
  model: google/translategemma-12b-it
  source_lang: hi
  target_lang: en
  max_chars_per_request: 1500
  apply_only_to_s3_transcript: true
```

This config should define defaults, but actual translation use remains opt-in through the runtime/CLI path.

## TranslateGemma integration notes

TranslateGemma must be invoked with its chat template and explicit language codes. For this use case:

- model: `google/translategemma-12b-it`
- `source_lang_code="hi"`
- `target_lang_code="en"`
- deterministic generation preferred

Transcript text should be translated in chunks that stay safely under the model's effective context budget. The implementation should avoid passing very large transcript bodies in one request.

## Failure handling

Backfill and on-demand translation should be best-effort per source.

Recommended behavior:

- If a source lacks `s3_transcript_json_uri`, mark it `skipped`
- If S3 download fails, mark it `failed`
- If translation fails, mark it `failed`
- If indexing succeeds, mark it `success`
- Aggregate summary should include counts and source IDs

The default/current active index must not be mutated by this workflow unless the operator explicitly activates the translated target index after completion. Creating or populating the translated target index must never delete from or overwrite the current active index.

## What we should not do

- Do not write translated docs into the current active index by default
- Do not keep original and translated variants in the same index for the same source/chunk
- Do not overload `track_id` to mean “translated corpus”
- Do not expand this first version to all transcript types
- Do not introduce query-time translation as part of this scope

## Testing strategy

### Unit-level

- translation eligibility logic only accepts `s3_transcript_json_uri` sources
- metadata for translated docs contains original text and translation markers
- CLI argument validation enforces `--source-id` xor `--all`

### Integration-level

- ingest one stored YouTube source with `s3_transcript_json_uri` into a fresh translated index
- verify docs land only in the target index, not the current active one
- verify translated docs preserve original metadata and original text
- verify a source missing S3 transcript JSON is skipped cleanly
- verify translation failure does not insert untranslated fallback docs into the translated index

### Operational validation

- build a canary translated index for a small number of Hinglish sources
- compare English query results between the default index and translated index
- activate translated index only after manual validation

## Implementation surfaces

Expected primary files to change in the later implementation plan:

- `config.yaml`
- `src/utils/config.py`
- `src/processors/youtube_processor.py`
- `src/main.py`
- tests covering translated document creation and CLI backfill behavior

Potentially add a small translation helper module if keeping `YouTubeProcessor` focused becomes difficult.

## Open decisions already resolved for this design

- Translation is **on demand**, not automatic
- It applies to **`s3_transcript_json_uri` only**
- Translated embeddings live in a **separate index**
- Existing S3 transcript sources get a **CLI backfill path**

## Summary

The first version should add an opt-in translated-English indexing path for S3 transcript-backed YouTube sources, keep the default corpus unchanged, and provide a CLI to build a dedicated translated index from existing stored sources. This gives safe rollout, traceable documents, and a direct way to improve English retrieval over Hinglish transcript content without destabilizing the current system.
