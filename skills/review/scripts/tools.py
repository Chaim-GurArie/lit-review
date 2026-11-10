#!/usr/bin/env python3
"""Small utilities used by the orchestrator.

    python3 tools.py brief    --out <review-output> --skill-dir <skill dir>
        Compile review-output/brief.md from core rules + profile + project.yaml + rules.md,
        and copy the rubric to review-output/rubric.md. Prints the profile's length budget.

    python3 tools.py overview --out <review-output>
        Write review-output/03_summaries/overview.md: one row per summary (for the user's check).

    python3 tools.py citations --out <review-output> --draft <draft.md>
        Report citation health: unknown IDs, articles never cited, paragraphs without citations.

    python3 tools.py wordcount --draft <draft.md>
        Words per top-level part and in total.

    python3 tools.py changed --old <v1.md> --new <v2.md>
        Paragraphs that are new or changed in v2 (for a focused fact-check).
"""
import argparse
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

CIT = re.compile(r"\[([^\[\]]+)\]")


def load_yaml(p):
    return yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}


def front_matter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, text[m.end():]


def summary_ids(out):
    d = Path(out) / "03_summaries"
    return sorted(p.stem for p in d.glob("*.json")) if d.exists() else []


def words(text):
    return len(re.findall(r"[\w֐-׿]+(?:['’\-][\w֐-׿]+)*", text))


def strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


# ------------------------------------------------------------------ brief
def cmd_brief(a):
    out, skill = Path(a.out), Path(a.skill_dir)
    proj = load_yaml(out / "project.yaml")
    profile_id = proj.get("profile") or "seminar"
    pfile = skill / "resources" / "profiles" / f"{profile_id}.md"
    if not pfile.exists():
        print(json.dumps({"error": f"profile {profile_id} not found"}))
        return 1
    meta, profile_body = front_matter(pfile.read_text(encoding="utf-8"))
    length = proj.get("length_words") or meta.get("default_length_words")
    core = (skill / "resources" / "core-rules.md").read_text(encoding="utf-8")
    rules_path = Path(a.rules) if a.rules else out.parent / "rules.md"
    rules = strip_comments(rules_path.read_text(encoding="utf-8")) if rules_path.exists() else ""
    rules_lines = [l for l in rules.splitlines() if l.strip().startswith(("-", "*")) or re.match(r"^\d+\.", l.strip())]
    project_view = {k: v for k, v in proj.items() if k not in ("format", "models")}
    parts = [
        "# BRIEF (read this first)",
        "",
        "Precedence: core rules (locked) > project rules > project settings > profile.",
        "",
        "## Project settings",
        "```yaml",
        yaml.safe_dump(project_view, allow_unicode=True, sort_keys=False).strip(),
        "```",
        f"Target length: about {length} words (body text, excluding bibliography).",
        "",
        core.strip(),
        "",
        "# Project rules (from rules.md)",
        "Apply the rules under 'General' / 'כללי' always, and the section that matches your role:",
        "Writing / כתיבה → section-writer, integrator, reviser; Critique / ביקורת → critic, fact-checker; Structure / מבנה → outliner, integrator.",
        "",
        (rules.strip() if rules_lines else "(no project rules)"),
        "",
        profile_body.strip(),
        "",
    ]
    (out / "brief.md").write_text("\n".join(parts), encoding="utf-8")
    shutil.copyfile(skill / "resources" / "rubric.md", out / "rubric.md")
    print(json.dumps({"brief": str(out / "brief.md"), "profile": profile_id, "length_words": length,
                      "project_rules": len(rules_lines), "cover": meta.get("id") != "review-article"},
                     ensure_ascii=False))
    return 0


# ------------------------------------------------------------------ overview
def cmd_overview(a):
    out = Path(a.out)
    proj = load_yaml(out / "project.yaml") if (out / "project.yaml").exists() else {}
    he = (proj.get("language") or "he") == "he"
    rows = []
    for p in sorted((out / "03_summaries").glob("*.json")):
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            rows.append((p.stem, "?", "?", "invalid JSON", ""))
            continue
        c = s.get("citation", {})
        auth = ", ".join(x.get("family", "") for x in (c.get("authors") or [])[:3])
        flags = []
        chk = out / "04_summary_checks" / f"{p.stem}.json"
        if chk.exists():
            try:
                v = json.loads(chk.read_text(encoding="utf-8"))
                if v.get("verdict") not in ("pass", None):
                    flags.append(("נבדק: " if he else "check: ") + v.get("verdict", ""))
            except Exception:
                pass
        if s.get("extraction_problems"):
            flags.append(("בעיות חילוץ" if he else "extraction problems"))
        rows.append((s.get("id", p.stem), f"{auth} ({c.get('year', '?')})", s.get("relevance", "?"),
                     (s.get("one_line") or "").replace("|", "/"), "; ".join(flags)))
    head = ("| מזהה | מחברים | רלוונטיות | במשפט אחד | הערות |" if he
            else "| ID | Authors | Relevance | One line | Notes |")
    lines = [("# סקירת התמציות" if he else "# Summary overview"), "", head, "|---|---|---|---|---|"]
    lines += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |" for r in rows]
    (out / "03_summaries" / "overview.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"overview": str(out / "03_summaries" / "overview.md"), "count": len(rows)}, ensure_ascii=False))
    return 0


# ------------------------------------------------------------------ citations
def paragraphs(text):
    paras = []
    for block in re.split(r"\n\s*\n", text):
        b = block.strip()
        if not b or b.startswith(("#", "|", "$$")):
            continue
        paras.append(b)
    return paras


def cited_ids(text, known):
    found, unknown = set(), set()
    for m in CIT.finditer(text):
        for part in m.group(1).split(";"):
            tok = part.strip().split(",")[0].strip().lstrip("@")
            if not tok or " " in tok:
                continue
            if tok in known:
                found.add(tok)
            elif re.match(r"^[A-Za-z][A-Za-z0-9\-]*\d{2,4}[a-z]?$", tok):
                unknown.add(tok)
    return found, unknown


def cmd_citations(a):
    out = Path(a.out)
    proj = load_yaml(out / "project.yaml") if (out / "project.yaml").exists() else {}
    known = set(summary_ids(out)) - set(proj.get("excluded_articles") or [])
    text = Path(a.draft).read_text(encoding="utf-8")
    found, unknown = cited_ids(text, known)
    uncited_paras = []
    for i, p in enumerate(paragraphs(text), 1):
        if words(p) >= 40 and not CIT.search(p):
            uncited_paras.append({"n": i, "start": p[:90]})
    print(json.dumps({
        "known_articles": len(known),
        "cited": sorted(found),
        "never_cited": sorted(known - found),
        "unknown_ids": sorted(unknown),
        "long_paragraphs_without_citation": uncited_paras[:40],
    }, ensure_ascii=False, indent=2))
    return 0


# ------------------------------------------------------------------ wordcount
def cmd_wordcount(a):
    text = Path(a.draft).read_text(encoding="utf-8")
    parts, current = {}, "(before first heading)"
    for line in text.splitlines():
        if re.match(r"^#\s+", line):
            current = line.lstrip("#").strip()
            parts.setdefault(current, 0)
            continue
        if line.startswith("|") or line.strip().startswith("$$"):
            continue
        clean = CIT.sub("", line)
        parts[current] = parts.get(current, 0) + words(clean)
    total = sum(parts.values())
    print(json.dumps({"total": total, "parts": parts}, ensure_ascii=False, indent=2))
    return 0


# ------------------------------------------------------------------ changed
def cmd_changed(a):
    old = set(paragraphs(Path(a.old).read_text(encoding="utf-8")))
    new = paragraphs(Path(a.new).read_text(encoding="utf-8"))
    changed = [{"n": i, "text": p} for i, p in enumerate(new, 1) if p not in old]
    print(json.dumps({"changed_paragraphs": len(changed), "paragraphs": changed}, ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("brief"); b.add_argument("--out", required=True); b.add_argument("--skill-dir", required=True); b.add_argument("--rules")
    o = sub.add_parser("overview"); o.add_argument("--out", required=True)
    c = sub.add_parser("citations"); c.add_argument("--out", required=True); c.add_argument("--draft", required=True)
    w = sub.add_parser("wordcount"); w.add_argument("--draft", required=True)
    d = sub.add_parser("changed"); d.add_argument("--old", required=True); d.add_argument("--new", required=True)
    a = ap.parse_args()
    return {"brief": cmd_brief, "overview": cmd_overview, "citations": cmd_citations,
            "wordcount": cmd_wordcount, "changed": cmd_changed}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
