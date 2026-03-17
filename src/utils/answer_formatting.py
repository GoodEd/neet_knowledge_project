import re
from collections.abc import Iterable

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString, PageElement


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


def _render_node(node: PageElement) -> str:
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return str(node)

    name = (node.name or "").lower()
    children = "".join(_render_node(child) for child in node.children)

    if name == "br":
        return "\n"
    if name in {"b", "strong"}:
        return f"**{children.strip()}**"
    if name in {"i", "em"}:
        return f"*{children.strip()}*"
    if name == "sup":
        return _render_with_map(children, _SUPERSCRIPT_MAP, "^")
    if name == "sub":
        return _render_with_map(children, _SUBSCRIPT_MAP, "_")
    return children


def _render_soup(nodes: Iterable[PageElement]) -> str:
    return "".join(_render_node(node) for node in nodes)


def _normalize_html_like_tags(text: str) -> str:
    if "<" not in text or ">" not in text:
        return text

    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    normalized = _render_soup(soup.contents)
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n[ \t]+", "\n", normalized)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    return normalized.strip()


def format_assistant_answer_for_streamlit(text: str) -> str:
    normalized = _normalize_html_like_tags(text)
    return _normalize_latex_delimiters(normalized)
