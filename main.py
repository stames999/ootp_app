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


def compute_df():
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
    # Sort by scarcity-adjusted WAR — that's the player's "true value"
    # accounting for positional difficulty (see metrics_war.calc_war).
    df = df.sort_values(by="best_adj", ascending=False)
    return df


def _flag_two_way_players(df):
    """Flag players whose CURRENT batting AND pitching are both
    admissible at SOME meaningful level. Symmetric — captures
    Ohtani-types (OOTP `position != 1`, primary bat with real
    scouted pitching ratings) AND pitcher-types with real current
    bats. The OOTP `position` field is incidental; what matters is
    whether both `wOBA` and `pwOBA` produce admissible level
    ceilings.

    The `_flag_two_way_best_side()` step (called next from
    `compute_df`) picks which side gets the roster slot based on
    higher expected WAR contribution.

    Thresholds borrow the cascade's own per-level admissibility:
      - `wOBA >= WOBA_MIN_HITTER['A']` (.200) — playable at A or above
      - `pwOBA <= PWOBA_MAX['R']` — admissible as a pitcher at R or above

    Players with low CURRENT wOBA (e.g. Tolle .084, default pitcher
    batting) won't pass the bat test → not flagged → pitcher-only.
    Ohtani's wOBA=.424 and computed pwOBA from his real scouted
    pitching ratings → flagged.
    """
    from config import WOBA_MIN_HITTER, PWOBA_MAX
    wOBA_ok = df["wOBA"].fillna(0) >= WOBA_MIN_HITTER["A"]
    pwOBA_ok = df["pwOBA"].fillna(1.0) <= PWOBA_MAX["R"]
    df["is_two_way"] = (wOBA_ok & pwOBA_ok).astype(bool)
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
