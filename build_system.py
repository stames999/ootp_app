"""LAA hitter assignment v3 - wOBA-driven with overflow cascade."""
import json

from config import RUNS_PER_GAME_HITTING_COEFF as _COEFF, RUNS_PER_WIN_HITTING as _RPW_H
# Tunable thresholds — see config.py "Roster builder tunables" section
# for full provenance / rationale comments. Imported here under the names
# they're used by in this module (alias-imports for the few that have
# disambiguating "_HITTER" suffixes in config to mark hitter scope).
from config import (  # noqa: F401  (some are re-exported)
    ROSTER_SIZES_HITTER as ROSTER_SIZES,
    WOBA_MIN_HITTER as WOBA_MIN,
    PREMIUM_WOBA_RELAX,
    C_FLD_WEIGHT, AGE_WEIGHT, AGE_CAP, C_FLD_GAP_MAX,
    CATCHER_RESCUE_MIN_NON_C_WAR, CATCHER_RESCUE_NON_C_POSITIONS,
    LINEUP_RHP_WEIGHT,
    HP_MAX_AGE, HP_BESTP_ADJ_THRESHOLD, HP_WOBA_THRESHOLD,
    PREMIUM_FLD_MIN, HP_PREMIUM_FIT_POSITIONS,
    IF_POSITIONS, OF_POSITIONS,
)

# Shared roster-construction utilities — single source of truth used by both
# this hitter system and build_pitcher_system. Re-exported here so existing
# callers (build_excel, streamlit_app, tests) don't need import-path churn.
from roster_common import (  # noqa: F401  (re-exports)
    LEVELS, MAX_AGE, SERVICE_LIMITS, DSL_LEAGUE_ID, DSL_INELIGIBLE_NATIONS,
    total_service_years, age_lowest_level, service_lowest_level,
    dsl_eligible_lowest_level, _count_dsl_teams, _load_injured_names,
    is_player_injured, is_mlb_tenure_protected,
    INJURED_FILE,
)
from config import HP_MIN_LEVEL_INDEX
import config

POSITIONS = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH']


def compute_roster_sizes(org=None):
    """Return ROSTER_SIZES with R(DLR) scaled by the org's DSL team count.
    Reads teams.csv (in config.filepath); falls back to the base sizes if
    the file is missing or unparseable."""
    sizes = dict(ROSTER_SIZES)
    n_dsl = _count_dsl_teams(org)
    sizes['R(DLR)'] = ROSTER_SIZES['R(DLR)'] * n_dsl
    return sizes

def best_non_c_war(p):
    """Max raw (non-scarcity-adjusted) MLB WAR across non-C positions a
    primary-C might realistically slot into via Hungarian. NaN-skipping;
    returns 0 if all candidate positions are NaN."""
    vals = [p.get(pos) for pos in CATCHER_RESCUE_NON_C_POSITIONS
            if p.get(pos) is not None]
    return max(vals) if vals else 0

HITTERS_JSON = 'outputs/hitters.json'

def load_team(org=None):
    """Load hitters for a single org. Defaults to config.team_managed."""
    if org is None:
        from config import team_managed
        org = team_managed
    d = json.load(open(HITTERS_JSON))
    return [r for r in d['rows'] if r['org'] == org]


def is_catcher(p):
    return p.get('C_adj') is not None

def is_catcher_candidate(p):
    """True if the player is a viable Step-1 catcher allocation candidate.
    Either:
      - primary catcher (pos_adj == 'C'), OR
      - multi-position player whose C glove is competitive with their best
        other position fielding rating (best_other_fld - C_fld <= C_FLD_GAP_MAX).
    Excludes utility players whose C rating is a defensive fallback only —
    their bat would otherwise let them outscore real backup catchers and
    claim a Step-1 catcher slot at a low level, only to be moved off C by
    Hungarian and end up stuck at the wrong level."""
    if not is_catcher(p):
        return False
    if p.get('pos_adj') == 'C':
        return True
    cfld = p.get('C_fld') or 0
    other_flds = [p.get(f'{pos}_fld') for pos in ('1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF')]
    other_flds = [v for v in other_flds if v is not None]
    if not other_flds:
        return True
    return (max(other_flds) - cfld) <= C_FLD_GAP_MAX

def catcher_alloc_score(p):
    """Catcher level/bench score: current bat + glove + small older-player
    tiebreak. Single source of truth for both Step 1 level allocation and
    Step 4 Backup C bench selection — both want the same notion of "best
    available catcher for the higher slot"."""
    woba = p.get('wOBA') or 0
    cfld = p.get('C_fld') or 0
    age = min(p.get('age') or 0, AGE_CAP)
    return woba + C_FLD_WEIGHT * cfld + AGE_WEIGHT * age

def priority(p, level=None):
    """Cascade/trim ordering blend. At MLB the only thing that matters is
    *current* performance — projection upside doesn't help an aging vet
    on the active roster lose his slot to a prospect, and a young arm
    whose ceiling is real should still earn the spot on his current bat.
    At every other level we keep a flat 70/30 current/projected blend so
    a prospect with same-current-bat-but-real-upside edges a player with
    no projection — modest enough that young prospects don't get over-
    promoted on potential alone."""
    woba = p.get('wOBA') or 0
    if level == 'MLB':
        return woba
    wobap = p.get('wOBAP') or 0
    return 0.7 * woba + 0.3 * wobap

def woba_max_level(p):
    # Ceiling is current wOBA only. We tried blending wOBAP for young players
    # to lift high-projection bats, but it over-promoted prospects into levels
    # their current bats couldn't handle and forced cascade to displace proven
    # mature players. The HP system already covers true prospects without
    # needing to inflate _top.
    #
    # Premium-position bat relaxation: a primary C/SS/CF gets PREMIUM_WOBA_RELAX
    # points knocked off each threshold, reflecting position scarcity — a
    # defensive-first up-the-middle profile plays at a level slightly above
    # his pure-bat eligibility. Small enough (.005) that it admits only
    # borderline cases, not real overmatches.
    woba = p.get('wOBA') or 0
    relax = PREMIUM_WOBA_RELAX.get(p.get('pos_adj'), 0.0)
    for lvl in LEVELS:
        if woba >= WOBA_MIN[lvl] - relax:
            return LEVELS.index(lvl)
    return len(LEVELS) - 1

def projected_pos_adj(p, pos):
    """Current pos_adj + bat development runway. Fielding doesn't develop."""
    cur = p.get(f'{pos}_adj')
    if cur is None: return None
    bat_dev = (p.get('war_hittingP') or 0) - (p.get('war_hitting') or 0)
    return cur + bat_dev

# Linear-weights coefficient from the pipeline. war_hitting is computed
# as (wOBA * RUNS_PER_GAME_HITTING_COEFF − RUNS_PER_GAME_HITTING_CONST) /
# RUNS_PER_WIN_HITTING in metrics_hitting.calc_hitting_metrics. Because
# that's linear in wOBA, the WAR change per unit wOBA is just
# COEFF / RUNS_PER_WIN_HITTING — independent of the player's overall
# wOBA or sign of war_hitting. Constants imported at top of file so
# any future recalibration of the hitting slope automatically flows through.
WAR_PER_WOBA_POINT = _COEFF / _RPW_H  # ≈ 48.33 WAR per 1.0 wOBA at 496.84/10.28


def weighted_platoon_pos_adj(p, pos, weight_r=LINEUP_RHP_WEIGHT):
    """Standard-lineup score for non-HP starters: weighted blend of vs-RHP
    and vs-LHP scarcity-adjusted WAR at `pos`. Returns None if the player
    can't play the position."""
    r = pos_adj_split(p, pos, 'R')
    if r is None:
        return None
    l = pos_adj_split(p, pos, 'L')
    if l is None:
        return r
    return weight_r * r + (1 - weight_r) * l

def pos_adj_split(p, pos, vs):
    """Position-adjusted WAR with the hitting component shifted by the
    player's platoon wOBA delta. `vs` must be 'R' or 'L'.

    pos_adj = fielding_at_pos + positional_bonus + hitting_war. We hold
    fielding/positional constant and replace hitting_war with the
    platoon-specific value. Because war_hitting is linear in wOBA in the
    pipeline, the substitution simplifies to:

        pos_adj_split = pos_adj + (wOBA_split − wOBA) * WAR_PER_WOBA_POINT

    Note: this is ADDITIVE in the wOBA delta, NOT multiplicative on
    war_hitting. A `war_hit * (split - overall) / overall` formulation
    flips sign for below-replacement hitters (war_hit < 0) — a player who
    hits BETTER vs L would get a WORSE platoon score. The additive
    linear-weights form avoids that.

    Players with wOBA == 0 or no platoon split data (e.g. prospects with
    no MLB PA where wOBAR == wOBAL == wOBA) collapse back to pos_adj —
    the right answer when there's no real split to apply. Returns None if
    the player can't play this position.
    """
    base = p.get(f'{pos}_adj')
    if base is None:
        return None
    woba = p.get('wOBA') or 0
    if woba <= 0:
        return base
    split_key = 'wOBAR' if vs == 'R' else 'wOBAL'
    woba_split = p.get(split_key)
    if woba_split is None:
        return base
    return base + (woba_split - woba) * WAR_PER_WOBA_POINT

def fill_starters_split(pool, level, vs, standard_starters=None):
    """Pick 9 starters using platoon-adjusted position scores. Same Hungarian
    over the same pool as `fill_starters`, but the score swaps in the
    handedness-specific hitting WAR.

    At MLB / AAA / AA / A+ / A this is a tactical lineup choice — the
    handedness Hungarian picks the best bat for the matchup. At R / R(DLR)
    the +10 dev bonus mirrors `fill_starters`: HP prospects play every day
    regardless of matchup, since rookie ball is for development not
    optimisation.

    `standard_starters` (optional): when provided, HP prospects who are
    starters in the standard lineup at position X are pinned to X in the
    platoon variant — they can only play X or sit. Avoids awkward platoon-
    only position shifts (a 3B prospect moved to CF vs LHP because his
    platoon bat fits awkwardly elsewhere). Non-HP veterans are NOT pinned —
    a 1B who plays 2B competently can legitimately shift across the IF in
    a platoon. Callers who want detection-mode (e.g. HP overmatch checks)
    leave it None.
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    pos_order = ['C', 'SS', '2B', 'CF', '3B', '1B', 'LF', 'RF', 'DH']
    is_dev = level in ('R', 'R(DLR)')
    pinned = ({p['name']: pos for pos, p in standard_starters.items()
               if p and is_high_potential(p)}
              if standard_starters else {})

    def score(p, pos):
        # Pin HP standard starters to their standard position. Other
        # positions are unreachable for them in the platoon — they either
        # play their standard slot or sit on the bench.
        pinned_pos = pinned.get(p['name'])
        if pinned_pos is not None and pinned_pos != pos:
            return None
        pwar = pos_adj_split(p, pos, vs)
        if pwar is None: return None
        # Same natural-position bonus as fill_starters: HPs get the full
        # 0.5 anchor; non-HPs get only the tiny priority tiebreak so the
        # platoon Hungarian picks pure handedness performance.
        if p.get('pos_adj') == pos:
            natural = (0.5 if is_high_potential(p) else 0) + 0.001 * priority(p)
        else:
            natural = 0
        # Rookie-ball dev bonus: HPs always start in every lineup at R /
        # R(DLR), matching the standard Hungarian. Their bat won't reliably
        # play the platoon split anyway and they need ABs more than the
        # team needs the marginal vs-handedness upgrade.
        bonus = 10.0 if (is_dev and is_high_potential(p)) else 0
        return pwar + natural + bonus

    n_p = len(pool)
    INF = -1e6
    cost = np.full((n_p, len(pos_order)), INF)
    for i, p in enumerate(pool):
        for j, pos in enumerate(pos_order):
            s = score(p, pos)
            if s is not None:
                cost[i, j] = s
    row_ind, col_ind = linear_sum_assignment(-cost)
    starters = {pos: None for pos in pos_order}
    for r, c in zip(row_ind, col_ind):
        if cost[r, c] > INF / 2:
            starters[pos_order[c]] = pool[r]
    return starters


def fill_backups(pool, starters, vs):
    """Per-position backup at each spot in the level's vs-`vs` lineup.
    Picks the best non-starter who can play the position (`{pos}_adj` not
    None), scored by `pos_adj_split` for the relevant handedness — the
    same matchup-adjusted WAR the platoon Hungarian uses. The same player
    can be the listed backup at multiple positions: a multi-position
    bench bat is the next-up choice at every spot they cover, and the
    real-game pick depends on which starter actually needs a day off."""
    pos_order = ['C', 'SS', '2B', 'CF', '3B', '1B', 'LF', 'RF', 'DH']
    starter_names = {p['name'] for p in starters.values() if p}
    candidates = [p for p in pool if p['name'] not in starter_names]
    backups = {pos: None for pos in pos_order}
    for pos in pos_order:
        best = None
        best_score = float('-inf')
        for p in candidates:
            score = pos_adj_split(p, pos, vs)
            if score is None:
                continue
            if score > best_score:
                best, best_score = p, score
        backups[pos] = best
    return backups


def fill_starters(pool, level):
    # Hungarian assignment over (player, position) cost matrix. Maximises
    # total team WAR via scipy's linear_sum_assignment (Jonker-Volgenant).
    # When two assignments produce identical totals (e.g. Schwarber-1B /
    # Harper-DH where both players have the same 1B_fld so swapping them
    # is mathematically a wash) the solver's tiebreaker is internal row/
    # column order — it is NOT deterministic from the user's perspective
    # and isn't a "preferred" placement. See PIPELINE_REVIEW R-08 / M-10.
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    pos_order = ['C', 'SS', '2B', 'CF', '3B', '1B', 'LF', 'RF', 'DH']

    is_dev = level in ('R', 'R(DLR)')

    # DH and 1B are the two "fallback" positions Hungarian uses when a
    # surplus HP can't get their natural slot — both treat positional
    # athleticism as a non-asset. Block HPs from either unless their actual
    # primary position IS that slot. A true 1B/DH prospect can still start
    # there; a CF/SS/etc. forced into one cascades down.
    NON_POSITIONAL = {'DH', '1B'}
    def score(p, pos):
        if (pos in NON_POSITIONAL
                and is_high_potential(p)
                and p.get('pos_adj') not in NON_POSITIONAL):
            return None
        # Every level optimises for runs/game using the 72.5/27.5 RHP/LHP
        # split. HPs no longer get a projection-based score override — if a
        # high-projection prospect at AAA can't earn their starting slot on
        # current matchup performance, they cascade to AA where their bat
        # plays. That's the realistic developmental progression, and it
        # avoids overmatching young prospects with raw projections.
        is_hp = is_high_potential(p)
        pwar = weighted_platoon_pos_adj(p, pos)
        if pwar is None: return None
        # Natural-position bonus: HPs get the full 0.5 anchor at their
        # natural slot (development consistency — they should play their
        # listed primary). Non-HPs get only a tiny priority tiebreak so
        # the Hungarian picks pure platoon-weighted performance.
        if p.get('pos_adj') == pos:
            natural = (0.5 if is_hp else 0) + 0.001 * priority(p)
        else:
            natural = 0
        bonus = 0
        if is_dev and is_hp:
            bonus = 10.0  # rookie ball: HPs always start
        elif p.get('_force_start') == level:
            bonus = 10.0
        return pwar + natural + bonus
    
    n_p = len(pool)
    n_pos = len(pos_order)
    INF = -1e6
    cost = np.full((n_p, n_pos), INF)
    for i, p in enumerate(pool):
        for j, pos in enumerate(pos_order):
            s = score(p, pos)
            if s is not None:
                cost[i, j] = s
    row_ind, col_ind = linear_sum_assignment(-cost)
    starters = {pos: None for pos in pos_order}
    used = set()
    for r, c in zip(row_ind, col_ind):
        if cost[r, c] > INF / 2:
            starters[pos_order[c]] = pool[r]
            used.add(pool[r]['name'])
    bench = [p for p in pool if p['name'] not in used]
    return starters, bench

# Note: PREMIUM_POS used internally below for HP-anchor logic. Not exported.
PREMIUM_POS = {'C', '2B', '3B', 'SS', 'CF'}


def classify_bench(bench, level=None):
    """Order the bench into role-defined slots, then depth.

    Returns a list of (role_label, player) tuples. The first four labels
    follow the user's bench design:
      1. Backup C  - best non-starting catcher by catcher_alloc_score
                      (current wOBA + glove + small older-player tiebreak)
      2. Utility IF - glove-first non-starter: max IF positions among
                      {2B, 3B, SS} they can play, tiebreak by sum of
                      fielding-only WAR across those positions, then
                      wOBA. Picks the best leather among viable bats —
                      not the best bat among viable leather.
      3. Utility OF - same shape over {LF, CF, RF}, with a +1 position-
                      count bump for CF eligibility (range as speed proxy).
      4. Best bat  - highest priority(p, level) among whoever's left.
    Subsequent slots are labelled 'Depth' in priority order. If no player
    fits a role (e.g. no catcher on the bench), that slot's player is None
    and the role is still included so callers can render an empty slot.

    `level`: when 'MLB', priority becomes pure current wOBA (no projection
    weight) — an MLB bench bat is judged on what they'll deliver this
    season, not on upside. At every other level the flat 70/30 default
    keeps a small upside boost for prospects.
    """
    pool = list(bench)
    ordered = []

    def take(pred_score):
        if not pool:
            return None
        # pred_score returns None to disqualify; otherwise a sortable key.
        scored = [(pred_score(p), p) for p in pool]
        scored = [(s, p) for s, p in scored if s is not None]
        if not scored:
            return None
        _, best = max(scored, key=lambda sp: sp[0])
        pool.remove(best)
        return best

    # 1. Backup C — same score as Step 1 level allocation so the
    #    "best available catcher" notion is consistent across the system.
    bc = take(lambda p: catcher_alloc_score(p) if is_catcher(p) else None)
    ordered.append(('Backup C', bc))

    # 2. Utility IF — glove-first but bat matters. Score tuple:
    #      (positions_playable, 0.6*fld_sum + 0.4*bat_war)
    #    Multi-position is still a hard prerequisite of utility (more
    #    positions wins outright), but within a tied position count the
    #    weighted glove+bat score lets a slightly-worse-glove player with
    #    a meaningfully better bat overtake a glove-only specialist.
    #    Both terms are in WAR units so the 60/40 split is on like-for-like.
    def if_score(p):
        fld_vals = [p.get(f'{pos}_fld') for pos in IF_POSITIONS]
        valid = [v for v in fld_vals if v is not None]
        if not valid:
            return None
        fld_sum = sum(valid)
        bat_war = p.get('war_hitting') or 0
        return (len(valid), 0.6 * fld_sum + 0.4 * bat_war)
    ordered.append(('Utility IF', take(if_score)))

    # 3. Utility OF — same shape. CF eligibility still adds +1 to the
    #    position count (speed/range proxy as well as a position, so a
    #    CF-capable OF beats a same-fielding LF/RF-only). Score is
    #    weighted glove+bat in WAR units.
    def of_score(p):
        fld_vals = {pos: p.get(f'{pos}_fld') for pos in OF_POSITIONS}
        valid_pos = [pos for pos, v in fld_vals.items() if v is not None]
        if not valid_pos:
            return None
        cf_bonus = 1 if 'CF' in valid_pos else 0
        fld_sum = sum(fld_vals[pos] for pos in valid_pos)
        bat_war = p.get('war_hitting') or 0
        return (
            len(valid_pos) + cf_bonus,
            0.6 * fld_sum + 0.4 * bat_war,
        )
    ordered.append(('Utility OF', take(of_score)))

    # 4. Best bat — level-aware priority so MLB picks pure current bat.
    ordered.append(('Best bat', take(lambda p: priority(p, level))))

    # Depth: whoever is left, by priority (same level-aware blend).
    pool.sort(key=lambda p: priority(p, level), reverse=True)
    for p in pool:
        ordered.append(('Depth', p))
    return ordered

def is_very_poor_fielder(p):
    """True if a player has NO playable defensive home outside 1B / DH.
    Definition: max `<pos>_fld` across non-1B / non-DH positions is
    below -0.5 WAR. Used to decide whether an HP starting at DH or 1B
    at AAA/AA/A+ should cascade further down — players who clear this
    bar (i.e., NOT very poor fielders) have a real defensive position
    elsewhere and should be developing it in the lower minors rather
    than slotting into bat-only roles at the higher tiers.

    Returns True only when the player has nowhere else to play — those
    are kept put as legitimate DH/1B-only prospects (Frank Thomas /
    Schwarber types) and not cascaded down for "defensive development"
    they can't deliver."""
    non_dh_1b = ['C', '2B', '3B', 'SS', 'LF', 'CF', 'RF']
    best_fld = float('-inf')
    for pos in non_dh_1b:
        fld = p.get(f'{pos}_fld')
        if fld is not None and fld > best_fld:
            best_fld = fld
    return best_fld < -0.5


def apply_hp_premium_fit_override(p):
    """If `p` is an HP with `_fld >= PREMIUM_FLD_MIN` at any premium-fit
    position (CF / SS / 2B), set their `pos_adj` to whichever of those
    they defend best. Mutates the player dict. Does nothing for non-HPs
    or HPs without elite premium-position glove. Idempotent.

    Why: scarcity adjustment can hand a CF-capable bat a corner-OF
    `pos_adj` (a CF defender with a corner-OF-quality bat ends up with
    RF_adj > CF_adj after scarcity, even though they really play CF).
    The Hungarian's natural-position bonus and HP enforcement then
    bench them at a level above where their bat plays, while a sub-floor
    defender mans CF a level below. Overriding pos_adj to the actual
    premium glove fixes both: HP enforcement still cascades them down
    until they start; Hungarian's natural bonus lands them at the
    premium position instead of a corner."""
    if not is_high_potential(p):
        return
    candidates = []
    for pos in HP_PREMIUM_FIT_POSITIONS:
        fld = p.get(f'{pos}_fld')
        if fld is not None and fld >= PREMIUM_FLD_MIN:
            candidates.append((fld, pos))
    if not candidates:
        return
    # Best premium glove first; tie-broken by HP_PREMIUM_FIT_POSITIONS order
    # (CF > SS > 2B) which tracks defensive scarcity.
    candidates.sort(key=lambda fp: (-fp[0], HP_PREMIUM_FIT_POSITIONS.index(fp[1])))
    p['pos_adj'] = candidates[0][1]


def is_high_potential(p):
    """Minor-league prospect (minor=1, age <= HP_MAX_AGE) qualifying via
    EITHER projected WAR (bestP_adj >= 2.0, league-average regular) OR
    elite bat projection (wOBAP >= .340). The OR combines a holistic
    WAR test (which elevates elite gloves and drops bat-only borderlines)
    with a bat-only safety net for genuine wOBAP-elite prospects whose
    defense at 1B/DH pulls their bestP_adj below the 2.0 bar.
    """
    if p.get('minor') != 1:
        return False
    if p['age'] > HP_MAX_AGE:
        return False
    bestP_adj = p.get('bestP_adj') or float('-inf')
    wobap = p.get('wOBAP') or 0
    return bestP_adj >= HP_BESTP_ADJ_THRESHOLD or wobap >= HP_WOBA_THRESHOLD

def main(org=None):
    laa = load_team(org)
    # Strip transient flags from any prior run on cached dicts (load_team
    # currently re-reads from disk, but this guards against future callers
    # that hand us already-processed players).
    for p in laa:
        p.pop('_force_start', None)
    # Exclude international complex: minor=0 + age <20 (not in active minor system this year)
    complex_players = [p for p in laa if p.get('minor') == 0 and p['age'] < 20]
    laa = [p for p in laa if not (p.get('minor') == 0 and p['age'] < 20)]
    # Pull out players listed in injured.txt — they don't compete for active
    # roster spots. Rerun the system once they're cleared. Separate from the
    # `flag` column (which is a display marker for the HTML reports — see
    # reader.is_flagged / flagged.txt — and intentionally NOT used here).
    injured = _load_injured_names()
    flagged_players = [p for p in laa if is_player_injured(p, injured)]
    laa = [p for p in laa if not is_player_injured(p, injured)]
    overflow = []
    by_level = {lvl: [] for lvl in LEVELS}

    # HP premium-fit pos_adj override: a CF-capable HP whose scarcity-
    # adjusted best position came out as a corner OF gets re-tagged to
    # the premium position they actually defend, so downstream HP
    # enforcement and the Hungarian put them at CF/SS/2B instead of a
    # corner. Applied here (rather than in metrics_war) so the override
    # is local to roster construction and doesn't affect exports.
    for p in laa:
        apply_hp_premium_fit_override(p)

    # Compute eligible range. _bot combines age and service-time floors —
    # the more restrictive (smaller index = higher level) wins. A player
    # whose service has burned through R/A/A+ can't be sent down there,
    # even if they're young enough.
    valid_players = []
    for p in laa:
        top = woba_max_level(p)
        bot = min(age_lowest_level(p), service_lowest_level(p),
                  dsl_eligible_lowest_level(p))
        # Set _top / _bot on every player (including those who go straight
        # to overflow). The bench-refinement overflow lookup needs _top to
        # check upper-level eligibility; before this the keys were only set
        # on valid_players and overflow lookups crashed on stranded bats.
        p['_top'] = top
        p['_bot'] = bot
        if top > bot:
            overflow.append(p)
            continue
        valid_players.append(p)

    # Per-org roster sizes — R(DLR) scales by DSL team count (1 or 2)
    roster_sizes = compute_roster_sizes(org)

    # === Catcher rescue: primary-C bat-bypass ===
    # Identify primary catchers whose wOBA qualifies for MLB AND whose
    # best non-C MLB WAR clears the rescue threshold. Pull them out of
    # the Step 1 candidate pool — they go through the non-catcher cascade
    # so the final Hungarian can place them at DH / 1B / corner OF at MLB
    # rather than locking them into a lower level as a starting C.
    rescued_catchers = [
        p for p in valid_players
        if is_catcher_candidate(p)
        and p['_top'] == 0  # _top == MLB
        and best_non_c_war(p) >= CATCHER_RESCUE_MIN_NON_C_WAR
    ]
    rescued_ids = {id(p) for p in rescued_catchers}

    # === STEP 1: Catchers (2/level) ===
    # Score-driven greedy allocation: rank `is_catcher_candidate` players
    # by `catcher_alloc_score` (current wOBA + small C_fld component + small
    # age tiebreak), then assign two per level top-down. is_catcher_candidate
    # filters out utility players whose C rating is a defensive fallback —
    # if their best non-C fielding is significantly above their C_fld
    # (gap > C_FLD_GAP_MAX), they're not really a catcher and shouldn't
    # win Step-1 slots on bat alone (else an RF with wOBA .300 and a
    # negative C_fld can claim a Rookie-level catcher slot, get moved
    # off C by Hungarian, and stay stuck at the wrong level). Such
    # players still flow through Step 2 as non-catchers.
    #
    # wOBA-eligibility (`_top`) and age-eligibility (`_bot`) are both
    # enforced strictly — no overmatched bats anywhere in the system. If
    # a level can't fill 2 catcher slots from strict-eligible candidates,
    # it stays short (sign-FA gap, same convention as the bullpen).
    #
    # Score uses CURRENT wOBA, not age-weighted `priority`: priority would
    # let a young high-projection catcher (e.g. Davalillo, age 19, wOBA .246 /
    # wOBAP .337) outrank a more mature catcher with a better current bat
    # (Laverde, age 22, wOBA .261) at AA — but development should put the
    # projection-heavy one at A+ where their bat plays, and the more-ready
    # bat at AA. HP enforcement still ensures every HP catcher starts
    # somewhere; this just decides the WHICH-LEVEL question by how the bat
    # will actually play. The small AGE_WEIGHT bonus mirrors the philosophy
    # already encoded in non-catcher cascade-down via priority weights:
    # older players have less developmental runway, so when scores are
    # close they get the higher level.
    catchers = sorted(
        [p for p in valid_players
         if is_catcher_candidate(p) and id(p) not in rescued_ids],
        key=catcher_alloc_score,
        reverse=True
    )
    cby = {lvl: [] for lvl in LEVELS}
    unassigned_c = list(catchers)

    for i, lvl in enumerate(LEVELS):
        while len(cby[lvl]) < 2:
            picked = None
            for k, c in enumerate(unassigned_c):
                if c['_top'] <= i <= c['_bot']:
                    picked = k
                    break
            if picked is None: break
            cby[lvl].append(unassigned_c.pop(picked))

    # === STEP 2: Non-catchers (plus catchers not picked at Step 1) ===
    # Anyone who failed `is_catcher_candidate` goes through the cascade
    # here — including utility players who have a fallback C rating but
    # whose C glove is significantly below their best other position
    # (the "good-bat utility-C ends up at Rookie ball" pathology guarded
    # against at Step 1).
    # A Step-1 catcher candidate who didn't make any of the 14 catcher
    # slots also falls through here — they may earn a bench spot via
    # their secondary positions rather than being released. is_catcher()
    # still returns True for all of them downstream (so HP swaps pair
    # like-with-like and sheets label them correctly), but they go through
    # the regular cascade as if they were any other non-catcher.
    noncatchers = (
        [p for p in valid_players if not is_catcher_candidate(p)]
        + list(unassigned_c)
        + rescued_catchers   # primary-C bat-bypass — see CATCHER_RESCUE_* above
    )
    # Sort each level's pool with that level's priority blend (MLB drops
    # projection, others use flat 70/30) AND a `_bot` cascadability
    # flag. Splits the pool into two groups: stuck (cannot cascade
    # below this level, `_bot == lvl_idx`) and cascadable (`_bot > lvl_idx`).
    # Pop takes the worst CASCADABLE player first; stuck players are
    # protected at the front of the queue and only get popped (to
    # overflow) when every cascadable has already been moved.
    #
    # See R-11 design notes: this is a tighter version of R-09. R-09
    # ordered cascade victims by mobility-distance, which over-
    # punished the MOST-mobile players (typically high-quality young
    # prospects with `_bot=R(DLR)`) — they got popped first because
    # they had "somewhere to go" even when their priority was better
    # than less-mobile players who could ALSO cascade. R-11 just asks
    # "can you cascade or not", then ranks by priority within each
    # group so the WORST cascadable player goes first.
    nc_by = {lvl: [] for lvl in LEVELS}
    for p in noncatchers:
        nc_by[LEVELS[p['_top']]].append(p)

    _MLB_IDX = LEVELS.index('MLB')

    def _cascade_sort_key_factory(lvl_idx, lvl_name):
        # MLB tenure quality gate (R-24): for 3-4 year vets at MLB, the
        # protection is conditional on their current WAR being within
        # MLB_TENURE_QUALITY_GATE_WAR of the best truly-cascadable
        # player at this level. "Truly cascadable" = yrs_MLB <
        # MLB_TENURE_PROTECTED_YRS (definitely not tenure-protected).
        # We compute the baseline ONCE per level here so each player's
        # sort key gets the same reference.
        baseline_war = None
        if lvl_idx == _MLB_IDX:
            young = [p for p in nc_by[lvl_name]
                     if (p.get('yrs_MLB') or 0)
                     < getattr(config, 'MLB_TENURE_PROTECTED_YRS', 3)]
            if young:
                baseline_war = max((p.get('best_adj') or 0) for p in young)

        def _key(p):
            # ASC sort: stuck (_bot == lvl_idx, can't cascade) first,
            # cascadable (_bot > lvl_idx) last. Within each group,
            # ordered by priority so position -1 = cascadable + WORST.
            cascadable = p['_bot'] > lvl_idx
            # MLB tenure protection — two-tier (R-24):
            #   5+ years -> always protected (anchor vet)
            #   3-4 years -> protected only if best_adj within
            #                MLB_TENURE_QUALITY_GATE_WAR of the
            #                org's best young cascadable hitter at MLB
            if (lvl_idx == _MLB_IDX
                    and is_mlb_tenure_protected(p, baseline_war, 'best_adj')):
                cascadable = False
            return (cascadable, -priority(p, lvl_name))
        return _key

    for lvl in LEVELS:
        nc_by[lvl].sort(key=_cascade_sort_key_factory(LEVELS.index(lvl), lvl))

    nc_slots = {lvl: roster_sizes[lvl] - len(cby[lvl]) for lvl in LEVELS}

    # Cascade down
    for i, lvl in enumerate(LEVELS):
        target = nc_slots[lvl]
        while len(nc_by[lvl]) > target:
            cascaded = nc_by[lvl].pop()
            next_idx = i + 1
            if next_idx <= cascaded['_bot'] and next_idx < len(LEVELS):
                nxt = LEVELS[next_idx]
                nc_by[nxt].append(cascaded)
                nc_by[nxt].sort(key=_cascade_sort_key_factory(next_idx, nxt))
            else:
                overflow.append(cascaded)

    # Pull up
    for i, lvl in enumerate(LEVELS):
        target = nc_slots[lvl]
        while len(nc_by[lvl]) < target:
            best, best_j = None, None
            for j in range(i + 1, len(LEVELS)):
                for p in nc_by[LEVELS[j]]:
                    if p['age'] > MAX_AGE[lvl]:
                        continue
                    # Don't pull a player above their wOBA-eligible ceiling.
                    # Without this an empty MLB/AAA slot can suck up a sub-threshold
                    # filler and (worse) drag an HP into a level where they'll bench.
                    if p['_top'] > i:
                        continue
                    if best is None or priority(p, lvl) > priority(best, lvl):
                        best, best_j = p, j
            if best is None: break
            nc_by[LEVELS[best_j]].remove(best)
            nc_by[lvl].append(best)
            nc_by[lvl].sort(key=_cascade_sort_key_factory(i, lvl))
    
    if len(nc_by['R(DLR)']) > nc_slots['R(DLR)']:
        overflow.extend(nc_by['R(DLR)'][nc_slots['R(DLR)']:])
        nc_by['R(DLR)'] = nc_by['R(DLR)'][:nc_slots['R(DLR)']]
    
    for lvl in LEVELS:
        by_level[lvl] = cby[lvl] + nc_by[lvl]

    # === HARD BLOCK: HPs are never placed on the MLB roster ===
    # Prospects develop in the minors regardless of projection. Any HP
    # who ended up at MLB after the cascade (because their `_top` was
    # MLB and Hungarian routed them there) is pushed down to exactly
    # AAA — the level just below MLB. `_bot` index >= HP_MIN_LEVEL_INDEX
    # means the HP can play AAA, so we put them there. If `_bot` is
    # somehow lower than HP_MIN_LEVEL_INDEX (very rare — would need
    # significant MLB service which an HP usually doesn't have), the
    # HP is left at MLB.
    # Controlled by HP_MIN_LEVEL_INDEX in config.py (default 1 = AAA).
    if HP_MIN_LEVEL_INDEX > 0:
        mlb_hps = [p for p in by_level[LEVELS[0]] if is_high_potential(p)]
        for hp in mlb_hps:
            target_idx = HP_MIN_LEVEL_INDEX   # destination = AAA (default)
            bot = hp.get('_bot')
            if bot is not None and bot < target_idx:
                continue  # _bot blocks AAA — leave at MLB
            target_lvl = LEVELS[target_idx]
            by_level[LEVELS[0]].remove(hp)
            by_level[target_lvl].append(hp)

    # === STEP 3: High-potential starter enforcement ===
    # If HP benched at level X: swap with non-HP at X+1. If can't (age cap
    # or service-floor blocks demotion), set `_force_start = X` so the HP
    # stays put and is treated as a starter at X by downstream passes.
    # At rookie ball: fill_starters auto-prioritizes HPs via the +10 dev bonus.
    #
    # `_force_start` semantics (set here, honoured by):
    #   - fill_starters: force_start == lvl gives the player a +10 Hungarian
    #     bonus at lvl, virtually guaranteeing a starting slot.
    #   - _rebalance_over_target: excludes force_start players from the
    #     "poppable" set so they don't get cascaded back down.
    #   - Step-4 candidate filter: excludes force_start players from being
    #     promoted as utility candidates (they're already locked at a level).
    # The flag is reset by `p.pop('_force_start', None)` at the top of main()
    # so it doesn't leak between roster builds on the same player dict.
    def _enforce_hp_starters():
        for _iter in range(20):
            changed = False
            for i, lvl in enumerate(LEVELS):
                # R / R(DLR) skip — those levels apply the +10 HP bonus inside
                # fill_starters so HPs always start there by construction. MLB
                # IS subject to HP cascade: if an HP gets pulled up by Step-2
                # pull-up but Hungarian benches them, demote back to AAA where
                # they can develop as a starter.
                if lvl in ('R', 'R(DLR)'):
                    continue
                starters, bench = fill_starters(by_level[lvl], lvl)
                hp_benched = [p for p in bench if is_high_potential(p)]
                # Platoon-overmatch signal: an HP standard starter who's
                # DROPPED from the vs-RHP lineup. RHB face righties ~3x as
                # often as lefties so vs-RHP is the dominant matchup signal;
                # an HP who can't earn a vs-RHP slot is surviving on
                # projection alone and should cascade down.
                sR = fill_starters_split(by_level[lvl], lvl, 'R')
                sR_starter_ids = {id(p) for p in sR.values() if p}
                hp_overmatched = [
                    p for p in starters.values()
                    if p and is_high_potential(p)
                    and id(p) not in sR_starter_ids
                ]
                # DH/1B-development signal: an HP starting at 1B or DH
                # who HAS a playable defensive position elsewhere
                # (best non-1B/DH `<pos>_fld` >= -0.5 WAR) should
                # cascade down to develop that position rather than
                # locking into bat-only at this level. Truly DH-only
                # prospects (Frank Thomas / Schwarber-types) stay put
                # via the is_very_poor_fielder exception.
                hp_at_dh_1b = [
                    p for pos, p in starters.items()
                    if p and is_high_potential(p)
                    and pos in ('1B', 'DH')
                    and not is_very_poor_fielder(p)
                ]
                hp_to_cascade = (
                    hp_benched
                    + [p for p in hp_overmatched if p not in hp_benched]
                    + [p for p in hp_at_dh_1b
                       if p not in hp_benched and p not in hp_overmatched]
                )
                if not hp_to_cascade:
                    continue

                for hp in hp_to_cascade:
                    cascaded = False
                    if i + 1 < len(LEVELS):
                        next_lvl = LEVELS[i + 1]
                        # Need both age-eligibility AND service/DSL floor (_bot)
                        # to allow demotion to next_lvl. Without the _bot guard
                        # an HP whose service has burned through R/A could be
                        # cascaded to R anyway, then any swap_target gets
                        # promoted past their _top.
                        if hp['age'] <= MAX_AGE[next_lvl] and (i + 1) <= hp['_bot']:
                            hp_is_c = is_catcher(hp)
                            non_hp_in_next = [p for p in by_level[next_lvl]
                                              if not is_high_potential(p)
                                              and p['age'] <= MAX_AGE[lvl]
                                              and p['_top'] <= i
                                              and is_catcher(p) == hp_is_c]
                            # Swap with target only if HP's projection
                            # advantage at least matches the target's
                            # current-bat advantage; otherwise demote
                            # without swap (HP just moves down a level).
                            swap_target = None
                            if non_hp_in_next:
                                candidate = max(non_hp_in_next, key=lambda p: priority(p))
                                current_loss = (candidate.get('wOBA') or 0) - (hp.get('wOBA') or 0)
                                potential_gain = (hp.get('wOBAP') or 0) - (candidate.get('wOBAP') or 0)
                                if potential_gain >= current_loss:
                                    swap_target = candidate
                            by_level[lvl].remove(hp)
                            by_level[next_lvl].append(hp)
                            if swap_target is not None:
                                by_level[next_lvl].remove(swap_target)
                                by_level[lvl].append(swap_target)
                            changed = True
                            cascaded = True
                    if not cascaded:
                        # Defence-in-depth: HPs never `_force_start` at MLB.
                        # The pre-Step-3 hard block above already moves any
                        # MLB-cascade HP down; this guard catches any HP
                        # that snuck back to MLB via pull-up logic later.
                        # Move to AAA (HP_MIN_LEVEL_INDEX), unless `_bot`
                        # blocks AAA in which case leave at MLB.
                        if lvl == LEVELS[0] and HP_MIN_LEVEL_INDEX > 0:
                            target_idx = HP_MIN_LEVEL_INDEX
                            bot = hp.get('_bot')
                            if bot is None or bot >= target_idx:
                                target_lvl = LEVELS[target_idx]
                                by_level[lvl].remove(hp)
                                by_level[target_lvl].append(hp)
                                hp['_force_start'] = target_lvl
                                continue
                        hp['_force_start'] = lvl
            if not changed:
                break

    def _rebalance_over_target():
        # Demote-without-swap from HP enforcement can leave a level over
        # ROSTER_SIZES; pop the lowest-priority non-HP non-force-start to
        # the next level (or overflow if their _bot doesn't allow).
        for i, lvl in enumerate(LEVELS):
            while len(by_level[lvl]) > roster_sizes[lvl]:
                poppable = [p for p in by_level[lvl]
                            if not is_high_potential(p)
                            and p.get('_force_start') != lvl]
                if not poppable:
                    break
                poppable.sort(key=lambda p: priority(p, lvl))
                cascaded = poppable[0]
                by_level[lvl].remove(cascaded)
                next_idx = i + 1
                if next_idx <= cascaded['_bot'] and next_idx < len(LEVELS):
                    by_level[LEVELS[next_idx]].append(cascaded)
                else:
                    overflow.append(cascaded)

    _enforce_hp_starters()

    # === STEP 3.5: Re-balance after HP cascade ===
    # HP demote-alone (no swap target) grows the destination level. With
    # service-time constraints there are often no eligible swap targets,
    # so AA / A+ etc. can balloon over their ROSTER_SIZES cap. Walk
    # top-down again and pop the lowest-priority non-HP, non-force-start
    # player from any over-target level — see _rebalance_over_target above.
    _rebalance_over_target()

    # === STEP 3.6: Three-pass pull-up + push-down ===
    # The Step-2 cascade pushes worst-priority players DOWN through the
    # levels until they hit overflow, but it doesn't reach back UP to
    # fill gaps that emerge later (HP demotions, service-locked players
    # that couldn't fit lower, etc.).
    #
    # PASS 1 (strict): any level under ROSTER_SIZES pulls the
    #   highest-priority overflow body whose `_top <= i <= _bot`. No
    #   stretch above the player's wOBA-qualified ceiling.
    #
    # PASS 2 (+1 stretch): if PASS 1 left a level still under target,
    #   allow non-HP non-catcher players whose `_top` is exactly ONE
    #   level below the under-filled level (`_top == i + 1`) to fill
    #   the gap. Mirrors the pitcher `_pull_up` Pass 2 stretch.
    #
    # PASS 3 (release-pool push-down): for any level still under target,
    #   pull ANY overflow body whose `_bot >= i` — regardless of `_top`.
    #   Catchers are eligible (Hungarian can route them to any
    #   position they `field`-qualify for). Only the OOTP hard rule
    #   (`_bot`: age + service + DSL nation) is respected. This is what
    #   the user calls "push down using release pool players to ensure
    #   all rosters fill" — release-pool players land wherever a slot
    #   exists, even if their wOBA is well below the level's nominal
    #   threshold. An empty roster slot is worse for org-depth display
    #   than an over-leveled body.
    #
    # PASS 1 + PASS 2 also pull from already-placed lower levels (not
    # just overflow), since most orgs have thin overflow pools and the
    # candidate is usually placed at R / R(DLR) by the cascade. PASS 3
    # only pulls from overflow — we never demote a placed player to
    # fill a gap (that would just shift the gap downward).
    def _pullup_eligible(p, i, allow_stretch, allow_push_down=False):
        if p.get('_bot') is None or i > p['_bot']:
            return False
        if p.get('_force_start'):
            return False
        # Hard block: HPs never pulled up above HP_MIN_LEVEL_INDEX.
        # Defaults to AAA (index 1) so HPs are blocked from MLB
        # promotion via any of the three pull-up passes.
        if HP_MIN_LEVEL_INDEX > 0 and i < HP_MIN_LEVEL_INDEX and is_high_potential(p):
            return False
        # Catchers are excluded from PASS 1/2 because Step 1 already
        # optimised catcher allocation; allowing them here would
        # double-count. PASS 3 (release-pool push-down) lets catchers
        # in — by then we're filling otherwise-empty slots and the
        # Hungarian can route a catcher to any non-C position they
        # `field`-qualify for.
        if is_catcher(p) and not allow_push_down:
            return False
        if allow_push_down:
            return True   # _bot is the only constraint
        top = p.get('_top')
        if top is None:
            return False
        if top <= i:
            return True   # strict eligibility
        if allow_stretch and top == i + 1 and not is_high_potential(p):
            return True   # non-HP +1 stretch
        return False

    def _try_fill_level(i, lvl, allow_stretch, allow_push_down=False):
        """Fill `lvl` from overflow first, then from already-placed
        lower levels (PASSES 1/2 only — PASS 3 stays in overflow).
        Returns when level is at target or no more eligible candidates."""
        target = roster_sizes[lvl]
        # Pass A: from overflow
        while len(by_level[lvl]) < target:
            candidates = [
                p for p in overflow
                if _pullup_eligible(p, i, allow_stretch, allow_push_down)
            ]
            if not candidates:
                break
            best = max(candidates, key=priority)
            overflow.remove(best)
            by_level[lvl].append(best)
        if allow_push_down:
            return  # don't pull placed players for push-down
        # Pass B: from lower placed levels
        while len(by_level[lvl]) < target:
            best, best_lvl = None, None
            for j in range(i + 1, len(LEVELS)):
                lower = LEVELS[j]
                for p in by_level[lower]:
                    if not _pullup_eligible(p, i, allow_stretch):
                        continue
                    if best is None or priority(p) > priority(best):
                        best, best_lvl = p, lower
            if best is None:
                break
            by_level[best_lvl].remove(best)
            by_level[lvl].append(best)

    # PASS 1: strict (no stretch).
    for i, lvl in enumerate(LEVELS):
        _try_fill_level(i, lvl, allow_stretch=False)
    # PASS 2: +1 stretch.
    for i, lvl in enumerate(LEVELS):
        _try_fill_level(i, lvl, allow_stretch=True)
    # PASS 3: release-pool push-down (overflow only, _bot only).
    for i, lvl in enumerate(LEVELS):
        _try_fill_level(i, lvl, allow_stretch=True, allow_push_down=True)

    # === STEP 4: Bench-role refinement ===
    # The priority cascade picks rosters by bat alone, so a level can end
    # up with a "Utility IF" who only plays one IF position (e.g. Meckler
    # at MLB with 3B as his sole IF) while a true super-utility (Jarvis:
    # SS / 2B / 3B) sits at AAA. Walk top-down and, for each utility
    # role, swap up if the next level has a strictly more flexible
    # candidate eligible at this level. We only refine the multi-position
    # roles (Util IF / Util OF) — Backup C is already optimised in Step 1
    # and Best bat / starters are bat-first picks the cascade gets right.
    # Refinement scoring must match classify_bench's of_score / if_score —
    # otherwise refinement only swaps on raw position-count and ignores
    # glove+bat quality, missing cases where a same-count candidate has
    # genuinely better skill. 60/40 fld/bat weighting in WAR units, same
    # as classify_bench.
    def _util_if_cap(p):
        fld_vals = [p.get(f'{pos}_fld') for pos in IF_POSITIONS]
        valid = [v for v in fld_vals if v is not None]
        if not valid:
            return (0, 0.0)
        fld_sum = sum(valid)
        bat_war = p.get('war_hitting') or 0
        return (len(valid), 0.6 * fld_sum + 0.4 * bat_war)

    def _util_of_cap(p):
        fld_vals = {pos: p.get(f'{pos}_fld') for pos in OF_POSITIONS}
        valid_pos = [pos for pos, v in fld_vals.items() if v is not None]
        if not valid_pos:
            return (0, 0.0)
        cf_bonus = 1 if 'CF' in valid_pos else 0
        fld_sum = sum(fld_vals[pos] for pos in valid_pos)
        bat_war = p.get('war_hitting') or 0
        return (
            len(valid_pos) + cf_bonus,
            0.6 * fld_sum + 0.4 * bat_war,
        )

    def _make_best_bat_cap(level):
        # Pure-bat refinement role: count component is always 0 (Best bat
        # has no multi-position prerequisite), score is the same level-
        # aware priority blend classify_bench uses (current-only at MLB,
        # 70/30 elsewhere). The (0, …) shape stays compatible with the
        # (-1, -inf) "empty slot" sentinel used elsewhere in this loop.
        def cap(p):
            return (0, priority(p, level))
        return cap

    # Backup C cap is a (0, alloc_score) tuple so it slots into the same
    # comparison machinery as the other named-role cap functions, which
    # all return (count, score). The 0 placeholder keeps any real catcher
    # ahead of the (-1, -inf) "empty role" sentinel.
    def _backup_c_cap(p):
        return (0, catcher_alloc_score(p))

    for _iter in range(20):
        changed = False
        for i, lvl in enumerate(LEVELS):
            if i + 1 >= len(LEVELS):
                continue
            next_lvl = LEVELS[i + 1]
            UTIL_ROLE_FNS = {
                'Backup C':   _backup_c_cap,
                'Utility IF': _util_if_cap,
                'Utility OF': _util_of_cap,
                'Best bat':   _make_best_bat_cap(lvl),
            }
            _, bench = fill_starters(by_level[lvl], lvl)
            bench_roles = classify_bench(bench, level=lvl)
            named_role_players = {p['name'] for _, p in bench_roles[:4] if p}
            for role, current in bench_roles[:4]:
                cap_fn = UTIL_ROLE_FNS.get(role)
                if cap_fn is None:
                    continue
                # Sentinel for "role currently empty" — any candidate beats
                # an empty slot. cap_fn returns a 2-tuple (count, score)
                # where score is signed; (-1, -inf) lets the smallest
                # legitimate score still win.
                current_cap = cap_fn(current) if current else (-1, float('-inf'))
                # Candidate at next_lvl must be eligible upstairs by wOBA and
                # age, not an HP (HPs need to start somewhere — even at MLB
                # the development cost of benching an HP outweighs the
                # marginal upgrade), and the right SHAPE for this role:
                # utility roles want non-catchers; Backup C wants a real
                # catcher candidate. Without the role-specific shape filter,
                # a Util IF refinement could pull up a fallback-C utility
                # bat (Step-1 already handled real catchers via alloc_score),
                # and a Backup C refinement would consider non-catchers.
                # Candidate pool: next-level roster + overflow. Including
                # overflow lets a great-glove player who got cascaded out
                # on bat still claim the role where their profile actually
                # matters (e.g. Robinson — CF_fld +5.35 — cascaded out of
                # AZ AAA on a weak bat; or Heineman — alloc_score 0.44 —
                # rescued out of TOR catcher allocation but bat-cascaded
                # out of MLB and is still the right MLB Backup C).
                is_backup_c = (role == 'Backup C')
                def _is_eligible_candidate(p):
                    if is_backup_c:
                        if not is_catcher_candidate(p):
                            return False
                    else:
                        if is_catcher(p):
                            return False
                    return (
                        p['_top'] <= i
                        and i <= p['_bot']
                        and p['age'] <= MAX_AGE[lvl]
                        and not is_high_potential(p)
                        and p.get('_force_start') != next_lvl
                        and (current is None or p['name'] != current['name'])
                    )
                candidates_below = [p for p in by_level[next_lvl] if _is_eligible_candidate(p)]
                candidates_overflow = [p for p in overflow if _is_eligible_candidate(p)]
                candidates = candidates_below + candidates_overflow
                if not candidates:
                    continue
                best_alt = max(candidates, key=lambda p: (cap_fn(p), priority(p)))
                if cap_fn(best_alt) <= current_cap:
                    continue
                from_overflow = best_alt in candidates_overflow

                # Pull-without-displace when the upper level has a vacancy —
                # no one needs to drop, just promote.
                if len(by_level[lvl]) < roster_sizes[lvl]:
                    if from_overflow:
                        overflow.remove(best_alt)
                    else:
                        by_level[next_lvl].remove(best_alt)
                    by_level[lvl].append(best_alt)
                    bench = bench + [best_alt]
                    named_role_players = {p['name'] for _, p in classify_bench(bench, level=lvl)[:4] if p}
                    changed = True
                    continue

                # Pick the displacement target by simulating the post-promotion
                # bench, not by blindly demoting `current`. The role-holder we
                # are upgrading might be the highest-priority bat on the bench
                # (e.g. a rescued primary-C with a real MLB bat being upgraded
                # off Util OF by a glove specialist) — demoting them throws
                # away a contributor while keeping a weaker bat. After fitting
                # the candidate in, prefer to drop a non-HP bench player who
                # holds NO named role in the post-promotion lineup; the named-
                # role holders (Backup C, Utility IF, Utility OF, Best bat in
                # the new bench) are protected because each role does real
                # work. If everyone holds a named role, fall back to `current`
                # (the prior behavior — demote the role-holder we're upgrading)
                # so we don't strip a Util-IF specialist just to seat a Util-OF
                # specialist.
                trial_pool = by_level[lvl] + [best_alt]
                _, trial_bench = fill_starters(trial_pool, lvl)
                trial_named = {p['name'] for _, p in classify_bench(trial_bench, level=lvl)[:4] if p}
                trial_unnamed = [p for p in trial_bench
                                 if p['name'] != best_alt['name']
                                 and not is_high_potential(p)
                                 and p['name'] not in trial_named]
                if trial_unnamed:
                    displace = min(trial_unnamed, key=lambda p: priority(p, lvl))
                elif current is not None:
                    displace = current
                else:
                    spare_bench = [p for p in bench if p['name'] not in named_role_players]
                    if not spare_bench:
                        continue
                    displace = min(spare_bench, key=lambda p: priority(p, lvl))
                # Overflow has no age cap; only enforce the next-level age
                # cap if the displaced player would be cascaded down a level.
                # Same for service/DSL floor — sending `displace` to next_lvl
                # is invalid if next_lvl > displace['_bot'] (e.g. a service-
                # exhausted player at A would cascade to R despite being
                # blocked from R/R(DLR)). Use the from_overflow path or skip.
                if not from_overflow:
                    if displace['age'] > MAX_AGE[next_lvl]:
                        continue
                    if (i + 1) > displace['_bot']:
                        # Send to overflow instead of an illegal level.
                        send_to_overflow = True
                    else:
                        send_to_overflow = False
                else:
                    send_to_overflow = False
                # `current` (and `bench_roles`) were computed at the top of
                # this outer pass; an earlier role iteration may already have
                # demoted `current`. If the displacement target is no longer
                # at this level, skip rather than crash — the next outer
                # pass will re-classify with fresh state.
                if not any(p is displace for p in by_level[lvl]):
                    continue
                by_level[lvl].remove(displace)
                if from_overflow:
                    overflow.remove(best_alt)
                    overflow.append(displace)
                elif send_to_overflow:
                    overflow.append(displace)
                    by_level[next_lvl].remove(best_alt)
                else:
                    by_level[next_lvl].remove(best_alt)
                    by_level[next_lvl].append(displace)
                by_level[lvl].append(best_alt)
                # Also keep our local view of the bench in sync so subsequent
                # role iterations within this pass don't double-count slots.
                bench = [p for p in bench if p['name'] != displace['name']] + [best_alt]
                named_role_players = {p['name'] for _, p in classify_bench(bench, level=lvl)[:4] if p}
                changed = True
        if not changed:
            break

    # === Premium-fit pull-up ===
    # Top-down (AAA → A), for each premium position (CF / SS / 2B), make sure
    # the level's starter at that position is the best HP defender available
    # in the system who's eligible at that level. Ranking is by
    # (-_top, _fld, priority) — higher-tier wOBA prospect wins, then better
    # glove, then better bat. This gives "best CF prospect plays at the
    # highest level he qualifies for" while preserving the existing catcher
    # mechanism for C and not touching MLB / R / R(DLR) (MLB plays for
    # current value, not glove-development; R/R(DLR) already prioritise HPs
    # via fill_starters' is_dev bonus).
    #
    # Skip rule: if the incumbent is a NON-HP real defender (`_fld` ≥
    # PREMIUM_FLD_MIN), leave them alone — we don't want to displace a
    # quality non-HP starter (e.g. Pereira at AAA CF) just to seat an HP
    # whose bat is meaningfully worse. HP-vs-HP swaps are allowed when the
    # candidate strictly outranks the incumbent on the score tuple.
    #
    # Demotion: instead of auto-demoting the incumbent (which can drop a
    # contributor two levels for no reason), we re-run the Hungarian and
    # pop the lowest-priority bench player at this level. The incumbent
    # likely shifts to a corner (Hungarian assigns by `_adj` + natural
    # bonus); somebody less essential drops to the candidate's old level.
    PREMIUM_FIT_PROMO_LEVELS = ('AAA', 'AA', 'A+', 'A')

    def _premium_candidate_score(p, pos):
        # Higher = better. -_top so higher-level wOBA-eligibility wins;
        # _fld so better glove wins next; priority for bat tiebreak.
        return (-p['_top'], p.get(f'{pos}_fld') or 0.0, priority(p))

    for _iter in range(20):
        changed = False
        for lvl in PREMIUM_FIT_PROMO_LEVELS:
            i = LEVELS.index(lvl)
            starters, _ = fill_starters(by_level[lvl], lvl)
            for pos in HP_PREMIUM_FIT_POSITIONS:
                cur = starters.get(pos)
                cur_fld = (cur.get(f'{pos}_fld') if cur else None) or float('-inf')
                # Don't displace a non-HP real defender — they're quality
                # starters whose bat carries the slot.
                if cur is not None and not is_high_potential(cur) and cur_fld >= PREMIUM_FLD_MIN:
                    continue
                # Sub-floor incumbents (or empty slots) are beatable by ANY
                # elite-glove HP candidate, regardless of _top tier. Without
                # this, a high-_top sub-floor defender (e.g. Montgomery at
                # AA CF, _top=MLB but CF_fld 1.29) would block a real
                # defender (Zavala, _top=AAA, CF_fld 2.36) on tier. Real-HP
                # incumbents (cur_fld ≥ floor) get the full (-_top, _fld,
                # priority) comparison so a higher-tier prospect with elite
                # glove keeps their slot vs a lower-tier one with marginally
                # better glove.
                if cur is None or cur_fld < PREMIUM_FLD_MIN:
                    cur_score = (float('-inf'),) * 3
                else:
                    cur_score = _premium_candidate_score(cur, pos)

                # Best HP candidate at a lower level with elite glove here
                best, best_j = None, None
                best_score = (float('-inf'),) * 3
                for j in range(i + 1, len(LEVELS)):
                    for p in by_level[LEVELS[j]]:
                        if not is_high_potential(p):
                            continue
                        fld = p.get(f'{pos}_fld')
                        if fld is None or fld < PREMIUM_FLD_MIN:
                            continue
                        if p['_top'] > i:
                            continue  # wOBA doesn't qualify upstairs
                        if i > p['_bot']:
                            continue  # service/age floor blocks upstairs
                        score = _premium_candidate_score(p, pos)
                        if score > best_score:
                            best, best_j, best_score = p, j, score
                if best is None or best_score <= cur_score:
                    continue

                # vs-RHP overmatch guard: simulate the post-promotion pool
                # and run both Hungarians. If the candidate would land in
                # the standard lineup but get dropped from the vs-RHP
                # lineup at this level, they're platoon-overmatched here —
                # exactly the signal HP enforcement uses to demote, so
                # promoting them just sets up oscillation. Use the
                # detection-mode (un-pinned) split Hungarian; the pin is
                # for display, not detection.
                sim_pool = by_level[lvl] + [best]
                sim_starters, _ = fill_starters(sim_pool, lvl)
                sim_std_names = {p['name'] for p in sim_starters.values() if p}
                if best['name'] in sim_std_names:
                    sim_sR = fill_starters_split(sim_pool, lvl, 'R')
                    sim_sR_names = {p['name'] for p in sim_sR.values() if p}
                    if best['name'] not in sim_sR_names:
                        continue  # would be vs-RHP overmatched at this level

                # Move the candidate up.
                by_level[LEVELS[best_j]].remove(best)
                by_level[lvl].append(best)

                # Identify someone at this level to drop. Re-run the
                # Hungarian to know who's currently bench post-promotion;
                # exclude HPs (don't fight HP enforcement) and named bench
                # roles (Backup C / Util IF / Util OF / Best bat — those
                # have already earned their slot). Fall back to any non-HP
                # bench player if no spare exists; last resort include HPs.
                _, new_bench = fill_starters(by_level[lvl], lvl)
                named = {p['name'] for _, p in classify_bench(new_bench)[:4] if p}
                pool = [p for p in new_bench if not is_high_potential(p) and p['name'] not in named]
                if not pool:
                    pool = [p for p in new_bench if not is_high_potential(p)]
                if not pool:
                    pool = list(new_bench)
                if not pool:
                    changed = True  # over capacity by one; loop continues
                    continue
                demoted = min(pool, key=priority)

                # Land at the candidate's old level if service floor allows;
                # otherwise the first level deeper than `lvl` they can play;
                # otherwise overflow.
                target_idx = best_j
                if target_idx > demoted['_bot']:
                    target_idx = None
                    for k in range(i + 1, len(LEVELS)):
                        if k <= demoted['_bot']:
                            target_idx = k
                            break
                by_level[lvl].remove(demoted)
                if target_idx is None:
                    overflow.append(demoted)
                else:
                    by_level[LEVELS[target_idx]].append(demoted)
                changed = True
        if not changed:
            break

    # === Step 4.6: Re-run HP enforcement ===
    # Bench refinement and the premium-fit pull-up can move players around
    # in ways that bench an HP at a level (e.g. a displaced MLB player
    # joining AAA and beating an HP for their slot in the Hungarian). The
    # Step-3 HP enforcement that ran earlier wouldn't have caught this.
    # Re-run it now, then rebalance any over-cap levels its demotions
    # produced.
    _enforce_hp_starters()
    _rebalance_over_target()

    # NOTE: Step 4.7 (two-way pin) was retired in R-10. Two-way pitchers
    # (position == 1 with meaningful potential bat) no longer appear in
    # the hitter cascade at all — they're excluded by the hitter export
    # filter (exporter.py) and take a roster slot ONLY on the pitcher
    # side. Their bat is informational ("can also play 1B / DH") rather
    # than competing with regular hitters for bench slots. The previous
    # pin was over-promoting prospects whose pitcher pwOBA only
    # marginally cleared the MLB cap, displacing competitively-better
    # MLB non-HP arms (e.g. BOS's Tolle pinned to MLB SP over Bello).

    # Final Hungarian (overall + platoon variants on the same roster).
    # Platoon variants pin standard starters to their standard position, so
    # an everyday 3B doesn't get shuffled to CF in vs-LHP just because his
    # platoon bat fits awkwardly elsewhere — he plays 3B vs LHP or sits.
    rosters = {}
    for lvl in LEVELS:
        starters, bench = fill_starters(by_level[lvl], lvl)
        sR = fill_starters_split(by_level[lvl], lvl, 'R', standard_starters=starters)
        sL = fill_starters_split(by_level[lvl], lvl, 'L', standard_starters=starters)
        rosters[lvl] = {
            'starters': starters,
            'starters_vsR': sR,
            'starters_vsL': sL,
            'backups_vsR': fill_backups(by_level[lvl], sR, 'R'),
            'backups_vsL': fill_backups(by_level[lvl], sL, 'L'),
            'bench': bench,
            'bench_roles': classify_bench(bench, level=lvl),
            'all': by_level[lvl],
            'target': roster_sizes[lvl],
        }

    # Split R(DLR) into n_dsl sub-teams (best, …, rest) by hitter priority
    # blend so each DSL affiliate displays as its own roster. Each gets an
    # independent Hungarian over its 15-player slice. No-op when n_dsl == 1.
    #
    # Sub-team keys are 'R(DLR)1', 'R(DLR)2', … — when downstream code
    # (e.g. test invariants, build_excel) needs the underlying LEVELS index
    # for one of these keys it must collapse the suffix back to 'R(DLR)'.
    # See `_level_index` in tests/test_roster_invariants.py for the canonical
    # remap; the same convention is used in build_pitcher_system.
    n_dsl = _count_dsl_teams(org)
    if n_dsl >= 2 and 'R(DLR)' in rosters:
        full_all = rosters.pop('R(DLR)')['all']
        # priority(p) is the cascade-ordering key for hitters — HIGHER is
        # better (age-weighted wOBA blend). Sort descending so chunk 1 is
        # the best chunk_size.
        ranked = sorted(full_all, key=priority, reverse=True)
        # Pull from ROSTER_SIZES so the per-DSL-team chunk size tracks
        # the configured per-level cap (16 since 2026-05; was hardcoded
        # 15 previously and would silently drop the 16th-best player
        # at every R(DLR) sub-team).
        chunk_size = ROSTER_SIZES['R(DLR)']
        for k in range(n_dsl):
            chunk = ranked[k*chunk_size:(k+1)*chunk_size]
            starters, bench = fill_starters(chunk, 'R(DLR)')
            sR = fill_starters_split(chunk, 'R(DLR)', 'R', standard_starters=starters)
            sL = fill_starters_split(chunk, 'R(DLR)', 'L', standard_starters=starters)
            rosters[f'R(DLR){k+1}'] = {
                'starters': starters,
                'starters_vsR': sR,
                'starters_vsL': sL,
                'backups_vsR': fill_backups(chunk, sR, 'R'),
                'backups_vsL': fill_backups(chunk, sL, 'L'),
                'bench': bench,
                'bench_roles': classify_bench(bench, level='R(DLR)'),
                'all': chunk,
                'target': chunk_size,
            }

    return rosters, overflow, flagged_players

if __name__ == '__main__':
    rosters, overflow, flagged = main()
    for lvl in rosters.keys():
        r = rosters[lvl]
        print(f"\n=== {lvl} ({len(r['all'])}) ===")
        for pos in POSITIONS:
            p = r['starters'].get(pos)
            if p:
                woba = p.get('wOBA') or 0
                pa = p.get(f'{pos}_adj') or 0
                print(f"  {pos}: {p['name']:25} age={p['age']:2} wOBA={woba:.3f} {pos}_adj={pa:5.2f} bestP={p['bestP']:5.1f}")
            else:
                print(f"  {pos}: -- empty --")
        print(f"  Bench:")
        for p in r['bench']:
            print(f"    {p['name']:25} age={p['age']:2} wOBA={p.get('wOBA') or 0:.3f} pos={p['pos_adj']}")
    print(f"\nOverflow/release: {len(overflow)}")
    print(f"Flagged (unavailable): {len(flagged)}")
