"""
Recompute BASE_HITTING_RATES and BATTING_COMPONENTS_ADJUST_MAP from
team-of-clones simulation data (sim_data.csv).

Each scenario row has all 9 batters at the same ratings, so per-PA rates
on the row are direct observations of what those ratings produce in OOTP.

PA is approximated as AB + BB (HBP/SF unavailable from this export).

Output:
  - new BASE rates (from baseline-50 averages)
  - per-rating delta tables (for each rating value: rate(v) - rate(50))
  - the existing Pistachio adjust map values for side-by-side comparison
  - validation: predicted runs/G from refitted rates vs actual

Run: python calibration/calibrate.py
"""

import csv
import os
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "sim_data.csv"

COMPONENTS = ["hr", "k", "bb", "1b", "2b", "3b"]
RATINGS = ["avk", "babip", "gap", "pow", "eye"]
# Pistachio table values exist at these rating points
TABLE_VALUES = [20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]


def load_rows():
    rows = []
    with open(DATA, newline="") as f:
        for r in csv.DictReader(f):
            for k, v in list(r.items()):
                if k == "name":
                    continue
                r[k] = float(v) if "." in v else int(v)
            rows.append(r)
    return rows


def rates(row):
    pa = row["AB"] + row["BB"]  # HBP/SF not exported; PA ≈ AB + BB
    one_b = row["H"] - row["2B"] - row["3B"] - row["HR"]
    return {
        "hr": row["HR"] / pa,
        "k": row["K"] / pa,
        "bb": row["BB"] / pa,
        "1b": one_b / pa,
        "2b": row["2B"] / pa,
        "3b": row["3B"] / pa,
    }


def main():
    rows = load_rows()
    by_name = {r["name"]: r for r in rows}

    # ── BASE RATES ────────────────────────────────────────────────────────────
    baselines = [by_name[n] for n in ("Baseline_1", "Baseline_2", "Baseline_3")]
    base_rates = {c: sum(rates(r)[c] for r in baselines) / 3 for c in COMPONENTS}

    print("=" * 78)
    print("NEW BASE_HITTING_RATES (from 3 baselines, all-50)")
    print("=" * 78)
    print(f"{'comp':<6} {'new':>10} {'current':>10} {'delta':>10}")
    current_base = {
        "hr": 0.0333, "k": 0.2089, "bb": 0.0706,
        "1b": 0.1564, "2b": 0.0450, "3b": 0.0048,
    }
    for c in COMPONENTS:
        delta = base_rates[c] - current_base[c]
        print(f"{c:<6} {base_rates[c]:>10.4f} {current_base[c]:>10.4f} {delta:>+10.4f}")

    # ── ADJUSTMENT TABLES ─────────────────────────────────────────────────────
    # For each rating R, for each value V (other ratings = 50), compute
    # rate_delta = observed_rate - base_rate. That IS the table entry.

    adj_tables = {}
    for rating in RATINGS:
        adj_tables[rating] = {}
        for v in TABLE_VALUES:
            if v == 50:
                adj_tables[rating][v] = {c: 0.0 for c in COMPONENTS}
                continue
            name = f"{rating.upper()}{v}"
            if name not in by_name:
                continue
            r = rates(by_name[name])
            adj_tables[rating][v] = {c: r[c] - base_rates[c] for c in COMPONENTS}

    # Pistachio's current values for comparison (import parent config)
    import sys
    sys.path.insert(0, str(HERE.parent))
    from config import BATTING_COMPONENTS_ADJUST_MAP as CURRENT

    rating_to_pkey = {
        "avk": "avk", "babip": "babip", "gap": "gap", "pow": "pow", "eye": "eye"
    }

    print()
    print("=" * 78)
    print("BATTING_COMPONENTS_ADJUST_MAP — new vs current")
    print("=" * 78)
    for rating in RATINGS:
        print(f"\n── {rating.upper()} ──")
        print(f"{'val':>4}  " + "  ".join(f"{c+'_new':>9}" for c in COMPONENTS))
        print(f"{'   ':>4}  " + "  ".join(f"{c+'_old':>9}" for c in COMPONENTS))
        pkey = rating_to_pkey[rating]
        for v in TABLE_VALUES:
            if v not in adj_tables[rating]:
                continue
            new_row = adj_tables[rating][v]
            cur_row_raw = CURRENT.get(pkey, {}).get(str(v), {})
            cur_row = {c: cur_row_raw.get(f"{c}_pct_adj", 0.0) for c in COMPONENTS}
            new_str = "  ".join(f"{new_row[c]:>+9.4f}" for c in COMPONENTS)
            cur_str = "  ".join(f"{cur_row[c]:>+9.4f}" for c in COMPONENTS)
            print(f"{v:>4}  {new_str}")
            print(f"{'':>4}  {cur_str}")

    # ── EMIT NEW PYTHON LITERALS for direct paste into config.py ─────────────
    out = HERE / "new_config_values.py"
    with open(out, "w") as f:
        f.write("# Auto-generated from calibration/calibrate.py\n")
        f.write("# Source: calibration/sim_data.csv (OOTP team-of-clones sim)\n\n")

        f.write("BASE_HITTING_RATES = {\n")
        for c in COMPONENTS:
            f.write(f'    "{c}_pct_baserate": {base_rates[c]:.4f},\n')
        f.write("}\n\n")

        f.write("BATTING_COMPONENTS_ADJUST_MAP = {\n")
        # Preserve speed table from Pistachio (sim doesn't vary speed)
        for rating in RATINGS:
            pkey = rating_to_pkey[rating]
            f.write(f'    "{pkey}": {{\n')
            for v in TABLE_VALUES:
                if v not in adj_tables[rating]:
                    continue
                row = adj_tables[rating][v]
                f.write(f'        "{v}": {{\n')
                for c in COMPONENTS:
                    f.write(f'            "{c}_pct_adj": {row[c]:+.4f},\n')
                f.write("        },\n")
            f.write("    },\n")
        f.write("    # NOTE: speed table not refitted (sim data has no speed sweep)\n")
        f.write("    # Keep existing speed entries from previous BATTING_COMPONENTS_ADJUST_MAP\n")
        f.write("}\n")

    print(f"\nWrote {out}")

    # ── SANITY CHECK: predicted vs actual runs/G across all scenarios ────────
    BAT_W = {"hr": 1.95, "bb": 0.72, "1b": 0.90, "2b": 1.24, "3b": 1.56}

    def predicted_woba(row):
        r = rates(row)
        return sum(BAT_W[c] * r[c] for c in BAT_W)

    print()
    print("=" * 78)
    print("Sanity: empirical wOBA from observed rates vs runs/G")
    print("=" * 78)
    print(f"{'scenario':<20} {'wOBA':>7} {'runs/G':>7}")
    pairs = []
    for r in rows:
        w = predicted_woba(r)
        rg = r["runs_per_g"]
        pairs.append((w, rg, r["name"]))

    # Print a few diagnostic
    for name in ["Baseline_1", "POW80", "EYE80", "AVK80", "POW20xEYE65", "POW80xEYE80"]:
        if name not in by_name:
            continue
        rrow = by_name[name]
        w = predicted_woba(rrow)
        print(f"{name:<20} {w:>7.4f} {rrow['runs_per_g']:>7.3f}")

    # Linear fit runs/G = a*wOBA + b across all scenarios → derive
    # per-162 coefficients in Pistachio's form.
    n = len(pairs)
    sx = sum(w for w, _, _ in pairs)
    sy = sum(rg for _, rg, _ in pairs)
    sxx = sum(w * w for w, _, _ in pairs)
    sxy = sum(w * rg for w, rg, _ in pairs)
    a = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    b = (sy - a * sx) / n
    # runs/162 = (a*wOBA + b) * 162
    # Pistachio form: runs/162 = COEFF*wOBA - CONST  ->  COEFF = a*162, CONST = -b*162
    coeff = a * 162
    const = -b * 162
    # R^2
    ymean = sy / n
    ss_tot = sum((rg - ymean) ** 2 for _, rg, _ in pairs)
    ss_res = sum((rg - (a * w + b)) ** 2 for w, rg, _ in pairs)
    r2 = 1 - ss_res / ss_tot

    print()
    print("=" * 78)
    print("Linear fit  runs/G = a*team_wOBA + b   (across all 88 scenarios)")
    print("=" * 78)
    print(f"slope a       = {a:.4f}   (team runs/G per wOBA point)")
    print(f"intercept b   = {b:.4f}")
    print(f"R^2           = {r2:.4f}")
    print(f"team-level COEFF = {coeff:.4f}   (vs current per-player {554.7865:.4f})")
    print(f"team-level CONST = {const:.4f}   (vs current per-player {178.9071:.4f})")
    print()
    print("NOTE: this slope/intercept is for TEAM runs vs TEAM wOBA in clone-team")
    print("sims. The current Pistachio COEFF/CONST is calibrated for INDIVIDUAL")
    print("player wOBA → individual run contribution in a normal lineup, which is")
    print("a different quantity. Use the team fit to QC the wOBA-rate model only;")
    print("don't paste these numbers into RUNS_PER_GAME_HITTING_COEFF/CONST.")


if __name__ == "__main__":
    main()
