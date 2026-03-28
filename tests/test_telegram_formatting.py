# pyright: reportMissingImports=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.telegram_bot.formatting import (
    format_answer_text,
    format_question_sources,
    format_response,
    format_youtube_sources,
    split_message,
)


def test_format_answer_text_plain_passthrough():
    assert format_answer_text("Simple NEET answer") == "Simple NEET answer"


def test_format_answer_text_escapes_html_special_chars():
    raw = "Use <tag> & keep > and < safely"
    assert format_answer_text(raw) == "Use &lt;tag&gt; &amp; keep &gt; and &lt; safely"


def test_format_answer_text_strips_inline_latex_delimiters():
    assert format_answer_text("Energy is $x^2$ law") == "Energy is x^2 law"


def test_format_answer_text_strips_block_latex_delimiters():
    assert (
        format_answer_text("Ratio $$\\frac{a}{b}$$ done") == "Ratio \\frac{a}{b} done"
    )


def test_format_answer_text_strips_parenthesis_latex_delimiters():
    assert format_answer_text(r"Compute \(x+1\) quickly") == "Compute x+1 quickly"


def test_format_answer_text_strips_bracket_latex_delimiters():
    assert format_answer_text(r"Matrix form: \[a+b\]") == "Matrix form: a+b"


def test_format_answer_text_converts_sup_tag_to_unicode():
    assert format_answer_text("x<sup>2</sup>") == "x²"


def test_format_answer_text_converts_sub_tag_to_unicode():
    assert format_answer_text("H<sub>2</sub>O") == "H₂O"


def test_format_answer_text_preserves_newlines_and_unicode_math_symbols():
    raw = "Line 1\nπ and √ stay"
    assert format_answer_text(raw) == raw


def test_format_youtube_sources_single_source_with_timestamp_link():
    sources = [
        {
            "title": "Kinematics intro",
            "url": "https://youtube.com/watch?v=abc123",
            "timestamp": "12:34",
        }
    ]

    rendered = format_youtube_sources(sources)

    assert rendered.startswith(
        '1. <a href="https://youtube.com/watch?v=abc123&amp;t=754">'
    )
    assert "Kinematics intro" in rendered
    assert "(12:34)" in rendered


def test_format_youtube_sources_empty_returns_blank_string():
    assert format_youtube_sources([]) == ""


def test_format_youtube_sources_multiple_sources_are_numbered():
    sources = [
        {"title": "First", "url": "https://youtu.be/1"},
        {"title": "Second", "url": "https://youtu.be/2", "timestamp": "00:10"},
    ]

    rendered = format_youtube_sources(sources)

    assert "1. " in rendered
    assert "2. " in rendered
    assert rendered.count("\n") == 1


def test_format_question_sources_single_question_with_neetprep_link():
    rendered = format_question_sources([{"id": 12345, "question": "Find acceleration"}])

    assert (
        rendered
        == '1. <a href="https://neetprep.com/epubQuestion/12345">Find acceleration</a>'
    )


def test_format_question_sources_empty_returns_blank_string():
    assert format_question_sources([]) == ""


def test_format_response_with_sources_combines_answer_and_source_sections():
    chunks = format_response(
        answer_text="Final answer",
        youtube_sources=[
            {
                "title": "Work-Energy",
                "url": "https://youtube.com/watch?v=xyz",
                "timestamp": "00:30",
            }
        ],
        question_sources=[{"id": "777", "question": "PYQ on energy"}],
    )

    combined = "".join(chunks)

    assert "Final answer" in combined


def test_format_response_without_sources_returns_answer_only():
    chunks = format_response(answer_text="Only answer")
    assert chunks == ["Only answer"]


def test_split_message_short_text_not_split():
    assert split_message("short", max_length=4096) == ["short"]


def test_split_message_long_text_split_at_max_length():
    text = "a" * 5000
    chunks = split_message(text, max_length=4096)

    assert len(chunks) == 2
    assert all(len(chunk) <= 4096 for chunk in chunks)
    assert "".join(chunks) == text


def test_split_message_prefers_newline_boundary_and_avoids_mid_html_tag():
    text = ("a" * 4000) + "\n" + ("b" * 80) + "<b>bold</b>" + ("c" * 80)
    chunks = split_message(text, max_length=4096)

    assert chunks[0].endswith("\n")
    assert "".join(chunks) == text
    assert chunks[1].startswith("b" * 80)

    tag_split_text = ("x" * 4094) + "<b>ok</b>"
    tag_chunks = split_message(tag_split_text, max_length=4096)
    assert tag_chunks[0].endswith("x")
    assert tag_chunks[1].startswith("<b>")
