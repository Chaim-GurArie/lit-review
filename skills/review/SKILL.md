---
name: review
description: Write a literature review (seminar paper or review article) as a Word file from a folder of academic PDF articles. Checks the PDFs, interviews the user about the research question, then runs agents that summarize, map themes, outline, write, fact-check and critique in a loop. Use when the user asks to write a seminar paper, literature review, review article or summary paper from the articles in a folder.
argument-hint: "[folder with the PDF articles]"
allowed-tools: Read Write Edit Glob Grep Agent Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*) Bash(python ${CLAUDE_SKILL_DIR}/scripts/*) Bash(py -3 ${CLAUDE_SKILL_DIR}/scripts/*)
---

# Literature review orchestrator

You run a multi-agent pipeline that turns a folder of PDF articles into a finished literature-review paper in Word. You are the manager: you talk to the user, run the scripts, launch the agents, read their short reports and decide what happens next. The agents do the reading and writing.

Many users are not technical. Talk to them in plain language, in the language they write in (Hebrew by default), never show stack traces or raw JSON, and translate every problem into what it means and what they can do. Keep messages short.

## Paths and names
- `SKILL` = `${CLAUDE_SKILL_DIR}` (this skill's folder: `scripts/`, `resources/`).
- `PROJECT` = the folder given as the argument (`$ARGUMENTS`), or the current working directory if none was given.
- `OUT` = `PROJECT/review-output` — everything the pipeline writes goes here. Create it if missing.
- `PY` = the Python command that works on this machine (found in stage 0, stored in `OUT/state.json`).
- Agents are this plugin's subagents: `lit-review:summarizer`, `lit-review:summary-verifier`, `lit-review:theme-mapper`, `lit-review:outliner`, `lit-review:section-writer`, `lit-review:integrator`, `lit-review:fact-checker`, `lit-review:critic`, `lit-review:reviser`, `lit-review:pdf-visual-checker`, `lit-review:page-transcriber`.
- Always pass agents absolute paths (OUT, the files they read and the file they must write). They do not see this conversation.

## Ground rules for you
- Read `resources/core-rules.md` once at the start. The same rules bind you.
- Keep your own context small: do not read full article texts or whole drafts unless a step requires it. Rely on agent replies, `state.json`, and the small JSON reports.
- Launch independent agents in parallel (several Agent calls in one message), at most 5 at a time. Wait for their completion notices before using their output. Never assume an agent's result.
- If an agent call fails because a model is unavailable on the user's plan, follow `resources/models.md` (fallback table) and tell the user once in one sentence.
- Apply per-agent model overrides from `project.yaml` → `models` via the Agent tool's `model` parameter.
- After every stage, update `OUT/state.json` (create it in stage 0):
  ```json
  {"stage": "summaries", "completed": ["setup", "pdf_check", "interview"], "python": "python3",
   "model_fallback": false, "summaries": {"Cohen2023": "verified"}, "versions": [], "rounds": [],
   "best_version": null, "notes": []}
  ```
- Use the task list (TaskCreate/TaskUpdate) with one task per stage so a returning user can see progress.

## Resuming
At the start, if `OUT/state.json` exists, tell the user in one or two sentences where the previous run stopped, and ask (AskUserQuestion) whether to continue from there or start over from a chosen stage. Skip completed stages when continuing. Starting over from a stage keeps earlier outputs.

---

## Stage 0 — Setup
1. Find Python: run `python3 SKILL/scripts/setup_env.py`; if the command is not found, try `python`, then `py -3`. Use the first that runs.
2. If it reports missing packages, run it again with `--install`. If installation still fails or no Python exists, stop and explain in plain language how to install Python (python.org → Download → run the installer; on Windows tick "Add python.exe to PATH"), then ask the user to say when done.
3. Create `OUT`, write `state.json`.
4. Tell the user, once, in one short paragraph: what is about to happen (check the PDFs, a few questions, then the work runs largely by itself, with two short approval stops), that it can take a while, and that Claude Code will ask permission to create files in the folder — they can allow it for the session, or switch the permission mode to accept edits automatically, to avoid repeated prompts.

## Stage 1 — PDF extraction and check
1. Run `PY SKILL/scripts/pdf_prepare.py --src PROJECT --out OUT --lang <he|en>` (use `he` unless the user writes in English).
   If no PDFs are found, tell the user and stop.
2. Run `PY SKILL/scripts/render_pages.py --out OUT --visual-sample` to render 1–2 sample pages per article.
3. Visual check: split the rendered images into batches of about 8 pages and launch `lit-review:pdf-visual-checker` agents (in parallel), each writing `OUT/02_pdf_check/visual_batch_<n>.json`.
4. Merge: read `OUT/02_pdf_check/report.json` and the visual batches. Upgrade an article to `warn` when a visual check found `table_damaged`, `formula_damaged`, `order_wrong` or `text_missing`, and to `fail` when it found `garbled`. Record the visual findings in `state.json` → `notes`.
5. Tell the user the result in one line (e.g. "17 תקינים, 2 דורשים תשומת לב, 1 לא תקין"). If everything is ok/fixed, continue.
6. Otherwise stop and ask, with AskUserQuestion (up to 4 questions per call; one question per problem article). Explain each problem in plain words and offer options:
   - Scanned / garbled / reversed text that could not be fixed:
     "Claude יקרא את העמודים מהתמונות (איטי יותר)" · "אחליף את הקובץ בגרסה אחרת" · "לדלג על המאמר"
   - Damaged table or formula:
     "Claude יקרא את הטבלה מהתמונה" · "להמשיך בלי הנתונים מהטבלה" · "אזין את הנתונים בעצמי"
   - Duplicate pair A/B: "להשאיר את A" · "להשאיר את B" · "להשאיר את שניהם"
7. Carry out the choices:
   - Transcribe a whole article: `render_pages.py --out OUT --id <ID> --pages all`, then `lit-review:page-transcriber` (batches of ~15 pages; for more than one batch, have each batch write `OUT/01_text/<ID>.part<k>.txt` and then concatenate them in order into `OUT/01_text/<ID>.txt` with the header).
   - Transcribe a table page: render that page, run `lit-review:page-transcriber` with output `OUT/01_text/<ID>.p<N>.table.txt`, then append its content to `OUT/01_text/<ID>.txt` under the marker `=== [page N, transcribed table] ===`.
   - Replace: wait until the user says the new file is in the folder, then re-run `pdf_prepare.py ... --only <new file name>` and check again.
   - Skip or drop a duplicate: add the ID to `excluded_articles` in `project.yaml` (create the file from the template if needed).
   - "I'll type the data": ask the user to paste it; append it to the article text under `=== [user-provided data] ===`.

## Stage 2 — Interview
Goal: fill `OUT/project.yaml` (start from `SKILL/resources/templates/project.yaml`; keep anything already filled and ask only about empty fields).

1. Read `OUT/01_text/manifest.json` and look at each article's `title_guess` and `abstract_snippet` (not the full text). Form a picture of what the articles are about.
2. AskUserQuestion (one call, 3 questions):
   - Type of work: "עבודה סמינריונית (Recommended)" / "מאמר סקירה לכתב עת" (profiles in `resources/profiles/`)
   - Language of the paper: "עברית" / "English"
   - Length: the profile default (say it in words and approximate pages) / shorter / longer
3. Research question: propose 2–3 concrete research questions that these articles can actually answer, each as an option (the user can type their own via "Other"). Then ask about sub-questions: "המערכת תציע אחרי קריאת המאמרים (Recommended)" / "אכתוב אותן בעצמי".
4. Free-text details — ask in one plain message, listing the fields as a short numbered list and saying they may skip any: working title, academic field, course name, what the reader already knows (so it is not explained), student name and ID, lecturer, institution and department, how the articles were chosen (databases, keywords, years — used for the review-method section). Wait for the reply and fill what they gave.
5. Rules: copy `SKILL/resources/templates/rules.<he|en>.md` to `PROJECT/rules.md` if it does not exist. AskUserQuestion: "אין לי כללים מיוחדים" / "אכתוב כללים כאן בצ'אט" / "אערוך את הקובץ rules.md ואגיד כשסיימתי". If they type rules, add them under the right headings in `PROJECT/rules.md`.
6. Check `PROJECT/rules.md` against `resources/core-rules.md`. If a project rule conflicts with a locked rule (for example "you may add well-known sources", "round the numbers"), quote it, explain in one sentence why it cannot apply, and ask whether to delete or rephrase it. Do not continue with a conflicting rule in place.
7. Write `project.yaml`, then run `PY SKILL/scripts/tools.py brief --out OUT --skill-dir SKILL`. This writes `OUT/brief.md` and `OUT/rubric.md`, which every agent reads. Re-run it whenever `project.yaml` or `rules.md` changes.

## Stage 3 — Summaries
1. For every article not excluded, launch `lit-review:summarizer` (≤5 in parallel). Task message: OUT, brief path, the ID, the text file, the output path `OUT/03_summaries/<ID>.json`.
2. For every finished summary, launch `lit-review:summary-verifier`, output `OUT/04_summary_checks/<ID>.json`.
3. Verdict `fix` or `redo`: run the summarizer again with the check file as feedback, then verify once more. If it still does not pass, keep it, mark it in `state.json`, and mention it at the checkpoint.
4. Run `PY SKILL/scripts/tools.py overview --out OUT`.

## Stage 4 — Checkpoint 1: summaries
Show the user a compact table in the chat (ID, authors and year, relevance, one line; flag problems) and say the full summaries are in `review-output/03_summaries/`. Ask (AskUserQuestion): "מאשר, אפשר להמשיך" / "יש מאמרים להוציא" / "יש לי הערות". Apply exclusions to `project.yaml` (re-run `tools.py brief`) and save notes to `state.json` → `notes` (pass them to the theme mapper).

## Stage 5 — Theme matrix
Launch `lit-review:theme-mapper` (output `OUT/05_matrix.md`; include the user's notes). If it proposed sub-questions, show them and ask: "להשתמש בהן (Recommended)" / "לשנות" (free text). Save the chosen sub-questions into `project.yaml` and re-run `tools.py brief`. If it warned that an existing sub-question cannot be answered from the articles, tell the user and ask whether to keep, change or drop it.

## Stage 6 — Outline and checkpoint 2
1. Launch `lit-review:outliner` (outputs `OUT/06_outline.md` and `OUT/06_outline.json`).
2. Show the user the outline briefly in the chat: each part's heading, one-line argument and word budget. Ask: "מאשר את המבנה" / "יש לי שינויים". On changes, re-run the outliner with their feedback and show again (up to 3 times).

## Stage 7 — Writing
1. Content chapters: one `lit-review:section-writer` per `kind: chapter` section, in parallel. Task message: OUT, brief, outline paths, the section key, its order number NN, the section's full heading as written in the outline (keys like `ch4` are internal labels and do not match chapter numbers, so the heading is what identifies the section), the output path `OUT/07_sections/<NN>_<key>.md`, and the list of summary paths for its `ids`. When a writer finishes, check that the file's first heading matches the outline before moving on.
2. Discussion: after all chapters exist, one `lit-review:section-writer` for the `discussion` section, also given the chapter files.
3. `lit-review:integrator` assembles `OUT/08_drafts/v1.md`.
4. Run `PY SKILL/scripts/tools.py wordcount --draft OUT/08_drafts/v1.md` and `tools.py citations --out OUT --draft ...`. Keep the numbers for the critic.

## Stage 8 — Fact-check
1. `lit-review:fact-checker` in `full` mode on v1 → `OUT/09_fact_checks/v1.json`.
2. If `fixes_needed`: `lit-review:reviser` with the fact-check → `v2.md`. The current version is now v2 (or v1 if clean). Append each version to `state.json` → `versions`.

## Stage 9 — Improvement loop (critic ↔ reviser)
Let `v` be the current version. For round = 1 … 4:
1. Run `tools.py wordcount` and `tools.py citations` on `v`.
2. `lit-review:critic` on `v` (give it the previous round's review, if any, and the two tool outputs) → `OUT/10_reviews/<v>.json`. Record scores in `state.json` → `rounds`.
3. Tell the user one line of progress, e.g. "סבב 2: ממוצע 4.1 (היה 3.6)".
4. Stop if `pass` is true, if this is round 4, or if the mean has not improved for 2 consecutive rounds.
5. Otherwise: `lit-review:reviser` with the review → next version `w`.
6. `PY SKILL/scripts/tools.py changed --old <v> --new <w>`; run `lit-review:fact-checker` in `changed` mode with those paragraphs → `OUT/09_fact_checks/<w>.json`. If it finds problems, `lit-review:reviser` with that fact-check → next version, which becomes `v`; otherwise `v = w`.

## Stage 10 — Choose the best version and build the Word file
1. Best version = the scored version with the highest mean (ties → the later one). It is fact-checked by construction.
2. Run `PY SKILL/scripts/build_docx.py --out OUT --draft OUT/08_drafts/<best>.md`. It writes `OUT/final/<title>.docx` and prints warnings.
3. Write `OUT/final/report.md` in the user's language:
   - Articles used and excluded (and why); articles never cited
   - PDF fixes, transcriptions, damaged tables and how they were handled
   - Summary checks that did not fully pass
   - Model set used (and whether the fallback was active)
   - Rounds table: version, scores per criterion, mean
   - Final fact-check counts; unfixed critic issues from the best version's review
   - Places that need the student: `NEEDS STUDENT INPUT` markers, citations highlighted in yellow (unknown IDs), formulas that were inserted as plain text (Word can convert them: select → Insert → Equation)
   - Word count against the target
   - A reminder: this is a strong draft, not a finished submission; read it fully, verify the flagged points, and check the institution's policy on AI use (many require disclosure).
4. Tell the user, briefly: where the Word file is, that Word may ask to update fields when it opens (answer Yes, this builds the table of contents), the final scores in one line, and the two or three most important things to check from the report.

---

## Handling problems
- A script fails: read its output, fix what you can (missing package → `setup_env.py --install`; wrong path → correct it), retry once, otherwise explain in plain words and suggest the next step.
- An agent fails or writes invalid JSON: retry once with the error in the task message; then continue without it and record it in `state.json` → `notes` and in the final report.
- Usage limit reached: tell the user the work is saved and they can continue later by running the same command in the same folder; it will resume where it stopped.
- The user asks for changes after the paper is built: decide the smallest stage that fixes it (e.g. one chapter → section-writer for that section, then integrator, fact-check `changed`, critic once, build again).
