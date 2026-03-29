#!/usr/bin/env python3
from __future__ import annotations

"""Run multi-model code review over a git diff.

Usage:
    python scripts/multi_model_review.py
    python scripts/multi_model_review.py --base origin/main --head HEAD
    git diff --staged | python scripts/multi_model_review.py --diff-stdin --format github-comment
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

try:
    import yaml
except ImportError:
    print("PyYAML is required: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


@dataclass
class ReviewConfig:
    models: list[dict[str, str]]
    timeout_seconds: int = 120
    max_diff_lines: int = 2000
    fail_on_critical: bool = True


REVIEW_SYSTEM_PROMPT = (
    "You are a senior code reviewer evaluating a git diff for production readiness. "
    "Be specific: reference file names and line numbers from the diff. "
    "Categorize issues by actual severity — not everything is Critical."
)

REVIEW_USER_TEMPLATE = """Review the following git diff.

<diff>
{diff}
</diff>

Use this checklist:

## Code Quality
- correctness and bug risks
- readability and maintainability
- security and data safety

## Architecture
- separation of concerns and coupling
- API/contracts and backward compatibility
- performance implications

## Testing
- test coverage for new/changed behavior
- missing edge cases/regressions
- determinism and reliability

## Production Readiness
- observability/logging
- error handling and rollback safety
- configuration and operational risk

Required output format:

## Strengths
- concrete positives found in this diff

## Issues
### Critical
- list only release-blocking issues (or "None")

### Important
- list significant non-blocking issues (or "None")

### Minor
- list nits/cleanup opportunities (or "None")

## Assessment
- merge readiness verdict (Ready / Needs Changes / Blocked)
- short rationale
"""


def load_config(path: str) -> ReviewConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = cast(dict[str, Any], yaml.safe_load(config_path.read_text()) or {})
    models = cast(list[dict[str, str]], raw.get("models") or [])
    if not models:
        raise ValueError("Config must define at least one model")

    settings = cast(dict[str, Any], raw.get("settings") or {})
    return ReviewConfig(
        models=models,
        timeout_seconds=int(settings.get("timeout_seconds", 120)),
        max_diff_lines=int(settings.get("max_diff_lines", 2000)),
        fail_on_critical=bool(settings.get("fail_on_critical", True)),
    )


def _run_git_diff(args: list[str]) -> str:
    proc = subprocess.run(args, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "Failed to collect git diff")
    return proc.stdout


def _truncate_diff(diff: str, max_lines: int) -> str:
    if max_lines <= 0:
        return diff

    lines = diff.splitlines()
    if len(lines) <= max_lines:
        return diff

    visible = "\n".join(lines[:max_lines])
    omitted = len(lines) - max_lines
    return f"{visible}\n\n[... diff truncated: {omitted} lines omitted ...]"


def get_diff(
    *, base: str | None, head: str | None, diff_text: str | None, max_lines: int
) -> str:
    if diff_text is not None:
        return _truncate_diff(diff_text, max_lines)

    if base:
        end_ref = head or "HEAD"
        diff = _run_git_diff(["git", "diff", f"{base}..{end_ref}"])
        return _truncate_diff(diff, max_lines)

    staged = _run_git_diff(["git", "diff", "--cached"])
    if staged.strip():
        return _truncate_diff(staged, max_lines)

    working_tree = _run_git_diff(["git", "diff"])
    return _truncate_diff(working_tree, max_lines)


def build_prompt(diff: str) -> str:
    return REVIEW_USER_TEMPLATE.replace("{diff}", diff)


async def call_model(
    client: httpx.AsyncClient,
    model_cfg: dict[str, str],
    prompt: str,
    timeout: int,
) -> dict[str, str | None]:
    model_id = model_cfg["id"]
    model_name = model_cfg.get("name", model_id)

    api_key = model_cfg.get("api_key") or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return {"model": model_name, "content": None, "error": "OPENAI_API_KEY not set"}

    base_url = (
        model_cfg.get("base_url")
        or os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    ).rstrip("/")

    headers: dict[str, str] = {"Authorization": f"Bearer {api_key}"}
    if "openrouter" in base_url:
        headers["HTTP-Referer"] = os.getenv(
            "OPENROUTER_HTTP_REFERER", "https://github.com"
        )
        headers["X-Title"] = os.getenv(
            "OPENROUTER_APP_TITLE", "multi-model-code-review"
        )

    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }

    try:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"model": model_name, "content": str(content), "error": None}
    except httpx.TimeoutException:
        return {
            "model": model_name,
            "content": None,
            "error": f"timeout after {timeout}s",
        }
    except httpx.HTTPStatusError as exc:
        return {
            "model": model_name,
            "content": None,
            "error": f"HTTP {exc.response.status_code}: {exc.response.text}",
        }
    except Exception as exc:
        return {"model": model_name, "content": None, "error": str(exc)}


async def call_all_models(
    config: ReviewConfig, prompt: str
) -> list[dict[str, str | None]]:
    async with httpx.AsyncClient() as client:
        tasks = [
            call_model(
                client=client,
                model_cfg=model,
                prompt=prompt,
                timeout=config.timeout_seconds,
            )
            for model in config.models
        ]
        return list(await asyncio.gather(*tasks))


def has_critical_issues(results: list[dict[str, str | None]]) -> bool:
    ignored = {"none", "n/a", "na", "-", "no", "no issues"}
    for result in results:
        content = result.get("content") or ""
        lines = str(content).splitlines()
        for index, line in enumerate(lines):
            normalized = line.strip().lower().strip(":")
            if normalized not in {"critical", "## critical", "### critical"}:
                continue

            for candidate in lines[index + 1 :]:
                stripped = candidate.strip()
                if not stripped:
                    continue
                if stripped.startswith("#"):
                    break

                lowered = stripped.lower().lstrip("-*").strip()
                if lowered not in ignored:
                    return True
    return False


def merge_reviews(results: list[dict[str, str | None]]) -> str:
    queried = len(results)
    responded = sum(1 for r in results if r.get("content"))
    failed = sum(1 for r in results if r.get("error"))
    critical = has_critical_issues(results)

    sections = [
        "# Multi-Model Code Review",
        "",
        f"- Queried: {queried}",
        f"- Responded: {responded}",
        f"- Failed: {failed}",
        f"- Critical issues detected: {'Yes' if critical else 'No'}",
    ]

    for result in results:
        sections.extend(["", f"## Model: {result['model']}"])
        if result.get("error"):
            sections.append(f"**Error:** {result['error']}")
        else:
            sections.append(result.get("content") or "")

    return "\n".join(sections).rstrip() + "\n"


def format_terminal(review: str) -> str:
    return review


def format_github_comment(review: str) -> str:
    marker = "\n## Model: "
    if marker not in review:
        return review

    head, tail = review.split(marker, 1)
    model_blocks = [tail]
    if marker in tail:
        model_blocks = tail.split(marker)

    formatted_sections = [head.rstrip()]
    for block in model_blocks:
        block_lines = block.splitlines()
        if not block_lines:
            continue

        name = block_lines[0].strip()
        body = "\n".join(block_lines[1:]).strip()
        formatted_sections.append(
            f"<details>\n<summary>Model: {name}</summary>\n\n{body}\n</details>"
        )

    return "\n\n".join(part for part in formatted_sections if part).rstrip() + "\n"


def find_config() -> str:
    current = Path.cwd().resolve()
    for directory in (current, *current.parents):
        candidate = directory / ".multi-review.yaml"
        if candidate.exists():
            return str(candidate)

    global_config = Path.home() / ".config" / "multi-review.yaml"
    if global_config.exists():
        return str(global_config)

    raise FileNotFoundError(
        "No .multi-review.yaml found (searched project tree and ~/.config/)"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run multi-model code review over git diffs.",
        epilog=(
            "Examples:\n"
            "  python scripts/multi_model_review.py\n"
            "  python scripts/multi_model_review.py --base origin/main --head HEAD\n"
            "  git diff --staged | python scripts/multi_model_review.py --diff-stdin --format github-comment"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--config", help="Path to .multi-review.yaml")
    parser.add_argument("--base", help="Base git ref for diff range")
    parser.add_argument("--head", default="HEAD", help="Head git ref (default: HEAD)")
    parser.add_argument(
        "--format",
        choices=["terminal", "github-comment", "json"],
        default="terminal",
        help="Output format",
    )
    parser.add_argument(
        "--diff-stdin", action="store_true", help="Read diff content from stdin"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        config_path = args.config or find_config()
        print(f"[multi-review] Using config: {config_path}", file=sys.stderr)
        config = load_config(config_path)

        supplied_diff = sys.stdin.read() if args.diff_stdin else None
        diff = get_diff(
            base=args.base,
            head=args.head,
            diff_text=supplied_diff,
            max_lines=config.max_diff_lines,
        )
        if not diff.strip():
            print("[multi-review] No changes to review.", file=sys.stderr)
            return 0

        prompt = build_prompt(diff)
        print(
            f"[multi-review] Querying {len(config.models)} model(s)...",
            file=sys.stderr,
        )
        results = asyncio.run(call_all_models(config, prompt))
        review = merge_reviews(results)

        if args.format == "terminal":
            output = format_terminal(review)
        elif args.format == "github-comment":
            output = format_github_comment(review)
        else:
            output = json.dumps(results, indent=2)

        print(output)

        if config.fail_on_critical and has_critical_issues(results):
            print("[multi-review] Critical issues detected.", file=sys.stderr)
            return 1
        return 0
    except Exception as exc:
        print(f"[multi-review] Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
