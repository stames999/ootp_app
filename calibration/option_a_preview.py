"""Preview Option A: replace POSITIONAL_ADJUSTMENT_RUNS with empirical p99
implied values (DH capped at -10). Recomputes adjusted WAR per position
and shows the top 10 at each.
"""
import sys
sys.path.insert(0, ".")

import pandas as pd
from main import compute_df

# Empirical p99 equalization (from calibration/scarcity_check_unfiltered.py)
NEW_POS_ADJ_RUNS = {
    "C":  19.4,
    "1B": -2.5,
    "2B":  7.9,
    "3B": -2.5,
    "SS": 10.8,
    "LF": -12.1,
    "CF": -7.3,
    "RF": -16.9,
    "DH": -10.0,   # capped — empirical gave +3.2 but DH should retain a
                   # "no defense" cost that the bat-only median doesn't see
}
RPW_F = 9.53
POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]

df = compute_df()

# Recompute *_adj with the new pos_adj values. The pipeline already produced
# bare *pos* columns (= bat + def, NaN'd for floor violators) — apply new
# pos_adj on top.
for pos in POSITIONS:
    new_adj_war = NEW_POS_ADJ_RUNS[pos] / RPW_F
    df[f"{pos}_adj_NEW"] = df[pos] + new_adj_war

# New best/pos based on NEW values
adj_new_cols = [f"{p}_adj_NEW" for p in POSITIONS]
df["best_adj_NEW"] = df[adj_new_cols].max(axis=1)
df["pos_adj_NEW"] = (
    df[adj_new_cols].idxmax(axis=1).str.replace("_adj_NEW", "", regex=False)
)

# Filter to position players only (exclude pitchers)
is_pitcher = (df["position"] == 1) | (df.get("pitches", 0).fillna(0) > 0)
pp = df[~is_pitcher].copy()

print(f"Position players: {len(pp)}")
print(f"Where best position lands under Option A:")
print(pp["pos_adj_NEW"].value_counts())
print()

print("=" * 86)
print("TOP 10 PER POSITION (by *_adj_NEW), where pos_adj_NEW == position")
print("=" * 86)

for pos in POSITIONS:
    sub = pp[pp["pos_adj_NEW"] == pos].copy()
    sub = sub.sort_values(f"{pos}_adj_NEW", ascending=False).head(10)
    print(f"\n--- {pos}  (pos_adj={NEW_POS_ADJ_RUNS[pos]:+.1f} runs, "
          f"{NEW_POS_ADJ_RUNS[pos]/RPW_F:+.2f} WAR; pool={len(pp[pp['pos_adj_NEW']==pos])}) ---")
    print(f"{'Player':<28s} {'Org':<5s} {'wOBA':>6s} "
          f"{'NEW':>6s} {'OLD':>6s} {'Δ':>6s}")
    for _, r in sub.iterrows():
        name = str(r.get("name", "?"))[:28]
        org_str = str(r.get("org", "?"))[:4]
        wOBA = r.get("wOBA", float("nan"))
        new_v = r[f"{pos}_adj_NEW"]
        old_v = r.get(f"{pos}_adj", float("nan"))
        delta = new_v - old_v if pd.notna(old_v) else float("nan")
        print(f"{name:<28s} {org_str:<5s} {wOBA:>6.3f} "
              f"{new_v:>+6.2f} {old_v:>+6.2f} {delta:>+6.2f}")

# Also compare specific star players cross-position
print()
print("=" * 86)
print("BENCHMARK: top stars across the board")
print("=" * 86)
star_names = ["Bobby Witt", "Juan Soto", "Aaron Judge", "Kyle Tucker",
              "Shohei Ohtani", "Roman Anthony", "Elly De La Cruz",
              "Cal Raleigh", "Corey Seager", "Jose Ramirez"]
for nm in star_names:
    matches = pp[pp["name"].str.contains(nm, case=False, na=False)]
    if len(matches) == 0:
        continue
    r = matches.iloc[0]
    old_best = r.get("best_adj", float("nan"))
    new_best = r["best_adj_NEW"]
    old_pos = r.get("pos_adj", "?")
    new_pos = r["pos_adj_NEW"]
    print(f"{nm:<22s} OLD: {old_best:>+6.2f} @ {old_pos:<3s}   "
          f"NEW: {new_best:>+6.2f} @ {new_pos:<3s}   "
          f"Δ {new_best - old_best:>+6.2f}")
