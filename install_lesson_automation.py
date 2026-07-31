"""Install or remove the macOS background lesson-transcription worker.

The installer creates a user LaunchAgent that starts at login and keeps
``transcribe_recordings.py --watch --extract-rules`` running in the background.
Use ``--dry-run`` to inspect the generated plist without changing macOS.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from teacher_workspace import TeacherWorkspace, resolve_teacher


PROJECT_ROOT = Path(__file__).parent.resolve()
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"


def label_for(workspace: TeacherWorkspace) -> str:
    return f"com.understudy.lesson-automation.{workspace.teacher_id}"


def plist_path_for(workspace: TeacherWorkspace) -> Path:
    return LAUNCH_AGENTS_DIR / f"{label_for(workspace)}.plist"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the UnderStudy lesson worker as a macOS LaunchAgent."
    )
    parser.add_argument(
        "--teacher",
        default=None,
        help="Teacher ID or display name. Required when more than one teacher exists.",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--uninstall", action="store_true", help="Remove the worker.")
    action.add_argument(
        "--dry-run", action="store_true", help="Print the plist without installing it."
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Automatically retry items marked failed on later scans.",
    )
    return parser.parse_args()


def launch_domain() -> str:
    return f"gui/{os.getuid()}"


def worker_python() -> Path:
    virtualenv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if not virtualenv_python.is_file():
        raise FileNotFoundError(
            f"Virtual-environment Python not found: {virtualenv_python}\n"
            "Follow SETUP.md before installing the automation."
        )
    return virtualenv_python


def build_plist(
    workspace: TeacherWorkspace, retry_failed: bool = False
) -> dict[str, object]:
    arguments = [
        str(worker_python()),
        str(PROJECT_ROOT / "transcribe_recordings.py"),
        "--watch",
        "--extract-rules",
        "--teacher",
        workspace.teacher_id,
    ]
    if retry_failed:
        arguments.append("--retry-failed")
    log_directory = workspace.internal_dir
    return {
        "Label": label_for(workspace),
        "ProgramArguments": arguments,
        "WorkingDirectory": str(PROJECT_ROOT),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "ThrottleInterval": 10,
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
        "StandardOutPath": str(log_directory / "lesson_automation.log"),
        "StandardErrorPath": str(log_directory / "lesson_automation_error.log"),
    }


def run_launchctl(arguments: list[str], allow_failure: bool = False) -> None:
    result = subprocess.run(
        ["launchctl", *arguments], capture_output=True, text=True, check=False
    )
    if result.returncode and not allow_failure:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"launchctl failed: {detail}")


def install(workspace: TeacherWorkspace, retry_failed: bool) -> None:
    plist = build_plist(workspace, retry_failed)
    workspace.internal_dir.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    plist_path = plist_path_for(workspace)
    temporary = plist_path.with_suffix(".plist.tmp")
    with temporary.open("wb") as output:
        plistlib.dump(plist, output, sort_keys=True)
    temporary.replace(plist_path)

    run_launchctl(["bootout", launch_domain(), str(plist_path)], allow_failure=True)
    run_launchctl(["bootstrap", launch_domain(), str(plist_path)])
    run_launchctl(["kickstart", "-k", f"{launch_domain()}/{label_for(workspace)}"])
    print(f"Installed and started {label_for(workspace)}")
    print(f"Incoming recordings: {workspace.incoming_dir}")
    print(f"Logs: {workspace.internal_dir}")


def uninstall(workspace: TeacherWorkspace) -> None:
    plist_path = plist_path_for(workspace)
    run_launchctl(["bootout", launch_domain(), str(plist_path)], allow_failure=True)
    if plist_path.exists():
        plist_path.unlink()
    print(f"Removed {label_for(workspace)}")


def main() -> None:
    args = parse_arguments()
    try:
        workspace = resolve_teacher(args.teacher)
        if args.dry_run:
            sys.stdout.buffer.write(
                plistlib.dumps(build_plist(workspace, args.retry_failed))
            )
        elif args.uninstall:
            uninstall(workspace)
        else:
            install(workspace, args.retry_failed)
    except (FileNotFoundError, RuntimeError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
