"""Step-2 fielding calibration: drive the residual p0.999 gap to zero
on top of the step-1 (top-10 mean) multipliers.

After step-1, several positions still have nonzero Δ_fld at p0.999 of
the MLB-natural-position pool — the top-10 mean fit matches the elite
cohort *average* but the tip of the distribution drifts. This script
computes a small residual multiplier per position to close that p0.999
gap directly.

Method (per position):
  1. FG target = max of FG `Fielding` column (in runs) from
     `<POS>_batting_value.csv`. This is the same metric the gap report
     uses (FG_fld_max).
  2. Sim current = p0.999 of `<pos>_def` for MLB-natural-position
     players, converted to runs via `× RUNS_PER_WIN_FIELDING`.
  3. residual_multiplier = FG_target / sim_current.
  4. Writes the multipliers into the standard proposal JSON so the
     existing `apply_fielding_calibration.py` script can apply them
     on top of the current (post-step-1) tables.

  python -X utf8 calibration/fielding_calibration_step2.py            # dry-run
  python -X utf8 calibration/apply_fielding_calibration.py --apply    # apply
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

import config
from calibration.war_dist_per_pos import load_floored_df

POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
OOTP_POS_CODE = {"C": 2, "1B": 3, "2B": 4, "3B": 5, "SS": 6,
                 "LF": 7, "CF": 8, "RF": 9}

FG_DIR = Path("calibration/fg_2025")
OUT_JSON = Path("outputs/fielding_calibration_proposal.json")

# Floor for sim's p0.999 in runs. Below this, the multiplier denominator
# is too small to be reliable.
SIM_MIN_P999 = 0.5  # runs

# Damping factor — pull multiplier toward 1.0 by this fraction to avoid
# overshooting again. 1.0 = full correction; 0.5 = half-step.
DEFAULT_DAMP = 1.0


def fg_target(pos: str) -> dict | None:
    """Match what the gap report uses: max of FG Fielding column (runs)."""
    bv_path = FG_DIR / f"{pos}_batting_value.csv"
    if not bv_path.exists():
        return None
    bv = pd.read_csv(bv_path)
    if "Fielding" not in bv.columns:
        return None
    fld = bv["Fielding"].dropna()
    if fld.empty:
        return None
    name_col = "Name" if "Name" in bv.columns else None
    top_row = bv.loc[fld.idxmax()] if name_col else None
    return {
        "fg_fld_max_runs": float(fld.max()),
        "top_player": str(top_row[name_col]) if top_row is not None and name_col else "",
        "n": int(len(bv)),
    }


def sim_current(df: pd.DataFrame, pos: str) -> dict | None:
    code = OOTP_POS_CODE[pos]
    sub = df[(df["minor"] == 0) & (df["position"] == code)]
    col = f"{pos}_def"
    if col not in sub.columns:
        return None
    values = sub[col].dropna()
    if values.empty:
        return None
    p999_war = float(values.quantile(0.999))
    p999_runs = p999_war * config.RUNS_PER_WIN_FIELDING
    return {
        "p999_war": p999_war,
        "p999_runs": p999_runs,
        "n": int(len(sub)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--damp", type=float, default=DEFAULT_DAMP,
                    help="multiplier damping (1.0=full, 0.5=half). "
                         "Lower values pull toward no change.")
    args = ap.parse_args()

    print("Regenerating sim df via main.compute_df()...")
    df_sim = load_floored_df()
    print(f"Pool: n = {len(df_sim)}")
    print()

    proposal = {"top_n": "p0.999", "method": "step-2 residual to FG Fielding max",
                "damp": args.damp, "positions": {}}

    print(f"  {'Pos':<5s} {'FG_fld_max':>12s} {'Sim_p999_runs':>15s} "
          f"{'Residual':>10s} {'Damped':>10s}  {'FG top':<22s} {'Sim n':>6s}")
    for pos in POSITIONS:
        fg = fg_target(pos)
        sim = sim_current(df_sim, pos)
        entry = {"fg": fg, "sim": sim, "multiplier": None,
                 "reason_skipped": None}
        if fg is None:
            entry["reason_skipped"] = "no FG data"
        elif sim is None:
            entry["reason_skipped"] = "no sim data"
        elif abs(sim["p999_runs"]) < SIM_MIN_P999:
            entry["reason_skipped"] = (
                f"sim p0.999 too close to zero ({sim['p999_runs']:.2f}) — "
                "multiplier unreliable"
            )
        else:
            raw = fg["fg_fld_max_runs"] / sim["p999_runs"]
            # Apply damping
            damped = 1.0 + (raw - 1.0) * args.damp
            entry["multiplier_raw"] = raw
            entry["multiplier"] = damped

        proposal["positions"][pos] = entry

        fg_val = fg["fg_fld_max_runs"] if fg else float("nan")
        sim_val = sim["p999_runs"] if sim else float("nan")
        sim_n = sim["n"] if sim else 0
        fg_top = fg["top_player"] if fg else ""
        raw = entry.get("multiplier_raw", float("nan"))
        damped = entry["multiplier"] if entry["multiplier"] is not None else float("nan")

        def fmt(v): return f"{v:.3f}" if pd.notna(v) else "—"
        print(f"  {pos:<5s} {fg_val:>12.2f} {sim_val:>15.2f} "
              f"{fmt(raw):>10s} {fmt(damped):>10s}  {fg_top:<22s} {sim_n:>6d}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(proposal, f, indent=2, default=str)

    print(f"\nSaved proposal: {OUT_JSON.resolve()}")
    print("DRY-RUN. Apply with: "
          "python -X utf8 calibration/apply_fielding_calibration.py --apply")


if __name__ == "__main__":
    main()
