"""
Name resolution shared by the artifact builder and the import command.

Pure Python (no Django side effects at import). Callers pass plain User
objects so this stays test/CLI friendly.
"""

import re

# Hand-seeded aliases for names not derivable by heuristic. Maps a normalized
# raw name -> an email (active user) or the sentinel "<drop>".
SEED = {
    "svitlana b": "svetlanabe99@gmail.com",
    "svitlana": "svetlanabe99@gmail.com",
    "lana": "svetlanabe99@gmail.com",
    "wendy mkhize": "mkhizew@icloud.com",
    "wendy ramirez": "mkhizew@icloud.com",
    "wendy ham": "wendyham@gmail.com",
    "dinah": "dainathomas@gmail.com",
    "dinah thomas": "dainathomas@gmail.com",
    "daina thomas": "dainathomas@gmail.com",
    "diana thomas": "dainathomas@gmail.com",
    "yami suarez": "toastmasters@yamil.com",
    "becky serris": "<drop>",
    "rebecca serris": "<drop>",
    # confirmed by user: Erica Phan == active Erica Nguyen
    "erica phan": "thuphannguyenminh@gmail.com",
}

# first-name nicknames -> canonical first name used in the DB
NICK = {"nick": "nicholas", "jen": "jennifer", "jenn": "jennifer"}


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def match(raw, active, all_users, by_email):
    """Return (bucket, detail). bucket in {confident, ambiguous, drop}.
    For 'confident' detail is a User; 'ambiguous' a list of Users; 'drop' a str.
    """
    n = norm(raw)
    if n in SEED:
        tgt = SEED[n]
        if tgt == "<drop>":
            return "drop", "seed: no DB match"
        u = by_email[tgt]
        return ("confident", u) if u.is_active else ("drop", f"inactive {u}")

    toks = n.split()
    if toks:
        toks[0] = NICK.get(toks[0], toks[0])

    def actives(pred):
        return [u for u in active if pred(u)]

    if len(toks) >= 2:
        f, l = toks[0], toks[-1]
        c = actives(lambda u: u.first_name.lower() == f and u.last_name.lower() == l)
        if len(c) == 1:
            return "confident", c[0]
        if len(c) > 1:
            return "ambiguous", c
    if len(toks) == 2 and len(toks[1]) <= 2:
        f, li = toks[0], toks[1][0]
        c = actives(lambda u: u.first_name.lower() == f
                    and u.last_name[:1].lower() == li)
        if len(c) == 1:
            return "confident", c[0]
        if len(c) > 1:
            return "ambiguous", c
    if len(toks) >= 2:
        f, l = toks[0], toks[-1]
        c = actives(lambda u: u.first_name.lower() == f
                    and u.last_name.lower().startswith(l))
        if len(c) == 1:
            return "confident", c[0]
    if len(toks) == 1:
        c = actives(lambda u: u.first_name.lower() == toks[0])
        if len(c) == 1:
            return "confident", c[0]
        if len(c) > 1:
            return "ambiguous", c
    if len(toks) == 1:
        c = actives(lambda u: u.last_name.lower() == toks[0])
        if len(c) == 1:
            return "confident", c[0]

    for u in all_users:
        if norm(f"{u.first_name} {u.last_name}") == n:
            return "drop", f"inactive {u}" if not u.is_active else f"?{u}"
    return "drop", "no DB match"


def resolve(raw, active, all_users, by_email):
    """Return the active User for a raw name, or None if not confidently
    matched (ambiguous or drop)."""
    bucket, detail = match(raw, active, all_users, by_email)
    return detail if bucket == "confident" else None
