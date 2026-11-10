# Model tiers and fallback

Each agent file sets a default model. The principle: anything that checks or judges runs on a stronger model than the agent whose work it checks.

| Agent | Default | Role |
|---|---|---|
| pdf-visual-checker | haiku | compare rendered page images to extracted text |
| page-transcriber | haiku | read scanned pages (image to text) |
| summarizer | sonnet | structured summary of one article |
| summary-verifier | opus | check one summary against its article |
| theme-mapper | opus | cross-article theme matrix, conflicts, gaps |
| outliner | opus | chapter plan with word budgets and sources |
| section-writer | sonnet | write one chapter |
| integrator | sonnet | assemble chapters, write abstract, introduction, conclusions, transitions |
| fact-checker | opus | verify every claim against summaries and sources |
| critic | opus | score with the rubric, list concrete issues |
| reviser | sonnet | fix only the listed issues |

## Overrides from the project
`project.yaml` may contain a `models:` map, for example `models: {section-writer: opus}`. The orchestrator passes the override as the per-invocation `model` parameter.

## Fallback when a model is not available
Some plans do not include every model (for example, Opus may be unavailable on some plans). If an agent call fails with an error saying the model is unavailable, not allowed, or not included in the plan:

1. Switch to the fallback table below for the rest of the run, and record it in `state.json` under `model_fallback: true`.
2. Re-run the failed call with the per-invocation `model` parameter from the table.
3. Tell the user once, in one plain sentence, that a lighter model set is being used.

| Default | Fallback |
|---|---|
| opus | sonnet |
| sonnet | haiku |
| haiku | haiku |

The fallback keeps the gap between writers and checkers: the critic (sonnet) still runs one level above the writer (haiku).
