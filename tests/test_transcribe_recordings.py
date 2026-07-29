import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import transcribe_recordings as transcription
import extract_rules


class FakeTranscriptions:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


class FakeClient:
    def __init__(self, payload):
        self.audio = type("Audio", (), {})()
        self.audio.transcriptions = FakeTranscriptions(payload)


class TranscriptionWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.incoming = self.root / "incoming"
        self.processed = self.root / "processed"
        self.transcripts = self.root / "transcripts"
        for directory in (self.incoming, self.processed, self.transcripts):
            directory.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def settings(self, **overrides):
        values = {
            "incoming_dir": self.incoming,
            "processed_dir": self.processed,
            "transcripts_dir": self.transcripts,
            "manifest_path": self.root / "manifest.json",
            "lock_path": self.root / "worker.lock",
            "model": "gpt-4o-transcribe-diarize",
            "language": None,
            "teacher_name": None,
            "teacher_reference": None,
            "max_upload_bytes": 1024 * 1024,
            "settle_seconds": 0,
            "poll_seconds": 1,
            "api_retries": 1,
        }
        values.update(overrides)
        return transcription.Settings(**values)

    def create_recording(self, name="lesson.m4a", content=b"audio"):
        path = self.incoming / name
        path.write_bytes(content)
        old_time = time.time() - 60
        os.utime(path, (old_time, old_time))
        return path

    def test_scan_transcribes_archives_and_records_manifest(self):
        self.create_recording()
        payload = {
            "duration": 12.4,
            "text": "Teacher explains bonding.",
            "segments": [
                {
                    "speaker": "A",
                    "start": 0.0,
                    "end": 12.4,
                    "text": "Teacher explains bonding.",
                }
            ],
        }
        client = FakeClient(payload)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
            counts = transcription.scan_once(
                self.settings(), False, False, client_factory=lambda: client
            )

        self.assertEqual(counts, (1, 0, 0))
        self.assertFalse((self.incoming / "lesson.m4a").exists())
        self.assertTrue((self.processed / "lesson.m4a").is_file())
        transcript_path = self.transcripts / "lesson.md"
        self.assertTrue(transcript_path.is_file())
        transcript_text = transcript_path.read_text(encoding="utf-8")
        self.assertIn("**[00:00:00–00:00:12] A:** Teacher explains bonding.", transcript_text)
        manifest = transcription.ManifestStore(self.root / "manifest.json")
        record = next(iter(manifest.recordings.values()))
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["segment_count"], 1)
        self.assertEqual(len(client.audio.transcriptions.calls), 1)

    def test_completed_duplicate_is_archived_without_an_api_call(self):
        self.create_recording(content=b"same lesson")
        client = FakeClient({"text": "done", "segments": []})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
            transcription.scan_once(
                self.settings(), False, False, client_factory=lambda: client
            )
            self.create_recording(content=b"same lesson")
            counts = transcription.scan_once(
                self.settings(), False, False, client_factory=lambda: client
            )

        self.assertEqual(counts, (0, 1, 0))
        self.assertEqual(len(client.audio.transcriptions.calls), 1)
        self.assertTrue((self.processed / "lesson_2.m4a").is_file())

    def test_combining_parts_offsets_later_timestamps(self):
        combined = transcription.combine_transcription_payloads(
            [
                {
                    "duration": 10,
                    "segments": [
                        {"speaker": "A", "start": 1, "end": 3, "text": "First"}
                    ],
                },
                {
                    "duration": 8,
                    "segments": [
                        {"speaker": "A", "start": 2, "end": 5, "text": "Second"}
                    ],
                },
            ]
        )
        self.assertEqual(combined["segments"][1]["start"], 12)
        self.assertEqual(combined["segments"][1]["end"], 15)
        self.assertEqual(combined["duration"], 18)

    def test_large_recording_explains_ffmpeg_requirement(self):
        source = self.create_recording(content=b"x" * 20)
        with tempfile.TemporaryDirectory() as temporary:
            with patch("transcribe_recordings.shutil.which", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "Install ffmpeg"):
                    transcription.prepare_audio_parts(
                        source, Path(temporary), max_upload_bytes=10
                    )

    def test_teacher_reference_is_sent_for_speaker_matching(self):
        recording = self.create_recording()
        reference = self.root / "teacher.m4a"
        reference.write_bytes(b"teacher voice")
        client = FakeClient({"text": "hello", "segments": []})
        settings = self.settings(
            teacher_name="Hong Ting", teacher_reference=reference
        )

        transcription.transcribe_part(client, recording, settings)

        call = client.audio.transcriptions.calls[0]
        self.assertEqual(call["known_speaker_names"], ["Hong Ting"])
        self.assertTrue(call["known_speaker_references"][0].startswith("data:audio/"))

    def test_non_diarized_model_uses_plain_json(self):
        recording = self.create_recording()
        client = FakeClient({"text": "hello"})
        settings = self.settings(model="gpt-4o-transcribe")

        transcription.transcribe_part(client, recording, settings)

        call = client.audio.transcriptions.calls[0]
        self.assertEqual(call["response_format"], "json")
        self.assertNotIn("chunking_strategy", call)

    def test_rules_handoff_uses_existing_extraction_engine(self):
        transcript = self.transcripts / "lesson.md"
        transcript.write_text("Teacher explains ionic bonding.", encoding="utf-8")
        drafts = self.root / "drafts"

        with patch.object(extract_rules, "RULE_DRAFTS_DIR", drafts):
            with patch.object(
                extract_rules, "load_extraction_prompt", return_value="Hong Ting prompt"
            ):
                with patch.object(
                    extract_rules, "generate_draft", return_value="# Rules draft"
                ) as generate:
                    result = transcription.create_rules_draft(transcript)

        self.assertEqual(result, drafts / "lesson_rules_draft.md")
        self.assertEqual(result.read_text(encoding="utf-8"), "# Rules draft\n")
        instructions, source = generate.call_args.args
        self.assertEqual(instructions, "Hong Ting prompt")
        self.assertIn("Teacher explains ionic bonding.", source)


if __name__ == "__main__":
    unittest.main()
