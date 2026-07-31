"""Merge a tutor-reviewed rules draft into data/rules.md.

This is the coded version of the "review the draft, then copy approved
content into data/rules.md" step described in the README. It makes no
content decisions of its own -- it only merges text that a tutor has already
resolved directly in the draft file (every inline review marker and every
"Needs tutor decision" item must be gone before this will run).

Usage:
    python apply_rules.py                          # auto-detects the draft
    python apply_rules.py data/rule_drafts/foo.md   # applies a specific draft
    python apply_rules.py --check                  # validate only, no write
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).parent
RULES_PATH = PROJECT_ROOT / "data" / "rules.md"
RULE_DRAFTS_DIR = PROJECT_ROOT / "data" / "rule_drafts"

# Canonical section order, matching the template in
# prompts/extract_rules_prompt.md and the existing structure of rules.md.
SECTION_ORDER = [
    "Student-request types and recognition cues",
    "Tutor response approaches",
    "Required and preferred vocabulary",
    "Wording to avoid or qualify",
    "Topic map and reusable explanations",
    "Analogies and examples to reuse",
    "Misconceptions to pre-empt",
    "Syllabus boundaries",
    "Build Examples",
]

# Draft-only sections that must never be copied into rules.md.
META_SECTIONS = {"Review status", "Needs tutor decision", "Review summary", "Source coverage"}

# Sections whose items are multi-paragraph and must be split on their own
# "### " subheadings instead of on blank lines -- a single Build Example
# routinely contains several paragraphs (question, talk-through, final
# answer) that belong together as one block.
HEADING_DELIMITED_SECTIONS = {"Build Examples"}


def split_blocks(title: str, body: str) -> "list[str]":
    """Split a section body into its individual rule/example blocks."""
    if not body.strip():
        return []
    if title in HEADING_DELIMITED_SECTIONS:
        blocks = re.split(r"\n(?=###\s)", body.strip())
    else:
        blocks = re.split(r"\n\s*\n", body)
    return [block.strip() for block in blocks if block.strip()]

# If any of these strings are still present, the draft has not been fully
# reviewed and this script refuses to touch rules.md.
UNRESOLVED_MARKERS = ("REVIEW REQUIRED", "Needs tutor decision", "IF KEEP", "IF EDIT", "IF EXCLUDE")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge a tutor-reviewed rules draft into data/rules.md."
    )
    parser.add_argument(
        "draft",
        type=Path,
        nargs="?",
        default=None,
        help=(
            "Path to the reviewed draft file. If omitted and exactly one "
            f"file exists in {RULE_DRAFTS_DIR}, that file is used."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate the draft (unresolved markers, missing source tags) "
            "without writing to rules.md."
        ),
    )
    return parser.parse_args()


def resolve_draft_path(arg_path: Optional[Path]) -> Path:
    if arg_path:
        if not arg_path.is_file():
            raise FileNotFoundError(f"Draft file not found: {arg_path}")
        return arg_path
    if not RULE_DRAFTS_DIR.is_dir():
        raise FileNotFoundError(f"No rule drafts directory found at {RULE_DRAFTS_DIR}.")
    drafts = sorted(RULE_DRAFTS_DIR.glob("*_rules_draft.md"))
    if not drafts:
        raise FileNotFoundError(f"No draft files found in {RULE_DRAFTS_DIR}.")
    if len(drafts) > 1:
        names = ", ".join(path.name for path in drafts)
        raise ValueError(
            f"Multiple drafts found ({names}). Pass the one to apply "
            "explicitly: python apply_rules.py data/rule_drafts/<file>."
        )
    return drafts[0]


def check_no_unresolved_markers(draft_text: str) -> "list[str]":
    return [marker for marker in UNRESOLVED_MARKERS if marker in draft_text]


def find_untagged_blocks(sections: "dict[str, str]") -> "list[tuple[str, str]]":
    """Return (section_title, block_text) for every substantive block that
    has no `(...)` source citation at all -- not just a missing match for
    this particular source_key, but no citation whatsoever."""
    untagged = []
    for title, body in sections.items():
        if title in META_SECTIONS or not body.strip():
            continue
        for block in split_blocks(title, body):
            if not re.search(r"\([^()]*\)\s*$", block):
                untagged.append((title, block))
    return untagged


def validate_draft(draft_text: str, sections: "dict[str, str]") -> None:
    problems = check_no_unresolved_markers(draft_text)
    if problems:
        raise ValueError(
            "This draft still has unresolved review markers: "
            f"{', '.join(problems)}. Open the draft file yourself, decide "
            "each one, and delete the marker text before applying it. This "
            "script will not make content decisions for you."
        )

    untagged = find_untagged_blocks(sections)
    if untagged:
        listed = "\n".join(
            f"  - [{title}] {block.splitlines()[0][:80]}..." for title, block in untagged
        )
        raise ValueError(
            "This draft has rule(s) with no source citation in parentheses "
            f"at the end, e.g. `(data/transcripts/<name>)`:\n{listed}\n"
            "Add a source tag to each before applying -- without one, this "
            "rule can never be identified or replaced on a future re-apply."
        )


def split_sections(text: str) -> "dict[str, str]":
    """Split a rules document into {section_title: body_text}."""
    sections: "dict[str, str]" = {}
    current_title = None
    current_lines: "list[str]" = []
    for line in text.splitlines():
        heading = re.match(r"^##\s+(.*)$", line)
        if heading:
            if current_title is not None:
                sections[current_title] = "\n".join(current_lines).strip("\n")
            current_title = heading.group(1).strip()
            current_lines = []
        elif current_title is not None:
            current_lines.append(line)
    if current_title is not None:
        sections[current_title] = "\n".join(current_lines).strip("\n")
    return sections


def source_key_from_draft(draft_path: Path) -> str:
    stem = draft_path.stem
    suffix = "_rules_draft"
    return stem[: -len(suffix)] if stem.endswith(suffix) else stem


def remove_blocks_for_source(title: str, body: str, source_key: str) -> str:
    """Drop existing blocks tagged with this source, so re-applying an
    updated draft replaces old content instead of duplicating it."""
    if not body.strip():
        return body
    kept = [block for block in split_blocks(title, body) if source_key not in block]
    return "\n\n".join(kept).strip("\n")


def merge(existing_text: str, draft_text: str, source_key: str) -> str:
    existing_sections = split_sections(existing_text)
    draft_sections = split_sections(draft_text)

    for title in META_SECTIONS:
        draft_sections.pop(title, None)

    merged_sections = dict(existing_sections)
    for title, draft_body in draft_sections.items():
        current_body = remove_blocks_for_source(title, merged_sections.get(title, ""), source_key)
        new_body = draft_body.strip("\n")
        if not new_body:
            merged_sections[title] = current_body
            continue
        merged_sections[title] = (
            f"{current_body}\n\n{new_body}".strip("\n") if current_body else new_body
        )

    ordered_titles = [title for title in SECTION_ORDER if title in merged_sections]
    ordered_titles += [title for title in merged_sections if title not in ordered_titles]

    header = existing_text.split("\n## ", 1)[0].rstrip("\n")
    parts = [header] if header.strip() else []
    for title in ordered_titles:
        body = merged_sections[title]
        parts.append(f"## {title}\n\n{body}".rstrip("\n"))
    return "\n\n".join(parts).strip("\n") + "\n"


def main() -> None:
    args = parse_arguments()
    draft_path = resolve_draft_path(args.draft)
    draft_text = draft_path.read_text(encoding="utf-8")
    draft_sections = split_sections(draft_text)
    validate_draft(draft_text, draft_sections)

    if args.check:
        print(f"{draft_path.name} is fully resolved and ready to apply.")
        return

    existing_text = RULES_PATH.read_text(encoding="utf-8") if RULES_PATH.is_file() else ""
    source_key = source_key_from_draft(draft_path)
    merged_text = merge(existing_text, draft_text, source_key)

    RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    RULES_PATH.write_text(merged_text, encoding="utf-8")
    print(f"Applied {draft_path.name} into {RULES_PATH}")
    print(f"Any prior '{source_key}' content in rules.md was replaced, not duplicated.")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
