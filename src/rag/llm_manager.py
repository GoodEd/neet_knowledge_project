from typing import Optional, Dict, Any, List
import os
import base64


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

    def _openrouter_tracking_kwargs(
        self, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {}
        headers: Dict[str, str] = {}
        extra_body: Dict[str, Any] = {}

        if session_id:
            sid = str(session_id)[:128]
            headers["x-session-id"] = sid
            if self.provider == "openrouter":
                extra_body["session_id"] = sid

        if user_id:
            uid = str(user_id)[:128]
            kwargs["user"] = uid
            headers["x-user-id"] = uid

        if headers:
            kwargs["extra_headers"] = headers

        if extra_body:
            kwargs["extra_body"] = extra_body

        return kwargs

    def generate(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        if self.llm is None:
            raise ValueError("LLM not initialized")

        if self.provider in {"openai", "openrouter"}:
            from openai import OpenAI

            api_key = os.getenv("OPENAI_API_KEY")
            base_url = os.getenv("OPENAI_BASE_URL")
            if not api_key:
                raise ValueError("OPENAI_API_KEY is required")

            client = OpenAI(api_key=api_key, base_url=base_url)
            kwargs = self._openrouter_tracking_kwargs(
                session_id=session_id, user_id=user_id
            )
            response = client.chat.completions.create(
                model=self.model,
                temperature=0.7,
                messages=[{"role": "user", "content": prompt}],
                **kwargs,
            )
            content = response.choices[0].message.content
            if isinstance(content, str):
                return content
            return str(content)

        response = self.llm.invoke(prompt)
        if hasattr(response, "content"):
            return response.content
        return str(response)

    def extract_image_context(
        self,
        image_bytes: bytes,
        filename: str = "image.png",
        user_hint: str = "",
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        if self.provider not in {"openai", "openrouter"}:
            raise ValueError(
                "Image extraction requires openai/openrouter provider in current setup"
            )

        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        vision_model = os.getenv("VISION_MODEL_NAME", self.model)

        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for image context extraction")

        mime = "image/png"
        lower_name = (filename or "").lower()
        if lower_name.endswith(".jpg") or lower_name.endswith(".jpeg"):
            mime = "image/jpeg"
        elif lower_name.endswith(".webp"):
            mime = "image/webp"

        image_data = base64.b64encode(image_bytes).decode("utf-8")
        image_url = f"data:{mime};base64,{image_data}"

        system_prompt = (
            "You are a NEET exam assistant. Extract the problem statement from the image with high fidelity. "
            "Preserve key formulas, options, units, and diagram cues in plain text. "
            "Return concise structured text with sections: QUESTION, OPTIONS (if any), KNOWN VALUES, "
            "WHAT IS ASKED, and TOPIC GUESS."
        )
        hint_suffix = f"User hint: {user_hint}" if user_hint else ""
        user_prompt = (
            "Read this uploaded question image and produce retrieval-friendly context text. "
            "Do not solve it. Only extract and normalize the question information. "
            f"{hint_suffix}"
        )

        client = OpenAI(api_key=api_key, base_url=base_url)
        kwargs = self._openrouter_tracking_kwargs(
            session_id=session_id, user_id=user_id
        )
        response = client.chat.completions.create(
            model=vision_model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            **kwargs,
        )

        content = response.choices[0].message.content
        if isinstance(content, str):
            return content.strip()
        return str(content).strip()

    def get_model_info(self) -> Dict[str, Any]:
        return {"provider": self.provider, "model": self.model}


class RAGPromptBuilder:
    def __init__(self, system_prompt: Optional[str] = None):
        self.default_system_prompt = system_prompt or self._get_default_system_prompt()

    def _get_default_system_prompt(self) -> str:
        return """You are a NEET Previous Year Questions (PYQ) Assistant. Your role is to help NEET aspirants by analyzing matching PYQs from the knowledge base.

When questions are found in context, provide:
1. Types of questions asked on this topic (MCQ patterns, common question formats)
2. Important concepts being tested
3. Common mistakes to avoid
4. Specific guidance for the chapter or topic

Guidelines:
- Be as concise as possible — keep answers to 3-5 sentences max
- If no relevant questions are found, say so briefly
- Use LaTeX with $...$ for inline math and $$...$$ for display math
- Do NOT say "Document 1", "Document 2", etc.
- Do NOT repeat the full question text back to the student"""

    def build_prompt(
        self, query: str, context_docs: List[Any], include_sources: bool = True
    ) -> str:
        context_parts = []

        for i, doc in enumerate(context_docs):
            meta = getattr(doc, "metadata", {})
            content = getattr(doc, "page_content", str(doc))
            source_type = meta.get("source_type") or meta.get("content_type", "")

            if source_type == "youtube":
                continue

            chapter = meta.get("chapter_name", "")
            topic = meta.get("topic_names", "")
            label = "Previous Year Question"
            if chapter:
                label += f" ({chapter})"

            context_part = f"--- {label} ---\n"
            context_part += f"Content: {content}\n"

            context_parts.append(context_part)

        context = "\n".join(context_parts)

        if not context_parts:
            return f"Question: {query}\n\nNo matching previous year questions found."

        context = "\n".join(context_parts)

        prompt = f"""Context:
{context}

Question: {query}

Analyze the PYQs above and provide concise guidance."""

        return prompt

    def build_with_history(
        self,
        query: str,
        context_docs: List[Any],
        chat_history: Optional[List[tuple]] = None,
    ) -> str:
        prompt = self.build_prompt(query, context_docs)

        if chat_history:
            history_parts = []
            for human, ai in chat_history:
                history_parts.append(f"User: {human}\nAssistant: {ai}")

            prompt = (
                "Previous conversation:\n"
                + "\n\n".join(history_parts)
                + "\n\n"
                + prompt
            )

        return prompt
