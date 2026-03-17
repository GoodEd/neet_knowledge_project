import re


_SCRIPT_STYLE_BLOCK_PATTERN = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
_LINE_BREAK_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)
_SUPPORTED_TAG_PATTERNS = {
    "bold": re.compile(r"<(b|strong)\b[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL),
    "italic": re.compile(r"<(i|em)\b[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL),
    "sup": re.compile(r"<sup\b[^>]*>(.*?)</sup>", re.IGNORECASE | re.DOTALL),
    "sub": re.compile(r"<sub\b[^>]*>(.*?)</sub>", re.IGNORECASE | re.DOTALL),
}


_SUPERSCRIPT_MAP = {
    "0": "⁰",
    "1": "¹",
    "2": "²",
    "3": "³",
    "4": "⁴",
    "5": "⁵",
    "6": "⁶",
    "7": "⁷",
    "8": "⁸",
    "9": "⁹",
    "+": "⁺",
    "-": "⁻",
    "=": "⁼",
    "(": "⁽",
    ")": "⁾",
    "i": "ⁱ",
    "n": "ⁿ",
}

_SUBSCRIPT_MAP = {
    "0": "₀",
    "1": "₁",
    "2": "₂",
    "3": "₃",
    "4": "₄",
    "5": "₅",
    "6": "₆",
    "7": "₇",
    "8": "₈",
    "9": "₉",
    "+": "₊",
    "-": "₋",
    "=": "₌",
    "(": "₍",
    ")": "₎",
    "a": "ₐ",
    "e": "ₑ",
    "h": "ₕ",
    "i": "ᵢ",
    "j": "ⱼ",
    "k": "ₖ",
    "l": "ₗ",
    "m": "ₘ",
    "n": "ₙ",
    "o": "ₒ",
    "p": "ₚ",
    "r": "ᵣ",
    "s": "ₛ",
    "t": "ₜ",
    "u": "ᵤ",
    "v": "ᵥ",
    "x": "ₓ",
}


def _normalize_latex_delimiters(text: str) -> str:
    text = re.sub(r"\\\[(.+?)\\\]", r"$$\1$$", text, flags=re.DOTALL)
    text = re.sub(r"\\\((.+?)\\\)", r"$\1$", text, flags=re.DOTALL)
    return text


def _render_with_map(text: str, mapping: dict[str, str], fallback_prefix: str) -> str:
    cleaned = text.strip()
    if cleaned and all(char in mapping for char in cleaned):
        return "".join(mapping[char] for char in cleaned)
    return f"{fallback_prefix}({cleaned})" if cleaned else ""


def _normalize_html_like_tags(text: str) -> str:
    if "<" not in text or ">" not in text:
        return text

    normalized = _SCRIPT_STYLE_BLOCK_PATTERN.sub("", text)
    normalized = _LINE_BREAK_PATTERN.sub("\n", normalized)

    normalized = _SUPPORTED_TAG_PATTERNS["bold"].sub(
        lambda match: f"**{match.group(2).strip()}**", normalized
    )
    normalized = _SUPPORTED_TAG_PATTERNS["italic"].sub(
        lambda match: f"*{match.group(2).strip()}*", normalized
    )
    normalized = _SUPPORTED_TAG_PATTERNS["sup"].sub(
        lambda match: _render_with_map(match.group(1), _SUPERSCRIPT_MAP, "^"),
        normalized,
    )
    normalized = _SUPPORTED_TAG_PATTERNS["sub"].sub(
        lambda match: _render_with_map(match.group(1), _SUBSCRIPT_MAP, "_"),
        normalized,
    )

    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n[ \t]+", "\n", normalized)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    return normalized.strip()


def format_assistant_answer_for_streamlit(text: str) -> str:
    normalized = _normalize_html_like_tags(text)
    return _normalize_latex_delimiters(normalized)


def format_chat_message_for_streamlit(role: str, text: str) -> str:
    if role != "assistant":
        return text
    return format_assistant_answer_for_streamlit(text)
