"""Interactively resolve a generated tutor-rules draft in the terminal.

The review engine is intentionally separate from the prompt presentation so a
future web interface can reuse ``resolve_draft`` with different decision
providers.

Examples:
    python review_rules.py --teacher hong-ting
    python review_rules.py --teacher hong-ting path/to/lesson_rules_draft.md
    python review_rules.py --teacher hong-ting --apply
"""

from __future__ import annotations

import argparse
import re
import shutil
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
    apply_draft,
    check_no_unresolved_markers,
    split_sections,
    validate_draft,
)
from teacher_workspace import TeacherWorkspace, resolve_teacher


Action = Literal["keep", "edit", "custom", "exclude"]
META_DECISION_SECTION = "Needs tutor decision"
DRAFT_ONLY_SECTIONS = (
    "Review status",
    META_DECISION_SECTION,
    "Review summary",
    "Source coverage",
)
REVIEW_START = "> ⚠ **REVIEW REQUIRED**"
FIELD_PATTERN = re.compile(
    r"^>\s*\*\*(POINT TO REVIEW|IF KEEP|IF EDIT|IF EXCLUDE|RULE AS DRAFTED|"
    r"ISSUE WITH THIS RULE|SUGGESTED REVISION):\*\*\s*(.*)$"
)
FIELD_ALIASES = {
    "POINT TO REVIEW": "issue",
    "ISSUE WITH THIS RULE": "issue",
    "IF KEEP": "rule",
    "RULE AS DRAFTED": "rule",
    "IF EDIT": "suggestion",
    "SUGGESTED REVISION": "suggestion",
    "IF EXCLUDE": "exclude",
}
SOURCE_PATTERN = re.compile(r"Source:\s*`([^`]+)`")
SOURCE_CITATION_PATTERN = re.compile(r"\(([^()]*)\)\s*$")
HEADING_PATTERN = re.compile(r"^##\s+(.+?)\s*$")


@dataclass(frozen=True)
class ReviewBlock:
    start: int
    end: int
    section: str
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


@dataclass(frozen=True)
class DecisionContext:
    draft_rules: tuple[str, ...] = ()
    transcript_excerpts: tuple[str, ...] = ()


ReviewProvider = Callable[[ReviewBlock, int, int], ReviewResolution]
InlineProvider = Callable[[InlineDecision, int, int], str | None]


CONTEXT_STOP_WORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "but",
    "confirm",
    "confirmation",
    "decide",
    "does",
    "every",
    "for",
    "from",
    "full",
    "has",
    "have",
    "into",
    "its",
    "needs",
    "not",
    "only",
    "provide",
    "required",
    "rule",
    "rules",
    "source",
    "state",
    "that",
    "the",
    "their",
    "there",
    "this",
    "through",
    "tutor",
    "use",
    "uses",
    "whether",
    "with",
    "wording",
}


def parse_review_blocks(text: str) -> list[ReviewBlock]:
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)

    blocks: list[ReviewBlock] = []
    index = 0
    current_section = "Document"
    while index < len(lines):
        heading = HEADING_PATTERN.match(lines[index].rstrip("\r\n"))
        if heading:
            current_section = heading.group(1)
            index += 1
            continue
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
                current_field = FIELD_ALIASES[match.group(1)]
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
                section=current_section,
                source=source,
                point=fields.get("issue", "Review this drafted rule."),
                keep=fields.get("rule") or None,
                edit=fields.get("suggestion") or None,
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
    rule = re.sub(
        r"^\*\*(?:IF KEEP|IF EDIT|RULE AS DRAFTED|SUGGESTED REVISION):\*\*\s*",
        "",
        rule,
    )
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


def legacy_meta_decisions(text: str) -> list[str]:
    """Find old-style missing-content questions that are not rule review blocks."""
    decisions: list[str] = []
    current_section = "Document"
    for line in text.splitlines():
        heading = HEADING_PATTERN.match(line)
        if heading:
            current_section = heading.group(1)
            continue
        if current_section != META_DECISION_SECTION or not re.match(r"^\s*-\s+", line):
            continue
        plain = re.sub(r"[*_`]", "", line).strip().casefold()
        if plain.startswith(("- none", "- no separate", "- no tutor")):
            continue
        decisions.append(line.strip())
    return decisions


def decision_from_line(
    line: str, line_number: int, section: str
) -> InlineDecision:
    source_match = SOURCE_CITATION_PATTERN.search(line.strip())
    source = (
        source_match.group(1).split(",", 1)[0].strip()
        if source_match
        else "source transcript"
    )
    lead_match = re.match(r"^\s*-\s*(\*\*[^*]+:\*\*)", line)
    return InlineDecision(
        line_number=line_number,
        section=section,
        original_line=line,
        source=source,
        lead=lead_match.group(1) if lead_match else None,
    )


def parse_inline_decisions(text: str) -> list[InlineDecision]:
    """Return decision markers embedded in normal rule sections only."""
    decisions: list[InlineDecision] = []
    current_section = "Document"
    for line_number, line in enumerate(text.splitlines(), start=1):
        heading = HEADING_PATTERN.match(line)
        if heading:
            current_section = heading.group(1)
            continue
        if current_section in DRAFT_ONLY_SECTIONS or "Needs tutor decision" not in line:
            continue
        decisions.append(decision_from_line(line, line_number, current_section))
    return decisions


def context_terms(text: str) -> set[str]:
    cleaned = re.sub(r"\([^()]*\)\s*$", "", text)
    words = re.findall(r"[a-z0-9]+", cleaned.casefold())
    aliases = {
        "oxidizing": "oxidising",
        "oxidized": "oxidised",
        "increases": "increase",
        "increased": "increase",
        "questions": "question",
        "students": "student",
    }
    return {
        aliases.get(word, word)
        for word in words
        if len(word) > 2 and word not in CONTEXT_STOP_WORDS
    }


def ranked_context(
    query: str, candidates: list[str], *, limit: int = 2
) -> tuple[str, ...]:
    query_terms = context_terms(query)
    scored: list[tuple[int, int, str]] = []
    for position, candidate in enumerate(candidates):
        overlap = len(query_terms & context_terms(candidate))
        if overlap:
            scored.append((overlap, -position, candidate))
    scored.sort(reverse=True)
    return tuple(candidate for _, _, candidate in scored[:limit])


def draft_rule_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    current_section = "Document"
    for line in text.splitlines():
        heading = HEADING_PATTERN.match(line)
        if heading:
            current_section = heading.group(1)
            continue
        if current_section in DRAFT_ONLY_SECTIONS or not re.match(r"^\s*-\s+", line):
            continue
        candidates.append(f"[{current_section}] {line.strip()}")
    return candidates


def transcript_candidates(path: Path | None) -> list[str]:
    if path is None or not path.is_file():
        return []
    candidates: list[str] = []
    in_transcript = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "## Transcript":
            in_transcript = True
            continue
        if not in_transcript or not line.strip() or line.startswith("## "):
            continue
        candidates.append(line.strip())
    return candidates


def find_transcript(
    source: str, transcripts_dir: Path | None
) -> Path | None:
    source_path = Path(source).expanduser()
    candidates: list[Path] = []
    if source_path.is_absolute():
        candidates.append(source_path)
    if transcripts_dir is not None:
        candidates.append(transcripts_dir / source_path.name)
        if not source_path.suffix:
            candidates.append(transcripts_dir / f"{source_path.name}.md")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def decision_key(decision: InlineDecision) -> tuple[str, str]:
    return decision.section, decision.original_line.strip()


def build_decision_contexts(
    text: str, transcripts_dir: Path | None = None
) -> dict[tuple[str, str], DecisionContext]:
    """Find relevant existing rules and source passages for review prompts."""
    decisions = parse_inline_decisions(text)
    draft_candidates = draft_rule_candidates(text)
    transcript_cache: dict[str, list[str]] = {}
    contexts: dict[tuple[str, str], DecisionContext] = {}
    for decision in decisions:
        if decision.source not in transcript_cache:
            transcript_cache[decision.source] = transcript_candidates(
                find_transcript(decision.source, transcripts_dir)
            )
        contexts[decision_key(decision)] = DecisionContext(
            draft_rules=ranked_context(decision.original_line, draft_candidates),
            transcript_excerpts=ranked_context(
                decision.original_line, transcript_cache[decision.source]
            ),
        )
    return contexts


def normalise_decision_answer(
    decision: InlineDecision, replacement: str | None
) -> str | None:
    if replacement is None or not replacement.strip():
        return None
    custom = replacement.strip()
    if decision.lead and not custom.startswith("**") and not custom.startswith("-"):
        custom = f"{decision.lead} {custom}"
    return normalise_rule(custom, decision.source, tutor_edited=True)


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
        replacement = normalise_decision_answer(
            decision, provider(decision, decisions.index(decision) + 1, len(decisions))
        )
        if replacement is None:
            continue
        resolved_lines.append(replacement + "\n")
    return "".join(resolved_lines)


def clean_spacing(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n") + "\n"


def resolve_draft(
    text: str, review_provider: ReviewProvider, inline_provider: InlineProvider
) -> str:
    reviewed = resolve_review_blocks(text, review_provider)
    for section in DRAFT_ONLY_SECTIONS:
        reviewed = remove_markdown_section(reviewed, section)
    reviewed = resolve_inline_decisions(reviewed, inline_provider)
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
    print(f"RULE ISSUE {index} OF {total} — {block.section}")
    if block.keep:
        print(f"\nRule as drafted:\n  {block.keep}")
    print(f"\nWhy the AI flagged this rule:\n  {block.point}")
    if block.edit:
        print(f"\nSuggested revision:\n  {block.edit}")
    if block.keep:
        print("\n[K] Keep the drafted rule")
    if block.edit:
        print("[E] Accept the suggested revision")
    print("[C] Write your own replacement")
    print("[X] Exclude the rule")

    allowed = {"c", "x"}
    if block.keep:
        allowed.add("k")
    if block.edit:
        allowed.add("e")
    choice = prompt_choice("\nChoice: ", allowed)
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
    decision: InlineDecision,
    index: int,
    total: int,
    context: DecisionContext | None = None,
) -> str | None:
    print("\n" + "=" * 72)
    print(f"OPEN DECISION {index} OF {total} — {decision.section}")
    print(decision.original_line.strip())
    context = context or DecisionContext()
    print("\nClosest existing draft wording:")
    if context.draft_rules:
        for rule in context.draft_rules:
            print(f"  {rule}")
    else:
        print("  No related rule wording was drafted.")
    print("\nClosest source transcript wording:")
    if context.transcript_excerpts:
        for excerpt in context.transcript_excerpts:
            print(f"  {excerpt}")
    else:
        print("  No matching transcript passage was found.")
    print("\n[E] Enter the teacher's final wording")
    print("[X] Remove this undecided rule")
    choice = prompt_choice("\nChoice: ", {"e", "x"})
    if choice == "x":
        return None
    answer = input(
        "Type the final wording (label and source citation are added automatically):\n> "
    ).strip()
    while not answer:
        answer = input("The wording cannot be empty. Try again:\n> ").strip()
    return answer


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Review a generated tutor-rules draft through guided questions."
    )
    parser.add_argument(
        "--teacher",
        default=None,
        help="Teacher ID or display name. Required when more than one teacher exists.",
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


def choose_draft_path(requested_path: Path | None, rule_drafts_dir: Path) -> Path:
    if requested_path:
        path = requested_path.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Draft file not found: {requested_path}")
        return path

    if not rule_drafts_dir.is_dir():
        raise FileNotFoundError(f"No rule drafts directory found at {rule_drafts_dir}.")
    drafts = sorted(
        rule_drafts_dir.glob("*_rules_draft.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not drafts:
        raise FileNotFoundError(f"No draft files found in {rule_drafts_dir}.")

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


def review_file(draft_path: Path, transcripts_dir: Path | None = None) -> None:
    original = draft_path.read_text(encoding="utf-8")
    old_questions = legacy_meta_decisions(original)
    if old_questions:
        raise ValueError(
            "This draft uses the old missing-content review format "
            f"({len(old_questions)} open questions). Regenerate the rules draft "
            "with the current extractor before reviewing it."
        )
    review_count = len(parse_review_blocks(original))
    decision_count = len(parse_inline_decisions(original))
    print(f"Reviewing: {draft_path}")
    print(f"Rule issues to review: {review_count}")
    if decision_count:
        print(f"Legacy unresolved rule lines: {decision_count}")

    if transcripts_dir is None:
        inferred = draft_path.parent.parent / "transcripts"
        transcripts_dir = inferred if inferred.is_dir() else None
    contexts = build_decision_contexts(original, transcripts_dir)

    def contextual_provider(
        decision: InlineDecision, index: int, total: int
    ) -> str | None:
        return console_inline_provider(
            decision,
            index,
            total,
            contexts.get(decision_key(decision)),
        )

    reviewed = resolve_draft(
        original, console_review_provider, contextual_provider
    )
    validate_draft(reviewed, split_sections(reviewed))

    backup_path = draft_path.with_suffix(draft_path.suffix + ".bak")
    shutil.copy2(draft_path, backup_path)
    draft_path.write_text(reviewed, encoding="utf-8")
    print(f"\nReview complete and validated: {draft_path.name}")
    print(f"Backup saved: {backup_path.name}")


def apply_with_existing_pipeline(
    draft_path: Path, workspace: TeacherWorkspace
) -> None:
    """Apply through the existing validated merge pipeline."""
    apply_draft(draft_path, workspace.rules_path)


def main() -> None:
    args = parse_arguments()
    try:
        workspace = resolve_teacher(args.teacher)
        draft_path = choose_draft_path(args.draft, workspace.rule_drafts_dir)
        try:
            draft_path.resolve().relative_to(workspace.rule_drafts_dir.resolve())
        except ValueError as error:
            raise ValueError(
                f"Draft does not belong to teacher {workspace.display_name}: {draft_path}"
            ) from error
        review_file(draft_path, workspace.transcripts_dir)

        should_apply = args.apply
        if not args.apply and not args.no_apply_prompt:
            should_apply = prompt_choice(
                f"Apply these rules to {workspace.display_name}'s rules.md now? [y/N]: ",
                {"y", "n"},
                "n",
            ) == "y"
        if should_apply:
            apply_with_existing_pipeline(draft_path, workspace)
        else:
            print(
                "To apply later: python apply_rules.py "
                f"--teacher {workspace.teacher_id} {draft_path}"
            )
    except (FileNotFoundError, RuntimeError, ValueError, UnicodeDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
