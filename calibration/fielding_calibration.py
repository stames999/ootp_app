"""Fielding-table calibration: align sim per-position fielding ceilings
to FanGraphs 2025 FRV.

For each position:
  - FG target: mean(top 5 by FRV per-162) among players with Inn >= 500
  - Sim current: mean(top 5 by <pos>_def converted to runs) among
                 natural-position MLB players
  - Multiplier: target / current
  - To apply: multiply every entry in
      FIELDING_RUN_VALUES_VS_REPLACEMENT[pos]
    by multiplier[pos]. For 2B/3B/SS, also multiply every value in
      FIELDING_SATURATION[pos]
    by multiplier[pos] (preserves the tanh shape exactly — output = k *
    old_output when both input table AND ceil/scale params scale by k).

Default behaviour is DRY-RUN: prints multipliers, shows top players on
each side, saves a JSON with the proposed new tables. The user inspects
the JSON, then a follow-up step applies the new tables to config.py.

  python -X utf8 calibration/fielding_calibration.py            # dry-run
  python -X utf8 calibration/fielding_calibration.py --top-n 10 # change N
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

# Positions to calibrate (DH has no fielding). 1B included but flagged
# separately because its variance is tiny by design and multipliers may
# be unstable.
POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
OOTP_POS_CODE = {"C": 2, "1B": 3, "2B": 4, "3B": 5, "SS": 6,
                 "LF": 7, "CF": 8, "RF": 9}

FG_DIR = Path("calibration/fg_2025")
OUT_JSON = Path("outputs/fielding_calibration_proposal.json")

# Pro-rate FG players' FRV to a 162-game-equivalent season.
# 162 games × 9 innings = 1458 innings of full-season defensive workload.
FULL_SEASON_INN = 162 * 9

# Filter FG samples to at least this many innings to avoid noise from
# tiny-sample appearances at a position.
INN_THRESHOLD = 500

# Floor for sim's top-N mean. If sim's elite cohort is below this many
# runs, the multiplier denominator is too small to be reliable — skip.
SIM_MIN_TOP_N = 1.0  # runs


def fg_top_n(pos: str, top_n: int) -> dict | None:
    af_path = FG_DIR / f"{pos}_adv_fielding.csv"
    if not af_path.exists():
        return None
    df = pd.read_csv(af_path)
    if "FRV" not in df.columns or "Inn" not in df.columns:
        return None
    df = df[df["Inn"] >= INN_THRESHOLD].copy()
    if df.empty:
        return None
    # Per-162 pro-ration: FRV * (1458 / Inn). Players with full-season
    # innings are unaffected; partial-season elites get scaled up.
    df["FRV_162"] = df["FRV"] * FULL_SEASON_INN / df["Inn"]
    df = df.dropna(subset=["FRV_162"])
    if len(df) < top_n:
        return None
    top = df.nlargest(top_n, "FRV_162")
    return {
        "n_eligible": int(len(df)),
        "top_n_mean": float(top["FRV_162"].mean()),
        "top_n_players": top[["Name", "Team", "Inn", "FRV", "FRV_162"]]
            .to_dict(orient="records"),
        "pool_max": float(df["FRV_162"].max()),
        "pool_p95": float(df["FRV_162"].quantile(0.95)),
        "pool_p99": float(df["FRV_162"].quantile(0.99)),
    }


def sim_top_n(df_sim: pd.DataFrame, pos: str, top_n: int) -> dict | None:
    code = OOTP_POS_CODE[pos]
    sub = df_sim[(df_sim["minor"] == 0) & (df_sim["position"] == code)].copy()
    col = f"{pos}_def"
    if col not in sub.columns:
        return None
    sub["_fld_runs"] = sub[col] * config.RUNS_PER_WIN_FIELDING
    sub = sub.dropna(subset=["_fld_runs"])
    if len(sub) < top_n:
        return None
    top = sub.nlargest(top_n, "_fld_runs")
    return {
        "n_eligible": int(len(sub)),
        "top_n_mean": float(top["_fld_runs"].mean()),
        "top_n_players": top[["name", "_fld_runs"]]
            .rename(columns={"_fld_runs": "fld_runs"})
            .to_dict(orient="records"),
        "pool_max": float(sub["_fld_runs"].max()),
        "pool_p95": float(sub["_fld_runs"].quantile(0.95)),
        "pool_p99": float(sub["_fld_runs"].quantile(0.99)),
    }


def build_proposal(top_n: int) -> dict:
    print("Regenerating sim df via main.compute_df()...")
    df_sim = load_floored_df()
    print(f"Position-player pool: n = {len(df_sim)}")
    print()

    proposal = {"top_n": top_n, "inn_threshold": INN_THRESHOLD,
                "positions": {}}

    for pos in POSITIONS:
        fg = fg_top_n(pos, top_n)
        sim = sim_top_n(df_sim, pos, top_n)

        entry = {"fg": fg, "sim": sim, "multiplier": None,
                 "reason_skipped": None}

        if fg is None:
            entry["reason_skipped"] = "no FG data"
        elif sim is None:
            entry["reason_skipped"] = "no sim data"
        elif sim["top_n_mean"] < SIM_MIN_TOP_N:
            entry["reason_skipped"] = (
                f"sim top-{top_n} mean too small ({sim['top_n_mean']:.2f} < "
                f"{SIM_MIN_TOP_N}) — multiplier would be unreliable"
            )
        else:
            entry["multiplier"] = fg["top_n_mean"] / sim["top_n_mean"]

        # Compute the new top-N target for sanity:
        # if multiplier applied, sim_new_top_n_mean = sim_top_n_mean * mult = fg_top_n_mean
        if entry["multiplier"] is not None and sim is not None:
            entry["sim_after_calibration_top_n_mean_est"] = (
                sim["top_n_mean"] * entry["multiplier"]
            )

        proposal["positions"][pos] = entry

    return proposal


def print_proposal(p: dict) -> None:
    print(f"=== Fielding calibration proposal (top-{p['top_n']} cohort) ===")
    print(f"FG inn threshold: {p['inn_threshold']}, "
          f"runs/win (fielding): {config.RUNS_PER_WIN_FIELDING}")
    print()
    print(f"  {'Pos':<5s} {'FG_top5':>9s} {'Sim_top5':>10s} "
          f"{'Mult':>8s} {'FG_n':>5s} {'Sim_n':>5s}  {'Status':<40s}")
    for pos, e in p["positions"].items():
        fg_top = e["fg"]["top_n_mean"] if e["fg"] else float("nan")
        sim_top = e["sim"]["top_n_mean"] if e["sim"] else float("nan")
        fg_n = e["fg"]["n_eligible"] if e["fg"] else 0
        sim_n = e["sim"]["n_eligible"] if e["sim"] else 0
        m = e["multiplier"]
        status = e["reason_skipped"] or "OK"
        m_str = f"{m:.3f}" if m is not None else "—"
        print(f"  {pos:<5s} {fg_top:>9.2f} {sim_top:>10.2f} "
              f"{m_str:>8s} {fg_n:>5d} {sim_n:>5d}  {status:<40s}")

    print()
    print("Per-position elite cohort detail:")
    for pos, e in p["positions"].items():
        if not e["fg"] or not e["sim"]:
            continue
        print(f"\n  [{pos}]")
        print(f"    FG top 5 (Inn >= {p['inn_threshold']}, FRV per-162):")
        for r in e["fg"]["top_n_players"]:
            print(f"      {r['Name']:<26s} {r['Team']:<6s} "
                  f"Inn={r['Inn']:>6.1f}  FRV={r['FRV']:>5.1f}  "
                  f"FRV_162={r['FRV_162']:>6.2f}")
        print(f"    Sim top 5 (natural-position MLB, _def x 9.53 runs):")
        for r in e["sim"]["top_n_players"]:
            print(f"      {r['name']:<26s} {' '*7}                  "
                  f"     fld_runs={r['fld_runs']:>6.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-n", type=int, default=5,
                    help="size of the elite cohort to calibrate against")
    args = ap.parse_args()

    proposal = build_proposal(args.top_n)
    print_proposal(proposal)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(proposal, f, indent=2, default=str)
    print(f"\nSaved proposal: {OUT_JSON.resolve()}")
    print()
    print("DRY-RUN ONLY. No config.py changes made.")
    print("If the multipliers look right, run the apply step "
          "(separate command, to be added).")


if __name__ == "__main__":
    main()
