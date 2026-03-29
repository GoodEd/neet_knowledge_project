from __future__ import annotations

import importlib
import sys
from pathlib import Path

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
