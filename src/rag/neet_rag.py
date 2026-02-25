from typing import Dict, Any, List, Optional, Union
from pathlib import Path
import os
import re
import logging
from collections import defaultdict

from langchain_core.documents import Document

from ..processors import ContentProcessor
from .vector_store import VectorStoreManager
from .llm_manager import LLMManager, RAGPromptBuilder
from .index_registry import resolve_runtime_index


class NEETRAG:
    def __init__(
        self,
        persist_directory: Optional[str] = None,
        embedding_provider: Optional[str] = None,
        embedding_model: Optional[str] = None,
        embedding_dimension: int = 384,
        llm_provider: str = "ollama",
        llm_model: str = "llama3.2",
        llm_base_url: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        index_name: Optional[str] = None,
    ):
        from src.utils.config import Config

        config = Config()
        self.config = config
        self.similarity_threshold = config.similarity_threshold

        embedding_provider = embedding_provider or config.embedding_provider
        embedding_model = embedding_model or config.embedding_model
        embedding_provider, embedding_model, resolved_persist_dir = (
            resolve_runtime_index(
                embedding_provider=embedding_provider,
                embedding_model=embedding_model,
                persist_directory=persist_directory,
                index_name=index_name,
                data_dir=os.environ.get("DATA_DIR", "./data"),
            )
        )

        self.content_processor = ContentProcessor(
            chunk_size=chunk_size or config.chunk_size,
            chunk_overlap=chunk_overlap or config.chunk_overlap,
        )

        self.vector_manager = VectorStoreManager(
            persist_directory=resolved_persist_dir,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embedding_dimension=embedding_dimension,
        )

        self.llm_manager = LLMManager(
            provider=llm_provider, model=llm_model, base_url=llm_base_url
        )

        self.prompt_builder = RAGPromptBuilder()
        self._vectorstore_loaded = False
        self.logger = logging.getLogger(__name__)

    def ingest_processed_content(
        self, processed_result: Dict[str, Any], source_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Ingest content that has already been processed into chunks."""
        chunked_docs = processed_result.get("chunked_documents", [])
        source = processed_result.get("source", "Unknown")

        if chunked_docs and source_id:
            for chunk in chunked_docs:
                if isinstance(chunk, dict):
                    chunk["source_id"] = source_id

        if chunked_docs:
            langchain_docs = self._convert_to_langchain_docs(chunked_docs)

            try:
                self.vector_manager.load_vectorstore()
                self.vector_manager.add_documents(langchain_docs)
            except:
                self.vector_manager.create_vectorstore(langchain_docs)

            self._vectorstore_loaded = True

        return {
            "source": source,
            "status": "success",
            "documents_processed": len(chunked_docs),
            "processed_at": processed_result.get("processed_at"),
        }

    def ingest_content(
        self, source: Union[str, List[str]], source_type: str = "auto"
    ) -> Dict[str, Any]:
        results = []

        if isinstance(source, str):
            source = [source]

        for src in source:
            try:
                result = self._process_single_source(src, source_type)
                results.append(result)
            except Exception as e:
                results.append({"source": src, "status": "error", "error": str(e)})

        return {
            "results": results,
            "total_processed": len(
                [r for r in results if r.get("status") == "success"]
            ),
            "total_failed": len([r for r in results if r.get("status") == "error"]),
        }

    def _process_single_source(self, source: str, source_type: str) -> Dict[str, Any]:
        if source_type == "auto" or source_type == "youtube":
            if "youtube.com" in source or "youtu.be" in source:
                processed = self.content_processor.process_youtube(source)
            elif source.startswith("http"):
                processed = self.content_processor.process(source)
            else:
                processed = self.content_processor.process(source)
        elif source_type == "text":
            processed = self.content_processor.process_text(source)
        elif source_type == "html":
            processed = self.content_processor.process_html_content(source)
        else:
            processed = self.content_processor.process(source)

        chunked_docs = processed.get("chunked_documents", [])

        if chunked_docs:
            langchain_docs = self._convert_to_langchain_docs(chunked_docs)

            try:
                self.vector_manager.load_vectorstore()
                self.vector_manager.add_documents(langchain_docs)
            except:
                self.vector_manager.create_vectorstore(langchain_docs)

            self._vectorstore_loaded = True

        return {
            "source": source,
            "status": "success",
            "documents_processed": len(chunked_docs),
            "processed_at": processed.get("processed_at"),
        }

    def _convert_to_langchain_docs(self, chunked_docs: List[Dict]) -> List[Document]:
        docs = []

        for chunk in chunked_docs:
            metadata = chunk.copy()
            content = metadata.pop("content", "")

            # Ensure standard fields exist
            if "source" not in metadata:
                metadata["source"] = ""
            if "content_type" not in metadata:
                metadata["content_type"] = "text"

            doc = Document(page_content=content, metadata=metadata)
            docs.append(doc)

        return docs

    @staticmethod
    def _format_youtube_url(source: str, video_id: str, timestamp: float) -> str:
        """Build a timestamped YouTube URL from metadata."""
        seconds = int(timestamp)
        if video_id and seconds > 0:
            return f"https://www.youtube.com/watch?v={video_id}&t={seconds}s"
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
        return source

    @staticmethod
    def _format_timestamp_label(seconds: float) -> str:
        """Convert seconds to a human-readable mm:ss or hh:mm:ss label."""
        total = int(seconds)
        if total <= 0:
            return ""
        h, remainder = divmod(total, 3600)
        m, s = divmod(remainder, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    @staticmethod
    def _extract_video_id(url: str) -> str:
        """Extract YouTube video ID from a URL."""
        patterns = [
            r"[?&]v=([a-zA-Z0-9_-]{11})",
            r"youtu\.be/([a-zA-Z0-9_-]{11})",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return ""

    def _build_source_info(self, doc: "Document") -> Dict[str, Any]:
        """Extract source info from a retrieved document, including YouTube timestamps."""
        content = doc.page_content
        source = doc.metadata.get("source", "Unknown")
        # Check both content_type and source_type (batch-ingested docs use source_type)
        content_type = doc.metadata.get("content_type") or doc.metadata.get(
            "source_type", "text"
        )
        title = doc.metadata.get("title", "")
        video_id = doc.metadata.get("video_id", "")
        timestamp = doc.metadata.get("start_time", 0)
        track_id = doc.metadata.get("track_id", "")

        # Fallback: extract video_id from source URL if missing
        if content_type == "youtube" and not video_id and source:
            video_id = self._extract_video_id(source)

        source_info = {
            "content": content[:200] + "..." if len(content) > 200 else content,
            "source": source,
            "content_type": content_type,
            "title": title,
            "track_id": track_id,
        }

        # Add YouTube-specific fields
        if content_type == "youtube" and video_id:
            source_info["video_id"] = video_id
            source_info["timestamp"] = timestamp
            source_info["timestamp_url"] = self._format_youtube_url(
                source, video_id, timestamp
            )
            source_info["timestamp_label"] = self._format_timestamp_label(timestamp)

        return source_info

    @staticmethod
    def _score_to_similarity(score: float) -> float:
        try:
            return 1.0 / (1.0 + float(score))
        except Exception:
            return 0.0

    def _dedupe_docs(self, docs: List[Document]) -> List[Document]:
        deduped = []
        seen = set()
        for doc in docs:
            source_type = doc.metadata.get("source_type") or doc.metadata.get(
                "content_type", ""
            )
            if source_type == "youtube":
                video_id = doc.metadata.get("video_id", "")
                start_time = int(float(doc.metadata.get("start_time", 0) or 0))
                track_id = doc.metadata.get("track_id", "")
                key = ("youtube", video_id, start_time, track_id)
            else:
                key = (
                    source_type,
                    doc.metadata.get("source", ""),
                    doc.page_content[:120],
                )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(doc)
        return deduped

    @staticmethod
    def _doc_group_key(doc: Document) -> tuple:
        source_type = doc.metadata.get("source_type") or doc.metadata.get(
            "content_type", ""
        )
        if source_type == "youtube":
            video_id = doc.metadata.get("video_id", "")
            if not video_id:
                video_id = NEETRAG._extract_video_id(doc.metadata.get("source", ""))
            return ("youtube", video_id or doc.metadata.get("source", ""))
        return (source_type, doc.metadata.get("source", ""))

    def _merge_rerank_docs(self, scored: List[tuple], top_k: int) -> List[Document]:
        groups: Dict[tuple, List[tuple]] = defaultdict(list)
        for doc, score in scored:
            sim = self._score_to_similarity(score)
            groups[self._doc_group_key(doc)].append((doc, score, sim))

        for key in groups:
            groups[key].sort(key=lambda x: x[2], reverse=True)

        ranked_groups = sorted(
            groups.items(),
            key=lambda item: (
                item[1][0][2],
                sum(x[2] for x in item[1][:2]) / min(2, len(item[1])),
            ),
            reverse=True,
        )

        merged: List[Document] = []
        round_idx = 0
        while len(merged) < top_k:
            added_in_round = False
            for _, docs_in_group in ranked_groups:
                if round_idx < len(docs_in_group):
                    merged.append(docs_in_group[round_idx][0])
                    added_in_round = True
                    if len(merged) >= top_k:
                        break
            if not added_in_round:
                break
            round_idx += 1

        return merged

    def _retrieve_docs(self, question: str, top_k: int) -> List[Document]:
        fetch_k = max(top_k * 4, top_k)
        scored = self.vector_manager.similarity_search_with_score(question, k=fetch_k)
        filtered_scored = []
        for doc, score in scored:
            sim = self._score_to_similarity(score)
            if sim >= self.similarity_threshold:
                filtered_scored.append((doc, score))
        if not filtered_scored:
            filtered_scored = scored[:fetch_k]

        merged = self._merge_rerank_docs(filtered_scored, top_k=top_k)
        deduped = self._dedupe_docs(merged)
        return deduped[:top_k]

    @staticmethod
    def _is_youtube_doc(doc: Document) -> bool:
        source_type = doc.metadata.get("source_type") or doc.metadata.get(
            "content_type", ""
        )
        return source_type == "youtube"

    def _build_public_sources(self, docs: List[Document]) -> List[Dict[str, Any]]:
        selected_docs: List[Document] = []
        seen = set()

        for doc in docs:
            source_type = doc.metadata.get("source_type") or doc.metadata.get(
                "content_type", ""
            )

            if self._is_youtube_doc(doc):
                video_id = doc.metadata.get("video_id") or self._extract_video_id(
                    doc.metadata.get("source", "")
                )
                key = ("youtube", video_id or doc.metadata.get("source", ""))
            elif source_type == "csv":
                key = (
                    "csv",
                    doc.metadata.get("source_id", ""),
                    str(doc.metadata.get("question_id", "")),
                    doc.metadata.get("source", ""),
                )
            else:
                key = (source_type or "text", doc.metadata.get("source", ""))

            if key in seen:
                continue

            seen.add(key)
            selected_docs.append(doc)

        return [self._build_source_info(doc) for doc in selected_docs]

    def query(
        self, question: str, top_k: int = 5, include_sources: bool = True
    ) -> Dict[str, Any]:
        if not self._vectorstore_loaded:
            try:
                self.vector_manager.load_vectorstore()
            except:
                pass

        try:
            relevant_docs = self._retrieve_docs(question=question, top_k=top_k)
        except Exception as e:
            return {
                "question": question,
                "answer": "No knowledge base available. Please ingest content first.",
                "sources": [],
                "error": str(e),
            }

        if not relevant_docs:
            return {
                "question": question,
                "answer": "No relevant information found in the knowledge base.",
                "sources": [],
            }

        prompt = self.prompt_builder.build_prompt(
            query=question, context_docs=relevant_docs, include_sources=include_sources
        )
        self.logger.info("LLM prompt payload: %s", prompt)

        try:
            answer = self.llm_manager.generate(prompt)
        except Exception as e:
            answer = f"Error generating answer: {str(e)}"

        sources = self._build_public_sources(relevant_docs)

        return {"answer": answer, "sources": sources, "question": question}

    def query_with_history(
        self, question: str, chat_history: Optional[List[tuple]] = None, top_k: int = 5
    ) -> Dict[str, Any]:
        if not self._vectorstore_loaded:
            try:
                self.vector_manager.load_vectorstore()
            except:
                pass

        relevant_docs = self._retrieve_docs(question=question, top_k=top_k)

        if not relevant_docs:
            return {"answer": "No relevant information found.", "sources": []}

        prompt = self.prompt_builder.build_with_history(
            query=question,
            context_docs=relevant_docs,
            chat_history=chat_history or [],
        )
        self.logger.info("LLM prompt payload with history: %s", prompt)

        try:
            answer = self.llm_manager.generate(prompt)
        except Exception as e:
            answer = f"Error generating answer: {str(e)}"

        sources = self._build_public_sources(relevant_docs)

        return {"answer": answer, "sources": sources}

    def get_stats(self) -> Dict[str, Any]:
        try:
            info = self.vector_manager.get_collection_info()
            return {"vectorstore": info, "llm": self.llm_manager.get_model_info()}
        except Exception as e:
            return {"error": str(e)}

    def reset_knowledge_base(self):
        self.vector_manager.delete_collection()
        self._vectorstore_loaded = False
