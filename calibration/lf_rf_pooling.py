"""
lf_rf_pooling.py — Test whether RF strictly dominates LF for every hitter.

If LF_def < RF_def for every player (and LF_adj < RF_adj after scarcity),
then LF can never win the `pos_adj` argmax and could be safely pooled
into RF as a single OF/corner-OF position.

Run:
    PYTHONUTF8=1 python -m calibration.lf_rf_pooling
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from config import FIELDING_RUN_VALUES_VS_REPLACEMENT, POSITION_FLOOR
from calibration.compare_adjustments import (
    filter_hitters,
    load_pipeline_df,
    scheme_capped_mean,
)


def main():
    print("Loading and processing pipeline...")
    df = load_pipeline_df()
    hitters = filter_hitters(df)

    # OF eligibility (same rating set for LF/RF — OFrange, OFerror, OFarm).
    of_ratings = list(FIELDING_RUN_VALUES_VS_REPLACEMENT["RF"].keys())
    of_eligible = (hitters[of_ratings].fillna(0) >= POSITION_FLOOR).all(axis=1)
    eligible = hitters[of_eligible]
    print(f"  hitters: {len(hitters)}")
    print(f"  OF-eligible (all OF ratings >= {POSITION_FLOOR}): {len(eligible)}")
    print()

    # Compute current scarcity adjustments (mirror calc_war).
    adj, _ = scheme_capped_mean(hitters)
    adj_LF, adj_RF = adj["LF"], adj["RF"]
    print(f"Current scarcity adjustments: LF +{adj_LF:.2f}, RF +{adj_RF:.2f}")
    print(f"Scarcity gap (RF − LF): +{adj_RF - adj_LF:.2f} WAR — LF needs to beat RF on")
    print(f"raw _def by more than this for LF_adj to win.")
    print()

    # For each player, compute the per-position pre-scarcity gap (LF_def − RF_def)
    # and post-scarcity gap (LF_adj − RF_adj). Same `war_hitting` cancels.
    e = eligible.copy()
    e["lf_minus_rf_def"] = e["LF_def"] - e["RF_def"]
    e["lf_minus_rf_adj"] = e["lf_minus_rf_def"] + (adj_LF - adj_RF)

    n_lf_better_def = int((e["lf_minus_rf_def"] > 0).sum())
    n_lf_better_adj = int((e["lf_minus_rf_adj"] > 0).sum())
    print("Among OF-eligible hitters:")
    print(f"  LF_def > RF_def: {n_lf_better_def} / {len(e)} ({100*n_lf_better_def/len(e):.1f}%)")
    print(f"  LF_adj > RF_adj: {n_lf_better_adj} / {len(e)} ({100*n_lf_better_adj/len(e):.1f}%)")
    print()

    # Distribution of the post-scarcity gap.
    print("Distribution of LF_adj − RF_adj (WAR units), eligible hitters:")
    print(e["lf_minus_rf_adj"].describe(percentiles=[0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99]).round(3).to_string())
    print()

    # If LF ever wins, which players? Show the top 10 by LF_adj edge.
    if n_lf_better_adj > 0:
        print("Top 10 hitters where LF_adj beats RF_adj:")
        cols = ["name", "OFrange", "OFerror", "OFarm", "LF_def", "RF_def", "lf_minus_rf_def", "lf_minus_rf_adj"]
        cols = [c for c in cols if c in e.columns]
        top = e.nlargest(10, "lf_minus_rf_adj")[cols]
        print(top.to_string(index=False))
    else:
        print("No OF-eligible hitter has LF_adj > RF_adj — RF strictly dominates LF after scarcity.")

    # Also: among players whose `pos_adj` is currently LF (i.e. LF is their best
    # adjusted position), does RF also beat all other positions for them? If so,
    # pooling LF→RF would give them the same answer (just relabeled).
    if "pos_adj" in df.columns:
        pos_adj_dist = df["pos_adj"].value_counts(dropna=False)
        print()
        print("Current `pos_adj` distribution (informational):")
        print(pos_adj_dist.to_string())


if __name__ == "__main__":
    main()
