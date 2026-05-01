"""Least-squares refit of SS fielding tables using ALL sim scenarios.

Pistachio's SS_def is forced to be additive: SS_def = T_rng[r] + T_err[e]
+ T_arm[a] + T_tdp[t]. We can't fix the architectural sub-additivity that
the data shows for RNG×ARM, but we CAN find the additive table values that
minimize total squared error across all 60+ scenarios — not just the
single-attribute marginal sweeps.

This trades a little single-attr accuracy for much better multi-attr
accuracy, which is what matters for evaluating real elite-SS players.

Anchors: T_rng[60]=0, T_err[60]=0, T_arm[55]=0, T_tdp[50]=0 (sim baseline).
"""

import csv
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import FIELDING_RUN_VALUES_VS_REPLACEMENT as CURRENT

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

# Drop exact baselines (delta=0 by construction; would skew weights)
sim_rows = [r for r in rows if r["delta"] != 0]
# Average duplicate rating tuples (shouldn't be any but safe)

ANCHORS = {"rng": 60, "err": 60, "arm": 55, "tdp": 50}

# Collect observed values per attribute
observed = {a: set() for a in ANCHORS}
for r in sim_rows:
    for a in ANCHORS:
        observed[a].add(r[a])

# Build parameter index: each attribute has free params at all observed
# values EXCEPT the anchor (which is fixed at 0).
param_index = {}
i = 0
for a in ("rng", "err", "arm", "tdp"):
    for v in sorted(observed[a]):
        if v == ANCHORS[a]:
            continue
        param_index[(a, v)] = i
        i += 1
n_params = i
print(f"n_params = {n_params}, n_obs = {len(sim_rows)}")

# Build design matrix
X = np.zeros((len(sim_rows), n_params))
y = np.zeros(len(sim_rows))
for row_idx, r in enumerate(sim_rows):
    y[row_idx] = r["delta"]
    for a in ANCHORS:
        v = r[a]
        if (a, v) in param_index:
            X[row_idx, param_index[(a, v)]] = 1.0

# Solve via lstsq
beta, residuals, rank, sv = np.linalg.lstsq(X, y, rcond=None)
y_pred = X @ beta
mse = np.mean((y_pred - y) ** 2)
mae = np.mean(np.abs(y_pred - y))
print(f"fit MAE = {mae:.2f} runs, RMSE = {np.sqrt(mse):.2f}")

# ── unpack into tables ───────────────────────────────────────────────────────
fitted = {a: {ANCHORS[a]: 0.0} for a in ANCHORS}
for (a, v), idx in param_index.items():
    fitted[a][v] = float(beta[idx])

# Map our internal keys to Pistachio's table keys
attr_map = {"rng": "IFrange", "err": "IFerror", "arm": "IFarm", "tdp": "turnDP"}

# ── extrapolate to 30, 35, 80 (not in sim) ───────────────────────────────────
# For ratings <40, clamp at the observed minimum (effectively unable to play SS).
# For 80, clamp at observed max for that attr (saturation).
def extrapolate(table, all_values=(30, 35, 40, 45, 50, 55, 60, 65, 70, 75)):
    """Fill any missing rating in `all_values` from the nearest observed value
    (constant extrapolation). Values inside the observed range get the nearest
    observed neighbor; values below the min get the min; above the max get max."""
    out = dict(table)
    obs = sorted(table.keys())
    for v in all_values:
        if v in out:
            continue
        # constant extrapolation to nearest observed
        nearest = min(obs, key=lambda k: abs(k - v))
        out[v] = table[nearest]
    return out

for a in fitted:
    fitted[a] = extrapolate(fitted[a])

# ── isotonic smoothing (pool adjacent violators) ─────────────────────────────
# LSQ fit can have small non-monotonic blips from noise; enforce monotone
# non-decreasing so a higher rating never scores worse than a lower one.
def isotonic_nondecreasing(values):
    # PAV: walk left-to-right; whenever we find a decrease, pool with prior block.
    blocks = [[v, 1] for v in values]  # (mean, weight)
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] > blocks[i + 1][0]:
            mv, mw = blocks[i]
            nv, nw = blocks[i + 1]
            new_mean = (mv * mw + nv * nw) / (mw + nw)
            blocks[i:i + 2] = [[new_mean, mw + nw]]
            i = max(i - 1, 0)  # re-check leftward
        else:
            i += 1
    out = []
    for mean, weight in blocks:
        out.extend([mean] * weight)
    return out

for a in fitted:
    keys = sorted(fitted[a].keys())
    smoothed = isotonic_nondecreasing([fitted[a][k] for k in keys])
    fitted[a] = {k: round(v, 1) for k, v in zip(keys, smoothed)}

# ── compare ──────────────────────────────────────────────────────────────────
def lkup(table, v):
    v = max(min(v, max(table.keys())), min(table.keys()))
    # Snap to nearest 5 like Pistachio does
    snapped = round(v / 5) * 5
    return table.get(snapped, table.get(v, 0))


def predict_new(rats):
    rng, err, arm, tdp = rats
    return (
        lkup(fitted["rng"], rng) + lkup(fitted["err"], err)
        + lkup(fitted["arm"], arm) + lkup(fitted["tdp"], tdp)
    )


def predict_old(rats):
    rng, err, arm, tdp = rats
    cur = CURRENT["SS"]
    return (
        lkup(cur["IFrange"], rng) + lkup(cur["IFerror"], err)
        + lkup(cur["IFarm"], arm) + lkup(cur["turnDP"], tdp)
    )


# Marginal-only fit (from prior script) for comparison
marginal = {
    "rng": {40: -10.1, 45: -7.0, 50: -11.2, 55: -13.1, 60: 0, 65: 28.4, 70: 32.6, 75: 33.9},
    "err": {50: -4.1, 55: -4.0, 60: 0, 65: -0.2, 70: 3.3, 75: 2.0},
    "arm": {40: -13.3, 45: -11.3, 50: -10.1, 55: 0, 60: 15.4, 65: 27.8, 70: 29.1, 75: 31.8},
    "tdp": {45: -4.1, 50: 0, 55: -0.8, 60: 1.6, 65: 1.6, 70: 0.4, 75: 0.8},
}
def predict_marginal(rats):
    rng, err, arm, tdp = rats
    return marginal["rng"].get(rng, 0) + marginal["err"].get(err, 0) + marginal["arm"].get(arm, 0) + marginal["tdp"].get(tdp, 0)


print()
print("=" * 90)
print("Errors per scenario (predicted - actual, in runs/162)")
print("=" * 90)
print(f"{'scenario':<32} {'actual':>8} {'lsq':>8} {'marg':>8} {'old':>8} {'lsq_e':>7} {'marg_e':>7} {'old_e':>7}")
errs_lsq, errs_marg, errs_old = [], [], []
for r in rows:
    rats = (r["rng"], r["err"], r["arm"], r["tdp"])
    actual = r["delta"]
    p_lsq = predict_new(rats)
    p_marg = predict_marginal(rats)
    p_old = predict_old(rats)
    e_lsq = p_lsq - actual
    e_marg = p_marg - actual
    e_old = p_old - actual
    if rats != (60, 60, 55, 50):
        errs_lsq.append(e_lsq)
        errs_marg.append(e_marg)
        errs_old.append(e_old)
    diffs = sum(1 for i, (k, ank) in enumerate(zip(rats, (60, 60, 55, 50))) if k != ank)
    if diffs >= 2 or r["name"].startswith("Baseline"):
        print(f"{r['name']:<32} {actual:>+8.1f} {p_lsq:>+8.1f} {p_marg:>+8.1f} {p_old:>+8.1f} {e_lsq:>+7.1f} {e_marg:>+7.1f} {e_old:>+7.1f}")

import statistics as st
print()
print(f"{'Mean abs error (all scenarios)':<32}  lsq: {st.mean(abs(e) for e in errs_lsq):.1f}   marg: {st.mean(abs(e) for e in errs_marg):.1f}   old: {st.mean(abs(e) for e in errs_old):.1f}")
print(f"{'Max abs error':<32}  lsq: {max(abs(e) for e in errs_lsq):.1f}   marg: {max(abs(e) for e in errs_marg):.1f}   old: {max(abs(e) for e in errs_old):.1f}")

# ── print fitted tables ──────────────────────────────────────────────────────
print()
print("=" * 90)
print("Fitted SS tables (lsq) vs marginal vs current")
print("=" * 90)
ATTR_VALUES = [30, 35, 40, 45, 50, 55, 60, 65, 70, 75]
for a, label in attr_map.items():
    print(f"\n── {label} ──")
    print(f"  {'val':>4}  {'lsq':>7}  {'marg':>7}  {'old':>7}")
    cur = CURRENT["SS"][label]
    for v in ATTR_VALUES:
        new_v = fitted[a].get(v)
        marg_v = marginal[a].get(v)
        old_v = cur.get(v)
        s = lambda x: f"{x:+.1f}" if x is not None else "    —"
        print(f"  {v:>4}  {s(new_v):>7}  {s(marg_v):>7}  {s(old_v):>7}")

# ── emit Pistachio block ─────────────────────────────────────────────────────
lines = ['    "SS": {']
for a, label in attr_map.items():
    lines.append(f'        "{label}": {{')
    for v in ATTR_VALUES:
        val = fitted[a].get(v, 0.0)
        # Match Pistachio style: no leading + on non-negative
        lines.append(f"            {v}: {val:.1f},")
    lines.append("        },")
lines.append("    },")
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"\nWrote {OUT}")
