# Rule-checklist scoring: UnderStudy vs. baseline, 10 held-out questions

Checklist derived directly from `data/rules.md` (tutor-approved). These 10 questions
(`data/eval_questions_hidden/`) were written after all prompt tuning was finished and
were never used to develop `answer.py` — a genuine held-out set, not the 3 questions
used earlier for development. Scoring done by mechanically checking each answer
against the checklist below; this is not a blind human read by the tutor himself,
which is a real limitation, noted in WRITEUP.md.

## Checklist (from data/rules.md)

1. **C1 — Required structure phrase.** Uses the tutor's exact structure term
   ("giant ionic lattice structure," "simple molecular structure," "giant covalent
   structure," "giant metallic lattice structure"), not a generic paraphrase.
2. **C2 — Ionic bonding phrasing.** States "strong electrostatic forces of
   attraction between cations and anions" (named ions where relevant), not just
   "ionic bonds."
3. **C3 — Metallic bonding phrasing.** States "strong electrostatic forces of
   attraction between metal cations and the sea of delocalised electrons," not
   just "metallic bonds." (Only applicable when bonding itself, not just
   structure/conductivity, is asked.)
4. **C4 — No "molecule" mislabel.** Never calls a giant covalent structure a
   "molecule" or "giant molecular structure."
5. **C5 — Graphite interlayer wording.** Uses "weak forces between the layers,"
   not "intermolecular forces," and never claims graphite conducts "in all states."
6. **C6 — Correct charge carriers.** Ionic: mobile ions, molten/aqueous only.
   Metals: delocalised electrons, including solid state. Simple molecular /
   diamond / SiO2: none. No swapping between categories.
7. **C7 — Simple molecular wording.** Uses "weak intermolecular forces of
   attraction" correctly for low melting/boiling point.
8. **C8 — Syllabus boundary.** Does not give Group 1 vs. transition-metal detail,
   or other material outside bonding-and-structure, within this topic.
9. **C9 — Structure-then-bonding-then-property order.**
10. **C10 — No misconception errors** (e.g. ions carrying charge in metals, or
    vice versa; incorrect brittleness mechanism).

## Per-question scores (pass count / applicable items)

| # | Question | Applicable items | UnderStudy | Baseline |
|---|---|---|---|---|
| H1 | NaCl structure & bonding | C1, C2, C9 | 3/3 | 0/3 |
| H2 | NaCl conductivity (molten vs. solid) | C1, C6, C9 | 3/3 | 1/3 |
| H3 | Diamond vs. graphite conductivity | C4, C5, C6 | 3/3 | 3/3 |
| H4 | CO2 low melting point | C1, C7, C9 | 3/3 | 3/3 |
| H5 | SiO2 structure & melting point | C1, C4, C9 | 3/3 | 3/3 |
| H6 | Metal structure & conductivity | C1, C6, C9 | 3/3 | 2/3 |
| H7 | Metals malleable vs. ionic brittle | C1, C9, C10 | 3/3 | 2/3 |
| H8 | Is graphite a molecule? | C1, C4, C9 | 3/3 | 3/3 |
| H9 | Compare MgO vs. SO2 | C1, C2, C6, C7, C9 | 5/5 | 2/5 |
| H10 | Transition metal reactivity trends (out of scope) | C8 | 1/1 | 0/1 |
| **Total** | | **31 applicable** | **30/31 (97%)** | **19/31 (61%)** |

## Syllabus-overshoot (separate from the checklist above)

Whether the answer pulled in material outside bonding-and-structure entirely
(a stronger, separate signal from failing an individual vocabulary check):

- UnderStudy: 0/10 questions overshot scope.
- Baseline: 2/10 (H9 pulled in acid-base oxide classification/litmus/reactions
  with acids; H10 answered transition-metal reactivity trends in full).

## What this does *not* show (read before citing the 97%/61% number)

- **Not blind, not human-graded.** Scored by mechanically checking text against
  the list above, not a blind read by Hong Ting. A human tutor may weigh things
  differently (e.g. penalize an awkward phrase more or less than this checklist does).
- **Baseline matched the tutor's own required wording on 4 of 10 questions**
  (H3, H4, H5, H8) — the two systems are not different on every question; the
  gap concentrates specifically on exact required phrasing, bonding-label
  precision, and syllabus-boundary respect, not general answer quality.
- **A real bug surfaced during this run:** H9 ("Compare the properties of...")
  should have triggered the two-part context/"### Answer to write" format per
  `answer.py`'s command-word rule ("compare" is explicitly listed), but did not.
  Not fixed as part of this eval — logged as a known issue.
- **A real model glitch surfaced too:** UnderStudy's H8 answer contains one
  stray Georgian-script word ("ამიტომ," meaning "therefore") mid-sentence in an
  otherwise-English answer — an unexplained artifact, not something introduced
  by any instruction here.
- n=10. This is a pilot, not a statistically powered evaluation.
