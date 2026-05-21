"""Curated sampler of hitter archetypes across the league.

Scans every non-pitcher in the scouted-ratings pool and picks
representative examples for each archetype. Archetypes use the
underlying skills (BABIP + K-avoid + Power + Eye) instead of the
derived `contact` rating, since contact is itself a composite of BABIP
and K-avoid and decomposing them is more informative.

Outputs to `outputs/hitter_archetypes.xlsx`.
"""
from pathlib import Path

import pandas as pd

SAVE_DIR = Path(
    r"C:\Users\sfwea\OneDrive\Documents\Out of the Park Developments\OOTP Baseball 27"
    r"\saved_games\Rockies Rebuild.lg\import_export\csv"
)
OUT_PATH = Path("outputs/hitter_archetypes_v2.xlsx")

POSITION_MAP = {1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B",
                 6: "SS", 7: "LF", 8: "CF", 9: "RF", 10: "DH"}
BATS_MAP = {1: "R", 2: "L", 3: "S"}

# Underlying skills on the 20-80 scale. Higher = better for all of these
# (K_AVOID column = batter's ability to AVOID K, so higher = harder to
# strike out).
BABIP = "batting_ratings_overall_babip"
K_AVOID = "batting_ratings_overall_strikeouts"
POWER = "batting_ratings_overall_power"
EYE = "batting_ratings_overall_eye"
GAP = "batting_ratings_overall_gap"
SPEED = "running_ratings_speed"
STEAL = "running_ratings_stealing"
BASERUN = "running_ratings_baserunning"


def main() -> None:
    players = pd.read_csv(SAVE_DIR / "players.csv", low_memory=False)
    ratings = pd.read_csv(SAVE_DIR / "players_scouted_ratings.csv", low_memory=False)
    teams = pd.read_csv(SAVE_DIR / "teams.csv")

    # Dedupe ratings and strip ID/admin cols that collide on merge.
    ratings = ratings[ratings["scouting_coach_id"] == 0].copy()
    ratings = ratings.drop(columns=[
        c for c in ("team_id", "league_id", "position", "role",
                    "scouting_coach_id", "scouting_team_id", "scouting_accuracy")
        if c in ratings.columns
    ])

    # Active non-pitchers
    hitters = players[
        (players["retired"] != 1) & (players["position"] != 1)
    ].copy()
    hitters["Name"] = hitters["first_name"] + " " + hitters["last_name"]
    hitters["Pos"] = hitters["position"].map(POSITION_MAP)
    hitters["Bats"] = hitters["bats"].map(BATS_MAP)
    hitters["Age"] = hitters["age"]

    team_name_map = dict(zip(teams["team_id"], teams["name"]))
    team_abbr_map = dict(zip(teams["team_id"], teams["abbr"]))
    hitters["Team"] = hitters["team_id"].map(team_name_map)
    hitters["Org"] = hitters["team_id"].map(team_abbr_map)

    df = hitters.merge(ratings, on="player_id", how="inner")

    # ------------------------------------------------------------------
    # Archetypes built on BABIP + K-avoid + Power + Eye. Each entry is
    # (label, predicate, sort_key, N_examples).
    # ------------------------------------------------------------------
    archetypes: list[tuple[str, callable, callable, int]] = [
        (
            "Elite all-around (high in every column)",
            lambda r: r[BABIP] >= 55 and r[K_AVOID] >= 50
                      and r[POWER] >= 65 and r[EYE] >= 65,
            lambda r: -(r[BABIP] + r[K_AVOID] + r[POWER] + r[EYE]),
            5,
        ),
        (
            "Plus across the board (4-tool, no peak)",
            lambda r: (50 <= r[BABIP] <= 65 and 50 <= r[K_AVOID] <= 65
                       and 55 <= r[POWER] <= 65 and 55 <= r[EYE] <= 65),
            lambda r: -(r[BABIP] + r[K_AVOID] + r[POWER] + r[EYE]),
            4,
        ),
        (
            "Average across the board",
            lambda r: all(40 <= r[c] <= 55 for c in (BABIP, K_AVOID, POWER, EYE)),
            lambda r: (abs(r[BABIP] - 50) + abs(r[K_AVOID] - 50)
                       + abs(r[POWER] - 50) + abs(r[EYE] - 50)),
            4,
        ),
        (
            "All-floor (terrible across the board)",
            lambda r: all(r[c] <= 25 for c in (BABIP, K_AVOID, POWER, EYE, GAP)),
            lambda r: r[BABIP] + r[K_AVOID] + r[POWER] + r[EYE] + r[GAP],
            4,
        ),
        (
            "Hard contact, no walks/power (BABIP-driven slap)",
            lambda r: r[BABIP] >= 60 and r[K_AVOID] >= 55
                      and r[POWER] <= 30 and r[EYE] <= 40,
            lambda r: -(r[BABIP] + r[K_AVOID]) + r[POWER] + r[EYE],
            4,
        ),
        (
            "Bat-on-ball, no power (high K-avoid, low POWER)",
            lambda r: r[K_AVOID] >= 60 and r[POWER] <= 30 and r[GAP] <= 35,
            lambda r: -r[K_AVOID] + r[POWER],
            4,
        ),
        (
            "Three-true-outcomes (huge power, huge eye, K-prone)",
            lambda r: r[POWER] >= 65 and r[EYE] >= 60 and r[K_AVOID] <= 40,
            lambda r: r[K_AVOID] - r[POWER] - r[EYE],
            4,
        ),
        (
            "Pure power (big power, contact-skill issues)",
            lambda r: r[POWER] >= 65 and r[BABIP] <= 35 and r[K_AVOID] <= 40,
            lambda r: -(r[POWER]) + r[BABIP] + r[K_AVOID],
            4,
        ),
        (
            "Big power + above-avg contact skills (rare)",
            lambda r: r[POWER] >= 65 and r[BABIP] >= 50 and r[K_AVOID] >= 50,
            lambda r: -(r[POWER] + r[BABIP] + r[K_AVOID]),
            4,
        ),
        (
            "All-eye (walks but nothing else)",
            lambda r: r[EYE] >= 60 and r[POWER] <= 35
                      and r[BABIP] <= 40 and r[K_AVOID] <= 40,
            lambda r: -r[EYE] + r[POWER] + r[BABIP] + r[K_AVOID],
            4,
        ),
        (
            "Free swinger (no eye, decent power)",
            lambda r: r[EYE] <= 25 and r[POWER] >= 45,
            lambda r: r[EYE] - r[POWER],
            4,
        ),
        (
            "Speed merchant (top speed, light bat)",
            lambda r: r[SPEED] >= 70 and r[POWER] <= 30,
            lambda r: -r[SPEED] + r[POWER],
            4,
        ),
        (
            "Speed + bat-on-ball, no power",
            lambda r: r[SPEED] >= 65 and r[K_AVOID] >= 55 and r[POWER] <= 30,
            lambda r: -(r[SPEED] + r[K_AVOID]) + r[POWER],
            4,
        ),
        (
            "Glove-first (no offense, premium position)",
            # All-low offense AND plays a premium glove (C/SS/CF).
            lambda r: (r[BABIP] <= 30 and r[K_AVOID] <= 35 and r[POWER] <= 30
                       and r[EYE] <= 40 and r["Pos"] in ("C", "SS", "CF")),
            lambda r: r[BABIP] + r[K_AVOID] + r[POWER] + r[EYE],
            4,
        ),
        (
            "Bunting specialist",
            lambda r: r["batting_ratings_misc_bunt"] >= 65
                      and r["batting_ratings_misc_bunt_for_hit"] >= 65,
            lambda r: -(r["batting_ratings_misc_bunt"]
                        + r["batting_ratings_misc_bunt_for_hit"]),
            3,
        ),
    ]

    selected = []
    seen_ids = set()
    archetype_counts = {}

    for label, predicate, sort_key, n in archetypes:
        matches = df[df.apply(predicate, axis=1)].copy()
        if matches.empty:
            archetype_counts[label] = 0
            continue
        matches["_sort"] = matches.apply(sort_key, axis=1)
        matches = matches.sort_values("_sort")
        picked = 0
        for _, row in matches.iterrows():
            if row["player_id"] in seen_ids:
                continue
            row_dict = row.to_dict()
            row_dict["Archetype"] = label
            selected.append(row_dict)
            seen_ids.add(row["player_id"])
            picked += 1
            if picked >= n:
                break
        archetype_counts[label] = picked

    out = pd.DataFrame(selected)

    # Display columns — dropped the derived `contact` column per analyst
    # preference; show BABIP + K-avoid + Power + Eye as the primary
    # offensive skill grid.
    display_cols = [
        "Archetype", "Name", "Org", "Team", "Pos", "Age", "Bats",
        BABIP, K_AVOID, POWER, EYE, GAP,
        SPEED, STEAL, BASERUN,
        "batting_ratings_misc_bunt", "batting_ratings_misc_bunt_for_hit",
        "overall", "talent",
    ]
    rename = {
        BABIP: "BABIP", K_AVOID: "K-avoid", POWER: "Power", EYE: "Eye", GAP: "Gap",
        SPEED: "Speed", STEAL: "Stealing", BASERUN: "Baserun",
        "batting_ratings_misc_bunt": "Bunt",
        "batting_ratings_misc_bunt_for_hit": "BuntHit",
        "overall": "Overall(sum)", "talent": "Talent(sum)",
    }
    out_display = out[display_cols].rename(columns=rename)

    OUT_PATH.parent.mkdir(exist_ok=True)
    with pd.ExcelWriter(OUT_PATH, engine="openpyxl") as writer:
        out_display.to_excel(writer, sheet_name="Hitter archetypes", index=False)
        ws = writer.sheets["Hitter archetypes"]
        for col_idx, col_name in enumerate(out_display.columns, 1):
            max_len = max(
                len(str(col_name)),
                *(len(str(v)) for v in out_display[col_name].astype(str).values[:80])
            )
            ws.column_dimensions[ws.cell(1, col_idx).column_letter].width = min(
                max_len + 2, 38
            )
        ws.freeze_panes = "C2"

    print(f"Wrote {len(out_display)} players to {OUT_PATH}")
    print()
    print("Archetype coverage:")
    for label, _, _, n in archetypes:
        found = archetype_counts.get(label, 0)
        flag = " " if found else " <- no examples found"
        print(f"  {label:<55}  {found}/{n}{flag}")


if __name__ == "__main__":
    main()
