"""Format blind worksheets and completed UnderStudy evaluation reports."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent
DEFAULT_INPUT_PATH = PROJECT_ROOT / "results" / "eval_output.csv"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "results" / "eval_report.md"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Format an evaluation CSV as a readable Markdown report."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.is_file():
        raise FileNotFoundError(
            f"No evaluation CSV found at {csv_path}. Run run_eval.py first."
        )
    with csv_path.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    if not rows:
        raise ValueError(f"{csv_path} has no rows to report on.")
    return rows


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _yes_no(value: object) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return "Yes" if _text(value).casefold() in {"true", "yes", "y", "1"} else "No"


def _score_values(rows: list[dict[str, object]], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(field, "")
        if value in {"", None}:
            continue
        try:
            values.append(float(str(value)))
        except ValueError:
            continue
    return values


def _average(values: list[float]) -> str:
    return f"{sum(values) / len(values):.2f}" if values else "Not scored"


def format_blind_report(
    rows: list[dict[str, object]],
    metadata: dict[str, object],
    score_guide: str,
) -> str:
    reviewed_count = sum(bool(_text(row.get("reviewed_at", ""))) for row in rows)
    sections = [
        "# Blind evaluation worksheet",
        "",
        f"Teacher: {_text(metadata.get('teacher_name'))}",
        f"Run: {_text(metadata.get('run_id'))}",
        f"Progress: {reviewed_count}/{len(rows)} questions reviewed",
        "",
        "Answer identities are deliberately hidden. Do not open the `internal` "
        "folder until the review is finished.",
        "",
        "## Scoring guide",
        "",
        "```text",
        score_guide,
        "```",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        sections.extend(
            [
                f"## Question {index}: {_text(row.get('question_id'))}",
                "",
                _text(row.get("question")),
                "",
                "### Answer A",
                "",
                _text(row.get("answer_a")) or "*(generation pending)*",
                "",
                "### Answer B",
                "",
                _text(row.get("answer_b")) or "*(generation pending)*",
                "",
                "### Blind review",
                "",
                f"- Answer A score: {_text(row.get('answer_a_score'))}",
                f"- Answer B score: {_text(row.get('answer_b_score'))}",
                "- Answer A syllabus overshoot: "
                + (
                    _yes_no(row.get("answer_a_syllabus_overshoot"))
                    if _text(row.get("reviewed_at"))
                    else ""
                ),
                "- Answer B syllabus overshoot: "
                + (
                    _yes_no(row.get("answer_b_syllabus_overshoot"))
                    if _text(row.get("reviewed_at"))
                    else ""
                ),
                f"- Preferred answer: {_text(row.get('preferred_answer'))}",
                f"- Notes: {_text(row.get('reviewer_notes'))}",
                "",
                "---",
                "",
            ]
        )
    return "\n".join(sections).rstrip() + "\n"


def format_final_report(
    rows: list[dict[str, object]], metadata: dict[str, object] | None = None
) -> str:
    metadata = metadata or {}
    baseline_type = _text(metadata.get("baseline_type")) or "baseline"
    baseline_title = (
        "Syllabus-only baseline"
        if baseline_type == "syllabus-only"
        else "Generic baseline"
    )
    understudy_scores = _score_values(rows, "understudy_rule_score")
    baseline_scores = _score_values(rows, "baseline_rule_score")
    understudy_preferences = sum(
        _text(row.get("preferred_system")) == "understudy" for row in rows
    )
    baseline_preferences = sum(
        _text(row.get("preferred_system")) == "syllabus_baseline" for row in rows
    )
    ties = sum(_text(row.get("preferred_system")) == "tie" for row in rows)
    understudy_overshoots = sum(
        _yes_no(row.get("understudy_syllabus_overshoot")) == "Yes" for row in rows
    )
    baseline_overshoots = sum(
        _yes_no(row.get("baseline_syllabus_overshoot")) == "Yes" for row in rows
    )

    title = "# UnderStudy evaluation report"
    sections = [title, ""]
    if metadata:
        sections.extend(
            [
                f"- Teacher: {_text(metadata.get('teacher_name'))}",
                f"- Run: {_text(metadata.get('run_id'))}",
                f"- Model: {_text(metadata.get('model'))}",
                f"- Questions: {len(rows)}",
                f"- Baseline: {baseline_title}",
                f"- Created: {_text(metadata.get('created_at'))}",
                f"- Completed: {_text(metadata.get('completed_at'))}",
                "",
            ]
        )

    sections.extend(
        [
            "## Summary",
            "",
            "| Measure | UnderStudy | " + baseline_title + " |",
            "|---|---:|---:|",
            f"| Average teacher-fit score (0–3) | {_average(understudy_scores)} | {_average(baseline_scores)} |",
            f"| Preferred answers | {understudy_preferences} | {baseline_preferences} |",
            f"| Syllabus overshoots | {understudy_overshoots} | {baseline_overshoots} |",
            "",
            f"Ties: {ties}",
            "",
        ]
    )

    for index, row in enumerate(rows, start=1):
        preferred = _text(row.get("preferred_system"))
        preferred_label = {
            "understudy": "UnderStudy",
            "syllabus_baseline": baseline_title,
            "tie": "Tie",
        }.get(preferred, preferred or "Not recorded")
        sections.extend(
            [
                f"## Question {index}: {_text(row.get('question_id'))}",
                "",
                f"**Question:** {_text(row.get('question'))}",
                "",
                "### UnderStudy answer",
                "",
                _text(row.get("understudy_answer")) or "*(empty)*",
                "",
                "### " + baseline_title + " answer",
                "",
                _text(row.get("baseline_answer")) or "*(empty)*",
                "",
                "### Review result",
                "",
                f"- UnderStudy teacher-fit score: {_text(row.get('understudy_rule_score'))}",
                f"- {baseline_title} teacher-fit score: {_text(row.get('baseline_rule_score'))}",
                "- UnderStudy syllabus overshoot: "
                + _yes_no(row.get("understudy_syllabus_overshoot")),
                f"- {baseline_title} syllabus overshoot: "
                + _yes_no(row.get("baseline_syllabus_overshoot")),
                f"- Preferred answer: {preferred_label}",
                f"- Notes: {_text(row.get('reviewer_notes')) or 'None'}",
                "",
                "---",
                "",
            ]
        )
    return "\n".join(sections).rstrip() + "\n"


def format_report(rows: list[dict[str, object]]) -> str:
    """Backward-compatible name used by older callers."""
    return format_final_report(rows)


def main() -> None:
    args = parse_arguments()
    rows = load_rows(args.input)
    report = format_final_report(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Wrote readable report for {len(rows)} question(s) to {args.output}")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
