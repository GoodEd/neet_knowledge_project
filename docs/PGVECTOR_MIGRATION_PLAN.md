# PostgreSQL pgvector Migration Plan (Deferred Execution)

## Status

- Plan state: approved for planning only
- Execution state: not started
- Constraint: do not execute any migration steps until explicitly authorized

---

## Purpose

This document captures a safe migration plan to move vector retrieval from the current FAISS-based setup to PostgreSQL + pgvector at a later date.

It is intentionally written as a staged plan with go/no-go gates, rollback options, and complexity estimates.

---

## Current Baseline (As-Is)

- Vector backend is FAISS, not Elasticsearch (`src/rag/vector_store.py`, `config.yaml`).
- Retrieval pipeline uses `similarity_search_with_score` and custom score conversion + thresholding (`src/rag/neet_rag.py`).
- Deployment docs assume EFS-backed persistence for FAISS in ECS (`docs/deployment.md`).

Implication: this migration is FAISS -> pgvector for this codebase.

---

## Decision Summary

Use PostgreSQL + pgvector if one or more are true:

1. Multiple concurrent writers are required.
2. Near-real-time visibility of new content is required.
3. SQL filtering and relational joins are needed for retrieval.
4. A managed PostgreSQL footprint already exists in production.

Stay on FAISS if all are true:

1. Corpus remains small-to-medium.
2. Ingestion can remain single-writer.
3. Current latency and relevance are acceptable.
4. Operational simplicity is prioritized.

---

## Scope

In scope:

- Add a pgvector-backed vector store adapter.
- Add database schema and indexes.
- Backfill data.
- Run dual-write and shadow-read phases.
- Perform zero-downtime cutover with rollback path.

Out of scope:

- Any immediate production execution.
- Non-vector architecture changes unrelated to retrieval.

---

## Target Architecture (Planned)

- PostgreSQL table stores chunk text, metadata, embedding vector, timestamps.
- pgvector index (HNSW or IVFFlat) supports nearest-neighbor retrieval.
- App selects vector backend by config flag (`vector_db.type`).
- Ingestion writes to both FAISS and pgvector during transition.
- Query path switches to pgvector only after shadow-read parity checks pass.

---

## Phased Migration Plan (Execution Later)

### Phase 0 - Readiness and Acceptance Criteria

Tasks:

1. Freeze embedding model/dimension for migration window.
2. Define retrieval acceptance metrics (top-k overlap, latency p95, answer quality checks).
3. Create a benchmark query set from real usage.

Exit criteria:

- Acceptance metrics agreed and documented.
- Benchmark set versioned and reproducible.

Complexity: Low (0.5-1 day)

---

### Phase 1 - Schema and Adapter Implementation

Tasks:

1. Provision PostgreSQL and enable `pgvector` extension.
2. Create table (example fields):
   - `id`
   - `chunk_id` (deterministic id for idempotency)
   - `content`
   - `metadata` (jsonb and/or typed columns)
   - `embedding vector(384)`
   - `created_at`, `updated_at`
3. Add indexes:
   - vector index (HNSW/IVFFlat)
   - metadata filter indexes (btree/gin as needed)
4. Implement new vector store class with parity methods:
   - `create_vectorstore`
   - `load_vectorstore`
   - `add_documents`
   - `similarity_search`
   - `similarity_search_with_score`
   - metadata-based delete methods currently used by ingestion flows
5. Wire backend selection using config (`vector_db.type`).

Exit criteria:

- Backend is switchable without changing query/ingest call sites.
- Local tests pass for adapter CRUD/search behavior.

Complexity: Medium (2-4 days)

---

### Phase 2 - Backfill and Data Validation

Tasks:

1. Backfill pgvector from existing corpus (re-ingest or FAISS export path).
2. Validate record counts and metadata parity by source.
3. Sample retrieval parity checks on benchmark queries.

Exit criteria:

- Backfill completed with no unresolved mismatches.
- Parity report generated and accepted.

Complexity: Medium (1-3 days, depends on corpus size)

---

### Phase 3 - Dual-Write (Safety Window)

Tasks:

1. Enable dual-write during ingestion (FAISS + pgvector).
2. Ensure idempotent upserts using deterministic `chunk_id`.
3. Add operational alerts for write failures on either backend.

Exit criteria:

- Dual-write stable for a defined soak period.
- No data drift detected between stores.

Complexity: Medium (1-2 days)

---

### Phase 4 - Shadow Read and Threshold Calibration

Tasks:

1. Keep serving FAISS results to users.
2. Run pgvector retrieval in shadow mode for same queries.
3. Log and compare:
   - top-k overlap
   - score distribution drift
   - filter behavior
   - latency p50/p95
4. Re-tune similarity threshold mapping in `neet_rag` logic.

Exit criteria:

- Quality and latency within accepted bounds.
- Threshold and rank behavior signed off.

Complexity: Medium (2-3 days)

---

### Phase 5 - Controlled Cutover

Tasks:

1. Flip read path to pgvector via config flag.
2. Keep dual-write enabled during stabilization window.
3. Monitor errors, latency, and quality regression signals.

Exit criteria:

- Stabilization window completed without critical regressions.

Complexity: Low-Medium (0.5-2 days)

---

### Phase 6 - Decommission and Closure

Tasks:

1. Disable FAISS writes after sign-off.
2. Snapshot final FAISS state for archive/rollback evidence.
3. Remove unused FAISS operational paths (separate change set).

Exit criteria:

- Cleanup complete and documented.

Complexity: Low (0.5-1 day)

---

## Rollback Strategy

- Immediate rollback: set backend flag back to FAISS and restart services.
- Data safety: keep dual-write active until pgvector stability is proven.
- Recovery artifacts: retain DB snapshot + final FAISS snapshot.

Rollback trigger examples:

1. Sustained p95 latency regression above agreed threshold.
2. Retrieval quality degradation against benchmark set.
3. Elevated retrieval or ingestion error rate.

---

## Complexity and Effort Estimate

If PostgreSQL is already available and managed:

- Engineering effort: 5-10 eng-days
- Calendar duration: 1-2 weeks
- Risk: Medium

If PostgreSQL infrastructure is new:

- Engineering effort: 8-15 eng-days
- Calendar duration: 2-4 weeks
- Risk: Medium-High

Top risk areas:

1. Score semantics drift affecting thresholding and ranking.
2. Metadata parity for dedupe/filter behavior.
3. Database sizing/index tuning under concurrent load.

---

## Go / No-Go Gates

Proceed only if all conditions are met:

1. Shadow-read parity within agreed bounds.
2. Latency and error rates stable in soak window.
3. Rollback path tested in non-production.
4. Operational ownership for PostgreSQL is confirmed.

If any gate fails, pause cutover and continue with FAISS.

---

## Execution Checklist (For Future Use)

- [ ] Confirm business need still justifies migration.
- [ ] Revalidate embedding model and dimension.
- [ ] Re-run benchmark baseline on current FAISS.
- [ ] Apply schema/adapter changes.
- [ ] Complete backfill + validation.
- [ ] Enable dual-write.
- [ ] Run shadow-read and tune thresholds.
- [ ] Perform controlled cutover.
- [ ] Validate and close.

---

## Notes

- This document is a plan only.
- No migration actions should be executed from this document without explicit approval.
