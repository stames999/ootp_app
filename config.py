from pathlib import Path

# =============
# Project Paths
# =============

filepath = Path(
    "C:/Users/sfwea/OneDrive/Documents/Out of the Park Developments/OOTP Baseball 27/saved_games/Rockies Rebuild.lg/import_export/csv")
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
# Position viability gap (display filter only)
# ============================
# Used to filter the displayed `field` column: a position is shown only
# if the player's adjusted WAR there is within FIELD_VIABILITY_GAP of
# their best position's adjusted WAR. ALL per-position WARs are still
# computed and exported — this only affects the displayed `field` summary
# so the user sees realistic alternatives rather than every position the
# player technically passes the rating floor for. Calibrated to roughly
# "positions where the player would be a passable starter relative to
# their best fit."
FIELD_VIABILITY_GAP = 2.0


# ============================
# Positional adjustments (scarcity premiums)
# ============================
# Fixed per-position run adjustments. Values in runs/162; applied per
# player as a flat add to bat + def, divided by RUNS_PER_WIN_FIELDING
# (= 9.53) to convert to WAR — same divisor used for fielding _def so
# the bat/def/pos_adj chain stays internally consistent in the fielding
# sim's run environment.
#
# Calibrated 2026-05-09 via a grid sweep (calibration/pos_adj_sweep.py)
# scoring against MLB DRS leaders 2024 landing at their MLB primary
# position + pool-balance + Olson-not-CF hard-fail. Replaces an earlier
# team-of-clones-derived set that conflated fielding magnitude with
# scarcity premium.
#
# Test-set match rate: 74% (26/35 elite-glove DRS leaders correctly
# placed). Remaining misplacements are OOTP rating-driven — Gimenez,
# Edman, Hayes, etc. genuinely qualify at SS by their IF range/arm in
# this OOTP save and no pos_adj setting reconciles them with their
# MLB primary position.
#
# DH at -10 is a deliberate "no defensive contribution" cost. Anti-
# placements (Olson must not be CF) are encoded in the sweep scoring
# function, not enforced at runtime here.
#
# Catcher caveat: C is +7.5 here vs FanGraphs' +12.5. Partly because
# OOTP's catcher framing engine plateaus at +8 runs (Cfram >= 65 collapse
# to the same value), so elite framers — worth ~+30 in real MLB FRV —
# are invisible to our model. The +7.5 is what survives once the engine-
# capped framing tier blends with the other catcher contributions; raising
# it to FG's +12.5 would over-credit average catchers without recovering
# the framing tail.
POSITIONAL_ADJUSTMENT_RUNS = {
    # Calibrated per-position to align sim top-5 mean `<pos>_adj`
    # with FG 2025 top-5 mean WAR per position. The sim engine's
    # fielding tables (FIELDING_RUN_VALUES_VS_REPLACEMENT) are left
    # untouched — they encode team-of-clones measurements and shouldn't
    # be reshaped. Per-position positional constants are the
    # appropriate calibration knob: each one shifts the whole position's
    # WAR distribution by a constant, preserving within-position ranking
    # and shape. Pos_adj here is therefore a CALIBRATION constant, not
    # the FG-standard scarcity convention (which we deviate from).
    "C":    12.5,
    "1B":    -7.5,
    "2B":     7.5,
    "3B":     0.0,
    "SS":     7.5,
    "LF":   -13.5,
    "CF":   -11.0,
    "RF":   -16.5,
    "DH":   -17.5,
}

# ============================
# Pitcher rating thresholds used to determine if a pitcher is a starter or reliever
# ============================

PITCH_MINIMUM_RATING = 1  # rating floor for count_pitches — any rating ≥ 1 counts the pitch type as "in the arsenal" (i.e. the pitcher throws it). Was 45 ("effective pitch"); changed 2026-05-12 because SP eligibility is about arsenal size (number of pitch types thrown), not rating quality. A 4-pitch mix at modest grades (e.g. 40/40/40/45) is still SP-viable.
MINIMUM_STARTER_STAMINA = 40  # stamina ≥ 40 → SP-viable; below → RP-only
MIN_PITCHES_FOR_SP = 3  # minimum number of pitches (rated ≥ PITCH_MINIMUM_RATING) to qualify as SP — 2-pitch arms become RP regardless of stamina
# Pitcher classification (sprp / sprpP) uses ONLY position == 1 (from OOTP)
# and the stamina threshold above. Stamina alone is the rotation-viability
# signal; one-pitch specialists with low stamina correctly land in the RP
# bucket regardless of pitch count.

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

# Component-specific runs-per-win values, empirically derived from the
# calibration sim environments. Each value is the slope of the
# (runs/162 → wins/162) regression in that component's sim env. R² > 0.97
# in all three. Used so each component's WAR reflects the actual win
# value of runs in the environment it was measured against, rather than a
# one-size-fits-all conversion.
#
# Where each is read (verified 2026-05-10 in the pipeline review):
# - RUNS_PER_WIN_HITTING:  metrics_hitting (war_hitting / DH_hitting),
#                          org_report._war_from_woba,
#                          build_system.WAR_PER_WOBA_POINT
# - RUNS_PER_WIN_FIELDING: metrics_fielding._def divisor AND metrics_war
#                          for pos_adj conversion (chain-consistent —
#                          fielding tables and pos_adj live in the same
#                          run environment, so no double-conversion)
# - RUNS_PER_WIN_PITCHING: NOT directly read by any module — pitcher
#                          WAR uses PITCHING_WAR_COEFFS which are pre-
#                          scaled empirically (no RPW divisor). Kept here
#                          as documentation of the pitching sim's run env.
RUNS_PER_WIN_HITTING = 10.28   # hitting sim baseline RS/G = 4.38
RUNS_PER_WIN_PITCHING = 10.76  # pitching sim baseline RS/G = 4.40 (origin-forced fit)
RUNS_PER_WIN_FIELDING = 9.53   # fielding sim baseline RS/G = 4.16

REPLACEMENT_LEVEL_WOBA = 0.290  # FanGraphs convention; sets hitting WAR zero point

# Component-aware WAR coefficients for pitchers. Refitted from OOTP team-of-
# clones sims (CTRL + HRA sweeps, 23 points, RMSE 0.15 WAR). Inputs are
# component rates as PERCENTAGES (multiply decimal rate by 100). Output is
# WAR at "good starter" SP usage (~200 IP — top-of-rotation workload, real
# MLB qualifying starters throw 180-220 with 200 a typical solid season).
#
# Two scaling layers applied to the raw fit:
#   1. IP scaling 200/224 = 0.8929 — raw fit was against OOTP Editor WAR
#      which assumes 224 IP/season (32 GS × 7 IP); we scale to a realistic
#      200 IP target. Matches modern MLB top-tier SP usage and gives
#      Skubal-tier aces ~5.5-6.0 WAR (consistent with FG benchmarks).
#   2. Runs-per-win scaling 10/10.76 = 0.9294 — OOTP Editor's WAR uses an
#      implicit ~10 runs/win conversion, but the pitcher sim env has an
#      empirical 10.76 runs/win (R²=0.98). Applying this brings pitcher
#      WAR onto the same sim-empirical basis as hitting (10.28) and
#      fielding (9.53).
# Combined scale factor: 0.8929 × 0.9294 = 0.8299 vs raw OOTP Editor fit.
# All-50 SP lands at ~2.6 WAR (matches "average MLB SP"); aces ~5.5-6.0.
# RP WAR derived as sp_war × RELIEVER_VS_STARTER_AVERAGE_IP (= 0.333),
# implying ~67 IP for an RP — elite-closer/setup-man workload territory.
PITCHING_WAR_COEFFS = {
    "intercept": 9.41,        # raw 11.34 × 0.8299
    "hr_pct_coef": -1.01,     # raw -1.22 × 0.8299
    "bb_pct_coef": -0.38,     # raw -0.46 × 0.8299
    "k_pct_coef": 0.13,       # raw 0.16 × 0.8299
    "h_nothr_pct_coef": -0.19,  # raw -0.23 × 0.8299
}

# Regression of wOBA vs runs/162 games for hitters. Refitted from
# calibration/sim_data.csv (OOTP team-of-clones, 100k G per scenario,
# R²=0.99). Old hand-tuned values: COEFF=554.79, CONST=178.91 (which
# implied replacement wOBA ≈ 0.322 — above league average; clearly miscalibrated).
# New values: empirical slope, with CONST set to put replacement at
# wOBA=0.290 (REPLACEMENT_LEVEL_WOBA, FanGraphs convention). Result:
# league-average MLB hitter (wOBA ≈ 0.310) lands at ~+1.0 WAR; OOTP
# calibrated league-average (wOBA ≈ 0.318) at ~+1.4 WAR; star (wOBA 0.400)
# at ~+5 WAR; elite (wOBA 0.450) at ~+7.4 WAR.
RUNS_PER_GAME_HITTING_COEFF = 496.84
RUNS_PER_GAME_HITTING_CONST = 144.08  # = COEFF × REPLACEMENT_LEVEL_WOBA

RELIEVER_VS_STARTER_AVERAGE_IP = 0.3333333  # relievers assumed to pitch one-third of the innings of a starter, on average
DH_PENALTY = 0.030  # multiplicative wOBA penalty for being a DH (not playing defense).
# Empirically derived from team-of-clones sim: same hitter at each position
# produced wOBA 0.3116 (non-DH avg, range 0.309-0.313) vs 0.3024 (DH).
# Ratio: 1 - (0.3024 / 0.3116) = 0.0295. The penalty is stable across multiple
# sim runs (DH OPS consistently 0.686-0.689). Old hand-tuned value was 0.023.
HANDEDNESS_WEIGHTS = {"R": 0.7, "L": 0.3}

# ====================================================
# Roster builder tunables — hitter cascade
# ====================================================
# All constants below were previously defined in build_system.py /
# build_pitcher_system.py source. Moved here so tuning a threshold no
# longer requires a source edit. Each block keeps the original
# provenance / rationale comment.

# Per-org slot capacities by level. R(DLR) is BASE — actual R(DLR)
# capacity is scaled by org's DSL team count via compute_roster_sizes.
#
# Sizes (post-2026-05 expansion):
#   MLB                = 13 (active-roster minimum, unchanged)
#   AAA / AA           = 15 (was 13; the extra two slots match real-world
#                            AAA/AA roster depth and reduce A-level
#                            under-fill from cascade exhaustion)
#   A+ / A / R / R(DLR)= 16 (was 13/13/15/15; matches the pitcher staff
#                            sizing of 6 SP + 10 RP at these levels)
ROSTER_SIZES_HITTER = {
    'MLB': 13, 'AAA': 15, 'AA': 15, 'A+': 16, 'A': 16, 'R': 16, 'R(DLR)': 16
}

# Minimum wOBA required to be eligible at each level. The cascade ranks
# players by priority(p, lvl) and trims; a player whose wOBA is below
# WOBA_MIN[lvl] is ineligible for that level entirely (their _top is
# the next level down). Calibrated from observation of OOTP league
# distributions — MLB regulars cluster .280+, AAA fringe to .250, etc.
WOBA_MIN_HITTER = {
    'MLB': 0.280,
    'AAA': 0.250,
    'AA': 0.220,
    'A+': 0.210,
    'A': 0.200,
    'R': 0.165,
    'R(DLR)': -1.0,
}

# Premium-position bat relaxation: the wOBA threshold for a level is
# lowered by this many points when the player's primary position is C,
# SS, or CF — the up-the-middle defensive premiums in real baseball.
# A defensive-first profile at any of them plays at a level slightly
# above where his pure bat would qualify, because the glove value at
# scarce positions offsets a borderline bat. Kept small (.005 = ~5 wOBA
# points, roughly +0.25 WAR) so a TRULY overmatched bat still can't
# sneak up.
PREMIUM_WOBA_RELAX = {
    'C':  0.005,
    'SS': 0.005,
    'CF': 0.005,
}

# Standard lineup faces RHP roughly 70-75% of the time. Non-HP starter
# selection weights the platoon-adjusted WAR by this fraction so the
# standard lineup leans toward the matchup that's actually in front of
# the team most often. Note: `wOBA` itself is already a 70/30 R/L blend
# (HANDEDNESS_WEIGHTS), so a 0.70 weight here recovers the existing
# overall `_adj` exactly. 0.725 is the midpoint of the 70-75% range.
LINEUP_RHP_WEIGHT = 0.725

# ====================================================
# Catcher allocation tuning
# ====================================================
# Step-1 catcher allocation scores each catcher by:
#   alloc_score = wOBA + C_FLD_WEIGHT * C_fld + AGE_WEIGHT * min(age, AGE_CAP)
# C_fld typically ranges -2 (poor) to +5 (elite framer); wOBA in the
# .15-.40 band. Using C_fld rather than C_adj avoids double-counting bat.
# At C_FLD_WEIGHT=0.05 the defensive contribution maxes out around ±0.25,
# comparable to a .025 wOBA swing.
C_FLD_WEIGHT = 0.05
# Older catchers preferred for higher levels (less developmental runway).
# Small enough to act as a tiebreak for catchers within ~.012 of each
# other rather than overriding real talent gaps. Capped at AGE_CAP so a
# 35-year-old journeyman doesn't get an unbounded boost.
AGE_WEIGHT = 0.002
AGE_CAP = 30

# Maximum gap (in fielding-WAR units) between a player's BEST non-C
# fielding rating and their C_fld for them to still be considered a
# Step-1 catcher candidate. Without this, a good-bat / bad-glove utility
# player whose pos_adj is RF/SS/etc. but who has a fallback C rating
# can outscore real backup catchers on the bat-driven catcher_alloc_score,
# claim a Step-1 catcher slot at a low level, then get reassigned off C
# by Hungarian — leaving them stuck at the wrong level. 1.5 WAR is
# "significantly worse at C than elsewhere" — they're a fallback, not
# a real dual-position catcher.
C_FLD_GAP_MAX = 1.5

# Catcher rescue (primary-C bat-bypass). If a primary catcher's bat
# plays as a non-C MLB regular AND clears a meaningful WAR floor, route
# them through the non-catcher cascade so the final Hungarian can place
# them at DH / 1B / corner OF where their bat plays. They remain
# is_catcher() (still satisfy backup-C / emergency-C downstream).
#
# Threshold raised from 0.30 to 1.5 (PIPELINE_REVIEW R-01). The 0.30
# floor admitted defense-first backups (Heineman wOBA .302, bnw 0.60)
# into the rescue pool — they then bat-cascaded out of MLB to AAA even
# though their alloc_score would have won them MLB Backup C in Step-1.
# 1.5 ≈ "real positive-WAR bat at a non-C position", filtering for
# catchers whose secondary value at 1B/DH/corner OF actually competes
# with MLB regulars.
CATCHER_RESCUE_MIN_NON_C_WAR = 1.5
# Positions to consider for the rescue's "best non-C MLB WAR" check.
# DH is included (the obvious destination); SS/2B/CF are not — a
# primary-C typically can't field those, so any positive WAR there is
# an artifact.
CATCHER_RESCUE_NON_C_POSITIONS = ('DH', '1B', 'LF', 'RF', '3B')

# ====================================================
# Hitter HP (high-potential) thresholds
# ====================================================
HP_MAX_AGE = 24
# HP qualifies if EITHER projected WAR clears HP_BESTP_ADJ_THRESHOLD
# (league-average regular floor, ~MLB-regular projected WAR) OR
# wOBAP clears HP_WOBA_THRESHOLD (elite bat projection — even with no
# defensive contribution at 1B/DH a wOBAP-.330 hitter is a real
# prospect). The OR-rule combines a holistic projected-WAR signal with
# a bat-only safety net; bestP_adj already encodes bat + def + scarcity,
# so this naturally elevates elite gloves without a defensive premium
# discount.
#
# wOBAP threshold lowered from .340 → .330 to catch borderline-elite bat
# projects whose `bestP_adj` gets dragged down by a corner-OF / DH
# position tag — they'd qualify as HP and then get the premium-fit
# pos_adj override if their `field` list includes CF / SS / 2B.
# Reference: a wOBAP .330 hitter is roughly a 105-110 wRC+ projected bat.
HP_BESTP_ADJ_THRESHOLD = 1.5
HP_WOBA_THRESHOLD = 0.330

# HP players are never placed on the MLB roster regardless of projection.
# Prospects develop at AAA or below; the builder's HP-enforcement logic
# clamps their target level to this index (or deeper if their _bot
# forces lower). 1 = AAA. Set to 0 to disable the block (HPs can land
# at MLB if cascade puts them there).
HP_MIN_LEVEL_INDEX = 1   # AAA — prospects never start at MLB

# MLB-tenure protection removed in R-27. The HP MLB block (R-20) is
# the only soft placement rule — everyone else is fair game based on
# current priority. The earlier two-tier tenure model (R-15 / R-24)
# created more problems than it solved: marginal vets held MLB slots
# from better cascadable players even with the quality gate active.
# Meritocratic cascade is simpler and gives the right outcome anyway.

# Minimum fielding-only WAR for treating a player as a "real" defender
# at a given position. Used in displacement / premium-fit logic, not in
# HP determination itself.
PREMIUM_FLD_MIN = 1.5

# Positions where an HP with elite glove gets pos_adj overridden to that
# position. Scarcity adjustment can push pos_adj to a corner OF for a
# real CF defender (CF_adj negative due to weak bat, RF_adj positive
# because of a strong corner glove); without the override the Hungarian
# benches them at their natural level in favour of corner-OF bats while
# a sub-floor defender mans the premium spot. Catcher excluded — Step-1
# catcher allocation already handles glove-aware placement. 3B excluded
# because it's the most bat-tolerant of the scarce positions.
HP_PREMIUM_FIT_POSITIONS = ('CF', 'SS', '2B')

# Position groupings used by Util IF / Util OF bench-role classification
# and by Step-4 utility-promotion candidate scoring.
IF_POSITIONS = ('2B', '3B', 'SS')
OF_POSITIONS = ('LF', 'CF', 'RF')

# ====================================================
# Pitcher cascade tunables
# ====================================================
# Per-level rotation + bullpen sizes. R(DLR) is base — actual capacity
# scales with org's DSL team count (each DSL team gets its own staff).
#
# Sizes (post-2026-05 expansion to match hitter ROSTER_SIZES_HITTER):
#   MLB                = 5 SP + 8 RP = 13 (unchanged, active-roster spec)
#   AAA / AA           = 5 SP + 10 RP = 15 (was 5+8; +2 RP for depth)
#   A+ / A / R / R(DLR)= 6 SP + 10 RP = 16 (was 5+8; 6 SP for development
#                            depth — minor-league rotations realistically
#                            cycle 6+ starters across a season)
SP_PER_LEVEL = {
    'MLB': 5, 'AAA': 5, 'AA': 5, 'A+': 6, 'A': 6, 'R': 6, 'R(DLR)': 6,
}
RP_PER_LEVEL = {
    'MLB': 8, 'AAA': 10, 'AA': 10, 'A+': 10, 'A': 10, 'R': 10, 'R(DLR)': 10,
}

# Maximum pwOBA a pitcher can allow and still belong at a given level.
# Lower = better stuff, so this is a CEILING (analogous to WOBA_MIN_HITTER
# being a floor for hitters). Calibrated against league wOBA ≈ .320:
# MLB pitchers cluster .280-.340; AAA fringe to .365; lower minors
# more permissive.
PWOBA_MAX = {
    'MLB':    0.345,
    'AAA':    0.370,
    'AA':     0.385,
    'A+':     0.395,
    'A':      0.405,
    'R':      0.420,
    'R(DLR)': 1.000,  # no upper limit — accepts whatever's left
}

# ====================================================
# Pitcher platoon-split classification (R-28)
# ====================================================
# Purely magnitude-driven, level-agnostic. The tag describes the SHAPE
# of the platoon split — quality (and therefore role / level implications)
# is read separately from overall pwOBA. A AAA arm with a wide vsL lean
# is a AAA-level matchup specialist; an MLB arm with the same split is
# an MLB-level one. Same tag, different role context.
#
# Five buckets:
#   vsR_specialist / vsL_specialist — |split| ≥ .030. Wide enough that
#     deployment should respect the lean. At MLB level + MLB-tier strong
#     side = the LOOGY / ROOGY catch the cascade might otherwise miss.
#     At minor-league levels, the same magnitude means a real matchup
#     edge for development planning.
#   slight_vsR_split / slight_vsL_split — .015 < |split| < .030. A
#     noticeable lean but not specialist-grade. Useful flag for closer-
#     candidate evaluation (slight lean is less ideal than truly
#     platoon-neutral) and to spot developing specialists whose split
#     hasn't fully widened yet.
#   neutral — |split| ≤ .015. Handles either side equally. Combine with
#     overall pwOBA + assigned level to judge role fit (closer-eligible
#     at MLB if pwOBA ≤ .345; closer-eligible at AAA if pwOBA ≤ .370; etc).
#
# Direction note: pwOBA is opponent wOBA — LOWER = better. So
#   pwOBA_split = pwOBAR - pwOBAL
# is NEGATIVE for vsR-leaning (lower pwOBA vs R = better vs R) and
# POSITIVE for vsL-leaning. Magnitudes match conventional wOBA-split
# scouting reports: 30 pts is "wide", under 15 pts is "neutral", the
# 15-30 band is a "slight lean".
PITCHER_SPLIT_SPECIALIST_THRESHOLD = 0.030
PITCHER_SPLIT_NEUTRAL_THRESHOLD = 0.015

# ====================================================
# Service-time cap toggle
# ====================================================
# OOTP's service-time rule (SERVICE_LIMITS in roster_common.py) is a
# REAL roster-eligibility constraint: a 6+ yr vet cannot be assigned
# below AA, a 5+ yr vet cannot be below A+, etc. The cap stays in
# place by default (True).
#
# What changed in R-28: the cascade no longer ARTIFICIALLY PROTECTS
# service-pinned vets via the (cascadable, priority) sort key. A vet
# at their service floor is no longer placed at the front of the
# cascade list; they compete on priority with everyone else. If they
# rank worst, they get popped — and since they can't cascade further
# down, they go to overflow (release pool). The rescue pass
# (_rescue_overflow_sps in build_pitcher_system.py) then offers each
# overflowing SP one shot to win a bullpen slot at a feasible level
# (between their _top and _bot) by outranking the worst displaceable
# RP there. This converts what was previously a hard "stuck at AA"
# slot-block into a meritocratic competition with a swingman safety
# net.
#
# Flip to False to remove the floor entirely (would let vets cascade
# all the way down to R(DLR), modelling a more permissive league
# without strict OOTP eligibility). Almost certainly not what you
# want — default True matches OOTP behaviour.
SERVICE_CAP_ENABLED = True

# ====================================================
# Priority blend + blocker penalty (R-30 / R-32, lifted to config R-33)
# ====================================================
# The `priority` (hitter) and `pitcher_priority` (pitcher) functions
# blend current and projected performance for cascade ordering at non-
# MLB levels. R-30 moved this from 70/30 to 85/15 because the 30%
# projection weight was demoting solid org-depth players behind HPs
# whose current performance wasn't competitive yet.
#
# R-32 added a "blocker penalty" inside the same priority blend: a
# non-HP at his ceiling (|current − potential| < BLOCKER_CEILING_DELTA)
# whose ceiling is sub-MLB gets penalised by his distance from
# MLB-tier. Pushes maxed-out depth players behind HPs with real
# projection upside.
#
# Single ranking rule across the system (post-R-31): cascade ordering,
# HP-enforcement displacement, push-down, and rescue all use these
# priority functions — no parallel ranking pass.
PRIORITY_BLEND_CURRENT_WEIGHT = 0.85
PRIORITY_BLEND_PROJECTED_WEIGHT = 0.15
# Threshold for "at-ceiling" detection — non-HPs with current
# performance within this delta of projection are considered maxed out
# (no real upside) and eligible for the blocker penalty. Direction-
# agnostic (`< 0.005` works for both pwOBA where lower is better and
# wOBA where higher is better because of how the sign is handled in
# each priority function).
BLOCKER_CEILING_DELTA = 0.005
# Sub-MLB ceiling thresholds. These reuse `PWOBA_MAX['MLB']` (.345) /
# `WOBA_MIN_HITTER['MLB']` (.280) by intent — kept as separate constants
# only because they're used in a different semantic role (penalty
# anchor, not eligibility cap) and renaming makes intent clearer.
BLOCKER_MLB_PWOBA = 0.345
BLOCKER_MLB_WOBA = 0.280

# ====================================================
# Bench classification weights (R-33, lifted to config)
# ====================================================
# Hitter bench-role scoring blends fielding sum and current batting
# WAR in WAR units. Same weighting used for Utility IF, Utility OF.
# Was hardcoded 0.6 / 0.4 in build_system.py:431,448.
BENCH_FIELD_WEIGHT = 0.6
BENCH_BAT_WEIGHT = 0.4

# ====================================================
# Bullpen handedness balance
# ====================================================
# Applied AFTER pitcher cascade pull-up to MLB / AAA / AA only. Lower
# minors are skewed toward RHP and aren't worth distorting; the user's
# real audience is the upper-minors / MLB pen. Hard 2-4 LHP, soft target 3.
LHP_LEVELS = ('MLB', 'AAA', 'AA')
LEFTY_MIN = 2
LEFTY_TARGET = 3
LEFTY_MAX = 4
# Soft-target swap is rejected if the promoted LHP's pitcher_priority
# blend is more than this much worse than the dropped RHP's. ~10 pwOBA
# points — roughly the gap between a back-end MLB reliever and a top
# AAA reliever.
LEFTY_TARGET_MAX_COST = 0.010

# ====================================================
# Pitcher swingman pull-up (opt-in feature toggle)
# ====================================================
# When enabled, after the standard RP cascade + LHP balance, pull AAA
# (or lower) SP-viable non-HP arms up to the MLB bullpen if their
# rp_warP exceeds the worst MLB RP's rp_warP by at least
# PITCHER_SWINGMAN_PULLUP_MIN_WARP_DELTA. The candidate's role flips
# from SP to RP for the call-up — model treats it as a long-relief /
# swingman audition rather than a permanent role change.
#
# Default OFF: the cascade-only system is the calibrated baseline.
# R-03 investigation found 10 orgs would benefit by potential WAR but
# most net negative in current-year WAR — turning this on biases
# toward development upside over current-year roster stability.
#
# Constraints (always enforced when ON):
#   - Candidate must be non-HP (HP enforcement owns those slots).
#   - Swap must not break LHP balance (LHP count stays in [LEFTY_MIN,
#     LEFTY_MAX] post-swap).
#   - Threshold of 0.5 WARP filters out marginal noise; lower thresholds
#     produce spurious swaps that hurt current-year value.
#
# Side effect: the candidate's old SP slot at AAA / lower is left empty
# (not auto-backfilled). Real-world equivalent: org signs a FA / calls
# someone up for that AAA rotation slot.
PITCHER_SWINGMAN_PULLUP_ENABLED = False
PITCHER_SWINGMAN_PULLUP_MIN_WARP_DELTA = 0.5


# ====================================================
# Pitcher HP thresholds
# ====================================================
# HP pitcher = young minor-league arm whose projection puts them at
# clearly above-MLB-rosterable quality. Mirrors the hitter HP idea:
# minor=1, age <= cap, projection clears a meaningful bar. We use
# pwOBAP <= HP_PITCHER_MAX_PWOBAP — sits between the AAA and MLB
# roster ceilings (PWOBA_MAX['AAA']=.370, PWOBA_MAX['MLB']=.345) so
# HP requires "real rotation/bullpen upside" rather than just
# "barely MLB-eligible".
#
# Cap raised from .330 → .340 to bring HP pitcher count closer to HP
# hitter count — at .330 the pitcher pool was ~half the hitter pool
# (258 vs 561 across 30 orgs), reflecting an over-tight gate rather
# than a real talent imbalance. .340 still keeps HP pitchers below
# the MLB threshold (.345) so the bar means "projects at least to
# fringe-MLB", not "currently MLB-rosterable".
HP_PITCHER_MAX_AGE = 24
HP_PITCHER_MAX_PWOBAP = 0.335


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
    # OOTP handedness code (1 = R, 2 = L). Surfaced for the bullpen LHP
    # balance pass in build_pitcher_system._enforce_lhp_balance.
    "throws",
    # Nationality. Used by build_system.dsl_eligible_lowest_level to block
    # US (206) and Canadian (36) players from R(DLR) — OOTP's DSL is
    # international-eligible only.
    "nation_id",
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
    # Position-WAR columns can be NaN when calc_war() applies POSITION_FLOOR
    # (any relevant rating < 40 NaNs the position; 1B exempt). Blanking lets
    # DataTables sort numerically and avoids the literal string "nan" in cells.
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

# Base rates for a pitcher with all 50 ratings.
# Refitted from OOTP team-of-clones sims (3 baseline reps, 100k G each, 54% GB).
# Old hand-tuned values: HR=0.0326, BB=0.0714, K=0.2078, contact=0.2050.
BASE_PITCHING_RATES = {
    "hr_vs_baserate": 0.0270,
    "bb_vs_baserate": 0.0750,
    "k_vs_baserate": 0.2140,
    "h_nothr_vs_baserate": 0.2137,
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
#
# Multiplicative ratios applied to BASE_PITCHING_RATES. For each rating
# category, look up the player's rating, multiply each component by the
# corresponding *_vs_mult factor. All five categories combine multiplicatively.
#
# Schema (post-refit): keys are *_vs_mult (was *_vs_adj in the old additive
# table). Old additive form deprecated 2026-05; multiplicative confirmed by
# HRA × CTRL = 20/20 interaction sim (predicted 0.472 pwOBA, actual 0.468).
#
# Tables refit from OOTP team-of-clones sims:
#   - Control / HRA: full sweeps (11 points each, 20-80), monotonic.
#   - PBABIP: zeroed (effect too weak to refit reliably; single PBABIP=20 sim
#     showed only 1.4pp contact rate change).
#   - Stamina: zeroed (sweep across 40-80 confirmed zero effect on rate stats;
#     stamina drives IP per appearance, not quality per IP).
#   - Stuff: mechanically converted from old additive table using OLD base
#     rates as denominator. Preserves the original K-driver behavior.

PITCHING_COMPONENTS_ADJUST_MAP = {
    "Control": {
        "20": {"hr_vs_mult": 0.8519, "bb_vs_mult": 2.8933, "k_vs_mult": 0.8318, "h_nothr_vs_mult": 0.8284},
        "25": {"hr_vs_mult": 0.8889, "bb_vs_mult": 2.2133, "k_vs_mult": 0.8879, "h_nothr_vs_mult": 0.8892},
        "30": {"hr_vs_mult": 0.9259, "bb_vs_mult": 1.9333, "k_vs_mult": 0.9159, "h_nothr_vs_mult": 0.9126},
        "35": {"hr_vs_mult": 0.9630, "bb_vs_mult": 1.6400, "k_vs_mult": 0.9393, "h_nothr_vs_mult": 0.9454},
        "40": {"hr_vs_mult": 0.9630, "bb_vs_mult": 1.3600, "k_vs_mult": 0.9673, "h_nothr_vs_mult": 0.9735},
        "45": {"hr_vs_mult": 1.0000, "bb_vs_mult": 1.1600, "k_vs_mult": 0.9860, "h_nothr_vs_mult": 0.9828},
        "50": {"hr_vs_mult": 1.0000, "bb_vs_mult": 1.0000, "k_vs_mult": 1.0000, "h_nothr_vs_mult": 1.0000},
        "55": {"hr_vs_mult": 1.0000, "bb_vs_mult": 0.9333, "k_vs_mult": 1.0047, "h_nothr_vs_mult": 1.0062},
        "60": {"hr_vs_mult": 1.0370, "bb_vs_mult": 0.8533, "k_vs_mult": 1.0093, "h_nothr_vs_mult": 1.0062},
        "65": {"hr_vs_mult": 1.0370, "bb_vs_mult": 0.7800, "k_vs_mult": 1.0210, "h_nothr_vs_mult": 1.0109},  # interp 60/70
        "70": {"hr_vs_mult": 1.0370, "bb_vs_mult": 0.7067, "k_vs_mult": 1.0327, "h_nothr_vs_mult": 1.0156},
        "75": {"hr_vs_mult": 1.0556, "bb_vs_mult": 0.6267, "k_vs_mult": 1.0374, "h_nothr_vs_mult": 1.0250},  # interp 70/80
        "80": {"hr_vs_mult": 1.0741, "bb_vs_mult": 0.5467, "k_vs_mult": 1.0421, "h_nothr_vs_mult": 1.0343},
    },
    "pBABIP": {
        "35": {"hr_vs_mult": 1.0, "bb_vs_mult": 1.0, "k_vs_mult": 1.0, "h_nothr_vs_mult": 1.0},
        "40": {"hr_vs_mult": 1.0, "bb_vs_mult": 1.0, "k_vs_mult": 1.0, "h_nothr_vs_mult": 1.0},
        "45": {"hr_vs_mult": 1.0, "bb_vs_mult": 1.0, "k_vs_mult": 1.0, "h_nothr_vs_mult": 1.0},
        "50": {"hr_vs_mult": 1.0, "bb_vs_mult": 1.0, "k_vs_mult": 1.0, "h_nothr_vs_mult": 1.0},
        "55": {"hr_vs_mult": 1.0, "bb_vs_mult": 1.0, "k_vs_mult": 1.0, "h_nothr_vs_mult": 1.0},
        "60": {"hr_vs_mult": 1.0, "bb_vs_mult": 1.0, "k_vs_mult": 1.0, "h_nothr_vs_mult": 1.0},
        "65": {"hr_vs_mult": 1.0, "bb_vs_mult": 1.0, "k_vs_mult": 1.0, "h_nothr_vs_mult": 1.0},
        "70": {"hr_vs_mult": 1.0, "bb_vs_mult": 1.0, "k_vs_mult": 1.0, "h_nothr_vs_mult": 1.0},
    },
    "HRA": {
        "20": {"hr_vs_mult": 3.5926, "bb_vs_mult": 0.9867, "k_vs_mult": 1.0140, "h_nothr_vs_mult": 0.8892},
        "25": {"hr_vs_mult": 2.6296, "bb_vs_mult": 1.0000, "k_vs_mult": 1.0047, "h_nothr_vs_mult": 0.9314},
        "30": {"hr_vs_mult": 2.2222, "bb_vs_mult": 1.0133, "k_vs_mult": 1.0047, "h_nothr_vs_mult": 0.9454},
        "35": {"hr_vs_mult": 1.8148, "bb_vs_mult": 1.0133, "k_vs_mult": 1.0047, "h_nothr_vs_mult": 0.9594},
        "40": {"hr_vs_mult": 1.4444, "bb_vs_mult": 1.0133, "k_vs_mult": 1.0000, "h_nothr_vs_mult": 0.9735},
        "45": {"hr_vs_mult": 1.1852, "bb_vs_mult": 1.0000, "k_vs_mult": 0.9953, "h_nothr_vs_mult": 0.9875},
        "50": {"hr_vs_mult": 1.0000, "bb_vs_mult": 1.0000, "k_vs_mult": 1.0000, "h_nothr_vs_mult": 1.0000},
        "55": {"hr_vs_mult": 0.9259, "bb_vs_mult": 1.0133, "k_vs_mult": 1.0000, "h_nothr_vs_mult": 1.0016},
        "60": {"hr_vs_mult": 0.8148, "bb_vs_mult": 1.0133, "k_vs_mult": 1.0047, "h_nothr_vs_mult": 1.0016},
        "65": {"hr_vs_mult": 0.7222, "bb_vs_mult": 1.0067, "k_vs_mult": 1.0047, "h_nothr_vs_mult": 1.0039},  # interp 60/70
        "70": {"hr_vs_mult": 0.6296, "bb_vs_mult": 1.0000, "k_vs_mult": 1.0047, "h_nothr_vs_mult": 1.0062},
        "75": {"hr_vs_mult": 0.5556, "bb_vs_mult": 1.0067, "k_vs_mult": 1.0000, "h_nothr_vs_mult": 1.0109},  # interp 70/80
        "80": {"hr_vs_mult": 0.4815, "bb_vs_mult": 1.0133, "k_vs_mult": 0.9953, "h_nothr_vs_mult": 1.0156},
    },
    "Stuff": {
        "35": {"hr_vs_mult": 0.9969, "bb_vs_mult": 0.9790, "k_vs_mult": 0.6506, "h_nothr_vs_mult": 1.1093},
        "40": {"hr_vs_mult": 0.9908, "bb_vs_mult": 0.9804, "k_vs_mult": 0.8099, "h_nothr_vs_mult": 1.0766},
        "45": {"hr_vs_mult": 1.0092, "bb_vs_mult": 1.0014, "k_vs_mult": 0.9259, "h_nothr_vs_mult": 1.0234},
        "50": {"hr_vs_mult": 1.0000, "bb_vs_mult": 1.0000, "k_vs_mult": 1.0000, "h_nothr_vs_mult": 1.0000},
        "55": {"hr_vs_mult": 1.0000, "bb_vs_mult": 0.9930, "k_vs_mult": 1.1492, "h_nothr_vs_mult": 0.9532},
        "60": {"hr_vs_mult": 0.9969, "bb_vs_mult": 0.9972, "k_vs_mult": 1.2300, "h_nothr_vs_mult": 0.9415},
        "65": {"hr_vs_mult": 0.9816, "bb_vs_mult": 0.9916, "k_vs_mult": 1.2719, "h_nothr_vs_mult": 0.8927},
        "70": {"hr_vs_mult": 0.9939, "bb_vs_mult": 0.9944, "k_vs_mult": 1.3619, "h_nothr_vs_mult": 0.8941},
        "75": {"hr_vs_mult": 0.9877, "bb_vs_mult": 0.9986, "k_vs_mult": 1.4240, "h_nothr_vs_mult": 0.8727},
        "80": {"hr_vs_mult": 0.9969, "bb_vs_mult": 0.9986, "k_vs_mult": 1.5202, "h_nothr_vs_mult": 0.8459},
    },
    "Stamina": {
        "40": {"hr_vs_mult": 1.0, "bb_vs_mult": 1.0, "k_vs_mult": 1.0, "h_nothr_vs_mult": 1.0},
        "45": {"hr_vs_mult": 1.0, "bb_vs_mult": 1.0, "k_vs_mult": 1.0, "h_nothr_vs_mult": 1.0},
        "50": {"hr_vs_mult": 1.0, "bb_vs_mult": 1.0, "k_vs_mult": 1.0, "h_nothr_vs_mult": 1.0},
        "55": {"hr_vs_mult": 1.0, "bb_vs_mult": 1.0, "k_vs_mult": 1.0, "h_nothr_vs_mult": 1.0},
        "60": {"hr_vs_mult": 1.0, "bb_vs_mult": 1.0, "k_vs_mult": 1.0, "h_nothr_vs_mult": 1.0},
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
    # C refitted from calibrated team-of-clones sims (10-pt FRM sweep + BLK/ARM
    # floor-ceiling pairs, all anchored at baseline 55/55/55 in the league-avg
    # run env, RS/G=4.16). Additivity verified: FRM(45.6) + BLK(6.6) + ARM(8.9)
    # = 61.1 vs cross-position floor/ceiling 62.4 (98% match). FRM is dominant
    # (73% of variance, asymmetric — 5x penalty vs ceiling); BLK and ARM
    # contribute small magnitudes interpolated linearly between sim points.
    "C": {
        "Cabil": {  # blocking, floor=-2.0, ceiling=+4.6
            20: -2.0,
            25: -1.7,
            30: -1.4,
            35: -1.1,
            40: -0.9,
            45: -0.6,
            50: -0.3,
            55: 0.0,
            60: 0.9,
            65: 1.8,
            70: 2.8,
            75: 3.7,
        },
        "Cfram": {  # framing, full sweep — plateau-smoothed at 65-75 (raw 9.3/7.9/7.4 → +8)
            20: -38.0,
            25: -36.0,
            30: -33.0,
            35: -27.0,
            40: -20.0,
            45: -13.0,
            50: -4.0,
            55: 0.0,
            60: 5.0,
            65: 8.0,
            70: 8.0,
            75: 8.0,
        },
        "Carm": {  # arm, floor=-6.9, ceiling=+2.0 — heavily downside-weighted
            20: -6.9,
            25: -5.9,
            30: -4.9,
            35: -3.9,
            40: -3.0,
            45: -2.0,
            50: -1.0,
            55: 0.0,
            60: 0.4,
            65: 0.8,
            70: 1.2,
            75: 1.6,
        },
    },
    # CF refitted from calibrated team-of-clones sims. Baseline 60/50/55
    # (RNG/ERR/ARM). Cross-position floor (all 20): -22.6; ceiling (all 80):
    # +36.7. Range 59.3.
    #
    # Individual rating sweeps:
    #   OFrange: full 9-pt sweep, plateau ~-11 below 60, sharp jump to +28
    #            plateau above 60 (the "elite-CF inflection")
    #   OFarm:   floor/ceiling, -6.1 to +7.8, near-linear
    #   OFerror: floor/ceiling, -2.1 to +2.6, near-linear
    #
    # Additivity holds (within sim noise). CF is 64% RNG-driven; ARM ~24%,
    # ERR ~12% of variance. The 60→65 cliff is the dominant feature.
    "CF": {
        "OFrange": {  # plateau ~-11 below 60, sharp jump to ~+28 plateau above
            20: -12.5,
            25: -12.0,
            30: -12.0,
            35: -11.0,
            40: -11.1,
            45: -11.0,
            50: -8.9,
            55: -11.5,
            60: 0.0,
            65: 28.0,
            70: 28.0,
            75: 28.0,
        },
        "OFarm": {  # linear interp from 20=-6.1 to 80=+7.8, anchor at 55
            20: -6.1,
            25: -5.2,
            30: -4.3,
            35: -3.5,
            40: -2.6,
            45: -1.7,
            50: -0.9,
            55: 0.0,
            60: 1.6,
            65: 3.1,
            70: 4.7,
            75: 6.2,
        },
        "OFerror": {  # linear interp from 20=-2.1 to 80=+2.6, anchor at 50
            20: -2.1,
            25: -1.8,
            30: -1.4,
            35: -1.1,
            40: -0.7,
            45: -0.4,
            50: 0.0,
            55: 0.4,
            60: 0.9,
            65: 1.3,
            70: 1.7,
            75: 2.2,
        },
    },
    # RF refitted from calibrated team-of-clones sims. Baseline 50/50/50.
    # Cross-position floor (all 20): -18.9; ceiling (all 80): +26.8. Range 45.7.
    #
    # Individual rating sweeps:
    #   OFrange: full 9-pt sweep, -8.5 to +17.0 (plateau structure ~-7 below
    #            50, ~+19 above 50)
    #   OFarm:   full 9-pt sweep, -6.1 to +9.9 (gradual curve)
    #   OFerror: floor/ceiling, -1 (extrapolated from +0.2 sim noise) to +2.4
    #
    # Additivity holds (saturation within sim-noise tolerance, ~9% at ceiling,
    # mild anti-saturation at floor). No interaction matrix needed.
    "RF": {
        "OFrange": {  # plateau ~-7 below 50, plateau ~+19 above 50
            20: -8.5,
            25: -8.0,
            30: -7.5,
            35: -7.0,
            40: -7.0,
            45: -7.0,
            50: 0.0,
            55: 19.0,
            60: 19.0,
            65: 19.0,
            70: 19.0,
            75: 19.0,
        },
        "OFarm": {  # gradual curve, 16-run total range
            20: -6.1,
            25: -5.4,
            30: -4.7,
            35: -4.0,
            40: -3.3,
            45: -2.0,
            50: 0.0,
            55: 3.5,
            60: 5.0,
            65: 6.0,
            70: 7.5,
            75: 9.0,
        },
        "OFerror": {  # very small effect, near-linear (within noise of zero at floor)
            20: -1.0,
            25: -0.7,
            30: -0.5,
            35: -0.3,
            40: -0.2,
            45: -0.1,
            50: 0.0,
            55: 0.5,
            60: 1.0,
            65: 1.5,
            70: 2.0,
            75: 2.4,
        },
    },
    # LF refitted from calibrated team-of-clones sims. Baseline 50/50/50.
    # Cross-position floor (all 20): -15.3; ceiling (all 80): +19.8. Range 35.1.
    #
    # Individual rating sweeps:
    #   OFrange: full 9-pt sweep, plateau ~+16 above 50 with slight downward drift
    #   OFarm:   floor/ceiling, -5.7 to +6.6, near-linear
    #   OFerror: floor/ceiling, +3.3 to +1.0 (both within sim noise of zero)
    #
    # Additivity holds (within 2 runs of cross-position floor/ceiling). LF is
    # 79% RNG-driven — by far the most range-dominant fielding position.
    # ERR is essentially noise; ARM contributes a small linear effect.
    "LF": {
        "OFrange": {  # plateau-smoothed at 55-75 (raw 18.1/17.0/16.2/15.0/14.2)
            20: -13.7,
            25: -13.0,
            30: -12.0,
            35: -12.0,
            40: -10.0,
            45: -5.0,
            50: 0.0,
            55: 16.0,
            60: 16.0,
            65: 16.0,
            70: 16.0,
            75: 16.0,
        },
        "OFarm": {  # linear interp from 20=-5.7 to 80=+6.6, anchor at 50
            20: -5.7,
            25: -4.8,
            30: -3.8,
            35: -2.9,
            40: -1.9,
            45: -1.0,
            50: 0.0,
            55: 1.1,
            60: 2.2,
            65: 3.3,
            70: 4.4,
            75: 5.5,
        },
        "OFerror": {  # essentially zero — small linear values for honesty
            20: -1.0,
            25: -0.8,
            30: -0.6,
            35: -0.4,
            40: -0.3,
            45: -0.1,
            50: 0.0,
            55: 0.2,
            60: 0.4,
            65: 0.6,
            70: 0.8,
            75: 1.0,
        },
    },
    # SS refitted from calibrated team-of-clones sims. Baseline 60/60/60/60.
    # Cross-position floor (all 20): -47.8; ceiling (all 80): +24.2. Range 72.0.
    #
    # Individual rating sweeps:
    #   IFrange: full 9-pt sweep, plateau structure (~-21 below 60, ~+16 above)
    #   IFarm:   full 9-pt sweep, plateau structure (~-17 below 60, ~+13 above)
    #   IFerror: floor/ceiling, -9.1 to +3.1, asymmetric linear
    #   turnDP:  floor/ceiling, -10.3 to +3.9, asymmetric linear
    #
    # Saturation: additive sum overstates extreme combos by ~40% on both sides.
    # Corrected at runtime via FIELDING_SATURATION["SS"] (uniform linear
    # ~0.6× compression both sides).
    "SS": {
        "IFrange": {  # plateau ~-21 below 60 (with mild floor at -27), ~+16 above 60
            20: -27.0,
            25: -27.0,
            30: -27.0,
            35: -27.0,
            40: -27.0,
            45: -25.0,
            50: -21.0,
            55: -21.0,
            60: 0.0,
            65: 16.0,
            70: 16.0,
            75: 16.0,
        },
        "IFarm": {  # ~-17 below 60 (floor -29); rising 60→65 to +10, plateau ~+15 at 70-75
            # ARM=65 is set to +10 (sim-measured) rather than the 70-75 plateau
            # value (+14 at 70, +15.9 at 75) — the prior plateau-smoothed +14
            # at 65 over-stated the (RNG=65, ARM=65) corner by ~4 runs and
            # was the main contributor to the SS saturation-fit residual.
            20: -29.0,
            25: -29.0,
            30: -28.0,
            35: -28.0,
            40: -25.0,
            45: -22.0,
            50: -17.0,
            55: -16.0,
            60: 0.0,
            65: 10.0,
            70: 14.0,
            75: 15.0,
        },
        "IFerror": {  # linear interp from 20=-9.1 to 80=+3.1, anchor at 60
            20: -9.1,
            25: -8.0,
            30: -6.8,
            35: -5.7,
            40: -4.6,
            45: -3.4,
            50: -2.3,
            55: -1.1,
            60: 0.0,
            65: 0.8,
            70: 1.6,
            75: 2.3,
        },
        "turnDP": {  # linear interp from 20=-10.3 to 80=+3.9, anchor at 60
            20: -10.3,
            25: -9.0,
            30: -7.7,
            35: -6.4,
            40: -5.2,
            45: -3.9,
            50: -2.6,
            55: -1.3,
            60: 0.0,
            65: 1.0,
            70: 1.9,
            75: 2.9,
        },
    },
    # 2B refitted from calibrated team-of-clones sims. Baseline 55/55/50/55
    # (RNG/ERR/ARM/TDP — note ARM baseline is 50, others 55).
    # Cross-position floor (all 20): -59.0; ceiling (all 80): +7.8. Range 66.8.
    #
    # Individual rating sweeps:
    #   IFrange: full 8-pt sweep, gradual descent below 55, plateau ~+2 above
    #   turnDP:  full 9-pt sweep, gradual S-curve from -18.7 to +6.8
    #   IFerror: floor/ceiling, -4.7 to +2.9, near-linear
    #   IFarm:   floor/ceiling, -10.7 to +4.1, near-linear (baseline ARM=50)
    #
    # Saturation: positive side ~40% (all-65 +9.3 → +5.4); negative side
    # mild and only at extremes. Corrected at runtime via FIELDING_SATURATION
    # ["2B"] (linear 0.589× on positive, tanh asymptote -73 on negative).
    "2B": {
        "IFrange": {  # gradual descent below 55, plateau ~+2 above
            20: -37.0,
            25: -35.0,
            30: -33.0,
            35: -32.0,
            40: -32.0,
            45: -29.0,
            50: -25.0,
            55: 0.0,
            60: 2.0,
            65: 2.0,
            70: 2.0,
            75: 2.0,
        },
        "IFerror": {  # linear interp from 20=-4.7 to 80=+2.9, anchor at 55
            20: -4.7,
            25: -4.0,
            30: -3.4,
            35: -2.7,
            40: -2.0,
            45: -1.3,
            50: -0.7,
            55: 0.0,
            60: 0.6,
            65: 1.2,
            70: 1.7,
            75: 2.3,
        },
        "IFarm": {  # linear interp from 20=-10.7 to 80=+4.1, anchor at 50
            20: -10.7,
            25: -8.9,
            30: -7.1,
            35: -5.4,
            40: -3.6,
            45: -1.8,
            50: 0.0,
            55: 0.7,
            60: 1.4,
            65: 2.1,
            70: 2.7,
            75: 3.4,
        },
        "turnDP": {  # full 9-pt sweep, gradual S-curve
            20: -18.7,
            25: -16.0,
            30: -13.0,
            35: -10.0,
            40: -6.4,
            45: -5.7,
            50: -1.7,
            55: 0.0,
            60: 0.9,
            65: 4.0,
            70: 4.0,
            75: 5.4,
        },
    },
    # 3B refitted from calibrated team-of-clones sims. Baseline 50/55/60/50
    # (RNG/ERR/ARM/TDP). Cross-position floor (all 20): -37.2; ceiling (all 80):
    # +23.8. Range = 61.0.
    #
    # Individual rating sweeps:
    #   IFrange: full 7-pt sweep, 20=-27 to 80=+19, sharp inflection at 50→55
    #   IFarm:   full 8-pt sweep, 20=-28 to 80=+21, sharp inflection at 60→65
    #   IFerror: floor/ceiling, 20=-7.9, 80=+6.3, linear interp
    #   turnDP:  floor/ceiling, 20=-1.9, 80=+2.1, near-zero contribution
    #
    # Saturation: ~50% on positive side, asymmetric on negative. Corrected
    # at runtime via FIELDING_SATURATION["3B"] (tanh both sides). Plus a
    # one-cell RNG×ARM interaction correction at (55, 55) — the all-55 sim
    # showed a 7-run residual after uniform saturation because RNG=55's
    # 50→55 inflection (+17) only delivers when ARM ≥ 60.
    # See FIELDING_INTERACTION_CORRECTION["3B"] for the cell.
    "3B": {
        "IFrange": {  # full sweep, plateau-smoothed at 60-75 (raw 21.8/17.6/18.5)
            20: -27.0,
            25: -22.0,
            30: -17.0,
            35: -14.0,
            40: -12.0,
            45: -10.0,
            50: 0.0,
            55: 17.0,
            60: 20.0,
            65: 20.0,
            70: 20.0,
            75: 20.0,
        },
        "IFerror": {  # linear interp from 20=-7.9 to 80=+6.3, anchored at 55
            20: -7.9,
            25: -6.8,
            30: -5.6,
            35: -4.5,
            40: -3.4,
            45: -2.3,
            50: -1.1,
            55: 0.0,
            60: 1.3,
            65: 2.5,
            70: 3.8,
            75: 5.0,
        },
        "IFarm": {  # full sweep, anchored at 60 (3B baseline ARM=60)
            20: -28.0,
            25: -27.0,
            30: -27.0,
            35: -26.0,
            40: -26.0,
            45: -20.0,
            50: -18.0,
            55: -12.0,
            60: 0.0,
            65: 17.0,
            70: 18.0,
            75: 21.0,
        },
        "turnDP": {  # linear interp from 20=-1.9 to 80=+2.1, anchored at 50
            20: -1.9,
            25: -1.6,
            30: -1.3,
            35: -0.9,
            40: -0.6,
            45: -0.3,
            50: 0.0,
            55: 0.4,
            60: 0.7,
            65: 1.1,
            70: 1.4,
            75: 1.8,
        },
    },
    # 1B refitted from calibrated team-of-clones sims. Baseline 35/35/35/35
    # (typical 1B rating profile in OOTP — much lower than other infield).
    # Cross-position floor (all 20): -3.5 runs; ceiling (all 80): +9.8 runs.
    # Range only 13.3 runs — confirms 1B has minimal defensive variance.
    #
    # Individual rating sweeps (each at 20 and 80, others held at 35):
    #   IFrange: -1.8 → +6.8  (range 8.6, ~65% of 1B variance)
    #   IFerror: +0.7 → +1.4  (range 0.7 — within sim noise of zero)
    #   IFarm:   +2.9 → +3.6  (range 0.7 — within sim noise of zero)
    #   turnDP:  +2.2 → +1.5  (range -0.7 — inverted, sim noise)
    #
    # Only IFrange is meaningful; ERR/ARM/TDP set to 0 since all measurements
    # were within ±2 run sim-noise tolerance. RNG curve is roughly linear,
    # piecewise around the 35 baseline anchor.
    "1B": {
        "IFrange": {  # slope 0.12/pt below 35, 0.151/pt above 35
            20: -1.8,
            25: -1.2,
            30: -0.6,
            35: 0.0,
            40: 0.8,
            45: 1.5,
            50: 2.3,
            55: 3.0,
            60: 3.8,
            65: 4.5,
            70: 5.3,
            75: 6.0,  # clamped via closest_rating; sim measured 80=+6.8
        },
        "IFerror": {  # within sim noise of zero
            20: 0.0, 25: 0.0, 30: 0.0, 35: 0.0, 40: 0.0, 45: 0.0,
            50: 0.0, 55: 0.0, 60: 0.0, 65: 0.0, 70: 0.0, 75: 0.0,
        },
        "IFarm": {  # within sim noise of zero
            20: 0.0, 25: 0.0, 30: 0.0, 35: 0.0, 40: 0.0, 45: 0.0,
            50: 0.0, 55: 0.0, 60: 0.0, 65: 0.0, 70: 0.0, 75: 0.0,
        },
        "turnDP": {  # within sim noise of zero (added for parity with other IF positions)
            20: 0.0, 25: 0.0, 30: 0.0, 35: 0.0, 40: 0.0, 45: 0.0,
            50: 0.0, 55: 0.0, 60: 0.0, 65: 0.0, 70: 0.0, 75: 0.0,
        },
    },
}


# ===============================================
# Infield saturation correction (2B / 3B / SS)
# ===============================================
# All three non-1B infield positions show saturation at extreme rating combos:
# the additive sum of 1D table contributions overstates the true run impact
# when multiple ratings move away from baseline together. Calibrated from
# sim sweeps at all-20/40/55/65/80 plus a 3B RNG×ARM corner test.
# See calibration/fit_saturation.py for the fit.
#
# Saturation form, applied per-position to the post-additive sum:
#   saturate(x) = +CEIL_POS * tanh(x / SCALE_POS)   if x >= 0
#                 -CEIL_NEG * tanh(-x / SCALE_NEG)  if x < 0
# Sides where the data is in the linear regime of the curve produce huge
# CEIL/SCALE that degenerate to a slope ≈ CEIL/SCALE — see the inline notes.
FIELDING_SATURATION = {
    "2B": {
        "ceil_pos":  200.000,  # +side LINEAR (slope ≈ 0.589)
        "scale_pos": 339.844,
        "ceil_neg":   73.164,  # -side TANH (asymptote -73)
        "scale_neg":  63.671,
    },
    "3B": {
        "ceil_pos":   45.748,  # +side TANH (asymptote +46)
        "scale_pos":  83.072,
        "ceil_neg":   37.730,  # -side TANH (asymptote -38)
        "scale_neg":  26.177,
    },
    "SS": {
        "ceil_pos":  200.000,  # +side LINEAR (slope ≈ 0.618)
        "scale_pos": 323.449,
        "ceil_neg":  200.000,  # -side LINEAR (slope ≈ 0.628)
        "scale_neg": 318.516,
    },
}

# 2D rating-pair corrections added to the additive sum BEFORE saturation.
# Currently only 3B has a confirmed cell — the all-55 sim showed a 7-run
# residual after saturation that uniform compression can't explain: at 3B,
# RNG=55 is just above its 50→55 inflection (+17 jump) but only delivers
# that benefit when ARM ≥ 60 (ARM's own inflection); with ARM=55, the RNG
# benefit is partially negated. Lookup is exact (snap to nearest 5);
# unlisted cells get correction 0.
FIELDING_INTERACTION_CORRECTION = {
    "3B": {
        # (IFrange, IFarm) → runs added before saturation
        (55, 55): -6.58,
    },
}
