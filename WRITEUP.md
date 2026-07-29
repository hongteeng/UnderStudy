# UnderStudy

*Five-pillar write-up, ~1000 words. Appendix doesn't count against the cap.*

## 1. Problem

Tuition teachers can't answer questions 24/7. When they do reply, it's usually over text, which loses what actually makes their teaching work — the pacing, the analogies, the exact phrasing that earns marks, the way they'd normally walk a student through getting unstuck. A rushed text reply is a worse version of the tutor, not a substitute for one.

Students turn to ChatGPT instead. It gives them a different method than the one their teacher drilled into them, which confuses the student and undermines the teacher.

The one-line pitch: **not a smarter tutor — a tutor that teaches your way when you're not there.**

Why a student can't just prompt ChatGPT into this: they don't know their teacher's method well enough to describe it. They can't type "answer this the way Sir taught me," because they don't know what that consists of — the recognition cues for question types, the phrases that earn marks, what's deliberately left out at this level. The teacher knows all of that. So the teacher encodes it once, and every student gets it, at 2am.

**Success, defined before we built anything:** the engine follows Hong Ting's actual vocabulary and explanation order where he's stated one, respects the syllabus boundaries he's drawn (won't wander into content he hasn't taught yet), and — critically — never lets an unreviewed, possibly-wrong AI guess about his teaching reach a student without him seeing it first.

## 2. Approach

Teaching pedagogy is tutor-authored, not hardcoded. The code's job is generic platform work: read the tutor's material, take the student's question, tell the model to follow the tutor's method — not decide what that method is.

**Pipeline:** transcript → `extract_rules.py` drafts rules (AI-written, never trusted directly) → Hong Ting reviews every flagged claim → `apply_rules.py` merges into `rules.md` (refuses to run if anything's unresolved) → `answer.py` reads `rules.md`, his own Q&A examples, and a syllabus reference → `run_eval.py` runs UnderStudy and a plain-GPT baseline side by side.

**What we ruled out, and why:**
- *Fine-tuning on his transcripts.* One tutor, a handful of lessons — not enough data, and every correction would mean retraining instead of editing a text file.
- *Skipping human review, applying every drafted rule automatically.* Tested this — it would have shipped real errors: a transcript line claiming giant covalent structures are "one big molecule" (wrong — diamond isn't a molecule), and an identification rule based on counting subscripts that fails on SiO2. `apply_rules.py` now refuses to merge anything with an unresolved flag or no source citation.
- *Hardcoding Hong Ting's answer style into the code.* Built this, then tore it back out — it worked, but forced every future tutor into his structure. Style has to come from his own rules and examples, not our prompt. Pulling it back out exposed a real gap (§5).
- *A full voice feature.* Not built. The pitch imagines answers spoken in his voice; right now everything is text (§5).

## 3. Evidence

We wrote 10 new test questions his material was never tuned against, ran both systems on all 10, and scored every answer against a checklist pulled straight from `rules.md` — required phrasing, correct charge carriers, whether his syllabus boundary was respected. Full scoring in `results/checklist_score.md`.

**Result: UnderStudy passed 30 of 31 applicable checklist items (97%). The baseline passed 19 of 31 (61%).**

Where the gap actually comes from: baseline matched Hong Ting's required wording on 4 of the 10 questions outright — this isn't "our AI is smarter everywhere." It concentrates on two things: exact phrasing (baseline kept saying "ionic bonds," which he explicitly bans in favor of naming the electrostatic attraction) and syllabus discipline. On a held-out question about transition-metal reactivity — explicitly outside this topic in his rules — UnderStudy said so and stopped; baseline wrote four paragraphs on d-electron trends nobody asked for. That happened on 2 of the 10 questions.

We found real problems this way too, not just wins: one question ("Compare the properties of...") should have triggered our two-part answer format and didn't — a live bug. One answer had a stray Georgian word mid-sentence for no traceable reason. Both logged, not hidden.

## 4. Constraints

- **Cost and latency:** every answer is a live, uncached API call. No batching. Ten questions through both systems took a bit under two minutes; that's fine for one student, unproven at real classroom scale.
- **Reliability over convenience, on purpose:** `apply_rules.py` won't run if a lesson's rules haven't been fully reviewed — slower, but nothing unverified reaches a student.
- **One tutor, one topic, tested.** Everything above is bonding and structure, from one transcript. No second topic or tutor yet.
- **No deployment surface.** Local scripts and a `.env` file. No auth, no multi-user handling, no hosting.

## 5. Honesty & Trajectory

**The scoring above isn't blind, and it isn't Hong Ting doing it.** We checked text against a list mechanically. A real blind read by the tutor — the original test design — would be more convincing and might disagree with us. That's the actual next step, not a finished result.

**Style-matching is still shaky.** With only 3 written examples of his answering style, the model didn't reliably keep his context-first structure once we stopped hardcoding it. More real examples of his voice, not more prompt engineering, is what fixes this.

**Two live bugs, found and logged, not fixed:** the two-part answer format doesn't reliably trigger on every "compare" question yet, and one answer had an unexplained foreign-script glitch in it.

**Voice output doesn't exist yet.** The pitch describes it; the repo doesn't have it.

**What's next, in order:** fix the two bugs above; get Hong Ting to do a real blind pass on the 10 held-out questions and see if he agrees with our 97/61 read; add enough real examples that style transfers without hardcoding; then, once one tutor works end to end, try a second one.
