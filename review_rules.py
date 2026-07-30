"""Interactively resolve a generated tutor-rules draft in the terminal.

The review engine is intentionally separate from the prompt presentation so a
future web interface can reuse ``resolve_draft`` with different decision
providers.

Examples:
    python review_rules.py
    python review_rules.py data/rule_drafts/lesson_rules_draft.md
    python review_rules.py --apply
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

try:
    import readline  # noqa: F401 -- importing it enables arrow-key/history
    # editing in input() prompts below. Without this import, Python's input()
    # has no line-editing support and arrow keys print raw escape codes
    # (e.g. "^[[D") instead of moving the cursor. Not available on Windows,
    # where input() falls back to its more limited default behavior.
except ImportError:
    pass

from apply_rules import (
    PROJECT_ROOT,
    RULE_DRAFTS_DIR,
    check_no_unresolved_markers,
    split_sections,
    validate_draft,
)


Action = Literal["keep", "edit", "custom", "exclude"]
META_DECISION_SECTION = "Needs tutor decision"
DRAFT_ONLY_SECTIONS = (
    "Review status",
    "Needs tutor decision",
    "Review summary",
    "Source coverage",
)
REVIEW_START = "> ⚠ **REVIEW REQUIRED**"
FIELD_PATTERN = re.compile(
    r"^>\s*\*\*(POINT TO REVIEW|IF KEEP|IF EDIT|IF EXCLUDE):\*\*\s*(.*)$"
)
SOURCE_PATTERN = re.compile(r"Source:\s*`([^`]+)`")
SOURCE_CITATION_PATTERN = re.compile(r"\(([^()]*)\)\s*$")
HEADING_PATTERN = re.compile(r"^##\s+(.+?)\s*$")


@dataclass(frozen=True)
class ReviewBlock:
    start: int
    end: int
    source: str
    point: str
    keep: str | None
    edit: str | None


@dataclass(frozen=True)
class ReviewResolution:
    action: Action
    custom_text: str | None = None


@dataclass(frozen=True)
class InlineDecision:
    line_number: int
    section: str
    original_line: str
    source: str
    lead: str | None


ReviewProvider = Callable[[ReviewBlock, int, int], ReviewResolution]
InlineProvider = Callable[[InlineDecision, int, int], str | None]


def parse_review_blocks(text: str) -> list[ReviewBlock]:
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)

    blocks: list[ReviewBlock] = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith(REVIEW_START):
            index += 1
            continue

        start_index = index
        block_lines = [lines[index].rstrip("\r\n")]
        index += 1
        while index < len(lines) and lines[index].startswith(">"):
            block_lines.append(lines[index].rstrip("\r\n"))
            index += 1

        source_match = SOURCE_PATTERN.search(block_lines[0])
        source = source_match.group(1) if source_match else "source transcript"
        fields: dict[str, str] = {}
        current_field: str | None = None
        for line in block_lines[1:]:
            match = FIELD_PATTERN.match(line)
            if match:
                current_field = match.group(1)
                fields[current_field] = match.group(2).strip()
            elif current_field:
                continuation = line.removeprefix("> ").strip()
                if continuation:
                    fields[current_field] += " " + continuation

        end = offsets[index] if index < len(lines) else len(text)
        blocks.append(
            ReviewBlock(
                start=offsets[start_index],
                end=end,
                source=source,
                point=fields.get("POINT TO REVIEW", "Review this extracted rule."),
                keep=fields.get("IF KEEP") or None,
                edit=fields.get("IF EDIT") or None,
            )
        )
    return blocks


def strip_quote_prefix(text: str) -> str:
    return " ".join(
        line.removeprefix("> ").strip() for line in text.splitlines() if line.strip()
    ).strip()


def extract_source_from_rule(rule: str, fallback: str) -> str:
    match = SOURCE_CITATION_PATTERN.search(rule.strip())
    if not match:
        return fallback
    citation = match.group(1).split(",", 1)[0].strip()
    return citation or fallback


def normalise_rule(text: str, source: str, tutor_edited: bool) -> str:
    rule = strip_quote_prefix(text).strip()
    rule = re.sub(r"^\*\*(?:IF KEEP|IF EDIT):\*\*\s*", "", rule)
    if not rule.startswith("-"):
        rule = f"- {rule}"
    elif not rule.startswith("- "):
        rule = "- " + rule[1:].lstrip()

    if not SOURCE_CITATION_PATTERN.search(rule):
        suffix = f"({source}, tutor-edited)" if tutor_edited else f"({source})"
        rule = f"{rule.rstrip()} {suffix}"
    return rule


def resolve_review_blocks(text: str, provider: ReviewProvider) -> str:
    blocks = parse_review_blocks(text)
    replacements: list[tuple[int, int, str]] = []
    for index, block in enumerate(blocks, start=1):
        resolution = provider(block, index, len(blocks))
        if resolution.action == "exclude":
            replacement = ""
        elif resolution.action == "keep":
            if not block.keep:
                raise ValueError("This review block has no original rule to keep.")
            source = extract_source_from_rule(block.keep, block.source)
            replacement = normalise_rule(block.keep, source, tutor_edited=False)
        elif resolution.action == "edit":
            if not block.edit:
                raise ValueError("This review block has no suggested edit.")
            source = extract_source_from_rule(block.edit, block.source)
            replacement = normalise_rule(block.edit, source, tutor_edited=True)
        else:
            if not resolution.custom_text or not resolution.custom_text.strip():
                raise ValueError("A custom rule cannot be empty.")
            replacement = normalise_rule(
                resolution.custom_text, block.source, tutor_edited=True
            )
        replacements.append((block.start, block.end, replacement))

    for start, end, replacement in reversed(replacements):
        text = text[:start] + replacement + text[end:]
    return text


def remove_markdown_section(text: str, title: str) -> str:
    pattern = re.compile(
        rf"(?ms)^##\s+{re.escape(title)}\s*\n.*?(?=^##\s+|\Z)"
    )
    return pattern.sub("", text)


def parse_inline_decisions(text: str) -> list[InlineDecision]:
    decisions: list[InlineDecision] = []
    current_section = "Document"
    for line_number, line in enumerate(text.splitlines(), start=1):
        heading = HEADING_PATTERN.match(line)
        if heading:
            current_section = heading.group(1)
            continue
        if "Needs tutor decision" not in line:
            continue
        source_match = SOURCE_CITATION_PATTERN.search(line.strip())
        source = (
            source_match.group(1).split(",", 1)[0].strip()
            if source_match
            else "source transcript"
        )
        lead_match = re.match(r"^\s*-\s*(\*\*[^*]+:\*\*)", line)
        decisions.append(
            InlineDecision(
                line_number=line_number,
                section=current_section,
                original_line=line,
                source=source,
                lead=lead_match.group(1) if lead_match else None,
            )
        )
    return decisions


def resolve_inline_decisions(text: str, provider: InlineProvider) -> str:
    decisions = parse_inline_decisions(text)
    if not decisions:
        return text
    by_line = {decision.line_number: decision for decision in decisions}
    resolved_lines: list[str] = []
    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        decision = by_line.get(line_number)
        if not decision:
            resolved_lines.append(line)
            continue
        replacement = provider(decision, decisions.index(decision) + 1, len(decisions))
        if replacement is None or not replacement.strip():
            continue
        custom = replacement.strip()
        if decision.lead and not custom.startswith("**") and not custom.startswith("-"):
            custom = f"{decision.lead} {custom}"
        resolved_lines.append(
            normalise_rule(custom, decision.source, tutor_edited=True) + "\n"
        )
    return "".join(resolved_lines)


def clean_spacing(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n") + "\n"


def resolve_draft(
    text: str, review_provider: ReviewProvider, inline_provider: InlineProvider
) -> str:
    reviewed = resolve_review_blocks(text, review_provider)
    reviewed = remove_markdown_section(reviewed, META_DECISION_SECTION)
    reviewed = resolve_inline_decisions(reviewed, inline_provider)
    for section in DRAFT_ONLY_SECTIONS:
        reviewed = remove_markdown_section(reviewed, section)
    return clean_spacing(reviewed)


def prompt_choice(prompt: str, allowed: set[str], default: str | None = None) -> str:
    while True:
        answer = input(prompt).strip().lower()
        if not answer and default:
            return default
        if answer in allowed:
            return answer
        print(f"Choose one of: {', '.join(sorted(allowed))}")


def console_review_provider(
    block: ReviewBlock, index: int, total: int
) -> ReviewResolution:
    print("\n" + "=" * 72)
    print(f"REVIEW {index} OF {total}")
    print(f"Issue: {block.point}")
    if block.keep:
        print(f"\n[K] Keep original\n    {block.keep}")
    if block.edit:
        print(f"\n[E] Use suggested edit\n    {block.edit}")
    print("\n[C] Type a custom rule")
    print("[X] Exclude this rule")

    allowed = {"c", "x"}
    if block.keep:
        allowed.add("k")
    if block.edit:
        allowed.add("e")
    default = "e" if block.edit else ("k" if block.keep else None)
    choice = prompt_choice(
        f"\nChoice{f' [{default.upper()}]' if default else ''}: ", allowed, default
    )
    if choice == "c":
        custom = input(
            "Type the final rule (the source citation is added automatically):\n> "
        ).strip()
        while not custom:
            custom = input("The rule cannot be empty. Try again:\n> ").strip()
        return ReviewResolution("custom", custom)
    actions: dict[str, Action] = {
        "k": "keep",
        "e": "edit",
        "x": "exclude",
    }
    return ReviewResolution(actions[choice])


def console_inline_provider(
    decision: InlineDecision, index: int, total: int
) -> str | None:
    print("\n" + "=" * 72)
    print(f"OPEN DECISION {index} OF {total} — {decision.section}")
    print(decision.original_line.strip())
    print("\n[E] Enter the teacher's final wording")
    print("[X] Remove this undecided rule")
    choice = prompt_choice("\nChoice [X]: ", {"e", "x"}, "x")
    if choice == "x":
        return None
    return input(
        "Type the final wording (label and source citation are added automatically):\n> "
    ).strip()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Review a generated tutor-rules draft through guided questions."
    )
    parser.add_argument(
        "draft",
        type=Path,
        nargs="?",
        default=None,
        help="Draft to review; auto-detected when exactly one draft exists.",
    )
    apply_group = parser.add_mutually_exclusive_group()
    apply_group.add_argument(
        "--apply", action="store_true", help="Apply immediately after validation."
    )
    apply_group.add_argument(
        "--no-apply-prompt",
        action="store_true",
        help="Save and validate without asking whether to apply.",
    )
    return parser.parse_args()


def choose_draft_path(requested_path: Path | None) -> Path:
    if requested_path:
        path = requested_path.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Draft file not found: {requested_path}")
        return path

    if not RULE_DRAFTS_DIR.is_dir():
        raise FileNotFoundError(f"No rule drafts directory found at {RULE_DRAFTS_DIR}.")
    drafts = sorted(
        RULE_DRAFTS_DIR.glob("*_rules_draft.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not drafts:
        raise FileNotFoundError(f"No draft files found in {RULE_DRAFTS_DIR}.")

    unresolved = [
        path
        for path in drafts
        if check_no_unresolved_markers(path.read_text(encoding="utf-8"))
    ]
    candidates = unresolved or drafts
    if len(candidates) == 1:
        return candidates[0]

    print("Available drafts:")
    for index, path in enumerate(candidates, start=1):
        status = (
            "needs review"
            if check_no_unresolved_markers(path.read_text(encoding="utf-8"))
            else "already resolved"
        )
        print(f"  [{index}] {path.name} — {status}")
    while True:
        choice = input("Select a draft [1]: ").strip() or "1"
        if choice.isdigit() and 1 <= int(choice) <= len(candidates):
            return candidates[int(choice) - 1]
        print(f"Enter a number from 1 to {len(candidates)}.")


def review_file(draft_path: Path) -> None:
    original = draft_path.read_text(encoding="utf-8")
    review_count = len(parse_review_blocks(original))
    without_meta = remove_markdown_section(original, META_DECISION_SECTION)
    decision_count = len(parse_inline_decisions(without_meta))
    print(f"Reviewing: {draft_path}")
    print(f"Questions: {review_count} flagged rules, {decision_count} open decisions")

    reviewed = resolve_draft(
        original, console_review_provider, console_inline_provider
    )
    validate_draft(reviewed, split_sections(reviewed))

    backup_path = draft_path.with_suffix(draft_path.suffix + ".bak")
    shutil.copy2(draft_path, backup_path)
    draft_path.write_text(reviewed, encoding="utf-8")
    print(f"\nReview complete and validated: {draft_path.name}")
    print(f"Backup saved: {backup_path.name}")


def apply_with_existing_pipeline(draft_path: Path) -> None:
    """Apply through Hong Ting's original command instead of replacing it."""
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "apply_rules.py"), str(draft_path)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(detail)
    if result.stdout.strip():
        print(result.stdout.strip())


def main() -> None:
    args = parse_arguments()
    try:
        draft_path = choose_draft_path(args.draft)
        review_file(draft_path)

        should_apply = args.apply
        if not args.apply and not args.no_apply_prompt:
            should_apply = prompt_choice(
                "Apply these rules to data/rules.md now? [y/N]: ", {"y", "n"}, "n"
            ) == "y"
        if should_apply:
            apply_with_existing_pipeline(draft_path)
        else:
            print(f"To apply later: python apply_rules.py {draft_path}")
    except (FileNotFoundError, RuntimeError, ValueError, UnicodeDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
