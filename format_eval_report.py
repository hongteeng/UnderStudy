"""Turn results/eval_output.csv into a clearly labeled, human-readable report.

The CSV from run_eval.py is only easy to read inside a spreadsheet app --
opened as plain text, its multi-line quoted cells run together. This script
reformats the same data into one section per question, each one clearly
labeled with its question ID, the question text, and both answers.
"""

import argparse
import csv
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent
DEFAULT_INPUT_PATH = PROJECT_ROOT / "results" / "eval_output.csv"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "results" / "eval_report.md"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Format results/eval_output.csv as a readable Markdown report."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"CSV to read (default: {DEFAULT_INPUT_PATH}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Markdown path to write (default: {DEFAULT_OUTPUT_PATH}).",
    )
    return parser.parse_args()


def load_rows(csv_path: Path) -> "list[dict]":
    if not csv_path.is_file():
        raise FileNotFoundError(
            f"No eval CSV found at {csv_path}. Run `python run_eval.py "
            "<question_directory>` first."
        )
    with csv_path.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    if not rows:
        raise ValueError(f"{csv_path} has no rows to report on.")
    return rows


def format_report(rows: "list[dict]") -> str:
    sections = ["# UnderStudy vs. baseline: evaluation report", ""]
    for index, row in enumerate(rows, start=1):
        question_id = row.get("question_id", f"question_{index}")
        question = row.get("question", "").strip()
        understudy_answer = row.get("understudy_answer", "").strip()
        baseline_answer = row.get("baseline_answer", "").strip()

        sections.append(f"## Question {index}: {question_id}")
        sections.append("")
        sections.append(f"**Question:** {question}")
        sections.append("")
        sections.append("### UnderStudy answer")
        sections.append("")
        sections.append(understudy_answer or "*(empty)*")
        sections.append("")
        sections.append("### Baseline answer")
        sections.append("")
        sections.append(baseline_answer or "*(empty)*")
        sections.append("")
        sections.append("### Reviewer notes")
        sections.append("")
        sections.append("- UnderStudy rule score: ")
        sections.append("- Baseline rule score: ")
        sections.append("- Notes: ")
        sections.append("")
        sections.append("---")
        sections.append("")
    return "\n".join(sections).rstrip() + "\n"


def main() -> None:
    args = parse_arguments()
    rows = load_rows(args.input)
    report = format_report(rows)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Wrote readable report for {len(rows)} question(s) to {args.output}")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
