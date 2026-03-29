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

### Review branch vs main (most common)

```bash
python scripts/multi_model_review.py --base origin/main
```

### Review staged changes

```bash
python scripts/multi_model_review.py
```

### Review last N commits

```bash
python scripts/multi_model_review.py --base HEAD~3 --head HEAD
```

### Output as JSON (for programmatic use)

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
  - id: deepseek/deepseek-r1
    name: DeepSeek R1
```

Browse available models: https://openrouter.ai/models

## What the Review Covers

Each model evaluates against this checklist:
- **Code Quality:** correctness, readability, security, data safety
- **Architecture:** separation of concerns, API contracts, performance
- **Testing:** coverage, edge cases, determinism
- **Production Readiness:** observability, error handling, rollback safety

## Output Format

Each model produces:
- **Strengths** — What's well done
- **Issues** — Categorized as Critical / Important / Minor with file:line references
- **Assessment** — Merge readiness verdict (Ready / Needs Changes / Blocked)

## Integration Points

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
