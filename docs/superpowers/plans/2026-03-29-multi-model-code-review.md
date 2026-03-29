# Multi-Model Code Review System — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-model code review system where 3 trigger points (OpenCode skill, GitHub Actions, git pre-push hook) share one config (`.multi-review.yaml`) that lists reviewer models. Each trigger reads the config, gets the git diff, calls all models in parallel via OpenRouter, and outputs a structured review report.

**Architecture:** Single Python engine (`scripts/multi_model_review.py`) does all the work — reads YAML config, collects git diff, fans out to N models via `asyncio`+`httpx`, and formats output. Three thin triggers (CI workflow, git hook, OpenCode skill) invoke the engine with context-appropriate defaults. Models are added/removed by editing the YAML — no code changes needed.

**Tech Stack:** Python 3.11, httpx (async HTTP), PyYAML, asyncio, OpenRouter API (OpenAI-compatible)

---

## File Structure

| File | Responsibility |
|------|----------------|
| `.multi-review.yaml` | Config: model list, timeouts, settings. Single source of truth for which models review code. |
| `scripts/multi_model_review.py` | Core engine: config parsing, diff collection, parallel API calls, output formatting. CLI interface via argparse. |
| `tests/test_multi_model_review.py` | Unit tests for config loading, prompt building, response merging, output formatting. |
| `.github/workflows/multi-review.yml` | CI trigger: runs engine on PRs, posts merged review as PR comment. |
| `.githooks/pre-push` | Git hook trigger: runs engine before push, blocks on critical issues. |
| `.opencode/skills/multi-model-review/SKILL.md` | OpenCode skill trigger: in-session review with interactive output. |

---

## Chunk 1: Config + Core Engine

### Task 1: Config File

**Files:**
- Create: `.multi-review.yaml`

- [ ] **Step 1: Create the config file**

```yaml
# Multi-Model Code Review Configuration
# Add/remove models by editing this file — no code changes needed.
#
# Each model must use an OpenRouter model ID.
# Browse models: https://openrouter.ai/models

models:
  - id: anthropic/claude-sonnet-4-5
    name: Claude Sonnet
  - id: google/gemini-2.5-pro-preview-05-06
    name: Gemini Pro
  - id: openai/gpt-4.1
    name: GPT-4.1

settings:
  # Seconds to wait for each model response
  timeout_seconds: 120
  # Truncate diffs longer than this (lines)
  max_diff_lines: 2000
  # Exit non-zero if any model reports Critical issues (used by pre-push hook)
  fail_on_critical: true
```

- [ ] **Step 2: Commit**

```bash
git add .multi-review.yaml
git commit -m "feat: add multi-model review config"
```

---

### Task 2: Engine — Config Loader + Diff Collector

**Files:**
- Create: `scripts/multi_model_review.py`
- Create: `tests/test_multi_model_review.py`

- [ ] **Step 1: Write failing tests for config loading and diff collection**

```python
# tests/test_multi_model_review.py
"""Tests for multi-model code review engine."""
import os
import sys
import tempfile
import textwrap

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.multi_model_review import (
    ReviewConfig,
    load_config,
    get_diff,
    build_prompt,
    merge_reviews,
    format_terminal,
    format_github_comment,
)


class TestLoadConfig:
    def test_loads_models_from_yaml(self, tmp_path):
        cfg_file = tmp_path / ".multi-review.yaml"
        cfg_file.write_text(textwrap.dedent("""\
            models:
              - id: anthropic/claude-sonnet-4-5
                name: Claude
              - id: openai/gpt-4.1
                name: GPT
            settings:
              timeout_seconds: 60
              max_diff_lines: 1000
              fail_on_critical: false
        """))
        config = load_config(str(cfg_file))
        assert len(config.models) == 2
        assert config.models[0]["id"] == "anthropic/claude-sonnet-4-5"
        assert config.timeout_seconds == 60
        assert config.fail_on_critical is False

    def test_defaults_when_settings_missing(self, tmp_path):
        cfg_file = tmp_path / ".multi-review.yaml"
        cfg_file.write_text(textwrap.dedent("""\
            models:
              - id: anthropic/claude-sonnet-4-5
                name: Claude
        """))
        config = load_config(str(cfg_file))
        assert config.timeout_seconds == 120
        assert config.max_diff_lines == 2000
        assert config.fail_on_critical is True

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/.multi-review.yaml")

    def test_raises_on_no_models(self, tmp_path):
        cfg_file = tmp_path / ".multi-review.yaml"
        cfg_file.write_text("models: []")
        with pytest.raises(ValueError, match="at least one model"):
            load_config(str(cfg_file))


class TestGetDiff:
    def test_returns_diff_string(self, tmp_path):
        """get_diff with explicit diff text should return it as-is."""
        diff_text = "+added line\n-removed line"
        result = get_diff(diff_text=diff_text)
        assert "+added line" in result

    def test_truncates_long_diff(self, tmp_path):
        long_diff = "\n".join(f"+line {i}" for i in range(3000))
        result = get_diff(diff_text=long_diff, max_lines=100)
        lines = result.strip().split("\n")
        # Should be truncated with a notice
        assert len(lines) <= 105  # 100 + truncation notice


class TestBuildPrompt:
    def test_includes_diff_in_prompt(self):
        diff = "+new code\n-old code"
        prompt = build_prompt(diff)
        assert "+new code" in prompt
        assert "Code Quality" in prompt  # checklist present
        assert "Critical" in prompt  # output format present

    def test_includes_review_checklist(self):
        prompt = build_prompt("some diff")
        assert "separation of concerns" in prompt.lower() or "error handling" in prompt.lower()
        assert "Strengths" in prompt
        assert "Assessment" in prompt


class TestMergeReviews:
    def test_merges_multiple_model_results(self):
        results = [
            {"model": "Claude", "content": "Looks good", "error": None},
            {"model": "GPT", "content": "Found issues", "error": None},
        ]
        merged = merge_reviews(results)
        assert "Claude" in merged
        assert "GPT" in merged
        assert "Looks good" in merged
        assert "Found issues" in merged

    def test_handles_partial_failures(self):
        results = [
            {"model": "Claude", "content": "Review text", "error": None},
            {"model": "GPT", "content": None, "error": "timeout"},
        ]
        merged = merge_reviews(results)
        assert "Claude" in merged
        assert "GPT" in merged
        assert "timeout" in merged.lower() or "error" in merged.lower()

    def test_all_failures(self):
        results = [
            {"model": "Claude", "content": None, "error": "rate limited"},
        ]
        merged = merge_reviews(results)
        assert "error" in merged.lower() or "fail" in merged.lower()


class TestFormatOutput:
    def test_terminal_format(self):
        review = "## Model: Claude\nLooks good\n## Model: GPT\nAlso good"
        output = format_terminal(review)
        assert "Claude" in output
        assert "GPT" in output

    def test_github_comment_format(self):
        review = "## Model: Claude\nLooks good"
        output = format_github_comment(review)
        assert "Multi-Model Code Review" in output
        assert "<details>" in output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_multi_model_review.py -v`
Expected: FAIL — `ModuleNotFoundError` (script doesn't exist yet)

- [ ] **Step 3: Create engine scaffold with config loader and diff collector**

```python
#!/usr/bin/env python3
"""Multi-model code review engine.

Reads .multi-review.yaml, gets git diff, calls N models in parallel via
OpenRouter, and outputs a merged review report.

Usage:
    # Review staged changes:
    python scripts/multi_model_review.py

    # Review branch diff against main:
    python scripts/multi_model_review.py --base origin/main --head HEAD

    # Output as GitHub PR comment:
    python scripts/multi_model_review.py --base origin/main --format github-comment

    # Use custom config:
    python scripts/multi_model_review.py --config path/to/.multi-review.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from typing import Any

import httpx
import yaml


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class ReviewConfig:
    """Parsed .multi-review.yaml."""
    models: list[dict[str, str]]
    timeout_seconds: int = 120
    max_diff_lines: int = 2000
    fail_on_critical: bool = True


def load_config(path: str) -> ReviewConfig:
    """Load and validate review config from YAML file."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Config not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    models = raw.get("models") or []
    if not models:
        raise ValueError("Config must define at least one model in 'models' list")

    settings = raw.get("settings") or {}
    return ReviewConfig(
        models=models,
        timeout_seconds=settings.get("timeout_seconds", 120),
        max_diff_lines=settings.get("max_diff_lines", 2000),
        fail_on_critical=settings.get("fail_on_critical", True),
    )


# ---------------------------------------------------------------------------
# Diff collection
# ---------------------------------------------------------------------------

def get_diff(
    *,
    base: str | None = None,
    head: str | None = None,
    diff_text: str | None = None,
    max_lines: int = 2000,
) -> str:
    """Get git diff, either from explicit text or by running git.

    Priority: diff_text > base..head > staged changes > working tree.
    """
    if diff_text is not None:
        raw = diff_text
    elif base:
        head = head or "HEAD"
        result = subprocess.run(
            ["git", "diff", f"{base}...{head}"],
            capture_output=True, text=True, check=True,
        )
        raw = result.stdout
    else:
        # Try staged first, fall back to working tree
        result = subprocess.run(
            ["git", "diff", "--cached"],
            capture_output=True, text=True, check=True,
        )
        raw = result.stdout
        if not raw.strip():
            result = subprocess.run(
                ["git", "diff"],
                capture_output=True, text=True, check=True,
            )
            raw = result.stdout

    if not raw.strip():
        return ""

    lines = raw.split("\n")
    if len(lines) > max_lines:
        truncated = lines[:max_lines]
        truncated.append(
            f"\n... (truncated: {len(lines)} total lines, showing first {max_lines})"
        )
        return "\n".join(truncated)

    return raw
```

- [ ] **Step 4: Run config + diff tests to verify they pass**

Run: `pytest tests/test_multi_model_review.py::TestLoadConfig tests/test_multi_model_review.py::TestGetDiff -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/multi_model_review.py tests/test_multi_model_review.py
git commit -m "feat: multi-model review engine scaffold with config + diff"
```

---

### Task 3: Engine — Prompt Builder + Parallel API Calls + Merging

**Files:**
- Modify: `scripts/multi_model_review.py`

- [ ] **Step 1: Add the review prompt builder**

Add to `scripts/multi_model_review.py` after the diff section:

```python
# ---------------------------------------------------------------------------
# Review prompt (matches requesting-code-review/code-reviewer.md structure)
# ---------------------------------------------------------------------------

REVIEW_SYSTEM_PROMPT = """\
You are a senior code reviewer evaluating a git diff for production readiness. \
Be specific: reference file names and line numbers from the diff. \
Categorize issues by actual severity — not everything is Critical."""

REVIEW_USER_TEMPLATE = """\
Review the following code changes.

## Review Checklist

**Code Quality:**
- Clean separation of concerns?
- Proper error handling?
- Type safety (if applicable)?
- DRY principle followed?
- Edge cases handled?

**Architecture:**
- Sound design decisions?
- Scalability considerations?
- Performance implications?
- Security concerns?

**Testing:**
- Tests actually test logic (not just mocks)?
- Edge cases covered?
- Integration tests where needed?

**Production Readiness:**
- Backward compatibility?
- Breaking changes documented?
- No obvious bugs?

## Required Output Format

### Strengths
[What's well done? Be specific with file:line references.]

### Issues

#### Critical (Must Fix)
[Bugs, security issues, data loss risks, broken functionality]

#### Important (Should Fix)
[Architecture problems, missing error handling, test gaps]

#### Minor (Nice to Have)
[Code style, optimization, documentation improvements]

For each issue: file:line reference, what's wrong, why it matters.

### Assessment
**Ready to merge?** [Yes / No / With fixes]
**Reasoning:** [1-2 sentences]

---

## Code Changes (git diff)

```diff
{diff}
```"""


def build_prompt(diff: str) -> str:
    """Build the review prompt with the diff embedded."""
    return REVIEW_USER_TEMPLATE.replace("{diff}", diff)
```

- [ ] **Step 2: Add parallel API caller**

```python
# ---------------------------------------------------------------------------
# Parallel API calls
# ---------------------------------------------------------------------------

async def call_model(
    client: httpx.AsyncClient,
    model_id: str,
    model_name: str,
    prompt: str,
    timeout: int,
) -> dict[str, Any]:
    """Call a single model via OpenRouter. Returns dict with model/content/error."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")

    if not api_key:
        return {"model": model_name, "content": None, "error": "OPENAI_API_KEY not set"}

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/neet-knowledge-project",
        "X-Title": "Multi-Model Code Review",
    }
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }

    try:
        resp = await client.post(
            url, headers=headers, json=payload,
            timeout=httpx.Timeout(float(timeout)),
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return {"model": model_name, "content": content, "error": None}
    except httpx.TimeoutException:
        return {"model": model_name, "content": None, "error": f"Timeout after {timeout}s"}
    except httpx.HTTPStatusError as e:
        return {"model": model_name, "content": None, "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"model": model_name, "content": None, "error": str(e)}


async def call_all_models(
    config: ReviewConfig,
    prompt: str,
) -> list[dict[str, Any]]:
    """Fan out review to all configured models in parallel."""
    async with httpx.AsyncClient() as client:
        tasks = [
            call_model(
                client=client,
                model_id=m["id"],
                model_name=m.get("name", m["id"]),
                prompt=prompt,
                timeout=config.timeout_seconds,
            )
            for m in config.models
        ]
        return await asyncio.gather(*tasks)
```

- [ ] **Step 3: Add response merging and output formatting**

```python
# ---------------------------------------------------------------------------
# Merge + format
# ---------------------------------------------------------------------------

def merge_reviews(results: list[dict[str, Any]]) -> str:
    """Merge individual model reviews into a single report."""
    sections: list[str] = []
    success_count = 0
    critical_found = False

    for r in results:
        name = r["model"]
        if r["error"]:
            sections.append(f"## Model: {name}\n\n**Error:** {r['error']}\n")
        else:
            sections.append(f"## Model: {name}\n\n{r['content']}\n")
            success_count += 1
            if r["content"] and "critical" in r["content"].lower():
                # Heuristic: check if Critical section has actual content
                content = r["content"]
                crit_idx = content.lower().find("critical")
                if crit_idx != -1:
                    after_crit = content[crit_idx:crit_idx + 200]
                    # If there's content after "Critical" beyond just the header
                    lines_after = [
                        l.strip() for l in after_crit.split("\n")[1:5]
                        if l.strip() and l.strip() not in ("", "None", "N/A", "-")
                    ]
                    if lines_after:
                        critical_found = True

    summary_parts = [
        f"**{len(results)} models queried** | "
        f"**{success_count} responded** | "
        f"**{len(results) - success_count} failed**",
    ]
    if critical_found:
        summary_parts.append("**Critical issues detected**")

    header = "# Multi-Model Code Review\n\n" + " | ".join(summary_parts) + "\n\n---\n\n"
    return header + "\n---\n\n".join(sections)


def format_terminal(review: str) -> str:
    """Format for terminal output (pass-through, review is already markdown)."""
    return review


def format_github_comment(review: str) -> str:
    """Format as a GitHub PR comment with collapsible model sections."""
    # Parse the merged review and wrap each model section in <details>
    lines = review.split("\n")
    output: list[str] = []
    in_model_section = False
    current_model = ""

    for line in lines:
        if line.startswith("## Model: "):
            if in_model_section:
                output.append("</details>\n")
            current_model = line.replace("## Model: ", "")
            output.append(f"<details>\n<summary><b>{current_model}</b></summary>\n")
            in_model_section = True
        elif line.startswith("# Multi-Model Code Review"):
            output.append(line)
        else:
            output.append(line)

    if in_model_section:
        output.append("</details>")

    return "\n".join(output)


def has_critical_issues(results: list[dict[str, Any]]) -> bool:
    """Check if any model reported critical issues (for exit code)."""
    for r in results:
        if r.get("content") and "critical" in r["content"].lower():
            content = r["content"]
            crit_idx = content.lower().find("critical")
            if crit_idx != -1:
                after_crit = content[crit_idx:crit_idx + 200]
                lines_after = [
                    l.strip() for l in after_crit.split("\n")[1:5]
                    if l.strip() and l.strip() not in ("", "None", "N/A", "-")
                ]
                if lines_after:
                    return True
    return False
```

- [ ] **Step 4: Run all engine tests**

Run: `pytest tests/test_multi_model_review.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/multi_model_review.py tests/test_multi_model_review.py
git commit -m "feat: multi-model review prompt builder, parallel API caller, merger"
```

---

### Task 4: CLI Interface

**Files:**
- Modify: `scripts/multi_model_review.py`

- [ ] **Step 1: Add argparse CLI and main entry point**

Add to the bottom of `scripts/multi_model_review.py`:

```python
# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def find_config() -> str:
    """Walk up from cwd to find .multi-review.yaml."""
    d = os.getcwd()
    while True:
        candidate = os.path.join(d, ".multi-review.yaml")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    raise FileNotFoundError(
        "No .multi-review.yaml found (searched from cwd to filesystem root)"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Multi-model code review via OpenRouter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              %(prog)s                          # review staged/working changes
              %(prog)s --base origin/main        # review branch diff vs main
              %(prog)s --base HEAD~3 --head HEAD # review last 3 commits
              %(prog)s --format github-comment   # output as PR comment
        """),
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to .multi-review.yaml (default: auto-detect)",
    )
    parser.add_argument(
        "--base", default=None,
        help="Base git ref for diff (e.g., origin/main, HEAD~3)",
    )
    parser.add_argument(
        "--head", default="HEAD",
        help="Head git ref for diff (default: HEAD)",
    )
    parser.add_argument(
        "--format", dest="output_format", default="terminal",
        choices=["terminal", "github-comment", "json"],
        help="Output format (default: terminal)",
    )
    parser.add_argument(
        "--diff-stdin", action="store_true",
        help="Read diff from stdin instead of running git",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 on success, 1 if critical issues found."""
    args = parse_args(argv)

    # Load config
    config_path = args.config or find_config()
    print(f"Config: {config_path}", file=sys.stderr)
    config = load_config(config_path)
    print(
        f"Models: {', '.join(m.get('name', m['id']) for m in config.models)}",
        file=sys.stderr,
    )

    # Collect diff
    if args.diff_stdin:
        diff = sys.stdin.read()
    else:
        diff = get_diff(base=args.base, head=args.head, max_lines=config.max_diff_lines)

    if not diff.strip():
        print("No changes to review.", file=sys.stderr)
        return 0

    diff_lines = len(diff.split("\n"))
    print(f"Diff: {diff_lines} lines", file=sys.stderr)

    # Build prompt
    prompt = build_prompt(diff)

    # Call models
    print("Calling models...", file=sys.stderr)
    results = asyncio.run(call_all_models(config, prompt))

    # Merge reviews
    merged = merge_reviews(results)

    # Format output
    if args.output_format == "github-comment":
        output = format_github_comment(merged)
    elif args.output_format == "json":
        output = json.dumps(
            {"review": merged, "results": results, "has_critical": has_critical_issues(results)},
            indent=2,
        )
    else:
        output = format_terminal(merged)

    print(output)

    # Exit code
    if config.fail_on_critical and has_critical_issues(results):
        print("\nCritical issues found — review above.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify script runs with --help**

Run: `python scripts/multi_model_review.py --help`
Expected: Usage info printed, exit 0

- [ ] **Step 3: Commit**

```bash
git add scripts/multi_model_review.py
git commit -m "feat: multi-model review CLI interface"
```

---

## Chunk 2: Trigger Points

### Task 5: GitHub Actions Workflow

**Files:**
- Create: `.github/workflows/multi-review.yml`

- [ ] **Step 1: Create the workflow**

```yaml
name: Multi-Model Code Review

on:
  pull_request:
    branches: [main]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    # Skip if PR only changes non-code files
    if: >-
      !contains(github.event.pull_request.title, '[skip-review]')
    
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Full history for accurate diff

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: review-pip-${{ hashFiles('requirements.txt') }}
          restore-keys: review-pip-

      - name: Install dependencies
        run: pip install httpx pyyaml

      - name: Run multi-model review
        id: review
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          OPENAI_BASE_URL: ${{ secrets.OPENAI_BASE_URL }}
        run: |
          python scripts/multi_model_review.py \
            --base origin/${{ github.base_ref }} \
            --head HEAD \
            --format github-comment \
            > review_output.md 2> review_stderr.txt || true
          echo "stderr<<EOF" >> "$GITHUB_OUTPUT"
          cat review_stderr.txt >> "$GITHUB_OUTPUT"
          echo "EOF" >> "$GITHUB_OUTPUT"

      - name: Post or update PR comment
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const body = fs.readFileSync('review_output.md', 'utf8');
            if (!body.trim()) {
              console.log('No review output — skipping comment.');
              return;
            }

            const marker = '<!-- multi-model-review -->';
            const fullBody = `${marker}\n${body}`;

            // Find existing comment
            const { data: comments } = await github.rest.issues.listComments({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
            });
            const existing = comments.find(c => c.body.includes(marker));

            if (existing) {
              await github.rest.issues.updateComment({
                owner: context.repo.owner,
                repo: context.repo.repo,
                comment_id: existing.id,
                body: fullBody,
              });
              console.log(`Updated comment ${existing.id}`);
            } else {
              await github.rest.issues.createComment({
                owner: context.repo.owner,
                repo: context.repo.repo,
                issue_number: context.issue.number,
                body: fullBody,
              });
              console.log('Created new review comment');
            }
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/multi-review.yml
git commit -m "ci: add multi-model code review workflow for PRs"
```

---

### Task 6: Git Pre-Push Hook

**Files:**
- Create: `.githooks/pre-push`

- [ ] **Step 1: Create the hook**

```bash
#!/usr/bin/env bash
# Multi-model code review — pre-push hook
#
# Install:
#   git config core.hooksPath .githooks
#
# Skip for a single push:
#   git push --no-verify
#
# Disable permanently:
#   git config --unset core.hooksPath
set -euo pipefail

# --- Guard: skip if no API key ---
if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "[multi-review] OPENAI_API_KEY not set — skipping review"
    exit 0
fi

# --- Guard: skip if config missing ---
if [ ! -f ".multi-review.yaml" ]; then
    echo "[multi-review] .multi-review.yaml not found — skipping review"
    exit 0
fi

# --- Guard: skip if engine missing ---
if [ ! -f "scripts/multi_model_review.py" ]; then
    echo "[multi-review] scripts/multi_model_review.py not found — skipping review"
    exit 0
fi

# --- Determine what we're pushing ---
# Read push info from stdin (provided by git)
while read -r local_ref local_oid remote_ref remote_oid; do
    # Skip delete pushes
    if [ "$local_oid" = "0000000000000000000000000000000000000000" ]; then
        continue
    fi

    # If remote branch exists, diff against it; otherwise diff against main
    if [ "$remote_oid" = "0000000000000000000000000000000000000000" ]; then
        base="origin/main"
    else
        base="$remote_oid"
    fi

    echo "[multi-review] Reviewing changes: ${base}..${local_oid}"
    echo ""

    # Run the review engine
    if ! python scripts/multi_model_review.py --base "$base" --head "$local_oid"; then
        echo ""
        echo "[multi-review] Critical issues found. Push blocked."
        echo "[multi-review] Fix the issues above, or skip with: git push --no-verify"
        exit 1
    fi
done

exit 0
```

- [ ] **Step 2: Make executable**

```bash
chmod +x .githooks/pre-push
```

- [ ] **Step 3: Commit**

```bash
git add .githooks/pre-push
git commit -m "feat: add pre-push hook for multi-model code review"
```

---

### Task 7: OpenCode Skill

**Files:**
- Create: `.opencode/skills/multi-model-review/SKILL.md`

- [ ] **Step 1: Create skill directory and SKILL.md**

```markdown
---
name: multi-model-review
description: Run multi-model code review on current changes — fans out to N LLM models in parallel via OpenRouter and merges findings
---

# Multi-Model Code Review

Run code review with multiple LLM models simultaneously. Each model independently reviews your changes, and results are merged into a single report.

**When to use:**
- Before creating a PR
- After completing a feature branch
- When you want diverse perspectives on code quality

## Prerequisites

- `OPENAI_API_KEY` env var set (OpenRouter key)
- `.multi-review.yaml` in project root (defines which models to use)
- Python 3.11+ with `httpx` and `pyyaml` installed

## How to Run

### Option 1: Review branch vs main (most common)

```bash
python scripts/multi_model_review.py --base origin/main
```

### Option 2: Review staged changes

```bash
python scripts/multi_model_review.py
```

### Option 3: Review last N commits

```bash
python scripts/multi_model_review.py --base HEAD~3 --head HEAD
```

### Option 4: Output as JSON (for programmatic use)

```bash
python scripts/multi_model_review.py --base origin/main --format json
```

## Managing Models

Edit `.multi-review.yaml` to add/remove reviewer models:

```yaml
models:
  - id: anthropic/claude-sonnet-4-5
    name: Claude Sonnet
  - id: google/gemini-2.5-pro-preview-05-06
    name: Gemini Pro
  # Add a new model — no code changes needed:
  - id: deepseek/deepseek-r1
    name: DeepSeek R1
```

Browse available models: https://openrouter.ai/models

## What the Review Covers

Each model evaluates against this checklist:
- **Code Quality:** Separation of concerns, error handling, type safety, DRY, edge cases
- **Architecture:** Design decisions, scalability, performance, security
- **Testing:** Real tests (not just mocks), edge cases, integration tests
- **Production Readiness:** Backward compatibility, breaking changes, bugs

## Output Format

Each model produces:
- **Strengths** — What's well done
- **Issues** — Categorized as Critical / Important / Minor with file:line references
- **Assessment** — Merge readiness verdict (Yes / No / With fixes)

## Integration Points

This review engine is triggered from three places:

| Trigger | When | Behavior |
|---------|------|----------|
| This skill | Manually in-session | Interactive terminal output |
| GitHub Actions | On PR to main | Posts PR comment (auto-updates) |
| Pre-push hook | Before `git push` | Blocks push if Critical issues found |

### Setting up the pre-push hook

```bash
git config core.hooksPath .githooks
```

To skip for one push: `git push --no-verify`

## Troubleshooting

- **"OPENAI_API_KEY not set"** — Export your OpenRouter key: `export OPENAI_API_KEY=sk-or-v1-...`
- **Timeouts** — Increase `timeout_seconds` in `.multi-review.yaml`
- **Rate limits** — Remove a model from the config, or add delays between calls
- **Empty diff** — Make sure you have uncommitted/committed changes relative to the base ref
```

- [ ] **Step 2: Commit**

```bash
git add .opencode/skills/multi-model-review/SKILL.md
git commit -m "feat: add multi-model-review OpenCode skill"
```

---

## Chunk 3: Polish + Verification

### Task 8: Documentation and Final Wiring

**Files:**
- Modify: `.env.example` (add note about review usage)
- Verify: all components work end-to-end

- [ ] **Step 1: Add review note to .env.example**

Add after the existing OPENAI_API_KEY comments:

```
# Also used by: scripts/multi_model_review.py (multi-model code review)
```

- [ ] **Step 2: Verify config auto-detection works**

```bash
# From project root
python scripts/multi_model_review.py --help
```
Expected: Help text with usage examples

- [ ] **Step 3: Verify hook is executable and well-formed**

```bash
bash -n .githooks/pre-push && echo "Syntax OK"
```
Expected: "Syntax OK"

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/test_multi_model_review.py -v
```
Expected: ALL PASS

- [ ] **Step 5: Final commit**

```bash
git add .env.example
git commit -m "docs: note multi-model review in env example"
```
