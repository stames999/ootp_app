# from exporter import export_hitters
# Note: export_org_report (the old standalone HTML report) has been retired —
# its unique features (batting order, R/G estimate) are now rendered directly
# in the xlsx by build_excel.py. The function still lives in exporter.py and
# can be called manually if needed.
import pandas as pd

from exporter import export_html_pages, export_json_pages
from metrics_fielding import calc_fielding_metrics
from metrics_hitting import calc_hitting_metrics, calc_potential_hitting_metrics
from metrics_pitching import calc_pitching_metrics, calc_potential_pitching_metrics
from metrics_war import calc_war
from reader import (
    add_hitting_career_stats,
    add_pitching_career_stats,
    add_scouted_ratings,
    add_years_at_level,
    count_pitches,
    is_flagged,
    load_players,
)


def compute_df() -> 'pd.DataFrame':
    """Run the full metrics pipeline and return the player DataFrame.
    Stops short of any export so callers can reuse the df for different
    downstream artifacts (e.g. an org-report for an arbitrary team)
    without re-running the pipeline."""
    df = load_players()
    df = add_pitching_career_stats(df)
    df = add_hitting_career_stats(df)
    # Years-at-level breakdown is derived from the same career-stats CSVs;
    # surfaces yrs_MLB / yrs_AAA / ... / yrs_R(DLR) columns. Optional —
    # zero-fills if the career CSVs aren't uploaded.
    df = add_years_at_level(df)
    df = add_scouted_ratings(df)
    df = count_pitches(df)
    df = is_flagged(df)
    # `field` column is produced inside calc_war(): it lists positions whose
    # adjusted WAR is within FIELD_VIABILITY_GAP of the player's best_adj.
    # Position eligibility itself is gated by POSITION_FLOOR (rating-based).
    df = calc_pitching_metrics(df)
    df = calc_potential_pitching_metrics(df)
    df = calc_hitting_metrics(df)
    df = calc_potential_hitting_metrics(df)
    df = calc_fielding_metrics(df)
    df = calc_war(df)
    df = _flag_two_way_players(df)
    df = _flag_two_way_best_side(df)
    df = _restrict_two_way_sp_to_dh(df)
    # Sort by scarcity-adjusted WAR — that's the player's "true value"
    # accounting for positional difficulty (see metrics_war.calc_war).
    df = df.sort_values(by="best_adj", ascending=False)
    return df


def _flag_two_way_players(df):
    """Flag players whose CURRENT batting AND pitching are BOTH
    MLB-tier — i.e. a genuine two-way star like Ohtani. Tight gate
    because OOTP's default ratings produce plausible-looking
    wOBA / pwOBA for most players (a regular MLB position player
    has SOME computed pwOBA from default pitching ratings; a regular
    MLB pitcher has SOME computed wOBA from default batting). Only
    players whose BOTH metrics clear the MLB threshold are flagged
    as true two-way and admitted to both pools.

    Thresholds:
      - `wOBA >= WOBA_MIN_HITTER['MLB']` (.280) — real MLB-tier bat
      - `pwOBA <= PWOBA_MAX['MLB']` (.345) — real MLB-tier arm

    Calibration: in Rockies Rebuild + Corbin HoF, this flags ONLY
    Shohei Ohtani (LAD, wOBA=.429, pwOBA=.310). Looser thresholds
    were producing 99 false positives (regular MLB position players
    and pitchers with default cross-side ratings).
    """
    from config import WOBA_MIN_HITTER, PWOBA_MAX
    wOBA_ok = df["wOBA"].fillna(0) >= WOBA_MIN_HITTER["MLB"]
    pwOBA_ok = df["pwOBA"].fillna(1.0) <= PWOBA_MAX["MLB"]
    df["is_two_way"] = (wOBA_ok & pwOBA_ok).astype(bool)
    return df


def _restrict_two_way_sp_to_dh(df):
    """SP-viable two-way players are limited to DH on the hitter side
    (Shohei rule — an SP can DH on non-pitching days but can't
    field). NaN out their non-DH `*_adj`, `*_fld`, raw `*` columns
    so the Hungarian assignment naturally places them at DH only.
    Then fix the derived `pos_adj`, `posP_adj`, `field`, `best_adj`,
    `bestP_adj` columns to reflect the DH-only constraint.

    RP-only two-way are NOT restricted — a reliever can field on
    days they're not pitching. (No RP-only two-way exist in current
    data, but the rule is correct.)
    """
    if not df["is_two_way"].any():
        return df
    sp_viable = df["sp_warP"].notna() | df["sp_war"].notna()
    mask = df["is_two_way"] & sp_viable
    if not mask.any():
        return df

    non_dh_positions = ('C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF')
    nan_cols = []
    for pos in non_dh_positions:
        nan_cols.extend([pos, f'{pos}_adj', f'{pos}_fld', f'{pos}P', f'{pos}P_adj'])
    for col in nan_cols:
        if col in df.columns:
            df.loc[mask, col] = pd.NA

    # Force display columns to DH
    if 'pos_adj' in df.columns:
        df.loc[mask, 'pos_adj'] = 'DH'
    if 'posP_adj' in df.columns:
        df.loc[mask, 'posP_adj'] = 'DH'
    if 'field' in df.columns:
        df.loc[mask, 'field'] = 'DH'

    # Recompute best_adj / bestP_adj from the surviving DH columns
    if 'DH_adj' in df.columns and 'best_adj' in df.columns:
        df.loc[mask, 'best_adj'] = df.loc[mask, 'DH_adj']
    if 'DHP_adj' in df.columns and 'bestP_adj' in df.columns:
        df.loc[mask, 'bestP_adj'] = df.loc[mask, 'DHP_adj']
    return df


def _flag_two_way_best_side(df):
    """For each two-way player, pick the side with higher expected WAR
    contribution. Approximates the marginal-replacement comparison —
    the side where the player's absence would force the team to fill
    the slot with a weaker replacement.

    Hitter side: `war_hitting` (bat-only WAR at full MLB workload).
    Pitcher side: max of `sp_war` and `rp_war` (whichever role they
    qualify for, take the better).

    Two-way players are admitted to ONLY their best-side pool by the
    exporter filters. The user's intent: 'they should only count on
    whichever side allows the best player to come into the team'.
    """
    hitter_war = df["war_hitting"].fillna(-99)
    sp = df["sp_war"].fillna(-99) if "sp_war" in df.columns else -99
    rp = df["rp_war"].fillna(-99) if "rp_war" in df.columns else -99
    pitcher_war = pd.concat([df["sp_war"], df["rp_war"]], axis=1).max(axis=1).fillna(-99)
    df["tw_best_side"] = ""
    df.loc[df["is_two_way"] & (hitter_war > pitcher_war), "tw_best_side"] = "hitter"
    df.loc[df["is_two_way"] & (hitter_war <= pitcher_war), "tw_best_side"] = "pitcher"
    return df


def main():
    df = compute_df()
    export_html_pages(df)
    export_json_pages(df)


if __name__ == "__main__":
    main()
