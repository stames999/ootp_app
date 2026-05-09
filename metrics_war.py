import numpy as np
import pandas as pd

from config import (
    FIELDING_RUN_VALUES_VS_REPLACEMENT,
    FIELD_VIABILITY_GAP,
    POSITION_FLOOR,
    POSITION_FLOOR_EXEMPT,
    POSITION_VIABILITY_GAP,
    POSITIONAL_ADJUSTMENT_RUNS,
    RUNS_PER_WIN_FIELDING,
)


def _hitter_mask(df):
    """Boolean mask: True for players treated as hitters in scarcity-pool
    construction. Anyone with no current pitch types above PITCH_MINIMUM_RATING
    is a hitter; pitchers (any pitch above floor) are excluded so they don't
    dilute the per-position fielding distribution. Falls back to all-True
    when neither `pitches` nor `ip` is in the frame (e.g. very early
    pre-pipeline calls during testing). Prefers `pitches` because it removes
    the dependency on the career_pitching_stats CSV."""
    if "pitches" in df.columns:
        return df["pitches"].fillna(0) == 0
    if "ip" in df.columns:
        return df["ip"].fillna(0) == 0
    return pd.Series(True, index=df.index)


# Positions listed in the displayed `field` column. DH is excluded (not a
# fielding position); 1B is included so a player who's a feasible 1B as a
# secondary option is correctly tagged.
FIELD_DISPLAY_POSITIONS = ["C", "CF", "RF", "LF", "SS", "2B", "3B", "1B"]

# Positions that participate in the WAR comparison (and therefore can become
# the player's `pos` / `posP`). DH is included so DH-only sluggers get picked.
ALL_POSITIONS = ["C", "CF", "RF", "LF", "SS", "2B", "3B", "1B", "DH"]


def _apply_position_floor(df):
    """
    NaN out a position's current AND potential WAR for any player whose
    relevant defensive rating at that position is below POSITION_FLOOR.

    Rationale: below the floor, our fielding tables are constant-clamped
    extrapolations from the lowest sim observation — we don't have measured
    data on how poor a fielder is at e.g. IFrange=30. Excluding rather than
    extrapolating prevents the adjusted-WAR ranking from projecting a player
    onto a position we have no baseline for.

    Positions in POSITION_FLOOR_EXEMPT (1B) are always allowed.
    Mutates `df` in place.
    """
    for pos, ratings_dict in FIELDING_RUN_VALUES_VS_REPLACEMENT.items():
        if pos in POSITION_FLOOR_EXEMPT:
            continue
        relevant_cols = [c for c in ratings_dict.keys() if c in df.columns]
        if not relevant_cols:
            continue
        # NaN-as-floor-violation via fillna(0); explicit 0 is also a violation.
        violation = (df[relevant_cols].fillna(0) < POSITION_FLOOR).any(axis=1)
        df.loc[violation, pos] = np.nan
        df.loc[violation, f"{pos}P"] = np.nan


def _apply_viability(df, war_columns, best_col):
    """
    NaN out any position WAR more than POSITION_VIABILITY_GAP wins below
    `best_col`. Mutates `df` in place.
    """
    for col in war_columns:
        outside = (df[best_col] - df[col]) > POSITION_VIABILITY_GAP
        df.loc[outside, col] = np.nan


def _build_field(df, position_cols, gap_col=None, best_col=None,
                 viability_gap=None):
    """Return a Series of comma-separated feasible non-DH positions.

    If gap_col, best_col, and viability_gap are all provided, additionally
    filter out positions whose `gap_col` value is more than `viability_gap`
    WAR below `best_col`. (gap_col is a template like "{}_adj" — formatted
    per position.) Used for the displayed `field` column so a player sees
    only realistic position alternatives rather than every position they
    pass the rating floor at.
    """
    if gap_col is None or best_col is None or viability_gap is None:
        return df[position_cols].apply(
            lambda row: ", ".join(p for p in position_cols if pd.notna(row[p])),
            axis=1,
        )

    def build(row):
        best = row[best_col]
        if pd.isna(best):
            return ""
        out = []
        for p in position_cols:
            if pd.isna(row[p]):
                continue
            val = row[gap_col.format(p)]
            if pd.notna(val) and val >= best - viability_gap:
                out.append(p)
        return ", ".join(out)

    return df.apply(build, axis=1)


def calc_war(df):
    """
    Combine hitting WAR with each position's defensive runs to produce
    per-position WAR columns. Position eligibility is determined by
    POSITION_FLOOR alone (any relevant rating <40 → NaN at that position;
    1B exempt as catch-all). The `field` column lists every position the
    player can physically play.

    Then applies fixed positional adjustments from POSITIONAL_ADJUSTMENT_RUNS
    (sim-calibrated, FG-standard ±12.5) and produces position-adjusted
    <pos>_adj columns plus best_adj / pos_adj.

    Output columns:
      Raw current:     C, CF, RF, LF, SS, 2B, 3B, 1B, DH (NaN if floor-violator)
                       best, pos, field
      Raw potential:   CP, CFP, RFP, LFP, SSP, 2BP, 3BP, 1BP, DHP, bestP, posP
      Adjusted:        C_adj, ..., DH_adj, best_adj, pos_adj
      Adjusted pot.:   CP_adj, ..., DHP_adj, bestP_adj, posP_adj
    """
    df = df.copy()  # defrag the dataframe to avoid warning

    # ── Current-rating position WAR ─────────────────────────────────────────
    df["C"] = df["C_def"] + df["war_hitting"]
    df["CF"] = df["CF_def"] + df["war_hitting"]
    df["RF"] = df["RF_def"] + df["war_hitting"]
    df["LF"] = df["LF_def"] + df["war_hitting"]
    df["SS"] = df["SS_def"] + df["war_hitting"]
    df["2B"] = df["2B_def"] + df["war_hitting"]
    df["3B"] = df["3B_def"] + df["war_hitting"]
    df["1B"] = df["1B_def"] + df["war_hitting"]
    df["DH"] = df["DH_hitting"]

    # ── Potential-rating position WAR ───────────────────────────────────────
    df["CP"] = df["C_def"] + df["war_hittingP"]
    df["CFP"] = df["CF_def"] + df["war_hittingP"]
    df["RFP"] = df["RF_def"] + df["war_hittingP"]
    df["LFP"] = df["LF_def"] + df["war_hittingP"]
    df["SSP"] = df["SS_def"] + df["war_hittingP"]
    df["2BP"] = df["2B_def"] + df["war_hittingP"]
    df["3BP"] = df["3B_def"] + df["war_hittingP"]
    df["1BP"] = df["1B_def"] + df["war_hittingP"]
    df["DHP"] = df["DH_hittingP"]

    # ── Apply POSITION_FLOOR exclusion ──────────────────────────────────────
    # A player with any relevant rating below the calibrated floor is
    # excluded from that position outright (1B exempt). This is now the only
    # eligibility filter — the WAR-gap viability filter has been removed in
    # favour of letting `field` reflect every position the player can
    # physically play, regardless of relative WAR. Use best_adj / pos_adj
    # for "where is this player most valuable" as the secondary signal.
    _apply_position_floor(df)

    war_columns = ALL_POSITIONS  # ["C","CF","RF","LF","SS","2B","3B","1B","DH"]
    df["best"] = df[war_columns].max(axis=1)
    df["pos"] = df[war_columns].idxmax(axis=1)

    war_potential_columns = [f"{p}P" for p in ALL_POSITIONS]
    df["bestP"] = df[war_potential_columns].max(axis=1)
    df["posP"] = df[war_potential_columns].idxmax(axis=1)

    # `field` is built later, after pos_adj is applied — it filters by the
    # FIELD_VIABILITY_GAP against best_adj.

    # ── Fixed positional adjustment ─────────────────────────────────────────
    #
    # Each position gets a flat per-player WAR adjustment from
    # POSITIONAL_ADJUSTMENT_RUNS (in runs/162, divided by RUNS_PER_WIN_FIELDING
    # to convert to WAR units in the fielding sim's run environment — same
    # divisor used for fielding _def, keeping the bat/def/pos-adj chain
    # internally consistent). Values were derived from OOTP team-of-clones
    # calibration, scaled to FG-standard ±12.5 range, and sum to zero across
    # the 8 fielding positions. DH = -17.5 from FanGraphs convention.
    #
    # Replaces the prior in-sample skill-aware scarcity bonus, which back-fit
    # a per-player premium against the population's fielding distribution.
    # The fixed scheme is conventional (matches FG/bWAR), externally calibrated
    # (sim-derived, not data-fit), and validated in test_fixed_pos_adj.py.
    #
    # _fld preserves the legacy behavior of "fielding-only WAR with positional
    # adjustment baked in" — same value across current and potential because
    # OOTP fielding ratings are static.
    for pos in ALL_POSITIONS:
        adj_runs = POSITIONAL_ADJUSTMENT_RUNS.get(pos, 0)
        adj_war = adj_runs / RUNS_PER_WIN_FIELDING

        if pos == "DH":
            # DH has no fielding (no _def). _adj is just bat + DH adjustment.
            df[f"{pos}_adj"] = df[pos] + adj_war
            df[f"{pos}P_adj"] = df[f"{pos}P"] + adj_war
            df["DH_fld"] = 0.0  # nominally zero for the no-defense position
            continue

        # Apply fixed per-position WAR adjustment. NaN at the underlying
        # position (floor violator) propagates so ineligible players stay NaN.
        df[f"{pos}_adj"] = df[pos] + adj_war
        df[f"{pos}P_adj"] = df[f"{pos}P"] + adj_war
        df[f"{pos}_fld"] = df[f"{pos}_def"] + adj_war
        df.loc[df[pos].isna(), f"{pos}_fld"] = float("nan")

    adj_cols = [f"{p}_adj" for p in ALL_POSITIONS]
    df["best_adj"] = df[adj_cols].max(axis=1)
    df["pos_adj"] = (
        df[adj_cols].idxmax(axis=1).str.replace("_adj", "", regex=False)
    )

    adjP_cols = [f"{p}P_adj" for p in ALL_POSITIONS]
    df["bestP_adj"] = df[adjP_cols].max(axis=1)
    df["posP_adj"] = (
        df[adjP_cols].idxmax(axis=1).str.replace("P_adj", "", regex=False)
    )

    # `field`: only show positions whose adjusted WAR is within
    # FIELD_VIABILITY_GAP of the player's best_adj. Removes the noise of
    # listing every position a player passes the rating floor at — keeps
    # only realistic alternatives. All per-position WARs remain in the
    # export untouched.
    df["field"] = _build_field(
        df, FIELD_DISPLAY_POSITIONS,
        gap_col="{}_adj", best_col="best_adj",
        viability_gap=FIELD_VIABILITY_GAP,
    )

    return df
