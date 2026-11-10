# Review rubric

The critic scores the draft on each criterion from 1 to 5. Scores are integers. Half points are not allowed.

| # | Criterion | 5 means | 3 means | 1 means |
|---|---|---|---|---|
| C1 | Coverage | Every relevant article in the project is used where it matters; nothing important is missing | Most articles used; one or two relevant ones are barely present | Key articles missing |
| C2 | Synthesis | Paragraphs compare, contrast and connect studies; themes drive the text | Mix of synthesis and article-by-article summary | Article after article, no comparison |
| C3 | Argument and structure | Each chapter answers its sub-question; clear line of reasoning from introduction to conclusions; sensible order | Structure exists but some chapters drift or repeat | No visible line of reasoning |
| C4 | Accuracy and citation | Every claim cited with a valid ID; numbers match sources; no overgeneralization | A few uncited or loosely supported claims | Many unsupported or wrong claims |
| C5 | Critical analysis | Limitations, methodological quality, conflicts and gaps are discussed for the important studies | Limitations mentioned generically | Findings accepted at face value |
| C6 | Depth and technical detail | Goes into methods, numbers, formulas and results tables where relevant; no encyclopedia-level filler | Some technical detail, some generic explanation | Generic, popular-level text |
| C7 | Compliance | Follows the profile structure, length budget, language, register and every project rule | Minor deviations | Ignores structure, length or rules |
| C8 | Writing quality | Clear, precise, consistent terminology, academic register, good transitions | Readable but uneven | Hard to read |

## Project rules as criteria
Every rule in the project's `rules.md` is checked under C7. A violated project rule must appear as an issue.

## Stop condition (used by the orchestrator)
- PASS: every criterion is 4 or higher AND the mean is at least 4.5.
- Also stop after 4 critic rounds, or when the mean has not improved for 2 consecutive rounds.
