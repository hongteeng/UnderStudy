"""Teacher-specific storage for every stage of the UnderStudy pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.resolve()
TEACHERS_ROOT = PROJECT_ROOT / "data" / "teachers"
TEACHER_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify_teacher_name(name: str) -> str:
    """Return a stable, filesystem-safe ID derived from a display name."""
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")
    if slug:
        return slug
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"teacher-{digest}"


@dataclass(frozen=True)
class TeacherWorkspace:
    teacher_id: str
    display_name: str
    root: Path

    @property
    def metadata_path(self) -> Path:
        return self.root / "teacher.json"

    @property
    def rules_path(self) -> Path:
        return self.root / "rules.md"

    @property
    def syllabus_path(self) -> Path:
        return self.root / "syllabus.md"

    @property
    def incoming_dir(self) -> Path:
        return self.root / "recordings" / "incoming"

    @property
    def processed_dir(self) -> Path:
        return self.root / "recordings" / "processed"

    @property
    def manifest_path(self) -> Path:
        return self.root / "recordings" / "transcription_manifest.json"

    @property
    def transcripts_dir(self) -> Path:
        return self.root / "transcripts"

    @property
    def rule_drafts_dir(self) -> Path:
        return self.root / "rule_drafts"

    @property
    def internal_dir(self) -> Path:
        return self.root / "internal"

    @property
    def lock_path(self) -> Path:
        return self.internal_dir / "transcription.lock"

    @property
    def results_dir(self) -> Path:
        return self.root / "results"

    @property
    def evaluation_runs_dir(self) -> Path:
        return self.results_dir / "evaluations"

    def ensure_directories(self) -> None:
        for directory in (
            self.incoming_dir,
            self.processed_dir,
            self.transcripts_dir,
            self.rule_drafts_dir,
            self.internal_dir,
            self.results_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _metadata(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read teacher profile {path}: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Teacher profile must contain a JSON object: {path}")
    return data


def list_teachers() -> list[TeacherWorkspace]:
    if not TEACHERS_ROOT.is_dir():
        return []
    teachers: list[TeacherWorkspace] = []
    for root in sorted(TEACHERS_ROOT.iterdir()):
        metadata_path = root / "teacher.json"
        if not root.is_dir() or not metadata_path.is_file():
            continue
        data = _metadata(metadata_path)
        teacher_id = str(data.get("teacher_id") or root.name)
        display_name = str(data.get("display_name") or teacher_id)
        teachers.append(TeacherWorkspace(teacher_id, display_name, root.resolve()))
    return teachers


def resolve_teacher(identifier: str | None = None) -> TeacherWorkspace:
    """Find a teacher by ID or display name, with a one-teacher convenience default."""
    requested = (identifier or os.getenv("UNDERSTUDY_TEACHER") or "").strip()
    teachers = list_teachers()
    if requested:
        matches = [
            teacher
            for teacher in teachers
            if teacher.teacher_id.casefold() == requested.casefold()
            or teacher.display_name.casefold() == requested.casefold()
        ]
        if len(matches) == 1:
            return matches[0]
        available = ", ".join(
            f"{teacher.teacher_id} ({teacher.display_name})" for teacher in teachers
        ) or "none"
        raise ValueError(f"Unknown teacher '{requested}'. Available teachers: {available}.")
    if len(teachers) == 1:
        return teachers[0]
    if not teachers:
        raise ValueError("No teacher exists yet. Run: python main.py")
    available = ", ".join(teacher.teacher_id for teacher in teachers)
    raise ValueError(
        f"More than one teacher exists ({available}). Pass --teacher <teacher-id>."
    )


def create_or_get_teacher(display_name: str) -> tuple[TeacherWorkspace, bool]:
    """Load an existing teacher or create an isolated workspace for a new one."""
    cleaned_name = " ".join(display_name.split())
    if not cleaned_name:
        raise ValueError("Teacher name cannot be empty.")

    existing = list_teachers()
    for teacher in existing:
        if (
            teacher.display_name.casefold() == cleaned_name.casefold()
            or teacher.teacher_id.casefold() == cleaned_name.casefold()
        ):
            teacher.ensure_directories()
            return teacher, False

    base_id = slugify_teacher_name(cleaned_name)
    teacher_id = base_id
    used_ids = {teacher.teacher_id.casefold() for teacher in existing}
    suffix = 2
    while teacher_id.casefold() in used_ids or (TEACHERS_ROOT / teacher_id).exists():
        teacher_id = f"{base_id}-{suffix}"
        suffix += 1

    if not TEACHER_ID_PATTERN.fullmatch(teacher_id):
        raise ValueError(f"Could not create a safe teacher ID from: {cleaned_name}")

    workspace = TeacherWorkspace(
        teacher_id=teacher_id,
        display_name=cleaned_name,
        root=(TEACHERS_ROOT / teacher_id).resolve(),
    )
    workspace.ensure_directories()
    metadata = {
        "version": 1,
        "teacher_id": teacher_id,
        "display_name": cleaned_name,
        "created_at": utc_now(),
    }
    workspace.metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    workspace.rules_path.write_text(
        f"# {cleaned_name}'s teaching rules\n", encoding="utf-8"
    )
    return workspace, True


def project_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())
