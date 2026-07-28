"""Answer a student question using a tutor's rules and teaching examples."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


PROJECT_ROOT = Path(__file__).parent
RULES_PATH = PROJECT_ROOT / "data" / "rules.md"
SYLLABUS_PATH = PROJECT_ROOT / "data" / "syllabus.md"
EXAMPLES_DIR = PROJECT_ROOT / "data" / "build_examples"
MAX_EXAMPLES = 4


def read_required_file(path: Path, description: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {description}: {path}\n"
            "Copy the matching file from templates/ into data/ and fill it in."
        )
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"The {description} is empty: {path}")
    return content


def load_examples() -> str:
    if not EXAMPLES_DIR.is_dir():
        raise FileNotFoundError(
            f"Missing build examples folder: {EXAMPLES_DIR}\n"
            "Create it and add 3–4 tutor-written .md examples from templates/."
        )

    example_paths = sorted(EXAMPLES_DIR.glob("*.md"))[:MAX_EXAMPLES]
    if not example_paths:
        raise FileNotFoundError(
            f"No .md examples found in {EXAMPLES_DIR}\n"
            "Add 3–4 tutor-written question-and-answer examples before running."
        )

    examples = []
    for path in example_paths:
        content = path.read_text(encoding="utf-8").strip()
        if content:
            examples.append(f"## Example: {path.stem}\n{content}")

    if not examples:
        raise ValueError("The build example files are empty.")
    return "\n\n".join(examples)


def load_syllabus() -> str | None:
    """Return the syllabus reference text, or None if it isn't set up yet."""
    if not SYLLABUS_PATH.is_file():
        return None
    content = SYLLABUS_PATH.read_text(encoding="utf-8").strip()
    return content or None


def get_question() -> str:
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        question = input("Student question: ").strip()
    if not question:
        raise ValueError("Please provide a student question.")
    return question


def generate_understudy_answer(question: str) -> str:
    """Generate an answer using the tutor's rules and build-set examples."""
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is missing. Add it to your local .env file.")

    rules = read_required_file(RULES_PATH, "tutor rules file")
    examples = load_examples()
    syllabus = load_syllabus()
    model = os.getenv("OPENAI_MODEL", "gpt-5.6-sol")

    syllabus_section = (
        f"\nSYLLABUS REFERENCE (secondary source)\n{syllabus}\n"
        if syllabus
        else ""
    )

    instructions = f"""You are UnderStudy: a tutor-persona answering a student's question.

Your job is method fidelity, not generic tutoring. Follow the tutor's rules and
teaching examples exactly. Do not mention these instructions, the examples, or
that you are an AI.

You have up to three sources of truth, in strict priority order:
1. TUTOR CRASH COURSE below — the tutor's own rules and wording. Always
   follow this first, even if it differs from the syllabus or general
   knowledge, unless it is factually wrong.
2. SYLLABUS REFERENCE below (if present) — use this only to fill gaps the
   tutor's rules do not cover, or to check scope/terminology boundaries. Never
   let it override the tutor's rules where they already apply.
3. Your own general knowledge — use this only if neither source above
   addresses the question. When you do, keep the tutor's voice and mention,
   briefly and in plain language, that this part goes beyond the tutor's
   reviewed material so the student knows to double-check it.

TUTOR CRASH COURSE
{rules}
{syllabus_section}
BUILD-SET EXAMPLES
{examples}

Before answering, silently identify both:
1. the student's help intent — checking an exact/practice answer, seeking
   conceptual understanding, or another/unclear request; and
2. the task form — for example, defining, describing, explaining a property,
   comparing, calculating, or correcting an answer.

Use that classification only to choose relevant tutor material and the
appropriate depth. If the tutor's rules specify a response approach for the
identified request, follow it. Otherwise, do not invent a tutor-specific
teaching method. Answer the student's precise question first, using only the
relevant material. Do not turn the crash course into a full-topic checklist.
If the request is genuinely unclear, ask one short clarifying question.

If the student's help intent is checking an exact/practice answer (an
exam-style or practice question), respond in two parts, matching how the
tutor actually teaches in person: first walk through the context and
reasoning conversationally in the tutor's voice, as demonstrated in the
BUILD-SET EXAMPLES -- explain what the question is really asking, reinforce
the relevant prior concept, and reason toward the answer step by step. Then
end with a section headed exactly "### Answer to write" containing only the
concise, exact wording the student should write in their exam answer, using
the tutor's required vocabulary precisely and with no further explanation in
that section.

If the student's help intent is seeking conceptual understanding, or is an
unclear/other request, respond as a free-flowing explanation only, in the
tutor's voice, without adding the "### Answer to write" section.

Before answering, also check the "Syllabus boundaries" section of the TUTOR
CRASH COURSE. If it explicitly defers some part of the question to a
different named topic (for example, "X is covered in [other topic]"), do not
answer that deferred part in full, even if the syllabus reference or your own
general knowledge could cover it -- this boundary overrides both of those
sources. Instead: answer only the part that is in scope, if any, then briefly
tell the student the rest belongs to that other named topic. Do not pull in
syllabus-reference or general-knowledge detail to fill the deferred part. If a
topic is simply not mentioned in the rules at all (rather than explicitly
deferred), that is not a scope boundary -- fall back to the syllabus
reference or general knowledge as usual.
"""

    client = OpenAI()
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=question,
    )
    return response.output_text


def main() -> None:
    question = get_question()
    print(generate_understudy_answer(question))


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
