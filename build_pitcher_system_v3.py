"""v3 pitcher placement — thresholdless two-phase waterfall.

Departure from v2: drop the `PWOBA_MAX` threshold gate entirely. An
arm's `_top` no longer constrains placement; only `_bot` (age + service
+ DSL) does. The placement model becomes:

  Phase 1 (SP fill, top-down):
    For each level i in [MLB, AAA, AA, A+, A, R, R(DLR)]:
      - Eligible = sp_viable arms not yet placed with `_bot >= i`,
        respecting the HP MLB block.
      - Reserve SP_PER_LEVEL[i] slots for HPs first (top HPs by
        priority).
      - Fill remaining SP slots with non-HP sp_viable arms by priority.

  Phase 2 (RP fill, top-down):
    For each level i:
      - Eligible = (sp_viable arms not placed in Phase 1)
                   + (rp-only arms with `_bot >= i`).
      - Pick top RP_PER_LEVEL[i] by priority, with LHP balance at
        LHP_LEVELS.

  Unplaced after both phases → overflow.

Semantic shift vs v2: levels are now "depth ranks within the org" not
"absolute skill tiers." A thin org's best 5 arms always fill MLB SP
even if their pwOBA is mediocre; a deep org pushes its surplus down.

Same priority function, same HP detection, same R(DLR) sub-team split,
same two-way / injured handling. The only thing eliminated is the
pwOBA-based level ceiling.
"""
from __future__ import annotations  # PEP 604 unions (`str | None`) — Python 3.9 (Streamlit Cloud) compat

import json

from roster_common import (
    LEVELS,
    age_lowest_level,
    service_lowest_level,
    dsl_eligible_lowest_level,
    _load_injured_names,
    _count_dsl_teams,
    is_player_injured,
)
from config import (
    SP_PER_LEVEL, RP_PER_LEVEL,
    LHP_LEVELS, LEFTY_MIN, LEFTY_TARGET, LEFTY_MAX,
    HP_PITCHER_MAX_AGE, HP_PITCHER_MAX_PWOBAP,
    HP_MIN_LEVEL_INDEX,
    PRIORITY_BLEND_CURRENT_WEIGHT, PRIORITY_BLEND_PROJECTED_WEIGHT,
    BLOCKER_CEILING_DELTA, BLOCKER_MLB_PWOBA, BLOCKER_PENALTY_SCALE,
)

PITCHERS_JSON = 'outputs/pitchers.json'

# Derived total roster size per level (SP + RP). Re-exported so downstream
# modules (build_excel, streamlit_app) can import it from the active
# pitcher-system module without caring which version it is.
PITCHER_ROSTER_SIZE = {lvl: SP_PER_LEVEL[lvl] + RP_PER_LEVEL[lvl] for lvl in LEVELS}

# Priority bonus applied when an HP is being ranked at their `_bot` level
# (the deepest level they can legally play). This is the "developmental
# home advantage": at every other level the HP competes on plain
# priority, but at their floor they get a 0.015 boost — enough to win
# the marginal SP slot that would otherwise go to a fringe non-HP and
# leave the HP in the bullpen pool. Empirically (sweep across 30 orgs
# on Rockies Rebuild): +0.015 rescues all sp_warP ≥ 2.0 HPs from
# bullpens with zero net change to slot fill or overflow — it's a clean
# swap (HP in / non-HP out at the level the priority cascade was about
# to leave the HP in bullpen anyway). +0.010 leaves 5 strong-projection
# HPs still stranded; +0.020+ shows diminishing returns.
HP_BOT_PRIORITY_BONUS = 0.015


# ---------------------------------------------------------------------------
# Shared helpers (copied from v2; consolidate later if v3 ships)
# ---------------------------------------------------------------------------

def load_team_pitchers(org: str | None = None) -> list[dict]:
    if org is None:
        from config import team_managed
        org = team_managed
    d = json.load(open(PITCHERS_JSON))
    return [r for r in d['rows'] if r['org'] == org]


def pitcher_priority(p: dict, level: str | None = None,
                      role: str = 'SP') -> float:
    """Cascade-ordering key. Lower = better.

    90/10 weighted blend of current and projected pwOBA — a small
    projection nudge that catches strong-projection HPs at the margin
    without inflating them multiple levels above their current pwOBA
    tier. Two targeted adjustments layer on top:

      1. Blocker penalty (SP-only) — non-HP at-ceiling sub-MLB-ceiling
         arms get their priority bumped by
         `BLOCKER_PENALTY_SCALE * (pwOBAP - .345)`. Keeps maxed-out
         fringe vets from displacing HPs with real upside in
         rotation competition. NOT applied for RP placement — at the
         bullpen, a maxed-out vet is perfectly fine depth and shouldn't
         be artificially pushed down.
      2. HP `_bot` bonus (always) — HPs at their deepest eligible level
         get `-HP_BOT_PRIORITY_BONUS` priority. Guarantees they crack
         SP where it matters most for development; in RP placement it
         still applies but rarely changes the outcome.

    `role` defaults to 'SP' to preserve behavior for any caller that
    doesn't pass it (display sort, etc.). Phase 2 RP placement passes
    `role='RP'`.
    """
    pwoba = p.get('pwOBA') if p.get('pwOBA') is not None else 1.0
    if level == 'MLB':
        return pwoba
    pwobap = p.get('pwOBAP') if p.get('pwOBAP') is not None else pwoba
    priority = (PRIORITY_BLEND_CURRENT_WEIGHT * pwoba
                + PRIORITY_BLEND_PROJECTED_WEIGHT * pwobap)
    # Blocker penalty: only for SP allocation.
    if (role == 'SP'
            and not is_high_potential_pitcher(p)
            and (pwoba - pwobap) < BLOCKER_CEILING_DELTA
            and pwobap > BLOCKER_MLB_PWOBA):
        priority += BLOCKER_PENALTY_SCALE * (pwobap - BLOCKER_MLB_PWOBA)
    # HP "developmental home advantage" at the floor level.
    if is_high_potential_pitcher(p) and level is not None:
        bot_idx = p.get('_bot')
        if bot_idx is not None:
            # R(DLR) sub-team keys (R(DLR)1, R(DLR)2, ...) collapse to R(DLR).
            sort_lvl = 'R(DLR)' if str(level).startswith('R(DLR)') else level
            if sort_lvl == LEVELS[bot_idx]:
                priority -= HP_BOT_PRIORITY_BONUS
    return priority


def is_sp_viable(p):
    return p.get('sp_warP') is not None


def is_rp_viable(p):
    return p.get('rp_warP') is not None


def pwoba_top_level(p: dict) -> int:
    """Highest level (smallest LEVELS index) the pitcher's CURRENT pwOBA
    qualifies for under config.PWOBA_MAX.

    v3 doesn't gate placement on `_top`, but the field is still set on
    every player for downstream display / diagnostic use (and consumed
    by build_excel / streamlit_app filters). Same semantics as v1/v2."""
    from config import PWOBA_MAX
    pwoba = p.get('pwOBA') if p.get('pwOBA') is not None else 1.0
    for lvl in LEVELS:
        if pwoba <= PWOBA_MAX[lvl]:
            return LEVELS.index(lvl)
    return len(LEVELS) - 1


def is_high_potential_pitcher(p):
    if p.get('minor') != 1:
        return False
    if p['age'] > HP_PITCHER_MAX_AGE:
        return False
    pwobap = p.get('pwOBAP')
    if pwobap is None:
        return False
    return pwobap <= HP_PITCHER_MAX_PWOBAP


def is_lhp(p):
    return p.get('throws') == 2


def _filter_complex_and_injured(laa):
    laa = [p for p in laa if not (p.get('minor') == 0 and p['age'] < 20)]
    injured = _load_injured_names()
    flagged_players = [p for p in laa if is_player_injured(p, injured)]
    valid = [p for p in laa if not is_player_injured(p, injured)]
    return valid, flagged_players


def _compute_eligibility_window(pool):
    """v3: only `_bot` is binding. `_top` is computed for display and
    diagnostic compatibility with v1/v2, but it doesn't gate placement.
    """
    # `_top` is still computed (against current PWOBA_MAX) for
    # diagnostic / display compatibility — renderers and tests sometimes
    # inspect it. The placement loop just ignores it.
    overflow = []
    valid = []
    for p in pool:
        p['_top'] = pwoba_top_level(p)
        p['_bot'] = min(age_lowest_level(p), service_lowest_level(p),
                        dsl_eligible_lowest_level(p))
        valid.append(p)
    return valid, overflow


def _per_org_slot_capacities(org):
    sp_slots = {lvl: SP_PER_LEVEL[lvl] for lvl in LEVELS}
    rp_slots = {lvl: RP_PER_LEVEL[lvl] for lvl in LEVELS}
    n_dsl = max(1, _count_dsl_teams(org))
    sp_slots['R(DLR)'] = SP_PER_LEVEL['R(DLR)'] * n_dsl
    rp_slots['R(DLR)'] = RP_PER_LEVEL['R(DLR)'] * n_dsl
    return sp_slots, rp_slots, n_dsl


def _select_bullpen_with_lhp(eligible, target, lvl):
    """Same shape as v2: pick top `target` by priority, with LHP balance
    reservation at LHP_LEVELS. Uses RP-role priority (blocker penalty
    suppressed) — maxed-out vets are fine bullpen depth and shouldn't be
    artificially pushed down."""
    sorted_eligible = sorted(eligible,
                             key=lambda p: pitcher_priority(p, lvl, role='RP'))
    if lvl not in LHP_LEVELS:
        return sorted_eligible[:target], 0
    lefties = [p for p in sorted_eligible if is_lhp(p)]
    reserved_lhp = lefties[:LEFTY_MIN]
    lhp_shortfall = max(0, LEFTY_MIN - len(reserved_lhp))
    remaining_slots = target - LEFTY_MIN
    extra_lhp_cap = LEFTY_MAX - len(reserved_lhp)
    extra_lhp_taken = 0
    extra = []
    reserved_ids = {id(p) for p in reserved_lhp}
    for p in sorted_eligible:
        if id(p) in reserved_ids:
            continue
        if len(extra) >= remaining_slots:
            break
        if is_lhp(p):
            if extra_lhp_taken >= extra_lhp_cap:
                continue
            extra_lhp_taken += 1
        extra.append(p)
    return reserved_lhp + extra, lhp_shortfall


# ---------------------------------------------------------------------------
# v3 core: two-phase waterfall
# ---------------------------------------------------------------------------

def _eligible_for_level(pool, level_idx, role_check):
    """Filter a pool to arms eligible for placement at `level_idx`:
      - `_bot` covers this level (level_idx <= _bot).
      - role-check (sp_viable / rp_viable) passes.
      - HP MLB block: HPs not placed at levels above HP_MIN_LEVEL_INDEX
        unless `_bot` is also above (pathological case).
    """
    eligible = []
    for p in pool:
        if level_idx > p.get('_bot', len(LEVELS) - 1):
            continue
        if not role_check(p):
            continue
        if (level_idx < HP_MIN_LEVEL_INDEX
                and is_high_potential_pitcher(p)
                and p.get('_bot', 0) >= HP_MIN_LEVEL_INDEX):
            continue
        eligible.append(p)
    return eligible


def _phase_one_sp(valid, sp_slots):
    """SP fill, top-down. At each level, take the top sp_target arms by
    priority — HPs compete on the same priority blend as everyone else,
    no HP reservation. Returns (sp_by, remaining_sp).

    Earlier v3 reserved SP slots for HPs first, but with thresholds
    removed that ended up cascading HPs UP (e.g., a .373 HP claiming an
    AAA SP slot the user expected at A+). Under priority-only filling,
    HPs with good projection still place well — the 85/15 blend gives
    their pwOBAP weight — but they don't leapfrog better-current-stuff
    non-HPs into higher rotations.
    """
    sp_by = {lvl: [] for lvl in LEVELS}
    remaining = [p for p in valid if is_sp_viable(p)]

    for i, lvl in enumerate(LEVELS):
        eligible = _eligible_for_level(remaining, i, is_sp_viable)
        target = sp_slots[lvl]
        eligible.sort(key=lambda p: pitcher_priority(p, lvl))
        starters = eligible[:target]
        sp_by[lvl] = starters
        taken = {id(p) for p in starters}
        remaining = [p for p in remaining if id(p) not in taken]

    return sp_by, remaining


def _phase_two_rp(valid, sp_by, remaining_sp, rp_slots):
    """RP fill, top-down. Pool = remaining_sp + rp-only arms. LHP balance
    applies at LHP_LEVELS. Returns (rp_by, remaining_rp, lhp_shortfalls).
    """
    rp_by = {lvl: [] for lvl in LEVELS}
    lhp_shortfalls: dict[str, int] = {}

    sp_placed_ids = {id(p) for lvl in LEVELS for p in sp_by[lvl]}
    # Pool: all rp_viable arms not placed as SP, plus sp_viable arms
    # who lost the SP race in Phase 1 (they're already in remaining_sp
    # and rp_viable if dual-viable).
    rp_pool = []
    for p in valid:
        if id(p) in sp_placed_ids:
            continue
        if not is_rp_viable(p):
            continue
        rp_pool.append(p)

    for i, lvl in enumerate(LEVELS):
        eligible = _eligible_for_level(rp_pool, i, is_rp_viable)
        bullpen, shortfall = _select_bullpen_with_lhp(
            eligible, rp_slots[lvl], lvl,
        )
        rp_by[lvl] = bullpen
        if shortfall:
            lhp_shortfalls[lvl] = shortfall
        taken = {id(p) for p in bullpen}
        rp_pool = [p for p in rp_pool if id(p) not in taken]

    return rp_by, rp_pool, lhp_shortfalls


def main(org: str | None = None) -> tuple[dict, list[dict], list[dict]]:
    """Build the pitcher staff for one org (v3). Same return shape as
    v1/v2: `(rosters_by_level, overflow, flagged_players)`."""
    laa = load_team_pitchers(org)
    for p in laa:
        p.pop('_role', None)

    laa, flagged_players = _filter_complex_and_injured(laa)
    valid, immediate_overflow = _compute_eligibility_window(laa)
    sp_slots, rp_slots, n_dsl = _per_org_slot_capacities(org)

    # Phase 1: fill SP slots.
    sp_by, remaining_sp = _phase_one_sp(valid, sp_slots)

    # Phase 2: fill RP slots.
    rp_by, remaining_rp, lhp_shortfalls = _phase_two_rp(
        valid, sp_by, remaining_sp, rp_slots,
    )

    # Unplaced sp_viable (no rp_viable status) join overflow alongside
    # unplaced rp_viable arms.
    sp_placed_ids = {id(p) for lvl in LEVELS for p in sp_by[lvl]}
    rp_placed_ids = {id(p) for lvl in LEVELS for p in rp_by[lvl]}
    overflow = list(immediate_overflow)
    placed = sp_placed_ids | rp_placed_ids
    for p in valid:
        if id(p) not in placed:
            overflow.append(p)

    # R(DLR) sub-team split.
    if n_dsl >= 2 and 'R(DLR)' in sp_by:
        dsl_sp = SP_PER_LEVEL['R(DLR)']
        dsl_rp = RP_PER_LEVEL['R(DLR)']
        sp_full = sorted(sp_by.pop('R(DLR)'),
                         key=lambda p: pitcher_priority(p, 'R(DLR)', role='SP'))
        rp_full = sorted(rp_by.pop('R(DLR)'),
                         key=lambda p: pitcher_priority(p, 'R(DLR)', role='RP'))
        for k in range(n_dsl):
            sp_by[f'R(DLR){k+1}'] = sp_full[k*dsl_sp:(k+1)*dsl_sp]
            rp_by[f'R(DLR){k+1}'] = rp_full[k*dsl_rp:(k+1)*dsl_rp]

    # Tag roles + present each level's lists in priority order.
    rosters: dict[str, dict] = {}
    for lvl in sp_by.keys():
        sort_lvl = 'R(DLR)' if lvl.startswith('R(DLR)') else lvl
        sp_by[lvl].sort(key=lambda p: pitcher_priority(p, sort_lvl, role='SP'))
        rp_by[lvl].sort(key=lambda p: pitcher_priority(p, sort_lvl, role='RP'))
        for p in sp_by[lvl]:
            p['_role'] = 'SP'
        for p in rp_by[lvl]:
            p['_role'] = 'RP'
        if lvl.startswith('R(DLR)') and lvl != 'R(DLR)':
            sp_target = SP_PER_LEVEL['R(DLR)']
            rp_target = RP_PER_LEVEL['R(DLR)']
        else:
            sp_target = sp_slots[lvl]
            rp_target = rp_slots[lvl]
        rosters[lvl] = {
            'starters': sp_by[lvl],
            'bullpen': rp_by[lvl],
            'all': sp_by[lvl] + rp_by[lvl],
            'sp_target': sp_target,
            'rp_target': rp_target,
            'sign_lhp': lhp_shortfalls.get(lvl, 0),
        }

    from roster_common import assert_bot_invariant
    assert_bot_invariant(sp_by, role_label='SP')
    assert_bot_invariant(rp_by, role_label='RP')

    return rosters, overflow, flagged_players


if __name__ == '__main__':
    rosters, overflow, flagged = main()
    for lvl in rosters.keys():
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
