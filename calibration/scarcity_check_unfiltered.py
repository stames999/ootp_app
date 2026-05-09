"""Scarcity analysis with NO POSITION_FLOOR filtering.

Reconstructs unfiltered (bat + def) per position from the exported hitters.json
by un-applying pos_adj from the *_fld columns. Includes ALL position players,
regardless of fielding eligibility — that's the right denominator for scarcity:
"of all position players, how many would produce positive WAR if forced to
play this position." Pitchers excluded by filtering on "pos" being non-null.
"""
import json
import pandas as pd

POS_ADJ_RUNS = {
    "SS": 6.5, "2B": 4.8, "C": 3.4, "3B": 2.9, "CF": 2.4,
    "RF": -3.7, "LF": -3.7, "1B": -12.5, "DH": -17.5,
}
RPW_F = 9.53
POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]

with open("outputs/hitters.json") as f:
    data = json.load(f)
df = pd.DataFrame(data["rows"], columns=data["columns"])

# Position players = anyone whose hitting WAR is computed (war_hitting not NaN
# AND not all *_fld are NaN). Pitchers have war_hitting NaN-or-tiny since
# they barely have batting ratings.
pp = df[df["war_hitting"].notna()].copy()
print(f"Position players in pool: {len(pp)} (of {len(df)} total hitters export)")

# Reconstruct {pos}_def = {pos}_fld - pos_adj_war (for everyone, including
# floor violators — *_fld is NaN'd for floor violators, but we want unfiltered).
# Trick: use *_def reconstruction from the unfiltered pipeline. Since *_fld is
# NaN'd, fall back to recomputing from war_hitting and the floor-violator's
# def value... actually we can just use bat + (a recomputed def via the
# fielding tables). Simpler: use the ungated raw computation directly.

# The pipeline already computes *_def for every player (not gated). It just
# isn't exported. So re-run the small slice that produces them.
import sys
sys.path.insert(0, ".")
from main import compute_df  # this runs the full pipeline including calc_war
                              # but *_def values are present pre-gating
df_full = compute_df()

# In df_full, *_def is for all players. Pitchers have it too but we filter.
is_pitcher = (df_full["position"] == 1) | (df_full.get("pitches", 0).fillna(0) > 0)
pp = df_full[~is_pitcher].copy()
print(f"Position players (re-derived): {len(pp)}")

for pos in POSITIONS:
    pp[f"_{pos}_raw"] = pp["war_hitting"] + pp[f"{pos}_def"]
pp["_DH_raw"] = pp["DH_hitting"]

print()
print(f"{'Pos':<4s} {'N':>6s} {'raw>0':>7s} {'rate':>6s} "
      f"{'p25':>7s} {'p50':>7s} {'p75':>7s} {'p90':>7s} {'p95':>7s} "
      f"{'p99':>7s} {'max':>7s}")
print("-" * 84)

stats = {}
for pos in POSITIONS + ["DH"]:
    col = f"_{pos}_raw"
    vals = pp[col].dropna()
    n = len(vals)
    n_pos = int((vals > 0).sum())
    rate = 100 * n_pos / n if n else 0
    p25 = vals.quantile(0.25)
    p50 = vals.median()
    p75 = vals.quantile(0.75)
    p90 = vals.quantile(0.90)
    p95 = vals.quantile(0.95)
    p99 = vals.quantile(0.99)
    mx = vals.max()
    stats[pos] = {"n": n, "p50": p50, "p75": p75, "p90": p90,
                  "p95": p95, "p99": p99, "raw>0": n_pos}
    print(f"{pos:<4s} {n:>6d} {n_pos:>7d} {rate:>5.1f}% "
          f"{p25:>+7.2f} {p50:>+7.2f} {p75:>+7.2f} {p90:>+7.2f} "
          f"{p95:>+7.2f} {p99:>+7.2f} {mx:>+7.2f}")

# Implied pos_adj at three different equalization targets:
print()
for target_quantile, target_label in [
    ("p50", "median"),
    ("p90", "90th percentile (~MLB regular)"),
    ("p99", "99th percentile (~MLB All-Star)"),
]:
    print(f"\n=== Implied pos_adj at {target_label} equalization ===")
    target_vals = {p: stats[p][target_quantile] for p in stats}
    overall = sum(target_vals.values()) / len(target_vals)
    print(f"  cross-position average {target_quantile}: {overall:+.2f} WAR")
    print(f"  {'Pos':<4s}  {target_quantile:>8s}  {'implied_runs':>14s}  "
          f"{'current':>8s}  {'delta':>8s}")
    for pos, v in target_vals.items():
        implied_war = overall - v
        implied_runs = implied_war * RPW_F
        delta = implied_runs - POS_ADJ_RUNS[pos]
        print(f"  {pos:<4s}  {v:>+8.2f}  {implied_runs:>+14.1f}  "
              f"{POS_ADJ_RUNS[pos]:>+8.1f}  {delta:>+8.1f}")
