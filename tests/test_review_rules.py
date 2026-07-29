import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apply_rules import split_sections, validate_draft
from review_rules import (
    ReviewResolution,
    choose_draft_path,
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


class ReviewRulesTests(unittest.TestCase):
    def test_parser_finds_review_choices(self):
        blocks = parse_review_blocks(DRAFT)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].source, "lesson.md")
        self.assertIn("mnemonic", blocks[0].point)
        self.assertIn("RED CAT", blocks[0].edit)

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

    def test_draft_picker_prefers_the_only_unresolved_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            resolved = directory / "old_rules_draft.md"
            unresolved = directory / "new_rules_draft.md"
            resolved.write_text("# Resolved\n", encoding="utf-8")
            unresolved.write_text("REVIEW REQUIRED\n", encoding="utf-8")

            with patch("review_rules.RULE_DRAFTS_DIR", directory):
                selected = choose_draft_path(None)

            self.assertEqual(selected, unresolved)


if __name__ == "__main__":
    unittest.main()
