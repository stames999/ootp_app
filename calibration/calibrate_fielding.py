"""Generic fielding calibrator for any position.

Reads fielding_sim.csv (rows tagged by position), runs LSQ over all scenarios
for the given position, applies PAV isotonic smoothing for monotonicity, and
emits Pistachio-style table blocks.

Usage:
    python calibration/calibrate_fielding.py [position ...]
    # default: 2B 3B CF SS
"""

import csv
import sys
from pathlib import Path
import numpy as np
from statistics import mean

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import FIELDING_RUN_VALUES_VS_REPLACEMENT as CURRENT

HERE = Path(__file__).parent
DATA = HERE / "fielding_sim.csv"

# ── per-position config ──────────────────────────────────────────────────────
POSITIONS = {
    "2B": {
        "baseline": {"rng": 50, "err": 55, "arm": 50, "tdp": 55},
        "attrs": ["rng", "err", "arm", "tdp"],
        "keys":  ["IFrange", "IFerror", "IFarm", "turnDP"],
    },
    "3B": {
        "baseline": {"rng": 55, "err": 55, "arm": 55},
        "attrs": ["rng", "err", "arm"],  # TDP is inert at 3B
        "keys":  ["IFrange", "IFerror", "IFarm"],
    },
    "CF": {
        "baseline": {"rng": 60, "err": 60, "arm": 55},
        "attrs": ["rng", "err", "arm"],
        "keys":  ["OFrange", "OFerror", "OFarm"],
    },
    "SS": {
        "baseline": {"rng": 60, "err": 60, "arm": 55, "tdp": 50},
        "attrs": ["rng", "err", "arm", "tdp"],
        "keys":  ["IFrange", "IFerror", "IFarm", "turnDP"],
    },
    # Catcher: CSV slot mapping is BLK->rng, FRM->err, ARM->arm. Pistachio's
    # table keys for C are Cabil (blocking), Cfram (framing), Carm (arm).
    "C": {
        "baseline": {"rng": 55, "err": 55, "arm": 50},
        "attrs": ["rng", "err", "arm"],
        "keys":  ["Cabil", "Cfram", "Carm"],
    },
    "LF": {
        "baseline": {"rng": 50, "err": 45, "arm": 50},
        "attrs": ["rng", "err", "arm"],
        "keys":  ["OFrange", "OFerror", "OFarm"],
    },
    "RF": {
        "baseline": {"rng": 50, "err": 55, "arm": 55},
        "attrs": ["rng", "err", "arm"],
        "keys":  ["OFrange", "OFerror", "OFarm"],
    },
    # 1B: sim shows nearly inert (all deltas ±4 runs/162). Only RNG and ERR are
    # meaningfully sampled; ARM/TDP have a single confounded observation each
    # so we treat them as inert (zero) per HTML model + previous Pistachio.
    # row_filter excludes the one row where ARM/TDP differ from baseline.
    "1B": {
        "baseline": {"rng": 35, "err": 35},
        "attrs": ["rng", "err"],
        "keys":  ["IFrange", "IFerror"],
        "row_filter": lambda r: r["arm"] == 40 and r["tdp"] == 40,
        "inert_attrs": [("IFarm", 0.0)],  # emit IFarm table with all zeros
    },
}

ALL_RATING_VALUES = [20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75]

# Per-5-rating penalty applied below the lowest sim-observed rating for an
# attribute. Used as a floor for the extrapolation slope so plateaued tables
# (where the LSQ-fitted slope at the bottom is near zero) still get a real
# penalty going further below the floor. Tables that already have a meaningful
# slope at the bottom use that slope instead (max of slope vs. this constant).
SUB_FLOOR_PENALTY_PER_5 = 3.0


# ── load ─────────────────────────────────────────────────────────────────────
def load(pos):
    rows = []
    with open(DATA, newline="") as f:
        for r in csv.DictReader(f):
            if r["position"] != pos:
                continue
            for k in ("rng", "err", "arm", "tdp"):
                v = r[k].strip() if r[k] else ""
                r[k] = int(v) if v else None
            r["delta"] = float(r["delta"])
            rows.append(r)
    return rows


# ── fit ──────────────────────────────────────────────────────────────────────
def fit_position(pos):
    cfg = POSITIONS[pos]
    rows = load(pos)
    if not rows:
        print(f"!! no rows for {pos}")
        return None
    sim_rows = [r for r in rows if r["delta"] != 0]
    # Optional per-position row filter (e.g. 1B drops the ARM/TDP-confounded row)
    if "row_filter" in cfg:
        sim_rows = [r for r in sim_rows if cfg["row_filter"](r)]

    # observed values per attr
    observed = {a: set() for a in cfg["attrs"]}
    for r in sim_rows:
        for a in cfg["attrs"]:
            observed[a].add(r[a])

    # Build parameter index (skip the anchor rating per attr — fixed at 0)
    param_index = {}
    i = 0
    for a in cfg["attrs"]:
        for v in sorted(observed[a]):
            if v == cfg["baseline"][a]:
                continue
            param_index[(a, v)] = i
            i += 1
    n_params = i

    # design matrix
    X = np.zeros((len(sim_rows), n_params))
    y = np.zeros(len(sim_rows))
    for ri, r in enumerate(sim_rows):
        y[ri] = r["delta"]
        for a in cfg["attrs"]:
            v = r[a]
            if (a, v) in param_index:
                X[ri, param_index[(a, v)]] = 1.0

    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    y_pred = X @ beta
    mae = float(np.mean(np.abs(y_pred - y)))

    # unpack
    fitted = {a: {cfg["baseline"][a]: 0.0} for a in cfg["attrs"]}
    for (a, v), idx in param_index.items():
        fitted[a][v] = float(beta[idx])

    return {
        "fitted": fitted, "rows": rows, "sim_rows": sim_rows,
        "n_params": n_params, "mae": mae, "cfg": cfg,
    }


def fill_observed_range(table):
    """Fill ratings in ALL_RATING_VALUES that lie WITHIN [obs_min, obs_max]
    via linear interpolation between bracketing observed values. Above the
    observed max, clamp to the max value. Below obs_min is left empty —
    extend_below_floor handles that AFTER PAV smoothing has applied to the
    observed range, so the sub-floor extrapolation uses the smoothed slope
    rather than raw LSQ noise."""
    out = dict(table)
    obs = sorted(table.keys())
    if not obs:
        return out
    obs_min, obs_max = obs[0], obs[-1]
    for v in ALL_RATING_VALUES:
        if v in out:
            continue
        if v > obs_max:
            out[v] = table[obs_max]
        elif v < obs_min:
            continue  # extend later
        else:
            lower = max(k for k in obs if k <= v)
            upper = min(k for k in obs if k >= v)
            if lower == upper:
                out[v] = table[lower]
            else:
                t = (v - lower) / (upper - lower)
                out[v] = table[lower] + t * (table[upper] - table[lower])
    return out


def extend_below_floor(smoothed_table, obs_min,
                       sub_floor_penalty_per_5=SUB_FLOOR_PENALTY_PER_5):
    """Extend a smoothed table below `obs_min` using max(post-PAV slope at
    bottom, SUB_FLOOR_PENALTY_PER_5) as the per-5 penalty going down.

    Using the post-PAV slope (rather than the raw LSQ slope) keeps the
    sub-floor extrapolation consistent with the rest of the table. For
    plateaued attributes the slope is ~0 and the constant penalty floor wins;
    for sloped attributes the slope is preserved (linear extrapolation).
    """
    out = dict(smoothed_table)
    floor_val = smoothed_table[obs_min]
    keys_above = sorted(k for k in smoothed_table.keys() if k > obs_min)
    if keys_above:
        next_key = keys_above[0]
        gap_steps = max(1, (next_key - obs_min) // 5)
        slope_up_per_5 = (smoothed_table[next_key] - floor_val) / gap_steps
    else:
        slope_up_per_5 = 0.0
    sub_floor_per_5 = max(sub_floor_penalty_per_5, slope_up_per_5)

    for v in ALL_RATING_VALUES:
        if v >= obs_min:
            continue
        steps = (obs_min - v) // 5
        out[v] = floor_val - steps * sub_floor_per_5
    return out


# Back-compat alias used by older code paths in this module.
extrapolate = fill_observed_range


def isotonic_nondecreasing(values):
    blocks = [[v, 1] for v in values]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] > blocks[i + 1][0]:
            mv, mw = blocks[i]; nv, nw = blocks[i + 1]
            new_mean = (mv * mw + nv * nw) / (mw + nw)
            blocks[i:i + 2] = [[new_mean, mw + nw]]
            i = max(i - 1, 0)
        else:
            i += 1
    out = []
    for mean_, weight in blocks:
        out.extend([mean_] * weight)
    return out


def smooth_and_extrap(fitted):
    """Three-stage process per attribute table:

    1. Fill the OBSERVED range [obs_min, obs_max] with linear interpolation
       (interior gaps) and clamp above obs_max.
    2. Apply PAV isotonic smoothing across that range so the curve is
       monotone non-decreasing.
    3. Extend BELOW obs_min using the post-smoothing slope at the bottom
       as the per-5 penalty (with SUB_FLOOR_PENALTY_PER_5 as a floor for
       plateaued curves). Done after PAV so the extrapolation uses smoothed
       behaviour rather than raw LSQ noise at the bottom of the curve.
    """
    out = {}
    for a, table in fitted.items():
        obs_min = min(table.keys())

        # Stage 1: fill observed range
        filled = fill_observed_range(table)

        # Stage 2: PAV across observed range (don't include below-min keys yet)
        keys_in_range = sorted(k for k in filled.keys() if k >= obs_min)
        smoothed_vals = isotonic_nondecreasing([filled[k] for k in keys_in_range])
        smoothed = {k: round(v, 1) for k, v in zip(keys_in_range, smoothed_vals)}

        # Stage 3: extend below obs_min using post-PAV slope
        smoothed = extend_below_floor(smoothed, obs_min)

        out[a] = {k: round(v, 1) for k, v in smoothed.items()}
    return out


# ── eval ─────────────────────────────────────────────────────────────────────
def lkup(table, v):
    snapped = max(min(round(v / 5) * 5, max(table.keys())), min(table.keys()))
    return table.get(snapped, 0)


def predict_with_tables(rats, tables, attrs, interaction=None):
    """
    Additive prediction across the position's tables, plus an optional
    2D interaction correction looked up by (interaction['attrs'][0],
    interaction['attrs'][1]) snapped to the grid keys.
    """
    s = sum(lkup(tables[a], rats[a]) for a in attrs if rats.get(a) is not None)
    if interaction is not None:
        a1, a2 = interaction["attrs"]
        v1, v2 = rats.get(a1), rats.get(a2)
        if v1 is not None and v2 is not None:
            s1 = max(min(round(v1 / 5) * 5, 75), 30)
            s2 = max(min(round(v2 / 5) * 5, 75), 30)
            s += interaction["grid"].get((s1, s2), 0.0)
    return s


def predict_old(pos, rats, attrs, keys):
    cur = CURRENT[pos]
    return sum(lkup(cur[k], rats[a]) for a, k in zip(attrs, keys) if rats.get(a) is not None and k in cur)


# ── 2D interaction correction (used for SS where RNG×ARM substitution
# violates the additive assumption) ─────────────────────────────────────────
def compute_interaction_grid(sim_rows, smoothed, cfg, attr_pair):
    """
    For each sim observation, compute residual = actual - additive_prediction.
    Bin by (attr_pair[0], attr_pair[1]) value. Average residuals in each bin.
    Bilinear-fill empty cells from the nearest filled neighbor.

    Returns a dict {(v1, v2): correction_in_runs/162}.
    """
    a1_key, a2_key = attr_pair

    # Collect residuals at observed (a1, a2) cells
    cells = {}
    for r in sim_rows:
        rats = {a: r[a] for a in cfg["attrs"]}
        if any(rats.get(a) is None for a in cfg["attrs"]):
            continue
        v1, v2 = rats[a1_key], rats[a2_key]
        predicted = predict_with_tables(rats, smoothed, cfg["attrs"])
        residual = r["delta"] - predicted
        cells.setdefault((v1, v2), []).append(residual)

    cell_avg = {k: round(float(np.mean(v)), 1) for k, v in cells.items()}

    # Build dense grid via nearest-filled-cell lookup for missing entries.
    grid = {}
    for v1 in ALL_RATING_VALUES:
        for v2 in ALL_RATING_VALUES:
            if (v1, v2) in cell_avg:
                grid[(v1, v2)] = cell_avg[(v1, v2)]
            elif cell_avg:
                # Manhattan-nearest filled cell. Prevents wild extrapolation
                # while still giving a reasonable default for empty cells.
                nearest = min(
                    cell_avg.keys(),
                    key=lambda k: abs(k[0] - v1) + abs(k[1] - v2),
                )
                grid[(v1, v2)] = cell_avg[nearest]
            else:
                grid[(v1, v2)] = 0.0
    return grid


def emit_interaction_block(name, grid, key1, key2):
    """Emit a Python dict literal for the interaction correction grid."""
    lines = [f"{name} = {{"]
    lines.append(f"    # Keys: ({key1}_rating, {key2}_rating); values: runs/162 correction")
    lines.append(f"    # to add on top of the additive sum for this position.")
    for v1 in ALL_RATING_VALUES:
        for v2 in ALL_RATING_VALUES:
            val = grid.get((v1, v2), 0.0)
            lines.append(f"    ({v1}, {v2}): {val:.1f},")
    lines.append("}")
    return "\n".join(lines)


# ── emit Pistachio block for a position ──────────────────────────────────────
def emit_block(pos, smoothed, cfg):
    lines = [f'    "{pos}": {{']
    for a, key in zip(cfg["attrs"], cfg["keys"]):
        lines.append(f'        "{key}": {{')
        for v in ALL_RATING_VALUES:
            val = smoothed[a].get(v, 0.0)
            lines.append(f"            {v}: {val:.1f},")
        lines.append("        },")
    # Emit any inert tables (e.g. IFarm at 1B) as flat zeros
    for key, val in cfg.get("inert_attrs", []):
        lines.append(f'        "{key}": {{')
        for v in ALL_RATING_VALUES:
            lines.append(f"            {v}: {val:.1f},")
        lines.append("        },")
    lines.append("    },")
    return "\n".join(lines)


# Positions that use a 2D interaction correction on top of the additive
# tables. Currently SS only — RNG×ARM substitution genuinely violates
# additivity and the residuals are bigger than other positions can absorb.
INTERACTION_POSITIONS = {
    "SS": ("rng", "arm"),  # interaction grid keyed on (IFrange, IFarm)
}


# ── main ─────────────────────────────────────────────────────────────────────
def report(pos):
    res = fit_position(pos)
    if res is None:
        return None
    cfg = res["cfg"]
    smoothed = smooth_and_extrap(res["fitted"])

    # Compute interaction grid if this position uses one
    interaction_grid = None
    if pos in INTERACTION_POSITIONS:
        attr_pair = INTERACTION_POSITIONS[pos]
        interaction_grid = compute_interaction_grid(
            res["sim_rows"], smoothed, cfg, attr_pair
        )

    # Validate. For interaction positions we report two new MAEs:
    #   "new (additive)" — the LSQ-fit additive tables alone
    #   "new (with interaction)" — additive + 2D correction
    new_errs, new_full_errs, old_errs = [], [], []
    for r in res["rows"]:
        rats = {a: r[a] for a in cfg["attrs"]}
        if all(rats[a] == cfg["baseline"][a] for a in cfg["attrs"]):
            continue
        actual = r["delta"]
        new_pred = predict_with_tables(rats, smoothed, cfg["attrs"])
        old_pred = predict_old(pos, rats, cfg["attrs"], cfg["keys"])
        new_errs.append(new_pred - actual)
        old_errs.append(old_pred - actual)
        if interaction_grid is not None:
            new_full_pred = predict_with_tables(
                rats, smoothed, cfg["attrs"],
                interaction={"attrs": INTERACTION_POSITIONS[pos], "grid": interaction_grid},
            )
            new_full_errs.append(new_full_pred - actual)

    print(f"\n{'=' * 78}")
    print(f"{pos}: n_params={res['n_params']}, n_obs={len(res['sim_rows'])}")
    print(f"{'=' * 78}")
    print(f"  Mean abs error    new: {mean(abs(e) for e in new_errs):.1f}   old: {mean(abs(e) for e in old_errs):.1f}")
    print(f"  Max abs error     new: {max(abs(e) for e in new_errs):.1f}   old: {max(abs(e) for e in old_errs):.1f}")
    if new_full_errs:
        print(f"  With interaction  new: {mean(abs(e) for e in new_full_errs):.1f}   max: {max(abs(e) for e in new_full_errs):.1f}")

    print()
    for a, key in zip(cfg["attrs"], cfg["keys"]):
        print(f"  ── {key} ──")
        print(f"    {'val':>4}  {'new':>7}  {'old':>7}")
        cur = CURRENT[pos].get(key, {})
        for v in ALL_RATING_VALUES:
            n = smoothed[a].get(v)
            o = cur.get(v)
            n_s = f"{n:+.1f}" if n is not None else "    —"
            o_s = f"{o:+.1f}" if o is not None else "    —"
            print(f"    {v:>4}  {n_s:>7}  {o_s:>7}")

    return smoothed, interaction_grid


if __name__ == "__main__":
    positions = sys.argv[1:] or ["2B", "3B", "CF", "SS"]
    blocks = []
    interaction_blocks = []
    for pos in positions:
        result = report(pos)
        if result is None:
            continue
        smoothed, interaction_grid = result
        blocks.append(emit_block(pos, smoothed, POSITIONS[pos]))
        if interaction_grid is not None:
            # Emit a Python dict literal ready to paste into config.py
            cfg = POSITIONS[pos]
            attr_pair = INTERACTION_POSITIONS[pos]
            keys = [cfg["keys"][cfg["attrs"].index(a)] for a in attr_pair]
            interaction_blocks.append(
                emit_interaction_block(
                    f"{pos}_INTERACTION_CORRECTION", interaction_grid, keys[0], keys[1]
                )
            )

    out = HERE / "new_fielding_blocks.txt"
    out.write_text("\n".join(blocks) + "\n", encoding="utf-8")
    print(f"\nWrote blocks to {out}")

    if interaction_blocks:
        out2 = HERE / "new_interaction_blocks.txt"
        out2.write_text("\n\n".join(interaction_blocks) + "\n", encoding="utf-8")
        print(f"Wrote interaction blocks to {out2}")
