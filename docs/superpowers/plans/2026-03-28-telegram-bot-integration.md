# Telegram Bot Integration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Telegram bot (`t.me/pyq_ai_bot`) as the primary chat interface for the NEET PYQ Assistant, reusing the existing RAG pipeline, image extraction, and Redis infrastructure.

**Architecture:** python-telegram-bot v21+ in polling mode. Four new modules: `formatting.py` (RAG→Telegram HTML), `history.py` (Redis per-user turns), `bot.py` (handlers + app factory), and `run_telegram_bot.py` (entry point). All modules are TDD — tests first.

**Tech Stack:** python-telegram-bot v21+, existing FAISS/LangChain/OpenRouter stack, Redis, pytest

**Spec:** `docs/superpowers/specs/2026-03-28-telegram-bot-integration-design.md`

---

## Chunk 1: Project Setup & Configuration

### Task 1: Add dependency and configure environment

**Files:**
- Modify: `requirements.txt`
- Modify: `.env`
- Modify: `.env.example`
- Create: `src/telegram_bot/__init__.py`

- [ ] **Step 1: Add python-telegram-bot to requirements.txt**

Append to `requirements.txt` after the existing `# Utilities` block:

```
# Telegram Bot
python-telegram-bot>=21.0
```

- [ ] **Step 2: Add TELEGRAM_BOT_TOKEN to .env**

Append to `.env`:

```bash
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=8633678117:AAEGrPEwSpzSL2YRylX9h-yHpK2QWL5gAHM
```

- [ ] **Step 3: Add placeholder to .env.example**

Append to `.env.example`:

```bash
# Telegram Bot Configuration
# Get your token from @BotFather on Telegram
TELEGRAM_BOT_TOKEN=
```

- [ ] **Step 4: Create telegram_bot package**

Create `src/telegram_bot/__init__.py`:

```python
"""Telegram bot interface for the NEET PYQ Assistant."""
```

- [ ] **Step 5: Install the dependency**

Run: `pip install "python-telegram-bot>=21.0"`
Expected: Successfully installed python-telegram-bot-21.x

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .env.example src/telegram_bot/__init__.py
git commit -m "chore: add python-telegram-bot dependency and telegram_bot package"
```

Note: `.env` is gitignored — do NOT add it.

---

## Chunk 2: Formatting Module (TDD)

### Task 2: Write formatting tests

**Files:**
- Create: `tests/test_telegram_formatting.py`

- [ ] **Step 1: Write all formatting tests**

Create `tests/test_telegram_formatting.py`:

```python
"""Tests for Telegram response formatting."""
import pytest


class TestFormatAnswerText:
    """Tests for format_answer_text — RAG answer to Telegram-safe HTML."""

    def test_plain_text_passes_through(self):
        from src.telegram_bot.formatting import format_answer_text

        assert format_answer_text("Simple answer") == "Simple answer"

    def test_html_special_chars_escaped(self):
        from src.telegram_bot.formatting import format_answer_text

        result = format_answer_text("a < b & c > d")
        assert "&lt;" in result
        assert "&amp;" in result
        assert "&gt;" in result

    def test_latex_inline_delimiters_stripped(self):
        from src.telegram_bot.formatting import format_answer_text

        result = format_answer_text("The value is $x^2$ here")
        assert "$" not in result
        assert "x^2" in result

    def test_latex_block_delimiters_stripped(self):
        from src.telegram_bot.formatting import format_answer_text

        result = format_answer_text("Formula: $$\\frac{a}{b}$$")
        assert "$$" not in result
        assert "\\frac{a}{b}" in result

    def test_latex_paren_delimiters_stripped(self):
        from src.telegram_bot.formatting import format_answer_text

        result = format_answer_text("Inline \\(x+1\\) here")
        assert "\\(" not in result
        assert "\\)" not in result
        assert "x+1" in result

    def test_latex_bracket_delimiters_stripped(self):
        from src.telegram_bot.formatting import format_answer_text

        result = format_answer_text("Block \\[E=mc^2\\] here")
        assert "\\[" not in result
        assert "\\]" not in result
        assert "E=mc^2" in result

    def test_sup_tag_converts_to_unicode(self):
        from src.telegram_bot.formatting import format_answer_text

        result = format_answer_text("10<sup>2</sup>")
        assert "²" in result
        assert "<sup>" not in result

    def test_sub_tag_converts_to_unicode(self):
        from src.telegram_bot.formatting import format_answer_text

        result = format_answer_text("H<sub>2</sub>O")
        assert "₂" in result
        assert "<sub>" not in result

    def test_newlines_preserved(self):
        from src.telegram_bot.formatting import format_answer_text

        result = format_answer_text("Line 1\nLine 2")
        assert "\n" in result

    def test_unicode_math_symbols_preserved(self):
        from src.telegram_bot.formatting import format_answer_text

        text = "Area = πr² and √2 ≈ 1.414"
        result = format_answer_text(text)
        assert "π" in result
        assert "√" in result


class TestFormatYoutubeSources:
    """Tests for format_youtube_sources — YouTube video links."""

    def test_single_source_with_timestamp(self):
        from src.telegram_bot.formatting import format_youtube_sources

        sources = [{
            "content_type": "youtube",
            "title": "Physics Wallah",
            "timestamp_url": "https://youtube.com/watch?v=abc&t=60s",
            "timestamp_label": "1:00",
        }]
        result = format_youtube_sources(sources)
        assert '<a href="https://youtube.com/watch?v=abc&amp;t=60s">' in result
        assert "Physics Wallah" in result
        assert "1:00" in result

    def test_empty_sources_returns_empty_string(self):
        from src.telegram_bot.formatting import format_youtube_sources

        assert format_youtube_sources([]) == ""

    def test_multiple_sources_numbered(self):
        from src.telegram_bot.formatting import format_youtube_sources

        sources = [
            {"content_type": "youtube", "title": "Video A",
             "timestamp_url": "https://youtube.com/watch?v=a", "timestamp_label": ""},
            {"content_type": "youtube", "title": "Video B",
             "timestamp_url": "https://youtube.com/watch?v=b", "timestamp_label": ""},
        ]
        result = format_youtube_sources(sources)
        assert "1." in result
        assert "2." in result


class TestFormatQuestionSources:
    """Tests for format_question_sources — NeetPrep question links."""

    def test_single_question(self):
        from src.telegram_bot.formatting import format_question_sources

        sources = [{"question_id": "12345", "content": "NEET 2023 Q.45"}]
        result = format_question_sources(sources)
        assert "neetprep.com/epubQuestion/12345" in result

    def test_empty_sources_returns_empty_string(self):
        from src.telegram_bot.formatting import format_question_sources

        assert format_question_sources([]) == ""


class TestFormatResponse:
    """Tests for format_response — full RAG result to message parts."""

    def test_response_with_sources(self):
        from src.telegram_bot.formatting import format_response

        result = format_response({
            "answer": "The answer is 42",
            "sources": [{"content_type": "youtube", "title": "Physics",
                         "timestamp_url": "https://youtube.com/watch?v=x",
                         "timestamp_label": "0:30"}],
            "question_sources": [{"question_id": "99", "content": "Q99"}],
        })
        assert isinstance(result, list)
        assert len(result) >= 1
        combined = "".join(result)
        assert "The answer is 42" in combined
        assert "youtube.com" in combined
        assert "neetprep.com" in combined

    def test_response_without_sources(self):
        from src.telegram_bot.formatting import format_response

        result = format_response({
            "answer": "No relevant information found.",
            "sources": [],
            "question_sources": [],
        })
        combined = "".join(result)
        assert "No relevant information found." in combined
        assert "Related Videos" not in combined


class TestSplitMessage:
    """Tests for split_message — splitting long text at safe boundaries."""

    def test_short_message_not_split(self):
        from src.telegram_bot.formatting import split_message

        result = split_message("short text")
        assert result == ["short text"]

    def test_long_message_split_at_boundary(self):
        from src.telegram_bot.formatting import split_message

        long_text = "A" * 5000
        result = split_message(long_text, max_length=4096)
        assert len(result) == 2
        assert len(result[0]) <= 4096
        assert "".join(result) == long_text

    def test_split_prefers_newline_boundary(self):
        from src.telegram_bot.formatting import split_message

        text = "A" * 4000 + "\n" + "B" * 200
        result = split_message(text, max_length=4096)
        assert result[0].endswith("A")
        assert result[1].startswith("B")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telegram_formatting.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.telegram_bot.formatting'`

### Task 3: Implement formatting module

**Files:**
- Create: `src/telegram_bot/formatting.py`

- [ ] **Step 1: Implement the formatting module**

Create `src/telegram_bot/formatting.py`:

```python
"""Convert RAG response dicts to Telegram HTML message parts."""
import re
from html import escape as html_escape
from typing import Any

# Reuse Unicode maps from the existing Streamlit formatter
from src.utils.answer_formatting import _SUPERSCRIPT_MAP, _SUBSCRIPT_MAP


# --- LaTeX delimiter patterns ---
_LATEX_BLOCK_PATTERN = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_LATEX_INLINE_PATTERN = re.compile(r"\$(.+?)\$")
_LATEX_BRACKET_PATTERN = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)
_LATEX_PAREN_PATTERN = re.compile(r"\\\((.+?)\\\)")

# --- HTML tag patterns (same as answer_formatting.py) ---
_SUP_PATTERN = re.compile(r"<sup\b[^>]*>(.*?)</sup>", re.IGNORECASE | re.DOTALL)
_SUB_PATTERN = re.compile(r"<sub\b[^>]*>(.*?)</sub>", re.IGNORECASE | re.DOTALL)

MAX_MESSAGE_LENGTH = 4096


def _render_unicode(text: str, mapping: dict[str, str], fallback_prefix: str) -> str:
    """Convert text to Unicode super/subscript if all chars are in the map."""
    cleaned = text.strip()
    if cleaned and all(char in mapping for char in cleaned):
        return "".join(mapping[char] for char in cleaned)
    return f"{fallback_prefix}({cleaned})" if cleaned else ""


def _strip_latex_delimiters(text: str) -> str:
    """Remove LaTeX delimiters, keep inner content."""
    text = _LATEX_BLOCK_PATTERN.sub(r"\1", text)
    text = _LATEX_INLINE_PATTERN.sub(r"\1", text)
    text = _LATEX_BRACKET_PATTERN.sub(r"\1", text)
    text = _LATEX_PAREN_PATTERN.sub(r"\1", text)
    return text


def _convert_sup_sub(text: str) -> str:
    """Convert <sup>/<sub> HTML tags to Unicode characters."""
    text = _SUP_PATTERN.sub(
        lambda m: _render_unicode(m.group(1), _SUPERSCRIPT_MAP, "^"), text
    )
    text = _SUB_PATTERN.sub(
        lambda m: _render_unicode(m.group(1), _SUBSCRIPT_MAP, "_"), text
    )
    return text


def format_answer_text(answer: str) -> str:
    """Convert RAG answer to Telegram-safe HTML with Unicode math.

    Order of operations:
    1. Convert <sup>/<sub> to Unicode (before HTML escaping eats the tags)
    2. Strip LaTeX delimiters
    3. HTML-escape remaining special chars for Telegram HTML parse_mode
    """
    text = _convert_sup_sub(answer)
    text = _strip_latex_delimiters(text)
    # HTML-escape but preserve newlines
    lines = text.split("\n")
    lines = [html_escape(line) for line in lines]
    return "\n".join(lines)


def format_youtube_sources(sources: list[dict[str, Any]]) -> str:
    """Format YouTube sources as numbered HTML link list."""
    if not sources:
        return ""

    parts: list[str] = []
    for i, src in enumerate(sources, 1):
        title = html_escape(src.get("title", "Video"))
        url = html_escape(src.get("timestamp_url", src.get("source", "")))
        ts_label = src.get("timestamp_label", "")
        display = f"{title} @ {ts_label}" if ts_label else title
        parts.append(f'{i}. <a href="{url}">{display}</a>')

    return "\n".join(parts)


def format_question_sources(question_sources: list[dict[str, Any]]) -> str:
    """Format NeetPrep question sources as numbered HTML link list."""
    if not question_sources:
        return ""

    parts: list[str] = []
    for i, src in enumerate(question_sources, 1):
        qid = src.get("question_id", "")
        url = f"https://www.neetprep.com/epubQuestion/{html_escape(str(qid))}"
        label = html_escape(src.get("content", f"Question {qid}"))
        parts.append(f'{i}. <a href="{url}">{label}</a>')

    return "\n".join(parts)


def format_response(rag_result: dict[str, Any]) -> list[str]:
    """Convert RAG response dict to list of Telegram HTML message parts.

    Returns a list because the full message may exceed 4096 chars.
    """
    answer = rag_result.get("answer", "")
    sources = rag_result.get("sources", [])
    question_sources = rag_result.get("question_sources", [])

    sections: list[str] = []

    # Answer section
    formatted_answer = format_answer_text(answer)
    sections.append(formatted_answer)

    # YouTube sources section
    yt_text = format_youtube_sources(sources)
    if yt_text:
        sections.append(f"\n<b>Related Videos:</b>\n{yt_text}")

    # Question sources section
    q_text = format_question_sources(question_sources)
    if q_text:
        sections.append(f"\n<b>Related Questions:</b>\n{q_text}")

    full_message = "\n".join(sections)
    return split_message(full_message)


def split_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split long text into parts, preferring newline boundaries."""
    if len(text) <= max_length:
        return [text]

    parts: list[str] = []
    remaining = text
    while len(remaining) > max_length:
        # Find last newline within limit
        split_at = remaining.rfind("\n", 0, max_length)
        if split_at <= 0:
            # No newline found — hard split
            split_at = max_length
        parts.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")

    if remaining:
        parts.append(remaining)

    return parts
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_telegram_formatting.py -v`
Expected: All ~15 tests PASS

- [ ] **Step 3: Commit**

```bash
git add src/telegram_bot/formatting.py tests/test_telegram_formatting.py
git commit -m "feat(telegram): add formatting module with TDD tests"
```

---

## Chunk 3: History Module (TDD)

### Task 4: Write history tests

**Files:**
- Create: `tests/test_telegram_history.py`

- [ ] **Step 1: Write all history tests**

Create `tests/test_telegram_history.py`:

```python
"""Tests for Telegram per-user chat history (Redis-backed)."""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestTelegramChatHistory:
    """Tests for TelegramChatHistory."""

    def _make_history(self, mock_redis=None):
        """Create a TelegramChatHistory with an optional mock Redis client."""
        from src.telegram_bot.history import TelegramChatHistory

        history = TelegramChatHistory.__new__(TelegramChatHistory)
        history._redis = mock_redis
        history._max_turns = 4
        history._ttl_seconds = 604800
        return history

    def test_load_returns_empty_for_unknown_user(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        history = self._make_history(mock_redis)

        result = history.load_history(user_id=999)

        assert result == []
        mock_redis.get.assert_called_once_with("telegram_chat:999")

    def test_save_and_load_single_turn(self):
        stored = {}

        def mock_get(key):
            return stored.get(key)

        def mock_setex(key, ttl, value):
            stored[key] = value

        mock_redis = MagicMock()
        mock_redis.get.side_effect = mock_get
        mock_redis.setex.side_effect = mock_setex

        history = self._make_history(mock_redis)
        history.save_turn(user_id=123, user_message="What is osmosis?",
                          assistant_message="Movement of water through membrane.")

        result = history.load_history(user_id=123)
        assert len(result) == 1
        assert result[0] == ("What is osmosis?", "Movement of water through membrane.")

    def test_history_trimmed_to_max_turns(self):
        stored = {}

        def mock_get(key):
            return stored.get(key)

        def mock_setex(key, ttl, value):
            stored[key] = value

        mock_redis = MagicMock()
        mock_redis.get.side_effect = mock_get
        mock_redis.setex.side_effect = mock_setex

        history = self._make_history(mock_redis)
        history._max_turns = 2

        for i in range(5):
            history.save_turn(user_id=1, user_message=f"q{i}", assistant_message=f"a{i}")

        result = history.load_history(user_id=1)
        assert len(result) == 2
        assert result[0] == ("q3", "a3")
        assert result[1] == ("q4", "a4")

    def test_different_users_isolated(self):
        stored = {}

        def mock_get(key):
            return stored.get(key)

        def mock_setex(key, ttl, value):
            stored[key] = value

        mock_redis = MagicMock()
        mock_redis.get.side_effect = mock_get
        mock_redis.setex.side_effect = mock_setex

        history = self._make_history(mock_redis)
        history.save_turn(user_id=1, user_message="q1", assistant_message="a1")
        history.save_turn(user_id=2, user_message="q2", assistant_message="a2")

        assert len(history.load_history(user_id=1)) == 1
        assert len(history.load_history(user_id=2)) == 1
        assert history.load_history(user_id=1)[0][0] == "q1"
        assert history.load_history(user_id=2)[0][0] == "q2"

    def test_ttl_set_on_save(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        history = self._make_history(mock_redis)
        history.save_turn(user_id=1, user_message="q", assistant_message="a")

        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args
        assert args[0][0] == "telegram_chat:1"
        assert args[0][1] == 604800  # 7 days

    def test_load_graceful_when_redis_unavailable(self):
        history = self._make_history(mock_redis=None)

        result = history.load_history(user_id=1)
        assert result == []

    def test_save_graceful_when_redis_unavailable(self):
        history = self._make_history(mock_redis=None)

        # Should not raise
        history.save_turn(user_id=1, user_message="q", assistant_message="a")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telegram_history.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.telegram_bot.history'`

### Task 5: Implement history module

**Files:**
- Create: `src/telegram_bot/history.py`

- [ ] **Step 1: Implement the history module**

Create `src/telegram_bot/history.py`:

```python
"""Per-user Telegram chat history backed by Redis."""
import json
import logging
import os
from typing import Optional

import redis

logger = logging.getLogger(__name__)


class TelegramChatHistory:
    """Store and retrieve per-user conversation turns in Redis.

    Stores raw answer text (not formatted HTML) so history passed back
    into RAG is clean plaintext.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        max_turns: int = 4,
        ttl_seconds: int = 604800,  # 7 days
    ) -> None:
        self._max_turns = max_turns
        self._ttl_seconds = ttl_seconds
        self._redis: Optional[redis.Redis] = None

        url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        try:
            client = redis.from_url(
                url,
                socket_connect_timeout=2,
                socket_timeout=2,
                retry_on_timeout=False,
            )
            client.ping()
            self._redis = client
            logger.info("Telegram history: Redis connected at %s", url)
        except Exception:
            logger.warning(
                "Telegram history: Redis unavailable at %s — history disabled", url
            )
            self._redis = None

    def _key(self, user_id: int) -> str:
        return f"telegram_chat:{user_id}"

    def load_history(self, user_id: int) -> list[tuple[str, str]]:
        """Load recent conversation turns for a user.

        Returns list of (user_message, assistant_message) tuples.
        Returns [] if Redis unavailable or no history exists.
        """
        if self._redis is None:
            return []

        try:
            raw = self._redis.get(self._key(user_id))
            if raw is None:
                return []
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", errors="ignore")
            pairs = json.loads(raw)
            return [(str(p[0]), str(p[1])) for p in pairs]
        except Exception:
            logger.warning("Failed to load history for user %s", user_id, exc_info=True)
            return []

    def save_turn(
        self, user_id: int, user_message: str, assistant_message: str
    ) -> None:
        """Append a conversation turn and trim to max_turns.

        assistant_message should be the RAW answer text from RAG,
        not the formatted Telegram HTML.
        """
        if self._redis is None:
            return

        try:
            existing = self.load_history(user_id)
            existing.append((user_message, assistant_message))
            # Trim to last N turns
            trimmed = existing[-self._max_turns :]
            payload = json.dumps([[u, a] for u, a in trimmed])
            self._redis.setex(self._key(user_id), self._ttl_seconds, payload)
        except Exception:
            logger.warning("Failed to save history for user %s", user_id, exc_info=True)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_telegram_history.py -v`
Expected: All 7 tests PASS

- [ ] **Step 3: Commit**

```bash
git add src/telegram_bot/history.py tests/test_telegram_history.py
git commit -m "feat(telegram): add per-user chat history module with TDD tests"
```

---

## Chunk 4: Bot Handlers (TDD)

### Task 6: Write bot handler tests

**Files:**
- Create: `tests/test_telegram_bot.py`

- [ ] **Step 1: Write all bot handler tests**

Create `tests/test_telegram_bot.py`:

```python
"""Tests for Telegram bot handlers."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_rag(answer="The answer is 42", sources=None, question_sources=None,
                   error=None, extract_return="QUESTION: test"):
    """Create a mock RAG system."""
    rag = MagicMock()
    result = {
        "answer": answer,
        "sources": sources or [],
        "question_sources": question_sources or [],
    }
    if error:
        result["error"] = error
    rag.query_with_history.return_value = result
    rag.llm_manager.extract_image_context.return_value = extract_return
    return rag


def _make_mock_history():
    """Create a mock TelegramChatHistory."""
    history = MagicMock()
    history.load_history.return_value = []
    return history


def _make_text_update(text, user_id=123):
    """Create a mock Update with a text message."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = user_id
    update.message.text = text
    update.message.photo = None
    update.message.caption = None
    update.message.reply_text = AsyncMock()
    return update


def _make_photo_update(caption="", user_id=123):
    """Create a mock Update with a photo message."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = user_id
    update.message.text = None
    update.message.caption = caption or None

    photo = MagicMock()
    photo.file_id = "test_file_id"
    update.message.photo = [photo]

    update.message.reply_text = AsyncMock()
    return update


def _make_context(rag=None, history=None):
    """Create a mock context with bot_data."""
    context = MagicMock()
    context.bot_data = {
        "rag": rag or _make_mock_rag(),
        "history": history or _make_mock_history(),
    }
    context.bot.send_chat_action = AsyncMock()

    # Mock file download for photo tests
    mock_file = MagicMock()
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake_image"))
    context.bot.get_file = AsyncMock(return_value=mock_file)

    return context


class TestStartCommand:
    @pytest.mark.asyncio
    async def test_sends_welcome_message(self):
        from src.telegram_bot.bot import start_command

        update = _make_text_update("/start")
        context = _make_context()

        await start_command(update, context)

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "NEET" in msg or "PYQ" in msg


class TestHelpCommand:
    @pytest.mark.asyncio
    async def test_sends_usage_text(self):
        from src.telegram_bot.bot import help_command

        update = _make_text_update("/help")
        context = _make_context()

        await help_command(update, context)

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "question" in msg.lower() or "photo" in msg.lower()


class TestHandleMessage:
    @pytest.mark.asyncio
    async def test_sends_typing_action(self):
        from src.telegram_bot.bot import handle_message

        update = _make_text_update("What is osmosis?")
        context = _make_context()

        await handle_message(update, context)

        context.bot.send_chat_action.assert_called()

    @pytest.mark.asyncio
    async def test_calls_rag_with_correct_args(self):
        from src.telegram_bot.bot import handle_message

        rag = _make_mock_rag()
        history = _make_mock_history()
        update = _make_text_update("What is osmosis?", user_id=456)
        context = _make_context(rag=rag, history=history)

        await handle_message(update, context)

        rag.query_with_history.assert_called_once()
        call_kwargs = rag.query_with_history.call_args
        assert call_kwargs[0][0] == "What is osmosis?"
        assert call_kwargs[1]["session_id"] == "456"

    @pytest.mark.asyncio
    async def test_reply_uses_html_parse_mode(self):
        from src.telegram_bot.bot import handle_message

        update = _make_text_update("test")
        context = _make_context()

        await handle_message(update, context)

        call_kwargs = update.message.reply_text.call_args[1]
        assert call_kwargs.get("parse_mode") == "HTML"

    @pytest.mark.asyncio
    async def test_saves_turn_to_history(self):
        from src.telegram_bot.bot import handle_message

        history = _make_mock_history()
        update = _make_text_update("What is osmosis?", user_id=789)
        context = _make_context(history=history)

        await handle_message(update, context)

        history.save_turn.assert_called_once()
        args = history.save_turn.call_args[1]
        assert args["user_id"] == 789
        assert args["user_message"] == "What is osmosis?"

    @pytest.mark.asyncio
    async def test_rag_exception_returns_friendly_message(self):
        from src.telegram_bot.bot import handle_message

        rag = _make_mock_rag()
        rag.query_with_history.side_effect = Exception("DB connection failed")
        update = _make_text_update("test")
        context = _make_context(rag=rag)

        await handle_message(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "sorry" in msg.lower() or "couldn't" in msg.lower()
        assert "DB connection" not in msg

    @pytest.mark.asyncio
    async def test_rag_error_as_answer_returns_friendly_message(self):
        from src.telegram_bot.bot import handle_message

        rag = _make_mock_rag(answer="Error generating answer: timeout", error="timeout")
        history = _make_mock_history()
        update = _make_text_update("test")
        context = _make_context(rag=rag, history=history)

        await handle_message(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "Error generating answer" not in msg
        history.save_turn.assert_not_called()

    @pytest.mark.asyncio
    async def test_rag_error_key_returns_friendly_message(self):
        from src.telegram_bot.bot import handle_message

        rag = _make_mock_rag(answer="Knowledge base is empty or unavailable.",
                             error="No vectorstore found")
        history = _make_mock_history()
        update = _make_text_update("test")
        context = _make_context(rag=rag, history=history)

        await handle_message(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "No vectorstore found" not in msg
        history.save_turn.assert_not_called()


class TestHandlePhoto:
    @pytest.mark.asyncio
    async def test_downloads_highest_res_photo(self):
        from src.telegram_bot.bot import handle_photo

        update = _make_photo_update()
        context = _make_context()

        await handle_photo(update, context)

        context.bot.get_file.assert_called_once_with("test_file_id")

    @pytest.mark.asyncio
    async def test_calls_extract_image_context(self):
        from src.telegram_bot.bot import handle_photo

        rag = _make_mock_rag()
        update = _make_photo_update()
        context = _make_context(rag=rag)

        await handle_photo(update, context)

        rag.llm_manager.extract_image_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_caption_included_in_query(self):
        from src.telegram_bot.bot import handle_photo

        rag = _make_mock_rag(extract_return="QUESTION: velocity problem")
        update = _make_photo_update(caption="Solve this physics problem")
        context = _make_context(rag=rag)

        await handle_photo(update, context)

        query = rag.query_with_history.call_args[0][0]
        assert "Solve this physics problem" in query
        assert "QUESTION: velocity problem" in query

    @pytest.mark.asyncio
    async def test_no_caption_uses_extracted_text(self):
        from src.telegram_bot.bot import handle_photo

        rag = _make_mock_rag(extract_return="QUESTION: biology cell division")
        update = _make_photo_update(caption="")
        context = _make_context(rag=rag)

        await handle_photo(update, context)

        query = rag.query_with_history.call_args[0][0]
        assert "QUESTION: biology cell division" in query

    @pytest.mark.asyncio
    async def test_image_extraction_error_returns_friendly_message(self):
        from src.telegram_bot.bot import handle_photo

        rag = _make_mock_rag()
        rag.llm_manager.extract_image_context.side_effect = Exception("Vision API down")
        update = _make_photo_update()
        context = _make_context(rag=rag)

        await handle_photo(update, context)

        msg = update.message.reply_text.call_args[0][0]
        assert "couldn't read" in msg.lower() or "image" in msg.lower()
        assert "Vision API" not in msg
```

- [ ] **Step 2: Install pytest-asyncio**

Run: `pip install pytest-asyncio`
Expected: Successfully installed

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.telegram_bot.bot'`

### Task 7: Implement bot handlers

**Files:**
- Create: `src/telegram_bot/bot.py`

- [ ] **Step 1: Implement the bot module**

Create `src/telegram_bot/bot.py`:

```python
"""Telegram bot application factory and message handlers."""
import asyncio
import logging
from typing import Optional

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.rag.neet_rag import NEETRAG
from src.telegram_bot.formatting import format_response
from src.telegram_bot.history import TelegramChatHistory

logger = logging.getLogger(__name__)

# User-friendly error messages (never expose internals)
_ERR_GENERIC = "Sorry, I couldn't process your question right now. Please try again."
_ERR_IMAGE_DOWNLOAD = "I couldn't download your image. Please try sending it again."
_ERR_IMAGE_EXTRACT = (
    "I couldn't read the question from your image. "
    "Try a clearer photo or type the question."
)


def _is_error_response(result: dict) -> bool:
    """Check if RAG result is an error (exception or error-as-answer)."""
    if "error" in result:
        return True
    answer = result.get("answer", "")
    if answer.startswith("Error generating answer:"):
        return True
    return False


def create_application(
    token: str, rag: Optional[NEETRAG] = None
) -> Application:
    """Build and configure the bot Application with all handlers.

    Args:
        token: Telegram bot API token.
        rag: Optional NEETRAG instance. If None, uses get_rag_system() singleton.
    """
    app = Application.builder().token(token).build()

    # Inject dependencies into bot_data for handler access
    if rag is None:
        from src.utils.rag_singleton import get_rag_system
        rag = get_rag_system()

    app.bot_data["rag"] = rag
    app.bot_data["history"] = TelegramChatHistory()

    # Register handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    return app


def run_polling(app: Application) -> None:
    """Start the bot in polling mode."""
    logger.info("Starting Telegram bot in polling mode...")
    app.run_polling(drop_pending_updates=True)


async def start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /start — send welcome message."""
    welcome = (
        "Welcome to the <b>NEET PYQ Assistant</b>!\n\n"
        "I can help you with NEET previous year questions. "
        "Send me a text question or a photo of a question, "
        "and I'll find relevant answers, solutions, and video explanations.\n\n"
        "Type /help for usage instructions."
    )
    await update.message.reply_text(welcome, parse_mode=ParseMode.HTML)


async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /help — send usage instructions."""
    help_text = (
        "<b>How to use this bot:</b>\n\n"
        "<b>Text question:</b> Just type your question and send it.\n"
        "Example: <i>What is the difference between mitosis and meiosis?</i>\n\n"
        "<b>Photo question:</b> Send a photo of a question from your textbook "
        "or exam paper. You can add a caption for extra context.\n\n"
        "I'll respond with:\n"
        "- An answer based on NEET PYQ knowledge base\n"
        "- Links to relevant YouTube video explanations\n"
        "- Links to related previous year questions"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


async def _send_typing_periodically(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Send typing action every 5 seconds until cancelled."""
    try:
        while True:
            await context.bot.send_chat_action(
                chat_id=chat_id, action=ChatAction.TYPING
            )
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        pass


async def handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle text messages — query RAG and reply."""
    question = update.message.text
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    rag: NEETRAG = context.bot_data["rag"]
    history: TelegramChatHistory = context.bot_data["history"]

    # Start typing indicator
    typing_task = asyncio.create_task(
        _send_typing_periodically(chat_id, context)
    )

    try:
        chat_history = history.load_history(user_id)

        result = rag.query_with_history(
            question,
            chat_history=chat_history,
            session_id=str(user_id),
            user_id=str(user_id),
        )

        # Check for error-as-answer
        if _is_error_response(result):
            logger.error(
                "RAG error for user %s: %s",
                user_id,
                result.get("error", result.get("answer", "")),
            )
            await update.message.reply_text(_ERR_GENERIC)
            return

        raw_answer = result.get("answer", "")
        parts = format_response(result)

        for part in parts:
            await update.message.reply_text(part, parse_mode=ParseMode.HTML)

        # Save raw answer (not formatted HTML) to history
        history.save_turn(
            user_id=user_id,
            user_message=question,
            assistant_message=raw_answer,
        )

    except Exception:
        logger.exception("Error handling message for user %s", user_id)
        await update.message.reply_text(_ERR_GENERIC)
    finally:
        typing_task.cancel()


async def handle_photo(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle photo messages — extract context, query RAG, reply."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    caption = update.message.caption or ""
    rag: NEETRAG = context.bot_data["rag"]
    history: TelegramChatHistory = context.bot_data["history"]

    # Start typing indicator
    typing_task = asyncio.create_task(
        _send_typing_periodically(chat_id, context)
    )

    try:
        # Download highest-resolution photo
        photo = update.message.photo[-1]
        try:
            file = await context.bot.get_file(photo.file_id)
            image_bytes = bytes(await file.download_as_bytearray())
        except Exception:
            logger.exception("Failed to download photo for user %s", user_id)
            await update.message.reply_text(_ERR_IMAGE_DOWNLOAD)
            return

        # Extract question context from image
        try:
            extracted = rag.llm_manager.extract_image_context(
                image_bytes=image_bytes,
                filename="telegram_photo.jpg",
                user_hint=caption,
                session_id=str(user_id),
                user_id=str(user_id),
            )
        except Exception:
            logger.exception("Image extraction failed for user %s", user_id)
            await update.message.reply_text(_ERR_IMAGE_EXTRACT)
            return

        # Build query from caption + extracted text
        if caption:
            question = f"{caption}\n\nImage context:\n{extracted}"
        else:
            question = extracted

        # Query RAG
        chat_history = history.load_history(user_id)

        result = rag.query_with_history(
            question,
            chat_history=chat_history,
            session_id=str(user_id),
            user_id=str(user_id),
        )

        if _is_error_response(result):
            logger.error(
                "RAG error for user %s: %s",
                user_id,
                result.get("error", result.get("answer", "")),
            )
            await update.message.reply_text(_ERR_GENERIC)
            return

        raw_answer = result.get("answer", "")
        parts = format_response(result)

        for part in parts:
            await update.message.reply_text(part, parse_mode=ParseMode.HTML)

        history.save_turn(
            user_id=user_id,
            user_message=question,
            assistant_message=raw_answer,
        )

    except Exception:
        logger.exception("Error handling photo for user %s", user_id)
        await update.message.reply_text(_ERR_GENERIC)
    finally:
        typing_task.cancel()


async def error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Global error handler — log error, never expose to user."""
    logger.error("Unhandled exception: %s", context.error, exc_info=context.error)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_telegram_bot.py -v`
Expected: All ~14 tests PASS

- [ ] **Step 3: Commit**

```bash
git add src/telegram_bot/bot.py tests/test_telegram_bot.py
git commit -m "feat(telegram): add bot handlers with TDD tests"
```

---

## Chunk 5: Integration Tests, Entry Point & Deployment

### Task 8: Write integration tests

**Files:**
- Create: `tests/test_telegram_integration.py`

- [ ] **Step 1: Write integration tests**

Create `tests/test_telegram_integration.py`:

```python
"""Integration tests for Telegram bot end-to-end flows."""
import pytest
from unittest.mock import AsyncMock, MagicMock

# Reuse helpers from bot tests
from tests.test_telegram_bot import (
    _make_mock_rag,
    _make_mock_history,
    _make_text_update,
    _make_photo_update,
    _make_context,
)


class TestTextEndToEnd:
    @pytest.mark.asyncio
    async def test_text_question_returns_formatted_html_with_sources(self):
        from src.telegram_bot.bot import handle_message

        rag = _make_mock_rag(
            answer="The answer is (B) 9.8 m/s²",
            sources=[{
                "content_type": "youtube",
                "title": "Gravity Explained",
                "timestamp_url": "https://youtube.com/watch?v=abc&t=30s",
                "timestamp_label": "0:30",
            }],
            question_sources=[{"question_id": "555", "content": "NEET 2022 Q.12"}],
        )
        update = _make_text_update("What is acceleration due to gravity?")
        context = _make_context(rag=rag)

        await handle_message(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "9.8" in reply
        assert "youtube.com" in reply
        assert "neetprep.com" in reply


class TestPhotoEndToEnd:
    @pytest.mark.asyncio
    async def test_photo_question_extracts_and_queries(self):
        from src.telegram_bot.bot import handle_photo

        rag = _make_mock_rag(
            answer="The solution involves Newton's second law",
            extract_return="QUESTION: A 2kg block on a frictionless surface...",
        )
        update = _make_photo_update(caption="Solve this")
        context = _make_context(rag=rag)

        await handle_photo(update, context)

        # Verify extraction was called
        rag.llm_manager.extract_image_context.assert_called_once()
        # Verify RAG query includes both caption and extracted text
        query = rag.query_with_history.call_args[0][0]
        assert "Solve this" in query
        assert "2kg block" in query
        # Verify reply was sent
        reply = update.message.reply_text.call_args[0][0]
        assert "Newton" in reply


class TestConversationContinuity:
    @pytest.mark.asyncio
    async def test_second_message_receives_history_from_first(self):
        from src.telegram_bot.bot import handle_message

        rag = _make_mock_rag(answer="Osmosis is the movement of water.")
        history = _make_mock_history()
        context = _make_context(rag=rag, history=history)

        # Message 1
        update1 = _make_text_update("What is osmosis?", user_id=100)
        await handle_message(update1, context)

        # Simulate history having the first turn
        history.load_history.return_value = [
            ("What is osmosis?", "Osmosis is the movement of water.")
        ]

        # Message 2
        rag.query_with_history.return_value = {
            "answer": "Diffusion does not require a membrane.",
            "sources": [],
            "question_sources": [],
        }
        update2 = _make_text_update("How is it different from diffusion?", user_id=100)
        await handle_message(update2, context)

        # Verify second call received history
        second_call = rag.query_with_history.call_args_list[1]
        chat_history = second_call[1].get("chat_history") or second_call[0][1]
        assert len(chat_history) == 1
        assert chat_history[0][0] == "What is osmosis?"


class TestErrorRecovery:
    @pytest.mark.asyncio
    async def test_rag_fails_then_succeeds(self):
        from src.telegram_bot.bot import handle_message

        rag = _make_mock_rag()
        rag.query_with_history.side_effect = [
            Exception("temporary failure"),
            {"answer": "The answer is 42", "sources": [], "question_sources": []},
        ]
        history = _make_mock_history()
        context = _make_context(rag=rag, history=history)

        # First message fails
        update1 = _make_text_update("test1")
        await handle_message(update1, context)
        msg1 = update1.message.reply_text.call_args[0][0]
        assert "sorry" in msg1.lower() or "couldn't" in msg1.lower()

        # Second message succeeds
        update2 = _make_text_update("test2")
        await handle_message(update2, context)
        msg2 = update2.message.reply_text.call_args[0][0]
        assert "42" in msg2


class TestEmptyKnowledgeBase:
    @pytest.mark.asyncio
    async def test_no_content_response_handled_gracefully(self):
        from src.telegram_bot.bot import handle_message

        rag = _make_mock_rag(answer="No relevant information found in the knowledge base.")
        update = _make_text_update("What is dark matter?")
        context = _make_context(rag=rag)

        await handle_message(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "No relevant information" in reply
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/test_telegram_integration.py -v`
Expected: All 5 tests PASS

### Task 9: Create entry point and update deployment

**Files:**
- Create: `run_telegram_bot.py`
- Modify: `deploy/entrypoint.sh`

- [ ] **Step 1: Create run_telegram_bot.py**

Create `run_telegram_bot.py`:

```python
"""Entry point for the NEET PYQ Telegram Bot."""
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

    logger.info("Initializing NEET PYQ Telegram Bot...")

    from src.telegram_bot.bot import create_application, run_polling

    app = create_application(token)
    run_polling(app)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Update deploy/entrypoint.sh**

Replace contents of `deploy/entrypoint.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Start Telegram bot in background (if token is configured)
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "[entrypoint] Starting Telegram bot (polling mode)..."
  python run_telegram_bot.py &
  TELEGRAM_PID=$!
  echo "[entrypoint] Telegram bot started (PID: $TELEGRAM_PID)"
fi

# Start Streamlit frontend (foreground — container stays alive)
exec python deploy/start_frontend.py
```

- [ ] **Step 3: Run all tests**

Run: `pytest tests/test_telegram_*.py -v`
Expected: All ~41 tests PASS

- [ ] **Step 4: Run existing tests to verify no regressions**

Run: `pytest tests/ -v --ignore=tests/manual_tests --ignore=tests/scripts`
Expected: All existing tests still pass

- [ ] **Step 5: Commit**

```bash
git add run_telegram_bot.py deploy/entrypoint.sh tests/test_telegram_integration.py
git commit -m "feat(telegram): add entry point, deployment integration, and integration tests"
```

---

## Chunk 6: Smoke Test & Final Verification

### Task 10: Manual smoke test

- [ ] **Step 1: Start the bot locally**

Run: `python run_telegram_bot.py`
Expected: Output includes "Starting Telegram bot in polling mode" and "Telegram bot started". No crash.

- [ ] **Step 2: Send /start to the bot**

Open Telegram, go to `t.me/pyq_ai_bot`, send `/start`.
Expected: Bot replies with welcome message containing "NEET PYQ Assistant".

- [ ] **Step 3: Send a text question**

Send: "What is the difference between mitosis and meiosis?"
Expected: Bot shows "typing...", then replies with an answer + YouTube video links + NeetPrep question links (if available in the knowledge base). Response uses HTML formatting.

- [ ] **Step 4: Send a photo of a question**

Send a photo of a NEET question (from textbook or phone screenshot).
Expected: Bot shows "typing...", extracts the question, queries RAG, and replies with an answer.

- [ ] **Step 5: Final commit with all files**

Run full test suite one more time:
```bash
pytest tests/test_telegram_*.py -v
```

If all pass:
```bash
git add -A
git status  # verify only expected files
git commit -m "feat(telegram): complete Telegram bot integration (Phase 1 — polling mode)"
```

- [ ] **Step 6: Verify git log**

Run: `git log --oneline -5`
Expected: See the series of commits from this plan.
