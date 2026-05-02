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
    df = add_scouted_ratings(df)
    df = count_pitches(df)
    df = is_flagged(df)
    # `field` column is now produced by calc_war() based on POSITION_VIABILITY_GAP
    df = calc_pitching_metrics(df)
    df = calc_potential_pitching_metrics(df)
    df = calc_hitting_metrics(df)
    df = calc_potential_hitting_metrics(df)
    df = calc_fielding_metrics(df)
    df = calc_war(df)
    # Sort by scarcity-adjusted WAR — that's the player's "true value"
    # accounting for positional difficulty (see metrics_war.calc_war).
    df = df.sort_values(by="best_adj", ascending=False)
    return df


def main():
    df = compute_df()
    export_html_pages(df)
    export_json_pages(df)


if __name__ == "__main__":
    main()
