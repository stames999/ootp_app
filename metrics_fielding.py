from config import (
    FIELDING_RUN_VALUES_VS_REPLACEMENT,
    RUNS_PER_WIN,
    SS_INTERACTION_CORRECTION,
)

# Positions with a 2D interaction correction layered on top of the additive
# tables. SS is the only one — its RNG×ARM substitution genuinely violates
# additivity. See config.SS_INTERACTION_CORRECTION for derivation.
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
    import pandas as pd
    if pd.isna(value):
        return 20
    rounded = round(value / 5) * 5
    return min(75, max(20, rounded))

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
        def_values = []

        for _, row in df.iterrows():
            total = 0.0

            for rating_name, rating_map in ratings_dict.items():
                if rating_name in row:
                    player_rating = row[rating_name]
                    rounded = closest_rating(player_rating)
                    value = rating_map.get(rounded, 0.0)
                    total += value

            # 2D interaction correction (SS only)
            if handler is not None:
                col1, col2 = handler["rating_cols"]
                v1 = closest_rating(row[col1]) if col1 in row else 30
                v2 = closest_rating(row[col2]) if col2 in row else 30
                total += handler["grid"].get((v1, v2), 0.0)

            def_values.append(total)

        df[total_def_column] = def_values
        df[total_def_column] = (df[total_def_column] / RUNS_PER_WIN).round(1) # convert from runs to wins i.e. fielding WAR
        added_columns.append(total_def_column)

    print(f"Added fielding columns: {added_columns}")
    return df