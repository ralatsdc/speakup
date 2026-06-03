"""
Read-only parser for "Speak Up Cambridge Open Roles.txt".

Iteration 1: tokenize the Google-Docs table export into tab-anchored cells,
segment into meeting blocks (date-header run + body), and dump the structure
so column alignment can be verified by eye before any name resolution or DB
write.

Run:  python import_scripts/parse_open_roles.py
"""

import os
import re
import sys

SRC = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "Speak-Up-Cambridge-Open-Roles.txt",
)

# --- tokenizer -------------------------------------------------------------

# Lines that delimit blocks / are boilerplate. Matched on the stripped line.
BOILERPLATE_RE = re.compile(
    r"^(?:"
    r"_{3,}"                                  # ________ separators
    r"|\*?\s*\*?\s*R\s*=\s*Remote"            # R = Remote (with optional *'s)
    r"|L\s*=\s*Local.*"                       # L = Local (in-person)
    r"|Role descriptions available.*"         # line 1 preamble
    r"|Meeting ID:.*"                         # line 2 preamble
    r")\s*$",
    re.IGNORECASE,
)

MONTHS = (
    r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|"
    r"January|February|March|April|June|July|August|September|October|"
    r"November|December"
)
DATE_RE = re.compile(rf"^\s*(?:{MONTHS})[a-z]*\.?\s*\d{{1,2}}\b", re.IGNORECASE)

CELL = "CELL"
BOUNDARY = "BOUNDARY"


def tokenize(path):
    """Return a list of (kind, text) tokens.

    A cell begins at a tab-prefixed line; bare (non-tab) lines are extra
    paragraphs of the current cell. Boilerplate lines flush the current cell
    and emit a BOUNDARY.
    """
    tokens = []
    cur = None  # list of paragraph strings for the open cell

    def flush():
        nonlocal cur
        if cur is not None:
            tokens.append((CELL, "\n".join(cur)))
            cur = None

    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            stripped = line.strip()
            if BOILERPLATE_RE.match(stripped):
                flush()
                tokens.append((BOUNDARY, stripped))
                continue
            if line.startswith("\t"):
                flush()
                cur = [line[1:].strip()]
            else:
                # bare line: continuation paragraph of the current cell
                if cur is None:
                    cur = [stripped]
                else:
                    cur.append(stripped)
    flush()
    return tokens


def is_date(text):
    return bool(DATE_RE.match(text.strip()))


# --- header parsing: date + meeting type ----------------------------------

MONTH_NUM = {
    m: i for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"], start=1)
}
HEAD_RE = re.compile(rf"^\s*({MONTHS})[a-z]*\.?\s*(\d{{1,2}})\b\s*,?\s*(\d{{4}})?",
                     re.IGNORECASE)


def parse_header(cell):
    """Return (month:int, day:int, explicit_year:int|None, type_text:str)."""
    first = cell.split("\n", 1)[0]
    m = HEAD_RE.match(first)
    mon = MONTH_NUM[m.group(1)[:3].lower()]
    day = int(m.group(2))
    yr = int(m.group(3)) if m.group(3) else None
    type_text = " ".join(p.strip() for p in cell.split("\n")[1:] if p.strip())
    return mon, day, yr, type_text


def meeting_type(type_text):
    """Map header type text to a DB MeetingType name, or None to skip."""
    t = type_text.lower()
    if "improv for the work" in t or "party" in t:
        return None  # skip
    if "think on your feet" in t or "all table topics" in t:
        return "Table Topic Meeting"
    return "Regular Meeting"


# --- role label vocabulary -------------------------------------------------

IGNORE = "<ignore>"
SKIP = "<skip>"
ROOM = "<room-or-ignore>"  # Room Leader if Table Topic else ignore


def map_role(cell):
    """Map a label cell to (db_role_name | IGNORE | SKIP | ROOM | None).
    None means 'not a label' (so it's a value cell)."""
    t = re.sub(r"[^a-z0-9 ]", " ", cell.lower())
    t = re.sub(r"\s+", " ", t).strip()
    if t.startswith("meeting coordinator"):
        return IGNORE
    if t.startswith("zoom host"):
        return "Zoom Host"
    if t.startswith("zoom wizard"):
        return "Zoom Wizard"
    if t.startswith("room master"):
        return ROOM
    if t.startswith("breakout"):
        return ROOM
    if t == "improv" or t.startswith("improv "):
        return "Improv Exercise Leader"
    if t.startswith("toastmaster"):
        return "Toastmaster"
    if t.startswith("timer"):
        return "Timer"
    if t.startswith("word of the day"):
        return "Word of the Day Presenter"
    if t.startswith("ah um counter") or t.startswith("ahum counter"):
        return "Ah-Um Counter"
    if t.startswith("humor"):
        return "Humorist"
    if t.startswith("intro to round robin") or t.startswith("round robin"):
        return "Round Robin Leader"
    if t.startswith("speech waitlist") or t.startswith("speech  waitlist"):
        return SKIP
    if t.startswith("speeches") or t.startswith("speech "):
        # 'speech evaluator ...' handled below; bare 'speeches' = Speaker
        if "evaluator" not in t:
            return "Speaker"
    if t.startswith("rant"):
        return "Ranter"
    if "table topics leader" in t or t == "leader":
        return "Topicmaster"
    if t.startswith("evaluate table topics"):
        return "Evaluator (Table Topic)"
    if t.startswith("general evaluation") or t.startswith("general eval"):
        return "General Evaluator"
    if t.startswith("speech") and "evaluator" in t:
        return "Evaluator (Rant)" if "rant" in t else "Evaluator (Speech)"
    if t.startswith("grammarian"):
        return "Grammarian"
    if t.startswith("spacemaster"):
        return IGNORE
    return None  # not a recognized label -> treat as value


# --- name extraction -------------------------------------------------------

NONNAME = {
    "", "open", "n/a", "na", "tbd", "no topics", "not tonight", "no rants",
    "none", "?", "*", "-", "--", "icebreaker", "ice breaker", "(ice breaker)",
    "if there s time", "if theres time", "online", "onsite", "remote", "tba",
    "the", "a speech", "taxes", "guest", "all", "both", "n", "l", "r",
}
SPLIT_RE = re.compile(r"\s*(?:\+|&|/|,| and )\s*", re.IGNORECASE)
ANNOT_RE = re.compile(
    r"\b(online|onsite|on-site|remote|icebreaker|ice\s*breaker|ice-breaker|"
    r"DTM|TBD|backup|guest|evaluator|special)\b", re.IGNORECASE)


def clean_name(s):
    s = re.sub(r"\[[^\]]*\]", " ", s)               # [R]
    s = re.sub(r"\([^)]*\)", " ", s)                # (remote)/(icebreaker)
    s = re.split(r"[‘’“”\"]", s)[0]             # drop speech title in quotes
    s = re.sub(r"^\s*(?:onsite|online|remote)\s*[-:]\s*", "", s, flags=re.I)
    s = re.split(r"\s[-–—]\s", s)[0]                 # drop ' - speech title'
    s = ANNOT_RE.sub(" ", s)                         # stray annotation words
    s = re.sub(r"\b[LR]\b", " ", s)                  # bare Local/Remote marker
    s = s.replace("*", " ")
    s = re.sub(r"^\s*\d+\s*[.)\-:+]*\s*", "", s)     # leading "1." "2)" "1+"
    s = re.sub(r"[^\w .'-]", " ", s)                 # keep word/.'- only
    s = re.sub(r"\s+", " ", s).strip(" .,:-'")
    return s


def extract_names(cell):
    """Return list of raw cleaned name strings from a value cell."""
    out = []
    # each paragraph may hold "1. X" "2. Y"; split on newlines, ';', and
    # before a numbered enumerator
    parts = re.split(r"\n|;|(?=\b[1-5]\s*[.)\-:])", cell)
    for part in parts:
        part = re.sub(r"\([^)]*\)", " ", part)       # strip parens BEFORE split
        part = re.split(r"[‘’“”\"]", part)[0]
        for piece in SPLIT_RE.split(part):
            name = clean_name(piece)
            low = name.lower()
            if name and low not in NONNAME and not name.isdigit() and len(name) > 1:
                out.append(name)
    return out


def split_blocks(tokens):
    """Split the token stream on BOUNDARY into segments, keep segments whose
    first cell is a date (those are real meeting blocks). Returns a list of
    dicts: {header_cells: [...], body_cells: [...]}."""
    blocks = []
    # group cells between boundaries
    segments = []
    cur = []
    for kind, text in tokens:
        if kind == BOUNDARY:
            if cur:
                segments.append(cur)
                cur = []
        else:
            cur.append(text)
    if cur:
        segments.append(cur)

    for seg in segments:
        # drop leading whitespace-only cells (blank lines after a separator
        # collect into an empty cell that hides the real date header)
        while seg and not seg[0].strip():
            seg = seg[1:]
        if not seg or not is_date(seg[0]):
            continue
        # leading run of date cells = header columns
        i = 0
        while i < len(seg) and is_date(seg[i]):
            i += 1
        blocks.append({"header_cells": seg[:i], "body_cells": seg[i:]})
    return blocks


from collections import defaultdict


def assemble(blocks):
    """Return list of meeting dicts (one per block column) with parsed
    headers and role->names, plus a list of alignment warnings."""
    meetings = []
    warnings = []
    for bi, blk in enumerate(blocks):
        headers = [parse_header(c) for c in blk["header_cells"]]
        n = len(headers)
        types = [meeting_type(h[3]) for h in headers]
        roles_per_col = [defaultdict(list) for _ in range(n)]

        body = blk["body_cells"]
        i = 0
        while i < len(body):
            role = map_role(body[i])
            if role is None:
                i += 1
                continue
            j = i + 1
            vals = []
            while j < len(body) and map_role(body[j]) is None:
                vals.append(body[j])
                j += 1
            if role not in (IGNORE, SKIP):
                if len([v for v in vals if v.strip(" /\n")]) and len(vals) != n:
                    warnings.append(
                        f"block{bi} '{body[i].splitlines()[0]}': "
                        f"{len(vals)} value cells != {n} columns")
                for col_idx, vcell in enumerate(vals):
                    if col_idx >= n:
                        break
                    db_role = role
                    if db_role == ROOM:
                        if types[col_idx] != "Table Topic Meeting":
                            continue
                        db_role = "Room Leader"
                    for nm in extract_names(vcell):
                        roles_per_col[col_idx][db_role].append(nm)
            i = j

        for ci, (mon, day, yr, ttext) in enumerate(headers):
            meetings.append({
                "block": bi, "col": ci, "mon": mon, "day": day,
                "explicit_year": yr, "type_text": ttext,
                "type": types[ci], "roles": dict(roles_per_col[ci]),
            })
    return meetings, warnings


def infer_years(meetings, seed_year=2026):
    """Assign a 'year' to each meeting. Walk DESCENDING chrono order (blocks
    top->bottom, columns right->left) anchored at the top (latest) meeting,
    decrementing the year whenever a date jumps forward (= crossed Jan).
    Explicit years override and re-anchor."""
    order = sorted(range(len(meetings)),
                   key=lambda k: (meetings[k]["block"], -meetings[k]["col"]))
    prev = None  # (year, mon, day)
    for k in order:
        m = meetings[k]
        if m["explicit_year"]:
            y = m["explicit_year"]
        elif prev is None:
            y = seed_year
        else:
            # descending: a forward jump in (mon,day) means we crossed a year
            y = prev[0] - 1 if (m["mon"], m["day"]) > (prev[1], prev[2]) else prev[0]
        m["year"] = y
        prev = (y, m["mon"], m["day"])
    return meetings


def main():
    tokens = tokenize(SRC)
    blocks = split_blocks(tokens)
    meetings, warnings = assemble(blocks)
    infer_years(meetings)

    print(f"blocks: {len(blocks)}  meetings: {len(meetings)}\n")
    print("=== inferred dates / type / #roles filled ===")
    for m in meetings:
        nfilled = sum(len(v) for v in m["roles"].values())
        flag = "  <<SKIP-TYPE>>" if m["type"] is None else ""
        print(f"  {m['year']}-{m['mon']:02d}-{m['day']:02d}  "
              f"{(m['type'] or m['type_text'])[:22]:22}  "
              f"roles:{len(m['roles']):2}  names:{nfilled:2}{flag}")

    print(f"\n=== alignment warnings: {len(warnings)} ===")
    for w in warnings[:40]:
        print(" ", w)


if __name__ == "__main__":
    main()
