# UnderStudy

UnderStudy lets a tutor encode their teaching method once, so students receive
answers in that tutor's method when the tutor is unavailable.

## First answering-engine test

1. Follow [SETUP.md](SETUP.md) to configure Python and `OPENAI_API_KEY`.
2. Add one or more lesson transcripts to `data/transcripts/raw/`.
3. Create a tutor-reviewable draft from those transcripts:

   ```bash
   python extract_rules.py
   ```

   This writes `data/rule_drafts/<transcript_name>_rules_draft.md`, named
   after the source transcript(s).
4. Open that draft file yourself and resolve every review marker in it:
   for each `⚠ REVIEW REQUIRED` block, pick `IF KEEP`, `IF EDIT`, or
   `IF EXCLUDE` and delete the rest of the block; for each item under
   `## Needs tutor decision`, make the call and edit the relevant rule
   directly. The draft is not usable until no `REVIEW REQUIRED`, `IF KEEP`,
   `IF EDIT`, or `Needs tutor decision` text remains in it.
5. Apply the reviewed draft into `data/rules.md`:

   ```bash
   python apply_rules.py
   ```

   This refuses to run if the draft still has unresolved markers, so you
   cannot accidentally publish an un-reviewed claim. Re-running it after
   editing the same draft again replaces that source's content in
   `rules.md` rather than duplicating it.
6. Copy `templates/build_example_template.md` to `data/build_examples/01.md`
   through `04.md`, then replace the template content with 3–4 real,
   tutor-written Q&As.
7. Run an answer:

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

The `data/` folder is deliberately ignored by Git because it contains the
tutor's private teaching material.
The `templates/` folder is safe to commit.

## Lesson-recording intake

The private `data/` folder separates automated drafts from the tutor-approved
materials used by students:

```text
data/
  recordings/incoming/              # newly uploaded, consented teacher audio
  recordings/processed/             # audio successfully transcribed
  transcripts/raw/                  # unedited transcription output
  transcripts/reviewed/             # tutor-approved transcripts
  rule_drafts/                      # AI-generated draft rules, named per transcript; never used directly
  extracted_examples/drafts/        # AI-suggested teaching examples
  extracted_examples/approved/      # tutor-approved candidates
  rules.md                          # final tutor-approved teaching rules
  build_examples/                   # final tutor-approved Q&A examples
```

Keep only consented tutor lesson recordings in `data/recordings/incoming/`.
To create a tutor-reviewable rules draft from the available transcripts, run:

```bash
python extract_rules.py
```

The script uses reviewed transcripts when any are available; otherwise it uses
the raw transcripts. It writes `data/rule_drafts/<transcript_name>_rules_draft.md`,
named after the source transcript(s). The tutor must review and edit this
draft before copying the approved content into `data/rules.md`.
Only `data/rules.md` and `data/build_examples/` are used for student answers.

Use [recording_manifest_template.csv](templates/recording_manifest_template.csv)
as the starting point for a private recording log. Keep the completed manifest
inside `data/`, not in `templates/`.
