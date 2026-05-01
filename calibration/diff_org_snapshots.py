"""diff_org_snapshots.py — print a focused diff of two org snapshots."""
import json
import sys
from pathlib import Path

import pandas as pd


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def lineup_table(records):
    df = pd.DataFrame(records)
    keep = [c for c in ["pos", "name", "pos_WAR", "wOBA_vs", "wRC+_vs", "note"] if c in df.columns]
    return df[keep]


def main():
    before = load(sys.argv[1])
    after = load(sys.argv[2])

    print("=" * 70)
    print(f"{'metric':25} {'before':>12} {'after':>12} {'delta':>12}")
    print("=" * 70)
    for k in ("lineup_war_r", "lineup_war_l", "runs_pg_r", "runs_pg_l"):
        b, a = before[k], after[k]
        d = (a - b) if (a is not None and b is not None) else None
        d_str = f"{d:+.2f}" if d is not None else "—"
        print(f"{k:25} {b:>12.2f} {a:>12.2f} {d_str:>12}")
    print()

    for side, key in (("vs RHP", "lineup_r"), ("vs LHP", "lineup_l")):
        print(f"── Lineup {side} ──")
        bt = lineup_table(before[key]).rename(columns={"name": "name_b", "pos_WAR": "pw_b"})
        at = lineup_table(after[key]).rename(columns={"name": "name_a", "pos_WAR": "pw_a"})
        cmp = bt[["pos", "name_b", "pw_b"]].merge(at[["pos", "name_a", "pw_a"]], on="pos", how="outer")
        cmp["same_player"] = cmp["name_b"] == cmp["name_a"]
        cmp["delta_war"] = cmp["pw_a"] - cmp["pw_b"]
        for col in ("pw_b", "pw_a", "delta_war"):
            cmp[col] = pd.to_numeric(cmp[col], errors="coerce").round(2)
        print(cmp.to_string(index=False))
        print()

    # Roster delta: who's in/out
    rb = {r.get("name", "") for r in before.get("roster", [])}
    ra = {r.get("name", "") for r in after.get("roster", [])}
    added = sorted(ra - rb)
    removed = sorted(rb - ra)
    if added or removed:
        print("── Roster delta ──")
        if added:
            print(f"  added:   {', '.join(added)}")
        if removed:
            print(f"  removed: {', '.join(removed)}")
        print()


if __name__ == "__main__":
    main()
