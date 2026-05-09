"""Sense-check WAR ranges across positions.

Loads outputs/hitters.json and produces per-position distributions of
best_adj (the WAR a player gets at their best position) for the
MLB-experienced subset of hitters, plus a top-performers list per
pos_adj group. Used to compare against MLB analytics conventions
(replacement ~0, average regular ~2, MVP-tier 6-8 WAR).
"""

import json
import pandas as pd

with open("outputs/hitters.json") as f:
    data = json.load(f)
df = pd.DataFrame(data["rows"], columns=data["columns"])

mlb_q = df[df["yrs_MLB"].fillna(0) >= 1].copy()
print(f"Players with MLB experience: {len(mlb_q)} (of {len(df)} total)")
print()

positions = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]

print("Per-position {pos}_adj distribution (MLB-experienced hitters)")
print(f"{'Pos':4s}  {'N':>5s}  {'mean':>6s}  {'p25':>6s}  {'p50':>6s}  "
      f"{'p75':>6s}  {'p95':>6s}  {'max':>6s}  {'min':>6s}")
print("-" * 70)
for pos in positions:
    col = f"{pos}_adj"
    vals = mlb_q[col].dropna()
    if len(vals) == 0:
        print(f"{pos:4s}  no eligible")
        continue
    print(f"{pos:4s}  {len(vals):>5d}  {vals.mean():>6.2f}  "
          f"{vals.quantile(0.25):>6.2f}  {vals.quantile(0.50):>6.2f}  "
          f"{vals.quantile(0.75):>6.2f}  {vals.quantile(0.95):>6.2f}  "
          f"{vals.max():>6.2f}  {vals.min():>6.2f}")

print()
print("Top 5 per pos_adj group (where the player's WAR is best maximized)")
for pos in positions:
    sub = df[df["pos_adj"] == pos].sort_values("best_adj", ascending=False).head(5)
    if len(sub):
        print(f"\n  {pos}  (n={len(df[df['pos_adj']==pos])} players):")
        print(sub[["name", "org", "wOBA", "best_adj", "field"]]
              .to_string(index=False))

print()
print("Where players' best position lands (full population):")
print(df["pos_adj"].value_counts())
