# pyright: reportPrivateUsage=false

import re
from html import escape as html_escape
from typing import TypedDict

from src.utils.answer_formatting import (
    _SUBSCRIPT_MAP,
    _SUPERSCRIPT_MAP,
)


class YouTubeSource(TypedDict, total=False):
    title: str
    url: str
    timestamp: str


class QuestionSource(TypedDict, total=False):
    id: int | str
    question: str
    title: str


_INLINE_LATEX_PATTERN = re.compile(r"\$(.+?)\$", re.DOTALL)
_BLOCK_LATEX_PATTERN = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_PAREN_LATEX_PATTERN = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
_BRACKET_LATEX_PATTERN = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)
_SUP_PATTERN = re.compile(r"<sup\b[^>]*>(.*?)</sup>", re.IGNORECASE | re.DOTALL)
_SUB_PATTERN = re.compile(r"<sub\b[^>]*>(.*?)</sub>", re.IGNORECASE | re.DOTALL)
_MD_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MD_ITALIC_PATTERN = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")


def _render_with_map(text: str, mapping: dict[str, str]) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""
    if all(char in mapping for char in cleaned):
        return "".join(mapping[char] for char in cleaned)
    return cleaned


def _strip_latex_delimiters(text: str) -> str:
    stripped = _BLOCK_LATEX_PATTERN.sub(r"\1", text)
    stripped = _PAREN_LATEX_PATTERN.sub(r"\1", stripped)
    stripped = _BRACKET_LATEX_PATTERN.sub(r"\1", stripped)
    stripped = _INLINE_LATEX_PATTERN.sub(r"\1", stripped)
    return stripped


def _convert_sup_sub(text: str) -> str:
    converted = _SUP_PATTERN.sub(
        lambda match: _render_with_map(match.group(1), _SUPERSCRIPT_MAP), text
    )
    converted = _SUB_PATTERN.sub(
        lambda match: _render_with_map(match.group(1), _SUBSCRIPT_MAP), converted
    )
    return converted


def _convert_markdown_to_html(text: str) -> str:
    converted = re.sub(r"\*{3}(.+?)\*{3}", r"<b><i>\1</i></b>", text)
    converted = _MD_BOLD_PATTERN.sub(r"<b>\1</b>", converted)
    converted = _MD_ITALIC_PATTERN.sub(r"<i>\1</i>", converted)
    converted = re.sub(r"^(\s*)\*\s+", r"\1" + "\u2022 ", converted, flags=re.MULTILINE)
    return converted


def _validate_html_tags(text: str) -> str:
    stack: list[str] = []
    tag_re = re.compile(r"<(/?)([a-z]+)[^>]*>", re.IGNORECASE)
    allowed = {"b", "i", "a", "code", "pre"}
    for match in tag_re.finditer(text):
        is_closing = match.group(1) == "/"
        tag = match.group(2).lower()
        if tag not in allowed:
            continue
        if is_closing:
            if stack and stack[-1] == tag:
                stack.pop()
            else:
                return re.sub(r"</?[bi]>", "", text)
        else:
            stack.append(tag)
    if stack:
        return re.sub(r"</?[bi]>", "", text)
    return text


def format_answer_text(answer_text: str) -> str:
    converted = _convert_sup_sub(answer_text)
    latex_stripped = _strip_latex_delimiters(converted)
    escaped = html_escape(latex_stripped)
    md_converted = _convert_markdown_to_html(escaped)
    return _validate_html_tags(md_converted)


def _parse_timestamp_to_seconds(timestamp: str) -> int | None:
    parts = [part.strip() for part in timestamp.split(":")]
    if not parts or any(not part.isdigit() for part in parts):
        return None

    values = [int(part) for part in parts]
    if len(values) == 3:
        hours, minutes, seconds = values
        return (hours * 3600) + (minutes * 60) + seconds
    if len(values) == 2:
        minutes, seconds = values
        return (minutes * 60) + seconds
    if len(values) == 1:
        return values[0]
    return None


def format_youtube_sources(sources: list[YouTubeSource]) -> str:
    if not sources:
        return ""

    lines: list[str] = []
    for index, source in enumerate(sources, start=1):
        raw_title = str(source.get("title") or f"YouTube Source {index}")
        raw_url = str(
            source.get("timestamp_url")
            or source.get("url")
            or source.get("source")
            or ""
        )
        timestamp = source.get("timestamp_label") or source.get("timestamp")

        if isinstance(timestamp, str) and timestamp.strip():
            ts_display = timestamp.strip()
            if "t=" not in raw_url:
                seconds = _parse_timestamp_to_seconds(ts_display)
                if seconds is not None:
                    separator = "&" if "?" in raw_url else "?"
                    raw_url = f"{raw_url}{separator}t={seconds}"
            raw_title = f"{raw_title} ({ts_display})"

        escaped_title = html_escape(raw_title)
        escaped_url = html_escape(raw_url, quote=True)
        lines.append(f'{index}. <a href="{escaped_url}">{escaped_title}</a>')

    return "\n".join(lines)


def format_question_sources(sources: list[QuestionSource]) -> str:
    if not sources:
        return ""

    lines: list[str] = []
    for index, source in enumerate(sources, start=1):
        question_id = str(source.get("question_id") or source.get("id") or "")
        raw_title = str(
            source.get("question") or source.get("title") or f"Question {index}"
        )
        url = f"https://neetprep.com/epubQuestion/{question_id}"
        lines.append(
            f'{index}. <a href="{html_escape(url, quote=True)}">{html_escape(raw_title)}</a>'
        )

    return "\n".join(lines)


def format_response(
    answer_text: str,
    youtube_sources: list[YouTubeSource] | None = None,
    question_sources: list[QuestionSource] | None = None,
    max_length: int = 4096,
) -> list[str]:
    full_text = format_answer_text(answer_text)

    youtube_block = format_youtube_sources(youtube_sources or [])
    if youtube_block:
        full_text += f"\n\n<b>YouTube Sources</b>\n{youtube_block}"

    question_block = format_question_sources(question_sources or [])
    if question_block:
        full_text += f"\n\n<b>Related Questions</b>\n{question_block}"

    return split_message(full_text, max_length=max_length)


def split_message(text: str, max_length: int = 4096) -> list[str]:
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        window = remaining[:max_length]
        split_at = window.rfind("\n")
        cut = split_at + 1 if split_at != -1 else max_length

        candidate = remaining[:cut]
        last_lt = candidate.rfind("<")
        last_gt = candidate.rfind(">")
        if last_lt > last_gt:
            safe_cut = last_lt
            if safe_cut > 0:
                cut = safe_cut
                candidate = remaining[:cut]

        if not candidate:
            candidate = remaining[:max_length]
            cut = len(candidate)

        chunks.append(candidate)
        remaining = remaining[cut:]

    return chunks
