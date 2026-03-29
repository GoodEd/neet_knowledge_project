from langchain_core.documents import Document
from sentence_transformers import CrossEncoder


class Reranker:
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model_name = model_name
        self._model: CrossEncoder | None = None

    def _ensure_loaded(self) -> None:
        if self._model is None:
            self._model = CrossEncoder(self.model_name)

    def rerank(
        self, query: str, candidates: list[Document], top_k: int
    ) -> list[Document]:
        if not candidates or top_k <= 0:
            return []

        self._ensure_loaded()
        assert self._model is not None

        pairs = [(query, doc.page_content) for doc in candidates]
        scores = self._model.predict(pairs)

        ranked = sorted(
            zip(candidates, scores),
            key=lambda item: float(item[1]),
            reverse=True,
        )
        return [doc for doc, _ in ranked[:top_k]]
