"""Validate the refitted hitting model against the sim data.

For each scenario, predict wOBA via Pistachio's pipeline using the new tables
and compare to the empirical wOBA computed directly from the sim's per-PA rates.
"""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import BASE_HITTING_RATES, BATTING_COMPONENTS_ADJUST_MAP, BATTING_WOBA_WEIGHTS

DATA = Path(__file__).parent / "sim_data.csv"

COMPS = ["hr", "k", "bb", "1b", "2b", "3b"]


def adjusted_rates(ratings):
    rates = {c: BASE_HITTING_RATES[f"{c}_pct_baserate"] for c in COMPS}
    for rating, val in ratings.items():
        table = BATTING_COMPONENTS_ADJUST_MAP.get(rating)
        if not table:
            continue
        # Snap to nearest 5 in [20, 80]
        clamped = max(20, min(80, int(round(val / 5) * 5)))
        adj = table.get(str(clamped), {})
        for c in COMPS:
            rates[c] += adj.get(f"{c}_pct_adj", 0.0)
    return rates


def woba_from_rates(rates):
    return (
        BATTING_WOBA_WEIGHTS["hr_pct_wOBA_weight"] * rates["hr"]
        + BATTING_WOBA_WEIGHTS["bb_pct_wOBA_weight"] * rates["bb"]
        + BATTING_WOBA_WEIGHTS["1b_pct_wOBA_weight"] * rates["1b"]
        + BATTING_WOBA_WEIGHTS["2b_pct_wOBA_weight"] * rates["2b"]
        + BATTING_WOBA_WEIGHTS["3b_pct_wOBA_weight"] * rates["3b"]
    )


def empirical_rates(row):
    pa = float(row["AB"]) + float(row["BB"])
    one_b = float(row["H"]) - float(row["2B"]) - float(row["3B"]) - float(row["HR"])
    return {
        "hr": float(row["HR"]) / pa,
        "k": float(row["K"]) / pa,
        "bb": float(row["BB"]) / pa,
        "1b": one_b / pa,
        "2b": float(row["2B"]) / pa,
        "3b": float(row["3B"]) / pa,
    }


with open(DATA, newline="") as f:
    rows = list(csv.DictReader(f))

# Speed default = 50 (sim doesn't vary it)
print(f"{'scenario':<22} {'pred_wOBA':>10} {'emp_wOBA':>10} {'diff':>8}")
diffs = []
for r in rows:
    rats = {
        "avk": int(r["avk"]),
        "babip": int(r["babip"]),
        "gap": int(r["gap"]),
        "pow": int(r["pow"]),
        "eye": int(r["eye"]),
        "speed": 50,
    }
    pred = woba_from_rates(adjusted_rates(rats))
    emp = woba_from_rates(empirical_rates(r))
    diff = pred - emp
    diffs.append(diff)
    if r["name"] in (
        "Baseline_1", "POW80", "EYE80", "AVK80", "GAP80",
        "POW20xEYE65", "POW80xEYE80", "AVK20xEYE20", "Diabolical",
    ):
        print(f"{r['name']:<22} {pred:>10.4f} {emp:>10.4f} {diff:>+8.4f}")

import statistics
print()
print(f"Mean signed diff:    {statistics.mean(diffs):+.4f}")
print(f"Mean abs diff:       {statistics.mean(abs(d) for d in diffs):.4f}")
print(f"Max abs diff:        {max(abs(d) for d in diffs):.4f}")
print(f"# scenarios:         {len(diffs)}")
