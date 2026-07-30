"""Run UnderStudy and the plain-GPT baseline over a folder of questions."""

import argparse
import csv
import re
from pathlib import Path

from answer import generate_understudy_answer
from baseline import generate_baseline_answer
from format_eval_report import format_report


PROJECT_ROOT = Path(__file__).parent
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "results" / "eval_output.csv"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "results" / "eval_report.md"
CSV_FIELDS = [
    "question_id",
    "question",
    "understudy_answer",
    "baseline_answer",
    "understudy_rule_score",
    "baseline_rule_score",
    "understudy_syllabus_overshoot",
    "baseline_syllabus_overshoot",
    "reviewer_notes",
]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run both answer systems on Markdown files in a supplied question directory."
        )
    )
    parser.add_argument(
        "question_directory",
        type=Path,
        help="Folder containing one Markdown question file per evaluation item.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"CSV path to write (default: {DEFAULT_OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help=(
            f"Readable Markdown report path to write (default: {DEFAULT_REPORT_PATH}). "
            "Written automatically alongside the CSV on every run."
        ),
    )
    return parser.parse_args()


def natural_sort_key(path: Path) -> tuple:
    """Sort filenames like q2, q10 in numeric order (2, 10) instead of
    lexicographic order (10, 2), while still sorting sensibly if a filename
    has no leading number at all."""
    match = re.search(r"\d+", path.stem)
    number = int(match.group()) if match else float("inf")
    return (number, path.stem)


def load_questions(question_directory: Path) -> list[tuple[str, str]]:
    if not question_directory.is_dir():
        raise FileNotFoundError(
            f"Question directory does not exist: {question_directory}"
        )

    question_files = sorted(question_directory.glob("*.md"), key=natural_sort_key)
    if not question_files:
        raise FileNotFoundError(
            f"No Markdown question files found in: {question_directory}"
        )

    questions = []
    for question_file in question_files:
        question = question_file.read_text(encoding="utf-8").strip()
        if not question:
            raise ValueError(f"Question file is empty: {question_file}")
        questions.append((question_file.stem, question))
    return questions


def main() -> None:
    args = parse_arguments()
    questions = load_questions(args.question_directory)

    rows = []
    for question_id, question in questions:
        print(f"Running {question_id}...")
        rows.append(
            {
                "question_id": question_id,
                "question": question,
                "understudy_answer": generate_understudy_answer(question),
                "baseline_answer": generate_baseline_answer(question),
                "understudy_rule_score": "",
                "baseline_rule_score": "",
                "understudy_syllabus_overshoot": "",
                "baseline_syllabus_overshoot": "",
                "reviewer_notes": "",
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Evaluation output written to {args.output}")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(format_report(rows), encoding="utf-8")
    print(f"Readable report written to {args.report}")


if __name__ == "__main__":
    main()
