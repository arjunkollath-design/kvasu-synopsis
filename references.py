"""
Reference handling: fetch from DOI (Crossref), parse BibTeX, and format
in KVASU thesis style or APA 7th edition.

A reference is a plain dict:
{
  "type": "article" | "book" | "chapter" | "standard" | "web",
  "authors": "Bauer, A.W.; Kirby, W.M.; Sherris, J.C.; Turck, M.",   # family, initials ; separated
  "year": "1966",
  "title": "Antibiotic sensitivity testing by a standardized single disk method",
  "journal": "American Journal of Clinical Pathology",
  "journal_abbr": "Am. J. Clin. Pathol.",
  "volume": "45", "issue": "4", "pages": "493-496",
  "publisher": "", "place": "", "edition": "", "editors": "", "book_title": "",
  "doi": "", "url": ""
}

Formatting functions return a list of "runs": (text, {"italic":bool,"bold":bool})
so the Word generator can apply italics / bold exactly.
"""
from __future__ import annotations

import html
import re
import unicodedata

import requests

REF_FIELDS = [
    "type", "authors", "year", "title", "journal", "journal_abbr", "volume",
    "issue", "pages", "publisher", "place", "edition", "editors",
    "book_title", "doi", "url",
]


def empty_ref() -> dict:
    r = {k: "" for k in REF_FIELDS}
    r["type"] = "article"
    return r


# --------------------------------------------------------------------------
# Author helpers
# --------------------------------------------------------------------------
def make_initials(given: str) -> str:
    """'Anthony William' -> 'A.W.' ; 'J.-C.' -> 'J.C.'"""
    given = (given or "").replace("-", " ").replace(".", " ")
    parts = [p for p in given.split() if p]
    return "".join(p[0].upper() + "." for p in parts)


def parse_authors(authors: str) -> list[tuple[str, str]]:
    """'Bauer, A.W.; Kirby, W.M.' -> [('Bauer','A.W.'), ('Kirby','W.M.')]
    Organisation names (no comma) are kept as a single family name."""
    out = []
    for a in (authors or "").split(";"):
        a = a.strip()
        if not a:
            continue
        if "," in a:
            fam, given = a.split(",", 1)
            given = given.strip()
            # normalise initials: 'A. W.' / 'Anthony W' -> 'A.W.'
            if not re.fullmatch(r"([A-Z]\.)+", given.replace(" ", "")):
                given = make_initials(given)
            else:
                given = given.replace(" ", "")
            out.append((fam.strip(), given))
        else:
            out.append((a, ""))
    return out


def first_author_surname(ref: dict) -> str:
    a = parse_authors(ref.get("authors", ""))
    return a[0][0] if a else ""


def in_text_citation(ref: dict) -> str:
    """Author-year citation key, e.g. 'Delezie et al., 2007'."""
    a = parse_authors(ref.get("authors", ""))
    y = ref.get("year", "")
    if not a:
        return y
    if len(a) == 1:
        return f"{a[0][0]}, {y}"
    if len(a) == 2:
        return f"{a[0][0]} and {a[1][0]}, {y}"
    return f"{a[0][0]} et al., {y}"


def sort_key(ref: dict):
    """KVASU / APA ordering: first author surname, then single-author
    before two-author before multi-author, then year."""
    a = parse_authors(ref.get("authors", ""))
    surname = strip_accents(a[0][0].lower()) if a else "zzz"
    n = len(a)
    group = 0 if n == 1 else (1 if n == 2 else 2)
    second = strip_accents(a[1][0].lower()) if (n == 2) else ""
    return (surname, group, second, ref.get("year", ""))


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def clean_pages(p: str) -> str:
    return (p or "").replace("--", "-").replace("–", "-").replace("—", "-").strip()


def ensure_period(s: str) -> str:
    s = (s or "").strip()
    return s if not s or s[-1] in ".?!" else s + "."


# --------------------------------------------------------------------------
# KVASU thesis style  (as in the example on Acad Form No. 19)
# Bauer, A.W., Kirby, W.M., Sherris, J.C. and Turck, M. 1966. Title.
#     Am. J. Clin. Pathol. 45: 493-496.
# --------------------------------------------------------------------------
def _kvasu_authors(ref) -> str:
    a = [f"{f}, {g}" if g else f for f, g in parse_authors(ref.get("authors", ""))]
    if not a:
        return ""
    if len(a) == 1:
        return a[0]
    return ", ".join(a[:-1]) + " and " + a[-1]


def format_kvasu(ref: dict) -> list[tuple[str, dict]]:
    N, I, B = {}, {"italic": True}, {"bold": True}
    t = ref.get("type", "article") or "article"
    runs = [(f"{_kvasu_authors(ref)} {ref.get('year','')}. ", N)]
    title = ensure_period(ref.get("title", ""))
    pages = clean_pages(ref.get("pages", ""))

    if t == "article":
        runs.append((title + " ", N))
        jr = ref.get("journal_abbr") or ref.get("journal", "")
        runs.append((jr, I))
        if ref.get("volume"):
            runs.append((" ", N))
            runs.append((ref["volume"], B))
        if pages:
            runs.append((f": {pages}.", N))
        else:
            runs.append((".", N))
    elif t == "book":
        runs.append((title, I))
        if ref.get("edition"):
            runs.append((f" ({ref['edition']} Ed.).", N))
        tail = ", ".join(x for x in [ref.get("publisher", ""), ref.get("place", "")] if x)
        if tail:
            runs.append((" " + tail, N))
        if pages:
            runs.append((f", {pages}p.", N))
        else:
            runs.append((".", N))
    elif t == "chapter":
        runs.append((title + " ", N))
        eds = ref.get("editors", "")
        if eds:
            runs.append((f"In: {eds} (eds.), ", N))
        runs.append((ensure_period(ref.get("book_title", "")), I))
        tail = ", ".join(x for x in [ref.get("publisher", ""), ref.get("place", "")] if x)
        if tail:
            runs.append((" " + tail, N))
        runs.append((f", pp. {pages}." if pages else ".", N))
    else:  # standard / web
        runs.append((title, N))
        if ref.get("publisher"):
            runs.append((" " + ensure_period(ref["publisher"]), N))
        link = ref.get("url") or (f"https://doi.org/{ref['doi']}" if ref.get("doi") else "")
        if link:
            runs.append((f" Available: {link}", N))
    return _merge(runs)


# --------------------------------------------------------------------------
# APA 7th edition
# --------------------------------------------------------------------------
def _apa_authors(ref) -> str:
    def fmt(f, g):
        if not g:
            return f
        g = " ".join(x + "." for x in g.strip(".").split("."))  # A.W. -> A. W.
        return f"{f}, {g}"
    a = [fmt(f, g) for f, g in parse_authors(ref.get("authors", ""))]
    if not a:
        return ""
    if len(a) == 1:
        return a[0]
    if len(a) <= 20:
        return ", ".join(a[:-1]) + ", & " + a[-1]
    return ", ".join(a[:19]) + ", . . . " + a[-1]


def format_apa(ref: dict) -> list[tuple[str, dict]]:
    N, I = {}, {"italic": True}
    t = ref.get("type", "article") or "article"
    auth = _apa_authors(ref)
    runs = [(f"{ensure_period(auth) if auth else ''} ({ref.get('year','n.d.')}). ", N)]
    pages = clean_pages(ref.get("pages", ""))
    link = f"https://doi.org/{ref['doi']}" if ref.get("doi") else ref.get("url", "")

    if t == "article":
        runs.append((ensure_period(ref.get("title", "")) + " ", N))
        runs.append((ref.get("journal", ""), I))
        if ref.get("volume"):
            runs.append((", ", N))
            runs.append((ref["volume"], I))
        if ref.get("issue"):
            runs.append((f"({ref['issue']})", N))
        if pages:
            runs.append((f", {pages}", N))
        runs.append((".", N))
    elif t == "book":
        title = ref.get("title", "")
        runs.append((title, I))
        if ref.get("edition"):
            runs.append((f" ({ref['edition']} ed.)", N))
        runs.append((". ", N))
        if ref.get("publisher"):
            runs.append((ensure_period(ref["publisher"]), N))
    elif t == "chapter":
        runs.append((ensure_period(ref.get("title", "")) + " ", N))
        if ref.get("editors"):
            runs.append((f"In {ref['editors']} (Eds.), ", N))
        runs.append((ref.get("book_title", ""), I))
        runs.append((f" (pp. {pages}). " if pages else ". ", N))
        if ref.get("publisher"):
            runs.append((ensure_period(ref["publisher"]), N))
    else:
        runs.append((ref.get("title", ""), I))
        runs.append((". ", N))
        if ref.get("publisher"):
            runs.append((ensure_period(ref["publisher"]), N))
    if link:
        runs.append((" " + link, N))
    return _merge(runs)


STYLES = {"KVASU thesis style": format_kvasu, "APA 7th edition": format_apa}


def format_reference(ref: dict, style: str):
    return STYLES.get(style, format_kvasu)(ref)


def runs_to_text(runs) -> str:
    return "".join(t for t, _ in runs)


def _merge(runs):
    out = []
    for t, f in runs:
        t = re.sub(r"\s+", " ", t)
        if out and out[-1][1] == f:
            out[-1] = (out[-1][0] + t, f)
        else:
            out.append((t, f))
    # tidy double punctuation like '..'
    return [(re.sub(r"\.\.(?!\.)", ".", t), f) for t, f in out if t]


# --------------------------------------------------------------------------
# Fetch from DOI via Crossref
# --------------------------------------------------------------------------
def _strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def fetch_doi(doi: str, timeout: int = 20) -> dict:
    doi = doi.strip()
    doi = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", doi, flags=re.I)
    r = requests.get(f"https://api.crossref.org/works/{doi}",
                     headers={"User-Agent": "KVASU-Synopsis-Generator/1.0 (mailto:user@example.com)"},
                     timeout=timeout)
    r.raise_for_status()
    m = r.json()["message"]
    ref = empty_ref()
    ctype = m.get("type", "")
    ref["type"] = {"journal-article": "article", "book": "book",
                   "book-chapter": "chapter", "standard": "standard"}.get(ctype, "article")
    authors = []
    for a in m.get("author", []):
        if "family" in a:
            authors.append(f"{a['family']}, {make_initials(a.get('given',''))}")
        elif "name" in a:
            authors.append(a["name"])
    ref["authors"] = "; ".join(authors)
    for key in ("published-print", "published-online", "issued", "created"):
        dp = m.get(key, {}).get("date-parts", [[None]])
        if dp and dp[0] and dp[0][0]:
            ref["year"] = str(dp[0][0])
            break
    ref["title"] = _strip_tags((m.get("title") or [""])[0])
    ct = m.get("container-title") or [""]
    sct = m.get("short-container-title") or [""]
    if ref["type"] == "chapter":
        ref["book_title"] = _strip_tags(ct[0])
    else:
        ref["journal"] = _strip_tags(ct[0])
        ref["journal_abbr"] = abbreviate_journal(_strip_tags(sct[0]) or ref["journal"])
    ref["volume"] = m.get("volume", "")
    ref["issue"] = m.get("issue", "")
    ref["pages"] = clean_pages(m.get("page", "") or m.get("article-number", ""))
    ref["publisher"] = m.get("publisher", "")
    ref["doi"] = m.get("DOI", doi)
    ref["url"] = m.get("URL", "")
    return ref


# Common ISO-4 word abbreviations used by veterinary / animal-science journals.
_ABBR = {
    "american": "Am.", "journal": "J.", "clinical": "Clin.", "pathology": "Pathol.",
    "poultry": "Poult.", "science": "Sci.", "sciences": "Sci.", "animal": "Anim.",
    "veterinary": "Vet.", "research": "Res.", "international": "Int.",
    "food": "Food", "meat": "Meat", "microbiology": "Microbiol.",
    "applied": "Appl.", "biochemistry": "Biochem.", "physiology": "Physiol.",
    "indian": "Indian", "world's": "World's", "worlds": "World's",
    "production": "Prod.", "technology": "Technol.", "quality": "Qual.",
    "agricultural": "Agric.", "agriculture": "Agric.", "medicine": "Med.",
    "medical": "Med.", "biology": "Biol.", "biological": "Biol.",
    "environmental": "Environ.", "nutrition": "Nutr.", "dairy": "Dairy",
    "livestock": "Livest.", "european": "Eur.", "british": "Br.",
    "chemistry": "Chem.", "society": "Soc.", "bioscience": "Biosci.",
    "biosciences": "Biosci.", "reviews": "Rev.", "review": "Rev.",
    "letters": "Lett.", "annals": "Ann.", "archives": "Arch.",
    "brazilian": "Braz.", "revista": "Rev.", "brasileira": "Bras.",
    "zootecnia": "Zootec.", "arquivo": "Arq.", "medicina": "Med.",
    "veterinária": "Vet.", "veterinaria": "Vet.", "comparative": "Comp.",
    "immunology": "Immunol.", "molecular": "Mol.", "engineering": "Eng.",
    "processing": "Process.", "preservation": "Preserv.", "safety": "Saf.",
    "protection": "Prot.", "condor": "Condor", "public": "Public",
    "health": "Health", "infection": "Infect.", "diseases": "Dis.",
    "disease": "Dis.", "tropical": "Trop.", "asian": "Asian",
    "australasian": "Australas.",
}
_SKIP = {"of", "and", "the", "for", "in", "on", "de", "e", "&", "a"}


def abbreviate_journal(name: str) -> str:
    """Best-effort abbreviation. Already-abbreviated names are returned as is.
    Users can always edit the 'journal_abbr' field."""
    name = (name or "").strip()
    if not name or "." in name:
        return name
    words = [w for w in re.split(r"\s+", name) if w.lower() not in _SKIP]
    if len(words) == 1:
        return name
    return " ".join(_ABBR.get(w.lower().strip(","), w) for w in words)


# --------------------------------------------------------------------------
# BibTeX / RIS import (lightweight, no extra dependency)
# --------------------------------------------------------------------------
def _bib_authors(s: str) -> str:
    out = []
    for a in re.split(r"\s+and\s+", s.replace("\n", " ")):
        a = a.strip().strip("{}")
        if not a:
            continue
        if "," in a:
            fam, given = a.split(",", 1)
        else:
            parts = a.split()
            fam, given = parts[-1], " ".join(parts[:-1])
        out.append(f"{fam.strip().strip('{}')}, {make_initials(given)}")
    return "; ".join(out)


def parse_bibtex(text: str) -> list[dict]:
    refs = []
    for m in re.finditer(r"@(\w+)\s*\{\s*[^,]*,(.*?)\n\}", text, flags=re.S):
        etype, body = m.group(1).lower(), m.group(2)
        fields = {}
        for fm in re.finditer(r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|\d+)", body):
            v = fm.group(2).strip()
            if v[0] in "{\"":
                v = v[1:-1]
            fields[fm.group(1).lower()] = re.sub(r"\s+", " ", v.replace("{", "").replace("}", ""))
        ref = empty_ref()
        ref["type"] = {"article": "article", "book": "book", "incollection": "chapter",
                       "inbook": "chapter", "misc": "web", "online": "web"}.get(etype, "article")
        ref["authors"] = _bib_authors(fields.get("author", ""))
        ref["year"] = fields.get("year", "")
        ref["title"] = fields.get("title", "")
        ref["journal"] = fields.get("journal", "")
        ref["journal_abbr"] = abbreviate_journal(fields.get("shortjournal", "") or ref["journal"])
        ref["volume"] = fields.get("volume", "")
        ref["issue"] = fields.get("number", "")
        ref["pages"] = clean_pages(fields.get("pages", ""))
        ref["publisher"] = fields.get("publisher", "")
        ref["place"] = fields.get("address", "")
        ref["edition"] = fields.get("edition", "")
        ref["editors"] = fields.get("editor", "")
        ref["book_title"] = fields.get("booktitle", "")
        ref["doi"] = fields.get("doi", "")
        ref["url"] = fields.get("url", "")
        refs.append(ref)
    return refs


def parse_ris(text: str) -> list[dict]:
    refs, cur, authors = [], None, []
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])\s{2}-\s?(.*)$", line)
        if not m:
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "TY":
            cur, authors = empty_ref(), []
            cur["type"] = {"JOUR": "article", "BOOK": "book", "CHAP": "chapter",
                           "STAND": "standard", "ELEC": "web"}.get(val, "article")
        elif cur is None:
            continue
        elif tag in ("AU", "A1"):
            fam, _, given = val.partition(",")
            authors.append(f"{fam.strip()}, {make_initials(given)}" if given else fam.strip())
        elif tag in ("PY", "Y1", "DA") and not cur["year"]:
            cur["year"] = val[:4]
        elif tag in ("TI", "T1"):
            cur["title"] = val
        elif tag in ("JO", "T2", "JF"):
            if cur["type"] == "chapter":
                cur["book_title"] = val
            elif not cur["journal"]:
                cur["journal"] = val
        elif tag in ("J2", "JA"):
            cur["journal_abbr"] = val
        elif tag == "VL":
            cur["volume"] = val
        elif tag == "IS":
            cur["issue"] = val
        elif tag == "SP":
            cur["pages"] = val
        elif tag == "EP":
            cur["pages"] = f"{cur['pages']}-{val}"
        elif tag == "PB":
            cur["publisher"] = val
        elif tag == "CY":
            cur["place"] = val
        elif tag == "DO":
            cur["doi"] = val
        elif tag == "UR":
            cur["url"] = val
        elif tag == "ER":
            cur["authors"] = "; ".join(authors)
            if not cur["journal_abbr"]:
                cur["journal_abbr"] = abbreviate_journal(cur["journal"])
            refs.append(cur)
            cur = None
    return refs
