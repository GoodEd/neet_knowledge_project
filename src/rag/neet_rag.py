from typing import Dict, Any, List, Optional, Union
from pathlib import Path
import os

from langchain_core.documents import Document

from ..processors import ContentProcessor
from .vector_store import VectorStoreManager
from .llm_manager import LLMManager, RAGPromptBuilder


class NEETRAG:
    def __init__(
        self,
        persist_directory: str = "./data/chroma_db",
        embedding_provider: str = "huggingface",
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        embedding_dimension: int = 384,
        llm_provider: str = "ollama",
        llm_model: str = "llama3.2",
        llm_base_url: Optional[str] = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        self.content_processor = ContentProcessor(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )

        self.vector_manager = VectorStoreManager(
            persist_directory=persist_directory,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embedding_dimension=embedding_dimension,
        )

        self.llm_manager = LLMManager(
            provider=llm_provider, model=llm_model, base_url=llm_base_url
        )

        self.prompt_builder = RAGPromptBuilder()
        self._vectorstore_loaded = False

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
            metadata = {
                "source": chunk.get("source", ""),
                "content_type": chunk.get("content_type", "text"),
                "timestamp": chunk.get("timestamp", ""),
            }

            if chunk.get("page"):
                metadata["page"] = chunk.get("page")
            if chunk.get("chunk_id"):
                metadata["chunk_id"] = chunk.get("chunk_id")

            doc = Document(page_content=chunk.get("content", ""), metadata=metadata)
            docs.append(doc)

        return docs

    def query(
        self, question: str, top_k: int = 5, include_sources: bool = True
    ) -> Dict[str, Any]:
        if not self._vectorstore_loaded:
            try:
                self.vector_manager.load_vectorstore()
            except:
                pass

        try:
            relevant_docs = self.vector_manager.similarity_search(
                query=question, k=top_k
            )
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

        try:
            answer = self.llm_manager.generate(prompt)
        except Exception as e:
            answer = f"Error generating answer: {str(e)}"

        sources = []
        for doc in relevant_docs:
            source_info = {
                "content": doc.page_content[:200] + "..."
                if len(doc.page_content) > 200
                else doc.page_content,
                "source": doc.metadata.get("source", "Unknown"),
                "content_type": doc.metadata.get("content_type", "text"),
            }
            sources.append(source_info)

        return {"answer": answer, "sources": sources, "question": question}

    def query_with_history(
        self, question: str, chat_history: List[tuple] = None, top_k: int = 5
    ) -> Dict[str, Any]:
        if not self._vectorstore_loaded:
            try:
                self.vector_manager.load_vectorstore()
            except:
                pass

        relevant_docs = self.vector_manager.similarity_search(query=question, k=top_k)

        if not relevant_docs:
            return {"answer": "No relevant information found.", "sources": []}

        prompt = self.prompt_builder.build_with_history(
            query=question, context_docs=relevant_docs, chat_history=chat_history
        )

        try:
            answer = self.llm_manager.generate(prompt)
        except Exception as e:
            answer = f"Error generating answer: {str(e)}"

        sources = []
        for doc in relevant_docs:
            sources.append(
                {
                    "source": doc.metadata.get("source", "Unknown"),
                    "content_type": doc.metadata.get("content_type", "text"),
                }
            )

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
