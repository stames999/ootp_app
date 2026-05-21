"""Pitcher-rating calibration pool — one curated set covering every
5-step rating value across every key pitcher dimension.

Same shape as the hitter calibration: one sheet, one row per pitcher,
no duplicates. The user fills in OOTP's in-game projection stats
(ERA, K/9, BB/9, HR/9, WHIP, BABIP-against, etc.) for each row, and
then we regress those projections against the rating columns to build
the v2 pitcher predictor.

Coverage targets (each 5-step value gets at least 2 examples):
  - Stuff vsR / vsL
  - Movement vsR / vsL
  - Control vsR / vsL
  - HRA vsR / vsL
  - pBABIP vsR / vsL
  - Velocity (mph — not 20-80 scale, but binned)
  - Stamina (binned)
  - Arm slot (binned)
  - GB/FB ratio (binned)

Diversity rows (regardless of bin priority — add explicit examples):
  - Pitch-arsenal types: 2-pitch fastball/slider, 4-pitch starter,
    knuckleballer, sinker-baller, splitter/forkball specialist
  - Throw-hand mix (LHP / RHP)
  - Role mix (high-stamina SP, swingman, pure RP)

Output: `outputs/pitcher_rating_calibration.xlsx`
"""
from pathlib import Path

import pandas as pd

SAVE_DIR = Path(
    r"C:\Users\sfwea\OneDrive\Documents\Out of the Park Developments\OOTP Baseball 27"
    r"\saved_games\Rockies Rebuild.lg\import_export\csv"
)
OUT_PATH = Path("outputs/pitcher_rating_calibration.xlsx")

THROWS_MAP = {1: "R", 2: "L"}

# Main pitcher 20-80 ratings to cover (label, CSV column)
STATS_20_80 = [
    ("StuffvR",      "pitching_ratings_vsr_stuff"),
    ("StuffvL",      "pitching_ratings_vsl_stuff"),
    ("MovementvR",   "pitching_ratings_vsr_movement"),
    ("MovementvL",   "pitching_ratings_vsl_movement"),
    ("ControlvR",    "pitching_ratings_vsr_control"),
    ("ControlvL",    "pitching_ratings_vsl_control"),
    ("HRAvR",        "pitching_ratings_vsr_hra"),
    ("HRAvL",        "pitching_ratings_vsl_hra"),
    ("pBABIPvR",     "pitching_ratings_vsr_pbabip"),
    ("pBABIPvL",     "pitching_ratings_vsl_pbabip"),
]

# Pitch arsenal — separate spread (20-80, but rating 0 means "doesn't throw")
PITCHES = [
    ("Fastball",     "pitching_ratings_pitches_fastball"),
    ("Slider",       "pitching_ratings_pitches_slider"),
    ("Curveball",    "pitching_ratings_pitches_curveball"),
    ("Changeup",     "pitching_ratings_pitches_changeup"),
    ("Sinker",       "pitching_ratings_pitches_sinker"),
    ("Splitter",     "pitching_ratings_pitches_splitter"),
    ("Cutter",       "pitching_ratings_pitches_cutter"),
    ("CircleCh",     "pitching_ratings_pitches_circlechange"),
    ("Knucklecurve", "pitching_ratings_pitches_knucklecurve"),
    ("Knuckleball",  "pitching_ratings_pitches_knuckleball"),
    ("Forkball",     "pitching_ratings_pitches_forkball"),
    ("Screwball",    "pitching_ratings_pitches_screwball"),
]

# Misc columns — not 20-80 scale, but binned for diversity
MISC = [
    ("Velocity",     "pitching_ratings_misc_velocity"),
    ("VelocityTgt",  "pitching_ratings_misc_velocity_target"),
    ("ArmSlot",      "pitching_ratings_misc_arm_slot"),
    ("Stamina",      "pitching_ratings_misc_stamina"),
    ("GroundFly",    "pitching_ratings_misc_ground_fly"),
    ("Hold",         "pitching_ratings_misc_hold"),
    ("HP",           "pitching_ratings_overall_hp"),
    ("Balk",         "pitching_ratings_overall_balk"),
    ("WildPitch",    "pitching_ratings_overall_wild_pitch"),
]

EXAMPLES_PER_BIN = 2


def team_level_rank(level):
    return int(level) if level in (1, 2, 3, 4, 5, 6) else 99


def main() -> None:
    players = pd.read_csv(SAVE_DIR / "players.csv", low_memory=False)
    ratings = pd.read_csv(SAVE_DIR / "players_scouted_ratings.csv", low_memory=False)
    teams = pd.read_csv(SAVE_DIR / "teams.csv")

    # Dedupe + strip ID/admin
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

    # Pitchers only (position == 1), non-retired
    pitchers = players[(players["retired"] != 1) & (players["position"] == 1)].copy()
    pitchers["Name"] = pitchers["first_name"] + " " + pitchers["last_name"]
    pitchers["Throws"] = pitchers["throws"].map(THROWS_MAP)
    pitchers["Age"] = pitchers["age"]
    pitchers["Org"] = pitchers["team_id"].map(team_abbr).fillna("FREE")
    pitchers["Level"] = pitchers["team_id"].apply(level_label)
    pitchers["_level_rank"] = pitchers["team_id"].map(team_level).apply(team_level_rank)

    df = pitchers.merge(ratings, on="player_id", how="inner")
    print(f"Pool: {len(df)} pitchers (active, non-retired)")

    # ----------------------------------------------------------------
    # Enumerate (stat, rating-value) bins in rarity-first order.
    # ----------------------------------------------------------------
    all_bins = []  # (label, col, value, pop)

    # 20-80 ratings: every 5-step value
    for label, col in STATS_20_80:
        if col not in df.columns:
            continue
        for v in range(20, int(df[col].max()) + 1, 5):
            pop = int((df[col] == v).sum())
            if pop > 0:
                all_bins.append((label, col, v, pop))

    # Pitches: only flag VALUES > 0 (a player either throws this pitch
    # or doesn't). For pitchers with the pitch, sample at 20-step
    # rating granularity (20, 40, 60, 80).
    for label, col in PITCHES:
        if col not in df.columns:
            continue
        for v in range(20, int(df[col].max()) + 1, 10):
            pop = int((df[col] == v).sum())
            if pop > 0:
                all_bins.append((f"{label}={v}", col, v, pop))

    # Misc: bin by quintile, label as low/mid/high
    for label, col in MISC:
        if col not in df.columns:
            continue
        vals = df[col].dropna()
        if vals.empty:
            continue
        q = vals.quantile([0.1, 0.3, 0.5, 0.7, 0.9]).values
        bin_centers = [int(round(v)) for v in q]
        for v in sorted(set(bin_centers)):
            pop = int((df[col] == v).sum())
            if pop == 0:
                # nearest neighbor — these are real-valued, find closest unique value
                # actually the misc cols are mostly integer-valued, but if not just skip
                continue
            all_bins.append((f"{label}~{v}", col, v, pop))

    # Sort by rarity ascending (rare bins first to lock in elites)
    all_bins.sort(key=lambda b: b[3])

    # ----------------------------------------------------------------
    # Greedy fill: skip bins already covered by previously-picked
    # players' rating profiles.
    # ----------------------------------------------------------------
    picked_set: set[int] = set()
    primary_coverage: dict[int, list[str]] = {}

    def bin_already_covered(col: str, value: int) -> int:
        if not picked_set:
            return 0
        sub = df[df["player_id"].isin(picked_set)]
        return int((sub[col] == value).sum())

    for label, col, value, _pop in all_bins:
        already = bin_already_covered(col, value)
        need = max(0, EXAMPLES_PER_BIN - already)
        if need == 0:
            continue
        candidates = df[(df[col] == value) & (~df["player_id"].isin(picked_set))]
        if candidates.empty:
            continue
        candidates = candidates.sort_values(
            ["_level_rank", "overall"], ascending=[True, False],
        )
        for _, p in candidates.head(need).iterrows():
            pid = int(p["player_id"])
            picked_set.add(pid)
            primary_coverage.setdefault(pid, []).append(f"{label}={value}")

    # ----------------------------------------------------------------
    # Add explicit diversity rows: archetype pitchers regardless of
    # bin priority. Each archetype gets 2 examples.
    # ----------------------------------------------------------------
    arche_specs = [
        ("Knuckleballer",
         lambda r: r.get("pitching_ratings_pitches_knuckleball", 0) >= 40),
        ("Sinker-baller",
         lambda r: r.get("pitching_ratings_pitches_sinker", 0) >= 60
                   and r.get("pitching_ratings_misc_ground_fly", 0) >= 60),
        ("Splitter/Forkball specialist",
         lambda r: max(r.get("pitching_ratings_pitches_splitter", 0),
                       r.get("pitching_ratings_pitches_forkball", 0)) >= 60),
        ("Screwball user",
         lambda r: r.get("pitching_ratings_pitches_screwball", 0) >= 40),
        ("Flamethrower (velocity >= 96)",
         lambda r: r.get("pitching_ratings_misc_velocity", 0) >= 96),
        ("Soft-tosser (velocity <= 88)",
         lambda r: r.get("pitching_ratings_misc_velocity", 0) <= 88
                   and r.get("pitching_ratings_misc_velocity", 0) >= 80),
        ("Sidearm/submarine (arm_slot extreme)",
         lambda r: r.get("pitching_ratings_misc_arm_slot", 50) <= 30
                   or r.get("pitching_ratings_misc_arm_slot", 50) >= 80),
        ("4+ pitch arsenal SP",
         lambda r: sum(1 for c, _ in
                       [(c, r.get(c, 0)) for c in
                        [p[1] for p in PITCHES]]
                       if r.get(c, 0) >= 40) >= 4
                   and r.get("pitching_ratings_misc_stamina", 0) >= 60),
        ("2-pitch RP (FB + breaker)",
         lambda r: sum(1 for p in PITCHES
                       if r.get(p[1], 0) >= 40) == 2
                   and r.get("pitching_ratings_misc_stamina", 0) <= 40),
        ("Elite high-leverage RP (Stuff 65+, Stamina < 50)",
         lambda r: r.get("pitching_ratings_vsr_stuff", 0) >= 65
                   and r.get("pitching_ratings_misc_stamina", 0) < 50),
        ("LHP starter",
         lambda r: r.get("throws", 0) == 2
                   and r.get("pitching_ratings_misc_stamina", 0) >= 60),
        ("LHP reliever",
         lambda r: r.get("throws", 0) == 2
                   and r.get("pitching_ratings_misc_stamina", 0) < 50),
    ]
    df_dict = df.set_index("player_id").to_dict("index")
    for arche_label, pred in arche_specs:
        matches = df[df.apply(pred, axis=1)]
        matches = matches[~matches["player_id"].isin(picked_set)]
        if matches.empty:
            continue
        matches = matches.sort_values(
            ["_level_rank", "overall"], ascending=[True, False],
        )
        for _, p in matches.head(2).iterrows():
            pid = int(p["player_id"])
            picked_set.add(pid)
            primary_coverage.setdefault(pid, []).append(f"Arch: {arche_label}")

    picked_df = df[df["player_id"].isin(picked_set)].copy()

    # ----------------------------------------------------------------
    # Build output: identity + ratings, plus PROJECTION columns left
    # blank for the user to fill in from OOTP's in-game projection.
    # ----------------------------------------------------------------
    # Identity columns
    identity_cols = ["Name", "Org", "Level", "Throws", "Age"]

    # Ratings columns to display (full pitcher rating grid)
    rating_cols = [c for _, c in STATS_20_80] + [c for _, c in PITCHES] + [c for _, c in MISC]
    rating_rename = {col: label for label, col in STATS_20_80}
    rating_rename.update({col: label for label, col in PITCHES})
    rating_rename.update({col: label for label, col in MISC})

    # Blank projection columns the user will fill in from OOTP's UI
    PROJECTION_COLS = [
        "IP", "BF", "ERA", "FIP", "WHIP",
        "K", "BB", "HR", "H", "ER",
        "K/9", "BB/9", "HR/9", "K%", "BB%", "HR%", "BABIP-against",
        "pwOBA-against", "GO+FO",
    ]

    picked_df["PickedFor"] = picked_df["player_id"].apply(
        lambda pid: " | ".join(primary_coverage.get(pid, []))
    )

    out = picked_df[identity_cols + rating_cols + ["PickedFor"]].rename(
        columns=rating_rename
    )
    for c in PROJECTION_COLS:
        out[c] = ""  # left blank for user to fill

    # Reorder: identity, then projection (blank), then ratings, then PickedFor
    final_order = identity_cols + PROJECTION_COLS + [
        c for c in out.columns
        if c not in identity_cols + PROJECTION_COLS + ["PickedFor"]
    ] + ["PickedFor"]
    out = out[final_order]

    # Sort: MLB first, then AAA/AA/...; SPs before RPs
    out["_lvl"] = out["Level"].map({"MLB": 0, "AAA": 1, "AA": 2, "A+": 3,
                                       "A": 4, "R": 5, "R(DLR)/other": 6}).fillna(99)
    out = out.sort_values(["_lvl", "Throws", "Name"]).drop(columns=["_lvl"])

    OUT_PATH.parent.mkdir(exist_ok=True)
    with pd.ExcelWriter(OUT_PATH, engine="openpyxl") as writer:
        out.to_excel(writer, sheet_name="Pitcher pool", index=False)
        ws = writer.sheets["Pitcher pool"]
        for col_idx, col_name in enumerate(out.columns, 1):
            sample = out[col_name].astype(str).values[:50]
            max_len = max([len(str(col_name))] + [len(s) for s in sample])
            ws.column_dimensions[ws.cell(1, col_idx).column_letter].width = min(
                max_len + 2, 28
            )
        # Freeze identity columns
        ws.freeze_panes = "F2"

    # Print summary
    print(f"\nWrote {len(out)} unique pitchers to {OUT_PATH}")
    print(f"  RHP: {(out['Throws']=='R').sum()}, LHP: {(out['Throws']=='L').sum()}")
    print(f"  Level: " + ", ".join(
        f"{lvl}={(out['Level']==lvl).sum()}"
        for lvl in ["MLB","AAA","AA","A+","A","R","R(DLR)/other"]
        if (out['Level']==lvl).sum() > 0
    ))

    # Coverage check
    print()
    expected = []
    for label, col in STATS_20_80:
        if col not in df.columns:
            continue
        for v in range(20, int(df[col].max()) + 1, 5):
            if (df[col] == v).sum() > 0:
                expected.append((label, col, v))
    picked_subset = df[df["player_id"].isin(picked_set)]
    missing = []
    for label, col, v in expected:
        if (picked_subset[col] == v).sum() == 0:
            missing.append(f"{label}={v}")
    print(f"  Covered: {len(expected) - len(missing)} / {len(expected)} 20-80 bins")
    if missing:
        print(f"  Missing bins: {missing}")
    else:
        print("  All 20-80 rating bins covered.")

    print()
    print("Output file structure:")
    print("  Identity:    Name, Org, Level, Throws, Age")
    print("  Projection (BLANK — for user to fill):")
    for c in PROJECTION_COLS:
        print(f"    {c}")
    print(f"  Ratings: {len(rating_cols)} columns covering Stuff, Movement,")
    print("           Control, HRA, pBABIP (vsR + vsL), all 12 pitch types,")
    print("           and 9 misc columns (velocity, stamina, etc.)")
    print("  Last col: PickedFor — which bin(s) this pitcher fills")


if __name__ == "__main__":
    main()
