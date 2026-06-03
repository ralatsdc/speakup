"""
Build the two REVIEW artifacts (no DB writes) for the role import:

  import_scripts/parse_preview.txt   - per-meeting date/type/role -> [raw names]
  import_scripts/alias_map_draft.md  - distinct raw name -> active-user match,
                                       bucketed confident / ambiguous / drop

Only meetings on/after CUTOFF are included.

Run:  python import_scripts/build_artifacts.py
"""

import datetime as dt
import importlib.util
import os
import sys
from collections import defaultdict

import django

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # project root for 'config'
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from members.models import User  # noqa: E402
from import_scripts import resolve as R  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CUTOFF = dt.date(2024, 7, 1)
TODAY = dt.date(2026, 6, 2)

# load parser module by path (it has no Django deps)
spec = importlib.util.spec_from_file_location(
    "parse_open_roles", os.path.join(HERE, "parse_open_roles.py"))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


def load_users():
    users = list(User.objects.all())
    active = [u for u in users if u.is_active]
    by_email = {u.email: u for u in users}
    return users, active, by_email


def main():
    tokens = P.tokenize(P.SRC)
    blocks = P.split_blocks(tokens)
    meetings, _ = P.assemble(blocks)
    P.infer_years(meetings)

    # filter to window + attach a date
    win = []
    for m in meetings:
        try:
            d = dt.date(m["year"], m["mon"], m["day"])
        except ValueError:
            continue
        if d >= CUTOFF and m["type"] is not None:
            m["date"] = d
            win.append(m)
    win.sort(key=lambda m: m["date"])

    users, active, by_email = load_users()

    # ---- parse_preview.txt ----
    lines = [f"PARSE PREVIEW  (meetings >= {CUTOFF}, {len(win)} meetings)",
             f"generated for review; today={TODAY}", ""]
    name_freq = defaultdict(int)
    name_meetings = defaultdict(set)
    for m in win:
        when = "UPCOMING" if m["date"] >= TODAY else "past"
        lines.append(f"=== {m['date']}  {m['type']}  [{when}] ===")
        for role in sorted(m["roles"]):
            names = m["roles"][role]
            for nm in names:
                name_freq[nm] += 1
                name_meetings[nm].add(str(m["date"]))
            lines.append(f"    {role:24} : {', '.join(names)}")
        lines.append("")
    with open(os.path.join(HERE, "parse_preview.txt"), "w") as fh:
        fh.write("\n".join(lines))

    # ---- alias_map_draft.md ----
    buckets = {"confident": [], "ambiguous": [], "drop": []}
    for raw in name_freq:
        bucket, detail = R.match(raw, active, users, by_email)
        buckets[bucket].append((raw, detail, name_freq[raw]))

    out = ["# Draft alias map (review before import)",
           f"_Window: meetings >= {CUTOFF}. Match targets: "
           f"{len(active)} ACTIVE users only._", "",
           f"- confident: {len(buckets['confident'])}  "
           f"ambiguous: {len(buckets['ambiguous'])}  "
           f"drop: {len(buckets['drop'])}", ""]

    out.append("## AMBIGUOUS — needs your decision\n")
    for raw, cands, f in sorted(buckets["ambiguous"], key=lambda x: -x[2]):
        opts = " | ".join(f"{u.first_name} {u.last_name}" for u in cands)
        out.append(f"- **{raw}** ({f}x)  ->  {opts}")
    out.append("\n## DROP — no active-user match (scan for any I missed)\n")
    for raw, detail, f in sorted(buckets["drop"], key=lambda x: -x[2]):
        out.append(f"- {raw} ({f}x)  -- {detail}")
    out.append("\n## CONFIDENT — auto-matched (spot-check)\n")
    for raw, u, f in sorted(buckets["confident"], key=lambda x: -x[2]):
        out.append(f"- {raw} ({f}x)  ->  {u.first_name} {u.last_name} <{u.email}>")
    with open(os.path.join(HERE, "alias_map_draft.md"), "w") as fh:
        fh.write("\n".join(out))

    print(f"meetings in window: {len(win)}")
    print(f"distinct raw names: {len(name_freq)}")
    print(f"  confident: {len(buckets['confident'])}")
    print(f"  ambiguous: {len(buckets['ambiguous'])}")
    print(f"  drop:      {len(buckets['drop'])}")
    print("wrote parse_preview.txt and alias_map_draft.md")


if __name__ == "__main__":
    main()
