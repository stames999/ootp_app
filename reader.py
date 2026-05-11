import numpy as np
import pandas as pd

# Note: filepath / pistachio_filepath are referenced as `config.filepath`
# inline (rather than imported here) so callers can monkey-patch
# `config.filepath = some_temp_dir` at runtime — used by the Streamlit
# uploader so the user doesn't need files in any specific local location.
import config
from config import (
    HITTING_STATS_COLUMNS,
    PITCH_MINIMUM_RATING,
    PITCH_RATING_COLUMNS,
    PITCHING_STATS_COLUMNS,
    PLAYERS_COLUMN_RENAMES,
    PLAYERS_COLUMNS,
    POTENTIAL_PITCH_RATING_COLUMNS,
    SCOUTED_RATINGS_COLUMNS,
    SCOUTED_RATINGS_RENAMES,
    club_lookup,
    rename_columns,
)


def load_players() -> pd.DataFrame:
    file = config.filepath / "players.csv"
    df = pd.read_csv(file, usecols=PLAYERS_COLUMNS, low_memory=False)
    # Remove retired players
    df = df[df.retired != 1]
    df = df.drop(columns=["retired"])
    # Rename columns
    for old, new in PLAYERS_COLUMN_RENAMES.items():
        df = rename_columns(df, old, new)
    # Combine first and last name into a single 'name' column
    df["name"] = df["first_name"] + " " + df["last_name"]
    df = df.drop(columns=["first_name", "last_name"])
    # Map numeric org values to team abbreviations using the club lookup
    # first flag minor leaguers for whom team and organisaition IDs are different
    df["minor"] = (df["org"] != df["team_id"]).astype(int)
    # Build the team_id → abbr map from teams.csv (level=1 rows) so
    # historical / alt-history saves get the right abbreviations (a 2004
    # historical save has ANA / FLA / MON / TBD, not the hardcoded
    # LAA / MIA / WSH / TB). Falls back to the hardcoded `club_lookup`
    # when teams.csv is missing — modern saves keep working unchanged.
    # Updates `config.club_lookup` in place so downstream reverse lookups
    # (roster_common._count_dsl_teams) see the same mapping.
    detected = detect_club_lookup(config.filepath)
    if detected is not None:
        config.club_lookup = detected
    df["org"] = df["org"].map(config.club_lookup)
    return df


def add_pitching_career_stats(df: pd.DataFrame) -> pd.DataFrame:
    # The `ip` column this adds is purely cosmetic (display in pitcher
    # tables). The hitter/pitcher classifier in metrics_war now uses
    # `pitches` instead, so this CSV is fully optional.
    file = config.filepath / "players_career_pitching_stats.csv"
    if not file.exists():
        df["ip"] = 0
        return df
    pitching_stats_df = pd.read_csv(
        file, usecols=PITCHING_STATS_COLUMNS, low_memory=False
    )
    # Filter for MLB + combined L/R splits, and most recent season only
    pitching_stats_df = pitching_stats_df[
        (pitching_stats_df["level_id"] == 1) & (pitching_stats_df["split_id"] == 1)
    ]
    max_year = pitching_stats_df["year"].max()
    pitching_stats_df = pitching_stats_df[pitching_stats_df["year"] == max_year]
    # sum innings pitched by player_id and merge into main DataFrame
    pitching_stats_df = (
        pitching_stats_df.groupby("player_id")[["ip"]].sum().reset_index()
    )
    df = pd.merge(df, pitching_stats_df, on="player_id", how="left")
    df["ip"] = df["ip"].fillna(0).astype(int)
    return df


# level_id mapping verified against LAA's 2026 farm trajectory (Trout 1=MLB,
# Cooper Ingle 4→3→2 = A+→AA→AAA, Davalillo 6→4 = R→A+, Laverde 6→4 = R→A+).
# May need re-verification on saves where league_id structure differs.
LEVEL_ID_TO_LEVEL = {
    1: 'MLB',
    2: 'AAA',
    3: 'AA',
    4: 'A+',
    5: 'A',
    6: 'R',
    7: 'R(DLR)',
}


def add_years_at_level(df: pd.DataFrame) -> pd.DataFrame:
    """Add `yrs_<LEVEL>` columns counting how many distinct calendar SEASONS
    each player has played, credited to the HIGHEST level they reached that
    year. A year that spans multiple levels counts as 1 year of service
    time, allocated to the topmost level reached — matching OOTP's
    service-time semantics where promotion supersedes the lower level
    for that year. Sources both career-stats CSVs (hitter and pitcher)
    so the count covers the whole pool. Level mapping uses
    LEVEL_ID_TO_LEVEL above; rows with unknown level_ids are ignored.

    No-op (zeros) if neither career-stats CSV is uploaded — the column
    set is still created so downstream code can rely on it."""
    levels = list(LEVEL_ID_TO_LEVEL.values())
    cols = [f'yrs_{lvl}' for lvl in levels]

    pieces = []
    for fn in ('players_career_batting_stats.csv',
               'players_career_pitching_stats.csv'):
        path = config.filepath / fn
        if not path.exists():
            continue
        sub = pd.read_csv(
            path,
            usecols=['player_id', 'year', 'level_id'],
            low_memory=False,
        )
        sub = sub[sub['level_id'].isin(LEVEL_ID_TO_LEVEL.keys())]
        pieces.append(sub)

    if not pieces:
        for c in cols:
            df[c] = 0
        return df

    combined = pd.concat(pieces, ignore_index=True)
    # Collapse to one row per (player_id, year) at the HIGHEST level
    # reached. LEVEL_ID_TO_LEVEL is keyed by OOTP level_id where 1=MLB
    # (the top), so the smallest level_id per (player_id, year) wins.
    combined = combined.drop_duplicates(['player_id', 'level_id', 'year'])
    combined = (
        combined.sort_values('level_id')
                .drop_duplicates(['player_id', 'year'], keep='first')
    )
    counts = (
        combined.groupby(['player_id', 'level_id'])
        .size()
        .unstack(fill_value=0)
    )
    counts.columns = [f'yrs_{LEVEL_ID_TO_LEVEL[c]}' for c in counts.columns]
    # Ensure all level columns exist in the result, even if unseen
    for c in cols:
        if c not in counts.columns:
            counts[c] = 0
    counts = counts[cols].reset_index()
    df = pd.merge(df, counts, on='player_id', how='left')
    for c in cols:
        df[c] = df[c].fillna(0).astype(int)
    return df


def add_hitting_career_stats(df: pd.DataFrame) -> pd.DataFrame:
    # The `pa` column this adds is purely cosmetic (display in hitter
    # tables). No projection or gate uses it, so this CSV is fully
    # optional — when missing we just default pa to 0.
    file = config.filepath / "players_career_batting_stats.csv"
    if not file.exists():
        df["pa"] = 0
        return df
    hitting_stats_df = pd.read_csv(
        file, usecols=HITTING_STATS_COLUMNS, low_memory=False
    )
    # Filter for MLB + combined L/R splits, and most recent season only
    hitting_stats_df = hitting_stats_df[
        (hitting_stats_df["level_id"] == 1) & (hitting_stats_df["split_id"] == 1)
    ]
    max_year = hitting_stats_df["year"].max()
    hitting_stats_df = hitting_stats_df[hitting_stats_df["year"] == max_year]
    # sum plate appearances by player_id and merge into main DataFrame
    hitting_stats_df = hitting_stats_df.groupby("player_id")[["pa"]].sum().reset_index()
    df = pd.merge(df, hitting_stats_df, on="player_id", how="left")
    df["pa"] = df["pa"].fillna(0).astype(int)
    return df


def add_scouted_ratings(df: pd.DataFrame) -> pd.DataFrame:
    file = config.filepath / "players_scouted_ratings.csv"
    all_rating_columns = (
        SCOUTED_RATINGS_COLUMNS + PITCH_RATING_COLUMNS + POTENTIAL_PITCH_RATING_COLUMNS
    )
    ratings_df = pd.read_csv(file, usecols=all_rating_columns, low_memory=False)
    # Keep only ratings from your scouting director
    # Read config.ID at call time so the Streamlit ratings-source toggle
    # (Head Scout vs OSA) can monkey-patch it before invoking the pipeline.
    filtered = ratings_df[ratings_df["scouting_coach_id"] == config.ID]
    # Defensive auto-correct: if the configured coach_id matches no rows in
    # the current CSV (e.g. config.ID is the repo default 114 from a stale
    # state but the active save's head scout is some other id), detect the
    # save's actual head scout and use that instead. Without this, every
    # rating column merges as NaN, wOBAP floors at the all-50 base rate,
    # and rosters silently come out empty / wrong.
    if len(filtered) == 0 and config.ID != -1:
        detected = detect_head_scout_id(config.filepath)
        if detected is not None and detected != config.ID:
            print(
                f"⚠ config.ID={config.ID} matched no rating rows in "
                f"{file.name}; auto-correcting to coach_id={detected}."
            )
            config.ID = detected
            filtered = ratings_df[ratings_df["scouting_coach_id"] == config.ID]
    ratings_df = filtered.drop(columns=["scouting_coach_id"])
    # Rename the column for clarity
    for old, new in SCOUTED_RATINGS_RENAMES.items():
        ratings_df = rename_columns(ratings_df, old, new)
    df = pd.merge(df, ratings_df, on="player_id", how="left")
    return df


# count 'how many pitches' a pitcher has got based on minimum threshold ratings
def count_pitches(df: pd.DataFrame) -> pd.DataFrame:
    pitch_flags = df[PITCH_RATING_COLUMNS] >= PITCH_MINIMUM_RATING
    df["pitches"] = pitch_flags.astype(int).sum(axis=1)
    potential_pitch_flags = df[POTENTIAL_PITCH_RATING_COLUMNS] >= PITCH_MINIMUM_RATING
    df["pitchesP"] = potential_pitch_flags.astype(int).sum(axis=1)
    df = df.drop(columns=PITCH_RATING_COLUMNS)
    df = df.drop(columns=POTENTIAL_PITCH_RATING_COLUMNS)
    return df


# Note: position eligibility is gated by POSITION_FLOOR (rating-based) in
# metrics_war.calc_war(). The displayed `field` column is then filtered to
# positions whose adjusted WAR is within FIELD_VIABILITY_GAP of best_adj.


def detect_club_lookup(csv_dir):
    """Build a `{team_id: abbr}` map from teams.csv (level=1 rows only).

    Replaces the hardcoded `config.club_lookup` at runtime so historical
    OOTP saves get the correct abbreviations (e.g. 2004 had ANA / FLA /
    MON / TBD, not LAA / MIA / WSH / TB). Modern saves keep working —
    the hardcoded map happens to match a current-day OOTP team layout,
    but level=1 derivation is authoritative for any save.

    Returns None if teams.csv is missing or doesn't have the level/abbr
    columns; callers fall back to the hardcoded `config.club_lookup` in
    that case.
    """
    from pathlib import Path as _Path
    f = _Path(csv_dir) / 'teams.csv'
    if not f.exists():
        return None
    try:
        df = pd.read_csv(
            f,
            usecols=['team_id', 'abbr', 'level'],
            low_memory=False,
        )
    except (ValueError, KeyError):
        return None
    mlb = df[df['level'] == 1]
    if mlb.empty:
        return None
    return {int(r.team_id): str(r.abbr) for r in mlb.itertuples(index=False)}


def detect_head_scout_id(csv_dir):
    """Scan `players_scouted_ratings.csv` and return the most-frequent
    non-OSA `scouting_coach_id` — that's the user's head scout in OOTP.
    Returns None if the CSV is missing or every rating row is OSA (-1).
    Used by both the Streamlit uploader and the CLI `refresh` subcommand
    so the right scout is picked per save without hardcoding `config.ID`."""
    import csv as csv_mod
    from collections import Counter
    from pathlib import Path as _Path
    f = _Path(csv_dir) / 'players_scouted_ratings.csv'
    if not f.exists():
        return None
    counts = Counter()
    with open(f) as fh:
        rdr = csv_mod.DictReader(fh)
        for r in rdr:
            cid = r.get('scouting_coach_id') or ''
            if cid and cid != '-1':
                counts[cid] += 1
    if not counts:
        return None
    return int(counts.most_common(1)[0][0])


def is_flagged(df: pd.DataFrame) -> pd.DataFrame:
    # Read player_ids from text file and convert to integers. Missing
    # flagged.txt is fine — it's just a display marker for the HTML
    # exporter, not roster-affecting.
    flagged_path = config.pistachio_filepath / "flagged.txt"
    if flagged_path.exists():
        with open(flagged_path, "r") as f:
            flagged_ids = [int(line.strip()) for line in f if line.strip().isdigit()]
    else:
        flagged_ids = []

    # Add 'flag' column based on player_id match
    df["flag"] = np.where(df["player_id"].isin(flagged_ids), "flag", "")
    return df
