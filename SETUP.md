# UnderStudy: first OpenAI API call

This guide verifies that your local project can make a single OpenAI API request.

## 1. Create the virtual environment

From the UnderStudy project folder, run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

You should see `(.venv)` at the beginning of your terminal prompt. Run the
`source .venv/bin/activate` command again whenever you open a new terminal.

## 2. Add your API key locally

Create a file named `.env` in this project folder. The complete set of optional
settings is shown in `.env.example`. The real `.env` is ignored by Git.

Add this line, replacing the placeholder with your actual key:

```text
OPENAI_API_KEY=your_api_key_here
```

Optional: choose a different available model without editing Python code:

```text
OPENAI_MODEL=gpt-5.6-sol
```

Lesson transcription defaults to the speaker-aware transcription model:

```text
OPENAI_TRANSCRIPTION_MODEL=gpt-4o-transcribe-diarize
```

For recordings larger than 24 MB, install `ffmpeg` so the automation can
compress and split them:

```bash
brew install ffmpeg
```

## 3. Run the smoke test

```bash
python hello_openai.py
```

Expected output:

```text
UnderStudy API connection successful.
```

## Troubleshooting

- `OPENAI_API_KEY is missing`: check that `.env` is in the project folder and
  contains the key name exactly as shown.
- `ModuleNotFoundError`: activate `.venv`, then run `pip install -r requirements.txt`.
- Authentication or quota error: check that you pasted an active API key and
  that the OpenAI project holding the Launchpad credits is selected.
- `Install ffmpeg`: the recording exceeds the upload limit; run
  `brew install ffmpeg`, then retry the failed recording.
- A failed recording is not retried automatically unless the worker was
  started with `--retry-failed`.

Never put an API key in source code, a chat message, or a Git commit.
