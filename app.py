"""
KVASU Synopsis Generator (Acad Form No. 19)
Run with:   streamlit run app.py
"""
import io
import json
import os
import re
import tempfile

import pandas as pd
import streamlit as st

try:  # normal layout: synopsis/ package
    from synopsis.generator import build_document
    from synopsis.references import (REF_FIELDS, STYLES, empty_ref, fetch_doi,
                                     format_reference, in_text_citation,
                                     parse_bibtex, parse_ris, runs_to_text, sort_key)
    from synopsis.validator import validate
except ImportError:  # all files in one folder
    from generator import build_document
    from references import (REF_FIELDS, STYLES, empty_ref, fetch_doi,
                            format_reference, in_text_citation,
                            parse_bibtex, parse_ris, runs_to_text, sort_key)
    from validator import validate

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = next((p for p in (os.path.join(HERE, "assets", "kvasu_logo.png"),
                         os.path.join(HERE, "kvasu_logo.png")) if os.path.exists(p)), "")
HAS_LOGO = bool(LOGO)
st.set_page_config(page_title="KVASU Synopsis Generator",
                   page_icon=LOGO if HAS_LOGO else "📄", layout="wide")
SAMPLE = os.path.join(HERE, "sample_synopsis.json")

BLANK = {
    "degree": "MASTERS", "faculty": "Faculty of Veterinary and Animal Sciences",
    "include_sd": True, "ref_style": "KVASU thesis style", "title": "",
    "project_title": "Nil", "project_code": "Not applicable", "student_name": "Dr. ",
    "admission_no": "", "discipline": "", "advisor_name": "Dr. ",
    "advisor_designation": "", "objectives": [], "utility": "", "publications": "",
    "technical": [], "observations": [], "facilities_existing": "",
    "facilities_additional": "", "duration": "Four semesters",
    "finance": [{"item": "Chemicals", "amount": 20000}, {"item": "Contingencies", "amount": 5000}],
    "pc_group": "", "place": "", "date": "", "committee": [], "references": [],
    "timeframe": [["Collection of literature", "Preparation of synopsis"], [], [], []],
}


# ------------------------------------------------------------------ converters
def obs_to_text(obs):
    lines = []
    for g in obs:
        g = {"text": g, "items": []} if isinstance(g, str) else g
        lines.append(g["text"])
        for s in g.get("items", []):
            s = {"text": s, "items": []} if isinstance(s, str) else s
            lines.append("- " + s["text"])
            for t in s.get("items", []):
                lines.append("-- " + (t if isinstance(t, str) else t["text"]))
    return "\n".join(lines)


def text_to_obs(text):
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("--"):
            if out and out[-1]["items"]:
                out[-1]["items"][-1]["items"].append(line[2:].strip())
        elif line.startswith("-"):
            if out:
                out[-1]["items"].append({"text": line[1:].strip(), "items": []})
        else:
            out.append({"text": re.sub(r"^\d+\.\s*", "", line), "items": []})
    return out


def tech_to_parts(tech):
    paras, table = [], None
    for b in tech:
        if isinstance(b, str) or b.get("type") != "table":
            paras.append(b if isinstance(b, str) else b.get("text", ""))
        else:
            paras.append("[TABLE]")
            table = b
    return "\n\n".join(paras), table


def parts_to_tech(text, table_df, caption):
    blocks = []
    for chunk in re.split(r"\[TABLE\]", text):
        if chunk.strip():
            blocks.append({"type": "para", "text": chunk.strip()})
        blocks.append("__T__")
    blocks = blocks[:-1] if blocks and blocks[-1] == "__T__" else blocks
    tbl = None
    if table_df is not None and len(table_df.columns):
        df = table_df.fillna("")
        tbl = {"type": "table", "caption": caption, "headers": [str(c) for c in df.columns],
               "rows": [[str(x) for x in r] for r in df.values.tolist() if any(str(x).strip() for x in r)]}
    res = []
    for b in blocks:
        if b == "__T__":
            if tbl:
                res.append(tbl)
        else:
            res.append(b)
    return res


# ------------------------------------------------------------------ state
def load_into_state(d):
    full = {**BLANK, **d}
    S = st.session_state
    for k in ("degree", "faculty", "include_sd", "ref_style", "title", "project_title",
              "project_code", "student_name", "admission_no", "discipline", "advisor_name",
              "advisor_designation", "utility", "publications", "facilities_existing",
              "facilities_additional", "duration", "pc_group", "place", "date"):
        S[k] = full[k]
    S["objectives_txt"] = "\n".join(full["objectives"])
    S["obs_txt"] = obs_to_text(full["observations"])
    S["tech_txt"], tbl = tech_to_parts(full["technical"])
    if tbl:
        S["tbl_df"] = pd.DataFrame(tbl["rows"], columns=tbl["headers"])
        S["tbl_caption"] = tbl.get("caption", "")
    else:
        S["tbl_df"] = pd.DataFrame([["", "", ""]], columns=["Treatment groups", "Column 2", "Column 3"])
        S["tbl_caption"] = ""
    S["fin_df"] = pd.DataFrame(full["finance"], columns=["item", "amount"])
    S["n_comm"] = max(len(full["committee"]), 1)
    for i in range(8):
        m = full["committee"][i] if i < len(full["committee"]) else {"name": "Dr. ", "address": ""}
        S[f"cm_name_{i}"] = m["name"]
        S[f"cm_addr_{i}"] = m["address"]
    S["n_sem"] = max(len(full["timeframe"]), 4)
    for i in range(6):
        S[f"sem_{i}"] = "\n".join(full["timeframe"][i]) if i < len(full["timeframe"]) else ""
    S["refs"] = [{**empty_ref(), **r} for r in full["references"]]
    S.pop("tbl_out", None)
    S.pop("fin_out", None)
    refresh_refs()


def refresh_refs():
    S = st.session_state
    S["refs_base"] = list(S["refs"])
    S["ref_ver"] = S.get("ref_ver", 0) + 1


def collect():
    S = st.session_state
    d = {k: S[k] for k in ("degree", "faculty", "include_sd", "ref_style", "title",
                           "project_title", "project_code", "student_name", "admission_no",
                           "discipline", "advisor_name", "advisor_designation", "utility",
                           "publications", "facilities_existing", "facilities_additional",
                           "duration", "pc_group", "place", "date")}
    d["objectives"] = [re.sub(r"^\d+\.\s*", "", o).strip() for o in S["objectives_txt"].splitlines() if o.strip()]
    d["observations"] = text_to_obs(S["obs_txt"])
    d["technical"] = parts_to_tech(S["tech_txt"], S.get("tbl_out", S.get("tbl_df")),
                                   S.get("tbl_caption", "")) if "[TABLE]" in S["tech_txt"] else \
        [{"type": "para", "text": S["tech_txt"]}]
    fin = S.get("fin_out", S["fin_df"]).fillna("")
    d["finance"] = [{"item": str(r["item"]), "amount": r["amount"]} for _, r in fin.iterrows()
                    if str(r["item"]).strip()]
    d["committee"] = [{"name": S[f"cm_name_{i}"], "address": S[f"cm_addr_{i}"]}
                      for i in range(S["n_comm"]) if S[f"cm_name_{i}"].strip() not in ("", "Dr.")]
    d["timeframe"] = [[t.strip() for t in S[f"sem_{i}"].splitlines() if t.strip()]
                      for i in range(S["n_sem"])]
    d["references"] = S["refs"]
    return d


if "title" not in st.session_state:
    load_into_state(BLANK)

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    if HAS_LOGO:
        st.image(LOGO, width=120)
    st.header("KVASU Synopsis Generator")
    st.caption("Acad Form No. 19 – Programme of Research Work")
    up = st.file_uploader("Open saved project (.json)", type=["json"])
    if up and st.button("Load project"):
        load_into_state(json.load(up))
        st.rerun()
    if os.path.exists(SAMPLE) and st.button("Load sample synopsis"):
        load_into_state(json.load(open(SAMPLE, encoding="utf-8")))
        st.rerun()
    if st.button("Start new blank synopsis"):
        load_into_state(BLANK)
        st.rerun()
    st.divider()
    st.radio("Degree", ["MASTERS", "DOCTORATE"], key="degree")
    st.selectbox("Reference style", list(STYLES.keys()), key="ref_style")
    st.checkbox("Add 'Sd/-' (soft copy)", key="include_sd")
    st.divider()
    st.caption("Formatting tags you can use in any text box: "
               "`<i>italic</i>`, `<b>bold</b>`, `<sup>2</sup>`, `<sub>2</sub>`")

# ------------------------------------------------------------------ page header
h1, h2 = st.columns([1, 9], vertical_alignment="center")
if HAS_LOGO:
    h1.image(LOGO, width=90)
h2.markdown("### KERALA VETERINARY AND ANIMAL SCIENCES UNIVERSITY\n"
            "**Programme of Research Work for Thesis (Acad Form No. 19) – Synopsis Generator**")
st.divider()

tabs = st.tabs(["1–4 Details", "5–7 Objectives & literature", "8 Technical programme",
                "9 Observations", "10–12 Facilities & budget", "Committee & signatures",
                "13 References", "14 Time frame", "✅ Check & generate"])

# ------------------------------------------------------------------ tab 1
with tabs[0]:
    st.text_input("Faculty", key="faculty")
    st.text_area("1. Title of thesis (no full stop at end)", key="title", height=80)
    c1, c2 = st.columns(2)
    c1.text_input("2a. Departmental/KVASU project title", key="project_title")
    c2.text_input("2b. Code No. and sanction order", key="project_code")
    c1, c2, c3 = st.columns(3)
    c1.text_input("3a. Name of student", key="student_name")
    c2.text_input("3b. Admission No.", key="admission_no", placeholder="24-MVM-11")
    c3.text_input("3c. Name of the discipline", key="discipline")
    c1, c2 = st.columns(2)
    c1.text_input("4a. Name of major advisor", key="advisor_name")
    c2.text_area("4b. Designation (one line per row)", key="advisor_designation", height=110)

with tabs[1]:
    st.text_area("5. Objectives – one per line (do not start with 'To', no full stop)",
                 key="objectives_txt", height=140)
    st.text_area("6. Practical / Scientific utility – separate paragraphs with a blank line",
                 key="utility", height=220)
    st.text_area("7. Important publications – one paragraph per study, blank line between, "
                 "in chronological order", key="publications", height=320)

with tabs[2]:
    st.text_area("8. Outline of the technical programme – blank line between paragraphs. "
                 "Type [TABLE] on its own line where the table should appear.",
                 key="tech_txt", height=380)
    st.text_input("Table caption (optional)", key="tbl_caption")
    st.caption("Table – edit cells, add rows at the bottom. To rename/add columns, edit "
               "'Column headings' below.")
    hdr = st.text_input("Column headings (separate with |)",
                        value=" | ".join(map(str, st.session_state["tbl_df"].columns)))
    new_cols = [h.strip() for h in hdr.split("|") if h.strip()]
    df = st.session_state.get("tbl_out", st.session_state["tbl_df"])
    if new_cols and new_cols != list(df.columns):
        vals = df.values.tolist()
        vals = [(r + [""] * len(new_cols))[:len(new_cols)] for r in vals]
        st.session_state["tbl_df"] = pd.DataFrame(vals, columns=new_cols)
    st.session_state["tbl_out"] = st.data_editor(st.session_state["tbl_df"], num_rows="dynamic",
                                                 width="stretch",
                                                 key=f"tbl_editor_{st.session_state['ref_ver']}_{len(new_cols)}")

with tabs[3]:
    st.markdown("Type each **main item** on its own line, sub-items starting with `- `, "
                "and sub-sub-items with `-- `. Numbering (1. a. i.) is added automatically.")
    st.text_area("9. Main items of observations", key="obs_txt", height=420)

with tabs[4]:
    st.text_area("10a. Facilities – existing", key="facilities_existing", height=100)
    st.text_input("10b. Facilities – additional", key="facilities_additional")
    st.text_input("11. Duration of study", key="duration")
    st.caption("12. Financial estimate (amount in rupees, numbers only – total is calculated)")
    st.session_state["fin_out"] = st.data_editor(
        st.session_state["fin_df"], num_rows="dynamic", width="stretch",
        key=f"fin_editor_{st.session_state['ref_ver']}",
        column_config={"item": "Item", "amount": st.column_config.NumberColumn("Amount (Rs.)", step=100)})

with tabs[5]:
    st.text_input("Project coordination group", key="pc_group")
    c1, c2 = st.columns(2)
    c1.text_input("Place", key="place")
    c2.text_input("Date (DD.MM.YYYY)", key="date")
    st.number_input("Number of other advisory committee members", 1, 8, key="n_comm")
    for i in range(st.session_state["n_comm"]):
        c1, c2 = st.columns([1, 2])
        c1.text_input(f"Member {i+1} name", key=f"cm_name_{i}")
        c2.text_area(f"Member {i+1} designation & address (one line per row)",
                     key=f"cm_addr_{i}", height=110)

# ------------------------------------------------------------------ references
with tabs[6]:
    S = st.session_state
    st.markdown("**Add references** – by DOI (fetched automatically from Crossref), "
                "by uploading a BibTeX/RIS export from Zotero/Mendeley/Google Scholar, or manually.")
    c1, c2 = st.columns(2)
    with c1:
        dois = st.text_area("DOIs (one per line)", height=120, key="doi_box")
        if st.button("Fetch from DOI"):
            have = {r.get("doi", "").lower() for r in S["refs"]}
            for doi in [x.strip() for x in dois.splitlines() if x.strip()]:
                clean = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", doi, flags=re.I).lower()
                if clean in have:
                    continue
                try:
                    S["refs"].append(fetch_doi(doi))
                    st.success(f"Added: {doi}")
                except Exception as e:
                    st.error(f"Could not fetch {doi}: {e}")
            refresh_refs()
    with c2:
        f = st.file_uploader("Upload .bib or .ris", type=["bib", "ris", "txt"])
        if f and st.button("Import file"):
            txt = f.read().decode("utf-8", errors="ignore")
            new = parse_ris(txt) if re.search(r"^TY\s{2}-", txt, re.M) else parse_bibtex(txt)
            S["refs"].extend(new)
            refresh_refs()
            st.success(f"Imported {len(new)} references")
        if st.button("➕ Add blank reference (manual entry)"):
            S["refs"].append(empty_ref())
            refresh_refs()

    st.markdown("**Edit references** – authors as `Surname, Initials; Surname, Initials`. "
                "Type: article / book / chapter / standard / web. Check `journal_abbr` "
                "(used in KVASU style).")
    base = S["refs_base"]
    ref_df = pd.DataFrame(base, columns=REF_FIELDS) if base else pd.DataFrame(columns=REF_FIELDS)
    edited = st.data_editor(
        ref_df, num_rows="dynamic", width="stretch", key=f"ref_editor_{S['ref_ver']}",
        column_config={"type": st.column_config.SelectboxColumn(
            "type", options=["article", "book", "chapter", "standard", "web"])})
    S["refs"] = [{k: ("" if pd.isna(v) else str(v)) for k, v in r.items()}
                 for r in edited.to_dict("records") if any(str(v).strip() for v in r.values() if not pd.isna(v))]

    st.markdown("**Preview** (sorted, as it will appear) and the in-text citation to use:")
    for r in sorted(S["refs"], key=sort_key):
        md = "".join(f"*{t}*" if fm.get("italic") and t.strip() else
                     (f"**{t}**" if fm.get("bold") and t.strip() else t)
                     for t, fm in format_reference(r, S["ref_style"]))
        st.markdown(f"- {md}  \n  ↳ cite as *({in_text_citation(r)})*")

with tabs[7]:
    st.number_input("Number of semesters", 1, 6, key="n_sem")
    cols = st.columns(2)
    roman = ["I", "II", "III", "IV", "V", "VI"]
    for i in range(st.session_state["n_sem"]):
        cols[i % 2].text_area(f"Semester {roman[i]} – one task per line", key=f"sem_{i}", height=110)

# ------------------------------------------------------------------ generate
with tabs[8]:
    data = collect()
    issues = validate(data)
    errs = [i for i in issues if i[0] == "error"]
    warns = [i for i in issues if i[0] == "warning"]
    st.subheader(f"Rule check: {len(errs)} errors, {len(warns)} warnings")
    if not issues:
        st.success("No problems found against the KVASU general instructions.")
    for lvl, sec, msg in errs:
        st.error(f"**{sec}** – {msg}")
    for lvl, sec, msg in warns:
        st.warning(f"**{sec}** – {msg}")
    st.divider()
    if st.button("📄 Generate Word document", type="primary"):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "synopsis.docx")
            build_document(data, out)
            st.session_state["docx_bytes"] = open(out, "rb").read()
    if st.session_state.get("docx_bytes"):
        name = re.sub(r"[^\w\-]+", "_", f"Synopsis_{data['student_name']}_{data['admission_no']}").strip("_")
        st.download_button("⬇️ Download .docx", st.session_state["docx_bytes"], file_name=f"{name}.docx",
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

with st.sidebar:
    st.divider()
    st.download_button("💾 Save project (.json)",
                       json.dumps(collect(), indent=2, ensure_ascii=False, default=str),
                       file_name="my_synopsis.json", mime="application/json")
