import re
from typing import Dict, List, Optional, Tuple

from langchain_core.documents import Document
from rank_bm25 import BM25Plus


def _tokenize(text: str) -> List[str]:
    return re.findall(r"\w+", text.lower())


class BM25KeywordRetriever:
    def __init__(self, documents: List[Document]):
        self.documents = documents
        self.source_type_map: Dict[str, List[int]] = {}

        tokenized_corpus = [_tokenize(doc.page_content) for doc in documents]
        self._bm25 = BM25Plus(tokenized_corpus) if tokenized_corpus else None

        for idx, doc in enumerate(documents):
            source_type = doc.metadata.get("source_type")
            if source_type is None:
                continue
            if source_type not in self.source_type_map:
                self.source_type_map[source_type] = []
            self.source_type_map[source_type].append(idx)

    def search(
        self, query: str, k: int = 5, source_type: Optional[str] = None
    ) -> List[Tuple[Document, float]]:
        if self._bm25 is None or k <= 0 or not query or not query.strip():
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scores = self._bm25.get_scores(query_tokens)

        if source_type is not None:
            candidate_indices = self.source_type_map.get(source_type, [])
        else:
            candidate_indices = range(len(self.documents))

        results: List[Tuple[Document, float]] = []
        for idx in candidate_indices:
            score = float(scores[idx])
            if score > 0:
                results.append((self.documents[idx], score))

        results.sort(key=lambda pair: pair[1], reverse=True)
        return results[:k]
