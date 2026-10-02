"""
Checks the synopsis content against the 'General instructions while preparing
the Programme of Research work' (KVASU). Returns a list of
(level, section, message) where level is 'error' or 'warning'.
"""
from __future__ import annotations

import re

try:
    from .references import parse_authors
except ImportError:  # files placed flat in one folder
    from references import parse_authors

NUM_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


def _text_blocks(d):
    tech = []
    for b in d.get("technical", []):
        if isinstance(b, str):
            tech.append(b)
        elif b.get("type") != "table":
            tech.append(b.get("text", ""))
    return {
        "6. Practical / Scientific utility": d.get("utility", ""),
        "7. Important publications": d.get("publications", ""),
        "8. Technical programme": "\n\n".join(tech),
    }


def _plain(s):
    return re.sub(r"</?(i|b|sup|sub)>", "", s or "")


def find_citations(text: str) -> list[tuple[str, str]]:
    """Return (surname, year) pairs for author-year citations in text."""
    text = _plain(text)
    out = []
    pat = re.compile(
        r"([A-Z][A-Za-zÀ-ÿ'`’\-]+)(?:\s+(?:et al\.?|and|&)\s*(?:[A-Z][A-Za-zÀ-ÿ'`’\-]+)?)?"
        r",?\s*\(?((?:19|20)\d{2})[a-z]?\)?")
    for m in pat.finditer(text):
        surname, year = m.group(1), m.group(2)
        if surname in {"In", "The", "Act", "Amendment", "Semester", "During", "SPSS"}:
            continue
        out.append((surname, year))
    return out


def validate(d: dict) -> list[tuple[str, str, str]]:
    issues = []
    E = lambda s, m: issues.append(("error", s, m))
    W = lambda s, m: issues.append(("warning", s, m))

    # ---- 1. Title
    t = _plain(d.get("title", "")).strip()
    if not t:
        E("1. Title", "Title of thesis is empty")
    else:
        if t.endswith("."):
            E("1. Title", "Remove the full stop at the end of the title")
        if re.match(r"(?i)^(studies|a study|study)\s+on", t):
            E("1. Title", "Avoid 'Studies on…' type titles")
        if re.search(r"\([^)]*\)", t) and "<i>" not in d.get("title", ""):
            W("1. Title", "Avoid brackets in title except for biological names")

    # ---- 3/4. names & discipline
    if not d.get("student_name", "").startswith("Dr"):
        W("3. Student", "Student name normally starts with 'Dr.'")
    if not re.fullmatch(r"\d{2}-[A-Z]{3}-\d{1,3}", d.get("admission_no", "").strip()):
        W("3. Admission No.", "Admission number format looks unusual (e.g. 24-MVM-11)")

    # ---- 5. Objectives
    objs = d.get("objectives", [])
    if not objs:
        E("5. Objectives", "Add at least one objective")
    if len(objs) > 4:
        W("5. Objectives", f"{len(objs)} objectives given; may be limited to four")
    for i, o in enumerate(objs, 1):
        if re.match(r"(?i)^to\s", o.strip()):
            E("5. Objectives", f"Objective {i}: do not begin with 'To' (e.g. 'Assess…')")
        if o.strip().endswith("."):
            E("5. Objectives", f"Objective {i}: no full stop at the end")

    # ---- 6. Utility
    up = [p for p in re.split(r"\n\s*\n", d.get("utility", "")) if p.strip()]
    if len(up) > 2:
        W("6. Utility", "Limit practical / scientific utility to one or two paragraphs")
    if find_citations(d.get("utility", "")):
        W("6. Utility", "Avoid using references in practical / scientific utility")

    # ---- 7. Publications: count + chronology
    pubs = [p for p in re.split(r"\n\s*\n", d.get("publications", "")) if p.strip()]
    n_min, n_max = (8, 10) if d.get("degree", "MASTERS").upper().startswith("MAST") else (10, 12)
    if not (n_min <= len(pubs) <= n_max):
        W("7. Publications", f"{len(pubs)} publication paragraphs; use {n_min}-{n_max} "
                             f"for {'MVSc' if n_min == 8 else 'PhD'}")
    prev = None
    for i, p in enumerate(pubs, 1):
        c = find_citations(p)
        if not c:
            W("7. Publications", f"Paragraph {i} has no author-year citation")
            continue
        key = (int(c[0][1]), c[0][0].lower())
        if prev and key < prev:
            E("7. Publications", f"Paragraph {i} ({c[0][0]}, {c[0][1]}) breaks chronological "
                                 f"order (same year → alphabetical by surname)")
        prev = key

    # ---- number style in text
    for sec, txt in _text_blocks(d).items():
        plain = _plain(txt)
        for m in re.finditer(r"(?:^|(?<=[.!?]\s))(\d+|[A-Z]{2,}\b)", plain):
            E(sec, f"Sentence begins with numeral/abbreviation: '{plain[m.start():m.start()+25]}…'")
        for m in re.finditer(r"(?<![\d.,:/\-±])\b([1-9])\b(?![\d.,:/%±\-])\s+(?!h\b|min\b|s\b|°|mm|cm|kg|g\b|ml|mL|days?\b)([a-z]{3,})", plain):
            W(sec, f"Write numbers below ten in words: '{m.group(0)}' → "
                   f"'{NUM_WORDS[int(m.group(1))]} {m.group(2)}'")
        for m in re.finditer(r"\b\d{1,3}(?:,\d{3})+\b", plain):
            E(sec, f"Do not use commas in numbers: '{m.group(0)}'")
        for m in re.finditer(r"\d\s*%", plain):
            ctx = plain[max(0, m.start() - 30):m.end()]
            if "(" not in ctx.split(")")[-1]:
                W(sec, f"Use 'per cent' in text (% only within brackets/tables): '…{ctx}'")
        for m in re.finditer(r"\b\d+\s*(hours?|hrs?|minutes?|mins|seconds?|secs)\b", plain):
            E(sec, f"Abbreviate units with numbers (h, min, s): '{m.group(0)}'")
        if re.search(r"(?i)^\s*(about|a total of|an amount of)\b", plain, flags=re.M):
            W(sec, "Avoid beginning sentences with 'about / a total of / an amount of'")
        for w in ["post infection", "post partum", "pre treatment", "day old", "petri dish", "Petri dish"]:
            if w in plain.lower() if w.islower() else w in plain:
                W(sec, f"Hyphenate: '{w}' → '{w.replace(' ', '-').replace('petri','Petri')}'")
        if re.search(r"\bPCV\b", plain):
            W(sec, "Use latest term VPRC instead of PCV")

    # ---- 9. Observations
    for i, g in enumerate(d.get("observations", []), 1):
        txts = [g] if isinstance(g, str) else [g.get("text", "")] + [
            x if isinstance(x, str) else x.get("text", "") for x in g.get("items", [])]
        for t in txts:
            if t.strip().endswith("."):
                E("9. Observations", f"No full stop at end of line: '{t}'")

    # ---- 12. Finance
    for it in d.get("finance", []):
        if re.match(r"(?i)\s*cost of", it.get("item", "")):
            E("12. Financial estimate", f"Avoid 'cost of': '{it['item']}'")
        if re.search(r"[,₹]", str(it.get("amount", ""))):
            E("12. Financial estimate", "Express amounts as 'Rs. 20000' (no commas/symbols)")

    # ---- Date
    if not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", d.get("date", "").strip()):
        E("Place/Date", "Date must be in DD.MM.YYYY format (e.g. 23.11.2022)")

    # ---- Time frame
    tf = d.get("timeframe", [])
    maxsem = 4 if d.get("degree", "MASTERS").upper().startswith("MAST") else 6
    if len(tf) > maxsem:
        E("14. Time frame", f"More than {maxsem} semesters given")

    # ---- References cross-check
    refs = d.get("references", [])
    ref_keys = set()
    for r in refs:
        a = parse_authors(r.get("authors", ""))
        if a:
            ref_keys.add((a[0][0].lower(), str(r.get("year", ""))))
        missing = [f for f in ("authors", "year", "title") if not r.get(f)]
        if missing:
            E("13. References", f"Reference '{r.get('title','')[:40] or r.get('doi','?')}' "
                                f"is missing: {', '.join(missing)}")
        if r.get("type", "article") == "article" and not (r.get("journal") or r.get("journal_abbr")):
            E("13. References", f"Journal missing for '{r.get('title','')[:40]}'")
        if (d.get("ref_style", "").startswith("KVASU") and r.get("type", "article") == "article"
                and not r.get("journal_abbr")):
            W("13. References", f"Abbreviated journal name missing for '{r.get('title','')[:40]}'")

    cited = set()
    for sec, txt in _text_blocks(d).items():
        for s, y in find_citations(txt):
            cited.add((s.lower(), y))
    org_names = {k for k in ref_keys if " " in k[0]}
    for s, y in sorted(cited):
        if (s, y) not in ref_keys and not any(s in k[0].split() and k[1] == y for k in org_names):
            E("Citations", f"'{s.title()}, {y}' is cited in text but not in References")
    for s, y in sorted(ref_keys):
        words = s.split()
        if not any(c[0] in words and c[1] == y for c in cited):
            W("Citations", f"'{s.title()}, {y}' is in References but not cited in text")

    return issues
