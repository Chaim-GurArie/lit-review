#!/usr/bin/env python3
"""Extract text from every PDF in a folder and check the extraction quality.

Usage:
    python3 pdf_prepare.py --src <folder with PDFs> --out <review-output folder> [--lang he|en]
    python3 pdf_prepare.py --src ... --out ... --only Cohen2023 Levi2021   # re-run some IDs

Writes into <out>:
    01_text/<ID>.txt          extracted text with page markers "=== [page N] ==="
    01_text/<ID>.refs.txt     the reference list cut from the end of the article (if found)
    01_text/manifest.json     one record per article (id, file, metadata guesses, status, issues)
    02_pdf_check/report.json  the same, plus duplicates and a summary
    02_pdf_check/report.md    human-readable report in the requested language

Status per article:
    ok     nothing to report
    fixed  problems were found and repaired automatically (listed under "fixes")
    warn   text is usable but a part needs attention (tables, formulas, missing metadata, duplicate)
    fail   text is not usable as it is (scanned, garbled, empty, cannot open)

Exit code 0 when no article failed, 3 when at least one failed (the report is still written).
"""
import argparse
import datetime
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    print(json.dumps({"error": "pdfplumber is not installed. Run setup_env.py --install"}))
    sys.exit(1)

HEB = re.compile(r"[֐-׿]")
HEB_WORD = re.compile(r"[א-ת]+")
FINALS = set("ךםןףץ")
LATIN_RUN = re.compile(r"[%$€£]?[A-Za-z0-9][A-Za-z0-9.,%\-/:_+=]*[A-Za-z0-9%]|[%$€£]?[A-Za-z0-9]")
LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    "ﬅ": "st", "ﬆ": "st", "­": "",
}
MIRROR = str.maketrans("()[]{}<>", ")(][}{><")
MATH_CHARS = set("∑∫∏√∂∇≤≥≈≠±×÷∞∈∉⊂⊆∪∩∀∃→⇒⇔αβγδεθλμσφψωΣΩΔΠ")
EN_STOP = set(
    "the of and to in is that for on with as by are be this from or an at which we it "
    "not were was can these their our than also has have been between results using "
    "study data model method based used two more such each into".split()
)
HE_STOP = set("של את על עם כי לא או גם זה זו היא הוא בין אשר כל יותר כמו אם אך הם הן לפי".split())
REF_HEAD = re.compile(
    r"^\s*(\d+\.?\s*)?(references|bibliography|literature cited|works cited|reference list|"
    r"מקורות|ביבליוגרפיה|רשימת מקורות|רשימת ספרות)\s*:?\s*$",
    re.IGNORECASE,
)
DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+[^\s\"<>.,;])")
YEAR = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")


# --------------------------------------------------------------------------- text helpers
def fix_ligatures(text):
    n = 0
    for k, v in LIGATURES.items():
        if k in text:
            n += text.count(k)
            text = text.replace(k, v)
    return text, n


def fix_hyphenation(text):
    pattern = re.compile(r"([A-Za-z]{2,})-\n([a-z]{2,})")
    n = len(pattern.findall(text))
    return pattern.sub(r"\1\2\n", text), n


def hebrew_reversed_score(text):
    """Share of Hebrew words that start with a final letter (high = reversed text)."""
    start = end = 0
    for w in HEB_WORD.findall(text):
        if len(w) < 2:
            continue
        if w[0] in FINALS:
            start += 1
        if w[-1] in FINALS:
            end += 1
    total = start + end
    return (start / total) if total >= 20 else 0.0, total


def unreverse_line(line):
    if not HEB.search(line):
        return line
    rev = line[::-1].translate(MIRROR)
    return LATIN_RUN.sub(lambda m: m.group(0)[::-1], rev)


def unreverse_hebrew(text):
    return "\n".join(unreverse_line(l) for l in text.split("\n"))


def language_of(text):
    heb = len(HEB.findall(text))
    lat = len(re.findall(r"[A-Za-z]", text))
    if heb + lat == 0:
        return "unknown"
    return "he" if heb > lat else "en"


def word_tokens(text):
    return re.findall(r"[A-Za-zא-ת]+", text)


def stopword_ratio(text, lang):
    toks = [t.lower() for t in word_tokens(text)]
    if len(toks) < 50:
        return None
    stop = HE_STOP if lang == "he" else EN_STOP
    return sum(1 for t in toks if t in stop) / len(toks)


def letter_ratio(text):
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    return sum(1 for c in chars if c.isalpha()) / len(chars)


# --------------------------------------------------------------------------- page extraction
def detect_columns(page, words):
    """Return (split_x, header_bottom) for a two-column page, else None."""
    if len(words) < 80:
        return None
    W, H = page.width, page.height
    best = None
    for frac in [i / 100 for i in range(36, 65, 2)]:
        x = W * frac
        crossing = [w for w in words if w["x0"] < x < w["x1"]]
        left = sum(1 for w in words if w["x1"] <= x)
        right = sum(1 for w in words if w["x0"] >= x)
        if left < 0.25 * len(words) or right < 0.25 * len(words):
            continue
        # a real gutter: nothing in the body comes within 4pt of the split line
        body_cross = [w for w in words if w["top"] > 0.45 * H and w["x0"] - 4 < x < w["x1"] + 4]
        score = len(body_cross)
        left_lines = {round(w["top"]) for w in words if w["x1"] <= x and w["top"] > 0.2 * H}
        right_lines = {round(w["top"]) for w in words if w["x0"] >= x and w["top"] > 0.2 * H}
        if len(left_lines) < 12 or len(right_lines) < 12:
            continue
        if best is None or score < best[0]:
            best = (score, x, crossing)
    if best is None:
        return None
    score, x, crossing = best
    if score > 0.01 * len(words):
        return None
    header = [w["bottom"] for w in crossing if w["top"] <= 0.45 * H]
    header_bottom = max(header) + 1 if header else 0
    return x, header_bottom


def extract_page(page):
    words = page.extract_words(x_tolerance=1.5, y_tolerance=3, keep_blank_chars=False)
    cols = detect_columns(page, words)
    kw = dict(x_tolerance=1.5, y_tolerance=3)
    if not cols:
        return page.extract_text(**kw) or "", False
    x, header_bottom = cols
    W, H = page.width, page.height
    parts = []
    if header_bottom > 0:
        parts.append(page.crop((0, 0, W, header_bottom)).extract_text(**kw) or "")
    left = page.crop((0, header_bottom, x, H)).extract_text(**kw) or ""
    right = page.crop((x, header_bottom, W, H)).extract_text(**kw) or ""
    sample = left + right
    # Hebrew pages read right column first
    if language_of(sample) == "he":
        parts += [right, left]
    else:
        parts += [left, right]
    return "\n".join(p for p in parts if p), True


def count_tables(page):
    try:
        return len(page.find_tables())
    except Exception:
        return 0


# --------------------------------------------------------------------------- metadata
def ascii_slug(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if c.isascii() and (c.isalnum()))
    return s


def guess_metadata(meta, first_text, fname):
    title = (meta or {}).get("Title") or ""
    author = (meta or {}).get("Author") or ""
    if len(title) < 8 or title.lower().startswith(("microsoft", "untitled")) or title.endswith((".doc", ".docx", ".pdf")):
        title = ""
    if not title:
        for line in first_text.split("\n")[:12]:
            line = line.strip()
            if 20 <= len(line) <= 200 and not re.search(r"(journal|vol\.|doi|issn|http|©|received)", line, re.I):
                title = line
                break
    years = [int(y) for y in YEAR.findall(first_text[:4000]) if int(y) <= datetime.date.today().year]
    year = max(set(years), key=years.count) if years else None
    doi = None
    m = DOI.search(first_text[:6000])
    if m:
        doi = m.group(1)
    family = ""
    if author:
        first = re.split(r"[;,&]| and ", author)[0].strip()
        parts = [p for p in re.split(r"\s+", first) if p]
        if parts:
            cand = ascii_slug(parts[-1])
            if 2 <= len(cand) <= 20 and cand.isalpha():
                family = cand.capitalize()
    abstract = ""
    m = re.search(r"(abstract|תקציר)\s*[:.\-—]?\s*(.{200,1800}?)(\n\s*(1\.?\s*)?(introduction|keywords|key words|מבוא|מילות מפתח))",
                  first_text, re.I | re.S)
    if m:
        abstract = re.sub(r"\s+", " ", m.group(2)).strip()
    else:
        abstract = re.sub(r"\s+", " ", first_text[:1200]).strip()
    return {
        "title_guess": title.strip(),
        "authors_guess": author.strip(),
        "first_author_family": family,
        "year_guess": year,
        "doi": doi,
        "abstract_snippet": abstract[:1500],
    }


def make_id(md, fname, used):
    if md["first_author_family"] and md["year_guess"]:
        base = f'{md["first_author_family"]}{md["year_guess"]}'
    else:
        base = ascii_slug(Path(fname).stem)[:24] or "Article"
        if not base[0].isalpha():
            base = "A" + base
    cand, i = base, 0
    while cand in used:
        cand = base + "abcdefghijklmnopqrstuvwxyz"[i]
        i += 1
    used.add(cand)
    return cand


# --------------------------------------------------------------------------- references
def split_references(text):
    lines = text.split("\n")
    n = len(lines)
    for i in range(n - 1, int(n * 0.45), -1):
        if REF_HEAD.match(lines[i]):
            body = "\n".join(lines[:i])
            refs = "\n".join(lines[i + 1:])
            # do not cut if what follows is tiny (probably a running header)
            if len(refs) > 300:
                return body, refs
    return text, ""


# --------------------------------------------------------------------------- duplicates
def shingles(text, k=5, limit=4000):
    toks = [t.lower() for t in word_tokens(text)][:limit]
    return {hash(" ".join(toks[i:i + k])) for i in range(max(0, len(toks) - k))}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------------------- main per file
def process(pdf_path, used_ids, text_dir):
    rec = {
        "file": pdf_path.name,
        "path": str(pdf_path),
        "status": "ok",
        "issues": [],
        "fixes": [],
        "pages": 0,
        "words": 0,
        "language": "unknown",
        "visual_check_pages": [],
    }
    try:
        pdf = pdfplumber.open(str(pdf_path))
    except Exception as e:
        rec["id"] = make_id({"first_author_family": "", "year_guess": None}, pdf_path.name, used_ids)
        rec["status"] = "fail"
        rec["issues"].append({"code": "OPEN_ERROR", "detail": str(e)[:300]})
        return rec, ""

    with pdf:
        rec["pages"] = len(pdf.pages)
        page_texts, empty_pages, column_pages, table_pages = [], [], 0, {}
        for i, page in enumerate(pdf.pages, start=1):
            try:
                txt, two_col = extract_page(page)
            except Exception as e:
                txt, two_col = "", False
                rec["issues"].append({"code": "PAGE_ERROR", "detail": f"page {i}: {str(e)[:120]}"})
            if two_col:
                column_pages += 1
            if len(txt.strip()) < 80:
                empty_pages.append(i)
            t = count_tables(page)
            if t:
                table_pages[i] = t
            page_texts.append(txt)
        meta = pdf.metadata or {}

    raw = "\n".join(page_texts)
    lang = language_of(raw)
    rec["language"] = lang

    # --- repairs
    lig_total, hyph_total = 0, 0
    fixed_pages = []
    rev_score, rev_n = hebrew_reversed_score(raw)
    reversed_fixed = False
    if lang == "he" and rev_score > 0.6:
        trial = unreverse_hebrew(raw)
        new_score, _ = hebrew_reversed_score(trial)
        if new_score < 0.3:
            reversed_fixed = True
        else:
            rec["issues"].append({"code": "HEBREW_REVERSED", "detail": f"score {rev_score:.2f}, automatic fix failed"})
    for p in page_texts:
        if reversed_fixed:
            p = unreverse_hebrew(p)
        p, a = fix_ligatures(p)
        p, b = fix_hyphenation(p)
        lig_total += a
        hyph_total += b
        fixed_pages.append(p)
    if reversed_fixed:
        rec["fixes"].append({"code": "HEBREW_REVERSED_FIXED", "detail": f"reversed Hebrew text corrected (score {rev_score:.2f})"})
    if lig_total:
        rec["fixes"].append({"code": "LIGATURES", "detail": f"{lig_total} ligature characters replaced"})
    if hyph_total:
        rec["fixes"].append({"code": "HYPHENATION", "detail": f"{hyph_total} words split across lines rejoined"})
    if column_pages:
        rec["fixes"].append({"code": "TWO_COLUMNS", "detail": f"two-column layout read in order on {column_pages} pages"})

    full = "\n".join(f"=== [page {i}] ===\n{t}" for i, t in enumerate(fixed_pages, start=1))
    plain = "\n".join(fixed_pages)

    # --- checks
    chars_per_page = len(plain.strip()) / max(1, rec["pages"])
    cid = len(re.findall(r"\(cid:\d+\)", plain))
    repl = plain.count("�")
    toks = word_tokens(plain)
    rec["words"] = len(toks)
    lr = letter_ratio(plain)
    sr = stopword_ratio(plain, lang)

    if rec["pages"] and len(empty_pages) >= max(1, int(0.8 * rec["pages"])):
        rec["issues"].append({"code": "SCANNED", "detail": f"{len(empty_pages)} of {rec['pages']} pages have no text layer"})
    elif empty_pages and len(empty_pages) > 1:
        rec["issues"].append({"code": "PARTIAL_SCANNED", "detail": f"pages without text: {empty_pages[:15]}"})
    if not toks:
        rec["issues"].append({"code": "EMPTY", "detail": "no words extracted"})
    if toks and (cid > 0.01 * len(toks) or repl > 0.01 * len(plain) or lr < 0.5):
        rec["issues"].append({"code": "GARBLED", "detail": f"cid={cid}, replacement chars={repl}, letter ratio={lr:.2f}"})
    elif sr is not None and sr < (0.05 if lang == "he" else 0.12):
        rec["issues"].append({"code": "LOW_REAL_WORDS", "detail": f"common-word ratio {sr:.2f} is unusually low; text may be scrambled"})
    if table_pages:
        pages_list = sorted(table_pages)
        rec["issues"].append({"code": "TABLES", "detail": f"{sum(table_pages.values())} tables on pages {pages_list[:12]}; check that their numbers were extracted correctly"})
    math = sum(1 for c in plain if c in MATH_CHARS)
    if toks and math > max(15, 0.004 * len(plain)):
        rec["issues"].append({"code": "FORMULAS", "detail": f"{math} math symbols; formulas are often damaged by extraction"})

    first_text = "\n".join(fixed_pages[:2])
    md = guess_metadata(meta, first_text, pdf_path.name)
    rec.update(md)
    rec["id"] = make_id(md, pdf_path.name, used_ids)
    if not md["first_author_family"] or not md["year_guess"]:
        rec["issues"].append({"code": "NO_METADATA", "detail": "authors or year not found automatically; the summarizer will read them from the article"})

    body, refs = split_references(full)
    if refs:
        rec["fixes"].append({"code": "REFERENCES_REMOVED", "detail": "reference list moved to a separate file"})
    rec["words_body"] = len(word_tokens(body))

    # visual check sample: first page plus the page with most tables (or the middle page)
    vis = [1] if rec["pages"] else []
    if table_pages:
        vis.append(max(table_pages, key=table_pages.get))
    elif rec["pages"] > 2:
        vis.append(rec["pages"] // 2 + 1)
    rec["visual_check_pages"] = sorted(set(vis))

    # --- status
    codes = {i["code"] for i in rec["issues"]}
    if codes & {"SCANNED", "EMPTY", "GARBLED", "OPEN_ERROR", "HEBREW_REVERSED"}:
        rec["status"] = "fail"
    elif codes & {"TABLES", "FORMULAS", "NO_METADATA", "PARTIAL_SCANNED", "LOW_REAL_WORDS", "PAGE_ERROR"}:
        rec["status"] = "warn"
    elif rec["fixes"]:
        rec["status"] = "fixed"

    (text_dir / f'{rec["id"]}.txt').write_text(
        f"# SOURCE FILE: {pdf_path.name}\n# ID: {rec['id']}\n# PAGES: {rec['pages']}\n\n{body}\n",
        encoding="utf-8",
    )
    if refs:
        (text_dir / f'{rec["id"]}.refs.txt').write_text(refs, encoding="utf-8")
    return rec, plain


# --------------------------------------------------------------------------- report
MSG = {
    "he": {
        "title": "דוח בדיקת קובצי PDF",
        "summary": "סיכום: {ok} תקינים, {fixed} תוקנו אוטומטית, {warn} דורשים תשומת לב, {fail} לא תקינים",
        "status": {"ok": "✅ תקין", "fixed": "🔧 תוקן אוטומטית", "warn": "⚠️ דורש תשומת לב", "fail": "❌ לא תקין"},
        "codes": {
            "SCANNED": "הקובץ סרוק (תמונה ללא שכבת טקסט)",
            "PARTIAL_SCANNED": "חלק מהעמודים סרוקים",
            "EMPTY": "לא חולץ טקסט",
            "GARBLED": "הטקסט שחולץ משובש (בעיית קידוד גופנים)",
            "LOW_REAL_WORDS": "הטקסט נראה משובש חלקית",
            "OPEN_ERROR": "לא ניתן לפתוח את הקובץ (פגום או מוגן בסיסמה)",
            "PAGE_ERROR": "שגיאה בעמוד מסוים",
            "HEBREW_REVERSED": "העברית יצאה הפוכה והתיקון האוטומטי נכשל",
            "TABLES": "יש טבלאות; כדאי לוודא שהמספרים חולצו נכון",
            "FORMULAS": "יש נוסחאות; הן נפגעות לעיתים קרובות בחילוץ",
            "NO_METADATA": "לא זוהו מחברים או שנה אוטומטית (ייקראו מתוך המאמר)",
            "DUPLICATE": "נראה כמו אותו מאמר כמו",
            "HEBREW_REVERSED_FIXED": "עברית הפוכה תוקנה",
            "LIGATURES": "תווים מחוברים תוקנו",
            "HYPHENATION": "מילים שנחתכו בסוף שורה חוברו",
            "TWO_COLUMNS": "פריסת שני טורים נקראה בסדר הנכון",
            "REFERENCES_REMOVED": "רשימת המקורות הועברה לקובץ נפרד",
        },
        "file": "קובץ", "id": "מזהה", "pages": "עמודים", "words": "מילים", "state": "מצב", "notes": "הערות",
    },
    "en": {
        "title": "PDF check report",
        "summary": "Summary: {ok} OK, {fixed} fixed automatically, {warn} need attention, {fail} not usable",
        "status": {"ok": "✅ OK", "fixed": "🔧 Fixed", "warn": "⚠️ Needs attention", "fail": "❌ Not usable"},
        "codes": {},
        "file": "File", "id": "ID", "pages": "Pages", "words": "Words", "state": "Status", "notes": "Notes",
    },
}


def write_report(records, dups, out_dir, lang):
    m = MSG.get(lang, MSG["en"])
    counts = {s: sum(1 for r in records if r["status"] == s) for s in ("ok", "fixed", "warn", "fail")}
    lines = [f"# {m['title']}", "", m["summary"].format(**counts), "",
             f"| {m['file']} | {m['id']} | {m['pages']} | {m['words']} | {m['state']} | {m['notes']} |",
             "|---|---|---|---|---|---|"]
    for r in records:
        notes = []
        for it in r["issues"] + r["fixes"]:
            label = m["codes"].get(it["code"], it["code"])
            if it["code"] == "DUPLICATE":
                notes.append(f"{label} {it['detail']}")
            else:
                notes.append(label)
        lines.append(f"| {r['file']} | {r['id']} | {r['pages']} | {r['words']} | {m['status'][r['status']]} | {'; '.join(notes)} |")
    lines.append("")
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "report.json").write_text(
        json.dumps({"counts": counts, "duplicates": dups, "articles": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lang", default="he")
    ap.add_argument("--only", nargs="*", help="re-process only these files (file names)")
    args = ap.parse_args()

    src, out = Path(args.src).resolve(), Path(args.out).resolve()
    text_dir, check_dir = out / "01_text", out / "02_pdf_check"
    text_dir.mkdir(parents=True, exist_ok=True)
    check_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(
        p for p in src.rglob("*")
        if p.is_file() and p.suffix.lower() == ".pdf" and out not in p.parents and not p.name.startswith(".")
    )
    manifest_path = text_dir / "manifest.json"
    previous = {}
    if args.only and manifest_path.exists():
        previous = {r["file"]: r for r in json.loads(manifest_path.read_text(encoding="utf-8"))}

    used, records, texts = set(), [], {}
    for p in pdfs:
        if args.only and p.name not in args.only and p.name in previous:
            rec = previous[p.name]
            used.add(rec["id"])
            records.append(rec)
            tp = text_dir / f"{rec['id']}.txt"
            texts[rec["id"]] = tp.read_text(encoding="utf-8") if tp.exists() else ""
            continue
        rec, plain = process(p, used, text_dir)
        records.append(rec)
        texts[rec["id"]] = plain

    # duplicates
    sh = {i: shingles(t) for i, t in texts.items()}
    ids = list(sh)
    dups = []
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            j = jaccard(sh[ids[a]], sh[ids[b]])
            if j > 0.5:
                dups.append({"a": ids[a], "b": ids[b], "similarity": round(j, 2)})
    by_id = {r["id"]: r for r in records}
    for d in dups:
        for x, y in ((d["a"], d["b"]), (d["b"], d["a"])):
            r = by_id[x]
            if not any(i["code"] == "DUPLICATE" for i in r["issues"]):
                r["issues"].append({"code": "DUPLICATE", "detail": f"{y} ({d['similarity']:.0%})"})
                if r["status"] in ("ok", "fixed"):
                    r["status"] = "warn"

    manifest_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = write_report(records, dups, check_dir, args.lang)
    print(json.dumps({"articles": len(records), "counts": counts, "duplicates": dups,
                      "report": str(check_dir / "report.md")}, ensure_ascii=False))
    return 3 if counts["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
