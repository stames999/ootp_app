"""Calibrate POSITIONAL_ADJUSTMENT_RUNS so each position's top-5 mean
`<pos>_adj` matches FG's top-5 mean WAR at that position.

The sim engine's fielding tables (FIELDING_RUN_VALUES_VS_REPLACEMENT)
are preserved exactly — those came from team-of-clones experiments and
represent measured OOTP behavior. Only the per-position positional
constant is shifted, which moves the whole position's distribution by a
single number without distorting within-position rankings or shapes.

Procedure (per position):
  1. FG target = mean of top-5 WAR from `<POS>_batting_value.csv`
  2. Sim current = mean of top-5 `<pos>_adj` from natural-position MLB pool
  3. delta_WAR = FG_target - sim_current
  4. new pos_adj_runs = old pos_adj_runs + delta_WAR × RUNS_PER_WIN_FIELDING

Output:
  - Prints the per-position table
  - Writes the new POSITIONAL_ADJUSTMENT_RUNS dict to console (ready to
    paste into config.py)
  - Optionally edits config.py in place with --apply

  python -X utf8 calibration/posadj_shift_calibration.py            # dry-run
  python -X utf8 calibration/posadj_shift_calibration.py --apply    # write config.py
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

import config
from calibration.war_dist_per_pos import load_floored_df

POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]
OOTP_POS_CODE = {"C": 2, "1B": 3, "2B": 4, "3B": 5, "SS": 6,
                 "LF": 7, "CF": 8, "RF": 9, "DH": 10}

FG_DIR = Path("calibration/fg_2025")
CONFIG_PY = _ROOT / "config.py"
TOP_N = 5


def fg_top_n_war(pos: str) -> float | None:
    """Top-N mean of the WAR column in FG's <POS>_batting_value.csv."""
    bv_path = FG_DIR / f"{pos}_batting_value.csv"
    if not bv_path.exists():
        return None
    bv = pd.read_csv(bv_path)
    if "WAR" not in bv.columns:
        return None
    war = bv["WAR"].dropna()
    if len(war) < TOP_N:
        return None
    return float(war.nlargest(TOP_N).mean())


def sim_top_n_adj(df: pd.DataFrame, pos: str) -> float | None:
    """Top-N mean of <pos>_adj for natural-position MLB players in sim."""
    code = OOTP_POS_CODE[pos]
    sub = df[(df["minor"] == 0) & (df["position"] == code)]
    col = f"{pos}_adj"
    if col not in sub.columns:
        return None
    values = sub[col].dropna()
    if len(values) < TOP_N:
        return None
    return float(values.nlargest(TOP_N).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually edit config.py POSITIONAL_ADJUSTMENT_RUNS")
    args = ap.parse_args()

    print("Regenerating sim df via main.compute_df()...")
    df = load_floored_df()
    print(f"Pool: n = {len(df)}")
    print()

    rpw = config.RUNS_PER_WIN_FIELDING
    current = dict(config.POSITIONAL_ADJUSTMENT_RUNS)
    new_pos_adj = {}

    print(f"  {'Pos':<5s} {'FG_top5_WAR':>13s} {'Sim_top5_adj':>14s} "
          f"{'Δ_WAR':>8s} {'Δ_runs':>9s} {'old_pos_adj':>13s} {'new_pos_adj':>13s}")
    print("  " + "-" * 88)
    for pos in POSITIONS:
        fg = fg_top_n_war(pos)
        sim = sim_top_n_adj(df, pos)
        old_pos = current.get(pos, 0.0)
        if fg is None or sim is None:
            new_pos_adj[pos] = old_pos
            print(f"  {pos:<5s} {'—':>13s} {'—':>14s} {'—':>8s} {'—':>9s} "
                  f"{old_pos:>13.2f} {old_pos:>13.2f}  (skipped)")
            continue
        delta_war = fg - sim
        delta_runs = delta_war * rpw
        new_pos = old_pos + delta_runs
        new_pos_adj[pos] = round(new_pos, 1)
        print(f"  {pos:<5s} {fg:>13.2f} {sim:>14.2f} {delta_war:>+8.2f} "
              f"{delta_runs:>+9.2f} {old_pos:>13.2f} {new_pos_adj[pos]:>13.2f}")

    # Format as Python source for config.py
    print()
    print("Proposed POSITIONAL_ADJUSTMENT_RUNS:")
    print("POSITIONAL_ADJUSTMENT_RUNS = {")
    for pos in POSITIONS:
        v = new_pos_adj[pos]
        print(f'    "{pos}": {v:>7.1f},')
    print("}")

    if not args.apply:
        print("\nDRY-RUN. Re-run with --apply to write config.py.")
        return

    # Apply edit
    text = CONFIG_PY.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # Find the POSITIONAL_ADJUSTMENT_RUNS block
    start = None
    for i, l in enumerate(lines):
        if l.startswith("POSITIONAL_ADJUSTMENT_RUNS = {"):
            start = i
            break
    if start is None:
        raise SystemExit("POSITIONAL_ADJUSTMENT_RUNS not found in config.py")
    end = None
    for i in range(start + 1, len(lines)):
        if lines[i].rstrip() == "}":
            end = i
            break
    if end is None:
        raise SystemExit("Closing brace for POSITIONAL_ADJUSTMENT_RUNS not found")

    # Backup
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = CONFIG_PY.with_suffix(f".py.bak.{ts}")
    shutil.copy(CONFIG_PY, backup)
    print(f"\nBacked up to: {backup.name}")

    # Replace block — preserve any inline header comment before the dict
    # by only replacing from POSITIONAL_ADJUSTMENT_RUNS = { through the
    # next standalone }.
    new_block = ["POSITIONAL_ADJUSTMENT_RUNS = {\n"]
    new_block.append("    # Calibrated per-position to align sim top-5 mean `<pos>_adj`\n")
    new_block.append("    # with FG 2025 top-5 mean WAR per position. The sim engine's\n")
    new_block.append("    # fielding tables (FIELDING_RUN_VALUES_VS_REPLACEMENT) are left\n")
    new_block.append("    # untouched — they encode team-of-clones measurements and shouldn't\n")
    new_block.append("    # be reshaped. Per-position positional constants are the\n")
    new_block.append("    # appropriate calibration knob: each one shifts the whole position's\n")
    new_block.append("    # WAR distribution by a constant, preserving within-position ranking\n")
    new_block.append("    # and shape. Pos_adj here is therefore a CALIBRATION constant, not\n")
    new_block.append("    # the FG-standard scarcity convention (which we deviate from).\n")
    for pos in POSITIONS:
        v = new_pos_adj[pos]
        new_block.append(f'    "{pos}": {v:>7.1f},\n')
    new_block.append("}\n")

    lines[start:end + 1] = new_block
    CONFIG_PY.write_text("".join(lines), encoding="utf-8")
    print(f"Wrote new {CONFIG_PY.name}")


if __name__ == "__main__":
    main()
