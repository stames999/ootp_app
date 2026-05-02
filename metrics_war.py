import numpy as np
import pandas as pd

from config import (
    FIELDING_RUN_VALUES_VS_REPLACEMENT,
    POSITION_ADJ_REFERENCE,
    POSITION_FLOOR,
    POSITION_FLOOR_EXEMPT,
    POSITION_VIABILITY_GAP,
    RUNS_PER_WIN,
    SCARCITY_SKILL_GAMMA,
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


def _build_field(df, position_cols):
    """Return a Series of comma-separated feasible non-DH positions."""
    return df[position_cols].apply(
        lambda row: ", ".join(p for p in position_cols if pd.notna(row[p])),
        axis=1,
    )


# Floor for per-position stdev when standardizing a player's defensive WAR
# (the denominator of the z-score). Just a safety net for under-sampled or
# pathologically-tight position distributions.
ADJ_STDEV_FLOOR = 0.3


def _all_floor_baseline(pos):
    """
    Synthetic <pos>_def value for a player whose relevant ratings are all at
    POSITION_FLOOR (40). Used as a CAP on per-player contributions to the
    positional mean — sub-floor extrapolated values can otherwise drag the
    all-hitters mean far below this baseline and inflate the adjustment.

    Returns the baseline in WAR units (runs / RUNS_PER_WIN).
    """
    ratings_dict = FIELDING_RUN_VALUES_VS_REPLACEMENT.get(pos, {})
    if not ratings_dict:
        return 0.0
    runs = sum(table.get(POSITION_FLOOR, 0) for table in ratings_dict.values())
    return runs / RUNS_PER_WIN


def _skill_aware_bonus(df, pos, scarcity_constant, gamma):
    """
    Per-player scarcity bonus, scaled by the player's percentile rank within
    the eligible hitter pool's <pos>_def. Mean-preserving by construction:

        mean(bonus | eligible hitter) == scarcity_constant

    so cross-position calibration anchored on POSITION_ADJ_REFERENCE is
    preserved. gamma=0 recovers the flat scheme; gamma=0.5 spreads bonuses
    from 0.5x to 1.5x scarcity_constant across the percentile range.

    The reference distribution is hitters-only (no current pitch types
    above the rating floor) so the percentile isn't diluted by pitchers
    who happen to clear the floor; bonuses are then interpolated for any
    non-hitter who passes the floor (rarely matters since pitcher
    <pos>_fld isn't consumed downstream).

    Returns a Series indexed like df: bonus for floor-passing players, NaN
    elsewhere. Adding this to df[pos] / df[f"{pos}_def"] propagates NaN
    correctly for ineligible players.
    """
    bonus = pd.Series(np.nan, index=df.index)

    elig_idx = df.index[df[pos].notna()]
    if len(elig_idx) == 0:
        return bonus

    hitter_mask = _hitter_mask(df)
    ref_idx = df.index[df[pos].notna() & hitter_mask]
    if len(ref_idx) == 0:
        return bonus

    ref_def = np.sort(df.loc[ref_idx, f"{pos}_def"].to_numpy())
    elig_def = df.loc[elig_idx, f"{pos}_def"].to_numpy()

    # Percentile against the hitter-eligible distribution, midpoint convention
    # so the empirical mean of pct is exactly 50 over the reference pool.
    n_ref = len(ref_def)
    left = np.searchsorted(ref_def, elig_def, side="left")
    right = np.searchsorted(ref_def, elig_def, side="right")
    pct = ((left + right) / 2.0 / n_ref) * 100.0

    bonus.loc[elig_idx] = scarcity_constant * (1.0 + gamma * (pct / 50.0 - 1.0))
    return bonus


def _compute_positional_distribution(df):
    """
    Compute (mean, stdev) of each position's defensive WAR. The mean drives
    the mean-shift positional adjustment in calc_war.

    Per-player <pos>_def values are CAPPED at the position's all-floor
    baseline before contributing to the mean. Without this cap, sub-floor
    extrapolated values (Cfram=20 → -57 runs, etc.) drag the all-hitters
    mean far below the realistic floor and inflate the scarcity adjustment
    (e.g. C adjustment ballooning to +7 WAR in real OOTP exports). Capping
    at the all-rating-40 baseline preserves the scarcity signal — positions
    where most players score below floor still produce meaningfully-negative
    means — without runaway inflation.

    1B is exempt (no floor → no cap). DH has no _def → degenerate.

    Returns a dict {position: (mean_capped, stdev_eligible)}.
    """
    hitters = df[_hitter_mask(df)]

    stats = {}
    for pos in ALL_POSITIONS:
        if pos == "DH":
            stats[pos] = (0.0, 0.0)  # degenerate; DH has no fielding value
            continue

        col = f"{pos}_def"
        if col not in hitters.columns:
            stats[pos] = (0.0, 0.0)
            continue

        # Mean: cap each player's <pos>_def at the all-floor baseline before
        # averaging. 1B (catch-all, no floor) skips the cap.
        if pos in POSITION_FLOOR_EXEMPT:
            pos_mean = float(hitters[col].mean())
        else:
            cap = _all_floor_baseline(pos)
            pos_mean = float(hitters[col].clip(lower=cap).mean())

        # Stdev kept around for diagnostics (computed over the eligible pool
        # to avoid sub-floor variance inflation). Not used by mean-shift adj.
        ratings_dict = FIELDING_RUN_VALUES_VS_REPLACEMENT.get(pos, {})
        relevant_cols = [c for c in ratings_dict.keys() if c in hitters.columns]
        if pos in POSITION_FLOOR_EXEMPT or not relevant_cols:
            eligible = hitters
        else:
            ok = (hitters[relevant_cols].fillna(0) >= POSITION_FLOOR).all(axis=1)
            eligible = hitters[ok]
        pos_std = float(eligible[col].std()) if len(eligible) > 1 else float(hitters[col].std())

        stats[pos] = (pos_mean, pos_std)
    return stats


def calc_war(df):
    """
    Combine hitting WAR with each position's defensive runs to produce
    per-position WAR columns. Position eligibility is determined by
    POSITION_FLOOR alone (any relevant rating <40 → NaN at that position;
    1B exempt as catch-all). The `field` column lists every position the
    player can physically play.

    Then computes empirical positional adjustments from <pos>_def averages
    over the all-hitters pool (anchored on POSITION_ADJ_REFERENCE) and
    produces scarcity-adjusted <pos>_adj columns plus best_adj / pos_adj.

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

    # ── Build `field` from feasible current-WAR positions ───────────────────
    df["field"] = _build_field(df, FIELD_DISPLAY_POSITIONS)

    # ── Skill-aware empirical positional adjustment ─────────────────────────
    #
    # For each non-anchor position, the scarcity bonus is mean-preserving but
    # per-player: the bonus scales with the player's percentile rank within
    # the eligible hitter pool's <pos>_def. The eligible-pool mean of the
    # bonus equals the flat mean-shift constant
    #
    #     scarcity_pos = mean_1B - mean_pos
    #
    # so cross-position calibration (anchored on POSITION_ADJ_REFERENCE) is
    # preserved by construction. SCARCITY_SKILL_GAMMA controls the spread:
    # gamma=0 recovers the flat scheme exactly; the production default 0.5
    # gives a 100th-percentile player at SS ~1.5x the scarcity bonus, a 0th
    # percentile player ~0.5x. See _skill_aware_bonus and
    # calibration/skill_aware_adj.py for the derivation and comparison
    # against the flat scheme.
    #
    # Hitting WAR is preserved as a literal additive term. 1B_adj == 1B by
    # construction (it's the anchor; bonus = 0). Same bonus is applied to
    # current and potential WAR because OOTP fielding ratings are static.
    pos_stats = _compute_positional_distribution(df)
    ref_mean, _ = pos_stats[POSITION_ADJ_REFERENCE]

    for pos in ALL_POSITIONS:
        if pos == "DH":
            # DH has no fielding distribution; no scarcity premium to capture.
            # DH penalty already lives inside DH_hitting; DH_fld is nominally 0.
            df[f"{pos}_adj"] = df[pos]
            df[f"{pos}P_adj"] = df[f"{pos}P"]
            df["DH_fld"] = 0.0
            continue

        if pos == POSITION_ADJ_REFERENCE:
            # Anchor: by construction adj_pos == 0 for the reference.
            df[f"{pos}_adj"] = df[pos]
            df[f"{pos}P_adj"] = df[f"{pos}P"]
            # _fld for the anchor = raw _def (no scarcity adj).
            df[f"{pos}_fld"] = df[f"{pos}_def"]
            df.loc[df[pos].isna(), f"{pos}_fld"] = float("nan")
            continue

        pos_mean, _ = pos_stats[pos]
        scarcity = ref_mean - pos_mean  # eligible-pool mean of the bonus
        bonus = _skill_aware_bonus(df, pos, scarcity, SCARCITY_SKILL_GAMMA)

        # Apply per-player bonus. NaN bonus for ineligible players propagates
        # through addition so floor-violators stay NaN'd in _adj / _fld.
        df[f"{pos}_adj"] = df[pos] + bonus
        df[f"{pos}P_adj"] = df[f"{pos}P"] + bonus
        df[f"{pos}_fld"] = df[f"{pos}_def"] + bonus
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

    return df
