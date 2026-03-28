import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.test_telegram_bot import (
    _make_context,
    _make_mock_history,
    _make_mock_rag,
    _make_photo_update,
    _make_text_update,
)


class TestTextEndToEnd:
    @pytest.mark.asyncio
    async def test_text_question_returns_formatted_html_with_sources(self):
        from src.telegram_bot.bot import handle_message

        rag = _make_mock_rag(
            answer="Mitosis creates two identical daughter cells.",
            sources=[
                {
                    "title": "Cell Division Lecture",
                    "url": "https://www.youtube.com/watch?v=abc123",
                    "timestamp": "01:30",
                }
            ],
            question_sources=[
                {
                    "id": 101,
                    "question": "Which phase includes chromosome alignment?",
                }
            ],
        )
        update = _make_text_update("What is mitosis?")
        context = _make_context(rag=rag)

        await handle_message(update, context)

        update.message.reply_text.assert_called_once()
        reply = update.message.reply_text.call_args.args[0]
        kwargs = update.message.reply_text.call_args.kwargs

        assert kwargs.get("parse_mode") == "HTML"
        assert "<b>YouTube Sources</b>" in reply
        assert "https://www.youtube.com/watch?v=abc123&amp;t=90" in reply
        assert "<b>Related Questions</b>" in reply
        assert "https://neetprep.com/epubQuestion/101" in reply


class TestPhotoEndToEnd:
    @pytest.mark.asyncio
    async def test_photo_extracts_queries_and_replies_with_answer(self):
        from src.telegram_bot.bot import handle_photo

        rag = _make_mock_rag(
            answer="The block accelerates downward due to gravity.",
            extract_return="QUESTION: A 2kg block is dropped from rest.",
        )
        update = _make_photo_update(caption="Solve this physics problem")
        context = _make_context(rag=rag)

        await handle_photo(update, context)

        rag.llm_manager.extract_image_context.assert_called_once()
        query = rag.query_with_history.call_args.args[0]
        assert "Solve this physics problem" in query
        assert "A 2kg block is dropped from rest" in query

        reply = update.message.reply_text.call_args.args[0]
        kwargs = update.message.reply_text.call_args.kwargs
        assert "accelerates downward" in reply
        assert kwargs.get("parse_mode") == "HTML"


class TestConversationContinuity:
    @pytest.mark.asyncio
    async def test_second_message_receives_history_from_first_message(self):
        from src.telegram_bot.bot import handle_message

        history_store: list[tuple[str, str]] = []
        history = MagicMock()

        def load_history(_user_id):
            return list(history_store)

        def save_turn(user_id, user_message, assistant_message):
            _ = user_id
            history_store.append((user_message, assistant_message))

        history.load_history.side_effect = load_history
        history.save_turn.side_effect = save_turn

        rag = _make_mock_rag(
            answer="Osmosis is water movement across a semipermeable membrane."
        )
        context = _make_context(rag=rag, history=history)

        update1 = _make_text_update("What is osmosis?", user_id=100)
        await handle_message(update1, context)

        rag.query_with_history.return_value = {
            "answer": "Diffusion needs no membrane boundary.",
            "sources": [],
            "question_sources": [],
        }
        update2 = _make_text_update("How is it different from diffusion?", user_id=100)
        await handle_message(update2, context)

        second_call = rag.query_with_history.call_args_list[1]
        chat_history = second_call.kwargs["chat_history"]
        assert len(chat_history) == 1
        assert chat_history[0][0] == "What is osmosis?"
        assert "water movement" in chat_history[0][1]


class TestErrorRecovery:
    @pytest.mark.asyncio
    async def test_rag_failure_on_first_message_recovers_on_second(self):
        from src.telegram_bot.bot import handle_message

        rag = _make_mock_rag()
        rag.query_with_history.side_effect = [
            Exception("temporary backend failure"),
            {
                "answer": "Recovered answer after retry path.",
                "sources": [],
                "question_sources": [],
            },
        ]

        history = _make_mock_history()
        update1 = _make_text_update("msg1")
        update2 = _make_text_update("msg2")
        context = _make_context(rag=rag, history=history)

        await handle_message(update1, context)
        first_reply = update1.message.reply_text.call_args.args[0]
        assert "sorry" in first_reply.lower() or "couldn't" in first_reply.lower()

        await handle_message(update2, context)
        second_reply = update2.message.reply_text.call_args.args[0]
        assert "Recovered answer" in second_reply

        assert history.save_turn.call_count == 1
        assert history.save_turn.call_args.kwargs["user_message"] == "msg2"


class TestEmptyKnowledgeBase:
    @pytest.mark.asyncio
    async def test_no_relevant_information_reply_is_handled_gracefully(self):
        from src.telegram_bot.bot import handle_message

        rag = _make_mock_rag(answer="No relevant information found.")
        update = _make_text_update("What is dark matter?")
        context = _make_context(rag=rag)

        await handle_message(update, context)

        reply = update.message.reply_text.call_args.args[0]
        kwargs = update.message.reply_text.call_args.kwargs
        assert "No relevant information found." in reply
        assert kwargs.get("parse_mode") == "HTML"
