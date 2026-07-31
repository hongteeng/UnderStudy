import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import teacher_workspace
from apply_rules import apply_draft


class TeacherWorkspaceTests(unittest.TestCase):
    def test_creates_and_reopens_isolated_teacher_workspaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            teachers_root = Path(temporary) / "teachers"
            with patch.object(teacher_workspace, "TEACHERS_ROOT", teachers_root):
                hong_ting, hong_created = teacher_workspace.create_or_get_teacher(
                    "Hong Ting"
                )
                jane, jane_created = teacher_workspace.create_or_get_teacher("Jane Tan")
                reopened, reopened_created = teacher_workspace.create_or_get_teacher(
                    "hong-ting"
                )

                self.assertTrue(hong_created)
                self.assertTrue(jane_created)
                self.assertFalse(reopened_created)
                self.assertEqual(reopened.root, hong_ting.root)
                self.assertNotEqual(hong_ting.rules_path, jane.rules_path)
                self.assertTrue(hong_ting.incoming_dir.is_dir())
                self.assertTrue(jane.rule_drafts_dir.is_dir())

    def test_applying_a_draft_changes_only_its_teacher(self):
        with tempfile.TemporaryDirectory() as temporary:
            teachers_root = Path(temporary) / "teachers"
            with patch.object(teacher_workspace, "TEACHERS_ROOT", teachers_root):
                first, _ = teacher_workspace.create_or_get_teacher("First Teacher")
                second, _ = teacher_workspace.create_or_get_teacher("Second Teacher")

                draft = first.rule_drafts_dir / "lesson_rules_draft.md"
                draft.write_text(
                    "# Draft rules\n\n"
                    "## Tutor response approaches\n\n"
                    "- Explain from first principles. (lesson.md)\n",
                    encoding="utf-8",
                )
                second_before = second.rules_path.read_text(encoding="utf-8")

                apply_draft(draft, first.rules_path)

                self.assertIn(
                    "Explain from first principles",
                    first.rules_path.read_text(encoding="utf-8"),
                )
                self.assertEqual(
                    second.rules_path.read_text(encoding="utf-8"), second_before
                )


if __name__ == "__main__":
    unittest.main()
