"""Answer a student question using a tutor's rules and teaching examples."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


PROJECT_ROOT = Path(__file__).parent
RULES_PATH = PROJECT_ROOT / "data" / "rules.md"
SYLLABUS_PATH = PROJECT_ROOT / "data" / "syllabus.md"


def read_required_file(path: Path, description: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {description}: {path}\n"
            "Run extract_rules.py and apply_rules.py to generate it first."
        )
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"The {description} is empty: {path}")
    return content


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
1. TUTOR CRASH COURSE below — the tutor's own rules, wording, and worked
   examples. Always follow this first, even if it differs from the syllabus
   or general knowledge, unless it is factually wrong.
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

The "Build Examples" section inside the TUTOR CRASH COURSE above, if present,
holds this tutor's real answers to real questions. Study them as a set and
identify the structural pattern that repeats across most or all of them --
not quirks that appear in only one. Compare them along these axes:
- Opening move: does the tutor start with the answer, with context, or with
  reframing the question?
- Sequencing: what order are ideas introduced in, and does that order repeat
  across examples answering similar question types?
- Final-answer separation: is there a distinct section holding the polished
  answer, separate from reasoning or explanation? What is it called, if
  anything?
- Register: formal/written vs. conversational; sentence length; how much is
  spelled out vs. assumed.
- Closing move: how does the tutor end -- a summary, a direct restatement, or
  just stopping after the last point?

Reproduce whichever pattern is consistent across the examples. If the
examples disagree with each other on a given axis, do not invent a
resolution -- follow the example whose question type most closely matches
the student's current question. If there are no Build Examples yet, or too
few to show a pattern, do not invent a structure -- fall back to whatever
structure the rest of the TUTOR CRASH COURSE demonstrates. Before finalizing
your answer, check it against the axes above and adjust if it drifts from
the pattern you identified.

Before answering, silently identify both:
1. the student's help intent — checking an exact/practice answer, seeking
   conceptual understanding, or another/unclear request; and
2. the task form — for example, defining, describing, explaining a property,
   comparing, calculating, or correcting an answer.

Use that classification only to choose relevant tutor material and the
appropriate depth. If the tutor's rules specify a response approach for the
identified request, follow it. Otherwise, do not invent a tutor-specific
teaching method. Do not turn the crash course into a full-topic checklist.
If the request is genuinely unclear, ask one short clarifying question.

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
