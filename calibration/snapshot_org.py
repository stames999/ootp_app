"""
snapshot_org.py — capture build_roster_constrained_plan output to JSON for
before/after comparison.

Usage:
    PYTHONUTF8=1 python -m calibration.snapshot_org [outfile]
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from config import team_managed
from metrics_fielding import calc_fielding_metrics
from metrics_hitting import calc_hitting_metrics, calc_potential_hitting_metrics
from metrics_pitching import calc_pitching_metrics, calc_potential_pitching_metrics
from metrics_war import calc_war
from org_report import build_roster_constrained_plan
from reader import (
    add_hitting_career_stats, add_pitching_career_stats, add_scouted_ratings,
    count_pitches, is_flagged, load_players,
)


def df_to_records(df):
    if df is None or df.empty:
        return []
    safe = df.copy()
    for col in safe.columns:
        if pd.api.types.is_float_dtype(safe[col]):
            safe[col] = safe[col].astype(object).where(safe[col].notna(), None)
    return safe.to_dict(orient="records")


def main():
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "org_snapshot.json"

    df = load_players()
    df = add_pitching_career_stats(df)
    df = add_hitting_career_stats(df)
    df = add_scouted_ratings(df)
    df = count_pitches(df)
    df = is_flagged(df)
    df = calc_pitching_metrics(df)
    df = calc_potential_pitching_metrics(df)
    df = calc_hitting_metrics(df)
    df = calc_potential_hitting_metrics(df)
    df = calc_fielding_metrics(df)
    df = calc_war(df)

    plan = build_roster_constrained_plan(df, org_abbr=team_managed)

    payload = {
        "org": plan.org,
        "lineup_war_r": plan.lineup_war_r,
        "lineup_war_l": plan.lineup_war_l,
        "runs_pg_r": plan.runs_pg_r if pd.notna(plan.runs_pg_r) else None,
        "runs_pg_l": plan.runs_pg_l if pd.notna(plan.runs_pg_l) else None,
        "lineup_r": df_to_records(plan.lineup_r),
        "lineup_l": df_to_records(plan.lineup_l),
        "order_r": df_to_records(plan.order_r),
        "order_l": df_to_records(plan.order_l),
        "roster": df_to_records(plan.roster),
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    print(f"Snapshot → {out_path}")
    print(f"  org: {plan.org}")
    print(f"  lineup_war_r: {plan.lineup_war_r:.2f}    runs_pg_r: {plan.runs_pg_r:.2f}")
    print(f"  lineup_war_l: {plan.lineup_war_l:.2f}    runs_pg_l: {plan.runs_pg_l:.2f}")


if __name__ == "__main__":
    main()
