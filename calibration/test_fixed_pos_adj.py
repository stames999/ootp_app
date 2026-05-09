"""
Side-by-side test: replace the existing skill-aware scarcity bonus with fixed
per-position adjustments (SS +6.5 ... 1B -12.5 runs/162) and see what changes.

Read-only — does not touch production columns. Builds parallel `*_new` columns
and compares position assignments + top-N rankings.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd


# Fixed per-position adjustments from the OOTP-calibrated handoff doc + DH.
# Values in runs/162; convert to WAR by dividing by 10.
# DH = -17.5 matches the FanGraphs convention; in this scheme it REPLACES the
# existing OOTP-internal DH_PENALTY (wOBA scaling) — DH adjustment is now a
# flat WAR penalty applied to raw war_hitting, not a wOBA scaling.
NEW_POS_ADJ_RUNS = {
    'SS': 6.5,
    '2B': 4.8,
    'C':  3.4,
    '3B': 2.9,
    'CF': 2.4,
    'RF': -2.0,
    'LF': -5.4,
    '1B': -12.5,
    'DH': -17.5,
}
NEW_POS_ADJ_WAR = {k: v / 10.0 for k, v in NEW_POS_ADJ_RUNS.items()}

ALL_POSITIONS = ["C", "CF", "RF", "LF", "SS", "2B", "3B", "1B", "DH"]


def load_df():
    class DevNull:
        def write(self, _): pass
        def flush(self): pass
    old = sys.stdout
    sys.stdout = DevNull()
    try:
        from main import compute_df
        df = compute_df()
    finally:
        sys.stdout = old
    return df


def apply_new_method(df):
    """Compute parallel `_new` columns using fixed positional adjustments.
    Mirrors `_apply_position_floor` semantics: a player whose floor-violating
    raw position is NaN stays NaN at that position in the new method too.

    For 8 fielding positions: new = bat_war + {pos}_def + new_adj_war
    For DH: new = bat_war + new_adj_war (no fielding contribution; raw war_hitting
            replaces existing DH_hitting which has the old DH_PENALTY scaling).
    """
    for pos in ('C', 'CF', 'RF', 'LF', 'SS', '2B', '3B', '1B'):
        adj_war = NEW_POS_ADJ_WAR[pos]
        # `df[pos]` is bat + fld at that position (post-floor). The floor
        # eligibility from current pipeline is preserved.
        df[f'{pos}_new'] = df[pos] + adj_war
        df[f'{pos}P_new'] = df[f'{pos}P'] + adj_war
    # DH: replace OOTP-internal DH_PENALTY scaling with flat -1.75 WAR adjustment
    # applied to raw war_hitting (not DH_hitting which has the old scaling).
    df['DH_new'] = df['war_hitting'] + NEW_POS_ADJ_WAR['DH']
    df['DHP_new'] = df['war_hittingP'] + NEW_POS_ADJ_WAR['DH']

    new_cols = [f'{p}_new' for p in ALL_POSITIONS]
    new_cols_P = [f'{p}P_new' for p in ALL_POSITIONS]
    df['best_new'] = df[new_cols].max(axis=1)
    df['pos_new'] = df[new_cols].idxmax(axis=1).str.replace('_new', '', regex=False)
    df['bestP_new'] = df[new_cols_P].max(axis=1)
    df['posP_new'] = df[new_cols_P].idxmax(axis=1).str.replace('P_new', '', regex=False).str.replace('_new', '', regex=False)
    return df


def main():
    df = load_df()
    hitters = df[df['position'] != 1].copy()
    print(f"Loaded {len(hitters)} hitters")
    print()

    apply_new_method(hitters)

    # ─── Top 20 by current `best_adj` vs by `best_new` ─────────────────────
    print("=" * 100)
    print("TOP 20 by CURRENT `best_adj` (skill-aware scarcity)")
    print("=" * 100)
    print(hitters.nlargest(20, 'best_adj')[
        ['name', 'org', 'age', 'pos_adj', 'best_adj', 'pos_new', 'best_new']
    ].to_string(index=False))
    print()
    print("=" * 100)
    print("TOP 20 by NEW `best_new` (fixed per-position adjustments)")
    print("=" * 100)
    print(hitters.nlargest(20, 'best_new')[
        ['name', 'org', 'age', 'pos_adj', 'best_adj', 'pos_new', 'best_new']
    ].to_string(index=False))
    print()

    # ─── Top 20 by potential side ──────────────────────────────────────────
    print("=" * 100)
    print("TOP 20 by NEW `bestP_new` (potential, fixed per-position)")
    print("=" * 100)
    print(hitters.nlargest(20, 'bestP_new')[
        ['name', 'org', 'age', 'posP_adj', 'bestP_adj', 'posP_new', 'bestP_new']
    ].to_string(index=False))
    print()

    # ─── Position assignment shifts ────────────────────────────────────────
    print("=" * 100)
    print("Position-assignment crosstab (pos_adj rows × pos_new cols), top tier only")
    print("=" * 100)
    # Filter to MLB-quality hitters to keep the matrix readable
    quality = hitters[hitters['best_adj'].notna() & (hitters['best_adj'] >= 1.0)]
    print(f"({len(quality)} hitters with best_adj >= 1.0)")
    crosstab = pd.crosstab(quality['pos_adj'], quality['pos_new'])
    print(crosstab.to_string())
    print()

    # ─── Per-position summary: how many shift IN vs OUT ────────────────────
    print("=" * 100)
    print("Per-position: net change in count (top-tier players, best_adj >= 1.0)")
    print("=" * 100)
    old_counts = quality['pos_adj'].value_counts()
    new_counts = quality['pos_new'].value_counts()
    summary = pd.DataFrame({'old': old_counts, 'new': new_counts}).fillna(0).astype(int)
    summary['delta'] = summary['new'] - summary['old']
    print(summary.sort_index().to_string())
    print()

    # ─── Notable individual shifts ─────────────────────────────────────────
    print("=" * 100)
    print("Players whose best position CHANGED (top 20 by current best_adj)")
    print("=" * 100)
    shifted = hitters[(hitters['pos_adj'] != hitters['pos_new']) &
                      hitters['best_adj'].notna() &
                      hitters['pos_adj'].notna() &
                      hitters['pos_new'].notna()].copy()
    shifted['shift'] = shifted['pos_adj'] + ' → ' + shifted['pos_new']
    print(f"  Total shifted: {len(shifted)} (out of {hitters['pos_adj'].notna().sum()} eligible)")
    print()
    print(shifted.nlargest(20, 'best_adj')[
        ['name', 'org', 'age', 'shift', 'best_adj', 'best_new']
    ].to_string(index=False))
    print()

    # ─── Magnitude comparison ──────────────────────────────────────────────
    print("=" * 100)
    print("Magnitude comparison: best_adj vs best_new (current-side, top-tier)")
    print("=" * 100)
    delta = (quality['best_new'] - quality['best_adj'])
    print(f"  delta (new - old):  mean={delta.mean():+.3f}  median={delta.median():+.3f}  "
          f"min={delta.min():+.3f}  max={delta.max():+.3f}")


if __name__ == '__main__':
    main()
