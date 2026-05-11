"""FanGraphs 2025 per-position reference ceilings.

Reads any single-position FanGraphs CSV pairs under `calibration/fg_2025/`:
  - `<POS>_batting_value.csv`  — Batting / Base Running / Fielding /
                                  Positional / Offense / Defense / RAR / WAR
  - `<POS>_adv_fielding.csv`   — DRS components, FRM, OAA, FRV, Def

For each position present, computes max / p0.999 / p0.99 / mean / n of the
relevant columns and writes a structured JSON to
`outputs/fg_2025_pos_ceilings.json` for the gap-report script to consume.

Runs are converted to WAR via FG's empirically-derived 2025 RPW (≈9.77):
verified against Raleigh's row (RAR 83.82 / WAR 8.58 = 9.77).

Per-position files are dropped in incrementally — the script processes
whatever is present. Run:

    python -X utf8 calibration/fg_2025_reference.py
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

FG_DIR = Path("calibration/fg_2025")
OUT_JSON = Path("outputs/fg_2025_pos_ceilings.json")

# Empirically derived from Raleigh 2025 (RAR=83.82 / WAR=8.58 = 9.77).
# Use this consistently for the run→WAR conversion across all columns.
RPW = 9.77

POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]

# Columns in <POS>_batting_value.csv that we care about (all in runs except WAR)
BATTING_VALUE_COLS = [
    "Batting", "Base Running", "Fielding", "Positional",
    "Offense", "Defense", "League", "Replacement", "RAR", "WAR",
]

# Columns in <POS>_adv_fielding.csv (DRS / Statcast / FG framing)
ADV_FIELDING_COLS = ["DRS", "FRM", "OAA", "FRV", "Def"]


def summarize(series: pd.Series) -> dict:
    s = series.dropna()
    if s.empty:
        return {"n": 0}
    return {
        "n": int(s.size),
        "max": float(s.max()),
        "p0_999": float(s.quantile(0.999)),
        "p0_99": float(s.quantile(0.99)),
        "p0_95": float(s.quantile(0.95)),
        "mean": float(s.mean()),
    }


def summarize_position(pos: str) -> dict | None:
    bv_path = FG_DIR / f"{pos}_batting_value.csv"
    af_path = FG_DIR / f"{pos}_adv_fielding.csv"
    if not bv_path.exists():
        return None

    out = {"position": pos, "rpw": RPW, "n_batting_rows": 0,
           "n_fielding_rows": 0, "batting_value": {}, "adv_fielding": {}}

    bv = pd.read_csv(bv_path)
    out["n_batting_rows"] = len(bv)
    for col in BATTING_VALUE_COLS:
        if col in bv.columns:
            stats = summarize(bv[col])
            # Convert runs to WAR for all components except WAR (already WAR).
            if col != "WAR" and stats.get("n", 0) > 0:
                stats["war_units"] = {
                    "max": stats["max"] / RPW,
                    "p0_999": stats["p0_999"] / RPW,
                    "p0_99": stats["p0_99"] / RPW,
                    "mean": stats["mean"] / RPW,
                }
            out["batting_value"][col] = stats

    if af_path.exists():
        af = pd.read_csv(af_path)
        out["n_fielding_rows"] = len(af)
        for col in ADV_FIELDING_COLS:
            if col in af.columns:
                stats = summarize(af[col])
                if stats.get("n", 0) > 0:
                    stats["war_units"] = {
                        "max": stats["max"] / RPW,
                        "p0_999": stats["p0_999"] / RPW,
                        "p0_99": stats["p0_99"] / RPW,
                        "mean": stats["mean"] / RPW,
                    }
                out["adv_fielding"][col] = stats

    # Top-5 leaders by Batting, Fielding, WAR — for quick spot-checking
    name_col = "Name" if "Name" in bv.columns else None
    if name_col:
        leaders = {}
        for sort_col in ("Batting", "Fielding", "Defense", "WAR"):
            if sort_col in bv.columns:
                top = (bv[[name_col, "Team", sort_col]]
                       .dropna()
                       .sort_values(sort_col, ascending=False)
                       .head(5)
                       .to_dict(orient="records"))
                leaders[sort_col] = top
        out["leaders"] = leaders

    return out


def print_position(summary: dict) -> None:
    pos = summary["position"]
    print(f"\n{'=' * 80}")
    print(f"  {pos}  (batting rows: {summary['n_batting_rows']}, "
          f"adv-fielding rows: {summary['n_fielding_rows']})")
    print(f"{'=' * 80}")

    bv = summary["batting_value"]
    print("\n  Batting value (FG 2025 — runs except WAR):")
    print(f"  {'column':<14s} {'n':>4s} {'max':>8s} {'p0.999':>8s} "
          f"{'p0.99':>8s} {'mean':>8s}  | {'max_WAR':>8s} {'p0.999_WAR':>10s}")
    for col in BATTING_VALUE_COLS:
        s = bv.get(col, {})
        if not s or s.get("n", 0) == 0:
            continue
        w = s.get("war_units", {})
        wmax = w.get("max", s.get("max", 0) if col == "WAR" else 0)
        wp999 = w.get("p0_999", s.get("p0_999", 0) if col == "WAR" else 0)
        print(f"  {col:<14s} {s['n']:>4d} {s['max']:>8.2f} {s['p0_999']:>8.2f} "
              f"{s['p0_99']:>8.2f} {s['mean']:>8.2f}  | {wmax:>8.2f} {wp999:>10.2f}")

    af = summary["adv_fielding"]
    if af:
        print("\n  Advanced fielding (FG 2025 — runs):")
        print(f"  {'column':<8s} {'n':>4s} {'max':>8s} {'p0.999':>8s} "
              f"{'p0.99':>8s} {'mean':>8s}  | {'max_WAR':>8s} {'p0.999_WAR':>10s}")
        for col in ADV_FIELDING_COLS:
            s = af.get(col, {})
            if not s or s.get("n", 0) == 0:
                continue
            w = s.get("war_units", {})
            print(f"  {col:<8s} {s['n']:>4d} {s['max']:>8.2f} {s['p0_999']:>8.2f} "
                  f"{s['p0_99']:>8.2f} {s['mean']:>8.2f}  | "
                  f"{w['max']:>8.2f} {w['p0_999']:>10.2f}")

    leaders = summary.get("leaders", {})
    if leaders:
        for col, rows in leaders.items():
            if not rows:
                continue
            print(f"\n  Top 5 by {col}:")
            for r in rows:
                name = str(r.get("Name", ""))[:25]
                team = str(r.get("Team", ""))[:6]
                val = r.get(col, 0)
                print(f"    {name:<25s} {team:<6s} {val:>8.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--positions", nargs="*", default=POSITIONS,
                    help="positions to process (default: all 9)")
    args = ap.parse_args()

    all_summaries = {}
    for pos in args.positions:
        s = summarize_position(pos)
        if s is None:
            continue
        all_summaries[pos] = s
        print_position(s)

    if not all_summaries:
        print(f"No FG CSVs found under {FG_DIR}/. Expected <POS>_batting_value.csv "
              f"and <POS>_adv_fielding.csv. Run aborted.")
        sys.exit(1)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(all_summaries, f, indent=2, default=str)
    print(f"\nSaved: {OUT_JSON.resolve()}")
    print(f"Positions processed: {', '.join(all_summaries)}")
    print(f"RPW used for runs→WAR conversion: {RPW}")


if __name__ == "__main__":
    main()
