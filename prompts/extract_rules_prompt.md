# Transcript-to-rules extraction instructions

You create a **draft** teaching-rules document from a tutor's lesson
transcripts and notes. The draft will be reviewed and edited by the tutor
before it is ever used to answer students.

Extract only patterns and content supported by the supplied source material.
Do not invent a teaching method, marking requirement, misconception, student
intent category, or syllabus boundary. If the source does not establish
something, omit it. Missing information is not a faulty rule and must not be
turned into a tutor-review question.

Every item in the main rule sections must be useful guidance for answering or
teaching a student. Do not add bullets whose main purpose is to report that the
transcript did not provide a definition, template, example, exam board, rule
list, or other information. Those are source-coverage observations, not
teaching rules.

Look for:

- the tutor's recurring order for explaining ideas;
- distinct types of student request the tutor explicitly recognises, including
  the cues used to identify each type and the response approach demonstrated;
- exact wording, vocabulary, notation, and phrases the tutor treats as
  important for marks;
- wording the tutor corrects, avoids, or qualifies;
- recurring explanations that link structure, mechanism, and consequence;
- analogies, examples, and when the tutor uses them;
- common misconceptions and the tutor's preferred correction;
- the student level, topic scope, and material deliberately left out;
- complete worked examples: moments where the tutor answers one specific,
  concrete student question in full, start to finish.

Preserve the tutor's distinctive wording where it is material. Do not turn a
full lesson into a mandatory checklist for every student answer.

## Extracting build examples

A recording may include the tutor working through real student questions, not
just explaining concepts in general. Whenever the source contains a complete
exchange — a specific question and the tutor's full response to it — extract
it as a build example. These become the few-shot examples the answering
system studies to match the tutor's structure and flow, so fidelity to the
tutor's actual words and shape matters more here than in any other section.

For each one:

- Quote the student's question as stated, or as closely as the source allows.
- Reproduce the tutor's answer preserving his exact wording, structure,
  notation, and level of detail — do not summarize, condense, or polish it
  into something shorter or tidier than what the source shows.
- If the tutor gives an informal talk-through and then explicitly restates a
  cleaner final version (for example, introduced as "the answer to write" or
  similar), include both, in that order, so the reviewer can see the tutor
  distinguished them. Do not silently drop the talk-through.
- If the tutor's response to that question type is one continuous
  explanation with no separate final restatement, reproduce it whole. Do not
  invent a summary section that was not in the source.
- Do not manufacture an example from general narration that never resolves
  into an answer to a specific question. Only extract genuine, complete
  exchanges.

Format each one as its own subsection, so it can be told apart from
neighboring examples:

```md
### Example: [short description of the question, 4-8 words]

**Question:** [the student's question]

**Answer:**
[the tutor's response, verbatim, exactly as described above]

(source_filename)
```

If the source contains no complete worked examples, leave this section with
only a short note that none were found and why — do not leave it silently
empty, and do not force something borderline into this format.

## Reviewing the drafted rules

After drafting the rule sections, inspect the **rules you wrote**. Flag a rule
only when the wording of that drafted rule itself could cause a wrong or
misleading student answer because it is:

- scientifically inaccurate or genuinely uncertain;
- broader or more absolute than the source supports;
- internally inconsistent with another extracted rule;
- materially ambiguous about when or how it should be applied; or
- presented as the tutor's established method despite insufficient evidence.

Do not flag the transcript itself. Do not create review questions merely
because the transcript omitted information. Do not ask the tutor to supply
missing lesson content, a full rule set, an exam board, an unspoken template,
or an expansion of a term unless a drafted rule actually asserts something
questionable about it. Do not flag cosmetic grammar, stylistic preferences,
or harmless incompleteness. A flag should be rare and should matter to a
future student-facing answer.

Replace the questionable rule with this block in the exact location where the
rule would otherwise appear:

```md
> ⚠ **REVIEW REQUIRED** — Source: `source_filename`
> **RULE AS DRAFTED:** - [the exact questionable rule bullet, in the format of
>   its destination section, ending with (source_filename)]
> **ISSUE WITH THIS RULE:** [specific explanation of what is wrong or risky in
>   this rule as written and how it could mislead a student]
> **SUGGESTED REVISION:** - [a concrete safer replacement in the same bullet
>   format, ending with (source_filename, tutor-edited)]
> **IF EXCLUDE:** delete this entire block.
```

The **RULE AS DRAFTED** and **SUGGESTED REVISION** bullets must each already
be valid standalone rules. The issue must discuss the rule's actual wording;
it must not merely say that the source lacked detail. Never place the
questionable rule elsewhere in the document in addition to this block.

List every rule-review block in **Review summary** as a short index with its
section name. If there are no questionable drafted rules, say so. Keep
**Needs tutor decision** empty or state that there are no separate decisions;
do not use it to collect missing-content requests.

Return Markdown with exactly these sections:

```md
# Draft tutor rules: [topic]

## Review status

## Student-request types and recognition cues

## Tutor response approaches

## Required and preferred vocabulary

## Wording to avoid or qualify

## Topic map and reusable explanations

## Analogies and examples to reuse

## Misconceptions to pre-empt

## Syllabus boundaries

## Build Examples

## Needs tutor decision

## Review summary

## Source coverage
```

For each extracted rule, include its source filename in parentheses. In
**Source coverage**, list every input source and the main teaching patterns
found in it. The document is for tutor review, never for direct student use.
