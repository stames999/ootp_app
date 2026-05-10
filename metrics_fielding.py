import numpy as np
import pandas as pd

from config import (
    FIELDING_INTERACTION_CORRECTION,
    FIELDING_RUN_VALUES_VS_REPLACEMENT,
    FIELDING_SATURATION,
    RUNS_PER_WIN_FIELDING,
)

# Per-position infield saturation correction. The 1D rating tables are
# derived from sweeps where one rating moves at a time and others sit at
# the position baseline; when MULTIPLE ratings move together, the actual
# run impact is less than the sum (saturation in the OOTP engine). We fit
# an asymmetric tanh per position from sim data:
#
#   2B: positive side ≈ 0.589x linear; negative side tanh asymptote -73
#   3B: both sides tanh (positive asymptote +46, negative -38)
#   SS: both sides linear (~0.6x compression)
#
# 3B additionally has a (RNG, ARM) interaction correction added BEFORE
# saturation: at RNG=ARM=55, RNG's 50→55 inflection (+17) doesn't fully
# materialize because ARM is below its own 60→65 inflection. The all-55
# sim was 7 runs lower than uniform saturation predicts; that residual is
# captured as a single grid cell. See calibration/fit_saturation.py.


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


def _apply_saturation(total, params):
    """Asymmetric tanh saturation. `total` is a Series of additive sums;
    returns a Series of post-saturation runs. Linear-degenerate sides
    (huge ceil/scale) evaluate via tanh's small-argument linear regime."""
    cp, sp = params["ceil_pos"], params["scale_pos"]
    cn, sn = params["ceil_neg"], params["scale_neg"]
    x = total.to_numpy()
    out = np.where(
        x >= 0,
        cp * np.tanh(x / sp),
        -cn * np.tanh(-x / sn),
    )
    return pd.Series(out, index=total.index)


def calc_fielding_metrics(df):
    """
    Calculates defensive value per position and adds the following columns to df:
    C_def, CF_def, RF_def, LF_def, SS_def, 2B_def, 3B_def, 1B_def

    Each column represents estimated runs saved vs replacement at that position.
    Computed for every player regardless of feasibility — eligibility filtering
    is handled downstream by metrics_war.calc_war() via POSITION_FLOOR
    (any rating < 40 NaNs the position; 1B exempt).

    For 2B/3B/SS, an asymmetric-tanh saturation is applied to the additive
    sum to correct the over-prediction at extreme rating combos. 3B also
    has a (RNG, ARM) interaction grid added before saturation.
    """
    for position, ratings_dict in FIELDING_RUN_VALUES_VS_REPLACEMENT.items():
        total_def_column = f"{position}_def"

        # Sum the lookup-table values across all ratings, vectorized.
        total = pd.Series(0.0, index=df.index)
        for rating_name, rating_map in ratings_dict.items():
            if rating_name not in df.columns:
                continue
            rounded = _vec_closest_rating(df[rating_name])
            total = total + rounded.map(rating_map).fillna(0.0)

        # 2D interaction correction (3B only). Added BEFORE saturation so
        # the correction lives in additive-runs space and is then compressed
        # along with the rest of the contributions. Cells not in the grid
        # default to 0 (the all-55 anomaly is the only confirmed cell).
        grid = FIELDING_INTERACTION_CORRECTION.get(position)
        if grid is not None:
            v1 = (_vec_closest_rating(df["IFrange"]) if "IFrange" in df.columns
                  else pd.Series(50, index=df.index))
            v2 = (_vec_closest_rating(df["IFarm"]) if "IFarm" in df.columns
                  else pd.Series(60, index=df.index))
            pairs = pd.Series(list(zip(v1, v2)), index=df.index)
            total = total + pairs.map(grid).fillna(0.0)

        # Per-position saturation (2B/3B/SS). Other positions are additive
        # within sim noise and skip this step.
        sat_params = FIELDING_SATURATION.get(position)
        if sat_params is not None:
            total = _apply_saturation(total, sat_params)

        df[total_def_column] = (total / RUNS_PER_WIN_FIELDING).round(1)

    return df
