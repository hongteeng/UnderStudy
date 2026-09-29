# UnderStudy

Students can ask a general LLM, but a correct answer is not always the right
answer for that student. It may use unfamiliar methods, stray beyond the
syllabus, or contradict the language their teacher expects.

UnderStudy is built around a simple idea: students do not need another
generic tutor. They need access to the way their own teacher teaches, when
that teacher is unavailable — not just the same final answer, but the
reasoning a teacher walks through before giving it: how they recognize what
kind of question this is, what habit or method they reach for because of
that, and how they tell it apart from a question it could be confused with.
A generic model tends to skip straight to a correct answer. A teacher
usually teaches the recognition first. UnderStudy's job is to notice
whichever of these patterns a given teacher actually repeats, and reproduce
it — not to assume in advance what that pattern will be.

UnderStudy turns lesson recordings into a reviewed set of teaching rules for
each teacher. Every teacher has an isolated workspace, so recordings and rules
from different teachers are never combined.

## Setup

Follow [SETUP.md](SETUP.md), activate the virtual environment, and make sure
`.env` contains `OPENAI_API_KEY`.

## Run the complete console workflow

```bash
python main.py
```

The program will:

1. ask for the teacher's name;
2. open that teacher's existing workspace or create a new one;
3. ask for lesson audio files or a folder containing audio files;
4. copy those recordings into the teacher's incoming folder;
5. transcribe each recording and create a rules draft;
6. ask the teacher to keep, edit, replace, or exclude flagged rules; and
7. apply approved material to that teacher's `rules.md`.

The reviewer flags the drafted rule, not the source transcript. Each review
screen shows the rule as drafted, the specific risk in that rule, and a
suggested revision. Missing transcript details are omitted rather than turned
into open-ended questions for the teacher.

At an audio prompt, paste a path or drag a file into the terminal. You can add
several files one at a time. Press Enter on an empty line to start processing.
MP3, MP4, MPEG, MPGA, M4A, WAV, and WebM files are supported.

Entering the same teacher name on a later run reopens the same workspace and
adds new lessons to the same `rules.md`.

## Teacher storage

Each teacher gets a stable, safe ID such as `hong-ting` or `jane-tan`:

```text
data/teachers/
  hong-ting/
    teacher.json
    rules.md
    syllabus.md                         # optional
    recordings/
      incoming/
      processed/
      transcription_manifest.json
    transcripts/
    rule_drafts/
    internal/
    results/
      evaluations/
        20260801_123456/
          blind_review.md
          blind_review.csv
          eval_report.md                 # created after review is complete
          eval_output.csv
          metadata.json
          inputs/                        # frozen rules, syllabus, and questions
          internal/                      # progress and hidden A/B answer key
```

Only the code and extraction prompt are shared. The manifest, recordings,
transcripts, drafts, syllabus, and final rules belong to exactly one teacher.
Hong Ting's original project data is stored under
`data/teachers/hong-ting/`.

## Use individual commands

The console wizard is the normal entry point. Individual stages remain
available for debugging or rerunning one step. When more than one teacher
exists, include `--teacher`.

```bash
python transcribe_recordings.py --teacher hong-ting --extract-rules
python extract_rules.py --teacher hong-ting
python review_rules.py --teacher hong-ting
python apply_rules.py --teacher hong-ting
python answer.py --teacher hong-ting "What is ionic bonding?"
```

`extract_rules.py` manually combines all transcripts belonging to the selected
teacher. The normal recording automation extracts only the recording that just
finished, so older lessons are not drafted again.

### Redo one recording

Place a fresh copy in that teacher's incoming folder, then run:

```bash
python transcribe_recordings.py --teacher hong-ting --reset redox.mp3
python transcribe_recordings.py --teacher hong-ting --extract-rules
```

Reset removes only that lesson's processed audio, transcript, draft, manifest
entry, backup, and previously applied rules. It keeps the fresh incoming copy.

### Identify the teacher in multi-speaker audio

Without a reference clip, transcripts still contain generic speaker labels.
For stronger speaker identification, supply a clear 2–10 second reference:

```bash
python transcribe_recordings.py \
  --teacher hong-ting \
  --teacher-name "Hong Ting" \
  --teacher-reference /absolute/path/to/reference.m4a \
  --extract-rules
```

### Long recordings

Recordings larger than the API upload limit are compressed and split with
`ffmpeg`:

```bash
brew install ffmpeg
```

### Background automation on macOS

A separate background worker can be installed for each teacher:

```bash
python install_lesson_automation.py --teacher hong-ting --dry-run
python install_lesson_automation.py --teacher hong-ting
```

It watches that teacher's incoming folder and creates transcripts and drafts.
Review remains interactive, so run `review_rules.py --teacher hong-ting` later.

Remove the worker with:

```bash
python install_lesson_automation.py --teacher hong-ting --uninstall
```

## Test teacher-specific answers

```bash
python answer.py --teacher hong-ting "Why does graphite conduct electricity?"
```

The answering engine reads only the selected teacher's `rules.md` and optional
`syllabus.md`.

## Evaluate a teacher

The shared evaluation questions are already stored in `data/eval_questions`, so
the normal command only needs the teacher:

```bash
python run_eval.py --teacher hong-ting
```

The evaluation:

1. freezes a copy of that teacher's current rules, optional syllabus, and the
   question set so the run remains reproducible;
2. generates an UnderStudy answer and a syllabus-only baseline answer using the
   same model;
3. saves after every answer, so an interruption does not discard completed API
   calls;
4. randomizes both systems as Answer A and Answer B;
5. asks the reviewer for a 0–3 teacher-fit score, syllabus-overshoot check,
   preference, and optional notes; and
6. reveals the systems and creates the final scored report only after every
   question has been reviewed.

Every run is isolated under
`data/teachers/<teacher-id>/results/evaluations/<run-id>/`; one teacher can never
overwrite another teacher's report. If the teacher has no `syllabus.md`, the
comparison is clearly recorded as a generic baseline instead.

To generate the answers now and review later:

```bash
python run_eval.py --teacher hong-ting --no-review
```

The command prints the exact resume command. You can also resume the newest
unfinished run with:

```bash
python run_eval.py --teacher hong-ting --resume latest
```

During blind review, enter `Q` at either score prompt to save and stop safely.
