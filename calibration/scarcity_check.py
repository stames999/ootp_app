"""Count WAR-positive players per position, with and without pos_adj.

For each position, reports:
  pos_eligible:    players for whom that position is feasible (pos floor passed)
  raw_pos_pos:     count where bat + _def > 0  (pre-pos_adj — pure scarcity signal)
  adj_pos_pos:     count where bat + _def + pos_adj > 0  (current WAR convention)

The raw count is the "intrinsic scarcity" — how many players can produce
above-replacement value at this position from bat and defense alone, before
any positional adjustment is applied. Useful for assessing whether the
current POSITIONAL_ADJUSTMENT_RUNS values match observed scarcity, or
whether they should be re-derived from this population.
"""
import json
import pandas as pd

with open("outputs/hitters.json") as f:
    data = json.load(f)
df = pd.DataFrame(data["rows"], columns=data["columns"])

positions = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]

# pos_adj in WAR = POSITIONAL_ADJUSTMENT_RUNS / RUNS_PER_WIN_FIELDING (= 9.53)
POS_ADJ_RUNS = {
    "SS": 6.5, "2B": 4.8, "C": 3.4, "3B": 2.9, "CF": 2.4,
    "RF": -3.7, "LF": -3.7, "1B": -12.5, "DH": -17.5,
}
RPW_F = 9.53

print(f"{'Pos':<4s} {'elig':>5s} {'raw>0':>6s} {'raw>1':>6s} {'raw>2':>6s} "
      f"{'raw>3':>6s} {'raw_p50':>8s} {'raw_p75':>8s} {'raw_p95':>8s} "
      f"{'adj>0':>6s} {'pos_adj':>8s}")
print("-" * 92)

stats = {}
for pos in positions:
    if pos == "DH":
        raw_col = "DH"
        adj_col = "DH_adj"
    else:
        raw_col = pos
        adj_col = f"{pos}_adj"

    elig = df[df[adj_col].notna()].copy()
    n_elig = len(elig)
    if n_elig == 0:
        print(f"{pos:<4s} {0:>5d}  no eligible")
        continue

    raw_vals = elig[raw_col]
    adj_vals = elig[adj_col]
    n_raw_0 = int((raw_vals > 0).sum())
    n_raw_1 = int((raw_vals > 1).sum())
    n_raw_2 = int((raw_vals > 2).sum())
    n_raw_3 = int((raw_vals > 3).sum())
    p50 = raw_vals.median()
    p75 = raw_vals.quantile(0.75)
    p95 = raw_vals.quantile(0.95)
    n_adj_0 = int((adj_vals > 0).sum())

    stats[pos] = {"elig": n_elig, "raw_p50": p50, "raw_p75": p75,
                  "raw_p95": p95, "raw>0": n_raw_0, "adj>0": n_adj_0}

    print(f"{pos:<4s} {n_elig:>5d} {n_raw_0:>6d} {n_raw_1:>6d} "
          f"{n_raw_2:>6d} {n_raw_3:>6d} {p50:>+8.2f} {p75:>+8.2f} "
          f"{p95:>+8.2f} {n_adj_0:>6d} {POS_ADJ_RUNS[pos]:>+8.1f}")

# What pos_adj would EQUALIZE the median raw WAR across positions?
# (If FG's pos_adj concept works empirically: average regular at each pos
# should produce same WAR after pos_adj, so pos_adj should offset the
# median raw difference across positions.)
print()
print("=== Implied pos_adj from median-equalization (no pos_adj baseline) ===")
medians = {p: stats[p]["raw_p50"] for p in positions if p in stats}
overall_med = sum(medians.values()) / len(medians)
print(f"Average of position medians: {overall_med:+.2f} WAR")
print(f"{'Pos':<4s}  {'raw_p50':>8s}  {'implied_runs':>14s}  {'current_runs':>14s}  {'delta':>8s}")
for pos, med in medians.items():
    # Want: median + pos_adj == overall_med
    # pos_adj_war = overall_med - med
    # pos_adj_runs = pos_adj_war * RPW_F
    implied_war = overall_med - med
    implied_runs = implied_war * RPW_F
    delta = implied_runs - POS_ADJ_RUNS[pos]
    print(f"{pos:<4s}  {med:>+8.2f}  {implied_runs:>+14.1f}  "
          f"{POS_ADJ_RUNS[pos]:>+14.1f}  {delta:>+8.1f}")

print()
print("=== Same exercise using p75 (above-average regular) ===")
p75s = {p: stats[p]["raw_p75"] for p in positions if p in stats}
overall_p75 = sum(p75s.values()) / len(p75s)
print(f"Average of position p75s: {overall_p75:+.2f} WAR")
for pos, q in p75s.items():
    implied_war = overall_p75 - q
    implied_runs = implied_war * RPW_F
    delta = implied_runs - POS_ADJ_RUNS[pos]
    print(f"{pos:<4s}  p75={q:>+6.2f}  implied={implied_runs:>+6.1f}  "
          f"current={POS_ADJ_RUNS[pos]:>+6.1f}  delta={delta:>+6.1f}")
