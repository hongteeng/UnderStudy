"""Create a tutor-reviewable rules draft from lesson transcripts."""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)
from teacher_workspace import resolve_teacher


PROJECT_ROOT = Path(__file__).parent
PROMPT_PATH = PROJECT_ROOT / "prompts" / "extract_rules_prompt.md"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a tutor-reviewable rules draft from lesson transcripts."
    )
    parser.add_argument(
        "--teacher",
        default=None,
        help="Teacher ID or display name. Required when more than one teacher exists.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Markdown path to write. Defaults to the selected teacher's "
            "rule_drafts/<transcript_name>_rules_draft.md."
        ),
    )
    return parser.parse_args()


def load_transcripts(transcript_directory: Path) -> tuple[str, list[str]]:
    if not transcript_directory.is_dir():
        raise FileNotFoundError(
            "No transcript directory found. Add text transcripts to "
            f"{transcript_directory}."
        )

    sources = []
    names = []
    for path in sorted(transcript_directory.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        content = path.read_text(encoding="utf-8").strip()
        if content:
            try:
                relative_path = path.resolve().relative_to(PROJECT_ROOT.resolve())
            except ValueError:
                relative_path = path.resolve()
            sources.append(f"## Source: {relative_path}\n{content}")
            names.append(path.stem)

    if not sources:
        raise ValueError(f"No non-empty transcripts found in {transcript_directory}.")
    return "\n\n".join(sources), names


def default_output_path(transcript_names: list[str], rule_drafts_dir: Path) -> Path:
    combined_name = "_and_".join(transcript_names)
    return rule_drafts_dir / f"{combined_name}_rules_draft.md"


def load_extraction_prompt() -> str:
    if not PROMPT_PATH.is_file():
        raise FileNotFoundError(f"Missing extraction prompt: {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def generate_draft(instructions: str, transcripts: str) -> str:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is missing. Add it to your local .env file.")

    model = os.getenv("OPENAI_MODEL", "gpt-5.6-sol")
    client = OpenAI()
    try:
        response = client.responses.create(
            model=model,
            instructions=instructions,
            input=f"# Source transcripts\n\n{transcripts}",
        )
    except AuthenticationError as error:
        raise RuntimeError("OpenAI rejected the API key. Check OPENAI_API_KEY.") from error
    except RateLimitError as error:
        raise RuntimeError("The API request was rate-limited or has no quota.") from error
    except APIConnectionError as error:
        raise RuntimeError("Could not connect to the OpenAI API.") from error
    except APIError as error:
        raise RuntimeError(f"OpenAI API error: {error}") from error

    draft = response.output_text.strip()
    if not draft:
        raise RuntimeError("The extraction model returned an empty rules draft.")
    return draft


def main() -> None:
    args = parse_arguments()
    workspace = resolve_teacher(args.teacher)
    workspace.ensure_directories()
    instructions = load_extraction_prompt()
    transcripts, transcript_names = load_transcripts(workspace.transcripts_dir)
    draft = generate_draft(instructions, transcripts)

    output_path = args.output or default_output_path(
        transcript_names, workspace.rule_drafts_dir
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(draft + "\n", encoding="utf-8")
    print(f"Tutor-reviewable rules draft written to {output_path}")
    print(
        f"Review it with: python review_rules.py --teacher {workspace.teacher_id} "
        f"{output_path}"
    )


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, RuntimeError, ValueError, UnicodeDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
