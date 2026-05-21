"""One-shot export: Twins MLB + AAA player ratings from Rockies Rebuild save.

Pulls scouted ratings (20-80 scale for per-attribute, aggregate scores for
`overall`/`talent`) for every player on Minnesota's MLB roster and St. Paul
Saints (AAA affiliate). Outputs to `outputs/MIN_MLB_AAA_ratings.xlsx`.
"""
from pathlib import Path

import pandas as pd

SAVE_DIR = Path(
    r"C:\Users\sfwea\OneDrive\Documents\Out of the Park Developments\OOTP Baseball 27"
    r"\saved_games\Rockies Rebuild.lg\import_export\csv"
)
OUT_PATH = Path("outputs/MIN_MLB_AAA_ratings.xlsx")

POSITION_MAP = {1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B",
                 6: "SS", 7: "LF", 8: "CF", 9: "RF", 10: "DH"}
BATS_MAP = {1: "R", 2: "L", 3: "S"}
THROWS_MAP = {1: "R", 2: "L"}
POS_ORDER = {"P": 0, "C": 1, "1B": 2, "2B": 3, "3B": 4,
             "SS": 5, "LF": 6, "CF": 7, "RF": 8, "DH": 9}


def categorise(col: str) -> tuple[int, str]:
    """Group rating columns by category so the Excel column order is
    readable (running → hitting → pitching → fielding → summary)."""
    if col.startswith("running_ratings_"):                   return (1, col)
    if col.startswith("batting_ratings_overall_"):           return (2, col)
    if col.startswith("batting_ratings_vsr_"):               return (3, col)
    if col.startswith("batting_ratings_vsl_"):               return (4, col)
    if col.startswith("batting_ratings_talent_"):            return (5, col)
    if col.startswith("batting_ratings_misc_"):              return (6, col)
    if col.startswith("pitching_ratings_overall_"):          return (7, col)
    if col.startswith("pitching_ratings_vsr_"):              return (8, col)
    if col.startswith("pitching_ratings_vsl_"):              return (9, col)
    if (col.startswith("pitching_ratings_talent_")
            and "pitches" not in col):                       return (10, col)
    if col.startswith("pitching_ratings_pitches_talent_"):   return (12, col)
    if col.startswith("pitching_ratings_pitches_"):          return (11, col)
    if col.startswith("pitching_ratings_misc_") or col == "pitching_ratings_babip":
                                                              return (13, col)
    if col.startswith("fielding_ratings_"):                  return (14, col)
    if col.startswith("fielding_rating_"):                   return (15, col)
    if col in ("overall", "overall_rating",
               "talent", "talent_rating"):                    return (16, col)
    return (99, col)


def main() -> None:
    players = pd.read_csv(SAVE_DIR / "players.csv", low_memory=False)
    ratings = pd.read_csv(SAVE_DIR / "players_scouted_ratings.csv", low_memory=False)
    teams = pd.read_csv(SAVE_DIR / "teams.csv")

    twins_mlb_id = teams[(teams["abbr"] == "MIN") & (teams["level"] == 1)]["team_id"].iloc[0]
    twins_aaa_id = teams[
        (teams["parent_team_id"] == twins_mlb_id) & (teams["level"] == 2)
    ]["team_id"].iloc[0]
    team_name_map = dict(zip(teams["team_id"], teams["name"]))
    level_label = {twins_mlb_id: "MLB", twins_aaa_id: "AAA"}

    # Twins MLB + AAA players, exclude retired
    twins_players = players[
        players["team_id"].isin([twins_mlb_id, twins_aaa_id])
        & (players["retired"] != 1)
    ].copy()
    print(f"Found {len(twins_players)} Twins MLB+AAA players")

    twins_players["Name"] = twins_players["first_name"] + " " + twins_players["last_name"]
    twins_players["Team"] = twins_players["team_id"].map(team_name_map)
    twins_players["Level"] = twins_players["team_id"].map(level_label)
    twins_players["Pos"] = twins_players["position"].map(POSITION_MAP)
    twins_players["Bats"] = twins_players["bats"].map(BATS_MAP)
    twins_players["Throws"] = twins_players["throws"].map(THROWS_MAP)
    twins_players["Age"] = twins_players["age"]

    # players_scouted_ratings.csv has two rows per player (scouting_coach_id
    # -1 = OSA, 0 = team scout) with identical values. Dedupe by taking the
    # team-scout row (matches what's shown in OOTP UI for the team owner).
    ratings_dedup = ratings[ratings["scouting_coach_id"] == 0].copy()

    # Drop ID/admin columns from ratings before merging
    drop_cols = ["team_id", "league_id", "position", "role",
                 "scouting_coach_id", "scouting_team_id", "scouting_accuracy"]
    ratings_clean = ratings_dedup.drop(
        columns=[c for c in drop_cols if c in ratings_dedup.columns]
    )

    merged = twins_players.merge(ratings_clean, on="player_id", how="left")

    identity_cols = ["Name", "Team", "Level", "Pos", "Age", "Bats", "Throws"]
    rating_cols = [c for c in ratings_clean.columns if c != "player_id"]
    rating_cols_ordered = [c for _, c in sorted([categorise(c) for c in rating_cols])]

    out = merged[identity_cols + rating_cols_ordered].copy()

    # Sort: MLB first, then AAA; within each, by position then name
    out["_lvl_sort"] = out["Level"].map({"MLB": 0, "AAA": 1})
    out["_pos_sort"] = out["Pos"].map(POS_ORDER).fillna(99)
    out = out.sort_values(["_lvl_sort", "_pos_sort", "Name"]).drop(
        columns=["_lvl_sort", "_pos_sort"]
    )

    OUT_PATH.parent.mkdir(exist_ok=True)
    with pd.ExcelWriter(OUT_PATH, engine="openpyxl") as writer:
        out.to_excel(writer, sheet_name="Twins MLB+AAA ratings", index=False)
        ws = writer.sheets["Twins MLB+AAA ratings"]
        # Auto-width
        for col_idx, col_name in enumerate(out.columns, 1):
            max_len = max(
                len(str(col_name)),
                *(len(str(v)) for v in out[col_name].astype(str).values[:80])
            )
            ws.column_dimensions[ws.cell(1, col_idx).column_letter].width = min(
                max_len + 2, 30
            )
        # Freeze header + identity columns
        ws.freeze_panes = "H2"

    print(f"Wrote {len(out)} rows x {len(out.columns)} cols to {OUT_PATH}")
    print()
    print("Scale notes:")
    print("  - Per-attribute ratings (contact, gap, eye, stuff, control, etc.)")
    print("    are on OOTP's 20-80 scale.")
    print("  - 'overall' / 'talent' columns are aggregate scores (sum-of-attrs),")
    print("    NOT on 20-80 — typical range ~80-200.")
    print()
    print("Roster split:")
    print(out.groupby(["Level", "Pos"]).size().unstack(fill_value=0))


if __name__ == "__main__":
    main()
