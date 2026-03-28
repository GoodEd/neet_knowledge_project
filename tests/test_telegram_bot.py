import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_mock_rag(
    answer="The answer is 42",
    sources=None,
    question_sources=None,
    error=None,
    extract_return="QUESTION: test",
):
    rag = MagicMock()
    result = {
        "answer": answer,
        "sources": sources or [],
        "question_sources": question_sources or [],
    }
    if error is not None:
        result["error"] = error

    rag.query_with_history.return_value = result
    rag.llm_manager.extract_image_context.return_value = extract_return
    return rag


def _make_mock_history():
    history = MagicMock()
    history.load_history.return_value = []
    return history


def _make_text_update(text, user_id=123):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = user_id
    update.message.text = text
    update.message.caption = None
    update.message.photo = None
    update.message.reply_text = AsyncMock()
    return update


def _make_photo_update(caption=None, user_id=123):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = user_id
    update.message.text = None
    update.message.caption = caption

    photo_small = MagicMock()
    photo_small.file_id = "small_file_id"
    photo_large = MagicMock()
    photo_large.file_id = "large_file_id"
    update.message.photo = [photo_small, photo_large]

    update.message.reply_text = AsyncMock()
    return update


def _make_context(rag=None, history=None):
    context = MagicMock()
    context.bot_data = {
        "rag": rag or _make_mock_rag(),
        "history": history or _make_mock_history(),
    }
    context.bot.send_chat_action = AsyncMock()

    mock_file = MagicMock()
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake_image"))
    context.bot.get_file = AsyncMock(return_value=mock_file)
    return context


@pytest.mark.asyncio
async def test_start_command_sends_welcome_message():
    from src.telegram_bot.bot import start_command

    update = _make_text_update("/start")
    context = _make_context()

    await start_command(update, context)

    update.message.reply_text.assert_called_once()
    message = update.message.reply_text.call_args.args[0]
    assert "NEET" in message or "PYQ" in message


@pytest.mark.asyncio
async def test_help_command_sends_usage_message():
    from src.telegram_bot.bot import help_command

    update = _make_text_update("/help")
    context = _make_context()

    await help_command(update, context)

    update.message.reply_text.assert_called_once()
    message = update.message.reply_text.call_args.args[0].lower()
    assert "question" in message or "photo" in message


@pytest.mark.asyncio
async def test_handle_message_sends_typing_action():
    from src.telegram_bot.bot import handle_message

    update = _make_text_update("What is osmosis?")
    context = _make_context()

    await handle_message(update, context)

    context.bot.send_chat_action.assert_called()


@pytest.mark.asyncio
async def test_handle_message_calls_rag_with_question_and_session_id():
    from src.telegram_bot.bot import handle_message

    rag = _make_mock_rag()
    update = _make_text_update("What is osmosis?", user_id=456)
    context = _make_context(rag=rag)

    await handle_message(update, context)

    rag.query_with_history.assert_called_once()
    call = rag.query_with_history.call_args
    assert call.args[0] == "What is osmosis?"
    assert call.kwargs["session_id"] == "456"


@pytest.mark.asyncio
async def test_handle_message_reply_uses_html_parse_mode():
    from src.telegram_bot.bot import handle_message

    update = _make_text_update("Explain diffusion")
    context = _make_context()

    await handle_message(update, context)

    kwargs = update.message.reply_text.call_args.kwargs
    assert kwargs.get("parse_mode") == "HTML"


@pytest.mark.asyncio
async def test_handle_message_saves_turn_after_reply():
    from src.telegram_bot.bot import handle_message

    history = _make_mock_history()
    update = _make_text_update("What is osmosis?", user_id=789)
    context = _make_context(history=history)

    await handle_message(update, context)

    history.save_turn.assert_called_once()
    args = history.save_turn.call_args.kwargs
    assert args["user_id"] == 789
    assert args["user_message"] == "What is osmosis?"


@pytest.mark.asyncio
async def test_handle_message_exception_returns_friendly_message_no_stack_trace():
    from src.telegram_bot.bot import handle_message

    rag = _make_mock_rag()
    rag.query_with_history.side_effect = Exception("DB connection failed")
    update = _make_text_update("Test question")
    context = _make_context(rag=rag)

    await handle_message(update, context)

    message = update.message.reply_text.call_args.args[0]
    assert "sorry" in message.lower() or "couldn't" in message.lower()
    assert "DB connection failed" not in message


@pytest.mark.asyncio
async def test_handle_message_error_as_answer_returns_friendly_message_and_not_saved():
    from src.telegram_bot.bot import handle_message

    rag = _make_mock_rag(answer="Error generating answer: timeout")
    history = _make_mock_history()
    update = _make_text_update("Test question")
    context = _make_context(rag=rag, history=history)

    await handle_message(update, context)

    message = update.message.reply_text.call_args.args[0]
    assert "Error generating answer" not in message
    history.save_turn.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_error_key_returns_friendly_message_and_not_saved():
    from src.telegram_bot.bot import handle_message

    rag = _make_mock_rag(
        answer="Knowledge base is empty or unavailable.", error="No vectorstore found"
    )
    history = _make_mock_history()
    update = _make_text_update("Test question")
    context = _make_context(rag=rag, history=history)

    await handle_message(update, context)

    message = update.message.reply_text.call_args.args[0]
    assert "No vectorstore found" not in message
    history.save_turn.assert_not_called()


@pytest.mark.asyncio
async def test_handle_photo_downloads_highest_resolution_photo():
    from src.telegram_bot.bot import handle_photo

    update = _make_photo_update(caption="")
    context = _make_context()

    await handle_photo(update, context)

    context.bot.get_file.assert_called_once_with("large_file_id")


@pytest.mark.asyncio
async def test_handle_photo_calls_extract_image_context():
    from src.telegram_bot.bot import handle_photo

    rag = _make_mock_rag()
    update = _make_photo_update(caption="")
    context = _make_context(rag=rag)

    await handle_photo(update, context)

    rag.llm_manager.extract_image_context.assert_called_once()


@pytest.mark.asyncio
async def test_handle_photo_caption_included_with_extracted_text():
    from src.telegram_bot.bot import handle_photo

    rag = _make_mock_rag(extract_return="QUESTION: velocity problem")
    update = _make_photo_update(caption="Solve this physics problem")
    context = _make_context(rag=rag)

    await handle_photo(update, context)

    query = rag.query_with_history.call_args.args[0]
    assert "Solve this physics problem" in query
    assert "QUESTION: velocity problem" in query


@pytest.mark.asyncio
async def test_handle_photo_without_caption_uses_extracted_text_only():
    from src.telegram_bot.bot import handle_photo

    rag = _make_mock_rag(extract_return="QUESTION: biology cell division")
    update = _make_photo_update(caption=None)
    context = _make_context(rag=rag)

    await handle_photo(update, context)

    query = rag.query_with_history.call_args.args[0]
    assert query == "QUESTION: biology cell division"


@pytest.mark.asyncio
async def test_handle_photo_download_failure_returns_couldnt_download_message():
    from src.telegram_bot.bot import handle_photo

    update = _make_photo_update(caption="")
    context = _make_context()
    context.bot.get_file.side_effect = Exception("Network timeout")

    await handle_photo(update, context)

    message = update.message.reply_text.call_args.args[0]
    assert "couldn't download" in message.lower()
    assert "Network timeout" not in message


@pytest.mark.asyncio
async def test_handle_photo_extraction_failure_returns_couldnt_read_message():
    from src.telegram_bot.bot import handle_photo

    rag = _make_mock_rag()
    rag.llm_manager.extract_image_context.side_effect = Exception("Vision API down")
    update = _make_photo_update(caption="")
    context = _make_context(rag=rag)

    await handle_photo(update, context)

    message = update.message.reply_text.call_args.args[0]
    assert "couldn't read" in message.lower()
    assert "Vision API" not in message


@pytest.mark.asyncio
async def test_history_boundary_saves_raw_answer_not_formatted_html():
    from src.telegram_bot.bot import handle_message

    rag = _make_mock_rag(answer="The answer has H<sub>2</sub>O and 10<sup>2</sup>")
    history = _make_mock_history()
    update = _make_text_update("What is water?", user_id=42)
    context = _make_context(rag=rag, history=history)

    await handle_message(update, context)

    save_call = history.save_turn.call_args.kwargs
    saved_answer = save_call["assistant_message"]
    assert saved_answer == "The answer has H<sub>2</sub>O and 10<sup>2</sup>"

    reply_text = update.message.reply_text.call_args.args[0]
    assert "<sub>" not in reply_text
    assert "₂" in reply_text
