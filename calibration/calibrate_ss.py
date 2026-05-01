"""Refit SS fielding tables in FIELDING_RUN_VALUES_VS_REPLACEMENT['SS']
from team-of-clones SS sim data (ss_sim.csv).

Sim baseline: RNG=60, ERR=60, ARM=55, TDP=50  (set as 0-runs reference).
All deltas in the CSV are runs/162 vs that baseline.

Strategy:
  - Pistachio's SS_def is sum of independent per-attribute lookups.
  - Use the single-attribute sweeps as direct table values; the table at
    the sim-baseline rating (e.g. ARM=55 for arm) is set to 0.
  - Multi-attribute crosses are reported as a residual to expose the
    additive model's overshoot at extremes (RNG×ARM is the big one).
"""

import csv
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import FIELDING_RUN_VALUES_VS_REPLACEMENT as CURRENT  # for diff

DATA = Path(__file__).parent / "ss_sim.csv"
OUT = Path(__file__).parent / "new_ss_block.txt"

# ── load ─────────────────────────────────────────────────────────────────────
rows = []
with open(DATA, newline="") as f:
    for r in csv.DictReader(f):
        for k in ("rng", "err", "arm", "tdp"):
            r[k] = int(r[k])
        r["delta"] = float(r["run_delta_162"])
        rows.append(r)

BASELINE = (60, 60, 55, 50)


def matches_baseline_except(row, attr_idx):
    rats = (row["rng"], row["err"], row["arm"], row["tdp"])
    for i in range(4):
        if i == attr_idx:
            continue
        if rats[i] != BASELINE[i]:
            return False
    return True


# ── extract single-attribute marginal effects ────────────────────────────────
attrs = [("IFrange", 0), ("IFerror", 1), ("IFarm", 2), ("turnDP", 3)]
attr_to_key = {0: "rng", 1: "err", 2: "arm", 3: "tdp"}

new_table = {}
for label, idx in attrs:
    sweeps = [r for r in rows if matches_baseline_except(r, idx)]
    table = {}
    for r in sweeps:
        v = r[attr_to_key[idx]]
        if v in table:
            table[v] = (table[v] + r["delta"]) / 2  # average baselines
        else:
            table[v] = r["delta"]
    new_table[label] = table

# Print marginals next to current values
print("=" * 78)
print("SS marginal effects from sim (table value = runs/162 vs sim baseline)")
print("=" * 78)
for label, _ in attrs:
    print(f"\n── {label} ──")
    print(f"  {'val':>4}  {'new':>8}  {'current':>8}")
    cur = CURRENT["SS"][label]
    vals = sorted(set(list(new_table[label].keys()) + list(cur.keys())))
    for v in vals:
        n = new_table[label].get(v)
        c = cur.get(v)
        n_s = f"{n:+.1f}" if n is not None else "  —"
        c_s = f"{c:+.1f}" if c is not None else "  —"
        print(f"  {v:>4}  {n_s:>8}  {c_s:>8}")

# ── extrapolate down to 30/35 (sim doesn't cover) ────────────────────────────
# Use lowest two points to extrapolate linearly. If still below the cliff,
# clamp at the floor (sim shows ratings <60 are all roughly equally bad for SS).
def extrapolate_low(table):
    out = dict(table)
    sim_min = min(table.keys())
    if 30 not in out:
        # Floor at the worst observed value (range/arm cliffs apply)
        floor = min(table.values())
        out[30] = floor
    if 35 not in out:
        floor = min(table.values())
        out[35] = floor
    return out

# Add 30, 35 entries by clamping at the floor (ratings <40 essentially can't play SS)
for label in new_table:
    new_table[label] = extrapolate_low(new_table[label])

# Add 80 if missing (assume same as 75 for now — sim doesn't cover)
for label in new_table:
    if 80 not in new_table[label] and 75 in new_table[label]:
        new_table[label][80] = new_table[label][75]

# ── validate against multi-attribute crosses ─────────────────────────────────
def predict(rats):
    rng, err, arm, tdp = rats
    return (
        new_table["IFrange"].get(rng, 0)
        + new_table["IFerror"].get(err, 0)
        + new_table["IFarm"].get(arm, 0)
        + new_table["turnDP"].get(tdp, 0)
    )


def predict_old(rats):
    rng, err, arm, tdp = rats
    cur = CURRENT["SS"]
    def lk(t, v):  # nearest-5 lookup like Pistachio does
        v = max(30, min(75, round(v / 5) * 5))
        return t.get(v, 0)
    return lk(cur["IFrange"], rng) + lk(cur["IFerror"], err) + lk(cur["IFarm"], arm) + lk(cur["turnDP"], tdp)


print()
print("=" * 78)
print("Multi-attribute crosses: actual vs new-additive vs old-additive")
print("=" * 78)
print(f"{'scenario':<32} {'actual':>8} {'new':>8} {'old':>8} {'new_err':>9} {'old_err':>9}")
new_errs, old_errs = [], []
for r in rows:
    rats = (r["rng"], r["err"], r["arm"], r["tdp"])
    if rats == BASELINE:
        continue
    # is single-attr or multi-attr?
    diffs = sum(1 for i in range(4) if rats[i] != BASELINE[i])
    if diffs <= 1:
        continue
    actual = r["delta"]
    new_pred = predict(rats)
    old_pred = predict_old(rats)
    new_err = new_pred - actual
    old_err = old_pred - actual
    new_errs.append(new_err)
    old_errs.append(old_err)
    print(f"{r['name']:<32} {actual:>+8.1f} {new_pred:>+8.1f} {old_pred:>+8.1f} {new_err:>+9.1f} {old_err:>+9.1f}")

print()
print(f"{'Mean abs error (multi-attr):':<32} {'new':>15}: {mean(abs(e) for e in new_errs):.1f}   {'old':>5}: {mean(abs(e) for e in old_errs):.1f}")
print(f"{'Mean signed error:':<32} {'new':>15}: {mean(new_errs):+.1f}   {'old':>5}: {mean(old_errs):+.1f}")

# Single-attr accuracy
print()
print("=" * 78)
print("Single-attribute accuracy")
print("=" * 78)
print(f"{'scenario':<14} {'actual':>8} {'new':>8} {'old':>8}")
for r in rows:
    rats = (r["rng"], r["err"], r["arm"], r["tdp"])
    if rats == BASELINE:
        continue
    diffs = sum(1 for i in range(4) if rats[i] != BASELINE[i])
    if diffs != 1:
        continue
    print(f"{r['name']:<14} {r['delta']:>+8.1f} {predict(rats):>+8.1f} {predict_old(rats):>+8.1f}")

# ── emit Pistachio-style block ───────────────────────────────────────────────
ATTR_VALUES = [30, 35, 40, 45, 50, 55, 60, 65, 70, 75]
lines = ['    "SS": {']
for label, _ in attrs:
    lines.append(f'        "{label}": {{')
    for v in ATTR_VALUES:
        val = new_table[label].get(v, 0.0)
        lines.append(f"            {v}: {val:+.1f},")
    lines.append("        },")
lines.append("    },")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print()
print(f"Wrote {OUT}")
