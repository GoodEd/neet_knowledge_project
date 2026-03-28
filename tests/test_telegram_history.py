# pyright: reportMissingImports=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportAny=false

import json
import os
import sys
from unittest.mock import MagicMock


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_history(mock_redis=None):
    from src.telegram_bot.history import TelegramChatHistory

    history = TelegramChatHistory.__new__(TelegramChatHistory)
    history._redis = mock_redis
    history._max_turns = 4
    history._ttl_seconds = 604800
    return history


def test_load_returns_empty_for_unknown_user():
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    history = _make_history(mock_redis)

    assert history.load_history(1) == []


def test_save_and_load_single_turn():
    storage = {}
    mock_redis = MagicMock()

    def _get(key):
        return storage.get(key)

    def _setex(key, _ttl, value):
        storage[key] = value

    mock_redis.get.side_effect = _get
    mock_redis.setex.side_effect = _setex

    history = _make_history(mock_redis)
    history.save_turn(1, "hello", "hi there")

    assert history.load_history(1) == [("hello", "hi there")]


def test_history_trimmed_to_max_turns():
    storage = {}
    mock_redis = MagicMock()

    def _get(key):
        return storage.get(key)

    def _setex(key, _ttl, value):
        storage[key] = value

    mock_redis.get.side_effect = _get
    mock_redis.setex.side_effect = _setex

    history = _make_history(mock_redis)
    history._max_turns = 2

    for i in range(5):
        history.save_turn(1, f"u{i}", f"a{i}")

    assert history.load_history(1) == [("u3", "a3"), ("u4", "a4")]


def test_different_users_isolated():
    storage = {}
    mock_redis = MagicMock()

    def _get(key):
        return storage.get(key)

    def _setex(key, _ttl, value):
        storage[key] = value

    mock_redis.get.side_effect = _get
    mock_redis.setex.side_effect = _setex

    history = _make_history(mock_redis)
    history.save_turn(1, "u1", "a1")
    history.save_turn(2, "u2", "a2")

    assert history.load_history(1) == [("u1", "a1")]
    assert history.load_history(2) == [("u2", "a2")]


def test_ttl_set_on_save():
    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    history = _make_history(mock_redis)

    history.save_turn(1, "hello", "raw answer")

    mock_redis.setex.assert_called_once()
    key, ttl, payload = mock_redis.setex.call_args.args
    assert key == "telegram_chat:1"
    assert ttl == 604800
    assert json.loads(payload) == [["hello", "raw answer"]]


def test_load_graceful_when_redis_unavailable():
    history = _make_history(None)

    assert history.load_history(1) == []


def test_save_graceful_when_redis_unavailable():
    history = _make_history(None)

    history.save_turn(1, "hello", "hi")
