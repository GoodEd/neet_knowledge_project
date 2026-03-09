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
        self._source_manager = None
        self._source_title_cache: Dict[str, str] = {}

    @staticmethod
    def _is_meaningful_title(title: str) -> bool:
        normalized = (title or "").strip()
        if not normalized:
            return False
        lowered = normalized.lower()
        if lowered in {"unknown video", "unknown"}:
            return False
        if lowered.startswith("http://") or lowered.startswith("https://"):
            return False
        if re.match(r"^youtube video \([0-9A-Za-z_-]{11}\)$", lowered):
            return False
        return True

    def _get_source_manager(self):
        if self._source_manager is not None:
            return self._source_manager
        try:
            from src.utils.content_manager import ContentSourceManager

            self._source_manager = ContentSourceManager()
        except Exception as e:
            self.logger.warning(
                "Could not initialize source manager for title lookup: %s", e
            )
            self._source_manager = None
        return self._source_manager

    def _resolve_youtube_title(
        self, doc: "Document", source: str, video_id: str
    ) -> str:
        metadata_title = str(doc.metadata.get("title") or "").strip()
        if self._is_meaningful_title(metadata_title):
            return metadata_title

        metadata_video_title = str(doc.metadata.get("video_title") or "").strip()
        if self._is_meaningful_title(metadata_video_title):
            return metadata_video_title

        source_id = str(doc.metadata.get("source_id") or "").strip()
        if source_id:
            cached_title = self._source_title_cache.get(source_id)
            if cached_title:
                return cached_title

            manager = self._get_source_manager()
            if manager:
                try:
                    source_record = manager.get_source(source_id)
                    db_title = (
                        str(source_record.title or "").strip() if source_record else ""
                    )
                    if self._is_meaningful_title(db_title):
                        self._source_title_cache[source_id] = db_title
                        return db_title
                except Exception as e:
                    self.logger.warning(
                        "Failed source title lookup for source_id=%s: %s", source_id, e
                    )

        if video_id:
            return f"YouTube Video ({video_id})"
        if source and not (
            source.startswith("http://") or source.startswith("https://")
        ):
            return source
        return "YouTube Video"

    @staticmethod
    def _knowledge_base_unavailable(question: str, error: str) -> Dict[str, Any]:
        return {
            "question": question,
            "answer": "Knowledge base is empty or unavailable. Please ingest content first.",
            "sources": [],
            "error": error,
        }

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

            if source_id:
                for doc in langchain_docs:
                    doc.metadata["source_id"] = source_id

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
        title = str(doc.metadata.get("title", "") or "").strip()
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
            title = self._resolve_youtube_title(
                doc=doc, source=source, video_id=video_id
            )
            source_info["title"] = title
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
            if not self._is_youtube_doc(doc):
                continue

            video_id = doc.metadata.get("video_id") or self._extract_video_id(
                doc.metadata.get("source", "")
            )
            key = ("youtube", video_id or doc.metadata.get("source", ""))

            if key in seen:
                continue

            seen.add(key)
            selected_docs.append(doc)

        return [self._build_source_info(doc) for doc in selected_docs]

    def query(
        self,
        question: str,
        top_k: int = 5,
        include_sources: bool = True,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
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
            answer = self.llm_manager.generate(
                prompt, session_id=session_id, user_id=user_id
            )
        except Exception as e:
            answer = f"Error generating answer: {str(e)}"

        sources = self._build_public_sources(relevant_docs)

        return {"answer": answer, "sources": sources, "question": question}

    def query_with_history(
        self,
        question: str,
        chat_history: Optional[List[tuple]] = None,
        top_k: int = 5,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._vectorstore_loaded:
            try:
                self.vector_manager.load_vectorstore()
            except:
                pass

        try:
            relevant_docs = self._retrieve_docs(question=question, top_k=top_k)
        except Exception as e:
            return self._knowledge_base_unavailable(question=question, error=str(e))

        if not relevant_docs:
            return {"answer": "No relevant information found.", "sources": []}

        prompt = self.prompt_builder.build_with_history(
            query=question,
            context_docs=relevant_docs,
            chat_history=chat_history or [],
        )
        self.logger.info("LLM prompt payload with history: %s", prompt)

        try:
            answer = self.llm_manager.generate(
                prompt, session_id=session_id, user_id=user_id
            )
        except Exception as e:
            answer = f"Error generating answer: {str(e)}"

        sources = self._build_public_sources(relevant_docs)

        return {"answer": answer, "sources": sources}

    def get_more_youtube_sources(
        self,
        question: str,
        exclude_video_ids: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        if not self._vectorstore_loaded:
            try:
                self.vector_manager.load_vectorstore()
            except Exception:
                return []

        exclude = set(exclude_video_ids or [])
        fetch_k = max(limit * 6, 30)

        try:
            scored = self.vector_manager.similarity_search_with_score(
                question, k=fetch_k
            )
        except Exception:
            return []

        # Filter to eligible YouTube docs (not already shown)
        eligible: List[tuple] = []
        seen_videos: set = set()
        for doc, score in scored:
            if not self._is_youtube_doc(doc):
                continue
            video_id = doc.metadata.get("video_id") or self._extract_video_id(
                doc.metadata.get("source", "")
            )
            if not video_id or video_id in exclude or video_id in seen_videos:
                continue
            seen_videos.add(video_id)
            eligible.append((doc, score, video_id))

        # Take videos above threshold first, then backfill from below-threshold
        # to reach the requested limit (same spirit as _retrieve_docs fallback)
        above = [
            (doc, vid)
            for doc, score, vid in eligible
            if self._score_to_similarity(score) >= self.similarity_threshold
        ]
        above_vids = {vid for _, vid in above}
        below = [(doc, vid) for doc, score, vid in eligible if vid not in above_vids]

        combined = above + below

        results: List[Dict[str, Any]] = []
        for doc, _ in combined[:limit]:
            results.append(self._build_source_info(doc))

        return results

    def get_stats(self) -> Dict[str, Any]:
        try:
            info = self.vector_manager.get_collection_info()
            return {"vectorstore": info, "llm": self.llm_manager.get_model_info()}
        except Exception as e:
            return {"error": str(e)}

    def reset_knowledge_base(self):
        self.vector_manager.delete_collection()
        self._vectorstore_loaded = False
