from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest


def _load_module():
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))
    module = importlib.import_module("scripts.multi_model_review")
    return importlib.reload(module)


def test_load_config_loads_models_and_defaults(tmp_path: Path):
    mod = _load_module()
    config_path = tmp_path / "review.yaml"
    config_path.write_text(
        """
models:
  - id: openai/gpt-4.1
    name: GPT
settings: {}
""".strip()
    )

    config = mod.load_config(str(config_path))

    assert len(config.models) == 1
    assert config.models[0]["id"] == "openai/gpt-4.1"
    assert config.timeout_seconds == 120
    assert config.max_diff_lines == 2000
    assert config.fail_on_critical is True


def test_load_config_raises_for_missing_file(tmp_path: Path):
    mod = _load_module()
    missing = tmp_path / "does-not-exist.yaml"

    with pytest.raises(FileNotFoundError):
        mod.load_config(str(missing))


def test_load_config_raises_when_models_missing(tmp_path: Path):
    mod = _load_module()
    config_path = tmp_path / "review.yaml"
    config_path.write_text("settings: {}")

    with pytest.raises(ValueError, match="at least one model"):
        mod.load_config(str(config_path))


def test_get_diff_returns_explicit_text_as_is():
    mod = _load_module()
    diff = "diff --git a/x.py b/x.py\n+new line\n"

    result = mod.get_diff(
        base=None,
        head="HEAD",
        diff_text=diff,
        max_lines=2000,
    )

    assert result == diff


def test_get_diff_truncates_long_diff_from_text():
    mod = _load_module()
    long_diff = "\n".join(f"line-{idx}" for idx in range(10))

    result = mod.get_diff(
        base=None,
        head="HEAD",
        diff_text=long_diff,
        max_lines=3,
    )

    assert "line-0" in result
    assert "line-2" in result
    assert "line-3" not in result
    assert "truncated" in result.lower()


def test_build_prompt_includes_diff_checklist_and_output_format():
    mod = _load_module()
    prompt = mod.build_prompt("diff --git a/app.py b/app.py")

    assert "diff --git a/app.py b/app.py" in prompt
    assert "Code Quality" in prompt
    assert "Architecture" in prompt
    assert "Testing" in prompt
    assert "Production Readiness" in prompt
    assert "Strengths" in prompt
    assert "Critical" in prompt
    assert "Important" in prompt
    assert "Minor" in prompt
    assert "Assessment" in prompt


def test_merge_reviews_with_partial_failure_and_summary():
    mod = _load_module()
    results = [
        {
            "model": "Claude",
            "content": "## Issues\n### Critical\n- SQL injection",
            "error": None,
        },
        {"model": "Gemini", "content": None, "error": "timeout"},
        {"model": "GPT", "content": "Looks good", "error": None},
    ]

    merged = mod.merge_reviews(results)

    assert "# Multi-Model Code Review" in merged
    assert "queried" in merged.lower()
    assert "responded" in merged.lower()
    assert "failed" in merged.lower()
    assert "## Model: Claude" in merged
    assert "## Model: Gemini" in merged
    assert "**Error:** timeout" in merged
    assert "critical" in merged.lower()


def test_merge_reviews_all_failures():
    mod = _load_module()
    results = [
        {"model": "Claude", "content": None, "error": "http 500"},
        {"model": "Gemini", "content": None, "error": "timeout"},
    ]

    merged = mod.merge_reviews(results)

    assert "responded: 0" in merged.lower()
    assert "failed: 2" in merged.lower()
    assert "**Error:** http 500" in merged
    assert "**Error:** timeout" in merged


def test_format_github_comment_wraps_model_sections_in_details():
    mod = _load_module()
    review = """# Multi-Model Code Review
Summary block

## Model: Claude
Claude body

## Model: Gemini
Gemini body
"""

    formatted = mod.format_github_comment(review)

    assert "<details>" in formatted
    assert "<summary>Model: Claude</summary>" in formatted
    assert "<summary>Model: Gemini</summary>" in formatted
    assert "Claude body" in formatted
    assert "Gemini body" in formatted


class TestCallModel:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_returns_error_when_api_key_missing(self):
        mod = _load_module()

        async def _test():
            async with httpx.AsyncClient() as client:
                return await mod.call_model(client, "test/model", "Test", "prompt", 30)

        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            result = self._run(_test())

        assert result["error"] == "OPENAI_API_KEY not set"
        assert result["content"] is None

    def test_returns_content_on_success(self):
        mod = _load_module()
        response_body = {"choices": [{"message": {"content": "Looks good"}}]}
        mock_request = httpx.Request("POST", "https://fake.api/v1/chat/completions")
        mock_response = httpx.Response(200, json=response_body, request=mock_request)

        async def mock_post(*args, **kwargs):
            return mock_response

        async def _test():
            client = AsyncMock(spec=httpx.AsyncClient)
            client.post = mock_post
            return await mod.call_model(client, "test/model", "Test", "review this", 30)

        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "sk-test-key", "OPENAI_BASE_URL": "https://fake.api/v1"},
            clear=False,
        ):
            result = self._run(_test())

        assert result["error"] is None
        assert result["content"] == "Looks good"
        assert result["model"] == "Test"

    def test_returns_error_on_timeout(self):
        mod = _load_module()

        async def mock_post(*args, **kwargs):
            raise httpx.TimeoutException("timed out")

        async def _test():
            client = AsyncMock(spec=httpx.AsyncClient)
            client.post = mock_post
            return await mod.call_model(client, "test/model", "Test", "review this", 30)

        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "sk-test-key", "OPENAI_BASE_URL": "https://fake.api/v1"},
            clear=False,
        ):
            result = self._run(_test())

        assert "timeout" in result["error"].lower()
        assert result["content"] is None

    def test_returns_error_on_http_error(self):
        mod = _load_module()
        mock_response = httpx.Response(429, text="rate limited")

        async def mock_post(*args, **kwargs):
            raise httpx.HTTPStatusError(
                "rate limited",
                request=httpx.Request("POST", "https://fake.api"),
                response=mock_response,
            )

        async def _test():
            client = AsyncMock(spec=httpx.AsyncClient)
            client.post = mock_post
            return await mod.call_model(client, "test/model", "Test", "review this", 30)

        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "sk-test-key", "OPENAI_BASE_URL": "https://fake.api/v1"},
            clear=False,
        ):
            result = self._run(_test())

        client = AsyncMock(spec=httpx.AsyncClient)
        client.post = mock_post

        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "sk-test-key", "OPENAI_BASE_URL": "https://fake.api/v1"},
            clear=False,
        ):
            result = self._run(
                mod.call_model(client, "test/model", "Test", "review this", 30)
            )

        assert "429" in result["error"]
        assert result["content"] is None
