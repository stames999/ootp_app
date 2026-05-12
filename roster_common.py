"""Shared roster-construction utilities used by both build_system.py
(hitters) and build_pitcher_system.py (pitchers).

History: these definitions used to live in `build_system.py` and the
pitcher system reached into them via private-underscore imports. That
left a coupling smell — fixes had to be applied symmetrically by hand,
and adding a third roster-builder (e.g. for some future role) would
require copying yet again. Moving them here gives both builders a
single source of truth for level / eligibility / DSL semantics.

Both builders re-export these symbols from their own modules so existing
callers (build_excel, streamlit_app, tests, calibration scripts) keep
working without import-path churn.
"""
import csv
import json

import config


# ============================================================================
# Level / capacity constants
# ============================================================================

LEVELS = ['MLB', 'AAA', 'AA', 'A+', 'A', 'R', 'R(DLR)']

# Maximum age allowed at each level. AA / AAA / MLB have no age cap (any
# age can play); the lower-minor caps reflect OOTP's roster eligibility
# (R(DLR) is teen-only, R caps at 22, etc.).
MAX_AGE = {
    'R(DLR)': 21, 'R': 22, 'A': 23, 'A+': 24,
    'AA': 99, 'AAA': 99, 'MLB': 99,
}


# ============================================================================
# Service-time constraints
# ============================================================================
# OOTP service-time limits per level (cumulative pro service years).
# The threshold is INCLUSIVE: a player with exactly 5 yrs total can still
# play A+, but with 6 yrs they can no longer. Above the limit, that level
# is no longer eligible — must be at a higher level. AA / AAA / MLB have
# no service-time limit. yrs_<LEVEL> columns come from
# reader.add_years_at_level (one year per calendar season, credited to
# the highest level reached that year).

SERVICE_LIMITS = {
    'A+':     5,
    'A':      4,
    'R':      3,
    'R(DLR)': 3,
}


def total_service_years(p):
    """Sum of yrs_<LEVEL> across all levels — cumulative pro experience."""
    return sum(p.get(f'yrs_{l}', 0) or 0 for l in LEVELS)


def is_mlb_tenure_protected(p):
    """True if a player has accumulated enough MLB seasons that they
    should not be casually cascaded off the MLB roster. Proxy for
    option-year exhaustion + veteran roster status — by the time a
    player has 3 (config.MLB_TENURE_PROTECTED_YRS) MLB seasons, real
    teams generally don't demote them without a clear plan (options
    exhausted, no-trade rights accumulating, contract structure).

    Used by build_system / build_pitcher_system cascade-sort to treat
    these players as "stuck" at MLB regardless of their `_bot` floor,
    so the cascade only pops them when every alternative is exhausted.
    Soft protection — does NOT prevent demotion if the MLB roster has
    no cascadable alternatives at all."""
    threshold = getattr(config, 'MLB_TENURE_PROTECTED_YRS', 3)
    return (p.get('yrs_MLB', 0) or 0) >= threshold


def service_lowest_level(p):
    """Highest LEVELS index (= lowest level) the player is still eligible
    for given their cumulative service. > 5 yrs blocks A+ and below; > 4
    blocks A and below; > 3 blocks R / R(DLR). Returns the deepest index
    they can still play; combine with age_lowest_level via min() for the
    final `_bot`."""
    s = total_service_years(p)
    if s > SERVICE_LIMITS['A+']:
        return LEVELS.index('AA')      # 2 — A+ exhausted, AA-or-above only
    if s > SERVICE_LIMITS['A']:
        return LEVELS.index('A+')      # 3 — A exhausted
    if s > SERVICE_LIMITS['R']:
        return LEVELS.index('A')       # 4 — R/DSL exhausted
    return len(LEVELS) - 1             # 6 — no service constraint


def age_lowest_level(p):
    """Highest LEVELS index (= lowest level) the player is age-eligible
    for given MAX_AGE. Returns 0 (MLB) for any player older than every
    cap (e.g. age 30+ — they can play any level)."""
    age = p['age']
    for lvl in reversed(LEVELS):
        if age <= MAX_AGE[lvl]:
            return LEVELS.index(lvl)
    return 0


# ============================================================================
# Dominican Summer League eligibility
# ============================================================================

# OOTP nation IDs for the two countries OOTP excludes from the Dominican
# Summer League. The DSL is for international players only — US- and
# Canadian-born players cannot be assigned to a DSL roster, regardless of
# age or service. Confirmed empirically: out of 2021 players currently on
# DSL teams in a fresh save, 0 are Canadian and only 8 are American (out
# of ~110k US-born players in the player pool).
DSL_INELIGIBLE_NATIONS = {206, 36}  # USA, Canada


def dsl_eligible_lowest_level(p):
    """Highest LEVELS index (= lowest tier) the player is eligible for given
    DSL nationality rules. US/Canadian players bottom out at R (index 5);
    everyone else can go down to R(DLR) (index 6). Combined with the age
    and service caps via min() for the final `_bot`."""
    if p.get('nation_id') in DSL_INELIGIBLE_NATIONS:
        return LEVELS.index('R')   # 5 — DSL blocked, R is the lowest tier
    return LEVELS.index('R(DLR)')  # 6 — DSL eligible


# DSL league ID in OOTP. Used by _count_dsl_teams to size R(DLR) capacity
# per org (most orgs have 1-2 DSL affiliates).
DSL_LEAGUE_ID = 234


def _count_dsl_teams(org=None):
    """Count DSL teams (league_id=234) belonging to an org. Returns 1 if
    teams.csv is missing or org not found — most orgs have 1 or 2 DSL
    teams, so 1 is a safe default for missing data. Used by hitter and
    pitcher roster builders for R(DLR) capacity scaling and the R(DLR)
    best/rest sub-roster split."""
    if org is None:
        org = config.team_managed
    try:
        import pandas as _pd
        teams = _pd.read_csv(
            config.filepath / 'teams.csv',
            usecols=['parent_team_id', 'league_id'],
            low_memory=False,
        )
        org_id = next((k for k, v in config.club_lookup.items() if v == org), None)
        if org_id is None:
            return 1
        n = int(((teams['parent_team_id'] == org_id)
                 & (teams['league_id'] == DSL_LEAGUE_ID)).sum())
        return max(1, n)
    except Exception:
        return 1


# ============================================================================
# Injury / unavailable-player loader
# ============================================================================

INJURED_FILE = 'injured.txt'


def _load_injured_names():
    """Return `{'pids': set[int], 'names': set[str]}` enumerating
    currently-injured players. Two sources, two channels:

    1. OOTP `players.csv` `injury_is_injured == 1` (auto-detected) →
       indexed by `player_id` (int). PID-based matching is unambiguous;
       using name strings here caused cross-player collisions like
       every "Jose Rodriguez"-named player in every org getting flagged
       because ONE of them (LAD farm, age 24) was actually injured.

    2. `injured.txt` (one name per line, `#` comments) → manual override
       for non-injury exclusions. Stays name-keyed because the file is
       hand-edited and PID lookups would be a chore. Name collisions
       are still possible there, but the user owns the list explicitly.

    Both sources are optional; missing files just mean no one is flagged.

    Day-to-day (DTD) injuries (`injury_dtd_injury == 1`) are NOT
    exclusions. Those guys are still playing; OOTP just rests them a
    game or two. Only `injury_is_injured == 1` AND no DTD flag counts
    as a proper IL stint that pulls them out of placement.

    The legacy function name is kept for backward compatibility — the
    return shape changed from `set[str]` to a dict on 2026-05-10 so
    callers that match against this need updating (see
    `is_player_injured` helper below).
    """
    pids = set()
    names = set()
    # Auto: OOTP CSV. Reference config.filepath at call time so the
    # Streamlit uploader's monkey-patched temp dir is honoured.
    try:
        with open(config.filepath / 'players.csv', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row.get('injury_is_injured') != '1':
                    continue
                if row.get('injury_dtd_injury') == '1':
                    continue
                try:
                    pids.add(int(row['player_id']))
                except (KeyError, ValueError, TypeError):
                    # Fallback to name if pid is missing / malformed.
                    names.add(f"{row['first_name']} {row['last_name']}")
    except (FileNotFoundError, ImportError, KeyError):
        pass
    # Manual: injured.txt
    try:
        with open(INJURED_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    names.add(line)
    except FileNotFoundError:
        pass
    return {'pids': pids, 'names': names}


def is_player_injured(p, injured):
    """Return True if player dict `p` matches the injured-keys dict
    returned by `_load_injured_names`. Matches first by player_id
    (unambiguous, from OOTP CSV) and falls back to name (covers
    injured.txt manual entries + the rare missing-pid case)."""
    pid = p.get('player_id')
    if pid is not None:
        try:
            if int(pid) in injured['pids']:
                return True
        except (ValueError, TypeError):
            pass
    return p.get('name') in injured['names']
