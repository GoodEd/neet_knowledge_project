import asyncio
import logging
import urllib.parse
from typing import Any, Mapping

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Update,
    WebAppInfo,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.telegram_bot.formatting import format_response
from src.telegram_bot.history import TelegramChatHistory

logger = logging.getLogger(__name__)

_ERR_GENERIC = "Sorry, I couldn't process your question right now. Please try again."
_ERR_IMAGE_DOWNLOAD = "I couldn't download your image. Please try sending it again."
_ERR_IMAGE_EXTRACT = "I couldn't read the question from your image. Try a clearer photo or type the question."


def _is_error_response(result: Mapping[str, object]) -> bool:
    if "error" in result:
        return True
    answer = result.get("answer", "")
    return isinstance(answer, str) and answer.startswith("Error generating answer:")


def create_application(token: str, rag: Any | None = None):
    app = Application.builder().token(token).build()
    if rag is None:
        from src.utils.rag_singleton import get_rag_system

        rag = get_rag_system()

    app.bot_data["rag"] = rag
    app.bot_data["history"] = TelegramChatHistory()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    return app


def run_webhook(
    app: Application[Any, Any, Any, Any, Any, Any],
    webhook_url: str,
    port: int = 8443,
) -> None:
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


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _ = context
    message = update.message
    if message is None:
        return
    welcome = (
        "Welcome to the <b>NEET PYQ Assistant</b>!\n\n"
        "Send a text question or a photo question and I will help with answers and sources.\n\n"
        "Type /help for usage instructions."
    )
    _ = await message.reply_text(welcome, parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _ = context
    message = update.message
    if message is None:
        return
    help_text = (
        "<b>How to use:</b>\n"
        "- Send a text question\n"
        "- Or send a photo of a question with an optional caption"
    )
    _ = await message.reply_text(help_text, parse_mode=ParseMode.HTML)


def _build_source_buttons(
    youtube_sources: list[dict[str, object]],
    question_sources: list[dict[str, object]],
) -> InlineKeyboardMarkup | None:
    buttons: list[list[InlineKeyboardButton]] = []

    for i, src in enumerate(youtube_sources[:5], start=1):
        url = str(src.get("timestamp_url") or src.get("source") or "")
        if not url:
            continue
        title = str(src.get("title") or f"Video #{i}")
        ts = src.get("timestamp_label") or ""
        label = f"\u25b6\ufe0f Video #{i}: {title}"
        if ts:
            label += f" ({ts})"
        if len(label) > 60:
            label = label[:57] + "..."
        buttons.append([InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))])

    for i, src in enumerate(question_sources[:5], start=1):
        qid = str(src.get("question_id") or "")
        if not qid:
            continue
        text = str(src.get("content") or src.get("title") or f"Question #{i}")
        text = text.replace("\n", " ").strip()
        label = f"\ud83d\udcdd Q#{i}: {text}"
        if len(label) > 60:
            label = label[:57] + "..."
        url = f"https://neetprep.com/epubQuestion/{qid}"
        buttons.append([InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))])

    return InlineKeyboardMarkup(buttons) if buttons else None


def _extract_first_youtube_url(sources: list[dict[str, object]]) -> str:
    for src in sources:
        url = str(src.get("timestamp_url") or src.get("source") or "")
        if url and ("youtube.com" in url or "youtu.be" in url):
            return url
    return ""


async def _send_reply_parts(
    message: Any,
    parts: list[str],
    sources: list[dict[str, object]],
    question_sources: list[dict[str, object]] | None = None,
) -> None:
    preview_url = _extract_first_youtube_url(sources)
    keyboard = _build_source_buttons(sources, question_sources or [])
    last_idx = len(parts) - 1
    for i, part in enumerate(parts):
        link_preview = None
        if i == 0 and preview_url:
            link_preview = LinkPreviewOptions(
                url=preview_url,
                prefer_large_media=True,
                show_above_text=True,
            )
        elif i > 0:
            link_preview = LinkPreviewOptions(is_disabled=True)
        reply_markup = keyboard if i == last_idx and keyboard else None
        _ = await message.reply_text(
            part,
            parse_mode=ParseMode.HTML,
            link_preview_options=link_preview,
            reply_markup=reply_markup,
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None or message.text is None:
        return

    question = message.text
    user_id = user.id
    chat_id = chat.id
    rag = context.bot_data["rag"]
    history = context.bot_data["history"]

    status_msg = await message.reply_text(
        "\u23f3 Searching knowledge base...",
        parse_mode=ParseMode.HTML,
    )
    try:
        chat_history = history.load_history(user_id)
        result = rag.query_with_history(
            question,
            chat_history=chat_history,
            session_id=str(user_id),
            user_id=str(user_id),
        )

        if _is_error_response(result):
            await status_msg.edit_text(_ERR_GENERIC)
            return

        await status_msg.edit_text("\u2705 Preparing answer...")

        raw_answer = str(result.get("answer", ""))
        sources = result.get("sources", [])
        q_sources = result.get("question_sources", [])
        parts = format_response(
            answer_text=raw_answer,
            youtube_sources=sources,
            question_sources=q_sources,
        )

        await status_msg.delete()
        await _send_reply_parts(message, parts, sources, q_sources)

        history.save_turn(
            user_id=user_id,
            user_message=question,
            assistant_message=raw_answer,
        )
    except Exception:
        logger.exception("Failed to handle text message")
        try:
            await status_msg.edit_text(_ERR_GENERIC)
        except Exception:
            await message.reply_text(_ERR_GENERIC)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None:
        return

    user_id = user.id
    chat_id = chat.id
    caption = message.caption or ""
    rag = context.bot_data["rag"]
    history = context.bot_data["history"]

    status_msg = await message.reply_text(
        "\u23f3 Reading your image...",
        parse_mode=ParseMode.HTML,
    )
    try:
        try:
            photo = message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            image_bytes = bytes(await file.download_as_bytearray())
        except Exception:
            logger.exception("Failed downloading photo")
            await status_msg.edit_text(_ERR_IMAGE_DOWNLOAD)
            return

        await status_msg.edit_text("\u23f3 Extracting question from image...")

        try:
            extracted = rag.llm_manager.extract_image_context(
                image_bytes=image_bytes,
                filename="telegram_photo.jpg",
                user_hint=caption,
                session_id=str(user_id),
                user_id=str(user_id),
            )
        except Exception:
            logger.exception("Failed extracting photo context")
            await status_msg.edit_text(_ERR_IMAGE_EXTRACT)
            return

        if caption:
            question = f"{caption}\n\nImage context:\n{extracted}"
        else:
            question = str(extracted)

        await status_msg.edit_text("\u23f3 Searching knowledge base...")

        chat_history = history.load_history(user_id)
        result = rag.query_with_history(
            question,
            chat_history=chat_history,
            session_id=str(user_id),
            user_id=str(user_id),
        )

        if _is_error_response(result):
            await status_msg.edit_text(_ERR_GENERIC)
            return

        await status_msg.edit_text("\u2705 Preparing answer...")

        raw_answer = str(result.get("answer", ""))
        sources = result.get("sources", [])
        q_sources = result.get("question_sources", [])
        parts = format_response(
            answer_text=raw_answer,
            youtube_sources=sources,
            question_sources=q_sources,
        )

        await status_msg.delete()
        await _send_reply_parts(message, parts, sources, q_sources)

        history.save_turn(
            user_id=user_id,
            user_message=question,
            assistant_message=raw_answer,
        )
    except Exception:
        logger.exception("Failed to handle photo message")
        try:
            await status_msg.edit_text(_ERR_GENERIC)
        except Exception:
            await message.reply_text(_ERR_GENERIC)
    finally:
        typing_task.cancel()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            _ = await context.bot.send_message(
                chat_id=update.effective_chat.id, text=_ERR_GENERIC
            )
        except Exception:
            logger.exception("Failed to send error message")
