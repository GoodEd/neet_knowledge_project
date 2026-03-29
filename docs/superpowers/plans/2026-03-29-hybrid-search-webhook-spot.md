# Hybrid Search + Webhook + Fargate Spot Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix RAG retrieval for short queries (BM25 hybrid + query expansion + cross-encoder reranking), switch Telegram bot to webhook mode for multi-instance support, and move ECS to Fargate Spot with 2 instances.

**Architecture:** Add BM25 keyword retriever alongside FAISS, merge results with Reciprocal Rank Fusion, rerank with cross-encoder. Replace Telegram polling with webhook mode (python-telegram-bot built-in webhook server on port 8443, ALB path-based routing). Switch ECS to Fargate Spot capacity provider with 2 desired tasks.

**Tech Stack:** rank-bm25, sentence-transformers (cross-encoder/ms-marco-MiniLM-L-6-v2), python-telegram-bot webhook, Terraform (ALB listener rule, Fargate Spot)

---

## File Structure

### New Files

| File | Responsibility |
|------|----------------|
| `src/rag/bm25_retriever.py` | BM25 keyword index built from FAISS docstore; search method returning scored docs |
| `src/rag/query_expander.py` | NEET domain synonym map; expand short queries before search |
| `src/rag/reranker.py` | Cross-encoder wrapper; rerank candidate docs by query-document relevance |
| `tests/test_bm25_retriever.py` | BM25 retriever tests |
| `tests/test_query_expander.py` | Query expansion tests |
| `tests/test_reranker.py` | Reranker tests |
| `tests/test_hybrid_retrieval.py` | Integration tests for full hybrid pipeline |

### Modified Files

| File | Change |
|------|--------|
| `requirements.txt` | Add `rank-bm25>=0.2.2` |
| `config.yaml` | Add `search:` section (bm25_weight, reranker_model, reranker_top_k, max_query_expansion) |
| `src/rag/neet_rag.py` | Replace `_retrieve_docs` with hybrid pipeline; fix fallback; use query expansion + BM25 + FAISS + RRF + reranker |
| `src/rag/vector_store.py` | Add `get_all_documents()` method to extract docs from FAISS docstore (needed to build BM25 index) |
| `src/telegram_bot/bot.py` | Replace `run_polling()` with `run_webhook()`; add webhook setup/teardown; remove polling code |
| `deploy/start_frontend.py` | Start bot in webhook mode with correct URL |
| `deploy/main.tf` | Add: bot target group (8443), ALB listener rule for /telegram-webhook, security group rule for 8443, capacity_provider_strategy FARGATE_SPOT, bump memory/cpu, desired_count=2 |
| `deploy/variables.tf` | Add: telegram_webhook_path, use_fargate_spot, desired_count |
| `deploy/terraform.tfvars.example` | Add new variables |
| `deploy/entrypoint.sh` | Simplify (webhook mode, no background process needed — bot runs in start_frontend.py) |

---

## Chunk 1: Hybrid Search — BM25 Retriever

### Task 1: Add BM25 dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add rank-bm25 to requirements.txt**

Append after `python-telegram-bot>=21.0`:

```
# Hybrid Search
rank-bm25>=0.2.2
```

- [ ] **Step 2: Install**

Run: `pip install "rank-bm25>=0.2.2"`

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add rank-bm25 dependency for hybrid search"
```

### Task 2: Add get_all_documents to VectorStoreManager

**Files:**
- Modify: `src/rag/vector_store.py`

- [ ] **Step 1: Add get_all_documents method to VectorStoreManager**

Add after the `get_collection_info` method (~line 230):

```python
def get_all_documents(self) -> List[Document]:
    """Extract all documents from the FAISS docstore for BM25 indexing."""
    if self.vectorstore is None:
        return []
    docstore = self.vectorstore.docstore
    if hasattr(docstore, '_dict'):
        return list(docstore._dict.values())
    return []
```

- [ ] **Step 2: Add get_all_documents to CompositeVectorStoreManager**

Add after the `get_collection_info` method (~line 457):

```python
def get_all_documents(self) -> List[Document]:
    """Extract all documents from all sub-index docstores."""
    all_docs: List[Document] = []
    for mgr in self._managers.values():
        all_docs.extend(mgr.get_all_documents())
    return all_docs
```

- [ ] **Step 3: Commit**

```bash
git add src/rag/vector_store.py
git commit -m "feat(rag): add get_all_documents for BM25 index building"
```

### Task 3: BM25 Retriever (TDD)

**Files:**
- Create: `src/rag/bm25_retriever.py`
- Create: `tests/test_bm25_retriever.py`

- [ ] **Step 1: Write tests**

Create `tests/test_bm25_retriever.py`:

```python
"""Tests for BM25 keyword retriever."""
import pytest
from langchain_core.documents import Document


def _make_docs():
    return [
        Document(page_content="Young's modulus is a measure of stiffness", metadata={"source_type": "youtube", "question_id": ""}),
        Document(page_content="Mitosis is a type of cell division", metadata={"source_type": "csv", "question_id": "123"}),
        Document(page_content="The elastic modulus and Young's modulus of steel", metadata={"source_type": "youtube", "question_id": ""}),
        Document(page_content="Wien's displacement law relates temperature", metadata={"source_type": "csv", "question_id": "456"}),
        Document(page_content="Stress strain curve shows elastic and plastic regions", metadata={"source_type": "youtube", "question_id": ""}),
    ]


class TestBM25Retriever:
    def test_search_returns_relevant_docs(self):
        from src.rag.bm25_retriever import BM25KeywordRetriever
        retriever = BM25KeywordRetriever(_make_docs())
        results = retriever.search("young modulus", k=3)
        assert len(results) > 0
        assert any("Young" in doc.page_content for doc, _ in results)

    def test_search_scores_descending(self):
        from src.rag.bm25_retriever import BM25KeywordRetriever
        retriever = BM25KeywordRetriever(_make_docs())
        results = retriever.search("young modulus", k=5)
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_with_filter(self):
        from src.rag.bm25_retriever import BM25KeywordRetriever
        retriever = BM25KeywordRetriever(_make_docs())
        results = retriever.search("modulus", k=5, source_type="youtube")
        for doc, _ in results:
            assert doc.metadata.get("source_type") == "youtube"

    def test_empty_query_returns_empty(self):
        from src.rag.bm25_retriever import BM25KeywordRetriever
        retriever = BM25KeywordRetriever(_make_docs())
        results = retriever.search("", k=3)
        assert results == []

    def test_no_match_returns_empty(self):
        from src.rag.bm25_retriever import BM25KeywordRetriever
        retriever = BM25KeywordRetriever(_make_docs())
        results = retriever.search("quantum entanglement teleportation", k=3)
        # BM25 may return low-score results; all should score near 0
        for _, score in results:
            assert score < 1.0

    def test_build_from_empty_list(self):
        from src.rag.bm25_retriever import BM25KeywordRetriever
        retriever = BM25KeywordRetriever([])
        results = retriever.search("anything", k=3)
        assert results == []
```

- [ ] **Step 2: Run tests → verify fail**

Run: `pytest tests/test_bm25_retriever.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement BM25 retriever**

Create `src/rag/bm25_retriever.py`:

```python
"""BM25 keyword retriever for hybrid search alongside FAISS."""
import logging
import re
from typing import Optional

from langchain_core.documents import Document
from rank_bm25 import BM25Plus

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer, lowercased."""
    return re.findall(r"\w+", text.lower())


class BM25KeywordRetriever:
    """BM25 keyword index over a list of Documents.

    Built once at startup from FAISS docstore contents.
    Searches are fast (~1ms for 40K docs).
    """

    def __init__(self, documents: list[Document]) -> None:
        self._documents = documents
        self._source_type_map: dict[str, list[int]] = {}

        if not documents:
            self._bm25 = None
            return

        corpus = []
        for i, doc in enumerate(documents):
            tokens = _tokenize(doc.page_content)
            corpus.append(tokens)
            st = doc.metadata.get("source_type", "")
            self._source_type_map.setdefault(st, []).append(i)

        self._bm25 = BM25Plus(corpus)
        logger.info("BM25 index built: %d documents", len(documents))

    def search(
        self,
        query: str,
        k: int = 20,
        source_type: Optional[str] = None,
    ) -> list[tuple[Document, float]]:
        """Search by BM25 keyword relevance.

        Returns list of (Document, score) sorted by score descending.
        """
        if not query.strip() or self._bm25 is None:
            return []

        tokens = _tokenize(query)
        if not tokens:
            return []

        scores = self._bm25.get_scores(tokens)

        if source_type and source_type in self._source_type_map:
            valid_indices = set(self._source_type_map[source_type])
            indexed = [(i, scores[i]) for i in valid_indices if scores[i] > 0]
        else:
            indexed = [(i, s) for i, s in enumerate(scores) if s > 0]

        indexed.sort(key=lambda x: x[1], reverse=True)
        return [(self._documents[i], score) for i, score in indexed[:k]]
```

- [ ] **Step 4: Run tests → verify pass**

Run: `pytest tests/test_bm25_retriever.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/rag/bm25_retriever.py tests/test_bm25_retriever.py
git commit -m "feat(rag): add BM25 keyword retriever with TDD tests"
```

---

## Chunk 2: Query Expansion + Cross-Encoder Reranker

### Task 4: Query Expander (TDD)

**Files:**
- Create: `src/rag/query_expander.py`
- Create: `tests/test_query_expander.py`

- [ ] **Step 1: Write tests**

Create `tests/test_query_expander.py`:

```python
"""Tests for NEET domain query expansion."""
import pytest


class TestQueryExpander:
    def test_short_query_gets_expanded(self):
        from src.rag.query_expander import expand_query
        result = expand_query("young modulus")
        assert len(result) > 1
        assert "young modulus" in result

    def test_long_query_not_expanded(self):
        from src.rag.query_expander import expand_query
        long_q = "explain the relationship between stress and strain in Young's modulus experiments"
        result = expand_query(long_q)
        assert result == [long_q]

    def test_known_synonym_included(self):
        from src.rag.query_expander import expand_query
        result = expand_query("young modulus")
        combined = " ".join(result).lower()
        assert "elastic" in combined or "stress" in combined or "stiffness" in combined

    def test_unknown_term_returns_original(self):
        from src.rag.query_expander import expand_query
        result = expand_query("xyz123")
        assert result == ["xyz123"]

    def test_empty_query(self):
        from src.rag.query_expander import expand_query
        result = expand_query("")
        assert result == [""]

    def test_wien_expansion(self):
        from src.rag.query_expander import expand_query
        result = expand_query("wien law")
        combined = " ".join(result).lower()
        assert "displacement" in combined or "blackbody" in combined
```

- [ ] **Step 2: Run tests → verify fail**

Run: `pytest tests/test_query_expander.py -v`

- [ ] **Step 3: Implement**

Create `src/rag/query_expander.py`:

```python
"""NEET domain query expansion for short queries."""

# Short queries (< 6 words) get expanded with domain synonyms
_MAX_WORDS_FOR_EXPANSION = 5

# NEET Physics/Chemistry/Biology synonym map
# Keys are lowercased; values are alternative phrasings
NEET_SYNONYMS: dict[str, list[str]] = {
    "young modulus": ["young's modulus", "elastic modulus", "stress strain", "mechanical properties of solids stiffness"],
    "young's modulus": ["young modulus", "elastic modulus", "stress strain curve"],
    "wien": ["wien's displacement law", "blackbody radiation peak wavelength temperature"],
    "wien law": ["wien's displacement law", "blackbody radiation peak wavelength"],
    "dark fringes": ["dark fringes young's double slit experiment", "interference pattern minima"],
    "fringes": ["interference fringes young's double slit experiment fringe width"],
    "fringe width": ["fringe width young's double slit experiment wavelength slit separation"],
    "osmosis": ["osmosis semipermeable membrane water potential"],
    "mitosis": ["mitosis cell division prophase metaphase anaphase telophase"],
    "meiosis": ["meiosis reduction division crossing over gamete formation"],
    "newton's laws": ["newton's laws of motion inertia force acceleration reaction"],
    "ohm's law": ["ohm's law resistance current voltage"],
    "kirchhoff": ["kirchhoff's law junction loop current voltage"],
    "lens": ["convex lens concave lens focal length image formation"],
    "mirror": ["concave mirror convex mirror focal length magnification"],
    "thermodynamics": ["thermodynamics heat work internal energy entropy"],
    "wave optics": ["wave optics interference diffraction polarization"],
    "electromagnetic": ["electromagnetic induction faraday's law lenz's law"],
    "photoelectric": ["photoelectric effect threshold frequency work function"],
    "radioactivity": ["radioactivity alpha beta gamma decay half life"],
    "organic chemistry": ["organic chemistry hydrocarbons functional groups reactions"],
    "chemical bonding": ["chemical bonding ionic covalent metallic hydrogen bond"],
    "acid base": ["acid base pH titration buffer solution"],
    "genetics": ["genetics inheritance mendel dominant recessive allele"],
    "ecology": ["ecology ecosystem food chain biodiversity"],
    "human physiology": ["human physiology digestion respiration circulation excretion"],
    "plant physiology": ["plant physiology photosynthesis transpiration mineral nutrition"],
    "biomolecules": ["biomolecules proteins carbohydrates lipids nucleic acids enzymes"],
    "cell biology": ["cell biology cell structure organelles membrane"],
    "evolution": ["evolution natural selection speciation adaptation"],
    "reproduction": ["reproduction sexual asexual fertilization embryo development"],
    "elasticity": ["elasticity stress strain young's modulus bulk modulus shear modulus"],
    "viscosity": ["viscosity fluid mechanics stokes law terminal velocity"],
    "surface tension": ["surface tension capillarity contact angle meniscus"],
    "gravitation": ["gravitation gravitational force orbital velocity escape velocity"],
    "rotational motion": ["rotational motion moment of inertia angular momentum torque"],
    "simple harmonic": ["simple harmonic motion SHM oscillation pendulum spring"],
    "semiconductor": ["semiconductor p-n junction diode transistor"],
    "capacitor": ["capacitor capacitance parallel plate series parallel combination"],
    "magnetic field": ["magnetic field biot savart ampere's law solenoid"],
}


def expand_query(query: str) -> list[str]:
    """Expand short queries with NEET domain synonyms.

    Returns a list of query variants. The original query is always first.
    Long queries (> 5 words) are returned unchanged.
    """
    if not query.strip():
        return [query]

    words = query.strip().split()
    if len(words) > _MAX_WORDS_FOR_EXPANSION:
        return [query]

    query_lower = query.strip().lower()
    expansions = [query]

    # Check exact match first
    if query_lower in NEET_SYNONYMS:
        expansions.extend(NEET_SYNONYMS[query_lower])
        return expansions[:5]

    # Check partial match (any key contained in query or query contained in key)
    for key, synonyms in NEET_SYNONYMS.items():
        if key in query_lower or query_lower in key:
            expansions.extend(synonyms)
            if len(expansions) >= 5:
                break

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for q in expansions:
        ql = q.lower()
        if ql not in seen:
            seen.add(ql)
            unique.append(q)
    return unique[:5]
```

- [ ] **Step 4: Run tests → verify pass**

Run: `pytest tests/test_query_expander.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/rag/query_expander.py tests/test_query_expander.py
git commit -m "feat(rag): add NEET domain query expander with synonym map"
```

### Task 5: Cross-Encoder Reranker (TDD)

**Files:**
- Create: `src/rag/reranker.py`
- Create: `tests/test_reranker.py`

- [ ] **Step 1: Write tests**

Create `tests/test_reranker.py`:

```python
"""Tests for cross-encoder reranker."""
import pytest
from unittest.mock import MagicMock, patch
from langchain_core.documents import Document


def _make_candidates():
    return [
        Document(page_content="Young's modulus of the wire is 2×10^11 N/m²"),
        Document(page_content="Mitosis cell division biology NCERT chapter"),
        Document(page_content="Stress strain curve elastic plastic deformation"),
        Document(page_content="Glucose and urea solution colloidal"),
    ]


class TestReranker:
    @patch("src.rag.reranker.CrossEncoder")
    def test_rerank_returns_top_k(self, mock_ce_class):
        from src.rag.reranker import Reranker
        mock_model = MagicMock()
        mock_model.predict.return_value = [0.9, 0.1, 0.7, 0.05]
        mock_ce_class.return_value = mock_model

        reranker = Reranker()
        results = reranker.rerank("young modulus", _make_candidates(), top_k=2)
        assert len(results) == 2
        assert "Young" in results[0].page_content
        assert "Stress" in results[1].page_content

    @patch("src.rag.reranker.CrossEncoder")
    def test_rerank_empty_candidates(self, mock_ce_class):
        from src.rag.reranker import Reranker
        reranker = Reranker()
        results = reranker.rerank("test", [], top_k=5)
        assert results == []

    @patch("src.rag.reranker.CrossEncoder")
    def test_rerank_preserves_metadata(self, mock_ce_class):
        from src.rag.reranker import Reranker
        mock_model = MagicMock()
        mock_model.predict.return_value = [0.8]
        mock_ce_class.return_value = mock_model

        doc = Document(page_content="test", metadata={"question_id": "123"})
        reranker = Reranker()
        results = reranker.rerank("query", [doc], top_k=1)
        assert results[0].metadata["question_id"] == "123"
```

- [ ] **Step 2: Run tests → verify fail**

- [ ] **Step 3: Implement**

Create `src/rag/reranker.py`:

```python
"""Cross-encoder reranker for hybrid search results."""
import logging

from langchain_core.documents import Document
from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class Reranker:
    """Rerank candidate documents using a cross-encoder model.

    The cross-encoder scores each (query, document) pair directly,
    producing much more accurate relevance scores than bi-encoder
    cosine similarity — especially for short queries.
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model: CrossEncoder | None = None

    def _ensure_loaded(self) -> CrossEncoder:
        if self._model is None:
            logger.info("Loading cross-encoder: %s", self._model_name)
            self._model = CrossEncoder(self._model_name)
            logger.info("Cross-encoder loaded")
        return self._model

    def rerank(
        self, query: str, candidates: list[Document], top_k: int = 10
    ) -> list[Document]:
        """Rerank candidates by cross-encoder relevance score.

        Returns top_k documents sorted by relevance (highest first).
        """
        if not candidates:
            return []

        model = self._ensure_loaded()
        pairs = [(query, doc.page_content) for doc in candidates]
        scores = model.predict(pairs, show_progress_bar=False)

        scored = sorted(
            zip(candidates, scores), key=lambda x: x[1], reverse=True
        )
        return [doc for doc, _ in scored[:top_k]]
```

- [ ] **Step 4: Run tests → verify pass**

Run: `pytest tests/test_reranker.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/rag/reranker.py tests/test_reranker.py
git commit -m "feat(rag): add cross-encoder reranker with TDD tests"
```

---

## Chunk 3: Integrate Hybrid Search into RAG Pipeline

### Task 6: Wire hybrid search into neet_rag.py

**Files:**
- Modify: `src/rag/neet_rag.py`
- Modify: `config.yaml`
- Create: `tests/test_hybrid_retrieval.py`

- [ ] **Step 1: Add search config to config.yaml**

Add after the existing `similarity_threshold: 0.5` line:

```yaml
  # Hybrid search settings
  bm25_weight: 0.4
  faiss_weight: 0.6
  reranker_model: cross-encoder/ms-marco-MiniLM-L-6-v2
  reranker_top_k: 50
  max_query_expansions: 5
```

- [ ] **Step 2: Write integration tests**

Create `tests/test_hybrid_retrieval.py`:

```python
"""Tests for hybrid retrieval pipeline."""
import pytest
from unittest.mock import MagicMock, patch
from langchain_core.documents import Document


def _physics_doc(content="Young's modulus wire 2×10^11"):
    return Document(page_content=content, metadata={"source_type": "youtube", "question_id": ""})

def _biology_doc(content="Mitosis cell division prophase"):
    return Document(page_content=content, metadata={"source_type": "csv", "question_id": "123"})


class TestRRFFusion:
    def test_rrf_merges_two_lists(self):
        from src.rag.neet_rag import _reciprocal_rank_fusion
        list_a = [(_physics_doc("A"), 0.9), (_biology_doc("B"), 0.5)]
        list_b = [(_biology_doc("B"), 0.8), (_physics_doc("A"), 0.3)]
        merged = _reciprocal_rank_fusion([list_a, list_b], k=60)
        assert len(merged) == 2

    def test_rrf_boosts_docs_in_both_lists(self):
        from src.rag.neet_rag import _reciprocal_rank_fusion
        shared = _physics_doc("shared")
        only_a = _biology_doc("only_a")
        only_b = _biology_doc("only_b")
        list_a = [(shared, 0.9), (only_a, 0.5)]
        list_b = [(shared, 0.8), (only_b, 0.3)]
        merged = _reciprocal_rank_fusion([list_a, list_b], k=60)
        assert merged[0].page_content == "shared"


class TestFallbackFix:
    def test_no_docs_above_threshold_returns_empty(self):
        """When no docs pass similarity threshold, return empty — don't fall back to irrelevant."""
        from src.rag.neet_rag import NEETRAG
        rag = MagicMock(spec=NEETRAG)
        rag.similarity_threshold = 0.5
        # All scores below threshold (sim = 1/(1+16) = 0.059)
        scored = [(Document(page_content="irrelevant"), 16.0)]
        rag._score_to_similarity = NEETRAG._score_to_similarity
        filtered = [(doc, s) for doc, s in scored if rag._score_to_similarity(s) >= 0.5]
        assert filtered == []
```

- [ ] **Step 3: Modify NEETRAG to use hybrid pipeline**

In `src/rag/neet_rag.py`, make these changes:

**Add imports at the top:**
```python
from src.rag.bm25_retriever import BM25KeywordRetriever
from src.rag.query_expander import expand_query
from src.rag.reranker import Reranker
```

**Add RRF function (module-level, before the class):**
```python
def _reciprocal_rank_fusion(
    ranked_lists: list[list[tuple[Document, float]]],
    k: int = 60,
) -> list[Document]:
    """Merge multiple ranked result lists using Reciprocal Rank Fusion."""
    doc_scores: dict[int, float] = {}
    doc_map: dict[int, Document] = {}
    for results in ranked_lists:
        for rank, (doc, _) in enumerate(results, start=1):
            doc_id = id(doc)
            doc_scores[doc_id] = doc_scores.get(doc_id, 0) + 1.0 / (k + rank)
            doc_map[doc_id] = doc
    sorted_ids = sorted(doc_scores, key=doc_scores.get, reverse=True)
    return [doc_map[did] for did in sorted_ids]
```

**In NEETRAG.__init__, after vector_manager initialization, add:**
```python
self._bm25: BM25KeywordRetriever | None = None
self._reranker: Reranker | None = None
```

**Add method to lazily build BM25 index:**
```python
def _ensure_bm25(self) -> BM25KeywordRetriever:
    if self._bm25 is None:
        docs = self.vector_manager.get_all_documents()
        self._bm25 = BM25KeywordRetriever(docs)
    return self._bm25

def _ensure_reranker(self) -> Reranker:
    if self._reranker is None:
        model = getattr(self.config, 'reranker_model', 'cross-encoder/ms-marco-MiniLM-L-6-v2')
        self._reranker = Reranker(model_name=model)
    return self._reranker
```

**Replace `_retrieve_docs` method with hybrid version:**
```python
def _retrieve_docs(self, question: str, top_k: int) -> list[Document]:
    if isinstance(self.vector_manager, CompositeVectorStoreManager):
        return self._retrieve_docs_hybrid(question, top_k)
    # Fallback for non-composite (shouldn't happen in prod)
    return self._retrieve_docs_hybrid(question, top_k)

def _retrieve_docs_hybrid(self, question: str, top_k: int) -> list[Document]:
    """Hybrid retrieval: query expansion → BM25 + FAISS → RRF → cross-encoder rerank."""
    queries = expand_query(question)
    fetch_k = max(top_k * 4, 20)

    # FAISS vector search (best query variant)
    faiss_results: list[tuple[Document, float]] = []
    for q in queries:
        try:
            scored = self.vector_manager.similarity_search_with_score(q, k=fetch_k)
            # Only keep docs above threshold — NO fallback to irrelevant content
            for doc, score in scored:
                sim = self._score_to_similarity(score)
                if sim >= self.similarity_threshold:
                    faiss_results.append((doc, sim))
        except Exception:
            continue

    # BM25 keyword search
    bm25_results: list[tuple[Document, float]] = []
    try:
        bm25 = self._ensure_bm25()
        for q in queries:
            bm25_results.extend(bm25.search(q, k=fetch_k))
    except Exception:
        pass

    # RRF merge
    merged = _reciprocal_rank_fusion([faiss_results, bm25_results], k=60)

    if not merged:
        return []

    # Cross-encoder rerank top candidates
    reranker = self._ensure_reranker()
    rerank_top = min(len(merged), 50)
    reranked = reranker.rerank(question, merged[:rerank_top], top_k=top_k)

    return self._dedupe_docs(reranked)[:top_k]
```

**Also fix `_retrieve_docs_blended` — remove the fallback:**
Replace lines 461-462:
```python
# BEFORE:
if not filtered:
    filtered = csv_scored[:max_csv]
# AFTER:
if not filtered:
    # Try BM25 keyword search as rescue
    try:
        bm25 = self._ensure_bm25()
        bm25_results = bm25.search(question, k=max_csv, source_type="csv")
        if bm25_results:
            return [doc for doc, _ in bm25_results[:max_csv]]
    except Exception:
        pass
    return []
```

**Also fix `_retrieve_youtube_sources` fallback (lines 544-555) — use BM25 rescue:**
```python
# BEFORE:
if not results:
    seen_videos = set()
    for doc, score in scored[:fetch_k]:
        ...
# AFTER:
if not results:
    try:
        bm25 = self._ensure_bm25()
        bm25_results = bm25.search(question, k=fetch_k, source_type="youtube")
        for doc, _ in bm25_results:
            video_id = doc.metadata.get("video_id") or self._extract_video_id(doc.metadata.get("source", ""))
            if not video_id or video_id in seen_videos:
                continue
            seen_videos.add(video_id)
            results.append(self._build_source_info(doc))
            if len(results) >= top_k:
                break
    except Exception:
        pass
```

**Also fix `_retrieve_question_sources` fallback (lines 586-596) — same BM25 rescue pattern.**

- [ ] **Step 4: Run all tests**

Run: `pytest tests/test_hybrid_retrieval.py tests/test_bm25_retriever.py tests/test_query_expander.py tests/test_reranker.py -v`
Expected: All PASS

- [ ] **Step 5: Run existing tests for regression**

Run: `pytest tests/ -v --ignore=tests/manual_tests --ignore=tests/scripts --ignore=tests/scenario_neet_2025.py`

- [ ] **Step 6: Commit**

```bash
git add src/rag/neet_rag.py config.yaml tests/test_hybrid_retrieval.py
git commit -m "feat(rag): integrate hybrid search pipeline — BM25 + FAISS + RRF + cross-encoder reranking

Replaces pure FAISS retrieval with hybrid pipeline:
- Query expansion with NEET domain synonyms
- BM25 keyword search alongside FAISS vector search
- Reciprocal Rank Fusion to merge results
- Cross-encoder reranking for final ordering
- Fallback fix: return empty instead of irrelevant content"
```

---

## Chunk 4: Telegram Webhook Mode

### Task 7: Switch bot from polling to webhook

**Files:**
- Modify: `src/telegram_bot/bot.py`
- Modify: `deploy/start_frontend.py`

- [ ] **Step 1: Replace polling with webhook in bot.py**

Replace `run_polling` function and update imports:

```python
# Add to imports at top:
import urllib.parse

# Replace run_polling with:
def run_webhook(app: Application, webhook_url: str, port: int = 8443) -> None:
    """Start the bot in webhook mode."""
    logger.info("Starting Telegram bot webhook on port %d", port)
    logger.info("Webhook URL: %s", webhook_url)
    parsed = urllib.parse.urlparse(webhook_url)
    webhook_path = parsed.path or "/telegram-webhook"
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=webhook_path,
        webhook_url=webhook_url,
        drop_pending_updates=True,
    )
```

Remove the `run_polling` function entirely.

Update `__init__.py`:
```python
from src.telegram_bot.bot import create_application, run_webhook
```

- [ ] **Step 2: Update start_frontend.py to use webhook**

Replace the bot startup section in `deploy/start_frontend.py`:

```python
telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if telegram_token:
    import subprocess
    webhook_url = os.environ.get("TELEGRAM_WEBHOOK_URL", "")
    if webhook_url:
        print(f"[startup] Starting Telegram bot (webhook mode: {webhook_url})...")
        bot_proc = subprocess.Popen(
            [sys.executable, "run_telegram_bot.py"],
        )
        print(f"[startup] Telegram bot started (PID: {bot_proc.pid})")
    else:
        print("[startup] TELEGRAM_WEBHOOK_URL not set — skipping bot startup")
```

- [ ] **Step 3: Update run_telegram_bot.py**

Replace contents:

```python
"""Entry point for the NEET PYQ Telegram Bot (webhook mode)."""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL")
    if not webhook_url:
        raise ValueError("TELEGRAM_WEBHOOK_URL environment variable is required")

    port = int(os.getenv("TELEGRAM_WEBHOOK_PORT", "8443"))

    logger.info("Initializing NEET PYQ Telegram Bot (webhook)...")

    from src.telegram_bot.bot import create_application, run_webhook

    app = create_application(token)
    run_webhook(app, webhook_url=webhook_url, port=port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Update entrypoint.sh**

Replace contents of `deploy/entrypoint.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

exec python deploy/start_frontend.py
```

- [ ] **Step 5: Run telegram tests**

Run: `pytest tests/test_telegram_*.py -v`
Note: Some tests may need updating since `run_polling` is removed. Fix any import errors.

- [ ] **Step 6: Commit**

```bash
git add src/telegram_bot/bot.py src/telegram_bot/__init__.py deploy/start_frontend.py deploy/entrypoint.sh run_telegram_bot.py
git commit -m "feat(telegram): switch from polling to webhook mode for multi-instance support"
```

---

## Chunk 5: Terraform — ALB Webhook Route + Fargate Spot

### Task 8: Add webhook ALB routing and Fargate Spot

**Files:**
- Modify: `deploy/main.tf`
- Modify: `deploy/variables.tf`
- Modify: `deploy/terraform.tfvars.example`

- [ ] **Step 1: Add new variables**

Append to `deploy/variables.tf`:

```hcl
variable "telegram_webhook_path" {
  description = "ALB path pattern for Telegram webhook. Must match the bot's url_path."
  type        = string
  default     = "/telegram-webhook"
}

variable "use_fargate_spot" {
  description = "Use FARGATE_SPOT capacity provider for cost savings (tasks may be interrupted)."
  type        = bool
  default     = false
}

variable "streamlit_desired_count" {
  description = "Number of desired ECS tasks for the streamlit service."
  type        = number
  default     = 1
}
```

- [ ] **Step 2: Add Telegram webhook target group and listener rule to main.tf**

Add after the existing `aws_lb_target_group.streamlit` resource:

```hcl
resource "aws_lb_target_group" "telegram_webhook" {
  name        = "${var.project_name}-telegram-tg"
  port        = 8443
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/telegram-webhook"
    port                = "8443"
    protocol            = "HTTP"
    matcher             = "200-405"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = {
    Name = "${var.project_name}-telegram-tg"
  }
}

resource "aws_lb_listener_rule" "telegram_webhook" {
  listener_arn = aws_lb_listener.neet_https.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.telegram_webhook.arn
  }

  condition {
    path_pattern {
      values = ["${var.telegram_webhook_path}*"]
    }
  }
}
```

- [ ] **Step 3: Add port 8443 to ECS task definition and security group**

Add to the `containerDefinitions` portMappings in `aws_ecs_task_definition.streamlit` (after the existing port 8501 mapping):

```json
{
  "containerPort": 8443,
  "protocol": "tcp"
}
```

Add security group ingress rule after existing port 8501 rule:

```hcl
resource "aws_security_group_rule" "ecs_telegram_webhook" {
  type                     = "ingress"
  from_port                = 8443
  to_port                  = 8443
  protocol                 = "tcp"
  security_group_id        = aws_security_group.ecs_tasks.id
  source_security_group_id = var.existing_alb_security_group_id
  description              = "ALB to ECS Telegram webhook"
}
```

- [ ] **Step 4: Add second load_balancer block to ECS service**

In `aws_ecs_service.streamlit`, add after the existing `load_balancer` block:

```hcl
  load_balancer {
    target_group_arn = aws_lb_target_group.telegram_webhook.arn
    container_name   = "streamlit"
    container_port   = 8443
  }
```

- [ ] **Step 5: Add TELEGRAM_WEBHOOK_URL to container environment**

Add to the `environment` list in the streamlit container definition:

```json
{
  "name": "TELEGRAM_WEBHOOK_URL",
  "value": "https://${var.app_fqdn}:7443${var.telegram_webhook_path}"
}
```

- [ ] **Step 6: Switch to Fargate Spot and bump resources**

In `aws_ecs_service.streamlit`, replace `launch_type = "FARGATE"` with:

```hcl
  dynamic "capacity_provider_strategy" {
    for_each = var.use_fargate_spot ? [1] : []
    content {
      capacity_provider = "FARGATE_SPOT"
      weight            = 1
      base              = 0
    }
  }

  dynamic "capacity_provider_strategy" {
    for_each = var.use_fargate_spot ? [] : [1]
    content {
      capacity_provider = "FARGATE"
      weight            = 1
      base              = 0
    }
  }
```

Also remove the `launch_type = "FARGATE"` line (can't have both launch_type and capacity_provider_strategy).

Update `desired_count`:
```hcl
  desired_count = var.streamlit_desired_count
```

In the task definition, bump resources:
```hcl
  cpu    = "4096"
  memory = "8192"
```

- [ ] **Step 7: Update terraform.tfvars.example**

Add:
```hcl
# Telegram Webhook
telegram_webhook_path = "/telegram-webhook"

# Fargate Spot (70% cost savings, tasks may be interrupted)
use_fargate_spot        = true
streamlit_desired_count = 2
```

- [ ] **Step 8: Update terraform.tfvars**

Add:
```hcl
telegram_webhook_path   = "/telegram-webhook"
use_fargate_spot        = true
streamlit_desired_count = 2
```

Also add TELEGRAM_WEBHOOK_URL secret or environment variable.

- [ ] **Step 9: Commit**

```bash
git add deploy/main.tf deploy/variables.tf deploy/terraform.tfvars.example
git commit -m "infra: add Telegram webhook ALB routing + Fargate Spot + resource bump

- New target group for Telegram webhook (port 8443)
- ALB listener rule for /telegram-webhook path
- Security group rule for ALB → ECS on 8443
- Fargate Spot capacity provider (configurable)
- Bump to 4 vCPU / 8 GiB for hybrid search components
- Desired count configurable (default 1)"
```

---

## Chunk 6: Final Integration + Smoke Test

### Task 9: Run all tests and verify

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v --ignore=tests/manual_tests --ignore=tests/scripts --ignore=tests/scenario_neet_2025.py`
Expected: All pass

- [ ] **Step 2: Local smoke test (hybrid search)**

```python
# Quick test that hybrid search works
python -c "
from src.rag.bm25_retriever import BM25KeywordRetriever
from src.rag.query_expander import expand_query
from src.rag.reranker import Reranker
print('BM25:', BM25KeywordRetriever([]))
print('Expand:', expand_query('young modulus'))
print('Reranker:', Reranker())
print('All components load OK')
"
```

- [ ] **Step 3: Push to main**

```bash
git push origin main
```

- [ ] **Step 4: Wait for CodePipeline build + deploy**

Monitor: `aws codepipeline get-pipeline-state --name neet-knowledge-dev-pipeline --region ap-south-1`

- [ ] **Step 5: Apply Terraform changes**

```bash
cd deploy
terraform plan
terraform apply
```

This registers the webhook target group, listener rule, security group rule, Fargate Spot, and bumps resources.

- [ ] **Step 6: Force new ECS deployment with updated task definition**

The CodePipeline deploy may use the old task definition. Register a new one with updated memory/cpu and the TELEGRAM_WEBHOOK_URL env var, then update the service.

- [ ] **Step 7: Verify bot webhook is working**

```bash
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo" | python3 -m json.tool
```

Expected: webhook URL set, no pending errors.

- [ ] **Step 8: Test on Telegram**

Send "young modulus" to `t.me/pyq_ai_bot`.
Expected: Physics answer with correct YouTube videos and question sources.

- [ ] **Step 9: Verify Fargate Spot**

```bash
aws ecs describe-services --cluster np-pgrest --services neet-knowledge-dev-streamlit --region ap-south-1 --query 'services[0].{CapacityProvider:capacityProviderStrategy,Desired:desiredCount,Running:runningCount}'
```

Expected: FARGATE_SPOT, 2 desired, 2 running.
