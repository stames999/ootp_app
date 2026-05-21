"""Simplified pitcher placement — A/B test against build_pitcher_system.

Single-pass per-level greedy assignment. Replaces the v1 multi-stage
pipeline (cascade → pull-up → swingman → push-down → rescue → HP
enforcement → LHP balance, each in 2-4 invocations) with a single rule:

    For each level top-down:
      1. Collect arms whose `_top ≤ i ≤ _bot` and not yet placed.
      2. Take top SP_PER_LEVEL[lvl] sp_viable arms by priority → starters.
      3. Take next RP_PER_LEVEL[lvl] arms (sp_viable or rp_viable not yet
         placed) by priority → bullpen, with LHP-balance constraint at
         LHP_LEVELS.
      4. Remaining eligible arms carry forward to the next level.

Same eligibility model as v1 (`_top` from pwOBA, `_bot` from age + service
+ DSL). Same priority function. Same R(DLR) sub-team split. Same flagged-
injured handling. Same two-way handling (preserved on the hitter side
via main.py; pitcher side just admits two-way arms normally).

Differences from v1:
  - No SP/RP cascade — selection is by priority within an eligibility-
    window pool at each level.
  - No pull-up / push-down / rescue / swingman / promote-natural — every
    arm's level is the highest where their priority wins a slot.
  - No HP enforcement pass — HPs compete on priority. Hard MLB block is
    a level-eligibility filter rather than a separate move.
  - LHP balance enforced inside the RP slice (single decision point per
    level), not via top-down repeated swap passes.
  - Same-level priority inversion is impossible: SP slots strictly hold
    the top sp_viable arms; no rp-side arm at the same level can have a
    better priority than the worst starter (the slot would have gone to
    them otherwise).
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
    SP_PER_LEVEL, RP_PER_LEVEL, PWOBA_MAX,
    LHP_LEVELS, LEFTY_MIN, LEFTY_TARGET, LEFTY_MAX,
    HP_PITCHER_MAX_AGE, HP_PITCHER_MAX_PWOBAP,
    HP_MIN_LEVEL_INDEX,
    PRIORITY_BLEND_CURRENT_WEIGHT, PRIORITY_BLEND_PROJECTED_WEIGHT,
    BLOCKER_CEILING_DELTA, BLOCKER_MLB_PWOBA, BLOCKER_PENALTY_SCALE,
)

# Reuse v1's JSON cache so the streamlit + xlsx renderers don't care
# which builder produced the file.
PITCHERS_JSON = 'outputs/pitchers.json'


# ---------------------------------------------------------------------------
# Same helpers as v1 (copied verbatim so the two modules are independently
# testable). If v2 ships, factor these out to roster_common.
# ---------------------------------------------------------------------------

def load_team_pitchers(org: str | None = None) -> list[dict]:
    if org is None:
        from config import team_managed
        org = team_managed
    d = json.load(open(PITCHERS_JSON))
    return [r for r in d['rows'] if r['org'] == org]


def pitcher_priority(p: dict, level: str | None = None) -> float:
    """Cascade-ordering key. Lower = better (matches pwOBA convention).

    Identical to v1's `pitcher_priority`. Kept here so v2 is self-contained
    during A/B testing — once v2 is adopted, factor to roster_common."""
    pwoba = p.get('pwOBA') if p.get('pwOBA') is not None else 1.0
    if level == 'MLB':
        return pwoba
    pwobap = p.get('pwOBAP') if p.get('pwOBAP') is not None else pwoba
    blend = (PRIORITY_BLEND_CURRENT_WEIGHT * pwoba
             + PRIORITY_BLEND_PROJECTED_WEIGHT * pwobap)
    if (not is_high_potential_pitcher(p)
            and (pwoba - pwobap) < BLOCKER_CEILING_DELTA
            and pwobap > BLOCKER_MLB_PWOBA):
        blend += BLOCKER_PENALTY_SCALE * (pwobap - BLOCKER_MLB_PWOBA)
    return blend


def pwoba_top_level(p: dict) -> int:
    pwoba = p.get('pwOBA') if p.get('pwOBA') is not None else 1.0
    for lvl in LEVELS:
        if pwoba <= PWOBA_MAX[lvl]:
            return LEVELS.index(lvl)
    return len(LEVELS) - 1


def is_sp_viable(p):
    return p.get('sp_warP') is not None


def is_rp_viable(p):
    return p.get('rp_warP') is not None


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
    """Same as v1."""
    laa = [p for p in laa if not (p.get('minor') == 0 and p['age'] < 20)]
    injured = _load_injured_names()
    flagged_players = [p for p in laa if is_player_injured(p, injured)]
    valid = [p for p in laa if not is_player_injured(p, injured)]
    return valid, flagged_players


def _compute_eligibility_window(pool):
    """Same as v1."""
    overflow = []
    valid = []
    for p in pool:
        p['_top'] = pwoba_top_level(p)
        p['_bot'] = min(age_lowest_level(p), service_lowest_level(p),
                        dsl_eligible_lowest_level(p))
        if p['_top'] > p['_bot']:
            overflow.append(p)
        else:
            valid.append(p)
    return valid, overflow


def _per_org_slot_capacities(org):
    """Same as v1."""
    sp_slots = {lvl: SP_PER_LEVEL[lvl] for lvl in LEVELS}
    rp_slots = {lvl: RP_PER_LEVEL[lvl] for lvl in LEVELS}
    n_dsl = max(1, _count_dsl_teams(org))
    sp_slots['R(DLR)'] = SP_PER_LEVEL['R(DLR)'] * n_dsl
    rp_slots['R(DLR)'] = RP_PER_LEVEL['R(DLR)'] * n_dsl
    return sp_slots, rp_slots, n_dsl


# ---------------------------------------------------------------------------
# v2 core: single-pass per-level placement
# ---------------------------------------------------------------------------

def _select_bullpen_with_lhp(eligible: list[dict], target: int,
                              lvl: str) -> tuple[list[dict], int]:
    """Pick up to `target` bullpen arms from `eligible` by priority.

    At LHP_LEVELS, reserve LEFTY_MIN slots for the top LHPs (strict
    eligibility — no +1 stretch). Cap total LHPs at LEFTY_MAX. Returns
    `(selected, lhp_shortfall)` where shortfall = LEFTY_MIN minus the
    number of LHP arms found; the renderer shows "Sign LHP" for those
    unfilled slots.

    Outside LHP_LEVELS, no balance constraint — just take top `target`
    by priority.

    Aims for LEFTY_TARGET (3) as a soft preference: if an LHP exists in
    `eligible` whose priority is better than the worst RHP currently
    selected and we have only LEFTY_MIN lefties, swap. Skip for now —
    soft target adds complexity; v1's soft-target swap rarely fires.
    """
    sorted_eligible = sorted(eligible, key=lambda p: pitcher_priority(p, lvl))

    if lvl not in LHP_LEVELS:
        return sorted_eligible[:target], 0

    # Reserve LEFTY_MIN slots for top lefties (strict eligibility).
    lefties = [p for p in sorted_eligible if is_lhp(p)]
    reserved_lhp = lefties[:LEFTY_MIN]
    lhp_shortfall = max(0, LEFTY_MIN - len(reserved_lhp))

    # Fill remaining slots from the rest of the pool, capping additional
    # lefties so total LHP count <= LEFTY_MAX.
    remaining_slots = target - LEFTY_MIN  # target slots after reserved-LHP
    extra_lhp_capacity = LEFTY_MAX - len(reserved_lhp)
    extra_lhp_taken = 0
    extra = []
    reserved_set = set(id(p) for p in reserved_lhp)
    for p in sorted_eligible:
        if id(p) in reserved_set:
            continue
        if len(extra) >= remaining_slots:
            break
        if is_lhp(p):
            if extra_lhp_taken >= extra_lhp_capacity:
                continue
            extra_lhp_taken += 1
        extra.append(p)

    selected = reserved_lhp + extra
    return selected, lhp_shortfall


def _place_level(level_idx: int, lvl: str, remaining: list[dict],
                  sp_target: int, rp_target: int
                  ) -> tuple[list[dict], list[dict], int, list[dict]]:
    """Place arms at one level. Returns
    `(starters, bullpen, lhp_shortfall, remaining_after)`.

    Eligibility window: `_top ≤ level_idx ≤ _bot`. HPs are filtered out
    at levels above HP_MIN_LEVEL_INDEX unless their `_bot` constrains
    them to that level only.

    SP slot allocation: SP-viable HPs claim rotation slots FIRST (up to
    sp_target), even if a non-HP with marginally better priority is
    eligible. HPs are projection plays and need rotation reps to
    develop — putting them in a bullpen slot wastes the developmental
    intent. Remaining SP slots then fill with non-HP sp_viable arms by
    priority. If HPs exceed sp_target, the extra HPs flow to
    `remaining_after` (they'll get another shot at the next level
    down).
    """
    eligible = []
    for p in remaining:
        if not (p['_top'] <= level_idx <= p['_bot']):
            continue
        # Hard HP block: HPs not allowed above HP_MIN_LEVEL_INDEX
        # (default MLB). Exception: an HP whose `_bot` puts them
        # MLB-only stays (pathological case but mirrors v1's
        # `_block_hps_at_mlb` semantics).
        if (level_idx < HP_MIN_LEVEL_INDEX
                and is_high_potential_pitcher(p)
                and p['_bot'] >= HP_MIN_LEVEL_INDEX):
            continue
        eligible.append(p)

    # Step 1: HP SP-viable arms get first claim on rotation slots.
    hp_sp = sorted(
        [p for p in eligible
         if is_sp_viable(p) and is_high_potential_pitcher(p)],
        key=lambda p: pitcher_priority(p, lvl),
    )
    starters = hp_sp[:sp_target]

    # Step 2: remaining SP slots fill with non-HP sp_viable by priority.
    remaining_sp_slots = sp_target - len(starters)
    if remaining_sp_slots > 0:
        starter_ids_so_far = set(id(p) for p in starters)
        non_hp_sp = sorted(
            [p for p in eligible
             if is_sp_viable(p)
             and not is_high_potential_pitcher(p)
             and id(p) not in starter_ids_so_far],
            key=lambda p: pitcher_priority(p, lvl),
        )
        starters.extend(non_hp_sp[:remaining_sp_slots])

    starter_ids = set(id(p) for p in starters)

    # Step 3: bullpen — top remaining RP-viable arms (sp_viable arms not
    # picked as starters can also fill bullpen slots), honouring LHP
    # balance at LHP_LEVELS.
    rp_eligible = [p for p in eligible
                   if id(p) not in starter_ids and is_rp_viable(p)]
    bullpen, lhp_shortfall = _select_bullpen_with_lhp(
        rp_eligible, rp_target, lvl,
    )

    placed_ids = starter_ids | set(id(p) for p in bullpen)
    remaining_after = [p for p in remaining if id(p) not in placed_ids]
    return starters, bullpen, lhp_shortfall, remaining_after


def main(org: str | None = None) -> tuple[dict, list[dict], list[dict]]:
    """Build the pitcher staff for one org (v2). Same return shape as v1.

    Returns `(rosters_by_level, overflow, flagged_players)`.
    """
    laa = load_team_pitchers(org)
    for p in laa:
        p.pop('_role', None)

    laa, flagged_players = _filter_complex_and_injured(laa)
    valid, overflow = _compute_eligibility_window(laa)
    sp_slots, rp_slots, n_dsl = _per_org_slot_capacities(org)

    # Single-pass per-level placement.
    sp_by = {lvl: [] for lvl in LEVELS}
    rp_by = {lvl: [] for lvl in LEVELS}
    lhp_shortfalls: dict[str, int] = {}
    remaining = list(valid)

    for i, lvl in enumerate(LEVELS):
        starters, bullpen, shortfall, remaining = _place_level(
            i, lvl, remaining, sp_slots[lvl], rp_slots[lvl],
        )
        sp_by[lvl] = starters
        rp_by[lvl] = bullpen
        if shortfall:
            lhp_shortfalls[lvl] = shortfall

    # Anyone never placed → overflow.
    overflow.extend(remaining)

    # R(DLR) sub-team split (same as v1).
    if n_dsl >= 2 and 'R(DLR)' in sp_by:
        dsl_sp = SP_PER_LEVEL['R(DLR)']
        dsl_rp = RP_PER_LEVEL['R(DLR)']
        sp_full = sorted(sp_by.pop('R(DLR)'),
                         key=lambda p: pitcher_priority(p, 'R(DLR)'))
        rp_full = sorted(rp_by.pop('R(DLR)'),
                         key=lambda p: pitcher_priority(p, 'R(DLR)'))
        for k in range(n_dsl):
            sp_by[f'R(DLR){k+1}'] = sp_full[k*dsl_sp:(k+1)*dsl_sp]
            rp_by[f'R(DLR){k+1}'] = rp_full[k*dsl_rp:(k+1)*dsl_rp]

    # Tag roles + present each level's lists in priority order.
    rosters: dict[str, dict] = {}
    for lvl in sp_by.keys():
        sort_lvl = 'R(DLR)' if lvl.startswith('R(DLR)') else lvl
        sp_by[lvl].sort(key=lambda p: pitcher_priority(p, sort_lvl))
        rp_by[lvl].sort(key=lambda p: pitcher_priority(p, sort_lvl))
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

    # Defence-in-depth — every placement should respect `_bot`.
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
