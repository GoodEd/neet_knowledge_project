import os
import sys
from importlib import import_module
from typing import cast

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rag.llm_manager import RAGPromptBuilder


def _doc(content: str, **metadata: object) -> object:
    document_cls = cast(
        type, getattr(import_module("langchain_core.documents"), "Document")
    )
    return cast(object, document_cls(page_content=content, metadata=metadata))


def test_youtube_docs_are_excluded_from_prompt():
    builder = RAGPromptBuilder()
    docs = [
        _doc("YouTube transcript snippet", source_type="youtube"),
        _doc("CSV PYQ content", source_type="csv"),
    ]

    prompt = builder.build_prompt("Explain this", docs)

    assert "YouTube transcript snippet" not in prompt
    assert "CSV PYQ content" in prompt


def test_csv_docs_get_previous_year_question_label():
    builder = RAGPromptBuilder()

    prompt = builder.build_prompt(
        "Question?", [_doc("PYQ statement", source_type="csv")]
    )

    assert "--- Previous Year Question ---" in prompt


def test_csv_docs_with_chapter_name_get_label_with_chapter():
    builder = RAGPromptBuilder()

    prompt = builder.build_prompt(
        "Question?",
        [_doc("PYQ statement", source_type="csv", chapter_name="Organic Chemistry")],
    )

    assert "--- Previous Year Question (Organic Chemistry) ---" in prompt


def test_csv_docs_without_chapter_name_get_plain_label():
    builder = RAGPromptBuilder()

    prompt = builder.build_prompt(
        "Question?", [_doc("Another PYQ", source_type="csv", chapter_name="")]
    )

    assert "--- Previous Year Question ---" in prompt
    assert "--- Previous Year Question (" not in prompt


def test_all_youtube_docs_return_no_matching_message():
    builder = RAGPromptBuilder()
    docs = [
        _doc("YT 1", source_type="youtube"),
        _doc("YT 2", source_type="youtube"),
    ]

    prompt = builder.build_prompt("Find PYQ", docs)

    assert prompt == "Question: Find PYQ\n\nNo matching previous year questions found."


def test_no_docs_return_no_matching_message():
    builder = RAGPromptBuilder()

    prompt = builder.build_prompt("Find PYQ", [])

    assert prompt == "Question: Find PYQ\n\nNo matching previous year questions found."


def test_prompt_ends_with_expected_guidance_suffix():
    builder = RAGPromptBuilder()

    prompt = builder.build_prompt("Help", [_doc("PYQ text", source_type="csv")])

    assert prompt.endswith("Analyze the PYQs above and provide concise guidance.")


def test_query_text_appears_in_prompt():
    builder = RAGPromptBuilder()
    query = "How to solve this NEET PYQ?"

    prompt = builder.build_prompt(query, [_doc("PYQ text", source_type="csv")])

    assert f"Question: {query}" in prompt


def test_doc_content_appears_in_prompt():
    builder = RAGPromptBuilder()
    content = "Given f(x)=x^2, find derivative."

    prompt = builder.build_prompt("Solve", [_doc(content, source_type="csv")])

    assert f"Content: {content}" in prompt


def test_multiple_csv_docs_all_appear_in_prompt():
    builder = RAGPromptBuilder()
    docs = [
        _doc("PYQ A", source_type="csv"),
        _doc("PYQ B", source_type="csv"),
        _doc("PYQ C", source_type="csv", chapter_name="Mechanics"),
    ]

    prompt = builder.build_prompt("Compare", docs)

    assert "PYQ A" in prompt
    assert "PYQ B" in prompt
    assert "PYQ C" in prompt


def test_mixed_youtube_and_csv_only_csv_appears():
    builder = RAGPromptBuilder()
    docs = [
        _doc("YouTube explanation", source_type="youtube"),
        _doc("PYQ from CSV", source_type="csv"),
        _doc("Another YouTube piece", content_type="youtube"),
    ]

    prompt = builder.build_prompt("Analyze", docs)

    assert "PYQ from CSV" in prompt
    assert "YouTube explanation" not in prompt
    assert "Another YouTube piece" not in prompt


def test_build_with_history_includes_chat_history():
    builder = RAGPromptBuilder()
    history: list[tuple[str, str]] = [
        ("What is osmosis?", "Movement of solvent across semipermeable membrane."),
        ("And diffusion?", "Movement from high concentration to low concentration."),
    ]

    prompt = builder.build_with_history(  # pyright: ignore[reportUnknownMemberType]
        "Give a quick comparison",
        [_doc("PYQ on osmosis vs diffusion", source_type="csv")],
        chat_history=history,
    )

    assert "Previous conversation:" in prompt
    assert "User: What is osmosis?" in prompt
    assert "Assistant: Movement of solvent across semipermeable membrane." in prompt
    assert "User: And diffusion?" in prompt
    assert "Assistant: Movement from high concentration to low concentration." in prompt


def test_custom_system_prompt_via_constructor():
    custom_prompt = "Custom instruction for strict PYQ tutoring."

    builder = RAGPromptBuilder(system_prompt=custom_prompt)

    assert builder.default_system_prompt == custom_prompt


def test_default_system_prompt_mentions_pyqs_not_video_or_youtube():
    builder = RAGPromptBuilder()
    system_prompt = builder.default_system_prompt.lower()

    assert "pyqs" in system_prompt
    assert "video" not in system_prompt
    assert "youtube" not in system_prompt
