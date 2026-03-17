import unittest


class TestAssistantAnswerFormatting(unittest.TestCase):
    def test_normalize_assistant_answer_converts_known_html_tags(self):
        from src.utils.answer_formatting import format_assistant_answer_for_streamlit

        raw = (
            "Kinetic energy is proportional to mv<sup>2</sup>/2. "
            "Water is H<sub>2</sub>O.<br>"
            "<b>Important</b> and <i>revised</i>."
        )

        formatted = format_assistant_answer_for_streamlit(raw)

        self.assertEqual(
            formatted,
            "Kinetic energy is proportional to mv²/2. Water is H₂O.\n"
            + "**Important** and *revised*.",
        )

    def test_normalize_assistant_answer_falls_back_for_non_unicode_subscripts(self):
        from src.utils.answer_formatting import format_assistant_answer_for_streamlit

        raw = "For ideal solutions, ΔH<sub>xyz</sub> = 0 and x<sup>ab</sup> is generic."

        formatted = format_assistant_answer_for_streamlit(raw)

        self.assertIn("ΔH_(xyz) = 0", formatted)
        self.assertIn("x^(ab)", formatted)

    def test_normalize_assistant_answer_strips_scripts_without_rewriting_literals(self):
        from src.utils.answer_formatting import format_assistant_answer_for_streamlit

        raw = "Use work-energy theorem<script>alert(1)</script> safely."

        formatted = format_assistant_answer_for_streamlit(raw)

        self.assertEqual(formatted, "Use work-energy theorem safely.")

    def test_normalize_assistant_answer_preserves_literal_supported_tag_text(self):
        from src.utils.answer_formatting import format_assistant_answer_for_streamlit

        raw = "The literal token is <sup> in HTML and should stay visible."

        formatted = format_assistant_answer_for_streamlit(raw)

        self.assertEqual(formatted, raw)

    def test_format_chat_message_leaves_user_text_unchanged(self):
        from src.utils.answer_formatting import format_chat_message_for_streamlit

        raw = "What does <b> mean in HTML?"

        formatted = format_chat_message_for_streamlit("user", raw)

        self.assertEqual(formatted, raw)

    def test_prompt_builder_explicitly_forbids_html_tags(self):
        from src.rag.llm_manager import RAGPromptBuilder

        prompt = RAGPromptBuilder().default_system_prompt

        self.assertIn("Do NOT use HTML tags", prompt)
        self.assertIn("<sup>", prompt)
        self.assertIn("LaTeX", prompt)


if __name__ == "__main__":
    _ = unittest.main(verbosity=2)
