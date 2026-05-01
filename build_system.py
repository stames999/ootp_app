"""LAA hitter assignment v3 - wOBA-driven with overflow cascade."""
import json

POSITIONS = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH']
LEVELS = ['MLB', 'AAA', 'AA', 'A+', 'A', 'R', 'R(DLR)']
ROSTER_SIZES = {'MLB': 13, 'AAA': 13, 'AA': 13, 'A+': 13, 'A': 13, 'R': 15, 'R(DLR)': 15}

WOBA_MIN = {
    'MLB': 0.280,
    'AAA': 0.250,
    'AA': 0.220,
    'A+': 0.195,
    'A': 0.170,
    'R': 0.140,
    'R(DLR)': -1.0,
}

MAX_AGE = {
    'R(DLR)': 21, 'R': 22, 'A': 23, 'A+': 24,
    'AA': 99, 'AAA': 99, 'MLB': 99,
}

HITTERS_JSON = 'outputs/hitters.json'

def load_laa():
    d = json.load(open(HITTERS_JSON))
    return [r for r in d['rows'] if r['org'] == 'LAA']

def is_catcher(p):
    return p.get('C_adj') is not None

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
    woba = p.get('wOBA') or 0
    wobap = p.get('wOBAP') or 0
    age = p['age']
    # For young players, current wOBA understates the ceiling (small samples,
    # raw tools not yet realized). Blend in wOBAP so a high-projection bat
    # below the HP threshold isn't stranded at a level beneath their potential.
    # Weights are deliberately conservative; tune if assignments feel off.
    if age <= 19:
        effective = max(woba, 0.6 * woba + 0.4 * wobap)
    elif age <= 21:
        effective = max(woba, 0.8 * woba + 0.2 * wobap)
    else:
        effective = woba
    for lvl in LEVELS:
        if effective >= WOBA_MIN[lvl]:
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

def fill_starters(pool, level):
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    pos_order = ['C', 'SS', '2B', 'CF', '3B', '1B', 'LF', 'RF', 'DH']
    
    is_dev = level in ('R', 'R(DLR)')
    use_projected = level not in ('MLB', 'AAA')
    
    def score(p, pos):
        pwar = projected_pos_adj(p, pos) if use_projected else p.get(f'{pos}_adj')
        if pwar is None: return None
        natural = 0.5 if p.get('pos_adj') == pos else 0
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

def is_high_potential(p):
    """Minor-league prospect (minor=1) with elite projected bat for position."""
    if p.get('minor') != 1:
        return False
    wobap = p.get('wOBAP') or 0
    pos = p.get('pos_adj')
    threshold = 0.300 if pos in PREMIUM_POS else 0.320
    return wobap >= threshold

def main():
    laa = load_laa()
    # Strip transient flags from any prior run on cached dicts (load_laa
    # currently re-reads from disk, but this guards against future callers
    # that hand us already-processed players).
    for p in laa:
        p.pop('_force_start', None)
    # Exclude international complex: minor=0 + age <20 (not in active minor system this year)
    complex_players = [p for p in laa if p.get('minor') == 0 and p['age'] < 20]
    laa = [p for p in laa if not (p.get('minor') == 0 and p['age'] < 20)]
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
    catchers = sorted(
        [p for p in valid_players if is_catcher(p)],
        key=lambda p: (priority(p)) + 0.05 * (p.get('C_adj') or 0),
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
    overflow.extend(unassigned_c)
    
    # === STEP 2: Non-catchers ===
    noncatchers = [p for p in valid_players if not is_catcher(p)]
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
            if lvl in ('R', 'R(DLR)'):
                continue
            starters, bench = fill_starters(by_level[lvl], lvl)
            hp_benched = [p for p in bench if is_high_potential(p)]
            if not hp_benched: continue
            
            for hp in hp_benched:
                # Try to cascade down first
                cascaded = False
                if i + 1 < len(LEVELS):
                    next_lvl = LEVELS[i + 1]
                    if hp['age'] <= MAX_AGE[next_lvl]:
                        non_hp_in_next = [p for p in by_level[next_lvl] 
                                          if not is_high_potential(p) and p['age'] <= MAX_AGE[lvl]]
                        if non_hp_in_next:
                            swap = min(non_hp_in_next, key=lambda p: priority(p))
                            by_level[lvl].remove(hp)
                            by_level[next_lvl].remove(swap)
                            by_level[next_lvl].append(hp)
                            by_level[lvl].append(swap)
                            changed = True
                            cascaded = True
                # Can't cascade → mark for force-start at current level (handled in final fill_starters)
                if not cascaded:
                    hp['_force_start'] = lvl
        if not changed: break
    
    # Final Hungarian
    rosters = {}
    for lvl in LEVELS:
        starters, bench = fill_starters(by_level[lvl], lvl)
        rosters[lvl] = {'starters': starters, 'bench': bench, 'all': by_level[lvl]}
    
    return rosters, overflow

if __name__ == '__main__':
    rosters, overflow = main()
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
