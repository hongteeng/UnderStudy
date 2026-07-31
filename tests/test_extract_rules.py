import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import extract_rules


class ExtractRulesTests(unittest.TestCase):
    def test_load_transcripts_reads_files_directly_from_transcripts_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            transcripts = Path(temporary) / "transcripts"
            transcripts.mkdir()
            (transcripts / "lesson.md").write_text(
                "Teacher explains bonding.", encoding="utf-8"
            )

            with patch.object(extract_rules, "PROJECT_ROOT", Path(temporary)):
                text, names = extract_rules.load_transcripts(transcripts)

        self.assertIn("Teacher explains bonding.", text)
        self.assertIn("transcripts/lesson.md", text)
        self.assertEqual(names, ["lesson"])

    def test_load_transcripts_does_not_use_nested_status_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            transcripts = Path(temporary) / "transcripts"
            nested = transcripts / "reviewed"
            nested.mkdir(parents=True)
            (transcripts / "current.md").write_text("Current", encoding="utf-8")
            (nested / "legacy.md").write_text("Legacy", encoding="utf-8")

            with patch.object(extract_rules, "PROJECT_ROOT", Path(temporary)):
                text, names = extract_rules.load_transcripts(transcripts)

        self.assertIn("Current", text)
        self.assertNotIn("Legacy", text)
        self.assertEqual(names, ["current"])


if __name__ == "__main__":
    unittest.main()
