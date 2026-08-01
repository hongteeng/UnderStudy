import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_eval
from teacher_workspace import TeacherWorkspace


class EvaluationFlowTests(unittest.TestCase):
    def make_workspace(self, root: Path, *, syllabus: bool = True) -> TeacherWorkspace:
        workspace = TeacherWorkspace("test-teacher", "Test Teacher", root / "test-teacher")
        workspace.ensure_directories()
        workspace.rules_path.write_text(
            "# Test Teacher's teaching rules\n\n- Explain structure before properties.\n",
            encoding="utf-8",
        )
        if syllabus:
            workspace.syllabus_path.write_text(
                "# Chemistry syllabus\n\nBonding and structure.\n", encoding="utf-8"
            )
        return workspace

    def make_questions(self, root: Path, count: int = 1) -> Path:
        questions = root / "questions"
        questions.mkdir()
        for index in range(1, count + 1):
            (questions / f"q{index}.md").write_text(
                f"Question number {index}?\n", encoding="utf-8"
            )
        return questions

    def test_run_is_stored_inside_teacher_and_snapshots_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self.make_workspace(root)
            questions = self.make_questions(root)

            evaluation = run_eval.create_evaluation_run(workspace, questions)

            self.assertEqual(
                evaluation.root.parent, workspace.root / "results" / "evaluations"
            )
            self.assertTrue(evaluation.rules_path.is_file())
            self.assertTrue(evaluation.syllabus_path.is_file())
            self.assertTrue((evaluation.questions_dir / "q1.md").is_file())
            self.assertEqual(evaluation.metadata["teacher_id"], "test-teacher")
            self.assertEqual(evaluation.metadata["baseline_type"], "syllabus-only")

    def test_teacher_without_syllabus_gets_a_generic_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self.make_workspace(root, syllabus=False)

            evaluation = run_eval.create_evaluation_run(
                workspace, self.make_questions(root)
            )

            self.assertEqual(evaluation.metadata["baseline_type"], "generic")
            self.assertFalse(evaluation.syllabus_path.exists())

    def test_generation_checkpoints_and_resumes_without_repeating_saved_answer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self.make_workspace(root)
            evaluation = run_eval.create_evaluation_run(
                workspace, self.make_questions(root)
            )

            with patch.object(
                run_eval, "generate_understudy_answer", return_value="Teacher answer"
            ) as understudy, patch.object(
                run_eval,
                "generate_baseline_answer",
                side_effect=RuntimeError("temporary API failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "temporary API failure"):
                    run_eval.generate_answers(evaluation)
                understudy.assert_called_once()

            saved = json.loads(evaluation.responses_path.read_text(encoding="utf-8"))
            self.assertEqual(saved[0]["understudy_answer"], "Teacher answer")
            self.assertEqual(saved[0]["baseline_answer"], "")
            self.assertEqual(evaluation.metadata["status"], "interrupted")

            with patch.object(run_eval, "generate_understudy_answer") as understudy, patch.object(
                run_eval, "generate_baseline_answer", return_value="Baseline answer"
            ) as baseline:
                run_eval.generate_answers(evaluation)
                understudy.assert_not_called()
                baseline.assert_called_once_with(
                    "Question number 1?",
                    syllabus_path=evaluation.syllabus_path,
                    model=evaluation.metadata["model"],
                )

            self.assertTrue(run_eval.answers_complete(evaluation))
            self.assertEqual(evaluation.metadata["status"], "reviewing")
            self.assertEqual(
                {
                    evaluation.rows[0]["answer_a_system"],
                    evaluation.rows[0]["answer_b_system"],
                },
                {run_eval.SYSTEM_UNDERSTUDY, run_eval.SYSTEM_BASELINE},
            )

    def test_blind_review_maps_scores_back_and_writes_final_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self.make_workspace(root)
            evaluation = run_eval.create_evaluation_run(
                workspace, self.make_questions(root)
            )
            with patch.object(
                run_eval, "generate_understudy_answer", return_value="Teacher answer"
            ), patch.object(
                run_eval, "generate_baseline_answer", return_value="Baseline answer"
            ):
                run_eval.generate_answers(evaluation)

            inputs = iter(["3", "1", "n", "y", "A", "Clearer wording"])
            completed = run_eval.review_answers(evaluation, input_fn=lambda _: next(inputs))

            self.assertTrue(completed)
            self.assertEqual(evaluation.metadata["status"], "complete")
            self.assertTrue(evaluation.final_report_path.is_file())
            self.assertTrue(evaluation.final_csv_path.is_file())
            with evaluation.final_csv_path.open(encoding="utf-8", newline="") as source:
                row = next(csv.DictReader(source))

            if evaluation.rows[0]["answer_a_system"] == run_eval.SYSTEM_UNDERSTUDY:
                self.assertEqual(row["understudy_rule_score"], "3")
                self.assertEqual(row["baseline_rule_score"], "1")
                self.assertEqual(row["preferred_system"], "understudy")
            else:
                self.assertEqual(row["understudy_rule_score"], "1")
                self.assertEqual(row["baseline_rule_score"], "3")
                self.assertEqual(row["preferred_system"], "syllabus_baseline")

            report = evaluation.final_report_path.read_text(encoding="utf-8")
            self.assertIn("# UnderStudy evaluation report", report)
            self.assertIn("Average teacher-fit score", report)
            self.assertIn("Clearer wording", report)


if __name__ == "__main__":
    unittest.main()
