"""Top 10 per position by `<POS>_adj` (scarcity-adjusted WAR), with the
two components broken out: bat (war_hitting / DH_hitting) and fld (the
remainder, = position fielding + positional scarcity adjustment).

By construction:  <pos>_adj  =  bat  +  fld

For DH the `fld` column is just the DH positional adjustment (no defense)
and `bat` already has the DH penalty applied.

Reads `outputs/hitters.json` so it reflects the same data the cascade /
optimizer see. Players whose `<pos>_adj` is NaN at a position (floor
violators) are excluded from that position's ranking.

Run from the project root:
  python -X utf8 calibration/top10_per_pos_adj_split.py
  python -X utf8 calibration/top10_per_pos_adj_split.py --level MLB
  python -X utf8 calibration/top10_per_pos_adj_split.py --org AZ
  python -X utf8 calibration/top10_per_pos_adj_split.py --potential   # use _P columns
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]
HITTERS_JSON = Path("outputs/hitters.json")


def load() -> pd.DataFrame:
    d = json.load(open(HITTERS_JSON))
    return pd.DataFrame(d["rows"], columns=d["columns"])


def bat_col(pos: str, potential: bool) -> str:
    if pos == "DH":
        return "DH_hittingP" if potential else "DH_hitting"
    return "war_hittingP" if potential else "war_hitting"


def adj_col(pos: str, potential: bool) -> str:
    if potential:
        return f"{pos}P_adj"
    return f"{pos}_adj"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", choices=["MLB", "minors", "all"], default="all")
    ap.add_argument("--org", default=None)
    ap.add_argument("--potential", action="store_true",
                    help="use the projected (`<POS>P_adj` / war_hittingP) columns")
    ap.add_argument("--n", type=int, default=10, help="rows per position (default 10)")
    args = ap.parse_args()

    df = load()
    label_bits = []
    if args.level == "MLB":
        df = df[df["minor"] == 0]
        label_bits.append("MLB only")
    elif args.level == "minors":
        df = df[df["minor"] == 1]
        label_bits.append("minors only")
    else:
        label_bits.append("all levels")
    if args.org:
        df = df[df["org"] == args.org]
        label_bits.append(f"org={args.org}")
    if args.potential:
        label_bits.append("PROJECTED")
    else:
        label_bits.append("CURRENT")

    print(f"Top {args.n} per position by {'projected ' if args.potential else ''}"
          f"_adj WAR — {', '.join(label_bits)}  (pool n={len(df)})")
    print("=" * 95)

    for pos in POSITIONS:
        ac = adj_col(pos, args.potential)
        bc = bat_col(pos, args.potential)
        if ac not in df.columns:
            print(f"\n--- {pos}: column {ac} missing, skipping")
            continue

        sub = df.dropna(subset=[ac]).copy()
        sub["_bat"] = sub[bc]
        sub["_fld"] = sub[ac] - sub["_bat"]
        sub = sub.sort_values(ac, ascending=False).head(args.n)

        head = "POTENTIAL" if args.potential else "CURRENT"
        print(f"\n--- TOP {args.n} {pos} ({head} _adj) "
              f"[eligible pool: {df[ac].notna().sum()}]")
        print(f"  {'Player':<24s} {'Org':<4s} {'Age':>3s} {'Lvl':<5s} "
              f"{'bat':>7s} {'fld':>7s} {'_adj':>7s}")
        for _, r in sub.iterrows():
            level = "MLB" if r.get("minor", 1) == 0 else "minor"
            print(f"  {str(r['name'])[:24]:<24s} {str(r['org'])[:4]:<4s} "
                  f"{int(r.get('age', 0)):>3d} {level:<5s} "
                  f"{r['_bat']:>7.2f} {r['_fld']:>7.2f} {r[ac]:>7.2f}")


if __name__ == "__main__":
    main()
