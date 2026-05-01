"""
skill_aware_adj.py — compare flat mean-shift scarcity (current production)
to a per-player skill-aware adjustment that scales with the player's rank
within the eligible pool.

Two skill-aware schemes:
  P: percentile-scaled — bonus = scarcity * (1 + gamma*(pct/50 - 1))
     Preserves the eligible-pool mean (= flat scarcity constant) by
     construction, so cross-position calibration stays anchored. Robust to
     small pools (no variance blowup; rank-based).

  Z: capped z-score — bonus = scarcity + beta * stdev_baseline * clip(z, ±zmax)
     Uses eligible-pool mean+stdev consistently (the prior failed attempt
     mixed all-hitters mean with eligible-pool stdev). Caps z to bound the
     bonus and avoid extreme outliers. stdev_baseline is a fixed per-pos
     anchor (median eligible-pool stdev across positions) so tight catcher
     pools don't get amplified relative to wide CF pools.

Run: PYTHONUTF8=1 python -m calibration.skill_aware_adj
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from config import (
    FIELDING_RUN_VALUES_VS_REPLACEMENT,
    POSITION_ADJ_REFERENCE,
    POSITION_FLOOR,
    POSITION_FLOOR_EXEMPT,
)
from calibration.compare_adjustments import (
    filter_hitters,
    load_pipeline_df,
    scheme_capped_mean,
)

POSITIONS = ["C", "CF", "RF", "LF", "SS", "2B", "3B", "1B"]
GAMMA = 0.5      # percentile-scheme spread
BETA = 0.5       # z-scheme scale
Z_CAP = 2.0      # clip z to ±this


def eligible_mask(hitters, pos):
    if pos in POSITION_FLOOR_EXEMPT:
        return pd.Series(True, index=hitters.index)
    ratings = FIELDING_RUN_VALUES_VS_REPLACEMENT.get(pos, {})
    relevant = [c for c in ratings.keys() if c in hitters.columns]
    if not relevant:
        return pd.Series(True, index=hitters.index)
    return (hitters[relevant].fillna(0) >= POSITION_FLOOR).all(axis=1)


def percentile_bonus(elig_def, scarcity, gamma=GAMMA):
    """bonus = scarcity * (1 + gamma * (pct/50 - 1)). Mean-preserving by construction."""
    if len(elig_def) == 0:
        return pd.Series(dtype=float)
    pct = elig_def.rank(pct=True) * 100.0
    return scarcity * (1.0 + gamma * (pct / 50.0 - 1.0))


def zscore_bonus(elig_def, scarcity, stdev_baseline, beta=BETA, zcap=Z_CAP):
    """bonus = scarcity + beta * stdev_baseline * clip(z_eligible, ±zcap)."""
    if len(elig_def) <= 1:
        return pd.Series(scarcity, index=elig_def.index)
    mu = elig_def.mean()
    sd = elig_def.std(ddof=0)
    if sd <= 0:
        return pd.Series(scarcity, index=elig_def.index)
    z = ((elig_def - mu) / sd).clip(-zcap, zcap)
    return scarcity + beta * stdev_baseline * z


def main():
    print("Loading pipeline...")
    df = load_pipeline_df()
    hitters = filter_hitters(df)
    print(f"  hitters: {len(hitters)}")

    # Flat scarcity constants from current production scheme.
    flat_adj, _ = scheme_capped_mean(hitters)

    # Eligible-pool stdevs per position (used as z-score baseline).
    elig_stdev = {}
    for pos in POSITIONS:
        m = eligible_mask(hitters, pos)
        elig_stdev[pos] = float(hitters.loc[m, f"{pos}_def"].std(ddof=0))
    # Use the median eligible-pool stdev as a shared baseline for the z-scheme,
    # so tight pools (catchers) don't get a bigger bonus per unit of skill.
    stdev_baseline = float(np.median(list(elig_stdev.values())))
    print(f"\nEligible-pool stdevs of <pos>_def (WAR units):")
    for p, s in elig_stdev.items():
        print(f"  {p}: {s:.2f}")
    print(f"  baseline (median): {stdev_baseline:.2f}")

    # Per-pos summary of all three schemes.
    print()
    print(f"=== Bonus distribution per position (gamma={GAMMA}, beta={BETA}, z_cap=±{Z_CAP}) ===")
    summary_rows = []
    elig_data = {}
    for pos in POSITIONS:
        scarcity = flat_adj[pos]
        m = eligible_mask(hitters, pos)
        elig = hitters[m].copy()
        elig_def = elig[f"{pos}_def"]
        elig_data[pos] = (elig, elig_def)

        flat = pd.Series(scarcity, index=elig.index)
        pct_b = percentile_bonus(elig_def, scarcity)
        z_b = zscore_bonus(elig_def, scarcity, stdev_baseline)

        for scheme_name, series in (("F: flat", flat), ("P: percentile", pct_b), ("Z: z-score", z_b)):
            summary_rows.append({
                "pos": pos,
                "scheme": scheme_name,
                "n": len(series),
                "min": round(series.min(), 2),
                "p10": round(series.quantile(0.10), 2),
                "p50": round(series.quantile(0.50), 2),
                "p90": round(series.quantile(0.90), 2),
                "max": round(series.max(), 2),
                "mean": round(series.mean(), 2),
                "spread": round(series.max() - series.min(), 2),
            })
    summary = pd.DataFrame(summary_rows)
    print(summary.to_string(index=False))

    # Specific players: top / p75 / median / p25 / bottom at each scarce pos.
    print()
    print("=== Example players at each position (showing skill-aware nuance) ===")
    examples = []
    scarce_positions = ["C", "SS", "CF", "3B", "2B", "RF", "LF"]
    for pos in scarce_positions:
        elig, elig_def = elig_data[pos]
        if len(elig) == 0:
            continue
        scarcity = flat_adj[pos]
        pct = elig_def.rank(pct=True) * 100.0
        pct_b = percentile_bonus(elig_def, scarcity)
        z_b = zscore_bonus(elig_def, scarcity, stdev_baseline)

        elig_view = elig.copy()
        elig_view["pos_def"] = elig_def
        elig_view["pct"] = pct
        elig_view["flat"] = scarcity
        elig_view["pctile_bonus"] = pct_b
        elig_view["z_bonus"] = z_b

        for label, target in [("top1%", 99), ("p90", 90), ("p50", 50), ("p10", 10), ("bot1%", 1)]:
            idx = (elig_view["pct"] - target).abs().idxmin()
            r = elig_view.loc[idx]
            examples.append({
                "pos": pos,
                "tier": label,
                "name": r.get("name", "")[:22],
                "pos_def": round(r["pos_def"], 2),
                "pct": round(r["pct"], 1),
                "flat": round(r["flat"], 2),
                "P_bonus": round(r["pctile_bonus"], 2),
                "Z_bonus": round(r["z_bonus"], 2),
                "P_delta": round(r["pctile_bonus"] - r["flat"], 2),
                "Z_delta": round(r["z_bonus"] - r["flat"], 2),
            })
    print(pd.DataFrame(examples).to_string(index=False))

    # Effect on cross-position rankings: top-20 by best_adj — does the order change?
    print()
    print("=== Effect on top-20 by best_adj (current production = flat scheme) ===")
    # Compute per-player best_adj under each scheme.
    war_cols = {}
    for pos in POSITIONS:
        flat = pd.Series(flat_adj[pos], index=hitters.index)
        m = eligible_mask(hitters, pos)
        # For ineligible players, the bonus is irrelevant (filtered upstream by floor),
        # but we set NaN to be safe in the argmax.
        pct_full = pd.Series(np.nan, index=hitters.index)
        z_full = pd.Series(np.nan, index=hitters.index)
        elig, elig_def = elig_data[pos]
        if len(elig) > 0:
            pct_full.loc[elig.index] = percentile_bonus(elig_def, flat_adj[pos])
            z_full.loc[elig.index] = zscore_bonus(elig_def, flat_adj[pos], stdev_baseline)

        # raw <pos> WAR (= <pos>_def + war_hitting). Use NaN where ineligible.
        raw_war = hitters[f"{pos}_def"] + hitters["war_hitting"]
        if pos not in POSITION_FLOOR_EXEMPT:
            raw_war = raw_war.where(m, other=np.nan)

        war_cols[(pos, "F")] = raw_war + flat
        war_cols[(pos, "P")] = raw_war + pct_full
        war_cols[(pos, "Z")] = raw_war + z_full

    def best_adj_under(scheme):
        cols = [war_cols[(pos, scheme)] for pos in POSITIONS]
        stack = pd.concat(cols, axis=1, keys=POSITIONS)
        return stack.max(axis=1), stack.idxmax(axis=1)

    F_best, F_pos = best_adj_under("F")
    P_best, P_pos = best_adj_under("P")
    Z_best, Z_pos = best_adj_under("Z")

    cmp_df = hitters[["name"]].copy()
    cmp_df["F_best"] = F_best
    cmp_df["F_pos"] = F_pos
    cmp_df["P_best"] = P_best
    cmp_df["P_pos"] = P_pos
    cmp_df["Z_best"] = Z_best
    cmp_df["Z_pos"] = Z_pos
    cmp_df["P_minus_F"] = (P_best - F_best).round(2)
    cmp_df["Z_minus_F"] = (Z_best - F_best).round(2)
    top20 = cmp_df.sort_values("F_best", ascending=False).head(20)
    print(top20[["name", "F_pos", "F_best", "P_pos", "P_best", "P_minus_F", "Z_pos", "Z_best", "Z_minus_F"]]
          .round(2).to_string(index=False))

    # Rank churn: how many of the top-50 by F_best are still in top-50 by P_best?
    n_top = 50
    F_top = set(cmp_df.nlargest(n_top, "F_best")["name"])
    P_top = set(cmp_df.nlargest(n_top, "P_best")["name"])
    Z_top = set(cmp_df.nlargest(n_top, "Z_best")["name"])
    print()
    print(f"Top-{n_top} membership churn vs flat scheme:")
    print(f"  P: {len(F_top & P_top)}/{n_top} retained ({len(F_top - P_top)} dropped, {len(P_top - F_top)} added)")
    print(f"  Z: {len(F_top & Z_top)}/{n_top} retained ({len(F_top - Z_top)} dropped, {len(Z_top - F_top)} added)")


if __name__ == "__main__":
    main()
