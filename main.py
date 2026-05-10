# from exporter import export_hitters
# Note: export_org_report (the old standalone HTML report) has been retired —
# its unique features (batting order, R/G estimate) are now rendered directly
# in the xlsx by build_excel.py. The function still lives in exporter.py and
# can be called manually if needed.
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
    # Sort by scarcity-adjusted WAR — that's the player's "true value"
    # accounting for positional difficulty (see metrics_war.calc_war).
    df = df.sort_values(by="best_adj", ascending=False)
    return df


def _flag_two_way_players(df):
    """Flag players who are scouted as both pitchers AND meaningful hitters.

    OOTP marks `position == 1` for any pitcher, including Ohtani-types whose
    batting is also competitive. The hitter pipeline filters out
    `position == 1` rows, so without this flag a two-way player's bat is
    invisible to roster construction. We mark them with `is_two_way = True`
    and pre-compute their level ceiling on the better-of-two-skills basis,
    so both builders can pin them to the same level.

    Heuristic — must satisfy ALL of:
      - `position == 1` (OOTP marks them as a pitcher)
      - `age <= 24` (active prospects, not legacy conversions). OOTP often
        keeps stale batting ratings on older converted-from-position-player
        pitchers; the age cap filters them out. Real two-way prospects
        develop young.
      - `powP, eyeP, gapP >= 40` (meaningful potential — OOTP defaults
        pitcher batting to 5-25; clearing 40 across all three rate skills
        means a deliberate two-way scouting profile)
      - `wOBAP >= 0.270` (a holistic check — not just individual ratings).
        Roughly the threshold for a useful bench bat in the lower minors.

    Calibration: with these gates ~1 in 230 pitchers is flagged in a
    typical save (~30-40 across the full population) — matches the user's
    observation that Caden Grice / Patrick Forbes were the two AZ
    two-way players in the Corbin HoF save.
    """
    import numpy as np
    is_pitcher = df["position"] == 1
    young = df["age"].fillna(99) <= 24
    bat_ok = (
        (df["powP"].fillna(0) >= 40)
        & (df["eyeP"].fillna(0) >= 40)
        & (df["gapP"].fillna(0) >= 40)
    )
    woba_ok = df["wOBAP"].fillna(0) >= 0.270
    df["is_two_way"] = (is_pitcher & young & bat_ok & woba_ok).astype(bool)

    # Two-way effective top: the LOWER index (= higher level) of the
    # hitter-side and pitcher-side ceilings — the better skill drives
    # promotion. Stored as integer level index; non-two-way rows get NaN.
    from build_system import woba_max_level
    from build_pitcher_system import pwoba_top_level

    def combined_top(row):
        if not row.get("is_two_way"):
            return np.nan
        d = row.to_dict()
        h_top = woba_max_level(d)
        p_top = pwoba_top_level(d)
        return min(h_top, p_top)

    df["tw_target_lvl"] = df.apply(combined_top, axis=1)
    return df


def main():
    df = compute_df()
    export_html_pages(df)
    export_json_pages(df)


if __name__ == "__main__":
    main()
