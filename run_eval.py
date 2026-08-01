"""Run a resumable, blind comparison for one teacher's question set."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

from answer import generate_understudy_answer
from baseline import generate_baseline_answer
from format_eval_report import format_blind_report, format_final_report
from teacher_workspace import TeacherWorkspace, project_relative, resolve_teacher


PROJECT_ROOT = Path(__file__).parent.resolve()
DEFAULT_QUESTION_DIRECTORY = PROJECT_ROOT / "data" / "eval_questions"
SYSTEM_UNDERSTUDY = "understudy"
SYSTEM_BASELINE = "syllabus_baseline"
RUN_VERSION = 2

BLIND_CSV_FIELDS = [
    "question_id",
    "question",
    "answer_a",
    "answer_b",
    "answer_a_score",
    "answer_b_score",
    "answer_a_syllabus_overshoot",
    "answer_b_syllabus_overshoot",
    "preferred_answer",
    "reviewer_notes",
    "reviewed_at",
]

FINAL_CSV_FIELDS = [
    "question_id",
    "question",
    "understudy_answer",
    "baseline_answer",
    "understudy_rule_score",
    "baseline_rule_score",
    "understudy_syllabus_overshoot",
    "baseline_syllabus_overshoot",
    "preferred_system",
    "reviewer_notes",
]

SCORE_GUIDE = (
    "0 = incorrect or unusable\n"
    "1 = needs major correction\n"
    "2 = usable after a minor edit\n"
    "3 = ready to use and matches the teacher"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate and blindly review UnderStudy and syllabus-only baseline "
            "answers for one teacher."
        )
    )
    parser.add_argument(
        "--teacher",
        default=None,
        help="Teacher ID or display name. Required when more than one teacher exists.",
    )
    parser.add_argument(
        "question_directory",
        type=Path,
        nargs="?",
        default=DEFAULT_QUESTION_DIRECTORY,
        help=(
            "Folder containing one Markdown question per item "
            f"(default: {project_relative(DEFAULT_QUESTION_DIRECTORY)})."
        ),
    )
    parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        help=(
            "Continue a saved evaluation. Use a run ID shown by an earlier run, "
            "or 'latest' for the newest incomplete run."
        ),
    )
    parser.add_argument(
        "--no-review",
        action="store_true",
        help="Generate the blinded answers now and review them in a later run.",
    )
    return parser.parse_args()


def natural_sort_key(path: Path) -> tuple[float, str]:
    match = re.search(r"\d+", path.stem)
    number = int(match.group()) if match else float("inf")
    return (number, path.stem)


def question_files(question_directory: Path) -> list[Path]:
    if not question_directory.is_dir():
        raise FileNotFoundError(
            f"Question directory does not exist: {question_directory}"
        )
    files = sorted(question_directory.glob("*.md"), key=natural_sort_key)
    if not files:
        raise FileNotFoundError(
            f"No Markdown question files found in: {question_directory}"
        )
    return files


def load_questions(question_directory: Path) -> list[tuple[str, str]]:
    questions: list[tuple[str, str]] = []
    for path in question_files(question_directory):
        question = path.read_text(encoding="utf-8").strip()
        if not question:
            raise ValueError(f"Question file is empty: {path}")
        questions.append((path.stem, question))
    return questions


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_question_set(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in question_files(directory):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def has_substantive_rules(path: Path) -> bool:
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return True
    return False


def write_json(path: Path, value: object) -> None:
    """Atomically replace a JSON progress file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read saved evaluation file {path}: {error}") from error


def next_run_id(root: Path) -> str:
    base = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    candidate = base
    suffix = 2
    while (root / candidate).exists():
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


@dataclass
class EvaluationRun:
    workspace: TeacherWorkspace
    root: Path
    metadata: dict[str, object]
    rows: list[dict[str, object]]

    @property
    def run_id(self) -> str:
        return str(self.metadata["run_id"])

    @property
    def inputs_dir(self) -> Path:
        return self.root / "inputs"

    @property
    def rules_path(self) -> Path:
        return self.inputs_dir / "rules.md"

    @property
    def syllabus_path(self) -> Path:
        return self.inputs_dir / "syllabus.md"

    @property
    def questions_dir(self) -> Path:
        return self.inputs_dir / "questions"

    @property
    def internal_dir(self) -> Path:
        return self.root / "internal"

    @property
    def metadata_path(self) -> Path:
        return self.root / "metadata.json"

    @property
    def responses_path(self) -> Path:
        return self.internal_dir / "responses.json"

    @property
    def answer_key_path(self) -> Path:
        return self.internal_dir / "answer_key.json"

    @property
    def blind_csv_path(self) -> Path:
        return self.root / "blind_review.csv"

    @property
    def blind_report_path(self) -> Path:
        return self.root / "blind_review.md"

    @property
    def final_csv_path(self) -> Path:
        return self.root / "eval_output.csv"

    @property
    def final_report_path(self) -> Path:
        return self.root / "eval_report.md"


def create_evaluation_run(
    workspace: TeacherWorkspace, question_directory: Path
) -> EvaluationRun:
    if not has_substantive_rules(workspace.rules_path):
        raise ValueError(
            f"{workspace.display_name}'s rules.md does not contain any reviewed rules yet. "
            "Apply at least one lesson before running an evaluation."
        )

    source_questions = question_files(question_directory.resolve())
    # Read now so an empty item cannot leave behind a half-created run.
    load_questions(question_directory.resolve())

    workspace.evaluation_runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = next_run_id(workspace.evaluation_runs_dir)
    root = workspace.evaluation_runs_dir / run_id
    inputs_dir = root / "inputs"
    snapshot_questions_dir = inputs_dir / "questions"
    internal_dir = root / "internal"
    snapshot_questions_dir.mkdir(parents=True)
    internal_dir.mkdir(parents=True)

    shutil.copy2(workspace.rules_path, inputs_dir / "rules.md")
    syllabus_available = (
        workspace.syllabus_path.is_file()
        and bool(workspace.syllabus_path.read_text(encoding="utf-8").strip())
    )
    if syllabus_available:
        shutil.copy2(workspace.syllabus_path, inputs_dir / "syllabus.md")
    for source in source_questions:
        shutil.copy2(source, snapshot_questions_dir / source.name)

    snapshot_questions = load_questions(snapshot_questions_dir)
    load_dotenv()
    created_at = utc_now()
    metadata: dict[str, object] = {
        "version": RUN_VERSION,
        "run_id": run_id,
        "teacher_id": workspace.teacher_id,
        "teacher_name": workspace.display_name,
        "status": "generating",
        "created_at": created_at,
        "updated_at": created_at,
        "completed_at": None,
        "model": os.getenv("OPENAI_MODEL", "gpt-5.6-sol"),
        "baseline_type": "syllabus-only" if syllabus_available else "generic",
        "question_count": len(snapshot_questions),
        "source_question_directory": project_relative(question_directory.resolve()),
        "question_set_sha256": sha256_question_set(snapshot_questions_dir),
        "rules_sha256": sha256_file(inputs_dir / "rules.md"),
        "syllabus_sha256": (
            sha256_file(inputs_dir / "syllabus.md") if syllabus_available else None
        ),
    }
    rows: list[dict[str, object]] = [
        {
            "question_id": question_id,
            "question": question,
            "understudy_answer": "",
            "baseline_answer": "",
            "answer_a_system": "",
            "answer_b_system": "",
            "review": {},
        }
        for question_id, question in snapshot_questions
    ]
    evaluation = EvaluationRun(workspace, root, metadata, rows)
    save_evaluation_run(evaluation)
    return evaluation


def _safe_run_directory(workspace: TeacherWorkspace, run_id: str) -> Path:
    if run_id == "latest":
        root = workspace.evaluation_runs_dir
        candidates = (
            sorted(
                (path for path in root.iterdir() if path.is_dir()),
                key=lambda path: path.name,
                reverse=True,
            )
            if root.is_dir()
            else []
        )
        incomplete = []
        for candidate in candidates:
            metadata_path = candidate / "metadata.json"
            if not metadata_path.is_file():
                continue
            metadata = read_json(metadata_path)
            if isinstance(metadata, dict) and metadata.get("status") != "complete":
                incomplete.append(candidate)
        if not incomplete:
            raise ValueError(
                f"No incomplete evaluation runs exist for {workspace.display_name}."
            )
        return incomplete[0]

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id):
        raise ValueError(f"Invalid evaluation run ID: {run_id}")
    return workspace.evaluation_runs_dir / run_id


def load_evaluation_run(
    workspace: TeacherWorkspace, run_id: str
) -> EvaluationRun:
    root = _safe_run_directory(workspace, run_id)
    metadata_value = read_json(root / "metadata.json")
    responses_value = read_json(root / "internal" / "responses.json")
    if not isinstance(metadata_value, dict) or not isinstance(responses_value, list):
        raise ValueError(f"Evaluation run is malformed: {root}")
    if metadata_value.get("teacher_id") != workspace.teacher_id:
        raise ValueError(f"Evaluation run does not belong to {workspace.display_name}: {root}")
    if metadata_value.get("version") != RUN_VERSION:
        raise ValueError(
            f"Evaluation run {root.name} uses an unsupported format version."
        )
    return EvaluationRun(workspace, root, metadata_value, responses_value)


def blind_row(row: dict[str, object]) -> dict[str, object]:
    answer_a_system = str(row.get("answer_a_system", ""))
    answer_b_system = str(row.get("answer_b_system", ""))
    review = row.get("review")
    if not isinstance(review, dict):
        review = {}

    def answer_for(system: str) -> str:
        if system == SYSTEM_UNDERSTUDY:
            return str(row.get("understudy_answer", ""))
        if system == SYSTEM_BASELINE:
            return str(row.get("baseline_answer", ""))
        return ""

    return {
        "question_id": row.get("question_id", ""),
        "question": row.get("question", ""),
        "answer_a": answer_for(answer_a_system),
        "answer_b": answer_for(answer_b_system),
        "answer_a_score": review.get("answer_a_score", ""),
        "answer_b_score": review.get("answer_b_score", ""),
        "answer_a_syllabus_overshoot": review.get(
            "answer_a_syllabus_overshoot", ""
        ),
        "answer_b_syllabus_overshoot": review.get(
            "answer_b_syllabus_overshoot", ""
        ),
        "preferred_answer": review.get("preferred_answer", ""),
        "reviewer_notes": review.get("reviewer_notes", ""),
        "reviewed_at": review.get("reviewed_at", ""),
    }


def answer_key(run: EvaluationRun) -> dict[str, object]:
    return {
        "warning": "Keep this file closed until blind review is complete.",
        "run_id": run.run_id,
        "answers": {
            str(row.get("question_id", "")): {
                "A": row.get("answer_a_system", ""),
                "B": row.get("answer_b_system", ""),
            }
            for row in run.rows
            if row.get("answer_a_system") and row.get("answer_b_system")
        },
    }


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def save_evaluation_run(run: EvaluationRun) -> None:
    run.metadata["updated_at"] = utc_now()
    write_json(run.metadata_path, run.metadata)
    write_json(run.responses_path, run.rows)
    write_json(run.answer_key_path, answer_key(run))
    blind_rows = [blind_row(row) for row in run.rows]
    write_csv(run.blind_csv_path, BLIND_CSV_FIELDS, blind_rows)
    run.blind_report_path.write_text(
        format_blind_report(blind_rows, run.metadata, SCORE_GUIDE),
        encoding="utf-8",
    )


def assign_blind_order(row: dict[str, object]) -> None:
    if row.get("answer_a_system") and row.get("answer_b_system"):
        return
    systems = [SYSTEM_UNDERSTUDY, SYSTEM_BASELINE]
    random.SystemRandom().shuffle(systems)
    row["answer_a_system"], row["answer_b_system"] = systems


def answers_complete(run: EvaluationRun) -> bool:
    return all(
        row.get("understudy_answer")
        and row.get("baseline_answer")
        and row.get("answer_a_system")
        and row.get("answer_b_system")
        for row in run.rows
    )


def generate_answers(run: EvaluationRun) -> None:
    if answers_complete(run):
        if run.metadata.get("status") == "generating":
            run.metadata["status"] = "reviewing"
            save_evaluation_run(run)
        return

    run.metadata["status"] = "generating"
    run.metadata.pop("last_error", None)
    save_evaluation_run(run)
    total = len(run.rows)

    try:
        for index, row in enumerate(run.rows, start=1):
            question_id = str(row["question_id"])
            question = str(row["question"])
            if not row.get("understudy_answer"):
                print(f"[{index}/{total}] Generating Answer A/B for {question_id}...")
                row["understudy_answer"] = generate_understudy_answer(
                    question,
                    rules_path=run.rules_path,
                    syllabus_path=run.syllabus_path,
                    model=str(run.metadata["model"]),
                )
                save_evaluation_run(run)
            if not row.get("baseline_answer"):
                row["baseline_answer"] = generate_baseline_answer(
                    question,
                    syllabus_path=run.syllabus_path,
                    model=str(run.metadata["model"]),
                )
                save_evaluation_run(run)
            assign_blind_order(row)
            save_evaluation_run(run)
    except Exception as error:
        run.metadata["status"] = "interrupted"
        run.metadata["last_error"] = str(error)
        save_evaluation_run(run)
        raise RuntimeError(
            f"Evaluation generation stopped: {error}\n"
            f"Progress was saved. Resume with: {resume_command(run)}"
        ) from error

    run.metadata["status"] = "reviewing"
    run.metadata.pop("last_error", None)
    save_evaluation_run(run)


def prompt_score(label: str, input_fn: Callable[[str], str]) -> int | None:
    while True:
        value = input_fn(f"{label} teacher-fit score [0-3, Q=save and stop]: ").strip()
        if value.casefold() == "q":
            return None
        if value in {"0", "1", "2", "3"}:
            return int(value)
        print("Please enter 0, 1, 2, 3, or Q.")


def prompt_yes_no(label: str, input_fn: Callable[[str], str]) -> bool:
    while True:
        value = (
            input_fn(f"Does {label} go beyond the syllabus? [y/N]: ")
            .strip()
            .lower()
        )
        if value in {"", "n", "no"}:
            return False
        if value in {"y", "yes"}:
            return True
        print("Please enter Y or N.")


def prompt_preference(input_fn: Callable[[str], str]) -> str:
    while True:
        value = input_fn("Which answer would you use? [A/B/T=tie]: ").strip().upper()
        if value in {"A", "B", "T"}:
            return value
        print("Please enter A, B, or T.")


def review_answers(
    run: EvaluationRun, input_fn: Callable[[str], str] = input
) -> bool:
    if not answers_complete(run):
        raise ValueError("Answer generation is incomplete; resume generation first.")

    pending = [row for row in run.rows if not _is_reviewed(row)]
    if not pending:
        finalize_evaluation(run)
        return True

    print("\nBLIND TEACHER REVIEW")
    print("The system identities stay hidden until every question is scored.")
    print("Teacher-fit score:")
    print(SCORE_GUIDE)

    total = len(run.rows)
    for row in run.rows:
        if _is_reviewed(row):
            continue
        position = run.rows.index(row) + 1
        blind = blind_row(row)
        print("\n" + "=" * 72)
        print(f"QUESTION {position} OF {total} — {blind['question_id']}")
        print(f"\nQuestion:\n{blind['question']}")
        print(f"\nANSWER A\n{'-' * 72}\n{blind['answer_a']}")
        print(f"\nANSWER B\n{'-' * 72}\n{blind['answer_b']}")

        answer_a_score = prompt_score("Answer A", input_fn)
        if answer_a_score is None:
            save_evaluation_run(run)
            return False
        answer_b_score = prompt_score("Answer B", input_fn)
        if answer_b_score is None:
            save_evaluation_run(run)
            return False

        review = {
            "answer_a_score": answer_a_score,
            "answer_b_score": answer_b_score,
            "answer_a_syllabus_overshoot": prompt_yes_no("Answer A", input_fn),
            "answer_b_syllabus_overshoot": prompt_yes_no("Answer B", input_fn),
            "preferred_answer": prompt_preference(input_fn),
            "reviewer_notes": input_fn("Optional notes (press Enter to skip): ").strip(),
            "reviewed_at": utc_now(),
        }
        row["review"] = review
        save_evaluation_run(run)
        print("Saved this review.")

    finalize_evaluation(run)
    return True


def _is_reviewed(row: dict[str, object]) -> bool:
    review = row.get("review")
    return isinstance(review, dict) and bool(review.get("reviewed_at"))


def system_value(row: dict[str, object], field: str, system: str) -> object:
    review = row.get("review")
    if not isinstance(review, dict):
        return ""
    if row.get("answer_a_system") == system:
        return review.get(f"answer_a_{field}", "")
    if row.get("answer_b_system") == system:
        return review.get(f"answer_b_{field}", "")
    return ""


def preferred_system(row: dict[str, object]) -> str:
    review = row.get("review")
    if not isinstance(review, dict):
        return ""
    preferred = review.get("preferred_answer")
    if preferred == "T":
        return "tie"
    if preferred == "A":
        return str(row.get("answer_a_system", ""))
    if preferred == "B":
        return str(row.get("answer_b_system", ""))
    return ""


def final_row(row: dict[str, object]) -> dict[str, object]:
    review = row.get("review")
    if not isinstance(review, dict):
        review = {}
    return {
        "question_id": row.get("question_id", ""),
        "question": row.get("question", ""),
        "understudy_answer": row.get("understudy_answer", ""),
        "baseline_answer": row.get("baseline_answer", ""),
        "understudy_rule_score": system_value(row, "score", SYSTEM_UNDERSTUDY),
        "baseline_rule_score": system_value(row, "score", SYSTEM_BASELINE),
        "understudy_syllabus_overshoot": system_value(
            row, "syllabus_overshoot", SYSTEM_UNDERSTUDY
        ),
        "baseline_syllabus_overshoot": system_value(
            row, "syllabus_overshoot", SYSTEM_BASELINE
        ),
        "preferred_system": preferred_system(row),
        "reviewer_notes": review.get("reviewer_notes", ""),
    }


def finalize_evaluation(run: EvaluationRun) -> None:
    if not all(_is_reviewed(row) for row in run.rows):
        return
    rows = [final_row(row) for row in run.rows]
    write_csv(run.final_csv_path, FINAL_CSV_FIELDS, rows)
    run.metadata["status"] = "complete"
    run.metadata["completed_at"] = utc_now()
    run.final_report_path.write_text(
        format_final_report(rows, run.metadata), encoding="utf-8"
    )
    save_evaluation_run(run)


def resume_command(run: EvaluationRun) -> str:
    return f"python run_eval.py --teacher {run.workspace.teacher_id} --resume {run.run_id}"


def run_console(args: argparse.Namespace) -> None:
    workspace = resolve_teacher(args.teacher)
    if args.resume:
        run = load_evaluation_run(workspace, args.resume)
        print(f"Resuming evaluation {run.run_id} for {workspace.display_name}.")
    else:
        run = create_evaluation_run(workspace, args.question_directory)
        print(f"Created evaluation {run.run_id} for {workspace.display_name}.")
        print(f"Saved under: {project_relative(run.root)}")

    if run.metadata.get("status") == "complete":
        print(
            "This evaluation is already complete: "
            f"{project_relative(run.final_report_path)}"
        )
        return

    generate_answers(run)
    print(f"\nGenerated {len(run.rows)} blind answer pair(s).")
    print(f"Blind worksheet: {project_relative(run.blind_report_path)}")

    if args.no_review:
        print(f"Review later with: {resume_command(run)}")
        return

    completed = review_answers(run)
    if completed:
        print("\n" + "=" * 72)
        print(f"Evaluation complete for {workspace.display_name}.")
        print(f"Final report: {project_relative(run.final_report_path)}")
        print(f"Scored data: {project_relative(run.final_csv_path)}")
    else:
        print(f"\nReview saved. Continue later with: {resume_command(run)}")


def main() -> None:
    args = parse_arguments()
    try:
        run_console(args)
    except (EOFError, KeyboardInterrupt):
        print("\nStopped. Completed answers and reviews have been saved.")
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
