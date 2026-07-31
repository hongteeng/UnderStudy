"""Interactive, end-to-end console workflow for one teacher's lesson audio."""

from __future__ import annotations

import argparse
import shlex
import shutil
import sys
from pathlib import Path

from apply_rules import apply_draft
from review_rules import review_file
from teacher_workspace import (
    TeacherWorkspace,
    create_or_get_teacher,
    list_teachers,
    project_relative,
)
from transcribe_recordings import (
    SUPPORTED_EXTENSIONS,
    iter_recordings,
    run,
    unique_path,
)


def prompt_teacher() -> TeacherWorkspace:
    teachers = list_teachers()
    if teachers:
        print("Existing teachers:")
        for teacher in teachers:
            print(f"  - {teacher.display_name} [{teacher.teacher_id}]")
        print()

    while True:
        name = input("Teacher name: ").strip()
        try:
            workspace, created = create_or_get_teacher(name)
        except ValueError as error:
            print(f"Please try again: {error}")
            continue
        state = "Created" if created else "Using"
        print(f"{state} workspace for {workspace.display_name} [{workspace.teacher_id}].")
        print(f"Teacher rules: {project_relative(workspace.rules_path)}")
        return workspace


def parse_audio_entry(entry: str) -> list[Path]:
    """Parse pasted, quoted, or macOS drag-and-drop file paths."""
    whole_path = Path(entry.strip().strip("\"'")).expanduser()
    if whole_path.exists():
        return [whole_path.resolve()]
    try:
        parts = shlex.split(entry)
    except ValueError as error:
        raise ValueError(f"Could not read that path: {error}") from error
    return [Path(part).expanduser().resolve() for part in parts]


def audio_files_from_path(path: Path) -> list[Path]:
    if not path.exists():
        raise FileNotFoundError(f"File or folder not found: {path}")
    if path.is_dir():
        files = sorted(
            candidate
            for candidate in path.iterdir()
            if candidate.is_file()
            and not candidate.name.startswith(".")
            and candidate.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        if not files:
            raise ValueError(f"No supported audio files found in: {path}")
        return files
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported audio type for {path.name}. Supported: {supported}")
    return [path]


def stage_audio(source: Path, workspace: TeacherWorkspace) -> Path:
    workspace.incoming_dir.mkdir(parents=True, exist_ok=True)
    try:
        source.resolve().relative_to(workspace.incoming_dir.resolve())
    except ValueError:
        destination = unique_path(workspace.incoming_dir, source.name)
        shutil.copy2(source, destination)
        return destination
    return source.resolve()


def prompt_for_audio(workspace: TeacherWorkspace) -> list[Path]:
    print("\nAdd lesson recordings.")
    print("Paste a file or folder path (you can also drag it into this terminal).")
    print("Press Enter on an empty line when finished.")

    staged: list[Path] = []
    while True:
        entry = input("Audio path: ").strip()
        if not entry:
            break
        try:
            sources = [
                audio
                for path in parse_audio_entry(entry)
                for audio in audio_files_from_path(path)
            ]
            for source in sources:
                destination = stage_audio(source, workspace)
                staged.append(destination)
                print(f"Added: {destination.name}")
        except (FileNotFoundError, OSError, ValueError) as error:
            print(f"Could not add audio: {error}")
    return staged


def transcription_arguments(workspace: TeacherWorkspace) -> argparse.Namespace:
    return argparse.Namespace(
        teacher=workspace.teacher_id,
        watch=False,
        extract_rules=True,
        retry_failed=True,
        reset=None,
        incoming=None,
        model=None,
        teacher_name=None,
        teacher_reference=None,
        settle_seconds=0,
        poll_seconds=None,
    )


def review_and_apply(workspace: TeacherWorkspace, draft_paths: list[Path]) -> int:
    applied = 0
    for index, draft_path in enumerate(draft_paths, start=1):
        print("\n" + "=" * 72)
        print(f"RULE REVIEW {index} OF {len(draft_paths)}")
        review_file(draft_path)
        choice = input(
            f"Apply this lesson to {workspace.display_name}'s rules.md? [Y/n]: "
        ).strip().lower()
        if choice not in {"n", "no"}:
            apply_draft(draft_path, workspace.rules_path)
            applied += 1
        else:
            print(f"Not applied. The reviewed draft remains at {draft_path}.")
    return applied


def run_wizard() -> None:
    print("\nUnderStudy teacher setup and lesson pipeline\n")
    workspace = prompt_teacher()
    prompt_for_audio(workspace)

    queued = iter_recordings(workspace.incoming_dir)
    if not queued:
        print("\nNo recordings are waiting. You can run python main.py again later.")
        return

    print(f"\nProcessing {len(queued)} recording(s) for {workspace.display_name}...")
    existing_drafts = set(workspace.rule_drafts_dir.glob("*_rules_draft.md"))
    result = run(transcription_arguments(workspace))
    new_drafts = sorted(
        set(workspace.rule_drafts_dir.glob("*_rules_draft.md")) - existing_drafts,
        key=lambda path: path.stat().st_mtime,
    )

    if not new_drafts:
        if result:
            print("No rule drafts were created because processing did not complete.")
        else:
            print("No new rule drafts were created (the recordings may be duplicates).")
        return

    applied = review_and_apply(workspace, new_drafts)
    print("\n" + "=" * 72)
    print(f"Finished for {workspace.display_name}.")
    print(f"Reviewed {len(new_drafts)} draft(s); applied {applied}.")
    print(f"Rules file: {project_relative(workspace.rules_path)}")
    if result:
        print("Some recordings failed. They remain queued and will retry next time.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the interactive UnderStudy teacher and lesson workflow."
    )
    parser.parse_args()
    try:
        run_wizard()
    except (EOFError, KeyboardInterrupt):
        print("\nStopped. Existing files and completed work have been kept.")
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
