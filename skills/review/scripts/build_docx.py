#!/usr/bin/env python3
"""Build the final Word document from the selected draft.

Usage:
    python3 build_docx.py --out <review-output> --draft <review-output/08_drafts/v3.md> [--docx <path>]

Reads:
    <out>/project.yaml            title, language, cover details, format overrides, profile
    <out>/03_summaries/*.json     the "citation" object of every article (for APA)
    the draft                     Markdown written by the agents (see "Draft format" below)

Draft format:
    # Heading 1 (each starts on a new page), ## Heading 2, ### Heading 3
    Paragraphs separated by blank lines. **bold**, *italic*.
    - bullet / 1. numbered
    | pipe | tables |   (first row = header; the |---| line is skipped)
    $$ formula $$        (own line; rendered centered, as text)
    > quotation          (indented)
    Citations: [Cohen2023]  [Cohen2023; Levi2021]  [Cohen2023, p. 12]   → (Cohen, 2023) …
    Narrative citation: [@Cohen2023] → Cohen et al. (2023)

Writes the .docx (default: <out>/final/<title>.docx) and prints JSON with warnings.
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

import yaml
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HEB = re.compile(r"[\u0590-\u05FF]")
LATIN = re.compile(r"[A-Za-z]")
CIT = re.compile(r"\[(@?)([^\[\]]+)\]")

LABELS = {
    "he": {"toc": "תוכן העניינים", "bib": "ביבליוגרפיה", "student": "מגיש/ה", "id": "ת.ז.", "lecturer": "מרצה",
           "course": "קורס", "date": "תאריך", "kind": {"seminar": "עבודה סמינריונית", "review-article": "מאמר סקירה"},
           "toc_hint": "לחצו כאן לחיצה ימנית ובחרו 'עדכן שדה' כדי ליצור את תוכן העניינים.",
           "and": "ו", "etal": "ואחרים", "nd": "ללא תאריך"},
    "en": {"toc": "Table of Contents", "bib": "References", "student": "Submitted by", "id": "ID", "lecturer": "Lecturer",
           "course": "Course", "date": "Date", "kind": {"seminar": "Seminar Paper", "review-article": "Review Article"},
           "toc_hint": "Right-click here and choose 'Update Field' to build the table of contents.",
           "and": "&", "etal": "et al.", "nd": "n.d."},
}


# =========================================================================== XML helpers
def set_rtl_paragraph(p, rtl=True):
    pPr = p._p.get_or_add_pPr()
    for el in pPr.findall(qn("w:bidi")):
        pPr.remove(el)
    bidi = OxmlElement("w:bidi")
    if not rtl:
        # explicit off, because the Normal style is RTL in Hebrew documents
        bidi.set(qn("w:val"), "0")
    pPr.insert(0, bidi)


def set_run_fonts(run, font_en, font_he, size=None, rtl=False):
    rPr = run._r.get_or_add_rPr()
    fonts = rPr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rPr.insert(0, fonts)
    fonts.set(qn("w:ascii"), font_en)
    fonts.set(qn("w:hAnsi"), font_en)
    fonts.set(qn("w:cs"), font_he)
    if size:
        run.font.size = Pt(size)
        szcs = rPr.find(qn("w:szCs"))
        if szcs is None:
            szcs = OxmlElement("w:szCs")
            rPr.append(szcs)
        szcs.set(qn("w:val"), str(int(size * 2)))
    if rtl:
        r = OxmlElement("w:rtl")
        rPr.append(r)
        lang = rPr.find(qn("w:lang"))
        if lang is None:
            lang = OxmlElement("w:lang")
            rPr.append(lang)
        lang.set(qn("w:bidi"), "he-IL")


def add_field(paragraph, instr, placeholder=""):
    r = paragraph.add_run()
    b = OxmlElement("w:fldChar"); b.set(qn("w:fldCharType"), "begin"); r._r.append(b)
    r2 = paragraph.add_run()
    t = OxmlElement("w:instrText"); t.set(qn("xml:space"), "preserve"); t.text = instr; r2._r.append(t)
    r3 = paragraph.add_run()
    s = OxmlElement("w:fldChar"); s.set(qn("w:fldCharType"), "separate"); r3._r.append(s)
    r4 = paragraph.add_run(placeholder)
    r5 = paragraph.add_run()
    e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), "end"); r5._r.append(e)
    return r4


def style_set_fonts(style, font_en, font_he, size, bold=None, rtl=False):
    style.font.name = font_en
    style.font.size = Pt(size)
    if bold is not None:
        style.font.bold = bold
    style.font.color.rgb = RGBColor(0, 0, 0)
    rPr = style.element.get_or_add_rPr()
    fonts = rPr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rPr.insert(0, fonts)
    for k in ("w:ascii", "w:hAnsi", "w:eastAsia"):
        fonts.set(qn(k), font_en)
    fonts.set(qn("w:cs"), font_he)
    for k in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
        if fonts.get(qn(k)) is not None:
            del fonts.attrib[qn(k)]
    szcs = rPr.find(qn("w:szCs"))
    if szcs is None:
        szcs = OxmlElement("w:szCs")
        rPr.append(szcs)
    szcs.set(qn("w:val"), str(int(size * 2)))
    if bold:
        if rPr.find(qn("w:bCs")) is None:
            rPr.append(OxmlElement("w:bCs"))
    if rtl:
        pPr = style.element.get_or_add_pPr()
        if pPr.find(qn("w:bidi")) is None:
            pPr.insert(0, OxmlElement("w:bidi"))


# =========================================================================== APA
def is_heb(s):
    return bool(HEB.search(s or ""))


def initials(given):
    if not given:
        return ""
    given = given.strip()
    if re.fullmatch(r"([A-Z]\.\s?)+([A-Z]\.)?", given) or re.fullmatch(r"([A-Z]\.-?)+", given):
        return given.replace(" ", " ").strip()
    if is_heb(given):
        return " ".join(p[0] + "'" for p in given.split() if p)
    out = []
    for part in given.replace(".", " ").split():
        if "-" in part:
            out.append("-".join(x[0].upper() + "." for x in part.split("-") if x))
        elif part:
            out.append(part[0].upper() + ".")
    return " ".join(out)


def author_list_apa(authors):
    names = []
    for a in authors:
        fam = (a.get("family") or "").strip()
        ini = initials(a.get("given") or "")
        if a.get("literal"):
            names.append(a["literal"])
        elif fam:
            names.append(f"{fam}, {ini}" if ini else fam)
    if not names:
        return ""
    heb = any(is_heb(n) for n in names)
    amp = "ו" if heb else "& "
    if len(names) == 1:
        return names[0]
    if len(names) <= 20:
        return ", ".join(names[:-1]) + (", " if not heb else " ") + amp + names[-1]
    return ", ".join(names[:19]) + ", . . . " + names[-1]


def pages_str(pages):
    return (pages or "").replace("--", "–").replace("-", "–")


def doi_url(c):
    if c.get("doi"):
        d = c["doi"].strip()
        d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", d, flags=re.I)
        return f"https://doi.org/{d}"
    return (c.get("url") or "").strip()


def end_dot(s):
    s = (s or "").strip()
    return s if not s or s[-1] in ".?!" else s + "."


def apa_reference(c, nd):
    """Return a list of (text, italic) segments."""
    seg = []
    authors = author_list_apa(c.get("authors") or [])
    year = c.get("year") or nd
    year = f"{year}{c.get('year_suffix', '')}"
    title = (c.get("title") or "").strip()
    typ = (c.get("type") or "article").lower()
    cont = (c.get("container") or "").strip()
    link = doi_url(c)
    head = f"{authors} ({year}). " if authors else ""
    italic_title = typ in ("book", "report", "thesis", "dissertation", "preprint", "web", "dataset", "software")

    if not authors:
        # title moves to author position
        if italic_title:
            seg += [(end_dot(title), True), (f" ({year}). ", False)]
        else:
            seg += [(end_dot(title), False), (f" ({year}). ", False)]
        title_done = True
    else:
        seg.append((head, False))
        title_done = False

    if typ == "article":
        if not title_done:
            seg.append((end_dot(title) + " ", False))
        if cont:
            seg.append((cont, True))
            vol, iss = c.get("volume"), c.get("issue")
            if vol:
                seg += [(", ", False), (str(vol), True)]
            if iss:
                seg.append((f"({iss})", False))
            if c.get("pages"):
                seg.append((f", {pages_str(c['pages'])}", False))
            seg.append((". ", False))
    elif typ in ("chapter", "conference", "proceedings"):
        if not title_done:
            seg.append((end_dot(title) + " ", False))
        eds = c.get("editors") or []
        book = (c.get("book_title") or cont).strip()
        seg.append(("In ", False) if not is_heb(book) else ("בתוך ", False))
        if eds:
            ed_names = [f"{initials(e.get('given', ''))} {e.get('family', '')}".strip() for e in eds]
            ed_lbl = " (Eds.), " if len(eds) > 1 else " (Ed.), "
            if is_heb(book):
                ed_lbl = " (עורכים), " if len(eds) > 1 else " (עורך), "
            seg.append((", ".join(ed_names) + ed_lbl, False))
        if book:
            seg.append((book, True))
        if c.get("pages"):
            seg.append((f" (pp. {pages_str(c['pages'])})" if not is_heb(book) else f" (עמ' {pages_str(c['pages'])})", False))
        seg.append((". ", False))
        if c.get("publisher"):
            seg.append((end_dot(c["publisher"]) + " ", False))
    elif typ in ("thesis", "dissertation"):
        if not title_done:
            seg.append((title, True))
        kind = c.get("thesis_kind") or "Doctoral dissertation"
        inst = c.get("institution") or c.get("publisher") or ""
        seg.append((f" [{kind}{', ' + inst if inst else ''}]. ", False))
    else:  # book, report, preprint, web, other
        if not title_done:
            seg.append((title, True))
        extra = []
        if c.get("edition"):
            extra.append(f"{c['edition']} ed.")
        if c.get("report_number"):
            extra.append(str(c["report_number"]))
        if extra:
            seg.append((f" ({'; '.join(extra)})", False))
        if typ == "preprint":
            seg.append((" [Preprint]", False))
        seg.append((". ", False))
        pub = c.get("publisher") or c.get("institution") or cont
        if pub:
            seg.append((end_dot(pub) + " ", False))
    if link:
        seg.append((link, False))
    # tidy spacing
    out, prev = [], None
    for t, it in seg:
        if not t:
            continue
        out.append((re.sub(r"\s{2,}", " ", t), it))
    if out:
        out[-1] = (out[-1][0].rstrip(), out[-1][1])
    return out


def sort_key(c):
    a = (c.get("authors") or [{}])[0]
    fam = a.get("family") or a.get("literal") or c.get("title") or ""
    return (0 if is_heb(fam) else 1, fam.lower(), str(c.get("year") or ""), c.get("year_suffix", ""))


def intext_name(c, lab):
    authors = c.get("authors") or []
    fams = [(a.get("family") or a.get("literal") or "").strip() for a in authors]
    fams = [f for f in fams if f]
    if not fams:
        t = c.get("title") or "Anonymous"
        return f"\u201c{' '.join(t.split()[:4])}\u201d" if not is_heb(t) else f"\"{' '.join(t.split()[:4])}\""
    heb = is_heb(fams[0])
    if len(fams) == 1:
        return fams[0]
    if len(fams) == 2:
        return f"{fams[0]} ו{fams[1]}" if heb else f"{fams[0]} & {fams[1]}"
    return f"{fams[0]} {'ואחרים' if heb else 'et al.'}"


def intext_year(c, lab):
    return f"{c.get('year') or lab['nd']}{c.get('year_suffix', '')}"


def assign_suffixes(cites):
    groups = {}
    for i, c in cites.items():
        groups.setdefault((intext_name(c, LABELS["en"]), str(c.get("year"))), []).append(i)
    for key, ids in groups.items():
        if len(ids) > 1 and key[1] not in ("None", ""):
            ids.sort(key=lambda i: (cites[i].get("title") or "").lower())
            for n, i in enumerate(ids):
                cites[i]["year_suffix"] = "abcdefghijklmnopqrstuvwxyz"[n]


# =========================================================================== inline text
def resolve_citations(text, cites, lab, used, unknown):
    def repl(m):
        narrative, body = m.group(1), m.group(2)
        items = []
        for part in body.split(";"):
            part = part.strip()
            if not part:
                continue
            pid, _, loc = part.partition(",")
            pid = pid.strip().lstrip("@")
            loc = loc.strip()
            if pid not in cites:
                return None
            items.append((pid, loc))
        if not items:
            return None
        for pid, _ in items:
            used.add(pid)
        if narrative:
            outs = []
            for pid, loc in items:
                c = cites[pid]
                outs.append(f"{intext_name(c, lab)} ({intext_year(c, lab)}{', ' + loc if loc else ''})")
            return ", ".join(outs)
        items.sort(key=lambda x: sort_key(cites[x[0]]))
        inner = "; ".join(f"{intext_name(cites[p], lab)}, {intext_year(cites[p], lab)}{', ' + l if l else ''}" for p, l in items)
        return f"({inner})"

    out, pos = [], 0
    for m in CIT.finditer(text):
        r = repl(m)
        if r is None:
            tok = m.group(2).split(";")[0].split(",")[0].strip().lstrip("@")
            if re.match(r"^[A-Za-z][A-Za-z0-9\-]*\d{2,4}[a-z]?$", tok):
                unknown.add(tok)
                out.append((text[pos:m.start()], None))
                out.append((m.group(0), "unknown"))
                pos = m.end()
            continue
        out.append((text[pos:m.start()], None))
        out.append((r, "cite"))
        pos = m.end()
    out.append((text[pos:], None))
    # merge into one string, keeping unknown markers as separate spans
    spans = []
    for t, flag in out:
        if not t:
            continue
        if spans and spans[-1][1] == flag and flag is None:
            spans[-1] = (spans[-1][0] + t, flag)
        else:
            spans.append((t, flag))
    return spans


def inline_runs(text):
    """Split **bold** and *italic* markers into (text, bold, italic)."""
    out = []
    for m in re.finditer(r"\*\*(.+?)\*\*|\*(?!\s)(.+?)(?<!\s)\*|([^*]+|\*)", text):
        if m.group(1) is not None:
            out.append((m.group(1), True, False))
        elif m.group(2) is not None:
            out.append((m.group(2), False, True))
        else:
            out.append((m.group(3), False, False))
    return out


def direction_chunks(text):
    """Split text into chunks that are Hebrew (rtl) or Latin (ltr); neutrals join the previous chunk."""
    chunks, cur, cur_rtl = [], "", None
    for ch in text:
        if HEB.match(ch):
            d = True
        elif LATIN.match(ch) or ch.isdigit():
            d = False
        else:
            d = None
        if d is None or d == cur_rtl or cur_rtl is None:
            cur += ch
            if cur_rtl is None and d is not None:
                cur_rtl = d
        else:
            chunks.append((cur, cur_rtl))
            cur, cur_rtl = ch, d
    if cur:
        chunks.append((cur, cur_rtl))
    return chunks


class Writer:
    def __init__(self, doc, cfg, cites, lab):
        self.doc, self.cfg, self.cites, self.lab = doc, cfg, cites, lab
        self.used, self.unknown = set(), set()
        self.rtl_doc = cfg["lang"] == "he"

    def add_text(self, p, text, bold=False, italic=False, size=None, cite=True):
        spans = resolve_citations(text, self.cites, self.lab, self.used, self.unknown) if cite else [(text, None)]
        for span, flag in spans:
            if flag in ("cite", "unknown"):
                # keep a whole citation in one direction so its parentheses stay together
                strong = re.search(r"[A-Za-z֐-׿]", span)
                rtl = bool(strong and HEB.match(strong.group(0)))
                # no line breaks inside one source's citation (breaks are allowed after ";")
                span = "; ".join(part.replace(" ", " ") for part in span.split("; "))
                run = p.add_run(span)
                run.bold, run.italic = bold, italic
                set_run_fonts(run, self.cfg["font_en"], self.cfg["font_he"], size or self.cfg["size"], rtl=rtl)
                if flag == "unknown":
                    rPr = run._r.get_or_add_rPr()
                    h = OxmlElement("w:highlight"); h.set(qn("w:val"), "yellow"); rPr.append(h)
                continue
            for t, b, it in inline_runs(span):
                for chunk, rtl in direction_chunks(t):
                    run = p.add_run(chunk)
                    run.bold = bold or b
                    run.italic = italic or it
                    set_run_fonts(run, self.cfg["font_en"], self.cfg["font_he"], size or self.cfg["size"],
                                  rtl=bool(rtl) if rtl is not None else self.rtl_doc)
                    if flag == "unknown":
                        rPr = run._r.get_or_add_rPr()
                        h = OxmlElement("w:highlight"); h.set(qn("w:val"), "yellow"); rPr.append(h)

    def para(self, text="", style=None, align=None, rtl=None, **kw):
        p = self.doc.add_paragraph(style=style)
        set_rtl_paragraph(p, self.rtl_doc if rtl is None else rtl)
        if align is not None:
            p.alignment = align
        if text:
            self.add_text(p, text, **kw)
        return p


# =========================================================================== markdown blocks
def parse_blocks(md):
    lines = md.replace("\r\n", "\n").split("\n")
    blocks, buf, i = [], [], 0

    def flush():
        if buf:
            blocks.append(("p", " ".join(s.strip() for s in buf)))
            buf.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            flush(); i += 1; continue
        m = re.match(r"^(#{1,3})\s+(.*)$", s)
        if m:
            flush(); blocks.append((f"h{len(m.group(1))}", m.group(2).strip())); i += 1; continue
        if s.startswith("$$"):
            flush()
            eq = s[2:]
            if eq.endswith("$$") and len(s) > 4:
                blocks.append(("eq", eq[:-2].strip())); i += 1; continue
            parts = [eq]
            i += 1
            while i < len(lines) and "$$" not in lines[i]:
                parts.append(lines[i].strip()); i += 1
            if i < len(lines):
                parts.append(lines[i].strip().replace("$$", "")); i += 1
            blocks.append(("eq", " ".join(p for p in parts if p))); continue
        if s.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = lines[i].strip().strip("|")
                if not re.fullmatch(r"[\s:\-|]+", row):
                    rows.append([c.strip() for c in row.split("|")])
                i += 1
            blocks.append(("table", rows)); continue
        m = re.match(r"^([-*•])\s+(.*)$", s)
        if m:
            flush(); blocks.append(("bullet", m.group(2))); i += 1; continue
        m = re.match(r"^(\d+)[.)]\s+(.*)$", s)
        if m:
            flush(); blocks.append(("number", m.group(2))); i += 1; continue
        if s.startswith(">"):
            flush(); blocks.append(("quote", s.lstrip("> ").strip())); i += 1; continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            flush(); i += 1; continue
        if s.startswith("<!--"):
            flush()
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1; continue
        buf.append(line); i += 1
    flush()
    return blocks


# =========================================================================== document
def setup_document(cfg):
    doc = Document()
    sec = doc.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Cm(cfg["margins"]))
    rtl = cfg["lang"] == "he"
    if rtl:
        sectPr = sec._sectPr
        bidi = OxmlElement("w:bidi"); sectPr.append(bidi)
    normal = doc.styles["Normal"]
    style_set_fonts(normal, cfg["font_en"], cfg["font_he"], cfg["size"], rtl=rtl)
    normal.paragraph_format.line_spacing = cfg["spacing"]
    normal.paragraph_format.space_after = Pt(6)
    for name, size in (("Heading 1", cfg["size"] + 4), ("Heading 2", cfg["size"] + 2), ("Heading 3", cfg["size"] + 1),
                       ("Title", cfg["size"] + 10)):
        st = doc.styles[name]
        style_set_fonts(st, cfg["font_en"], cfg["font_he"], size, bold=True, rtl=rtl)
        st.paragraph_format.space_before = Pt(12)
        st.paragraph_format.space_after = Pt(6)
        st.paragraph_format.keep_with_next = True
    for name in ("List Bullet", "List Number"):
        style_set_fonts(doc.styles[name], cfg["font_en"], cfg["font_he"], cfg["size"], rtl=rtl)
    # page number in footer
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_field(fp, "PAGE", "1")
    # ask Word to refresh fields (TOC) when the file opens
    upd = OxmlElement("w:updateFields"); upd.set(qn("w:val"), "true")
    doc.settings.element.append(upd)
    return doc


def page_break(doc):
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def add_cover(w, proj, cfg, lab, profile):
    cover = proj.get("cover") or {}
    C = WD_ALIGN_PARAGRAPH.CENTER
    for _ in range(3):
        w.para()
    if cover.get("institution"):
        w.para(cover["institution"], align=C, size=cfg["size"] + 2, cite=False)
    if cover.get("department"):
        w.para(cover["department"], align=C, cite=False)
    w.para()
    w.para(lab["kind"].get(profile, ""), align=C, size=cfg["size"] + 2, cite=False)
    w.para(proj.get("title") or "", align=C, bold=True, size=cfg["size"] + 10, cite=False)
    for _ in range(4):
        w.para()
    rows = [("course", proj.get("course")), ("student", cover.get("student")), ("id", cover.get("student_id")),
            ("lecturer", cover.get("lecturer")), ("date", cfg["date"])]
    for key, val in rows:
        if val:
            w.para(f"{lab[key]}: {val}", align=C, cite=False)
    page_break(w.doc)


def add_toc(w, lab):
    w.para(lab["toc"], style="Heading 1", cite=False)
    p = w.para()
    add_field(p, 'TOC \\o "1-3" \\h \\z \\u', lab["toc_hint"])
    page_break(w.doc)


def add_table(w, rows, cfg):
    if not rows:
        return
    ncols = max(len(r) for r in rows)
    t = w.doc.add_table(rows=len(rows), cols=ncols)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    if w.rtl_doc:
        tblPr = t._tbl.tblPr
        bv = OxmlElement("w:bidiVisual"); tblPr.append(bv)
    for r, row in enumerate(rows):
        for c in range(ncols):
            cell = t.cell(r, c)
            p = cell.paragraphs[0]
            set_rtl_paragraph(p, w.rtl_doc)
            p.paragraph_format.line_spacing = 1.0
            p.paragraph_format.space_after = Pt(0)
            w.add_text(p, row[c] if c < len(row) else "", bold=(r == 0), size=cfg["size"] - 2)
    # repeat header row
    trPr = t.rows[0]._tr.get_or_add_trPr()
    h = OxmlElement("w:tblHeader"); h.set(qn("w:val"), "true"); trPr.append(h)
    w.para()


def build(args):
    out = Path(args.out)
    proj = yaml.safe_load((out / "project.yaml").read_text(encoding="utf-8")) or {}
    lang = proj.get("language") or "he"
    lab = LABELS["he" if lang == "he" else "en"]
    fmt = proj.get("format") or {}
    profile = proj.get("profile") or "seminar"
    today = datetime.date.today()
    cfg = {
        "lang": lang,
        "font_he": fmt.get("font_he") or "David",
        "font_en": fmt.get("font_en") or ("David" if lang == "he" else "Times New Roman"),
        "size": float(fmt.get("font_size") or 12),
        "spacing": float(fmt.get("line_spacing") or 1.5),
        "margins": float(fmt.get("margins_cm") or 2.5),
        "date": (proj.get("cover") or {}).get("date") or (today.strftime("%d.%m.%Y") if lang == "he" else today.strftime("%B %d, %Y")),
    }

    cites, warnings = {}, []
    excluded = set(proj.get("excluded_articles") or [])
    for p in sorted((out / "03_summaries").glob("*.json")):
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            warnings.append(f"{p.name}: invalid JSON ({e})")
            continue
        sid = s.get("id") or p.stem
        if sid in excluded:
            continue
        c = dict(s.get("citation") or {})
        if not c.get("title"):
            warnings.append(f"{sid}: citation has no title")
        cites[sid] = c
    assign_suffixes(cites)

    doc = setup_document(cfg)
    w = Writer(doc, cfg, cites, lab)
    if profile == "review-article" or proj.get("cover_page") is False:
        w.para(proj.get("title") or "", style="Title", align=WD_ALIGN_PARAGRAPH.CENTER, cite=False)
        cover = proj.get("cover") or {}
        line = " · ".join(x for x in (cover.get("student"), cover.get("institution"), cfg["date"]) if x)
        if line:
            w.para(line, align=WD_ALIGN_PARAGRAPH.CENTER, cite=False)
    else:
        add_cover(w, proj, cfg, lab, profile)
        add_toc(w, lab)

    md = Path(args.draft).read_text(encoding="utf-8")
    blocks = parse_blocks(md)
    first_h1 = True
    equations = 0
    J = WD_ALIGN_PARAGRAPH.JUSTIFY
    for kind, val in blocks:
        if kind == "h1":
            if not first_h1:
                page_break(doc)
            first_h1 = False
            w.para(val, style="Heading 1")
        elif kind in ("h2", "h3"):
            w.para(val, style="Heading 2" if kind == "h2" else "Heading 3")
        elif kind == "p":
            w.para(val, align=J)
        elif kind == "bullet":
            w.para(val, style="List Bullet")
        elif kind == "number":
            w.para(val, style="List Number")
        elif kind == "quote":
            p = w.para(val, italic=True)
            p.paragraph_format.left_indent = Cm(1)
            p.paragraph_format.right_indent = Cm(1)
        elif kind == "eq":
            equations += 1
            p = w.para(rtl=False, align=WD_ALIGN_PARAGRAPH.CENTER)
            run = p.add_run(val)
            set_run_fonts(run, "Cambria Math", "Cambria Math", cfg["size"])
        elif kind == "table":
            add_table(w, val, cfg)

    # bibliography: only works cited
    page_break(doc)
    w.para(lab["bib"], style="Heading 1", cite=False)
    for sid in sorted(w.used, key=lambda i: sort_key(cites[i])):
        c = cites[sid]
        segs = apa_reference(c, lab["nd"])
        heb_entry = is_heb("".join(t for t, _ in segs[:2]))
        p = doc.add_paragraph()
        set_rtl_paragraph(p, heb_entry)
        p.paragraph_format.left_indent = Cm(1.27)
        p.paragraph_format.first_line_indent = Cm(-1.27)
        if not heb_entry:
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for t, it in segs:
            for chunk, rtl in direction_chunks(t):
                run = p.add_run(chunk)
                run.italic = it
                set_run_fonts(run, cfg["font_en"], cfg["font_he"], cfg["size"], rtl=bool(rtl) if rtl is not None else heb_entry)

    target = Path(args.docx) if args.docx else out / "final" / (re.sub(r'[\\/:*?"<>|]+', "", proj.get("title") or "paper").strip()[:80] + ".docx")
    target.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(target))

    body_words = len(re.findall(r"[\w\u0590-\u05FF]+", CIT.sub("", md)))
    for sid in sorted(set(cites) - w.used):
        warnings.append(f"{sid}: in the folder but never cited")
    for c_id, c in cites.items():
        if c_id in w.used and not (c.get("authors") and c.get("year")):
            warnings.append(f"{c_id}: reference is missing authors or year")
    print(json.dumps({
        "docx": str(target),
        "body_words": body_words,
        "cited": sorted(w.used),
        "unknown_ids_highlighted": sorted(w.unknown),
        "equations_as_text": equations,
        "warnings": warnings,
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--draft", required=True)
    ap.add_argument("--docx")
    return build(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
