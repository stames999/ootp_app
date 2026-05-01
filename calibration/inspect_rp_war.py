"""inspect_rp_war.py — quick diagnostic of rp_war / sp_war values."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from metrics_pitching import calc_pitching_metrics, calc_potential_pitching_metrics
from reader import (
    add_hitting_career_stats, add_pitching_career_stats, add_scouted_ratings,
    count_pitches, is_flagged, load_players,
)


def main():
    df = load_players()
    df = add_pitching_career_stats(df)
    df = add_hitting_career_stats(df)
    df = add_scouted_ratings(df)
    df = count_pitches(df)
    df = is_flagged(df)
    df = calc_pitching_metrics(df)
    df = calc_potential_pitching_metrics(df)

    print("Role distribution (sprp):")
    print(df["sprp"].value_counts(dropna=False).to_string())
    print()

    rps = df[df["sprp"] == "rp"].copy()
    sps = df[df["sprp"] == "sp"].copy()
    print(f"SPs: {len(sps)}, RPs: {len(rps)}")
    print()

    print("=" * 70)
    print("Top 15 RPs by rp_war:")
    cols = ["name", "org", "ip", "sprp", "stamina", "pitches", "pwOBA", "war_pitching", "sp_war", "rp_war"]
    cols = [c for c in cols if c in rps.columns]
    print(rps.nlargest(15, "rp_war")[cols].to_string(index=False))
    print()

    print("=" * 70)
    print("rp_war distribution (RPs only):")
    print(rps["rp_war"].describe(percentiles=[0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99]).round(3).to_string())
    print()

    print("=" * 70)
    print("Sanity checks:")
    rps_with_zero = (rps["rp_war"] == 0).sum()
    rps_with_nan = rps["rp_war"].isna().sum()
    print(f"  RPs with rp_war == 0:   {rps_with_zero}")
    print(f"  RPs with rp_war NaN:    {rps_with_nan}")
    sps_with_nonzero_rp = (sps["rp_war"].fillna(0) != 0).sum()
    print(f"  SPs with non-zero rp_war: {sps_with_nonzero_rp}")
    print()
    # Spot-check: best rp by pwOBA should be best by rp_war
    rps_sorted_pwoba = rps.sort_values("pwOBA").head(5)[["name", "pwOBA", "rp_war", "war_pitching"]]
    print("Best 5 RPs by pwOBA (lower=better) — should also be best by rp_war:")
    print(rps_sorted_pwoba.to_string(index=False))
    print()

    print("=" * 70)
    print("Top 15 SPs by sp_war (for comparison of magnitude):")
    sp_cols = [c for c in cols if c in sps.columns]
    print(sps.nlargest(15, "sp_war")[sp_cols].to_string(index=False))
    print()

    print("=" * 70)
    print("WORST 10 RPs by rp_war — extreme negatives suggest sub-floor x10 penalty:")
    rating_cols = ["ctrlR", "ctrlL", "pbabipR", "pbabipL", "hraR", "hraL", "stuffR", "stuffL", "stamina"]
    rating_cols = [c for c in rating_cols if c in rps.columns]
    bad_cols = ["name", "org", "ip", "stamina", "pitches", "pwOBA", "rp_war"] + rating_cols
    bad_cols = [c for c in bad_cols if c in rps.columns]
    print(rps.nsmallest(10, "rp_war")[bad_cols].to_string(index=False))
    print()

    print("=" * 70)
    print("SP rp_war distribution (these should arguably show non-zero):")
    print(sps["rp_war"].describe().round(3).to_string())
    print()
    print("RP sp_war distribution:")
    print(rps["sp_war"].describe().round(3).to_string())
    print()

    print("=" * 70)
    print("Top 10 RPs by SP-equivalent WAR (potential stretch-out candidates):")
    rp_cols = [c for c in ["name", "org", "ip", "stamina", "pitches", "sp_war", "rp_war", "pwOBA"] if c in rps.columns]
    print(rps.nlargest(10, "sp_war")[rp_cols].to_string(index=False))
    print()

    print("=" * 70)
    print("Top 10 SPs by RP-equivalent WAR (would they thrive in the pen?):")
    sp_cols2 = [c for c in ["name", "org", "ip", "stamina", "pitches", "sp_war", "rp_war", "pwOBA"] if c in sps.columns]
    print(sps.nlargest(10, "rp_war")[sp_cols2].to_string(index=False))


if __name__ == "__main__":
    main()
