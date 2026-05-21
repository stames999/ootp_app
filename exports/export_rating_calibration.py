"""Hitter-rating calibration sheet — single sheet, no duplicates.

For every key vsL / vsR hitting rating plus speed, picks representative
example players covering each rating value on the 20-80 scale. Players
appear at most once; greedy bin-filling means a player picked to cover
"Power vsR = 60" might also incidentally cover "Gap vsL = 50" — those
incidental hits are listed in the `Covers` column for verification.

Output: `outputs/hitter_rating_calibration.xlsx` (one sheet)
"""
from pathlib import Path

import pandas as pd

SAVE_DIR = Path(
    r"C:\Users\sfwea\OneDrive\Documents\Out of the Park Developments\OOTP Baseball 27"
    r"\saved_games\Rockies Rebuild.lg\import_export\csv"
)
OUT_PATH = Path("outputs/hitter_rating_calibration.xlsx")

POSITION_MAP = {1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B",
                 6: "SS", 7: "LF", 8: "CF", 9: "RF", 10: "DH"}
BATS_MAP = {1: "R", 2: "L", 3: "S"}

# (display label, CSV column) — order also drives bin-fill priority
STATS = [
    ("BABIPvR",   "batting_ratings_vsr_babip"),
    ("BABIPvL",   "batting_ratings_vsl_babip"),
    ("K-avoidvR", "batting_ratings_vsr_strikeouts"),
    ("K-avoidvL", "batting_ratings_vsl_strikeouts"),
    ("PowervR",   "batting_ratings_vsr_power"),
    ("PowervL",   "batting_ratings_vsl_power"),
    ("EyevR",     "batting_ratings_vsr_eye"),
    ("EyevL",     "batting_ratings_vsl_eye"),
    ("GapvR",     "batting_ratings_vsr_gap"),
    ("GapvL",     "batting_ratings_vsl_gap"),
    ("Speed",     "running_ratings_speed"),
]

# How many distinct players we want to cover EACH bin (each at distinct
# rating value). 2 gives a bit of redundancy so a single player isn't
# the only example of a tier.
EXAMPLES_PER_BIN = 2


def team_level_rank(level):
    if level in (1, 2, 3, 4, 5, 6):
        return int(level)
    return 99


def main() -> None:
    players = pd.read_csv(SAVE_DIR / "players.csv", low_memory=False)
    ratings = pd.read_csv(SAVE_DIR / "players_scouted_ratings.csv", low_memory=False)
    teams = pd.read_csv(SAVE_DIR / "teams.csv")

    ratings = ratings[ratings["scouting_coach_id"] == 0].copy()
    ratings = ratings.drop(columns=[
        c for c in ("team_id", "league_id", "position", "role",
                    "scouting_coach_id", "scouting_team_id", "scouting_accuracy")
        if c in ratings.columns
    ])

    team_level = dict(zip(teams["team_id"], teams["level"]))
    team_abbr = dict(zip(teams["team_id"], teams["abbr"]))
    LEVEL_TO_LABEL = {1: "MLB", 2: "AAA", 3: "AA", 4: "A+", 5: "A", 6: "R"}

    def level_label(team_id):
        return LEVEL_TO_LABEL.get(team_level.get(team_id), "R(DLR)/other")

    hitters = players[
        (players["retired"] != 1) & (players["position"] != 1)
    ].copy()
    hitters["Name"] = hitters["first_name"] + " " + hitters["last_name"]
    hitters["Pos"] = hitters["position"].map(POSITION_MAP)
    hitters["Bats"] = hitters["bats"].map(BATS_MAP)
    hitters["Age"] = hitters["age"]
    hitters["Org"] = hitters["team_id"].map(team_abbr).fillna("FREE")
    hitters["Level"] = hitters["team_id"].apply(level_label)
    hitters["_level_rank"] = hitters["team_id"].map(team_level).apply(team_level_rank)

    df = hitters.merge(ratings, on="player_id", how="inner")

    # --------------------------------------------------------------
    # Enumerate every (stat, rating) bin we want covered.
    # Sort bins by RARITY (smallest population first) so the elite-end
    # bins get filled before their handful of qualifying players are
    # consumed by lower-rarity bins.
    # --------------------------------------------------------------
    bins: list[tuple[str, str, int, int]] = []  # (label, col, rating, pop)
    for label, stat_col in STATS:
        stat_max = int(df[stat_col].max())
        stat_max = ((stat_max + 4) // 5) * 5
        for rating in range(20, stat_max + 1, 5):
            pop = int((df[stat_col] == rating).sum())
            if pop > 0:
                bins.append((label, stat_col, rating, pop))
    bins.sort(key=lambda b: b[3])  # rarest first

    # --------------------------------------------------------------
    # Greedy: for each bin, skip if any already-picked player covers
    # it incidentally; otherwise pick the top EXAMPLES_PER_BIN players
    # with that rating who aren't already in the set.
    # --------------------------------------------------------------
    picked_set: set[int] = set()
    primary_coverage: dict[int, list[str]] = {}  # player_id -> ["BABIPvR=50", ...]
    bin_examples_count: dict[tuple[str, int], int] = {}  # (label, rating) -> n picked

    def bin_already_covered(label: str, stat_col: str, rating: int) -> int:
        """Count of already-picked players whose `stat_col == rating`."""
        if not picked_set:
            return 0
        sub = df[df["player_id"].isin(picked_set)]
        return int((sub[stat_col] == rating).sum())

    for label, stat_col, rating, _pop in bins:
        already = bin_already_covered(label, stat_col, rating)
        need = max(0, EXAMPLES_PER_BIN - already)
        if need == 0:
            continue
        candidates = df[(df[stat_col] == rating)
                        & (~df["player_id"].isin(picked_set))]
        if candidates.empty:
            continue
        candidates = candidates.sort_values(
            ["_level_rank", "overall"], ascending=[True, False],
        )
        for _, p in candidates.head(need).iterrows():
            pid = int(p["player_id"])
            picked_set.add(pid)
            primary_coverage.setdefault(pid, []).append(f"{label}={rating}")
        bin_examples_count[(label, rating)] = already + len(candidates.head(need))

    picked_df = df[df["player_id"].isin(picked_set)].copy()

    # Build "Covers" column: enumerate every (stat, rating) bin this
    # player satisfies across all 11 stats (not just the bin they were
    # picked for). Useful for test coverage verification.
    def covers_for_row(row):
        bins = []
        for label, stat_col in STATS:
            bins.append(f"{label}={int(row[stat_col])}")
        return " | ".join(bins)

    picked_df["Covers"] = picked_df.apply(covers_for_row, axis=1)
    picked_df["PickedFor"] = picked_df["player_id"].apply(
        lambda pid: " | ".join(primary_coverage.get(pid, []))
    )

    # Final display
    display_cols = (
        ["Name", "Org", "Level", "Pos", "Age", "Bats"]
        + [c for _, c in STATS]
        + ["PickedFor", "Covers"]
    )
    rename = {c: label for label, c in STATS}
    out = picked_df[display_cols].rename(columns=rename)

    # Sort: level first (MLB top), then position, then name
    pos_order = {"P": 0, "C": 1, "1B": 2, "2B": 3, "3B": 4,
                 "SS": 5, "LF": 6, "CF": 7, "RF": 8, "DH": 9}
    out["_lvl"] = out["Level"].map({"MLB": 0, "AAA": 1, "AA": 2, "A+": 3,
                                       "A": 4, "R": 5, "R(DLR)/other": 6}).fillna(99)
    out["_pos"] = out["Pos"].map(pos_order).fillna(99)
    out = out.sort_values(["_lvl", "_pos", "Name"]).drop(columns=["_lvl", "_pos"])

    # Coverage check: for each bin, count how many picked players have
    # exactly that value (whether they were explicitly picked for that
    # bin or not).
    expected_bins = []
    for label, stat_col in STATS:
        stat_max = int(df[stat_col].max())
        stat_max = ((stat_max + 4) // 5) * 5
        for rating in range(20, stat_max + 1, 5):
            pop = int((df[stat_col] == rating).sum())
            if pop > 0:
                expected_bins.append((label, stat_col, rating))

    picked_subset = df[df["player_id"].isin(picked_set)]
    missing_bins = []
    for label, stat_col, rating in expected_bins:
        n_in_set = int((picked_subset[stat_col] == rating).sum())
        if n_in_set == 0:
            missing_bins.append(f"{label}={rating}")

    OUT_PATH.parent.mkdir(exist_ok=True)
    with pd.ExcelWriter(OUT_PATH, engine="openpyxl") as writer:
        out.to_excel(writer, sheet_name="Calibration", index=False)
        ws = writer.sheets["Calibration"]
        for col_idx, col_name in enumerate(out.columns, 1):
            sample = out[col_name].astype(str).values[:60]
            max_len = max(
                [len(str(col_name))] + [len(s) for s in sample]
            )
            ws.column_dimensions[ws.cell(1, col_idx).column_letter].width = min(
                max_len + 2, 60
            )
        ws.freeze_panes = "B2"

    print(f"Wrote {len(out)} unique players to {OUT_PATH}")
    covered = len(expected_bins) - len(missing_bins)
    print(f"Covered bins: {covered} / {len(expected_bins)}")
    if missing_bins:
        print(f"Bins with no example in chosen set:")
        for b in missing_bins:
            print(f"  - {b}")
    else:
        print("All bins covered.")


if __name__ == "__main__":
    main()
