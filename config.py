from pathlib import Path

# =============
# Project Paths
# =============

filepath = Path(
    "C:/Users/sfwea/OneDrive/Documents/Out of the Park Developments/OOTP Baseball 27/saved_games/New Game 6.lg/import_export/csv")
# Derive the project root from config.py's own location so the pipeline writes
# outputs/ alongside this file regardless of whether we're running from the
# main repo or a git worktree. Previously hardcoded to the main repo, which
# meant a pipeline run from a worktree wrote JSONs into the main repo while
# the worktree's UI kept reading its own (stale) outputs/.
pistachio_filepath = Path(__file__).resolve().parent
export_filepath = pistachio_filepath / "outputs"

# ========================
# User & Team Identifiers
# ========================

ID = 114  # this is your scout's coach_id taken from coaches.csv
team_managed = "LAA"

# ======================
# Club Lookup Map
# ======================
# This maps team/org ID numbers to team abbreviations (e.g. 6 → "CHC")
# You can edit this dictionary if OOTP changes club IDs or you want to rename them

club_lookup = {
    0: "Free",
    1: "AZ",
    2: "ATL",
    3: "BAL",
    4: "BOS",
    5: "CWS",
    6: "CHC",
    7: "CIN",
    8: "CLE",
    9: "COL",
    10: "DET",
    11: "MIA",
    12: "HOU",
    13: "KC",
    14: "LAA",
    15: "LAD",
    16: "MIL",
    17: "MIN",
    18: "NYY",
    19: "NYM",
    20: "OAK",
    21: "PHI",
    22: "PIT",
    23: "SD",
    24: "SEA",
    25: "SF",
    26: "STL",
    27: "TB",
    28: "TEX",
    29: "TOR",
    30: "WSH",
}

# ============================
# Position rating floor
# ============================
# A player is excluded from a position if ANY of that position's relevant
# defensive ratings is below POSITION_FLOOR. Set to 40 because that's the
# lowest rating value we have sim calibration data for — below 40 the
# fielding tables are constant-clamped extrapolations rather than measured
# values, so we don't trust them.
#
# 1B is exempt (catch-all defensive position; players moved there when
# nothing else fits, and the 1B fielding tables are dominated by hitting
# anyway). DH is automatically exempt because it has no defensive ratings.
#
# Applied in metrics_war.calc_war() — position WARs (current + potential)
# are NaN'd out for floor violators BEFORE best/pos capture, so the
# adjusted-WAR ranking won't pick a position the player has no measured
# baseline for.
POSITION_FLOOR = 40
POSITION_FLOOR_EXEMPT = ["1B"]

# ============================
# Position viability gap (LEGACY — currently unused)
# ============================
# Was previously a secondary eligibility filter on top of POSITION_FLOOR:
# a position was feasible iff its WAR was within POSITION_VIABILITY_GAP wins
# of the player's best. Removed because once the floor was calibrated to
# match the lowest sim-tested rating, the WAR-gap filter created edge cases
# (e.g. elite-rated players being excluded from their OOTP-natural position
# because another position scored marginally higher).
#
# Constant kept for reference / easy re-enable. To re-apply, restore the
# `_apply_viability` calls in metrics_war.calc_war().
POSITION_VIABILITY_GAP = 1.5


# ============================
# Empirical positional adjustment
# ============================
# Reference position for the scarcity-adjusted WAR computation. For each
# position, calc_war derives an adjustment = mean(<ref>_def) - mean(<pos>_def)
# over the all-hitters pool, then adds it to the player's raw position WAR
# to produce <pos>_adj. Mirrors FanGraphs' positional adjustment but sourced
# entirely from your OOTP export instead of MLB historical data.
#
# 1B is the natural anchor: every player can fall back to it, and the
# adjustment for 1B itself is 0 by construction.
POSITION_ADJ_REFERENCE = "1B"

# Skill-aware spread of the scarcity bonus. The flat mean-shift adjustment
# `scarcity_constant = mean(<ref>_def) - mean(<pos>_def)` is replaced by a
# per-player bonus
#     bonus = scarcity_constant * (1 + gamma * (pct/50 - 1))
# where pct is the player's percentile rank within the eligible hitter pool's
# <pos>_def. Mean-preserving by construction (mean(bonus | eligible hitter) ==
# scarcity_constant) so cross-position calibration anchored on
# POSITION_ADJ_REFERENCE is preserved. gamma=0 recovers the flat scheme;
# gamma=0.5 means the 100th-percentile eligible player gets 1.5x and the 0th
# gets 0.5x. Derivation in calibration/skill_aware_adj.py.
SCARCITY_SKILL_GAMMA = 0.5

# ============================
# Pitcher rating thresholds used to determine if a pitcher is a starter or reliever
# ============================

PITCH_MINIMUM_RATING = 45  # rating floor used by count_pitches for `pitches` / `pitchesP` columns
MINIMUM_STARTER_STAMINA = 40  # stamina ≥ 40 → SP-viable; below → RP-only
# Pitcher classification (sprp / sprpP) now uses ONLY position == 1 (from OOTP)
# and the stamina threshold above. The pitch-count thresholds below are
# deprecated — kept as constants in case other notes reference them, but no
# code path reads them. Stamina alone is the rotation-viability signal;
# one-pitch specialists with low stamina correctly land in the RP bucket.
MINIMUM_STARTER_PITCHES = 3  # deprecated — stamina is the SP/RP gate
MINIMUM_RELIEVER_PITCHES = 1  # deprecated — position == 1 admits all pitchers

# ============================
# Pitcher skill rating floor
# ============================
# A pitcher with ANY current skill rating (ctrl, pbabip, hra, stuff vs R/L)
# below this floor has their CURRENT WAR set to NaN — the PITCHING_COMPONENTS_
# ADJUST_MAP only has data from rating 35 up, so anything below is an
# extrapolation we don't trust. Their potential WAR is still computed normally
# (with sub-floor potentials clamped to min_key) so the development view in
# pitchers.html via sp_warP / rp_warP / pwOBAP stays intact.
#
# Mirrors POSITION_FLOOR for fielders: ineligible-now-but-still-evaluable-by-
# potential. Set to 35 to match the lowest table key.
PITCHER_RATING_FLOOR = 35

# Below this stamina, the "if used as SP" hypothetical for CURRENT WAR
# (sp_war) is NaN'd — these pitchers physically can't be stretched to a
# full starter workload regardless of skill. Looser than
# MINIMUM_STARTER_STAMINA (40, which gates actual SP classification):
# pitchers in the 36-39 band can't be classified SP but their sp_war is
# shown as a stretch-out hypothetical. NOT applied to sp_warP — the
# potential view shows development upside including the "if this prospect
# ever stretched out" hypothetical regardless of current stamina.
SP_WAR_MIN_STAMINA = 36

# =================
# Metric Constants
# =================

RUNS_PER_WIN = 10
REPLACEMENT_LEVEL_WOBA = 0.3  # no positional adjustment
REPLACEMENT_LEVEL_PITCHER_WOBA = 0.36

# Regression of wOBA vs runs/162 games for pitchers; this is the slope and intercept of the regression line
RUNS_PER_GAME_PITCHING_COEFF = 646.6961042
RUNS_PER_GAME_PITCHING_CONST = 206.0579547

# same regression for hitters
RUNS_PER_GAME_HITTING_COEFF = 554.7865342
RUNS_PER_GAME_HITTING_CONST = 178.9071431

RELIEVER_VS_STARTER_AVERAGE_IP = 0.3333333  # relievers assumed to pitch one-third of the innings of a starter, on average
DH_PENALTY = 0.023  # penalty to expected wOBA for being a DH (i.e. not playing defense)
HANDEDNESS_WEIGHTS = {"R": 0.7, "L": 0.3}

# ============================
# Columns Used from Each CSV
# ============================

# —— players.csv ——
PLAYERS_COLUMNS = [
    "player_id",
    "first_name",
    "last_name",
    "age",
    "team_id",
    "organization_id",
    "retired",
    # OOTP position code (1 = pitcher; 2-10 = position players / DH).
    # Used as the canonical "is this a pitcher?" signal in metrics_pitching
    # — replaces the old pitch-count rating thresholds which over-filtered
    # 1-pitch specialists.
    "position",
]

# —— players_career_pitching_stats.csv ——
PITCHING_STATS_COLUMNS = ["player_id", "ip", "level_id", "split_id", "year"]

# —— players_career_batting_stats.csv ——
HITTING_STATS_COLUMNS = ["player_id", "year", "level_id", "split_id", "pa"]

# —— players_scouted_ratings.csv ——
SCOUTED_RATINGS_COLUMNS = [
    "player_id",
    "scouting_coach_id",
    "pitching_ratings_vsr_control",
    "pitching_ratings_vsr_pbabip",
    "pitching_ratings_vsr_hra",
    "pitching_ratings_vsr_stuff",
    "pitching_ratings_vsl_control",
    "pitching_ratings_vsl_pbabip",
    "pitching_ratings_vsl_hra",
    "pitching_ratings_vsl_stuff",
    "pitching_ratings_misc_stamina",
    "pitching_ratings_talent_control",
    "pitching_ratings_talent_pbabip",
    "pitching_ratings_talent_hra",
    "pitching_ratings_talent_stuff",
    "batting_ratings_vsr_power",
    "batting_ratings_vsr_eye",
    "batting_ratings_vsr_strikeouts",
    "batting_ratings_vsr_gap",
    "batting_ratings_vsr_babip",
    "batting_ratings_vsl_power",
    "batting_ratings_vsl_eye",
    "batting_ratings_vsl_strikeouts",
    "batting_ratings_vsl_gap",
    "batting_ratings_vsl_babip",
    "batting_ratings_talent_power",
    "batting_ratings_talent_eye",
    "batting_ratings_talent_strikeouts",
    "batting_ratings_talent_gap",
    "batting_ratings_talent_babip",
    "running_ratings_speed",
    "fielding_ratings_catcher_framing",
    "fielding_ratings_catcher_ability",
    "fielding_ratings_catcher_arm",
    "fielding_ratings_outfield_range",
    "fielding_ratings_outfield_arm",
    "fielding_ratings_outfield_error",
    "fielding_ratings_infield_range",
    "fielding_ratings_infield_error",
    "fielding_ratings_infield_arm",
    "fielding_ratings_turn_doubleplay",
]

PITCH_RATING_COLUMNS = [
    "pitching_ratings_pitches_fastball",
    "pitching_ratings_pitches_slider",
    "pitching_ratings_pitches_curveball",
    "pitching_ratings_pitches_screwball",
    "pitching_ratings_pitches_forkball",
    "pitching_ratings_pitches_changeup",
    "pitching_ratings_pitches_sinker",
    "pitching_ratings_pitches_splitter",
    "pitching_ratings_pitches_knuckleball",
    "pitching_ratings_pitches_cutter",
    "pitching_ratings_pitches_circlechange",
    "pitching_ratings_pitches_knucklecurve",
]

POTENTIAL_PITCH_RATING_COLUMNS = [
    "pitching_ratings_pitches_talent_fastball",
    "pitching_ratings_pitches_talent_slider",
    "pitching_ratings_pitches_talent_curveball",
    "pitching_ratings_pitches_talent_screwball",
    "pitching_ratings_pitches_talent_forkball",
    "pitching_ratings_pitches_talent_changeup",
    "pitching_ratings_pitches_talent_sinker",
    "pitching_ratings_pitches_talent_splitter",
    "pitching_ratings_pitches_talent_knuckleball",
    "pitching_ratings_pitches_talent_cutter",
    "pitching_ratings_pitches_talent_circlechange",
    "pitching_ratings_pitches_talent_knucklecurve",
]

# =================================
# Column Renames by CSV
# =================================

# —— players.csv ——
PLAYERS_COLUMN_RENAMES = {"organization_id": "org"}

# —— players_scouted_ratings.csv ——
SCOUTED_RATINGS_RENAMES = {
    "pitching_ratings_vsr_control": "ctrlR",
    "pitching_ratings_vsr_pbabip": "pbabipR",
    "pitching_ratings_vsr_hra": "hraR",
    "pitching_ratings_vsr_stuff": "stuffR",
    "pitching_ratings_vsl_control": "ctrlL",
    "pitching_ratings_vsl_pbabip": "pbabipL",
    "pitching_ratings_vsl_hra": "hraL",
    "pitching_ratings_vsl_stuff": "stuffL",
    "pitching_ratings_talent_control": "ctrlP",
    "pitching_ratings_talent_pbabip": "pbabipP",
    "pitching_ratings_talent_hra": "hraP",
    "pitching_ratings_talent_stuff": "stuffP",
    "pitching_ratings_misc_stamina": "stamina",
    "batting_ratings_vsr_power": "powR",
    "batting_ratings_vsr_eye": "eyeR",
    "batting_ratings_vsr_strikeouts": "avkR",
    "batting_ratings_vsr_gap": "gapR",
    "batting_ratings_vsr_babip": "babipR",
    "batting_ratings_vsl_power": "powL",
    "batting_ratings_vsl_eye": "eyeL",
    "batting_ratings_vsl_strikeouts": "avkL",
    "batting_ratings_vsl_gap": "gapL",
    "batting_ratings_vsl_babip": "babipL",
    "batting_ratings_talent_power": "powP",
    "batting_ratings_talent_eye": "eyeP",
    "batting_ratings_talent_strikeouts": "avkP",
    "batting_ratings_talent_gap": "gapP",
    "batting_ratings_talent_babip": "babipP",
    "fielding_ratings_catcher_framing": "Cfram",
    "fielding_ratings_catcher_ability": "Cabil",
    "fielding_ratings_catcher_arm": "Carm",
    "fielding_ratings_outfield_range": "OFrange",
    "fielding_ratings_outfield_arm": "OFarm",
    "fielding_ratings_outfield_error": "OFerror",
    "fielding_ratings_infield_range": "IFrange",
    "fielding_ratings_infield_error": "IFerror",
    "fielding_ratings_infield_arm": "IFarm",
    "fielding_ratings_turn_doubleplay": "turnDP",
}

# ===================
# Rename Helper
# ===================


def rename_columns(df, old, new):
    if old in df.columns:
        print(f"🔁 Renaming column: {old} → {new}")
        return df.rename(columns={old: new})
    else:
        print(f"⚠️ Column {old} not found — skipping rename")
        return df


# ================================
# Columns to Blank Before Export
# ================================
COLUMNS_TO_BLANK_BEFORE_EXPORT = [
    # Pitcher-side columns that are NaN for hitters, sub-floor pitchers, or
    # (sp_war / sp_warP only) below SP_WAR_MIN_STAMINA
    "pwOBA", "pwOBAR", "pwOBAL", "sp_war", "rp_war", "sp_warP", "rp_warP",
    # Position-WAR columns can be NaN when calc_war() filters via
    # POSITION_VIABILITY_GAP. Blanking lets DataTables sort numerically and
    # avoids the literal string "nan" appearing in cells.
    "C", "CF", "RF", "LF", "SS", "2B", "3B", "1B", "DH",
    # Potential-WAR counterparts
    "CP", "CFP", "RFP", "LFP", "SSP", "2BP", "3BP", "1BP", "DHP",
    # Scarcity-adjusted WAR columns (NaN inherits from raw <pos>)
    "C_adj", "CF_adj", "RF_adj", "LF_adj", "SS_adj", "2B_adj", "3B_adj", "1B_adj", "DH_adj",
    "CP_adj", "CFP_adj", "RFP_adj", "LFP_adj", "SSP_adj", "2BP_adj", "3BP_adj", "1BP_adj", "DHP_adj",
    # Fielding-only WAR (with scarcity adjustment baked in)
    "C_fld", "CF_fld", "RF_fld", "LF_fld", "SS_fld", "2B_fld", "3B_fld", "1B_fld", "DH_fld",
    # _def columns no longer NaN'd directly (every player gets a value)
    # but kept here for back-compat with any prior export expectation.
    "C_def", "CF_def", "RF_def", "LF_def", "SS_def", "2B_def", "3B_def",
]

# ============================
# wOBA and wRC+ weights
# ============================

# Base rates for a pitcher with all 50 ratings
BASE_PITCHING_RATES = {
    "hr_vs_baserate": 0.0326,
    "bb_vs_baserate": 0.0714,
    "k_vs_baserate": 0.2078,
    "h_nothr_vs_baserate": 0.2050,
}

# Run-Value Weights for Pitching wOBA (pwOBA) calculation
PITCHING_WOBA_WEIGHTS = {
    "hr_vs_wOBA_weight": 1.95,
    "bb_vs_wOBA_weight": 0.72,
    "h_nothr_vs_wOBA_weight": 0.99,
}

# Base rates for a hitter with all 50 ratings
# Refitted from calibration/sim_data.csv (OOTP team-of-clones, 100k G per scenario)
BASE_HITTING_RATES = {
    "hr_pct_baserate": 0.0268,
    "k_pct_baserate": 0.2159,
    "bb_pct_baserate": 0.0752,
    "1b_pct_baserate": 0.1604,
    "2b_pct_baserate": 0.0491,
    "3b_pct_baserate": 0.0039,
}

# Run-Value Weights for hitter wOBA calculation
BATTING_WOBA_WEIGHTS = {
    "hr_pct_wOBA_weight": 1.95,
    "bb_pct_wOBA_weight": 0.72,
    "1b_pct_wOBA_weight": 0.90,
    "2b_pct_wOBA_weight": 1.24,
    "3b_pct_wOBA_weight": 1.56,
}

# league context for wRC+
LEAGUE_WOBA = 0.320  # from all-50 hitter calibration
WOBA_SCALE = 1.15  # from Tango book
LEAGUE_RUNS_PER_PA = 0.120

# ===============================================
# Pitching wOBA component adjustments by rating
# ===============================================

PITCHING_COMPONENTS_ADJUST_MAP = {
    "Control": {
        "35": {
            "hr_vs_adj": -0.0022,
            "bb_vs_adj": 0.0486,
            "k_vs_adj": -0.0122,
            "h_nothr_vs_adj": -0.0132,
        },
        "40": {
            "hr_vs_adj": -0.0016,
            "bb_vs_adj": 0.0349,
            "k_vs_adj": -0.0081,
            "h_nothr_vs_adj": -0.0092,
        },
        "45": {
            "hr_vs_adj": -0.0012,
            "bb_vs_adj": 0.0176,
            "k_vs_adj": -0.0038,
            "h_nothr_vs_adj": -0.0047,
        },
        "50": {
            "hr_vs_adj": 0.0000,
            "bb_vs_adj": 0.0000,
            "k_vs_adj": 0.0000,
            "h_nothr_vs_adj": 0.0000,
        },
        "55": {
            "hr_vs_adj": 0.0006,
            "bb_vs_adj": -0.0083,
            "k_vs_adj": 0.0016,
            "h_nothr_vs_adj": 0.0019,
        },
        "60": {
            "hr_vs_adj": 0.0004,
            "bb_vs_adj": -0.0135,
            "k_vs_adj": 0.0039,
            "h_nothr_vs_adj": 0.0034,
        },
        "65": {
            "hr_vs_adj": 0.0005,
            "bb_vs_adj": -0.0173,
            "k_vs_adj": 0.0052,
            "h_nothr_vs_adj": 0.0043,
        },
        "70": {
            "hr_vs_adj": 0.0005,
            "bb_vs_adj": -0.0222,
            "k_vs_adj": 0.0058,
            "h_nothr_vs_adj": 0.0058,
        },
        "75": {
            "hr_vs_adj": 0.0010,
            "bb_vs_adj": -0.0264,
            "k_vs_adj": 0.0069,
            "h_nothr_vs_adj": 0.0069,
        },
        "80": {
            "hr_vs_adj": 0.0018,
            "bb_vs_adj": -0.0315,
            "k_vs_adj": 0.0088,
            "h_nothr_vs_adj": 0.0063,
        },
    },
    "pBABIP": {
        "35": {
            "hr_vs_adj": 0.0003,
            "bb_vs_adj": -0.0003,
            "k_vs_adj": -0.0009,
            "h_nothr_vs_adj": 0.0067,
        },
        "40": {
            "hr_vs_adj": -0.0005,
            "bb_vs_adj": -0.0012,
            "k_vs_adj": 0.0012,
            "h_nothr_vs_adj": -0.0001,
        },
        "45": {
            "hr_vs_adj": -0.0003,
            "bb_vs_adj": -0.0010,
            "k_vs_adj": 0.0002,
            "h_nothr_vs_adj": 0.0026,
        },
        "50": {
            "hr_vs_adj": 0.0000,
            "bb_vs_adj": 0.0000,
            "k_vs_adj": 0.0000,
            "h_nothr_vs_adj": 0.0000,
        },
        "55": {
            "hr_vs_adj": 0.0002,
            "bb_vs_adj": -0.0005,
            "k_vs_adj": 0.0008,
            "h_nothr_vs_adj": -0.0021,
        },
        "60": {
            "hr_vs_adj": 0.0001,
            "bb_vs_adj": -0.0006,
            "k_vs_adj": -0.0003,
            "h_nothr_vs_adj": -0.0032,
        },
        "65": {
            "hr_vs_adj": 0.0001,
            "bb_vs_adj": -0.0008,
            "k_vs_adj": 0.0008,
            "h_nothr_vs_adj": -0.0048,
        },
        "70": {
            "hr_vs_adj": -0.0001,
            "bb_vs_adj": 0.0002,
            "k_vs_adj": 0.0005,
            "h_nothr_vs_adj": -0.0083,
        },
    },
    "HRA": {
        "35": {
            "hr_vs_adj": 0.0286,
            "bb_vs_adj": -0.0013,
            "k_vs_adj": 0.0012,
            "h_nothr_vs_adj": -0.0094,
        },
        "40": {
            "hr_vs_adj": 0.0217,
            "bb_vs_adj": -0.0004,
            "k_vs_adj": 0.0003,
            "h_nothr_vs_adj": -0.0073,
        },
        "45": {
            "hr_vs_adj": 0.0110,
            "bb_vs_adj": -0.0008,
            "k_vs_adj": 0.0012,
            "h_nothr_vs_adj": -0.0030,
        },
        "50": {
            "hr_vs_adj": 0.0000,
            "bb_vs_adj": 0.0000,
            "k_vs_adj": 0.0000,
            "h_nothr_vs_adj": 0.0000,
        },
        "55": {
            "hr_vs_adj": -0.0040,
            "bb_vs_adj": -0.0007,
            "k_vs_adj": 0.0010,
            "h_nothr_vs_adj": 0.0014,
        },
        "60": {
            "hr_vs_adj": -0.0071,
            "bb_vs_adj": -0.0004,
            "k_vs_adj": 0.0003,
            "h_nothr_vs_adj": 0.0023,
        },
        "65": {
            "hr_vs_adj": -0.0096,
            "bb_vs_adj": -0.0006,
            "k_vs_adj": 0.0008,
            "h_nothr_vs_adj": 0.0026,
        },
        "70": {
            "hr_vs_adj": -0.0112,
            "bb_vs_adj": -0.0005,
            "k_vs_adj": -0.0006,
            "h_nothr_vs_adj": 0.0030,
        },
        "75": {
            "hr_vs_adj": -0.0141,
            "bb_vs_adj": -0.0002,
            "k_vs_adj": -0.0001,
            "h_nothr_vs_adj": 0.0043,
        },
        "80": {
            "hr_vs_adj": -0.0170,
            "bb_vs_adj": -0.0006,
            "k_vs_adj": 0.0000,
            "h_nothr_vs_adj": 0.0060,
        },
    },
    "Stuff": {
        "35": {
            "hr_vs_adj": -0.0001,
            "bb_vs_adj": -0.0015,
            "k_vs_adj": -0.0726,
            "h_nothr_vs_adj": 0.0224,
        },
        "40": {
            "hr_vs_adj": -0.0003,
            "bb_vs_adj": -0.0014,
            "k_vs_adj": -0.0395,
            "h_nothr_vs_adj": 0.0157,
        },
        "45": {
            "hr_vs_adj": 0.0003,
            "bb_vs_adj": 0.0001,
            "k_vs_adj": -0.0154,
            "h_nothr_vs_adj": 0.0048,
        },
        "50": {
            "hr_vs_adj": 0.0000,
            "bb_vs_adj": 0.0000,
            "k_vs_adj": 0.0000,
            "h_nothr_vs_adj": 0.0000,
        },
        "55": {
            "hr_vs_adj": 0.0000,
            "bb_vs_adj": -0.0005,
            "k_vs_adj": 0.0310,
            "h_nothr_vs_adj": -0.0096,
        },
        "60": {
            "hr_vs_adj": -0.0001,
            "bb_vs_adj": -0.0002,
            "k_vs_adj": 0.0478,
            "h_nothr_vs_adj": -0.0120,
        },
        "65": {
            "hr_vs_adj": -0.0006,
            "bb_vs_adj": -0.0006,
            "k_vs_adj": 0.0565,
            "h_nothr_vs_adj": -0.0220,
        },
        "70": {
            "hr_vs_adj": -0.0002,
            "bb_vs_adj": -0.0004,
            "k_vs_adj": 0.0752,
            "h_nothr_vs_adj": -0.0217,
        },
        "75": {
            "hr_vs_adj": -0.0004,
            "bb_vs_adj": -0.0001,
            "k_vs_adj": 0.0881,
            "h_nothr_vs_adj": -0.0261,
        },
        "80": {
            "hr_vs_adj": -0.0001,
            "bb_vs_adj": -0.0001,
            "k_vs_adj": 0.1081,
            "h_nothr_vs_adj": -0.0316,
        },
    },
    "Stamina": {
        "40": {
            "hr_vs_adj": -0.0008,
            "bb_vs_adj": -0.0009,
            "k_vs_adj": 0.0007,
            "h_nothr_vs_adj": 0.0004,
        },
        "45": {
            "hr_vs_adj": -0.0003,
            "bb_vs_adj": -0.0003,
            "k_vs_adj": -0.0001,
            "h_nothr_vs_adj": 0.0003,
        },
        "50": {
            "hr_vs_adj": 0.0000,
            "bb_vs_adj": 0.0000,
            "k_vs_adj": 0.0000,
            "h_nothr_vs_adj": 0.0000,
        },
        "55": {
            "hr_vs_adj": 0.0000,
            "bb_vs_adj": -0.0003,
            "k_vs_adj": 0.0009,
            "h_nothr_vs_adj": -0.0011,
        },
        "60": {
            "hr_vs_adj": 0.0001,
            "bb_vs_adj": -0.0006,
            "k_vs_adj": -0.0003,
            "h_nothr_vs_adj": 0.0003,
        },
    },
}


# ===============================================
# Hitting wOBA component adjustments by rating
# ===============================================

BATTING_COMPONENTS_ADJUST_MAP = {
    "babip": {
        "20": {
            "hr_pct_adj": 0.0003,
            "k_pct_adj": -0.0031,
            "bb_pct_adj": 0.0002,
            "1b_pct_adj": -0.0507,
            "2b_pct_adj": -0.0157,
            "3b_pct_adj": -0.0015,
        },
        "25": {
            "hr_pct_adj": -0.0002,
            "k_pct_adj": -0.0026,
            "bb_pct_adj": -0.0008,
            "1b_pct_adj": -0.0291,
            "2b_pct_adj": -0.0102,
            "3b_pct_adj": -0.0008,
        },
        "30": {
            "hr_pct_adj": -0.0001,
            "k_pct_adj": -0.0024,
            "bb_pct_adj": 0.0000,
            "1b_pct_adj": -0.0224,
            "2b_pct_adj": -0.0080,
            "3b_pct_adj": -0.0008,
        },
        "35": {
            "hr_pct_adj": -0.0004,
            "k_pct_adj": -0.0023,
            "bb_pct_adj": -0.0007,
            "1b_pct_adj": -0.0161,
            "2b_pct_adj": -0.0055,
            "3b_pct_adj": -0.0007,
        },
        "40": {
            "hr_pct_adj": 0.0001,
            "k_pct_adj": -0.0004,
            "bb_pct_adj": -0.0003,
            "1b_pct_adj": -0.0101,
            "2b_pct_adj": -0.0033,
            "3b_pct_adj": -0.0004,
        },
        "45": {
            "hr_pct_adj": 0.0001,
            "k_pct_adj": -0.0009,
            "bb_pct_adj": 0.0003,
            "1b_pct_adj": -0.0040,
            "2b_pct_adj": -0.0017,
            "3b_pct_adj": -0.0003,
        },
        "50": {
            "hr_pct_adj": 0.0000,
            "k_pct_adj": 0.0000,
            "bb_pct_adj": 0.0000,
            "1b_pct_adj": 0.0000,
            "2b_pct_adj": 0.0000,
            "3b_pct_adj": 0.0000,
        },
        "55": {
            "hr_pct_adj": 0.0004,
            "k_pct_adj": -0.0018,
            "bb_pct_adj": -0.0009,
            "1b_pct_adj": 0.0063,
            "2b_pct_adj": 0.0013,
            "3b_pct_adj": 0.0002,
        },
        "60": {
            "hr_pct_adj": 0.0002,
            "k_pct_adj": -0.0018,
            "bb_pct_adj": 0.0003,
            "1b_pct_adj": 0.0100,
            "2b_pct_adj": 0.0031,
            "3b_pct_adj": 0.0003,
        },
        "65": {
            "hr_pct_adj": 0.0001,
            "k_pct_adj": -0.0018,
            "bb_pct_adj": 0.0047,
            "1b_pct_adj": 0.0144,
            "2b_pct_adj": 0.0042,
            "3b_pct_adj": 0.0003,
        },
        "70": {
            "hr_pct_adj": 0.0005,
            "k_pct_adj": -0.0014,
            "bb_pct_adj": 0.0040,
            "1b_pct_adj": 0.0187,
            "2b_pct_adj": 0.0058,
            "3b_pct_adj": 0.0006,
        },
        "75": {
            "hr_pct_adj": 0.0008,
            "k_pct_adj": -0.0006,
            "bb_pct_adj": 0.0042,
            "1b_pct_adj": 0.0230,
            "2b_pct_adj": 0.0065,
            "3b_pct_adj": 0.0006,
        },
        "80": {
            "hr_pct_adj": -0.0001,
            "k_pct_adj": -0.0028,
            "bb_pct_adj": 0.0118,
            "1b_pct_adj": 0.0287,
            "2b_pct_adj": 0.0080,
            "3b_pct_adj": 0.0005,
        },
    },
    "avk": {
        "20": {
            "hr_pct_adj": -0.0001,
            "k_pct_adj": 0.2616,
            "bb_pct_adj": -0.0013,
            "1b_pct_adj": -0.0601,
            "2b_pct_adj": -0.0197,
            "3b_pct_adj": -0.0017,
        },
        "25": {
            "hr_pct_adj": -0.0003,
            "k_pct_adj": 0.1606,
            "bb_pct_adj": -0.0011,
            "1b_pct_adj": -0.0365,
            "2b_pct_adj": -0.0122,
            "3b_pct_adj": -0.0011,
        },
        "30": {
            "hr_pct_adj": 0.0001,
            "k_pct_adj": 0.1261,
            "bb_pct_adj": -0.0011,
            "1b_pct_adj": -0.0291,
            "2b_pct_adj": -0.0102,
            "3b_pct_adj": -0.0008,
        },
        "35": {
            "hr_pct_adj": 0.0004,
            "k_pct_adj": 0.0926,
            "bb_pct_adj": -0.0003,
            "1b_pct_adj": -0.0215,
            "2b_pct_adj": -0.0073,
            "3b_pct_adj": -0.0007,
        },
        "40": {
            "hr_pct_adj": 0.0003,
            "k_pct_adj": 0.0561,
            "bb_pct_adj": -0.0003,
            "1b_pct_adj": -0.0123,
            "2b_pct_adj": -0.0046,
            "3b_pct_adj": -0.0004,
        },
        "45": {
            "hr_pct_adj": 0.0000,
            "k_pct_adj": 0.0241,
            "bb_pct_adj": 0.0002,
            "1b_pct_adj": -0.0062,
            "2b_pct_adj": -0.0022,
            "3b_pct_adj": -0.0003,
        },
        "50": {
            "hr_pct_adj": 0.0000,
            "k_pct_adj": 0.0000,
            "bb_pct_adj": 0.0000,
            "1b_pct_adj": 0.0000,
            "2b_pct_adj": 0.0000,
            "3b_pct_adj": 0.0000,
        },
        "55": {
            "hr_pct_adj": 0.0002,
            "k_pct_adj": -0.0253,
            "bb_pct_adj": -0.0005,
            "1b_pct_adj": 0.0060,
            "2b_pct_adj": 0.0017,
            "3b_pct_adj": 0.0000,
        },
        "60": {
            "hr_pct_adj": 0.0002,
            "k_pct_adj": -0.0450,
            "bb_pct_adj": -0.0010,
            "1b_pct_adj": 0.0104,
            "2b_pct_adj": 0.0031,
            "3b_pct_adj": 0.0003,
        },
        "65": {
            "hr_pct_adj": 0.0001,
            "k_pct_adj": -0.0629,
            "bb_pct_adj": -0.0018,
            "1b_pct_adj": 0.0148,
            "2b_pct_adj": 0.0044,
            "3b_pct_adj": 0.0003,
        },
        "70": {
            "hr_pct_adj": 0.0004,
            "k_pct_adj": -0.0832,
            "bb_pct_adj": -0.0008,
            "1b_pct_adj": 0.0199,
            "2b_pct_adj": 0.0061,
            "3b_pct_adj": 0.0005,
        },
        "75": {
            "hr_pct_adj": 0.0007,
            "k_pct_adj": -0.1013,
            "bb_pct_adj": 0.0042,
            "1b_pct_adj": 0.0230,
            "2b_pct_adj": 0.0069,
            "3b_pct_adj": 0.0005,
        },
        "80": {
            "hr_pct_adj": 0.0004,
            "k_pct_adj": -0.1218,
            "bb_pct_adj": 0.0038,
            "1b_pct_adj": 0.0281,
            "2b_pct_adj": 0.0088,
            "3b_pct_adj": 0.0006,
        },
    },
    "gap": {
        "20": {
            "hr_pct_adj": 0.0000,
            "k_pct_adj": -0.0008,
            "bb_pct_adj": 0.0001,
            "1b_pct_adj": 0.0368,
            "2b_pct_adj": -0.0347,
            "3b_pct_adj": -0.0029,
        },
        "25": {
            "hr_pct_adj": -0.0001,
            "k_pct_adj": -0.0003,
            "bb_pct_adj": 0.0000,
            "1b_pct_adj": 0.0285,
            "2b_pct_adj": -0.0269,
            "3b_pct_adj": -0.0022,
        },
        "30": {
            "hr_pct_adj": 0.0003,
            "k_pct_adj": -0.0002,
            "bb_pct_adj": 0.0006,
            "1b_pct_adj": 0.0223,
            "2b_pct_adj": -0.0220,
            "3b_pct_adj": -0.0019,
        },
        "35": {
            "hr_pct_adj": 0.0000,
            "k_pct_adj": 0.0014,
            "bb_pct_adj": -0.0005,
            "1b_pct_adj": 0.0180,
            "2b_pct_adj": -0.0171,
            "3b_pct_adj": -0.0015,
        },
        "40": {
            "hr_pct_adj": 0.0006,
            "k_pct_adj": -0.0006,
            "bb_pct_adj": 0.0000,
            "1b_pct_adj": 0.0119,
            "2b_pct_adj": -0.0107,
            "3b_pct_adj": -0.0009,
        },
        "45": {
            "hr_pct_adj": 0.0004,
            "k_pct_adj": 0.0006,
            "bb_pct_adj": 0.0003,
            "1b_pct_adj": 0.0037,
            "2b_pct_adj": -0.0049,
            "3b_pct_adj": -0.0003,
        },
        "50": {
            "hr_pct_adj": 0.0000,
            "k_pct_adj": 0.0000,
            "bb_pct_adj": 0.0000,
            "1b_pct_adj": 0.0000,
            "2b_pct_adj": 0.0000,
            "3b_pct_adj": 0.0000,
        },
        "55": {
            "hr_pct_adj": 0.0004,
            "k_pct_adj": -0.0006,
            "bb_pct_adj": 0.0001,
            "1b_pct_adj": -0.0033,
            "2b_pct_adj": 0.0031,
            "3b_pct_adj": 0.0001,
        },
        "60": {
            "hr_pct_adj": 0.0002,
            "k_pct_adj": -0.0003,
            "bb_pct_adj": -0.0001,
            "1b_pct_adj": -0.0050,
            "2b_pct_adj": 0.0054,
            "3b_pct_adj": 0.0003,
        },
        "65": {
            "hr_pct_adj": -0.0001,
            "k_pct_adj": 0.0002,
            "bb_pct_adj": -0.0004,
            "1b_pct_adj": -0.0081,
            "2b_pct_adj": 0.0080,
            "3b_pct_adj": 0.0006,
        },
        "70": {
            "hr_pct_adj": 0.0006,
            "k_pct_adj": 0.0009,
            "bb_pct_adj": -0.0003,
            "1b_pct_adj": -0.0110,
            "2b_pct_adj": 0.0097,
            "3b_pct_adj": 0.0008,
        },
        "75": {
            "hr_pct_adj": 0.0002,
            "k_pct_adj": 0.0005,
            "bb_pct_adj": -0.0001,
            "1b_pct_adj": -0.0139,
            "2b_pct_adj": 0.0130,
            "3b_pct_adj": 0.0012,
        },
        "80": {
            "hr_pct_adj": 0.0005,
            "k_pct_adj": 0.0005,
            "bb_pct_adj": -0.0001,
            "1b_pct_adj": -0.0168,
            "2b_pct_adj": 0.0155,
            "3b_pct_adj": 0.0010,
        },
    },
    "pow": {
        "20": {
            "hr_pct_adj": -0.0249,
            "k_pct_adj": -0.0016,
            "bb_pct_adj": -0.0011,
            "1b_pct_adj": 0.0041,
            "2b_pct_adj": 0.0014,
            "3b_pct_adj": 0.0001,
        },
        "25": {
            "hr_pct_adj": -0.0214,
            "k_pct_adj": -0.0017,
            "bb_pct_adj": -0.0003,
            "1b_pct_adj": 0.0031,
            "2b_pct_adj": 0.0040,
            "3b_pct_adj": 0.0002,
        },
        "30": {
            "hr_pct_adj": -0.0181,
            "k_pct_adj": -0.0030,
            "bb_pct_adj": -0.0013,
            "1b_pct_adj": 0.0023,
            "2b_pct_adj": 0.0050,
            "3b_pct_adj": 0.0004,
        },
        "35": {
            "hr_pct_adj": -0.0143,
            "k_pct_adj": -0.0009,
            "bb_pct_adj": -0.0004,
            "1b_pct_adj": 0.0015,
            "2b_pct_adj": 0.0066,
            "3b_pct_adj": 0.0003,
        },
        "40": {
            "hr_pct_adj": -0.0094,
            "k_pct_adj": -0.0015,
            "bb_pct_adj": -0.0006,
            "1b_pct_adj": -0.0001,
            "2b_pct_adj": 0.0072,
            "3b_pct_adj": 0.0005,
        },
        "45": {
            "hr_pct_adj": -0.0035,
            "k_pct_adj": -0.0003,
            "bb_pct_adj": -0.0004,
            "1b_pct_adj": -0.0015,
            "2b_pct_adj": 0.0087,
            "3b_pct_adj": 0.0003,
        },
        "50": {
            "hr_pct_adj": 0.0000,
            "k_pct_adj": 0.0000,
            "bb_pct_adj": 0.0000,
            "1b_pct_adj": 0.0000,
            "2b_pct_adj": 0.0000,
            "3b_pct_adj": 0.0000,
        },
        "55": {
            "hr_pct_adj": 0.0067,
            "k_pct_adj": -0.0018,
            "bb_pct_adj": 0.0109,
            "1b_pct_adj": -0.0035,
            "2b_pct_adj": -0.0006,
            "3b_pct_adj": -0.0003,
        },
        "60": {
            "hr_pct_adj": 0.0134,
            "k_pct_adj": -0.0023,
            "bb_pct_adj": 0.0096,
            "1b_pct_adj": -0.0046,
            "2b_pct_adj": -0.0010,
            "3b_pct_adj": -0.0003,
        },
        "65": {
            "hr_pct_adj": 0.0196,
            "k_pct_adj": 0.0000,
            "bb_pct_adj": 0.0127,
            "1b_pct_adj": -0.0068,
            "2b_pct_adj": -0.0020,
            "3b_pct_adj": -0.0002,
        },
        "70": {
            "hr_pct_adj": 0.0256,
            "k_pct_adj": -0.0001,
            "bb_pct_adj": 0.0123,
            "1b_pct_adj": -0.0076,
            "2b_pct_adj": -0.0021,
            "3b_pct_adj": 0.0000,
        },
        "75": {
            "hr_pct_adj": 0.0319,
            "k_pct_adj": -0.0007,
            "bb_pct_adj": 0.0130,
            "1b_pct_adj": -0.0100,
            "2b_pct_adj": -0.0023,
            "3b_pct_adj": -0.0001,
        },
        "80": {
            "hr_pct_adj": 0.0398,
            "k_pct_adj": -0.0053,
            "bb_pct_adj": 0.0326,
            "1b_pct_adj": -0.0151,
            "2b_pct_adj": -0.0038,
            "3b_pct_adj": -0.0003,
        },
    },
    "eye": {
        "20": {
            "hr_pct_adj": 0.0020,
            "k_pct_adj": 0.0134,
            "bb_pct_adj": -0.0627,
            "1b_pct_adj": 0.0114,
            "2b_pct_adj": 0.0033,
            "3b_pct_adj": 0.0002,
        },
        "25": {
            "hr_pct_adj": 0.0016,
            "k_pct_adj": 0.0126,
            "bb_pct_adj": -0.0543,
            "1b_pct_adj": 0.0107,
            "2b_pct_adj": 0.0022,
            "3b_pct_adj": 0.0002,
        },
        "30": {
            "hr_pct_adj": 0.0016,
            "k_pct_adj": 0.0098,
            "bb_pct_adj": -0.0439,
            "1b_pct_adj": 0.0081,
            "2b_pct_adj": 0.0025,
            "3b_pct_adj": -0.0001,
        },
        "35": {
            "hr_pct_adj": 0.0013,
            "k_pct_adj": 0.0071,
            "bb_pct_adj": -0.0333,
            "1b_pct_adj": 0.0058,
            "2b_pct_adj": 0.0016,
            "3b_pct_adj": 0.0000,
        },
        "40": {
            "hr_pct_adj": 0.0006,
            "k_pct_adj": 0.0058,
            "bb_pct_adj": -0.0210,
            "1b_pct_adj": 0.0037,
            "2b_pct_adj": 0.0006,
            "3b_pct_adj": 0.0001,
        },
        "45": {
            "hr_pct_adj": 0.0005,
            "k_pct_adj": 0.0018,
            "bb_pct_adj": -0.0087,
            "1b_pct_adj": 0.0016,
            "2b_pct_adj": 0.0006,
            "3b_pct_adj": 0.0002,
        },
        "50": {
            "hr_pct_adj": 0.0000,
            "k_pct_adj": 0.0000,
            "bb_pct_adj": 0.0000,
            "1b_pct_adj": 0.0000,
            "2b_pct_adj": 0.0000,
            "3b_pct_adj": 0.0000,
        },
        "55": {
            "hr_pct_adj": 0.0001,
            "k_pct_adj": -0.0028,
            "bb_pct_adj": 0.0096,
            "1b_pct_adj": -0.0010,
            "2b_pct_adj": -0.0006,
            "3b_pct_adj": -0.0001,
        },
        "60": {
            "hr_pct_adj": -0.0001,
            "k_pct_adj": -0.0040,
            "bb_pct_adj": 0.0179,
            "1b_pct_adj": -0.0018,
            "2b_pct_adj": -0.0010,
            "3b_pct_adj": -0.0002,
        },
        "65": {
            "hr_pct_adj": -0.0005,
            "k_pct_adj": -0.0059,
            "bb_pct_adj": 0.0255,
            "1b_pct_adj": -0.0051,
            "2b_pct_adj": -0.0015,
            "3b_pct_adj": -0.0002,
        },
        "70": {
            "hr_pct_adj": -0.0005,
            "k_pct_adj": -0.0085,
            "bb_pct_adj": 0.0341,
            "1b_pct_adj": -0.0051,
            "2b_pct_adj": -0.0016,
            "3b_pct_adj": -0.0001,
        },
        "75": {
            "hr_pct_adj": -0.0007,
            "k_pct_adj": -0.0094,
            "bb_pct_adj": 0.0407,
            "1b_pct_adj": -0.0072,
            "2b_pct_adj": -0.0019,
            "3b_pct_adj": 0.0000,
        },
        "80": {
            "hr_pct_adj": -0.0011,
            "k_pct_adj": -0.0128,
            "bb_pct_adj": 0.0537,
            "1b_pct_adj": -0.0088,
            "2b_pct_adj": -0.0026,
            "3b_pct_adj": -0.0002,
        },
    },
    "speed": {
        "40": {
            "hr_pct_adj": 0.0005,
            "k_pct_adj": 0.0005,
            "bb_pct_adj": 0.0000,
            "1b_pct_adj": -0.0009,
            "2b_pct_adj": 0.0033,
            "3b_pct_adj": -0.0022,
        },
        "45": {
            "hr_pct_adj": 0.0007,
            "k_pct_adj": 0.0015,
            "bb_pct_adj": -0.0007,
            "1b_pct_adj": -0.0017,
            "2b_pct_adj": 0.0011,
            "3b_pct_adj": -0.0012,
        },
        "50": {
            "hr_pct_adj": 0.0004,
            "k_pct_adj": 0.0010,
            "bb_pct_adj": -0.0003,
            "1b_pct_adj": -0.0010,
            "2b_pct_adj": -0.0006,
            "3b_pct_adj": 0.0005,
        },
        "55": {
            "hr_pct_adj": 0.0006,
            "k_pct_adj": 0.0011,
            "bb_pct_adj": 0.0001,
            "1b_pct_adj": -0.0015,
            "2b_pct_adj": -0.0015,
            "3b_pct_adj": 0.0011,
        },
        "60": {
            "hr_pct_adj": 0.0006,
            "k_pct_adj": 0.0011,
            "bb_pct_adj": 0.0000,
            "1b_pct_adj": -0.0015,
            "2b_pct_adj": -0.0010,
            "3b_pct_adj": 0.0013,
        },
        "65": {
            "hr_pct_adj": 0.0003,
            "k_pct_adj": 0.0002,
            "bb_pct_adj": -0.0004,
            "1b_pct_adj": -0.0008,
            "2b_pct_adj": -0.0011,
            "3b_pct_adj": 0.0013,
        },
        "70": {
            "hr_pct_adj": 0.0003,
            "k_pct_adj": 0.0005,
            "bb_pct_adj": -0.0004,
            "1b_pct_adj": -0.0011,
            "2b_pct_adj": -0.0029,
            "3b_pct_adj": 0.0018,
        },
        "75": {
            "hr_pct_adj": 0.0007,
            "k_pct_adj": 0.0002,
            "bb_pct_adj": -0.0003,
            "1b_pct_adj": -0.0008,
            "2b_pct_adj": -0.0019,
            "3b_pct_adj": 0.0021,
        },
    },
}

# ===============================================
# Fielding run values vs replacement, by position
# ===============================================

FIELDING_RUN_VALUES_VS_REPLACEMENT = {
    # C refitted from calibration/fielding_sim.csv (LSQ over 30 OOTP scenarios).
    # MAE = 0.7 runs/162 vs 4.4 for previous table. Cfram is dominant (~30 run swing
    # 40→70); Cabil is a small +/- 3-run effect; Carm is nearly inert (~3 run swing).
    "C": {
        "Cabil": {
            20: -13.7,
            25: -10.7,
            30: -7.7,
            35: -4.7,
            40: -1.7,
            45: -1.2,
            50: -0.6,
            55: 0.0,
            60: 0.9,
            65: 1.8,
            70: 2.7,
            75: 3.1,
        },
        "Cfram": {
            20: -57.1,
            25: -48.5,
            30: -39.9,
            35: -31.3,
            40: -22.7,
            45: -14.1,
            50: -6.9,
            55: 0.0,
            60: 3.1,
            65: 7.5,
            70: 7.5,
            75: 7.5,
        },
        "Carm": {
            20: -15.0,
            25: -12.0,
            30: -9.0,
            35: -6.0,
            40: -3.0,
            45: -1.5,
            50: 0.0,
            55: 0.4,
            60: 0.7,
            65: 0.7,
            70: 0.7,
            75: 0.7,
        },
    },
    # CF refitted from calibration/fielding_sim.csv (LSQ over 52 OOTP scenarios
    # incl. dense 3D Systematic grid + RNG=45/50/55 single-attr sweeps to pin
    # down the 40-60 plateau). MAE = 1.0 runs/162. The OFrange cliff sits
    # entirely between 60 and 65 (+30.6 jump); below 60 the curve is flat-ish
    # at -11 to -12 — confirmed by direct sim measurement at RNG 45/50/55.
    "CF": {
        "OFrange": {
            20: -24.4,
            25: -21.4,
            30: -18.4,
            35: -15.4,
            40: -12.4,
            45: -12.4,
            50: -12.2,
            55: -11.2,
            60: 0.0,
            65: 30.6,
            70: 31.9,
            75: 31.9,
        },
        "OFerror": {
            20: -14.3,
            25: -11.3,
            30: -8.3,
            35: -5.3,
            40: -2.3,
            45: -1.0,
            50: 0.0,
            55: 0.0,
            60: 0.0,
            65: 0.0,
            70: 0.0,
            75: 0.0,
        },
        "OFarm": {
            20: -19.1,
            25: -16.1,
            30: -13.1,
            35: -10.1,
            40: -7.1,
            45: -6.4,
            50: -5.8,
            55: 0.0,
            60: 1.3,
            65: 3.0,
            70: 4.7,
            75: 4.8,
        },
    },
    # RF refitted from calibration/fielding_sim.csv (LSQ over 30 OOTP scenarios incl.
    # 3D Systematic grid, baseline 50/55/55). MAE = 1.4 runs/162 vs 25.3 for previous
    # table — old massively undershot the OFrange cliff (old +0.0 → new +32.9 at 55+)
    # and over-penalized below-floor range.
    "RF": {
        "OFrange": {
            20: -28.2,
            25: -25.2,
            30: -22.2,
            35: -19.2,
            40: -16.2,
            45: -14.1,
            50: 0.0,
            55: 32.6,
            60: 32.6,
            65: 32.6,
            70: 32.6,
            75: 32.6,
        },
        "OFerror": {
            20: -11.9,
            25: -8.9,
            30: -5.9,
            35: -2.9,
            40: 0.1,
            45: 0.1,
            50: 0.1,
            55: 0.1,
            60: 0.1,
            65: 0.6,
            70: 1.0,
            75: 1.5,
        },
        "OFarm": {
            20: -19.3,
            25: -16.3,
            30: -13.3,
            35: -10.3,
            40: -7.3,
            45: -4.9,
            50: -2.4,
            55: 0.0,
            60: 1.5,
            65: 3.1,
            70: 4.8,
            75: 6.4,
        },
    },
    # LF refitted from calibration/fielding_sim.csv (LSQ over 30 OOTP scenarios incl.
    # 3D Systematic grid). MAE = 0.9 runs/162 vs 12.3 for previous table — old massively
    # undershot the OFrange cliff at 55 (old +0.0 → new +18.7).
    "LF": {
        "OFrange": {
            20: -20.0,
            25: -17.0,
            30: -14.0,
            35: -11.0,
            40: -8.0,
            45: -5.7,
            50: 0.0,
            55: 18.7,
            60: 20.4,
            65: 20.4,
            70: 20.4,
            75: 20.4,
        },
        "OFerror": {
            20: -13.0,
            25: -10.0,
            30: -7.0,
            35: -4.0,
            40: -1.0,
            45: -0.6,
            50: -0.6,
            55: -0.6,
            60: -0.6,
            65: -0.6,
            70: -0.6,
            75: -0.6,
        },
        "OFarm": {
            20: -15.9,
            25: -12.9,
            30: -9.9,
            35: -6.9,
            40: -3.9,
            45: -1.9,
            50: -0.4,
            55: -0.4,
            60: -0.4,
            65: -0.1,
            70: 0.6,
            75: 1.3,
        },
    },
    # SS refitted from calibration/ss_sim.csv (least-squares over 64 OOTP scenarios,
    # then PAV-smoothed for monotonicity). MAE = 6.4 runs/162 vs 7.3 for previous table.
    # Architectural caveat: additive model can't fully capture RNG×ARM substitution
    # at extreme combos — use [Best position] runs values as a ranking signal, not absolute.
    "SS": {
        "IFrange": {
            20: -43.0,
            25: -36.8,
            30: -30.6,
            35: -24.4,
            40: -18.2,
            45: -12.0,
            50: -12.0,
            55: -12.0,
            60: 0.0,
            65: 16.7,
            70: 25.4,
            75: 25.4,
        },
        "IFerror": {
            20: -22.1,
            25: -19.1,
            30: -16.1,
            35: -13.1,
            40: -10.1,
            45: -7.1,
            50: -4.1,
            55: -4.0,
            60: -0.1,
            65: -0.1,
            70: 4.1,
            75: 4.1,
        },
        "IFarm": {
            20: -14.5,
            25: -11.5,
            30: -8.5,
            35: -5.5,
            40: -2.5,
            45: -2.5,
            50: 0.9,
            55: 0.9,
            60: 9.7,
            65: 11.3,
            70: 14.9,
            75: 17.9,
        },
        "turnDP": {
            20: -22.6,
            25: -18.9,
            30: -15.2,
            35: -11.5,
            40: -7.8,
            45: -4.1,
            50: -0.4,
            55: -0.4,
            60: 1.6,
            65: 1.6,
            70: 2.3,
            75: 2.3,
        },
    },
    # 2B refitted from calibration/fielding_sim.csv (LSQ over 44 OOTP scenarios).
    # MAE = 2.3 runs/162 vs 18.9 for previous table — old IFrange values like -39
    # below RNG=55 were ~10x too punitive vs sim reality.
    "2B": {
        "IFrange": {
            20: -15.7,
            25: -12.7,
            30: -9.7,
            35: -6.7,
            40: -3.7,
            45: -2.4,
            50: 0.0,
            55: 10.6,
            60: 11.0,
            65: 13.1,
            70: 13.1,
            75: 13.1,
        },
        "IFerror": {
            20: -15.0,
            25: -12.0,
            30: -9.0,
            35: -6.0,
            40: -3.0,
            45: -3.0,
            50: -3.0,
            55: -1.8,
            60: -1.8,
            65: -1.1,
            70: 1.4,
            75: 1.4,
        },
        "IFarm": {
            20: -15.6,
            25: -12.6,
            30: -9.6,
            35: -6.6,
            40: -3.6,
            45: -1.8,
            50: 0.0,
            55: 1.0,
            60: 1.7,
            65: 3.9,
            70: 3.9,
            75: 4.6,
        },
        "turnDP": {
            20: -18.2,
            25: -15.2,
            30: -12.2,
            35: -9.2,
            40: -6.2,
            45: -5.3,
            50: -4.4,
            55: 0.0,
            60: 0.3,
            65: 2.7,
            70: 4.5,
            75: 4.5,
        },
    },
    # 3B refitted from calibration/fielding_sim.csv (LSQ over 25 OOTP scenarios).
    # MAE = 1.9 runs/162 vs 3.1 for previous table. TDP omitted (sim shows it's inert at 3B).
    "3B": {
        "IFrange": {
            20: -17.7,
            25: -14.7,
            30: -11.7,
            35: -8.7,
            40: -5.7,
            45: -5.7,
            50: -5.7,
            55: 0.0,
            60: 4.8,
            65: 7.1,
            70: 9.4,
            75: 14.4,
        },
        "IFerror": {
            20: -16.2,
            25: -13.2,
            30: -10.2,
            35: -7.2,
            40: -4.2,
            45: -4.2,
            50: -4.2,
            55: -1.0,
            60: -1.0,
            65: 3.1,
            70: 4.2,
            75: 4.2,
        },
        "IFarm": {
            20: -21.9,
            25: -18.9,
            30: -15.9,
            35: -12.9,
            40: -9.9,
            45: -7.5,
            50: -5.0,
            55: 0.0,
            60: 7.7,
            65: 8.6,
            70: 9.5,
            75: 14.3,
        },
    },
    # 1B refitted from calibration/fielding_sim.csv (LSQ over 11 rows where ARM/TDP
    # held at baseline). MAE = 1.5 runs/162 vs 4.0 for previous table. Sim confirms
    # 1B defense is nearly inert — total RNG swing only ~4 runs, ERR essentially flat,
    # ARM treated as fully inert (single confounded sim observation insufficient to fit).
    "1B": {
        "IFrange": {
            20: -2.6,
            25: -2.6,
            30: -2.6,
            35: 0.0,
            40: 0.3,
            45: 1.2,
            50: 1.2,
            55: 1.2,
            60: 1.2,
            65: 1.2,
            70: 1.2,
            75: 1.2,
        },
        "IFerror": {
            20: -2.0,
            25: -1.0,
            30: -1.0,
            35: -1.0,
            40: -1.0,
            45: -1.0,
            50: -1.0,
            55: -1.0,
            60: -1.0,
            65: -1.0,
            70: -1.0,
            75: -1.0,
        },
        "IFarm": {
            20: 0.0,
            25: 0.0,
            30: 0.0,
            35: 0.0,
            40: 0.0,
            45: 0.0,
            50: 0.0,
            55: 0.0,
            60: 0.0,
            65: 0.0,
            70: 0.0,
            75: 0.0,
        },
    },
}


# ===============================================
# SS interaction correction (RNG x ARM substitution)
# ===============================================
# SS is the one position where additivity isn't enough — RNG and ARM substitute
# for each other in a way our independent lookup tables can't capture (a great
# arm partially makes up for limited range, and stacking both elite ratings
# doesn't double the value). This 2D correction is added on top of the additive
# SS_def sum at runtime; it's calibrated from the residuals of the LSQ-fit
# additive tables vs. observed sim deltas. With this layer, SS MAE drops from
# 6.4 to 0.3 runs/162 over the calibration set.
#
# Lookup is by (IFrange, IFarm) snapped to nearest 5; cells with no direct
# sim observation use the nearest-Manhattan filled cell.
SS_INTERACTION_CORRECTION = {
    # Keys: (IFrange_rating, IFarm_rating); values: runs/162 correction
    # to add on top of the additive sum for this position.
    (30, 30): 12.2,
    (30, 35): 12.2,
    (30, 40): 12.2,
    (30, 45): 12.2,
    (30, 50): 7.7,
    (30, 55): 7.7,
    (30, 60): 7.7,
    (30, 65): -1.2,
    (30, 70): -7.2,
    (30, 75): -9.0,
    (35, 30): 12.2,
    (35, 35): 12.2,
    (35, 40): 12.2,
    (35, 45): 12.2,
    (35, 50): 7.7,
    (35, 55): 7.7,
    (35, 60): 7.7,
    (35, 65): -1.2,
    (35, 70): -7.2,
    (35, 75): -9.0,
    (40, 30): 12.2,
    (40, 35): 12.2,
    (40, 40): 12.2,
    (40, 45): 12.2,
    (40, 50): 7.7,
    (40, 55): 7.7,
    (40, 60): 7.7,
    (40, 65): -1.2,
    (40, 70): -7.2,
    (40, 75): -9.0,
    (45, 30): 12.2,
    (45, 35): 12.2,
    (45, 40): 12.2,
    (45, 45): 5.5,
    (45, 50): 4.6,
    (45, 55): 4.6,
    (45, 60): 4.6,
    (45, 65): -1.2,
    (45, 70): -7.2,
    (45, 75): -9.0,
    (50, 30): 6.6,
    (50, 35): 6.6,
    (50, 40): 6.6,
    (50, 45): -0.5,
    (50, 50): -0.5,
    (50, 55): 0.4,
    (50, 60): 0.4,
    (50, 65): -12.9,
    (50, 70): -17.6,
    (50, 75): -17.6,
    (55, 30): 2.1,
    (55, 35): 2.1,
    (55, 40): 2.1,
    (55, 45): 0.4,
    (55, 50): -1.1,
    (55, 55): -1.5,
    (55, 60): -9.2,
    (55, 65): -5.7,
    (55, 70): -1.3,
    (55, 75): 13.1,
    (60, 30): -11.1,
    (60, 35): -11.1,
    (60, 40): -11.1,
    (60, 45): -9.1,
    (60, 50): -10.5,
    (60, 55): -1.4,
    (60, 60): 6.2,
    (60, 65): 17.0,
    (60, 70): 15.9,
    (60, 75): 14.4,
    (65, 30): -19.0,
    (65, 35): -19.0,
    (65, 40): -19.0,
    (65, 45): -9.9,
    (65, 50): 5.6,
    (65, 55): 11.3,
    (65, 60): 6.7,
    (65, 65): 3.2,
    (65, 70): 3.9,
    (65, 75): 0.7,
    (70, 30): 5.3,
    (70, 35): 5.3,
    (70, 40): 5.3,
    (70, 45): 8.8,
    (70, 50): 7.6,
    (70, 55): 5.5,
    (70, 60): -2.3,
    (70, 65): -3.4,
    (70, 70): -6.7,
    (70, 75): -10.1,
    (75, 30): 6.8,
    (75, 35): 6.8,
    (75, 40): 6.8,
    (75, 45): 6.8,
    (75, 50): 8.1,
    (75, 55): 8.1,
    (75, 60): 8.1,
    (75, 65): -3.4,
    (75, 70): -6.6,
    (75, 75): -6.6,
}
