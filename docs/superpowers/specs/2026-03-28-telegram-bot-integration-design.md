# Telegram Bot Integration Design Spec

## Goal

Add a Telegram bot (`t.me/pyq_ai_bot`) as a new chat interface for the NEET PYQ Assistant. The Telegram bot becomes the primary user-facing chat channel. Streamlit remains running for admin and history pages but its chat page is no longer the main entry point. The bot handles text messages and photo uploads of math/science questions, queries the existing RAG pipeline, and responds with formatted answers including YouTube video links and NeetPrep question links.

## Constraints

- Reuse existing RAG pipeline (`NEETRAG.query_with_history`), image extraction (`LLMManager.extract_image_context`), and Redis infrastructure
- Run in the same Docker container as Streamlit (shared ECS task)
- **Phase 1 (this spec): Polling mode only.** Webhook infrastructure (Terraform/ALB/TLS changes) is deferred to a follow-up task. The bot uses polling for both local dev and initial production deployment.
- No new LLM providers or vector stores — use existing OpenRouter/Gemini + FAISS

## Architecture

```
Telegram Cloud
    | getUpdates (long polling)
    v
python-telegram-bot v21+ (polling mode)
    |
    +-- /start, /help --> static welcome/usage text
    +-- Text message --> query pipeline
    +-- Photo message --> extract_image_context() --> query pipeline
    |
    v
Query Pipeline:
    1. sendChatAction("typing")
    2. Load user chat history from Redis
    3. rag.query_with_history(question, chat_history, session_id, user_id)
    4. Check for error-as-answer (e.g. "Error generating answer: ...")
    5. Format response as Telegram HTML
    6. Split if >4096 chars, send parts
    7. Save conversation turn to Redis (raw answer text, not formatted HTML)
```

### Container Layout

```
ECS Task (single container)
  +-- Streamlit (port 8501) -- existing frontend (admin/history)
  +-- Telegram Bot (polling) -- new background process, no port needed
  +-- Shared: FAISS index, Redis, env vars
```

The entry script (`deploy/entrypoint.sh`) starts both processes. The bot process is optional — controlled by `TELEGRAM_BOT_TOKEN` presence. Since Phase 1 uses polling (not webhook), no additional ports, ALB target groups, or Terraform changes are required.

## File Structure

### New Files

| File | Responsibility |
|------|----------------|
| `src/telegram_bot/__init__.py` | Package init, exports `create_application()` |
| `src/telegram_bot/bot.py` | Application factory, handlers (text, photo, commands), webhook/polling startup |
| `src/telegram_bot/formatting.py` | Convert RAG response dict to Telegram HTML string (answer + source links) |
| `src/telegram_bot/history.py` | Per-user Redis chat history: save turn, load recent turns, Redis connection |
| `run_telegram_bot.py` | Entry point: loads env, calls `create_application()`, starts polling or webhook |
| `tests/test_telegram_formatting.py` | Unit tests for formatting module |
| `tests/test_telegram_history.py` | Unit tests for history module |
| `tests/test_telegram_bot.py` | Unit tests for bot handlers |
| `tests/test_telegram_integration.py` | Integration tests for end-to-end flows |

### Modified Files

| File | Change |
|------|--------|
| `.env` | Add `TELEGRAM_BOT_TOKEN` (gitignored, never committed) |
| `.env.example` | Add `TELEGRAM_BOT_TOKEN=` placeholder with comment |
| `requirements.txt` | Add `python-telegram-bot>=21.0` |
| `deploy/entrypoint.sh` | Start bot process alongside Streamlit |

## Component Design

### 1. `src/telegram_bot/bot.py` — Bot Application

**Responsibilities:**
- Create `python-telegram-bot` `Application` instance
- Register command handlers (`/start`, `/help`)
- Register message handlers (text, photo)
- Start polling (Phase 1)

**RAG dependency:**
The bot obtains the RAG singleton via `get_rag_system()` from `src/utils/rag_singleton.py` at application startup. This is stored in `application.bot_data["rag"]` so handlers access it via `context.bot_data["rag"]`. This avoids global state and enables test injection via `app.bot_data["rag"] = mock_rag`.

**Public interface:**

```python
def create_application(token: str, rag: NEETRAG | None = None) -> Application:
    """Build and configure the bot Application with all handlers.
    If rag is None, uses get_rag_system() singleton. Pass explicit rag for testing."""

async def run_polling(app: Application) -> None:
    """Start the bot in polling mode."""
```

**Handlers:**

```python
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — send welcome message with bot description."""

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help — send usage instructions."""

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages — query RAG and reply with formatted answer."""

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo messages — extract context, query RAG, reply."""

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler — log error, send user-friendly message."""
```

**Message handler flow (text):**

1. Send `typing` chat action
2. Get RAG from `context.bot_data["rag"]` and history from `context.bot_data["history"]`
3. Load chat history from Redis via `history.load_history(user_id)`
4. Call `rag.query_with_history(question, chat_history, session_id=str(user_id), user_id=str(user_id))`
5. **Check for error-as-answer**: if `answer` starts with `"Error generating answer:"` or `result` contains `"error"` key, treat as failure — send user-friendly error message, log the real error, do NOT save to history
6. Format response via `formatting.format_response(rag_result)` — returns list of HTML message parts
7. Send response parts (split at 4096 chars if needed)
8. Save turn via `history.save_turn(user_id, question, raw_answer)` — saves the **raw answer text** from RAG, not the formatted HTML, so history passed back to RAG is clean plaintext

**Photo handler flow:**

1. Send `typing` chat action
2. Get highest-resolution photo from `update.message.photo[-1]`
3. Download file via `await context.bot.get_file(file_id)` then `await file.download_as_bytearray()`
4. Call `rag.llm_manager.extract_image_context(image_bytes, filename)`
5. Build query: `"{caption}\n\nImage context:\n{extracted}"` (or just extracted if no caption)
6. Continue as text handler from step 2

**Typing indicator refresh:**
For long RAG processing, the typing indicator expires after ~10s. Use `asyncio.create_task` to send typing action every 5 seconds, cancel when response is ready.

### 2. `src/telegram_bot/formatting.py` — Response Formatter

**Responsibilities:**
- Convert RAG answer text to Telegram-safe HTML
- Convert LaTeX delimiters to plain text with Unicode math symbols
- Format YouTube sources as clickable HTML links
- Format NeetPrep question sources as clickable HTML links
- Split long messages at safe boundaries

**Public interface:**

```python
def format_response(rag_result: dict) -> list[str]:
    """Convert RAG response dict to list of Telegram HTML message parts."""

def format_answer_text(answer: str) -> str:
    """Convert RAG answer to Telegram-safe HTML with Unicode math."""

def format_youtube_sources(sources: list[dict]) -> str:
    """Format YouTube sources as HTML link list."""

def format_question_sources(question_sources: list[dict]) -> str:
    """Format NeetPrep question sources as HTML link list."""

def split_message(text: str, max_length: int = 4096) -> list[str]:
    """Split long HTML text into parts, preserving tag boundaries."""
```

**LaTeX handling:**
- Strip `$...$` and `$$...$$` delimiters, keep inner content as plain text
- Strip `\(...\)` and `\[...\]` delimiters similarly
- Reuse `_SUPERSCRIPT_MAP` and `_SUBSCRIPT_MAP` from `src/utils/answer_formatting.py`
- Convert `<sup>` / `<sub>` HTML tags to Unicode (same logic as existing formatter)
- HTML-escape `&`, `<`, `>` in answer text for Telegram HTML parse_mode

**Source formatting example:**

```html
<b>Answer:</b>
The correct answer is (B) 3.6 x 10^4 J.

Using Q = mcDeltaT:
Q = 0.5 x 4200 x (100 - 25) = 157500 J

<b>Related Videos:</b>
1. <a href="https://youtube.com/watch?v=abc&amp;t=123s">Heat &amp; Thermodynamics by Physics Wallah @ 2:03</a>
2. <a href="https://youtube.com/watch?v=def&amp;t=456s">Calorimetry Problems @ 7:36</a>

<b>Related Questions:</b>
1. <a href="https://www.neetprep.com/epubQuestion/12345">Question 12345</a>
```

### 3. `src/telegram_bot/history.py` — Chat History

**Responsibilities:**
- Connect to Redis (reuse connection pattern from `pages/1_Chat.py`)
- Store per-user conversation as list of `(user_msg, assistant_msg)` tuples
- Trim to last N turns (default 4, matching Streamlit)
- 7-day TTL on history keys

**Public interface:**

```python
class TelegramChatHistory:
    def __init__(self, redis_url: str | None = None, max_turns: int = 4, ttl_seconds: int = 604800):
        """Initialize with Redis connection. Graceful fallback if Redis unavailable."""

    def load_history(self, user_id: int) -> list[tuple[str, str]]:
        """Load recent conversation turns for a user."""

    def save_turn(self, user_id: int, user_message: str, assistant_message: str) -> None:
        """Append a conversation turn and trim to max_turns."""
```

**Redis key format:** `telegram_chat:{user_id}`

**Storage format:** JSON array of `[user_msg, assistant_msg]` pairs. Same shape as Streamlit history but keyed by Telegram user_id instead of session UUID.

**Important boundary:** `save_turn()` receives and stores **raw answer text** from RAG (the `answer` string from `query_with_history()` result), NOT the formatted Telegram HTML. This ensures that when history is passed back into RAG for context, it contains clean plaintext without HTML tags or Telegram formatting artifacts. The formatting module is applied only at the reply stage, never at the storage stage.

### 4. `run_telegram_bot.py` — Entry Point

```python
"""Entry point for the NEET PYQ Telegram Bot."""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

from src.telegram_bot.bot import create_application, run_polling

def main():
    logging.basicConfig(level=logging.INFO)
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

    app = create_application(token)
    run_polling(app)

if __name__ == "__main__":
    main()
```

## Configuration Changes

### `.env` additions

```bash
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your-bot-token-here
```

Note: The actual bot token must be set in `.env` (which is gitignored) or injected via ECS task definition secrets. Never commit real tokens. All other Telegram settings use sensible defaults in code (history turns = 4, TTL = 7 days, max message length = 4096).

### `.env.example` additions

```bash
# Telegram Bot Configuration
# Get your token from @BotFather on Telegram
TELEGRAM_BOT_TOKEN=
```

### `requirements.txt` addition

```
python-telegram-bot>=21.0
```

### `deploy/entrypoint.sh` change

Add bot startup alongside Streamlit (only if token is set):

```bash
# Start Telegram bot in background (if token is configured)
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
  python run_telegram_bot.py &
  TELEGRAM_PID=$!
  echo "Telegram bot started (PID: $TELEGRAM_PID)"
fi

# Start Streamlit (existing, foreground — container stays alive while Streamlit runs)
streamlit run app.py --server.port 8501 ...
```

Note: If the bot process crashes, the container continues running (Streamlit is the foreground process). Bot logs go to stdout/stderr and are captured by CloudWatch via ECS log driver. Process supervision (e.g., automatic restart on crash) is deferred to the webhook infrastructure follow-up.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| RAG query raises exception | Reply: "Sorry, I couldn't process your question right now. Please try again." Log full error. Do not save turn to history. |
| RAG returns error-as-answer | `answer` starts with `"Error generating answer:"` or result has `"error"` key → same as exception: user-friendly message, log, skip history save. |
| RAG returns "no content" answer | `"Knowledge base is empty"` or `"No relevant information found"` → forward to user as-is (these are legitimate responses). Save to history. |
| Image download fails | Reply: "I couldn't download your image. Please try sending it again." |
| Image extraction fails | Reply: "I couldn't read the question from your image. Try a clearer photo or type the question." |
| Redis unavailable | Continue without history (empty chat_history). Log warning. |
| Message too long (>4096) | Split into multiple messages, send sequentially. |
| Telegram API rate limit | python-telegram-bot handles retry with backoff automatically. |
| Bot process crashes | Logs to CloudWatch. Streamlit continues. Manual restart required (Phase 1). |

## Testing

### Test Files and Coverage

| Test File | Count | What It Validates |
|-----------|-------|-------------------|
| `tests/test_telegram_formatting.py` | ~15 | RAG response to Telegram HTML conversion |
| `tests/test_telegram_history.py` | ~7 | Redis per-user chat history CRUD |
| `tests/test_telegram_bot.py` | ~14 | Bot handlers (text, photo, commands, error contracts) |
| `tests/test_telegram_integration.py` | ~5 | End-to-end flows with mocked externals |

### Formatting Tests (`test_telegram_formatting.py`)

- LaTeX `$x^2$` delimiters stripped, inner content preserved as plain text
- LaTeX `$$\frac{a}{b}$$` block delimiters stripped similarly
- `\(...\)` and `\[...\]` delimiters handled
- `<sup>2</sup>` converts to Unicode superscript `2` (reuses existing maps)
- `<sub>2</sub>` converts to Unicode subscript `2`
- HTML special chars `&`, `<`, `>` escaped to `&amp;`, `&lt;`, `&gt;`
- YouTube sources formatted as numbered HTML `<a>` links with timestamps
- NeetPrep question sources formatted as numbered HTML `<a>` links
- Empty sources list produces no sources section
- Mixed sources (YouTube + questions) produces both sections
- Message >4096 chars split into valid parts
- Split does not break mid-HTML-tag
- Answer with no special formatting passes through unchanged
- Unicode math symbols preserved (pi, sqrt, etc.)
- Newlines preserved in answer text

### History Tests (`test_telegram_history.py`)

- Save and load a single conversation turn
- Load returns empty list for unknown user_id
- History trimmed to max_turns (save 6 turns with max=4, load returns last 4)
- Different user_ids get isolated histories
- TTL set correctly on Redis key (7 days)
- Graceful fallback when Redis connection fails (load returns `[]`, save is no-op)
- Save with Redis unavailable does not raise

### Bot Handler Tests (`test_telegram_bot.py`)

Mock `Update`, `ContextTypes.DEFAULT_TYPE`, and RAG system:

- `/start` command sends welcome message containing bot description
- `/help` command sends usage text with examples
- Text message calls `sendChatAction("typing")`
- Text message calls `rag.query_with_history()` with correct question, history, session_id
- Text message reply uses HTML parse_mode
- Text message saves turn to history after reply
- Photo message downloads highest-res photo (last in array)
- Photo message calls `extract_image_context()` with downloaded bytes
- Photo with caption includes caption in query
- Photo without caption uses extracted text as query
- RAG exception returns user-friendly message (no stack trace)
- RAG error-as-answer (`"Error generating answer: ..."`) returns user-friendly message, not the raw error string
- RAG error-as-answer does NOT save turn to history
- Image extraction error returns specific error message

### Integration Tests (`test_telegram_integration.py`)

Full handler chain with mocked Telegram API + mocked RAG:

- Text question end-to-end: mock update -> handler -> mock RAG -> formatted reply verified
- Photo question end-to-end: mock photo update -> download -> extract -> RAG -> reply verified
- Conversation continuity: send message 1, then message 2 — verify history from msg 1 is passed to RAG for msg 2
- Error recovery: RAG fails on message 1 (user gets error), succeeds on message 2 (user gets answer)
- Empty knowledge base: RAG returns "no content" response — bot formats it gracefully

### Mocking Approach

```python
# Fixtures following existing test patterns
@pytest.fixture
def mock_rag():
    rag = MagicMock()
    rag.query_with_history.return_value = {
        "answer": "The answer is 42 m/s^2",
        "sources": [{
            "content_type": "youtube",
            "title": "Physics Wallah",
            "timestamp_url": "https://youtube.com/watch?v=abc&t=60s",
            "timestamp_label": "1:00",
        }],
        "question_sources": [{"question_id": "12345", "content": "NEET 2023 Q.45"}],
    }
    rag.llm_manager.extract_image_context.return_value = (
        "QUESTION: A ball is thrown upward...\nOPTIONS: (A) 10 (B) 20"
    )
    return rag

def make_text_update(text: str, user_id: int = 123) -> MagicMock:
    update = MagicMock(spec=Update)
    update.effective_user.id = user_id
    update.effective_chat.id = user_id
    update.message.text = text
    update.message.photo = None
    update.message.caption = None
    return update

def make_photo_update(caption: str = "", user_id: int = 123) -> MagicMock:
    update = MagicMock(spec=Update)
    update.effective_user.id = user_id
    update.effective_chat.id = user_id
    update.message.text = None
    update.message.caption = caption or None
    photo = MagicMock()
    photo.file_id = "test_file_id"
    update.message.photo = [photo]  # single-element list (highest res)
    return update
```

### Run Command

```bash
pytest tests/test_telegram_*.py -v
```
