# UnderStudy

UnderStudy lets a tutor encode their teaching method once, so students receive
answers in that tutor's method when the tutor is unavailable.

## First answering-engine test

1. Follow [SETUP.md](SETUP.md) to configure Python and `OPENAI_API_KEY`.
2. Add one or more lesson transcripts to `data/transcripts/raw/`, or use the
   automated recording workflow below.
3. Create a tutor-reviewable draft from those transcripts:

   ```bash
   python extract_rules.py
   ```

   This writes `data/rule_drafts/<transcript_name>_rules_draft.md`, named
   after the source transcript(s).
4. Review the draft through the guided console:

   ```bash
   python review_rules.py
   ```

   For each flagged rule, choose the original wording, the suggested edit,
   a custom edit, or exclusion. For any remaining open decision, enter the
   tutor's wording or remove it. The reviewer cleans the marker text,
   validates the result, saves a `.bak` backup, and asks whether to apply the
   finished rules immediately.
5. Apply the reviewed draft into `data/rules.md`:

   ```bash
   python apply_rules.py
   ```

   This refuses to run if the draft still has unresolved markers, so you
   cannot accidentally publish an un-reviewed claim. Re-running it after
   editing the same draft again replaces that source's content in
   `rules.md` rather than duplicating it.
6. Run an answer:

   ```bash
   python answer.py "What is the difference between ionic and covalent bonding?"
   ```

   Or run `python answer.py` and type the question when prompted.

## Plain-GPT baseline

Use the baseline for a fair comparison: it uses the same model as UnderStudy
but has no tutor rules or teaching examples.

```bash
python baseline.py "What is the difference between ionic and covalent bonding?"
```

Or run `python baseline.py` and type the question when prompted.

## Evaluation scaffold

When the tutor releases a set of Markdown question files for evaluation, run:

```bash
python run_eval.py path/to/question_folder
```

Each `.md` file must contain one question; its filename becomes the
`question_id`. The command runs UnderStudy and the plain-GPT baseline for each
file, then writes `results/eval_output.csv`.

The score and reviewer columns are intentionally blank. The tutor should score
the answer pairs manually; before a blind review, copy the two answer columns
into a separate sheet and remove or randomize their labels. This script does
not evaluate the answers automatically.

Everything under `data/` is shared through Git so both teammates work from the
same recordings, transcripts, drafts, rules, examples, and evaluation
materials. The `templates/` folder is also committed to Git. Only `.env` and
other secret or machine-specific files stay out of the repository.

## Lesson-recording intake

The shared `data/` folder separates automated drafts from the tutor-approved
materials used by students:

```text
data/
  recordings/incoming/              # newly uploaded lesson audio
  recordings/processed/             # audio successfully transcribed
  transcripts/raw/                  # unedited transcription output
  transcripts/reviewed/             # tutor-approved transcripts
  rule_drafts/                      # AI-generated draft rules, named per transcript; never used directly
  rules.md                          # final tutor-approved teaching rules and worked Q&A examples
```

A recording's transcript can include the tutor working through real student
questions, not just explaining concepts. `extract_rules.py` pulls any complete
question-and-answer exchanges it finds into a `## Build Examples` section
inside the same draft, right alongside the rest of the rules. Review it the
same way as everything else, in the same draft file, through
`review_rules.py` and `apply_rules.py`. There is no separate build-examples
folder or step -- once `rules.md` is applied, the worked examples live inside
it and `answer.py` reads them from there.

The combined workflow keeps the two parts separate:

```text
lesson recording
  → transcription automation
  → raw transcript
  → Hong Ting's rules extractor
  → tutor review and Hong Ting's apply gate
  → answering and evaluation
```

The transcription stage only supplies a new source transcript. It does not
replace the extraction prompt, rules-merging checks, answering logic, build
examples, or evaluation pipeline.

### Run the complete recording pipeline once

Put an MP3, MP4, MPEG, MPGA, M4A, WAV, or WebM lesson recording in
`data/recordings/incoming/`, then run:

```bash
python transcribe_recordings.py --extract-rules
```

For every completed recording, the worker:

1. transcribes the lesson with speaker labels;
2. writes `data/transcripts/raw/<recording_name>.md`;
3. moves the original audio to `data/recordings/processed/`;
4. records the result in `data/recordings/transcription_manifest.json`; and
5. hands that transcript to Hong Ting's existing extraction engine, which
   creates `data/rule_drafts/<recording_name>_rules_draft.md`.

The background worker cannot open an interactive prompt, so after it creates a
draft, review it with:

```bash
python review_rules.py
```

Press Enter to accept a suggested edit when one is available. The final prompt
can apply the reviewed rules immediately, so no manual Markdown cleanup is
needed. This console helper only collects the tutor's choices; final validation
and merging still run through Hong Ting's original `apply_rules.py` command.

Files still being copied are left alone until they stop changing. A recording
with the same contents is never transcribed twice. Failed recordings remain in
`incoming/` and can be retried with:

```bash
python transcribe_recordings.py --retry-failed --extract-rules
```

Recordings larger than the API upload limit are compressed and split with
`ffmpeg`. Install it with `brew install ffmpeg` before processing long lessons.

### Identify the teacher in a multi-speaker lesson

Record a clear 2–10 second teacher reference clip and add both settings to
`.env`:

```text
TEACHER_SPEAKER_NAME=Hong Ting
TEACHER_REFERENCE_AUDIO=/absolute/path/to/hong_ting_reference.m4a
```

If both settings are omitted, the transcript still includes speaker labels,
but they will be generic labels assigned by the transcription model.

### Keep it running automatically on macOS

First inspect the generated background-service configuration:

```bash
python install_lesson_automation.py --dry-run
```

Then install and start it:

```bash
python install_lesson_automation.py
```

It starts at login and continuously runs the equivalent of:

```bash
python transcribe_recordings.py --watch --extract-rules
```

To use a Dropbox, Google Drive, or iCloud folder as the teacher's upload
destination, add its absolute path to `.env`:

```text
UNDERSTUDY_INCOMING_DIR=/absolute/path/to/synced/lesson-recordings
```

The teacher can then record directly into that synced folder; the remaining
steps happen automatically. Logs are written under `data/internal/`. Remove
the background worker with `python install_lesson_automation.py --uninstall`.

### Hong Ting's manual transcript-to-rules operation

To run Hong Ting's original extractor manually, create one combined draft from
all available reviewed transcripts (or all raw transcripts when no reviewed
files exist):

```bash
python extract_rules.py
```

The script uses reviewed transcripts when any are available; otherwise it uses
the raw transcripts. It writes `data/rule_drafts/<transcript_name>_rules_draft.md`,
named after the source transcript(s), including a `## Build Examples` section
for any complete question-and-answer exchanges found in the source. The tutor
must review and edit this draft (`review_rules.py` or by hand) before applying
it into `data/rules.md` (`apply_rules.py`). Only `data/rules.md` is used for
student answers -- rules and worked examples together, in one file.

The automation maintains its own machine-readable recording manifest. The CSV
[recording manifest template](templates/recording_manifest_template.csv) remains
available if a separate manual log is wanted.
