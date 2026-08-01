import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from apply_rules import split_sections, validate_draft
from review_rules import (
    ReviewResolution,
    build_decision_contexts,
    choose_draft_path,
    console_review_provider,
    legacy_meta_decisions,
    parse_inline_decisions,
    parse_review_blocks,
    resolve_draft,
)


DRAFT = """# Draft tutor rules

## Required and preferred vocabulary

> ⚠ **REVIEW REQUIRED** — Source: `lesson.md`
> **POINT TO REVIEW:** The mnemonic may be wrong.
> **IF KEEP:** - **Mnemonic:** Use red cat. (lesson.md)
> **IF EDIT:** - **Mnemonic:** Use RED CAT. (lesson.md, tutor-edited)
> **IF EXCLUDE:** delete this entire block.

## Topic map and reusable explanations

> ⚠ **REVIEW REQUIRED** — Source: `lesson.md`
> **POINT TO REVIEW:** The explanation is optional.
> **IF KEEP:** - **Explanation:** Keep this explanation. (lesson.md)
> **IF EDIT:** - **Explanation:** Improve this explanation. (lesson.md, tutor-edited)
> **IF EXCLUDE:** delete this entire block.

## Syllabus boundaries

- **Student level:** Needs tutor decision; the source did not specify it. (lesson.md)

## Needs tutor decision

- Confirm the student level. (lesson.md)

## Review summary

- Two rules need review. (lesson.md)
"""


META_DECISIONS_DRAFT = """# Draft tutor rules

## Topic map and reusable explanations

- Redox is a foundational topic. (redox.md)
- **Oxidising-agent template:** Explain why compound X is an oxidising agent. (redox.md)

## Needs tutor decision

- **Oxidation-state rules:** Confirm the complete rule set. (redox.md)
- **Oxidising-agent template:** Supply the full wording. (redox.md)
- **OILRIG:** Confirm the expansion. (redox.md)
- **Grammar:** Choose whether to polish the quoted sentence. (redox.md)
- **Exam board:** Confirm the intended examination board. (redox.md)

## Review summary

- Decisions are needed on all five items. See **Needs tutor decision**.

## Source coverage

- Source summary. (redox.md)
"""


RULE_FOCUSED_DRAFT = """# Draft tutor rules

## Topic map and reusable explanations

> ⚠ **REVIEW REQUIRED** — Source: `lesson.md`
> **RULE AS DRAFTED:** - **Graphite:** Graphite is soft because its covalent bonds are weak. (lesson.md)
> **ISSUE WITH THIS RULE:** The rule incorrectly describes graphite's covalent bonds as weak and could teach the wrong structure-property link.
> **SUGGESTED REVISION:** - **Graphite:** Graphite is soft because weak forces between its layers allow the layers to slide. (lesson.md, tutor-edited)
> **IF EXCLUDE:** delete this entire block.

## Needs tutor decision

## Review summary

- Review the graphite rule in Topic map and reusable explanations.
"""


class ReviewRulesTests(unittest.TestCase):
    def test_parser_finds_review_choices(self):
        blocks = parse_review_blocks(DRAFT)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].source, "lesson.md")
        self.assertIn("mnemonic", blocks[0].point)
        self.assertIn("RED CAT", blocks[0].edit)

    def test_parser_supports_rule_focused_review_format(self):
        block = parse_review_blocks(RULE_FOCUSED_DRAFT)[0]

        self.assertEqual(block.section, "Topic map and reusable explanations")
        self.assertIn("Graphite is soft", block.keep)
        self.assertIn("incorrectly describes", block.point)
        self.assertIn("weak forces between its layers", block.edit)

    def test_console_makes_rule_issue_and_revision_easy_to_compare(self):
        block = parse_review_blocks(RULE_FOCUSED_DRAFT)[0]
        output = io.StringIO()
        with patch("builtins.input", return_value="x"), redirect_stdout(output):
            resolution = console_review_provider(block, 1, 1)

        rendered = output.getvalue()
        self.assertEqual(resolution.action, "exclude")
        self.assertIn("Rule as drafted:", rendered)
        self.assertIn("Why the AI flagged this rule:", rendered)
        self.assertIn("Suggested revision:", rendered)

    def test_rule_focused_suggested_revision_resolves_to_a_valid_rule(self):
        reviewed = resolve_draft(
            RULE_FOCUSED_DRAFT,
            lambda block, index, total: ReviewResolution("edit"),
            lambda decision, index, total: None,
        )

        self.assertIn("weak forces between its layers", reviewed)
        self.assertNotIn("RULE AS DRAFTED", reviewed)
        self.assertNotIn("ISSUE WITH THIS RULE", reviewed)
        self.assertNotIn("SUGGESTED REVISION", reviewed)
        validate_draft(reviewed, split_sections(reviewed))

    def test_edit_exclude_and_remove_decision_produce_valid_draft(self):
        def review_provider(block, index, total):
            return ReviewResolution("edit" if index == 1 else "exclude")

        reviewed = resolve_draft(
            DRAFT,
            review_provider,
            lambda decision, index, total: None,
        )

        self.assertIn("Use RED CAT", reviewed)
        self.assertNotIn("Keep this explanation", reviewed)
        self.assertNotIn("REVIEW REQUIRED", reviewed)
        self.assertNotIn("Needs tutor decision", reviewed)
        self.assertNotIn("Review summary", reviewed)
        validate_draft(reviewed, split_sections(reviewed))

    def test_custom_review_gets_bullet_and_source_citation(self):
        def review_provider(block, index, total):
            if index == 1:
                return ReviewResolution("custom", "**Mnemonic:** Use AN OX and RED CAT.")
            return ReviewResolution("keep")

        reviewed = resolve_draft(
            DRAFT,
            review_provider,
            lambda decision, index, total: "Secondary 3 chemistry",
        )

        self.assertIn(
            "- **Mnemonic:** Use AN OX and RED CAT. (lesson.md, tutor-edited)",
            reviewed,
        )
        self.assertIn(
            "- **Student level:** Secondary 3 chemistry (lesson.md, tutor-edited)",
            reviewed,
        )
        validate_draft(reviewed, split_sections(reviewed))

    def test_missing_source_details_are_not_turned_into_review_questions(self):
        prompted = []

        def decision_provider(decision, index, total):
            prompted.append((decision.original_line, index, total))
            return f"Unexpected answer {index}."

        reviewed = resolve_draft(
            META_DECISIONS_DRAFT,
            lambda block, index, total: ReviewResolution("exclude"),
            decision_provider,
        )

        self.assertEqual(prompted, [])
        self.assertNotIn("## Needs tutor decision", reviewed)
        self.assertNotIn("## Review summary", reviewed)
        self.assertNotIn("Unexpected answer", reviewed)
        validate_draft(reviewed, split_sections(reviewed))

    def test_legacy_missing_content_questions_are_detected_for_regeneration(self):
        self.assertEqual(len(legacy_meta_decisions(META_DECISIONS_DRAFT)), 5)

    def test_review_summary_is_not_mistaken_for_an_open_decision(self):
        self.assertEqual(parse_inline_decisions(META_DECISIONS_DRAFT), [])

    def test_open_decision_context_includes_draft_and_transcript_wording(self):
        with tempfile.TemporaryDirectory() as temporary:
            transcripts = Path(temporary) / "transcripts"
            transcripts.mkdir()
            (transcripts / "lesson.md").write_text(
                "# Lesson transcript\n\n## Transcript\n\n"
                "**[00:00:36–00:01:00] A:** This lesson is for Secondary 3 "
                "chemistry students.\n",
                encoding="utf-8",
            )
            contexts = build_decision_contexts(DRAFT, transcripts)
            decision = parse_inline_decisions(DRAFT)[0]
            context = contexts[(decision.section, decision.original_line.strip())]

        self.assertTrue(
            any("Student level" in rule for rule in context.draft_rules)
        )
        self.assertTrue(
            any("00:00:36" in excerpt for excerpt in context.transcript_excerpts)
        )

    def test_draft_picker_prefers_the_only_unresolved_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            resolved = directory / "old_rules_draft.md"
            unresolved = directory / "new_rules_draft.md"
            resolved.write_text("# Resolved\n", encoding="utf-8")
            unresolved.write_text("REVIEW REQUIRED\n", encoding="utf-8")

            selected = choose_draft_path(None, directory)

            self.assertEqual(selected, unresolved)


if __name__ == "__main__":
    unittest.main()
