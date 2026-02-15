from typing import Optional, Dict, Any, List
import os


class LLMManager:
    def __init__(
        self,
        provider: str = "ollama",
        model: str = "llama3.2",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.provider = provider
        self.model = model
        self.llm = None
        self._initialize_llm(api_key, base_url)

    def _initialize_llm(self, api_key: Optional[str], base_url: Optional[str]):
        if self.provider == "ollama":
            try:
                from langchain_community.llms import Ollama

                self.llm = Ollama(
                    model=self.model, base_url=base_url or "http://localhost:11434"
                )
            except ImportError:
                raise ImportError("ollama not installed. Run: pip install ollama")

        elif self.provider == "openai" or self.provider == "openrouter":
            try:
                from langchain_openai import ChatOpenAI

                self.llm = ChatOpenAI(
                    model=self.model,
                    api_key=api_key or os.getenv("OPENAI_API_KEY"),
                    base_url=base_url or os.getenv("OPENAI_BASE_URL"),
                    temperature=0.7,
                )
            except ImportError:
                raise ImportError("openai not installed. Run: pip install openai")

        elif self.provider == "anthropic":
            try:
                from langchain_anthropic import ChatAnthropic

                self.llm = ChatAnthropic(
                    model=self.model,
                    api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
                    temperature=0.7,
                )
            except ImportError:
                raise ImportError("anthropic not installed. Run: pip install anthropic")

        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def generate(self, prompt: str) -> str:
        if self.llm is None:
            raise ValueError("LLM not initialized")

        response = self.llm.invoke(prompt)
        if hasattr(response, "content"):
            return response.content
        return str(response)

    def get_model_info(self) -> Dict[str, Any]:
        return {"provider": self.provider, "model": self.model}


class RAGPromptBuilder:
    def __init__(self, system_prompt: str = None):
        self.default_system_prompt = system_prompt or self._get_default_system_prompt()

    def _get_default_system_prompt(self) -> str:
        return """You are a helpful AI assistant specialized in helping NEET aspirants in India. 
You have access to a knowledge base containing study materials, video transcripts, and notes.
Use the provided context to answer questions accurately and helpfuly.

Guidelines:
- Be clear and concise in your answers
- If the context doesn't contain enough information to answer, say so
- Use bullet points when listing multiple items
- For NEET-specific topics, provide accurate scientific information"""

    def build_prompt(
        self, query: str, context_docs: List[Any], include_sources: bool = True
    ) -> str:
        context_parts = []

        for i, doc in enumerate(context_docs):
            source = getattr(doc, "metadata", {}).get("source", f"Document {i + 1}")
            page = getattr(doc, "metadata", {}).get("page", "")
            content = getattr(doc, "page_content", str(doc))

            context_part = f"--- Document {i + 1} ---\n"
            if page:
                context_part += f"Source: {source} (Page {page})\n"
            else:
                context_part += f"Source: {source}\n"
            context_part += f"Content: {content}\n"

            context_parts.append(context_part)

        context = "\n".join(context_parts)

        prompt = f"""Context:
{context}

Question: {query}

Please provide a helpful answer based on the context above."""

        if include_sources:
            sources = []
            for doc in context_docs:
                source = getattr(doc, "metadata", {}).get("source", "Unknown")
                if source not in sources:
                    sources.append(source)
            prompt += f"\n\nSources: {', '.join(sources)}"

        return prompt

    def build_with_history(
        self, query: str, context_docs: List[Any], chat_history: List[tuple] = None
    ) -> str:
        prompt = self.build_prompt(query, context_docs)

        if chat_history:
            history_parts = []
            for human, ai in chat_history[-3:]:
                history_parts.append(f"User: {human}\nAssistant: {ai}")

            prompt = (
                "Previous conversation:\n"
                + "\n\n".join(history_parts)
                + "\n\n"
                + prompt
            )

        return prompt
