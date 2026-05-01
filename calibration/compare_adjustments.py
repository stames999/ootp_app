"""
compare_adjustments.py — Side-by-side comparison of candidate scarcity-adjustment
schemes for Pistachio's positional WAR layer.

Computes the per-position adjustment that gets added to <pos>_def to produce
<pos>_adj, under several alternative pool definitions, anchored on
POSITION_ADJ_REFERENCE (= 1B) so 1B's adjustment is always 0. Prints a
side-by-side comparison table and dumps a CSV.

Run from the repo root:
    python -m calibration.compare_adjustments
"""

import sys
from pathlib import Path

# Ensure repo root is importable when run as a script directly.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from config import (
    FIELDING_RUN_VALUES_VS_REPLACEMENT,
    POSITION_ADJ_REFERENCE,
    POSITION_FLOOR,
    POSITION_FLOOR_EXEMPT,
    RUNS_PER_WIN,
    SS_INTERACTION_CORRECTION,
)
from metrics_fielding import calc_fielding_metrics
from metrics_hitting import calc_hitting_metrics, calc_potential_hitting_metrics
from metrics_pitching import calc_pitching_metrics, calc_potential_pitching_metrics
from reader import (
    add_hitting_career_stats,
    add_pitching_career_stats,
    add_scouted_ratings,
    count_pitches,
    is_flagged,
    load_players,
)


POSITIONS = ["C", "CF", "RF", "LF", "SS", "2B", "3B", "1B"]

# FanGraphs convention (runs/162). Re-anchored on 1B (subtract 1B value) and
# converted to WAR by /RUNS_PER_WIN. Used as an external sanity reference.
FANGRAPHS_RAW_RUNS = {
    "C": 12.5, "SS": 7.5, "2B": 2.5, "3B": 2.5, "CF": 2.5,
    "RF": -7.5, "LF": -7.5, "1B": -12.5,
}


def fangraphs_adj_war():
    ref = FANGRAPHS_RAW_RUNS[POSITION_ADJ_REFERENCE]
    return {p: (FANGRAPHS_RAW_RUNS[p] - ref) / RUNS_PER_WIN for p in POSITIONS}


def def_at_uniform_rating(pos, rating_value):
    """Synthetic <pos>_def in WAR units for a player whose every relevant
    rating equals `rating_value`. Includes SS interaction at (v, v)."""
    ratings_dict = FIELDING_RUN_VALUES_VS_REPLACEMENT.get(pos, {})
    runs = sum(table.get(rating_value, 0.0) for table in ratings_dict.values())
    if pos == "SS":
        runs += SS_INTERACTION_CORRECTION.get((rating_value, rating_value), 0.0)
    return runs / RUNS_PER_WIN


def all_floor_baseline_war(pos):
    if pos in POSITION_FLOOR_EXEMPT:
        return None
    return def_at_uniform_rating(pos, POSITION_FLOOR)


# ─── Schemes ────────────────────────────────────────────────────────────────

def scheme_capped_mean(hitters):
    """A: current production. Mean(<pos>_def) over all hitters with each
    contribution clipped at the all-floor baseline (1B exempt)."""
    means = {}
    for pos in POSITIONS:
        col = f"{pos}_def"
        if pos in POSITION_FLOOR_EXEMPT:
            means[pos] = float(hitters[col].mean())
        else:
            cap = all_floor_baseline_war(pos)
            means[pos] = float(hitters[col].clip(lower=cap).mean())
    ref = means[POSITION_ADJ_REFERENCE]
    return {p: ref - means[p] for p in POSITIONS}, means


def scheme_uncapped_mean(hitters):
    """B: same all-hitters pool but no cap. Sub-floor extrapolated values pull
    means down → inflates the adjustment for hard positions."""
    means = {p: float(hitters[f"{p}_def"].mean()) for p in POSITIONS}
    ref = means[POSITION_ADJ_REFERENCE]
    return {p: ref - means[p] for p in POSITIONS}, means


def scheme_eligible_only(hitters):
    """C: mean over only players who pass POSITION_FLOOR for that position
    (1B includes everyone). Excludes the sub-floor cliff entirely."""
    means = {}
    for pos in POSITIONS:
        col = f"{pos}_def"
        if pos in POSITION_FLOOR_EXEMPT:
            eligible = hitters
        else:
            ratings_dict = FIELDING_RUN_VALUES_VS_REPLACEMENT[pos]
            relevant = [c for c in ratings_dict.keys() if c in hitters.columns]
            ok = (hitters[relevant].fillna(0) >= POSITION_FLOOR).all(axis=1)
            eligible = hitters[ok]
        means[pos] = float(eligible[col].mean()) if len(eligible) else 0.0
    ref = means[POSITION_ADJ_REFERENCE]
    return {p: ref - means[p] for p in POSITIONS}, means


def scheme_all_50(_hitters):
    """D: pool-free. Reference player has every relevant rating = 50.
    Adjustment is the gap between the table-implied 1B value and each pos."""
    means = {p: def_at_uniform_rating(p, 50) for p in POSITIONS}
    ref = means[POSITION_ADJ_REFERENCE]
    return {p: ref - means[p] for p in POSITIONS}, means


def scheme_all_floor(_hitters):
    """E: pool-free. Reference player at every rating = POSITION_FLOOR (40).
    The 'scarcity at the eligibility threshold' interpretation. Equal to the
    cap value used in scheme A by construction."""
    means = {p: def_at_uniform_rating(p, POSITION_FLOOR) for p in POSITIONS}
    ref = means[POSITION_ADJ_REFERENCE]
    return {p: ref - means[p] for p in POSITIONS}, means


def scheme_shrunk(hitters, factor=0.5):
    """F: scheme A scaled by `factor`. Quick lever, no theoretical basis."""
    adj, means = scheme_capped_mean(hitters)
    return {p: adj[p] * factor for p in POSITIONS}, means


def scheme_fangraphs(_hitters):
    """G: FanGraphs convention re-anchored on 1B."""
    return fangraphs_adj_war(), {}


# ─── Pipeline ───────────────────────────────────────────────────────────────

def load_pipeline_df():
    df = load_players()
    df = add_pitching_career_stats(df)
    df = add_hitting_career_stats(df)
    df = add_scouted_ratings(df)
    df = count_pitches(df)
    df = is_flagged(df)
    df = calc_pitching_metrics(df)
    df = calc_potential_pitching_metrics(df)
    df = calc_hitting_metrics(df)
    df = calc_potential_hitting_metrics(df)
    df = calc_fielding_metrics(df)
    return df


def filter_hitters(df):
    if "ip" in df.columns:
        return df[df["ip"].fillna(0) == 0]
    return df


def main():
    print("Loading and processing pipeline (this may take ~30-60s)...")
    df = load_pipeline_df()
    hitters = filter_hitters(df)
    print(f"  total players: {len(df)}")
    print(f"  hitters in pool (ip == 0): {len(hitters)}")

    schemes = [
        ("A: capped mean (current)", scheme_capped_mean),
        ("B: uncapped mean", scheme_uncapped_mean),
        ("C: eligible-only mean", scheme_eligible_only),
        ("D: all-50 reference", scheme_all_50),
        ("E: all-floor reference", scheme_all_floor),
        ("F: 0.5x current (shrunk)", scheme_shrunk),
        ("G: FanGraphs constants", scheme_fangraphs),
    ]

    rows, means_dump = [], {}
    for name, fn in schemes:
        adj, means = fn(hitters)
        rows.append({"scheme": name, **{p: round(adj[p], 2) for p in POSITIONS}})
        means_dump[name] = means

    table = pd.DataFrame(rows).set_index("scheme")
    print()
    print("Per-position scarcity adjustment in WAR units (anchored 1B = 0):")
    print(table.to_string())

    # Eligible-pool counts (for context on scheme C)
    print()
    print("Pool sizes by position (above-floor count vs. all hitters):")
    pool_counts = {"all_hitters": len(hitters)}
    for pos in POSITIONS:
        if pos in POSITION_FLOOR_EXEMPT:
            pool_counts[pos] = len(hitters)
            continue
        ratings_dict = FIELDING_RUN_VALUES_VS_REPLACEMENT[pos]
        relevant = [c for c in ratings_dict.keys() if c in hitters.columns]
        ok = (hitters[relevant].fillna(0) >= POSITION_FLOOR).all(axis=1)
        pool_counts[pos] = int(ok.sum())
    print(pd.Series(pool_counts).to_string())

    # Means diagnostic — what each pool-based scheme is actually averaging
    print()
    print("Diagnostic: mean(<pos>_def) under pool-based schemes (WAR units):")
    diag_rows = []
    for name, means in means_dump.items():
        if not means:
            continue
        diag_rows.append({"scheme": name, **{p: round(means[p], 2) for p in POSITIONS}})
    diag = pd.DataFrame(diag_rows).set_index("scheme")
    print(diag.to_string())

    out = Path(__file__).parent / "adjustments_compare.csv"
    table.to_csv(out)
    print()
    print(f"Saved adjustments to {out}")


if __name__ == "__main__":
    main()
