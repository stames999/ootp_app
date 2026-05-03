"""LAA pitcher assignment - 5 SP + 8 RP per level.

Mirrors the hitter system: a current-ability ceiling (`PWOBA_MAX`,
analogous to hitter `WOBA_MIN`) determines each pitcher's `_top` level,
and an age-weighted blend of current and projected pwOBA (`pitcher_priority`,
analogous to hitter `priority`) drives cascade ordering. The blend lets a
young high-projection arm (Fana, age 18, pwOBA .401 / pwOBAP .307) outrank
an older same-pwOBA arm with no projection upside. The threshold prevents
over-promotion: a prospect's projection can't push them above the level
their current stuff supports.

Algorithm:
  Step 0  Filter international complex (minor=0 + age<20).
  Step 1  Compute `_top` (best level by current pwOBA, gated by PWOBA_MAX —
          no age-based extra cap; current stuff alone determines ceiling)
          and `_bot` (oldest level by age, reusing hitter MAX_AGE). If
          `_top > _bot` the pitcher has nowhere to fit → overflow.
  Step 2  SP cascade. Place each SP-viable pitcher at their `_top` initially.
          For each level top-down, while over `SP_PER_LEVEL`, pop the
          worst-blend pitcher and cascade to the next level (or overflow if
          age cap blocks the next level).
  Step 3  SP pull-up. Walk levels top-down; if a level is under
          `SP_PER_LEVEL`, pull the best-blend pitcher from below who is
          age-eligible. Pull-up does NOT enforce `_top` (accepts sub-
          threshold filler) because under-filled rotations are worse than
          a marginal pitcher one level above their nominal ceiling.
  Step 4  RP cascade + pull-up — same shape with `RP_PER_LEVEL` slots over
          RP-viable pitchers minus those placed as SPs.
  Step 5  Anyone unplaced → overflow.

Notes / limitations:
- No SP↔RP comparative override (a 6th-best MLB SP cascades to AAA SP
  rather than possibly being a better fit as MLB RP).
- No platoon (vs RHB / vs LHB) staff variants — `pwOBAR` / `pwOBAL` are
  available and could power that later.
- No bullpen role tagging (closer / setup / LOOGY).
"""
import json

from build_system import LEVELS, MAX_AGE, age_lowest_level, _load_injured_names

PITCHERS_JSON = 'outputs/pitchers.json'

SP_PER_LEVEL = 5
RP_PER_LEVEL = 8
PITCHER_ROSTER_SIZE = SP_PER_LEVEL + RP_PER_LEVEL

# Maximum pwOBA a pitcher can allow and still belong at a given level.
# Lower = better stuff, so this is a CEILING (analogous to WOBA_MIN being a
# floor for hitters). Calibrated against league wOBA ≈ .320: MLB pitchers
# cluster .280-.340; AAA fringe to .365; lower minors more permissive. Tune
# if rosters look over- or under-matched at any level.
PWOBA_MAX = {
    'MLB':    0.345,
    'AAA':    0.370,
    'AA':     0.385,
    'A+':     0.395,
    'A':      0.405,
    'R':      0.420,
    'R(DLR)': 1.000,  # no upper limit — accepts whatever's left
}


def load_team_pitchers(org=None):
    """Load pitchers for a single org. Defaults to config.team_managed."""
    if org is None:
        from config import team_managed
        org = team_managed
    d = json.load(open(PITCHERS_JSON))
    return [r for r in d['rows'] if r['org'] == org]

# Back-compat alias.
def load_laa_pitchers():
    return load_team_pitchers('LAA')


def pitcher_priority(p):
    """Age-weighted blend of current and projected pwOBA. Lower = better
    (matches the pwOBA convention where lower-allowed-wOBA is the goal).
    Mirrors the hitter `priority` weights:
      ≤19  : 30% current + 70% projected (raw projection bias)
      20-21: 50/50
      22-23: 70/30
      24+  : 90/10 (mature, projection nearly realised)"""
    age = p['age']
    pwoba = p.get('pwOBA') if p.get('pwOBA') is not None else 1.0
    pwobap = p.get('pwOBAP') if p.get('pwOBAP') is not None else pwoba
    if age <= 19:
        return 0.3 * pwoba + 0.7 * pwobap
    if age <= 21:
        return 0.5 * pwoba + 0.5 * pwobap
    if age <= 23:
        return 0.7 * pwoba + 0.3 * pwobap
    return 0.9 * pwoba + 0.1 * pwobap


def pwoba_top_level(p):
    """Highest level (smallest LEVELS index) the pitcher's CURRENT pwOBA
    qualifies for. Threshold is a hard ceiling on placement — a prospect
    with great projection but currently-poor stuff can't be promoted past
    the level their current pwOBA supports."""
    pwoba = p.get('pwOBA') if p.get('pwOBA') is not None else 1.0
    for lvl in LEVELS:
        if pwoba <= PWOBA_MAX[lvl]:
            return LEVELS.index(lvl)
    return len(LEVELS) - 1


# NOTE: there is no age-based `_top` cap for pitchers. An earlier version
# had `PITCHER_AGE_TOP` to guard against the OOTP pwOBA-floor clamp (a
# young arm with truly bad stuff still rates pwOBA ~.403 because the
# linear-weights conversion bottoms out there). Removed because:
#   1. pwOBA .403 only qualifies for A or below (PWOBA_MAX['A'] = .405),
#      never MLB / AAA / AA, so the clamp wasn't actually causing
#      over-promotion the way the cap framing suggested.
#   2. The cap was over-conservative for legitimate young aces (e.g. a
#      21yo HP with pwOBA .345 was AA-locked despite MLB-grade stuff).
# `_top` is now `pwoba_top_level(p)` only — current pwOBA is the gate.


def is_sp_viable(p):
    return p.get('sp_warP') is not None


def is_rp_viable(p):
    return p.get('rp_warP') is not None


# HP pitcher = young minor-league arm whose projection puts them at clearly
# above-MLB-rosterable quality. Mirrors the hitter HP idea: minor=1, age ≤ 23,
# projection clears a meaningful bar. We use pwOBAP ≤ 0.330 — a tier below
# the MLB roster threshold (.345) so HP requires "true rotation/bullpen
# upside" rather than just "barely MLB-eligible". Tweak HP_PITCHER_MAX_PWOBAP
# if you want a tighter / looser bar.
HP_PITCHER_MAX_AGE = 23
HP_PITCHER_MAX_PWOBAP = 0.330


def is_high_potential_pitcher(p):
    if p.get('minor') != 1:
        return False
    if p['age'] > HP_PITCHER_MAX_AGE:
        return False
    pwobap = p.get('pwOBAP')
    if pwobap is None:
        return False
    return pwobap <= HP_PITCHER_MAX_PWOBAP


def _cascade(pool, slots_per_level):
    """Initial placement at each pitcher's `_top`, then cascade-down: while a
    level holds more than `slots_per_level`, pop the worst-blend pitcher and
    push to the next level (or to leftovers if age cap blocks). Returns
    (by_level, leftovers)."""
    by_level = {lvl: [] for lvl in LEVELS}
    leftovers = []
    for p in pool:
        by_level[LEVELS[p['_top']]].append(p)
    for lvl in LEVELS:
        by_level[lvl].sort(key=pitcher_priority)
    for i, lvl in enumerate(LEVELS):
        while len(by_level[lvl]) > slots_per_level:
            cascaded = by_level[lvl].pop()  # last = worst blend
            next_idx = i + 1
            if next_idx <= cascaded['_bot'] and next_idx < len(LEVELS):
                by_level[LEVELS[next_idx]].append(cascaded)
                by_level[LEVELS[next_idx]].sort(key=pitcher_priority)
            else:
                leftovers.append(cascaded)
    return by_level, leftovers


def _pull_up(by_level, slots_per_level):
    """Top-down fill in two passes per level:
      1. Strict — pull the best-blend pitcher from below whose `_top` already
         qualifies them at this level. HPs and non-HPs both compete here.
      2. Non-HP +1 stretch — if gaps remain, pull up non-HPs whose `_top` is
         exactly one level below this one. The veteran-arm stretch lets a
         steady AA reliever backfill an empty AAA bullpen slot rather than
         leaving a "Sign FA" gap. HPs are excluded from the stretch — we
         don't want to over-promote young arms whose pwOBA is unreliable
         anyway. Strict pass runs first so the best fits land in their
         natural level before any stretching happens."""
    for i, lvl in enumerate(LEVELS):
        # Pass 1: strict (_top <= i)
        while len(by_level[lvl]) < slots_per_level:
            best = None
            best_j = None
            for j in range(i + 1, len(LEVELS)):
                for p in by_level[LEVELS[j]]:
                    if i > p['_bot']:
                        continue
                    if p['_top'] > i:
                        continue
                    if best is None or pitcher_priority(p) < pitcher_priority(best):
                        best, best_j = p, j
            if best is None:
                break
            by_level[LEVELS[best_j]].remove(best)
            by_level[lvl].append(best)
            by_level[lvl].sort(key=pitcher_priority)

        # Pass 2: non-HP +1 stretch (_top == i + 1)
        while len(by_level[lvl]) < slots_per_level:
            best = None
            best_j = None
            for j in range(i + 1, len(LEVELS)):
                for p in by_level[LEVELS[j]]:
                    if i > p['_bot']:
                        continue
                    if p['_top'] != i + 1:
                        continue
                    if is_high_potential_pitcher(p):
                        continue
                    if best is None or pitcher_priority(p) < pitcher_priority(best):
                        best, best_j = p, j
            if best is None:
                break
            by_level[LEVELS[best_j]].remove(best)
            by_level[lvl].append(best)
            by_level[lvl].sort(key=pitcher_priority)


def main(org=None):
    laa = load_team_pitchers(org)
    for p in laa:
        p.pop('_role', None)

    # Step 0: filter international complex + injured-list (see injured.txt)
    laa = [p for p in laa if not (p.get('minor') == 0 and p['age'] < 20)]
    injured_names = _load_injured_names()
    flagged_players = [p for p in laa if p['name'] in injured_names]
    laa = [p for p in laa if p['name'] not in injured_names]

    # Step 1: eligibility window. `_top` = current pwOBA ceiling only;
    # there's no age-based extra cap (see PITCHER_AGE_TOP removal note).
    overflow = []
    valid = []
    for p in laa:
        p['_top'] = pwoba_top_level(p)
        p['_bot'] = age_lowest_level(p)
        if p['_top'] > p['_bot']:
            overflow.append(p)
        else:
            valid.append(p)

    # Step 2-3: SP cascade + pull-up
    sp_pool = [p for p in valid if is_sp_viable(p)]
    sp_by, _sp_leftover = _cascade(sp_pool, SP_PER_LEVEL)
    _pull_up(sp_by, SP_PER_LEVEL)
    sp_assigned = {p['name'] for lvl in LEVELS for p in sp_by[lvl]}

    # Step 4: RP cascade + pull-up
    rp_pool = [p for p in valid if is_rp_viable(p) and p['name'] not in sp_assigned]
    rp_by, rp_leftover = _cascade(rp_pool, RP_PER_LEVEL)
    _pull_up(rp_by, RP_PER_LEVEL)
    rp_assigned = {p['name'] for lvl in LEVELS for p in rp_by[lvl]}

    # Step 5: overflow
    overflow.extend(rp_leftover)
    overflow_names = {p['name'] for p in overflow}
    for p in valid:
        if (p['name'] not in sp_assigned
                and p['name'] not in rp_assigned
                and p['name'] not in overflow_names):
            overflow.append(p)
            overflow_names.add(p['name'])

    # Tag roles + present each level's lists in blend order (best first)
    rosters = {}
    for lvl in LEVELS:
        sp_by[lvl].sort(key=pitcher_priority)
        rp_by[lvl].sort(key=pitcher_priority)
        for p in sp_by[lvl]:
            p['_role'] = 'SP'
        for p in rp_by[lvl]:
            p['_role'] = 'RP'
        rosters[lvl] = {
            'starters': sp_by[lvl],
            'bullpen': rp_by[lvl],
            'all': sp_by[lvl] + rp_by[lvl],
        }

    return rosters, overflow, flagged_players


if __name__ == '__main__':
    rosters, overflow, flagged = main()
    for lvl in LEVELS:
        r = rosters[lvl]
        print(f"\n=== {lvl} ({len(r['all'])}) ===")
        print('  STARTING ROTATION:')
        for p in r['starters']:
            blend = pitcher_priority(p)
            print(f"    {p['name']:25} age={p['age']:2} pwOBA={p.get('pwOBA') or 0:.3f} pwOBAP={p.get('pwOBAP') or 0:.3f} blend={blend:.3f}")
        print('  BULLPEN:')
        for p in r['bullpen']:
            blend = pitcher_priority(p)
            print(f"    {p['name']:25} age={p['age']:2} pwOBA={p.get('pwOBA') or 0:.3f} pwOBAP={p.get('pwOBAP') or 0:.3f} blend={blend:.3f}")
    print(f'\nOverflow: {len(overflow)}')
    print(f'Flagged (unavailable): {len(flagged)}')
