"""Automatically turn lesson recordings into speaker-labelled transcripts.

The default one-shot mode processes every settled audio file in
``data/recordings/incoming``. Use ``--watch`` to keep the worker running and
``--extract-rules`` to create a tutor-reviewable rules draft after each
successful transcription.

Examples:
    python transcribe_recordings.py
    python transcribe_recordings.py --watch --extract-rules
    python transcribe_recordings.py --retry-failed --extract-rules
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)


PROJECT_ROOT = Path(__file__).parent
DEFAULT_INCOMING_DIR = PROJECT_ROOT / "data" / "recordings" / "incoming"
DEFAULT_PROCESSED_DIR = PROJECT_ROOT / "data" / "recordings" / "processed"
DEFAULT_TRANSCRIPTS_DIR = PROJECT_ROOT / "data" / "transcripts" / "raw"
DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT / "data" / "recordings" / "transcription_manifest.json"
)
DEFAULT_LOCK_PATH = PROJECT_ROOT / "data" / "internal" / "transcription.lock"
DEFAULT_MODEL = "gpt-4o-transcribe-diarize"
DEFAULT_MAX_UPLOAD_BYTES = 24 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}
MANIFEST_VERSION = 1


@dataclass(frozen=True)
class Settings:
    incoming_dir: Path
    processed_dir: Path
    transcripts_dir: Path
    manifest_path: Path
    lock_path: Path
    model: str
    language: str | None
    teacher_name: str | None
    teacher_reference: Path | None
    max_upload_bytes: int
    settle_seconds: float
    poll_seconds: float
    api_retries: int


@dataclass(frozen=True)
class TranscriptResult:
    transcript_path: Path
    processed_audio_path: Path
    segment_count: int
    duration_seconds: float | None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser().resolve() if value else default


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe new lesson recordings and archive completed audio."
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep watching the incoming folder instead of running once.",
    )
    parser.add_argument(
        "--extract-rules",
        action="store_true",
        help="Create a rules draft from each newly written transcript.",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry recordings or rule drafts previously marked as failed.",
    )
    parser.add_argument(
        "--incoming",
        type=Path,
        default=None,
        help="Override the incoming recordings folder.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"Transcription model (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--teacher-name",
        default=None,
        help="Speaker label to use with --teacher-reference.",
    )
    parser.add_argument(
        "--teacher-reference",
        type=Path,
        default=None,
        help="A clear 2–10 second recording of the teacher for speaker matching.",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=None,
        help="Wait until a recording has stopped changing for this many seconds.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=None,
        help="Seconds between folder scans in watch mode.",
    )
    return parser.parse_args()


def load_settings(args: argparse.Namespace) -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    incoming_dir = (
        args.incoming.expanduser().resolve()
        if args.incoming
        else env_path("UNDERSTUDY_INCOMING_DIR", DEFAULT_INCOMING_DIR)
    )
    teacher_reference_value = args.teacher_reference or (
        Path(os.environ["TEACHER_REFERENCE_AUDIO"])
        if os.getenv("TEACHER_REFERENCE_AUDIO")
        else None
    )
    teacher_reference = (
        teacher_reference_value.expanduser().resolve()
        if teacher_reference_value
        else None
    )
    teacher_name = args.teacher_name or os.getenv("TEACHER_SPEAKER_NAME")
    if bool(teacher_reference) != bool(teacher_name):
        raise ValueError(
            "Set both TEACHER_REFERENCE_AUDIO and TEACHER_SPEAKER_NAME, or neither."
        )
    if teacher_reference and not teacher_reference.is_file():
        raise FileNotFoundError(f"Teacher reference audio not found: {teacher_reference}")

    max_upload_mb = float(os.getenv("TRANSCRIPTION_MAX_UPLOAD_MB", "24"))
    settle_seconds = (
        args.settle_seconds
        if args.settle_seconds is not None
        else float(os.getenv("UNDERSTUDY_SETTLE_SECONDS", "20"))
    )
    poll_seconds = (
        args.poll_seconds
        if args.poll_seconds is not None
        else float(os.getenv("UNDERSTUDY_POLL_SECONDS", "30"))
    )
    api_retries = int(os.getenv("TRANSCRIPTION_API_RETRIES", "3"))
    if settle_seconds < 0 or poll_seconds <= 0 or max_upload_mb <= 0 or api_retries < 1:
        raise ValueError("Timing, upload-size, and retry settings must be positive.")

    return Settings(
        incoming_dir=incoming_dir,
        processed_dir=env_path("UNDERSTUDY_PROCESSED_DIR", DEFAULT_PROCESSED_DIR),
        transcripts_dir=env_path("UNDERSTUDY_TRANSCRIPTS_DIR", DEFAULT_TRANSCRIPTS_DIR),
        manifest_path=env_path("UNDERSTUDY_MANIFEST_PATH", DEFAULT_MANIFEST_PATH),
        lock_path=DEFAULT_LOCK_PATH,
        model=args.model or os.getenv("OPENAI_TRANSCRIPTION_MODEL", DEFAULT_MODEL),
        language=os.getenv("TRANSCRIPTION_LANGUAGE") or None,
        teacher_name=teacher_name,
        teacher_reference=teacher_reference,
        max_upload_bytes=int(max_upload_mb * 1024 * 1024),
        settle_seconds=settle_seconds,
        poll_seconds=poll_seconds,
        api_retries=api_retries,
    )


class ManifestStore:
    def __init__(self, path: Path):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"version": MANIFEST_VERSION, "recordings": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            raise ValueError(f"Could not read transcription manifest: {error}") from error
        if data.get("version") != MANIFEST_VERSION or not isinstance(
            data.get("recordings"), dict
        ):
            raise ValueError(f"Unsupported transcription manifest: {self.path}")
        return data

    @property
    def recordings(self) -> dict[str, dict[str, Any]]:
        return self.data["recordings"]

    def get(self, fingerprint: str) -> dict[str, Any] | None:
        return self.recordings.get(fingerprint)

    def update(self, fingerprint: str, **fields: Any) -> None:
        record = self.recordings.setdefault(fingerprint, {})
        record.update(fields)
        record["updated_at"] = utc_now()
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(self.path)


@contextmanager
def single_worker_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = path.open("a+", encoding="utf-8")
    try:
        try:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            pass
        except BlockingIOError as error:
            raise RuntimeError("Another lesson transcription worker is already running.") from error
        yield
    finally:
        lock_file.close()


def iter_recordings(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file()
        and not path.name.startswith(".")
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def is_settled(path: Path, settle_seconds: float, now: float | None = None) -> bool:
    current_time = time.time() if now is None else now
    return current_time - path.stat().st_mtime >= settle_seconds


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def unique_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    number = 2
    while True:
        candidate = directory / f"{stem}_{number}{suffix}"
        if not candidate.exists():
            return candidate
        number += 1


def safe_stem(path: Path) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in path.stem
    ).strip("_")
    return cleaned or "lesson"


def run_command(arguments: list[str]) -> None:
    result = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"Audio preparation failed: {detail}")


def prepare_audio_parts(
    source: Path, temporary_dir: Path, max_upload_bytes: int
) -> list[Path]:
    if source.stat().st_size <= max_upload_bytes:
        return [source]

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            f"{source.name} is larger than the upload limit. Install ffmpeg "
            "(`brew install ffmpeg`) so long recordings can be compressed and split."
        )

    compressed = temporary_dir / "compressed.mp3"
    run_command(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "32k",
            str(compressed),
        ]
    )
    if compressed.stat().st_size <= max_upload_bytes:
        return [compressed]

    part_pattern = temporary_dir / "part_%03d.mp3"
    run_command(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(compressed),
            "-f",
            "segment",
            "-segment_time",
            "2700",
            "-reset_timestamps",
            "1",
            "-c",
            "copy",
            str(part_pattern),
        ]
    )
    parts = sorted(temporary_dir.glob("part_*.mp3"))
    if not parts:
        raise RuntimeError("ffmpeg did not produce any audio segments.")
    oversized = [part.name for part in parts if part.stat().st_size > max_upload_bytes]
    if oversized:
        raise RuntimeError(f"Prepared audio segment is still too large: {oversized[0]}")
    return parts


def audio_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "audio/wav"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def response_payload(response: Any) -> dict[str, Any]:
    if isinstance(response, str):
        return {"text": response, "segments": []}
    if hasattr(response, "model_dump"):
        payload = response.model_dump()
    elif isinstance(response, dict):
        payload = response
    else:
        payload = {
            "text": getattr(response, "text", ""),
            "duration": getattr(response, "duration", None),
            "segments": getattr(response, "segments", []),
        }
    payload.setdefault("segments", [])
    return payload


def retryable_api_error(error: Exception) -> bool:
    if isinstance(error, (APIConnectionError, APITimeoutError, RateLimitError)):
        return True
    return isinstance(error, APIStatusError) and error.status_code >= 500


def transcribe_part(
    client: OpenAI,
    part: Path,
    settings: Settings,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    uses_diarization = settings.model == "gpt-4o-transcribe-diarize"
    parameters: dict[str, Any] = {
        "model": settings.model,
        "response_format": "diarized_json" if uses_diarization else "json",
    }
    if uses_diarization:
        parameters["chunking_strategy"] = "auto"
    if settings.language:
        parameters["language"] = settings.language
    if settings.teacher_reference and settings.teacher_name:
        if not uses_diarization:
            raise ValueError(
                "Teacher speaker matching requires gpt-4o-transcribe-diarize."
            )
        parameters["known_speaker_names"] = [settings.teacher_name]
        parameters["known_speaker_references"] = [
            audio_data_url(settings.teacher_reference)
        ]

    for attempt in range(1, settings.api_retries + 1):
        try:
            with part.open("rb") as audio_file:
                response = client.audio.transcriptions.create(file=audio_file, **parameters)
            return response_payload(response)
        except (AuthenticationError, PermissionDeniedError, BadRequestError):
            raise
        except APIError as error:
            if attempt == settings.api_retries or not retryable_api_error(error):
                raise
            sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError("Transcription retry loop ended unexpectedly.")


def segment_value(segment: Any, field: str, default: Any = None) -> Any:
    if isinstance(segment, dict):
        return segment.get(field, default)
    return getattr(segment, field, default)


def combine_transcription_payloads(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    combined_segments: list[dict[str, Any]] = []
    fallback_texts: list[str] = []
    offset = 0.0
    duration_known = False

    for part_number, payload in enumerate(payloads, start=1):
        segments = payload.get("segments") or []
        maximum_end = 0.0
        for segment in segments:
            start = float(segment_value(segment, "start", 0.0) or 0.0)
            end = float(segment_value(segment, "end", start) or start)
            maximum_end = max(maximum_end, end)
            combined_segments.append(
                {
                    "speaker": str(segment_value(segment, "speaker", "Speaker")),
                    "start": start + offset,
                    "end": end + offset,
                    "text": str(segment_value(segment, "text", "")).strip(),
                    "part": part_number,
                }
            )
        text = str(payload.get("text") or "").strip()
        if text and not segments:
            fallback_texts.append(text)
        part_duration = payload.get("duration")
        if part_duration is not None:
            part_duration = float(part_duration)
            duration_known = True
        else:
            part_duration = maximum_end
            duration_known = duration_known or bool(maximum_end)
        offset += part_duration

    return {
        "segments": combined_segments,
        "text": "\n\n".join(fallback_texts),
        "duration": offset if duration_known else None,
    }


def format_timestamp(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def render_transcript(
    source: Path, model: str, combined: dict[str, Any], teacher_name: str | None
) -> str:
    lines = [
        "# Lesson transcript",
        "",
        f"- Source recording: `{source.name}`",
        f"- Transcribed at: {utc_now()}",
        f"- Transcription model: `{model}`",
    ]
    duration = combined.get("duration")
    if duration is not None:
        lines.append(f"- Approximate duration: {format_timestamp(float(duration))}")
    if teacher_name:
        lines.append(f"- Known teacher speaker: {teacher_name}")
    lines.extend(["", "## Transcript", ""])

    segments = combined.get("segments") or []
    if segments:
        for segment in segments:
            text = str(segment.get("text") or "").strip()
            if not text:
                continue
            start = format_timestamp(float(segment.get("start") or 0.0))
            end = format_timestamp(float(segment.get("end") or 0.0))
            speaker = str(segment.get("speaker") or "Speaker")
            lines.append(f"**[{start}–{end}] {speaker}:** {text}")
            lines.append("")
    else:
        lines.append(str(combined.get("text") or "").strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_text_atomically(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def transcribe_recording(
    source: Path, settings: Settings, client: OpenAI
) -> tuple[Path, int, float | None]:
    with tempfile.TemporaryDirectory(prefix="understudy-audio-") as temporary_name:
        temporary_dir = Path(temporary_name)
        parts = prepare_audio_parts(source, temporary_dir, settings.max_upload_bytes)
        payloads = [transcribe_part(client, part, settings) for part in parts]
    combined = combine_transcription_payloads(payloads)
    transcript_path = unique_path(
        settings.transcripts_dir, f"{safe_stem(source)}.md"
    )
    transcript = render_transcript(
        source, settings.model, combined, settings.teacher_name
    )
    write_text_atomically(transcript_path, transcript)
    return (
        transcript_path,
        len(combined.get("segments") or []),
        combined.get("duration"),
    )


def archive_recording(source: Path, processed_dir: Path) -> Path:
    destination = unique_path(processed_dir, source.name)
    shutil.move(str(source), str(destination))
    return destination


def create_rules_draft(transcript_path: Path) -> Path:
    """Hand one transcript to Hong Ting's existing rules-extraction engine.

    The extractor itself remains responsible for the prompt and model call.
    This small adapter only scopes the input to the recording that just
    finished, so a background scan does not rebuild every older transcript.
    """
    from extract_rules import (
        RULE_DRAFTS_DIR,
        generate_draft,
        load_extraction_prompt,
    )

    content = transcript_path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"Transcript is empty: {transcript_path}")
    try:
        source_label = transcript_path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        source_label = transcript_path.resolve()

    source = f"## Source: {source_label}\n{content}"
    draft = generate_draft(load_extraction_prompt(), source)
    destination = RULE_DRAFTS_DIR / f"{transcript_path.stem}_rules_draft.md"
    write_text_atomically(destination, draft.rstrip() + "\n")
    return destination


def retry_failed_rule_drafts(manifest: ManifestStore) -> None:
    for fingerprint, record in list(manifest.recordings.items()):
        if record.get("status") != "completed" or record.get("rules_status") != "failed":
            continue
        transcript_value = record.get("transcript")
        if not transcript_value:
            continue
        transcript_path = PROJECT_ROOT / transcript_value
        if not transcript_path.is_file():
            continue
        try:
            draft_path = create_rules_draft(transcript_path)
        except Exception as error:
            manifest.update(fingerprint, rules_error=str(error))
            print(f"Rule extraction still failing for {transcript_path.name}: {error}")
        else:
            manifest.update(
                fingerprint,
                rules_status="completed",
                rules_draft=display_path(draft_path),
                rules_error=None,
            )
            print(f"Rules draft written: {display_path(draft_path)}")


def scan_once(
    settings: Settings,
    extract_rules_enabled: bool,
    retry_failed: bool,
    client_factory: Callable[[], OpenAI] = OpenAI,
) -> tuple[int, int, int]:
    manifest = ManifestStore(settings.manifest_path)
    if extract_rules_enabled and retry_failed:
        retry_failed_rule_drafts(manifest)

    processed_count = 0
    skipped_count = 0
    failed_count = 0
    client: OpenAI | None = None

    for source in iter_recordings(settings.incoming_dir):
        if not is_settled(source, settings.settle_seconds):
            skipped_count += 1
            continue
        fingerprint = sha256_file(source)
        previous = manifest.get(fingerprint)
        if previous and previous.get("status") == "completed":
            duplicate_path = archive_recording(source, settings.processed_dir)
            manifest.update(
                fingerprint,
                duplicate_count=int(previous.get("duplicate_count", 0)) + 1,
                last_duplicate=display_path(duplicate_path),
            )
            print(f"Archived duplicate recording: {source.name}")
            skipped_count += 1
            continue
        if previous and previous.get("status") == "failed" and not retry_failed:
            skipped_count += 1
            continue

        attempts = int(previous.get("attempts", 0)) + 1 if previous else 1
        manifest.update(
            fingerprint,
            source_name=source.name,
            source_size=source.stat().st_size,
            status="processing",
            attempts=attempts,
            model=settings.model,
            error=None,
        )
        print(f"Transcribing {source.name}...")

        try:
            if client is None:
                if not os.getenv("OPENAI_API_KEY"):
                    raise RuntimeError(
                        "OPENAI_API_KEY is missing. Add it to the project .env file."
                    )
                client = client_factory()
            transcript_path, segment_count, duration = transcribe_recording(
                source, settings, client
            )
            processed_audio_path = archive_recording(source, settings.processed_dir)
        except Exception as error:
            manifest.update(fingerprint, status="failed", error=str(error))
            failed_count += 1
            print(f"Failed {source.name}: {error}", file=sys.stderr)
            continue

        rules_status = "skipped"
        rules_draft: str | None = None
        rules_error: str | None = None
        if extract_rules_enabled:
            try:
                rules_path = create_rules_draft(transcript_path)
            except Exception as error:
                rules_status = "failed"
                rules_error = str(error)
                print(
                    f"Transcript completed, but rule extraction failed: {error}",
                    file=sys.stderr,
                )
            else:
                rules_status = "completed"
                rules_draft = display_path(rules_path)
                print(f"Rules draft written: {rules_draft}")
                print(f"Review it with: python review_rules.py {rules_draft}")

        manifest.update(
            fingerprint,
            status="completed",
            transcript=display_path(transcript_path),
            processed_audio=display_path(processed_audio_path),
            segment_count=segment_count,
            duration_seconds=duration,
            rules_status=rules_status,
            rules_draft=rules_draft,
            rules_error=rules_error,
        )
        processed_count += 1
        print(f"Transcript written: {display_path(transcript_path)}")

    return processed_count, skipped_count, failed_count


def run(args: argparse.Namespace) -> int:
    settings = load_settings(args)
    for directory in (
        settings.incoming_dir,
        settings.processed_dir,
        settings.transcripts_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    with single_worker_lock(settings.lock_path):
        while True:
            processed, skipped, failed = scan_once(
                settings,
                extract_rules_enabled=args.extract_rules,
                retry_failed=args.retry_failed,
            )
            if not args.watch:
                print(
                    f"Finished: {processed} processed, {skipped} skipped, {failed} failed."
                )
                return 1 if failed else 0
            if processed or failed:
                print(
                    f"Scan complete: {processed} processed, {skipped} skipped, "
                    f"{failed} failed."
                )
            time.sleep(settings.poll_seconds)


def main() -> None:
    try:
        raise SystemExit(run(parse_arguments()))
    except KeyboardInterrupt:
        print("Lesson transcription worker stopped.")
        raise SystemExit(0)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
