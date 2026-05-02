"""LAA hitter assignment v3 - wOBA-driven with overflow cascade."""
import json

POSITIONS = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH']
LEVELS = ['MLB', 'AAA', 'AA', 'A+', 'A', 'R', 'R(DLR)']
ROSTER_SIZES = {'MLB': 13, 'AAA': 13, 'AA': 13, 'A+': 13, 'A': 13, 'R': 15, 'R(DLR)': 15}

WOBA_MIN = {
    'MLB': 0.280,
    'AAA': 0.250,
    'AA': 0.220,
    'A+': 0.210,
    'A': 0.200,
    'R': 0.165,
    'R(DLR)': -1.0,
}

MAX_AGE = {
    'R(DLR)': 21, 'R': 22, 'A': 23, 'A+': 24,
    'AA': 99, 'AAA': 99, 'MLB': 99,
}

# Weight applied to C_fld (fielding-only WAR at C) in the catcher allocation
# score. Score = wOBA + C_FLD_WEIGHT * C_fld + AGE_WEIGHT * min(age, AGE_CAP).
# C_fld typically ranges from about -2 (poor) to +5 (elite framer); wOBA sits
# in the .15-.40 band. We use C_fld rather than C_adj on purpose: C_adj
# already folds the bat into the score, so combining it with the bat term
# would double-count — and a great-glove / weak-bat backup (e.g. Flores:
# C_fld +3.67, C_adj -0.33) would be wrongly demoted on his own offence.
# C_fld isolates the defensive component. At 0.05 the defensive contribution
# maxes out around ±0.25, comparable to a .025 wOBA swing.
C_FLD_WEIGHT = 0.05
# Older catchers preferred for higher levels (less developmental runway —
# their bat needs to play where it plays now). Small enough to act as a
# tiebreak for catchers within ~.012 of each other rather than overriding
# real talent gaps. Capped at AGE_CAP so a 35-year-old journeyman doesn't
# get an unbounded boost over a 28-year-old.
AGE_WEIGHT = 0.002
AGE_CAP = 30

# Premium-position bat relaxation: the wOBA threshold for a level is lowered
# by this many points when the player's primary position is C, SS, or CF.
# These three are the up-the-middle defensive premiums in real baseball — a
# defensive-first profile at any of them plays at a level slightly above
# where his pure bat would qualify, because the glove value at scarce
# positions offsets a borderline bat. Kept small (.005 = ~5 wOBA points,
# roughly +0.25 WAR) so a TRULY overmatched bat still can't sneak up — this
# admits borderline cases (Rogers .27966 vs MLB .280, Flores .24999 vs AAA
# .250) without re-creating the broad relaxation we removed.
PREMIUM_WOBA_RELAX = {
    'C':  0.005,
    'SS': 0.005,
    'CF': 0.005,
}

HITTERS_JSON = 'outputs/hitters.json'
INJURED_FILE = 'injured.txt'

def load_team(org=None):
    """Load hitters for a single org. Defaults to config.team_managed."""
    if org is None:
        from config import team_managed
        org = team_managed
    d = json.load(open(HITTERS_JSON))
    return [r for r in d['rows'] if r['org'] == org]

# Back-compat alias for any code still calling load_laa().
def load_laa():
    return load_team('LAA')

def _load_injured_names():
    """Return the set of currently-injured player names. Sources:
    1. OOTP `players.csv` `injury_is_injured == 1` (auto-detected).
    2. `injured.txt` (one name per line, `#` comments) as a manual override
       for cases where you want to mark someone unavailable for a non-injury
       reason — additive to the OOTP list.
    Both sources are optional; missing files just mean no one is flagged."""
    names = set()
    # Auto: OOTP CSV. Reference config.filepath at call time so the
    # Streamlit uploader's monkey-patched temp dir is honoured.
    # Day-to-day (DTD) injuries — flagged by `injury_dtd_injury == 1` —
    # are NOT exclusions. Those guys are still playing; OOTP just rests
    # them a game or two. Only `injury_is_injured == 1` AND no DTD flag
    # counts as a proper IL stint that pulls them out of placement.
    try:
        import config
        import csv
        with open(config.filepath / 'players.csv', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row.get('injury_is_injured') != '1':
                    continue
                if row.get('injury_dtd_injury') == '1':
                    continue
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
    return names

def is_catcher(p):
    return p.get('C_adj') is not None

def catcher_alloc_score(p):
    """Catcher level/bench score: current bat + glove + small older-player
    tiebreak. Single source of truth for both Step 1 level allocation and
    Step 4 Backup C bench selection — both want the same notion of "best
    available catcher for the higher slot"."""
    woba = p.get('wOBA') or 0
    cfld = p.get('C_fld') or 0
    age = min(p.get('age') or 0, AGE_CAP)
    return woba + C_FLD_WEIGHT * cfld + AGE_WEIGHT * age

def priority(p):
    """Age-weighted blend of current and projected bat. Used for cascade/trim ordering."""
    age = p['age']
    woba = p.get('wOBA') or 0
    wobap = p.get('wOBAP') or 0
    if age <= 19: return 0.3 * woba + 0.7 * wobap
    elif age <= 21: return 0.5 * woba + 0.5 * wobap
    elif age <= 23: return 0.7 * woba + 0.3 * wobap
    else: return 0.9 * woba + 0.1 * wobap

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

def age_lowest_level(p):
    age = p['age']
    for lvl in reversed(LEVELS):
        if age <= MAX_AGE[lvl]:
            return LEVELS.index(lvl)
    return 0

def projected_pos_adj(p, pos):
    """Current pos_adj + bat development runway. Fielding doesn't develop."""
    cur = p.get(f'{pos}_adj')
    if cur is None: return None
    bat_dev = (p.get('war_hittingP') or 0) - (p.get('war_hitting') or 0)
    return cur + bat_dev

# Linear-weights coefficient from the pipeline. war_hitting is computed
# as (wOBA * RUNS_PER_GAME_HITTING_COEFF − RUNS_PER_GAME_HITTING_CONST) /
# RUNS_PER_WIN in metrics_hitting.calc_hitting_metrics. Because that's
# linear in wOBA, the WAR change per unit wOBA is just COEFF / RUNS_PER_WIN
# — independent of the player's overall wOBA or sign of war_hitting. This
# is the correct multiplier for converting a platoon wOBA delta into a
# WAR delta on top of `pos_adj`.
WAR_PER_WOBA_POINT = 554.7865342 / 10  # ≈ 55.48 WAR per 1.0 wOBA

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

def fill_starters_split(pool, level, vs):
    """Pick 9 starters using platoon-adjusted position scores. Same Hungarian
    over the same pool as `fill_starters`, but the score swaps in the
    handedness-specific hitting WAR.

    Intentionally omits HP / force-start bonuses — these are tactical lineup
    choices on a fixed roster, not roster-construction decisions, so platoon
    matchups should drive the call without prospect-development overrides.
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    pos_order = ['C', 'SS', '2B', 'CF', '3B', '1B', 'LF', 'RF', 'DH']

    def score(p, pos):
        pwar = pos_adj_split(p, pos, vs)
        if pwar is None: return None
        # Same natural-position priority tiebreak as fill_starters — keeps
        # standard and platoon Hungarians from arbitrarily flipping
        # equal-score swaps between two players who share a primary slot.
        natural = (0.5 + 0.001 * priority(p)) if p.get('pos_adj') == pos else 0
        return pwar + natural

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

def fill_starters(pool, level):
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    pos_order = ['C', 'SS', '2B', 'CF', '3B', '1B', 'LF', 'RF', 'DH']
    
    is_dev = level in ('R', 'R(DLR)')
    use_projected = level not in ('MLB', 'AAA')
    
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
        # Projection-based scoring is a *development* affordance — it counts
        # bat-dev runway against position WAR so a real prospect's future
        # value matters at AA-and-below. Apply it only to HPs. A non-HP at
        # this level is here on current ability and should be ranked by
        # current pos_adj, otherwise a non-HP with a flukily-big bat-dev
        # delta can outrank one whose current bat is clearly better — and
        # the platoon Hungarians (which always use current) will keep
        # benching the projection-favoured pick, signalling the mismatch.
        use_proj_for_p = use_projected and is_high_potential(p)
        pwar = projected_pos_adj(p, pos) if use_proj_for_p else p.get(f'{pos}_adj')
        if pwar is None: return None
        # Natural-position bonus, with a tiny priority-weighted tiebreak so
        # that when two players share a primary position and identical
        # fielding (e.g. Kepler & Moore both RF, same LF/RF/CF_fld), the
        # higher-priority hitter deterministically wins the contested
        # primary slot. Without this, Hungarian sees the swap as exactly
        # equal total team WAR and arbitrarily flips between standard and
        # platoon assignments.
        natural = (0.5 + 0.001 * priority(p)) if p.get('pos_adj') == pos else 0
        bonus = 0
        if is_dev and is_high_potential(p):
            bonus = 10.0
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

PREMIUM_POS = {'C', '2B', '3B', 'SS', 'CF'}
HP_MAX_AGE = 23
# Minimum fielding-only WAR at the premium position required to claim the
# .300 wOBAP HP threshold (vs the .320 non-premium threshold). The premium
# discount exists because a prospect whose bat plays at a tough defensive
# position is more valuable — but only if they actually defend it. A SS
# whose SS_fld is +0.4 won't really stay at SS as they develop, so we
# don't grant them the discount; their wOBAP has to clear the higher
# non-premium bar to count as HP.
PREMIUM_FLD_MIN = 1.5

IF_POSITIONS = ('2B', '3B', 'SS')
OF_POSITIONS = ('LF', 'CF', 'RF')

def classify_bench(bench):
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
      4. Best bat  - highest priority(p) among whoever's left.
    Subsequent slots are labelled 'Depth' in priority order. If no player
    fits a role (e.g. no catcher on the bench), that slot's player is None
    and the role is still included so callers can render an empty slot.
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

    # 2. Utility IF — glove-first among viable bats. Real utility IFs are
    #    defensive-replacement profiles (multi-position glove, modest bat),
    #    not bench bats who happen to play one IF spot. The bat is already
    #    "viable" by virtue of the player being on this level's bench (his
    #    wOBA passed the level's threshold via Step 2 cascade). So we rank
    #    by fielding-only WAR (not pos_adj, which folds the bat back in)
    #    and only use wOBA as a final tiebreak.
    def if_score(p):
        fld_vals = [p.get(f'{pos}_fld') for pos in IF_POSITIONS]
        valid = [v for v in fld_vals if v is not None]
        if not valid:
            return None
        return (len(valid), sum(valid), p.get('wOBA') or 0)
    ordered.append(('Utility IF', take(if_score)))

    # 3. Utility OF — same glove-first logic. CF eligibility still adds
    #    +1 to the position count: it's a speed/range proxy as well as a
    #    position, so a CF-capable OF beats a same-fielding LF/RF-only.
    def of_score(p):
        fld_vals = {pos: p.get(f'{pos}_fld') for pos in OF_POSITIONS}
        valid_pos = [pos for pos, v in fld_vals.items() if v is not None]
        if not valid_pos:
            return None
        cf_bonus = 1 if 'CF' in valid_pos else 0
        return (
            len(valid_pos) + cf_bonus,
            sum(fld_vals[pos] for pos in valid_pos),
            p.get('wOBA') or 0,
        )
    ordered.append(('Utility OF', take(of_score)))

    # 4. Best bat
    ordered.append(('Best bat', take(priority)))

    # Depth: whoever is left, by priority
    pool.sort(key=priority, reverse=True)
    for p in pool:
        ordered.append(('Depth', p))
    return ordered

def is_high_potential(p):
    """Minor-league prospect (minor=1, age <= HP_MAX_AGE) with elite projected
    bat for position. Age cap excludes 24+ AAAA-types whose wOBAP clears the
    threshold but who aren't real development cases.

    The wOBAP threshold is .300 only for prospects who *actually* play their
    listed premium position competently (`{pos}_fld >= PREMIUM_FLD_MIN`).
    A player whose `pos_adj` is SS but who's a +0.4 SS defender won't stick
    at SS as they develop — they'll move to a corner — so they shouldn't
    inherit the premium-position discount. Those players use the .320 non-
    premium bar instead."""
    if p.get('minor') != 1:
        return False
    if p['age'] > HP_MAX_AGE:
        return False
    wobap = p.get('wOBAP') or 0
    pos = p.get('pos_adj')
    if pos in PREMIUM_POS:
        fld = p.get(f'{pos}_fld')
        if fld is not None and fld >= PREMIUM_FLD_MIN:
            threshold = 0.300
        else:
            threshold = 0.320
    else:
        threshold = 0.320
    return wobap >= threshold

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
    injured_names = _load_injured_names()
    flagged_players = [p for p in laa if p['name'] in injured_names]
    laa = [p for p in laa if p['name'] not in injured_names]
    overflow = []
    by_level = {lvl: [] for lvl in LEVELS}
    
    # Compute eligible range
    valid_players = []
    for p in laa:
        top = woba_max_level(p)
        bot = age_lowest_level(p)
        if top > bot:
            overflow.append(p)
            continue
        p['_top'] = top
        p['_bot'] = bot
        valid_players.append(p)
    
    # === STEP 1: Catchers (2/level) ===
    # Score-driven greedy allocation: rank all catchers by `catcher_alloc_score`
    # (current wOBA + small C_fld component + small age tiebreak), then assign
    # two per level top-down. wOBA-eligibility (`_top`) and age-eligibility
    # (`_bot`) are both enforced strictly — no overmatched bats anywhere in
    # the system. If a level can't fill 2 catcher slots from strict-eligible
    # arms, it stays short (sign-FA gap, same convention as the bullpen).
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
        [p for p in valid_players if is_catcher(p)],
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

    # === STEP 2: Non-catchers (plus catchers not picked as primary C) ===
    # A catcher whose bat is good but whose glove is below the 14 primary-C
    # slots gets a second chance here — they may earn a bench spot via their
    # secondary positions (OF/1B/DH) rather than being released. is_catcher()
    # still returns True for them downstream (so HP swaps pair like-with-like
    # and sheets label them correctly), but they go through the regular
    # cascade as if they were any other non-catcher.
    noncatchers = [p for p in valid_players if not is_catcher(p)] + list(unassigned_c)
    nc_by = {lvl: [] for lvl in LEVELS}
    for p in noncatchers:
        nc_by[LEVELS[p['_top']]].append(p)
    for lvl in LEVELS:
        nc_by[lvl].sort(key=lambda p: priority(p), reverse=True)
    
    nc_slots = {lvl: ROSTER_SIZES[lvl] - len(cby[lvl]) for lvl in LEVELS}
    
    # Cascade down
    for i, lvl in enumerate(LEVELS):
        target = nc_slots[lvl]
        while len(nc_by[lvl]) > target:
            cascaded = nc_by[lvl].pop()
            next_idx = i + 1
            if next_idx <= cascaded['_bot'] and next_idx < len(LEVELS):
                nc_by[LEVELS[next_idx]].append(cascaded)
                nc_by[LEVELS[next_idx]].sort(key=lambda p: priority(p), reverse=True)
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
                    if best is None or priority(p) > priority(best):
                        best, best_j = p, j
            if best is None: break
            nc_by[LEVELS[best_j]].remove(best)
            nc_by[lvl].append(best)
            nc_by[lvl].sort(key=lambda p: priority(p), reverse=True)
    
    if len(nc_by['R(DLR)']) > nc_slots['R(DLR)']:
        overflow.extend(nc_by['R(DLR)'][nc_slots['R(DLR)']:])
        nc_by['R(DLR)'] = nc_by['R(DLR)'][:nc_slots['R(DLR)']]
    
    for lvl in LEVELS:
        by_level[lvl] = cby[lvl] + nc_by[lvl]
    
    # === STEP 3: High-potential starter enforcement ===
    # If HP benched at level X: swap with non-HP at X+1. If can't (age cap), force-start at X.
    # At rookie ball: fill_starters auto-prioritizes HPs.
    for _iter in range(20):
        changed = False
        for i, lvl in enumerate(LEVELS):
            # R / R(DLR) skip — those levels apply the +10 HP bonus inside
            # fill_starters so HPs always start there by construction. MLB
            # IS subject to HP cascade: if an HP gets pulled up by Step-2
            # pull-up but Hungarian benches them, demote back to AAA where
            # they can develop as a starter. The development cost of an HP
            # benched at MLB outweighs the marginal Util IF/OF upgrade —
            # mature non-HPs (no projection upside being lost) fill MLB
            # bench slots better.
            if lvl in ('R', 'R(DLR)'):
                continue
            starters, bench = fill_starters(by_level[lvl], lvl)
            hp_benched = [p for p in bench if is_high_potential(p)]
            # Platoon-overmatch signal: an HP standard starter who's DROPPED
            # from the vs-RHP lineup. RHB face righties about 3x as often as
            # lefties so vs-RHP is the dominant matchup signal. Movement
            # within OF or between similar-family slots is fine — only a
            # straight drop (out of the lineup entirely) flags overmatching.
            # The vs-RHP Hungarian doesn't apply the +10 HP bonus, so an HP
            # who can't earn a vs-RHP slot is surviving on projection alone
            # and should cascade down. Non-HPs aren't subject to this — the
            # existing Hungarian + bench-role pass already routes them to
            # 1B / DH / bench when they don't earn a positional starting
            # slot vs RHP.
            sR = fill_starters_split(by_level[lvl], lvl, 'R')
            sR_starter_ids = {id(p) for p in sR.values() if p}
            hp_overmatched = [
                p for p in starters.values()
                if p and is_high_potential(p)
                and id(p) not in sR_starter_ids
            ]
            hp_to_cascade = hp_benched + [p for p in hp_overmatched if p not in hp_benched]
            if not hp_to_cascade: continue

            for hp in hp_to_cascade:
                # Try to demote one level first
                cascaded = False
                if i + 1 < len(LEVELS):
                    next_lvl = LEVELS[i + 1]
                    if hp['age'] <= MAX_AGE[next_lvl]:
                        # Swap target constraints (see earlier discussion):
                        #  - non-HP, eligible at the higher level (`_top` ≤ i),
                        #    same catcher/non-catcher status as the HP.
                        hp_is_c = is_catcher(hp)
                        non_hp_in_next = [p for p in by_level[next_lvl]
                                          if not is_high_potential(p)
                                          and p['age'] <= MAX_AGE[lvl]
                                          and p['_top'] <= i
                                          and is_catcher(p) == hp_is_c]
                        # Two demote modes:
                        #  (a) Swap with target — only if the trade improves
                        #      the upper level (target's current-bat advantage
                        #      exceeds the HP's projection advantage). This is
                        #      the wOBA-difference vs potential-difference
                        #      check: if the HP's upside doesn't beat the
                        #      target's current bat, the target deserves the
                        #      upper-level slot.
                        #  (b) Demote without swap — HP just moves down a
                        #      level. The upper level's slot stays unfilled
                        #      for this iteration; if the HP's projection
                        #      doesn't justify displacing a better current bat
                        #      we'd rather have the HP develop one level lower
                        #      than push a real contributor out.
                        swap_target = None
                        if non_hp_in_next:
                            candidate = max(non_hp_in_next, key=lambda p: priority(p))
                            current_loss = (candidate.get('wOBA') or 0) - (hp.get('wOBA') or 0)
                            potential_gain = (hp.get('wOBAP') or 0) - (candidate.get('wOBAP') or 0)
                            # Swap only if HP's projection advantage at least
                            # matches the candidate's current-bat advantage.
                            if potential_gain >= current_loss:
                                swap_target = candidate
                        by_level[lvl].remove(hp)
                        by_level[next_lvl].append(hp)
                        if swap_target is not None:
                            by_level[next_lvl].remove(swap_target)
                            by_level[lvl].append(swap_target)
                        changed = True
                        cascaded = True
                # Can't cascade → mark for force-start at current level (handled in final fill_starters)
                if not cascaded:
                    hp['_force_start'] = lvl
        if not changed: break

    # === STEP 4: Bench-role refinement ===
    # The priority cascade picks rosters by bat alone, so a level can end
    # up with a "Utility IF" who only plays one IF position (e.g. Meckler
    # at MLB with 3B as his sole IF) while a true super-utility (Jarvis:
    # SS / 2B / 3B) sits at AAA. Walk top-down and, for each utility
    # role, swap up if the next level has a strictly more flexible
    # candidate eligible at this level. We only refine the multi-position
    # roles (Util IF / Util OF) — Backup C is already optimised in Step 1
    # and Best bat / starters are bat-first picks the cascade gets right.
    UTIL_ROLE_FNS = {
        'Utility IF': lambda p: sum(1 for pos in IF_POSITIONS if p.get(f'{pos}_adj') is not None),
        'Utility OF': lambda p: sum(1 for pos in OF_POSITIONS if p.get(f'{pos}_adj') is not None) + (1 if p.get('CF_adj') is not None else 0),
    }
    for _iter in range(20):
        changed = False
        for i, lvl in enumerate(LEVELS):
            if i + 1 >= len(LEVELS):
                continue
            next_lvl = LEVELS[i + 1]
            _, bench = fill_starters(by_level[lvl], lvl)
            bench_roles = classify_bench(bench)
            named_role_players = {p['name'] for _, p in bench_roles[:4] if p}
            for role, current in bench_roles[:4]:
                cap_fn = UTIL_ROLE_FNS.get(role)
                if cap_fn is None:
                    continue
                current_cap = cap_fn(current) if current else -1
                # Candidate at next_lvl must be eligible upstairs by wOBA and
                # age, not a catcher (utility roles are non-C), and not an HP
                # (HPs need to start somewhere — even at MLB the development
                # cost of benching an HP outweighs the marginal Util IF/OF
                # upgrade, so a mature non-HP with no projection upside is
                # the right MLB bench piece). The HP-cascade skip at MLB
                # stays in place as a safety net but refinement won't pull
                # HPs up in the first place.
                candidates = [
                    p for p in by_level[next_lvl]
                    if p['_top'] <= i
                    and p['age'] <= MAX_AGE[lvl]
                    and not is_catcher(p)
                    and not is_high_potential(p)
                    and p.get('_force_start') != next_lvl
                    and (current is None or p['name'] != current['name'])
                ]
                if not candidates:
                    continue
                best_alt = max(candidates, key=lambda p: (cap_fn(p), priority(p)))
                if cap_fn(best_alt) <= current_cap:
                    continue
                # Refinement is always a 1-for-1 swap so roster sizes stay put.
                # If `current` is the role-holder we already have, displace them.
                # Otherwise (no fit on the bench at all), displace the lowest-
                # priority bench player who isn't holding another named role —
                # they're our most expendable depth piece. If everyone on the
                # bench is filling a named role and the role we want is still
                # missing, leave the role empty rather than evict a contributor.
                displace = current
                if displace is None:
                    spare_bench = [p for p in bench if p['name'] not in named_role_players]
                    if not spare_bench:
                        continue
                    displace = min(spare_bench, key=priority)
                if displace['age'] > MAX_AGE[next_lvl]:
                    continue
                by_level[lvl].remove(displace)
                by_level[next_lvl].append(displace)
                by_level[next_lvl].remove(best_alt)
                by_level[lvl].append(best_alt)
                # Also keep our local view of the bench in sync so subsequent
                # role iterations within this pass don't double-count slots.
                bench = [p for p in bench if p['name'] != displace['name']] + [best_alt]
                named_role_players = {p['name'] for _, p in classify_bench(bench)[:4] if p}
                changed = True
        if not changed:
            break

    # Final Hungarian (overall + platoon variants on the same roster)
    rosters = {}
    for lvl in LEVELS:
        starters, bench = fill_starters(by_level[lvl], lvl)
        rosters[lvl] = {
            'starters': starters,
            'starters_vsR': fill_starters_split(by_level[lvl], lvl, 'R'),
            'starters_vsL': fill_starters_split(by_level[lvl], lvl, 'L'),
            'bench': bench,
            'bench_roles': classify_bench(bench),
            'all': by_level[lvl],
        }

    return rosters, overflow, flagged_players

if __name__ == '__main__':
    rosters, overflow, flagged = main()
    for lvl in LEVELS:
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
