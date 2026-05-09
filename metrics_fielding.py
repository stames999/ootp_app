import numpy as np
import pandas as pd

from config import (
    FIELDING_RUN_VALUES_VS_REPLACEMENT,
    RUNS_PER_WIN,
    SS_INTERACTION_CORRECTION,
)

# Positions with a 2D interaction correction layered on top of the additive
# tables. SS is the only one currently — its RNG×ARM substitution genuinely
# violates additivity. See config.SS_INTERACTION_CORRECTION for derivation.
#
# KNOWN SATURATION LIMITATIONS (2B / 3B / SS):
# All three infield positions (excluding 1B) show ~30-50% saturation at
# extreme rating combos — the linear-additive sum overstates the
# cross-position floor/ceiling sims:
#   2B: 17% floor saturation, 45% ceiling saturation (validated all-65 sim
#       predicted +9.8 vs actual +5.4)
#   3B: 43% floor, 50% ceiling
#   SS: 36% floor, 31% ceiling (legacy SS_INTERACTION_CORRECTION grid below
#       provides partial correction but was calibrated against OLD 1D tables
#       and is stale; needs re-derivation against the current tables)
#
# Effect on elite infielder WAR: ~0.3-0.5 too high in absolute terms.
# Relative rankings within each position are preserved. Revisit with
# position-specific saturation functions or refit interaction grids when
# absolute WAR magnitudes matter (e.g., for cross-position comparisons via
# the +12.5/-12.5 pos-adj).
INTERACTION_HANDLERS = {
    "SS": {
        "grid": SS_INTERACTION_CORRECTION,
        "rating_cols": ("IFrange", "IFarm"),  # keys for the (v1, v2) lookup
    },
}


def closest_rating(value):
    """
    Round a rating to the nearest 5, then clamp it between 20 and 75.
    Sub-floor table entries (20, 25) carry the empirical sub-floor penalty
    so players with very low ratings drag mean(<pos>_def) down properly,
    which is what makes the empirical positional adjustment reflect real
    scarcity. NaN ratings default to 20 (most punitive) on the principle
    that "we have no data" should be treated like "this player can't field."
    """
    if pd.isna(value):
        return 20
    rounded = round(value / 5) * 5
    return min(75, max(20, rounded))


def _vec_closest_rating(series):
    """Vectorized closest_rating: round to nearest 5, clamp 20-75, NaN→20.
    Returns an int Series aligned with `series`."""
    arr = series.fillna(20).to_numpy(dtype=float)
    rounded = np.clip(np.rint(arr / 5.0) * 5.0, 20, 75).astype(int)
    return pd.Series(rounded, index=series.index)


def calc_fielding_metrics(df):
    """
    Calculates defensive value per position and adds the following columns to df:
    C_def, CF_def, RF_def, LF_def, SS_def, 2B_def, 3B_def, 1B_def

    Each column represents estimated runs saved vs replacement at that position.
    Computed for every player regardless of feasibility — eligibility filtering
    is handled downstream by metrics_war.calc_war() via POSITION_VIABILITY_GAP.

    For positions in INTERACTION_HANDLERS (currently SS), a 2D correction is
    added on top of the additive sum to capture rating-pair interactions that
    independent lookup tables can't represent.
    """
    added_columns = []

    for position, ratings_dict in FIELDING_RUN_VALUES_VS_REPLACEMENT.items():
        total_def_column = f"{position}_def"
        handler = INTERACTION_HANDLERS.get(position)

        # Sum the lookup-table values across all ratings, vectorized.
        total = pd.Series(0.0, index=df.index)
        for rating_name, rating_map in ratings_dict.items():
            if rating_name not in df.columns:
                continue
            rounded = _vec_closest_rating(df[rating_name])
            total = total + rounded.map(rating_map).fillna(0.0)

        # 2D interaction correction (SS only). Missing column defaults to
        # 30 to match the legacy iterrows behavior.
        if handler is not None:
            col1, col2 = handler["rating_cols"]
            v1 = (_vec_closest_rating(df[col1]) if col1 in df.columns
                  else pd.Series(30, index=df.index))
            v2 = (_vec_closest_rating(df[col2]) if col2 in df.columns
                  else pd.Series(30, index=df.index))
            pairs = pd.Series(list(zip(v1, v2)), index=df.index)
            total = total + pairs.map(handler["grid"]).fillna(0.0)

        df[total_def_column] = (total / RUNS_PER_WIN).round(1)
        added_columns.append(total_def_column)

    print(f"Added fielding columns: {added_columns}")
    return df
