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

from roster_common import (
    LEVELS, MAX_AGE,
    age_lowest_level, service_lowest_level, dsl_eligible_lowest_level,
    _load_injured_names, _count_dsl_teams, is_player_injured,
)
# Tunable thresholds — see config.py "Pitcher cascade tunables" section
# for full provenance / rationale comments. Re-exported below where other
# modules (build_excel, streamlit_app) historically imported them from
# this module.
from config import (  # noqa: F401  (re-exports)
    SP_PER_LEVEL, RP_PER_LEVEL, PWOBA_MAX,
    LHP_LEVELS, LEFTY_MIN, LEFTY_TARGET, LEFTY_MAX, LEFTY_TARGET_MAX_COST,
    HP_PITCHER_MAX_AGE, HP_PITCHER_MAX_PWOBAP,
    PITCHER_SWINGMAN_PULLUP_ENABLED, PITCHER_SWINGMAN_PULLUP_MIN_WARP_DELTA,
)

PITCHERS_JSON = 'outputs/pitchers.json'

# Derived: SP+RP slots per level. Kept here (not in config) because it's
# trivially derived from the two SP/RP per-level dicts and only
# build_excel imports it. Now a {level: int} dict since SP_PER_LEVEL /
# RP_PER_LEVEL became per-level dicts in the 2026-05 expansion.
PITCHER_ROSTER_SIZE = {lvl: SP_PER_LEVEL[lvl] + RP_PER_LEVEL[lvl] for lvl in LEVELS}


def load_team_pitchers(org=None):
    """Load pitchers for a single org. Defaults to config.team_managed."""
    if org is None:
        from config import team_managed
        org = team_managed
    d = json.load(open(PITCHERS_JSON))
    return [r for r in d['rows'] if r['org'] == org]


def pitcher_priority(p, level=None):
    """Cascade-ordering key for pitchers. Lower = better (matches the
    pwOBA convention). Mirrors the hitter `priority` blend:
      - MLB: pure current pwOBA. Projection upside doesn't help an active-
        roster arm hold a slot — only current stuff matters.
      - Every other level: 70/30 current/projected. A young arm with real
        upside edges a same-pwOBA pitcher with no projection room, but the
        weight is small enough that a meaningful pwOBA gap dominates."""
    pwoba = p.get('pwOBA') if p.get('pwOBA') is not None else 1.0
    if level == 'MLB':
        return pwoba
    pwobap = p.get('pwOBAP') if p.get('pwOBAP') is not None else pwoba
    return 0.7 * pwoba + 0.3 * pwobap


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


def is_high_potential_pitcher(p):
    if p.get('minor') != 1:
        return False
    if p['age'] > HP_PITCHER_MAX_AGE:
        return False
    pwobap = p.get('pwOBAP')
    if pwobap is None:
        return False
    return pwobap <= HP_PITCHER_MAX_PWOBAP


def _cascade(pool, slots_for):
    """Initial placement at each pitcher's `_top`, then cascade-down: while a
    level holds more than `slots_for[lvl]`, pop the worst-blend pitcher and
    push to the next level (or to leftovers if age cap blocks).
    `slots_for` is a {level: int} dict so per-level capacities (R(DLR)
    × DSL count) can vary.

    Sort key combines a `_bot` cascadability flag with `pitcher_priority`
    so the cascade prefers demoting the WORST pitcher who CAN actually
    cascade. Mirrors the hitter R-11 refinement: R-09 over-punished
    most-mobile players (typically high-quality young prospects with
    wide `_bot`) by popping them BEFORE less-mobile but better-priority
    ones who could also cascade. R-11 just asks 'can you cascade?'
    then ranks by priority within each group.

    Sort ASC by `(_bot > level_idx, pitcher_priority)`:
      position 0 = stuck (can't cascade) + best pitcher (kept first)
      position -1 = cascadable + worst pitcher (popped first)
    Stuck players only get popped (to leftovers) once every cascadable
    has already been moved."""
    by_level = {lvl: [] for lvl in LEVELS}
    leftovers = []
    for p in pool:
        by_level[LEVELS[p['_top']]].append(p)

    def _sort_key_factory(lvl_idx, lvl_name):
        def _key(p):
            return (p['_bot'] > lvl_idx, pitcher_priority(p, lvl_name))
        return _key

    for lvl in LEVELS:
        by_level[lvl].sort(key=_sort_key_factory(LEVELS.index(lvl), lvl))
    for i, lvl in enumerate(LEVELS):
        while len(by_level[lvl]) > slots_for[lvl]:
            cascaded = by_level[lvl].pop()  # last = wide-bot + worst-pitcher
            next_idx = i + 1
            if next_idx <= cascaded['_bot'] and next_idx < len(LEVELS):
                nxt = LEVELS[next_idx]
                by_level[nxt].append(cascaded)
                by_level[nxt].sort(key=_sort_key_factory(next_idx, nxt))
            else:
                leftovers.append(cascaded)
    return by_level, leftovers


def is_lhp(p):
    """OOTP convention: throws == 2 → left, 1 → right. Returns False if the
    field is missing (treated as right-handed by default)."""
    return p.get('throws') == 2


def _eligible_for_promotion(p, i, want_lhp, allow_stretch):
    """Common eligibility filter for handedness-swap candidates. Returns
    True if `p` is the right hand AND can legally be promoted to level i
    (`_bot ≥ i`, `_top ≤ i` strict OR `_top == i+1` non-HP stretch)."""
    if is_lhp(p) != want_lhp:
        return False
    if i > p['_bot']:
        return False
    if p['_top'] <= i:
        return True
    if allow_stretch and p['_top'] == i + 1 and not is_high_potential_pitcher(p):
        return True
    return False


def _swap(by_level, lvl_top, drop_player, add_player, add_lvl):
    """Swap drop_player (at lvl_top) with add_player (at add_lvl). Both
    lists re-sorted by pitcher_priority at their respective level."""
    by_level[lvl_top].remove(drop_player)
    by_level[add_lvl].remove(add_player)
    by_level[lvl_top].append(add_player)
    by_level[add_lvl].append(drop_player)
    by_level[lvl_top].sort(key=lambda p: pitcher_priority(p, lvl_top))
    by_level[add_lvl].sort(key=lambda p: pitcher_priority(p, add_lvl))


def _try_handedness_swap(by_level, overflow, lvl, i, drop_pool,
                          want_lhp_promoted, allow_stretch_options=(False, True),
                          max_cost=None):
    """Try to make one handedness swap at level `lvl`. Searches BOTH lower
    levels and overflow for the best promoted candidate, picks the
    worst-priority drop candidate whose `_bot` allows them to land at the
    swap destination. Promotion sources:
      • from level j: classic 1-for-1 swap, drop goes to LEVELS[j].
      • from overflow: candidate joins the level, drop goes to overflow
        (no `_bot` check needed — overflow is "below all levels").
    Tries strict eligibility first, then `+1` stretch by default."""
    for allow_stretch in allow_stretch_options:
        # Build candidate pool from lower levels + overflow.
        by_level_cands = []
        for j in range(i + 1, len(LEVELS)):
            for p in by_level[LEVELS[j]]:
                if _eligible_for_promotion(p, i, want_lhp_promoted, allow_stretch):
                    by_level_cands.append((p, j))
        overflow_cands = [p for p in overflow
                          if _eligible_for_promotion(p, i, want_lhp_promoted, allow_stretch)]
        if not by_level_cands and not overflow_cands:
            continue

        # Pick best across both sources by priority at the receiving level.
        all_cands = [(p, ('lvl', j)) for p, j in by_level_cands] + \
                    [(p, ('overflow', None)) for p in overflow_cands]
        promoted, src = min(all_cands, key=lambda c: pitcher_priority(c[0], lvl))

        # Eligible drops: from-level swap requires `_bot >= j`; from-overflow
        # has no constraint (drop just goes to overflow).
        if src[0] == 'lvl':
            eligible = [p for p in drop_pool if p['_bot'] >= src[1]]
        else:
            eligible = list(drop_pool)
        if not eligible:
            continue

        worst = max(eligible, key=lambda p: pitcher_priority(p, lvl))
        if max_cost is not None:
            cost = pitcher_priority(promoted, lvl) - pitcher_priority(worst, lvl)
            if cost > max_cost:
                continue

        if src[0] == 'lvl':
            _swap(by_level, lvl, worst, promoted, LEVELS[src[1]])
        else:
            # From overflow: candidate joins lvl, dropped goes to overflow.
            by_level[lvl].remove(worst)
            by_level[lvl].append(promoted)
            by_level[lvl].sort(key=lambda p: pitcher_priority(p, lvl))
            overflow.remove(promoted)
            overflow.append(worst)
        return True
    return False


def _enforce_lhp_balance(by_level, overflow, slots_for):
    """Adjust MLB/AAA/AA bullpens so 2 ≤ LHP ≤ 4, with a soft target of 3.
    Iterates top-down so a demoted MLB RHP is visible to the AAA pass.
    Under-filled bullpens are skipped — shape pressure already exists.

    Returns `{level: lhp_shortfall}` — the number of bullpen slots left
    open at each level because no strict-eligible LHP could be found.
    Renderers use this to display "Sign LHP" placeholders for those slots
    rather than generic "Sign FA"."""
    shortfalls = {}
    for lvl in LHP_LEVELS:
        if lvl not in by_level:
            continue
        i = LEVELS.index(lvl)
        if len(by_level[lvl]) < slots_for[lvl]:
            continue

        # Hard MAX: drop worst LHP, promote best eligible RHP from below.
        # Stretch is fine here — we're trying to drop excess LHP, RHP
        # quality at the level isn't the user's concern.
        while True:
            lefties = [p for p in by_level[lvl] if is_lhp(p)]
            if len(lefties) <= LEFTY_MAX:
                break
            if not _try_handedness_swap(by_level, overflow, lvl, i, lefties, want_lhp_promoted=False):
                break

        # Hard MIN: drop worst RHP, promote best STRICT-eligible LHP from
        # below or overflow. No +1 stretch — if there isn't a real LHP at
        # this level's pwOBA threshold, leave the slot open (handled below).
        while True:
            lefties = [p for p in by_level[lvl] if is_lhp(p)]
            if len(lefties) >= LEFTY_MIN:
                break
            righties = [p for p in by_level[lvl] if not is_lhp(p)]
            if not righties:
                break
            if not _try_handedness_swap(
                by_level, overflow, lvl, i, righties, want_lhp_promoted=True,
                allow_stretch_options=(False,),
            ):
                break

        # If MIN still unmet, drop the worst-priority RHP for each missing
        # LHP slot — they cascade DOWN one level (or overflow if their
        # `_bot` doesn't allow). The bullpen at this level runs short
        # until the user signs a free-agent LHP.
        n_lefties = sum(1 for p in by_level[lvl] if is_lhp(p))
        short = max(0, LEFTY_MIN - n_lefties)
        if short > 0:
            righties_sorted = sorted(
                [p for p in by_level[lvl] if not is_lhp(p)],
                key=lambda p: pitcher_priority(p, lvl),
            )
            next_idx = i + 1
            for _ in range(short):
                if not righties_sorted:
                    break
                worst = righties_sorted.pop()  # last is worst-priority
                by_level[lvl].remove(worst)
                if next_idx < len(LEVELS) and next_idx <= worst['_bot']:
                    by_level[LEVELS[next_idx]].append(worst)
                else:
                    overflow.append(worst)
            shortfalls[lvl] = short

        # Soft TARGET: chase a 3rd LHP only if the swap costs ≤ threshold,
        # and only via strict eligibility (no +1 stretch — a "nice to have"
        # 3rd lefty isn't worth promoting an unready arm).
        while True:
            lefties = [p for p in by_level[lvl] if is_lhp(p)]
            if len(lefties) >= LEFTY_TARGET:
                break
            righties = [p for p in by_level[lvl] if not is_lhp(p)]
            if not righties:
                break
            if not _try_handedness_swap(
                by_level, overflow, lvl, i, righties, want_lhp_promoted=True,
                allow_stretch_options=(False,), max_cost=LEFTY_TARGET_MAX_COST,
            ):
                break
    return shortfalls


def _pull_up(by_level, slots_for):
    """Top-down fill in two passes per level. `slots_for` is a {level: int}
    dict.
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
        while len(by_level[lvl]) < slots_for[lvl]:
            best = None
            best_j = None
            for j in range(i + 1, len(LEVELS)):
                for p in by_level[LEVELS[j]]:
                    if i > p['_bot']:
                        continue
                    if p['_top'] > i:
                        continue
                    if best is None or pitcher_priority(p, lvl) < pitcher_priority(best, lvl):
                        best, best_j = p, j
            if best is None:
                break
            by_level[LEVELS[best_j]].remove(best)
            by_level[lvl].append(best)
            by_level[lvl].sort(key=lambda p: pitcher_priority(p, lvl))

        # Pass 2: non-HP +1 stretch (_top == i + 1)
        while len(by_level[lvl]) < slots_for[lvl]:
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
                    if best is None or pitcher_priority(p, lvl) < pitcher_priority(best, lvl):
                        best, best_j = p, j
            if best is None:
                break
            by_level[LEVELS[best_j]].remove(best)
            by_level[lvl].append(best)
            by_level[lvl].sort(key=lambda p: pitcher_priority(p, lvl))


def _push_down_from_overflow(by_level, slots_for, overflow, role):
    """Release-pool push-down for pitcher staffs: any level still under
    target after cascade + pull-up gets filled from `overflow`, ignoring
    `_top` (pitcher analogue of build_system.py's hitter PASS 3).
    Respects only the OOTP hard rule (`_bot`: age + service + DSL nation).
    `role` is 'SP' or 'RP' so the right viability check applies.

    Why no `_top` constraint: at this stage we've already exhausted all
    in-tier and +1-stretch candidates. The remaining gap is between
    "leave the slot empty" and "fill with a sub-threshold release-pool
    arm". An empty slot is worse for org-depth display.
    """
    viability = {'SP': is_sp_viable, 'RP': is_rp_viable}[role]
    for i, lvl in enumerate(LEVELS):
        target = slots_for.get(lvl, 0)
        while len(by_level[lvl]) < target:
            candidates = [
                p for p in overflow
                if viability(p)
                and p.get('_bot') is not None
                and i <= p['_bot']
            ]
            if not candidates:
                break
            best = min(candidates, key=lambda p: pitcher_priority(p, lvl))
            overflow.remove(best)
            by_level[lvl].append(best)
            by_level[lvl].sort(key=lambda p: pitcher_priority(p, lvl))


def _swingman_pullup(sp_by, rp_by, rp_slots, overflow):
    """OPT-IN R-03 implementation: pull non-MLB SP-viable non-HP arms up
    to the MLB bullpen if their rp_warP exceeds the worst MLB RP's
    rp_warP by at least PITCHER_SWINGMAN_PULLUP_MIN_WARP_DELTA.

    OFF by default (PITCHER_SWINGMAN_PULLUP_ENABLED in config). The
    cascade-only baseline is calibrated; this is a "developmental
    upside" lever that biases toward calling up AAA SPs for MLB long-
    relief auditions. Trade-off: most candidates are net-negative in
    current-year WAR but net-positive in potential WAR.

    Constraints honoured:
      - Skips HP candidates (HP enforcement owns those slots).
      - Skips swaps that would push MLB LHP count outside [LEFTY_MIN,
        LEFTY_MAX] — handedness balance takes priority.
      - Demoted MLB RP cascades to AAA bullpen (or further down to
        first level <= their _bot, or overflow if blocked).

    Side effect: candidate's old SP slot at AAA / lower is left empty
    (not auto-backfilled). Real-world equivalent is signing a FA / new
    call-up to fill that AAA rotation slot. Acceptable because the
    point of the call-up is the MLB upgrade.

    Mutates sp_by, rp_by, overflow in place. No-op when toggle is OFF."""
    if not PITCHER_SWINGMAN_PULLUP_ENABLED:
        return
    if 'MLB' not in rp_by or not rp_by['MLB']:
        return

    for _iter in range(20):  # Bound to prevent any pathological infinite loop
        changed = False
        mlb_pen = rp_by['MLB']
        # Worst MLB RP by rp_warP (skip None to avoid "lowest" being a
        # data-anomaly entry; if everyone's rp_warP is None, give up).
        pen_with_war = [p for p in mlb_pen if p.get('rp_warP') is not None]
        if not pen_with_war:
            break
        worst_rp = min(pen_with_war, key=lambda p: p['rp_warP'])
        worst_war = worst_rp['rp_warP']

        # Best non-MLB SP-viable non-HP candidate by rp_warP, descending.
        cands = []
        for lvl, lst in sp_by.items():
            if lvl == 'MLB':
                continue
            for p in lst:
                if is_high_potential_pitcher(p):
                    continue
                if p.get('rp_warP') is None:
                    continue
                cands.append((p, lvl))
        if not cands:
            break
        cands.sort(key=lambda c: -c[0]['rp_warP'])

        # Try candidates in order; first valid swap wins this iteration.
        for cand, cand_lvl in cands:
            delta = cand['rp_warP'] - worst_war
            if delta < PITCHER_SWINGMAN_PULLUP_MIN_WARP_DELTA:
                break  # Sorted descending — no further candidate qualifies

            # Validate LHP balance post-swap.
            cand_is_lhp = (cand.get('throws') == 2)
            inc_is_lhp = (worst_rp.get('throws') == 2)
            cur_lhp = sum(1 for p in mlb_pen if p.get('throws') == 2)
            new_lhp = cur_lhp - (1 if inc_is_lhp else 0) + (1 if cand_is_lhp else 0)
            if not (LEFTY_MIN <= new_lhp <= LEFTY_MAX):
                continue  # Would break balance; try next candidate

            # Execute swap.
            sp_by[cand_lvl].remove(cand)
            mlb_pen.remove(worst_rp)
            mlb_pen.append(cand)

            # Demoted RP cascades to AAA bullpen if their _bot allows;
            # otherwise walk further down; otherwise overflow.
            target_idx = LEVELS.index('AAA')
            bot = worst_rp.get('_bot', len(LEVELS) - 1)
            if target_idx > bot:
                # AAA below their floor — find first eligible deeper level.
                target_idx = None
                for k in range(LEVELS.index('AAA') + 1, len(LEVELS)):
                    if k <= bot:
                        target_idx = k
                        break
            if target_idx is None:
                overflow.append(worst_rp)
            else:
                target_lvl = LEVELS[target_idx]
                if target_lvl in rp_by:
                    rp_by[target_lvl].append(worst_rp)
                else:
                    overflow.append(worst_rp)

            # Rebalance: cascade any over-cap level (the demoted RP just
            # joined AAA / lower, possibly pushing it over). Mirrors the
            # Step-4c rebalance pass in main(). Walk top-down popping
            # the worst-priority RP to the next level (or overflow).
            for i, lvl in enumerate(LEVELS):
                if lvl not in rp_by:
                    continue
                while len(rp_by[lvl]) > rp_slots.get(lvl, RP_PER_LEVEL.get(lvl, 8)):
                    worst = max(rp_by[lvl], key=lambda p: pitcher_priority(p, lvl))
                    rp_by[lvl].remove(worst)
                    next_idx = i + 1
                    if (next_idx < len(LEVELS)
                            and next_idx <= worst.get('_bot', len(LEVELS) - 1)
                            and LEVELS[next_idx] in rp_by):
                        rp_by[LEVELS[next_idx]].append(worst)
                    else:
                        overflow.append(worst)

            changed = True
            break  # Re-evaluate worst RP and candidate pool from scratch

        if not changed:
            break


def _enforce_hp_pitchers(by_level, slots_for, pool_names, overflow):
    """For HP pitchers in overflow, place them on a roster by displacing the
    worst-priority non-HP at the HP's natural target level. Mirrors the
    hitter Step 3 HP enforcement (`build_system.py:880+`).

    The cascade alone can leave HPs in overflow when their level is full of
    non-HPs whose current pwOBA is better — but the HP's projection is the
    point of keeping them on the roster. Without enforcement, a young arm
    like a 19yo HP with pwOBA .47 / pwOBAP .32 ends up cut despite being
    a real future contributor.

    Try levels from `_top` down to `_bot`. At each level, take the open slot
    if any; otherwise displace the worst non-HP if the swap is worth it
    (HP's projection gain >= non-HP's current loss, in pwOBA terms where
    LOWER is better). If no level has a viable swap, the HP stays in
    overflow but is tagged with `_force_start` for downstream display.

    `pool_names` scopes the enforcement to one role (SP-pool or RP-pool).
    Mutates `by_level` and `overflow` in place. Best HPs (lowest pwOBAP)
    are processed first so they get first claim on swap targets."""
    hps = sorted(
        [p for p in list(overflow)
         if p['name'] in pool_names and is_high_potential_pitcher(p)],
        key=lambda p: (p.get('pwOBAP') or 1.0)
    )
    for hp in hps:
        for idx in range(hp['_top'], hp['_bot'] + 1):
            lvl = LEVELS[idx]
            if lvl not in by_level:
                continue
            cap = slots_for.get(lvl, 0)
            if len(by_level[lvl]) < cap:
                # Open slot — just place the HP, no displacement needed.
                by_level[lvl].append(hp)
                overflow.remove(hp)
                by_level[lvl].sort(key=lambda p: pitcher_priority(p, lvl))
                hp['_force_start'] = lvl
                break
            # Level is full — try to swap with worst non-HP at this level.
            non_hps = [p for p in by_level[lvl] if not is_high_potential_pitcher(p)]
            if not non_hps:
                continue
            worst = max(non_hps, key=lambda p: pitcher_priority(p, lvl))
            current_loss = (hp.get('pwOBA') or 1.0) - (worst.get('pwOBA') or 1.0)
            potential_gain = (worst.get('pwOBAP') or 1.0) - (hp.get('pwOBAP') or 1.0)
            if potential_gain >= current_loss:
                by_level[lvl].remove(worst)
                by_level[lvl].append(hp)
                overflow.remove(hp)
                overflow.append(worst)
                by_level[lvl].sort(key=lambda p: pitcher_priority(p, lvl))
                hp['_force_start'] = lvl
                break


def main(org=None):
    laa = load_team_pitchers(org)
    for p in laa:
        p.pop('_role', None)

    # Step 0: filter international complex + injured-list (see injured.txt)
    laa = [p for p in laa if not (p.get('minor') == 0 and p['age'] < 20)]
    injured = _load_injured_names()
    flagged_players = [p for p in laa if is_player_injured(p, injured)]
    laa = [p for p in laa if not is_player_injured(p, injured)]

    # Step 1: eligibility window. `_top` = current pwOBA ceiling only;
    # there's no age-based extra cap (see PITCHER_AGE_TOP removal note).
    # `_bot` combines age and service-time floors — the more restrictive
    # wins, so a vet who's burned through A+ service time can't be sent
    # down there even if young enough.
    overflow = []
    valid = []
    for p in laa:
        p['_top'] = pwoba_top_level(p)
        p['_bot'] = min(age_lowest_level(p), service_lowest_level(p),
                        dsl_eligible_lowest_level(p))
        if p['_top'] > p['_bot']:
            overflow.append(p)
        else:
            valid.append(p)

    # Per-org pitcher capacities. R(DLR) scales by DSL team count (each
    # DSL team has its own staff = SP_PER_LEVEL[R(DLR)] + RP_PER_LEVEL[R(DLR)]
    # slots). SP_PER_LEVEL / RP_PER_LEVEL are now per-level dicts, so each
    # level reads its own SP/RP capacity directly.
    sp_slots = {lvl: SP_PER_LEVEL[lvl] for lvl in LEVELS}
    rp_slots = {lvl: RP_PER_LEVEL[lvl] for lvl in LEVELS}
    n_dsl = max(1, _count_dsl_teams(org))
    sp_slots['R(DLR)'] = SP_PER_LEVEL['R(DLR)'] * n_dsl
    rp_slots['R(DLR)'] = RP_PER_LEVEL['R(DLR)'] * n_dsl

    # Step 2-3: SP cascade + pull-up
    sp_pool = [p for p in valid if is_sp_viable(p)]
    sp_by, _sp_leftover = _cascade(sp_pool, sp_slots)
    _pull_up(sp_by, sp_slots)
    sp_assigned = {p['name'] for lvl in LEVELS for p in sp_by[lvl]}

    # Step 4: RP cascade + pull-up
    rp_pool = [p for p in valid if is_rp_viable(p) and p['name'] not in sp_assigned]
    rp_by, rp_leftover = _cascade(rp_pool, rp_slots)
    _pull_up(rp_by, rp_slots)

    # Step 4a: opt-in swingman pull-up (R-03). No-op when toggle is OFF.
    # Runs BEFORE LHP balance so any AAA imbalance the swingman swap
    # creates (cascading the demoted RP can push out an LHP) is then
    # repaired by the LHP balance pass at the next step.
    _swingman_pullup(sp_by, rp_by, rp_slots, overflow)

    # Step 4b: bullpen handedness balance — MLB / AAA / AA only.
    # Hard MIN uses strict eligibility only; if no qualified LHP exists,
    # the slot is left open and tagged in `lhp_shortfalls` so the renderer
    # can show "Sign LHP" instead of generic "Sign FA".
    lhp_shortfalls = _enforce_lhp_balance(rp_by, overflow, rp_slots)

    # Step 4c: rebalance any level the LHP shortfall pushed over capacity.
    # When MLB or AAA drops a RHP to make room for "Sign LHP" placeholders,
    # the demoted RHP cascades to the next level — which can then run over
    # its rp_target. Trim from the top down by popping the worst-priority
    # RP to the next level (or overflow if their _bot doesn't allow).
    for i, lvl in enumerate(LEVELS):
        if lvl not in rp_by:
            continue
        while len(rp_by[lvl]) > rp_slots.get(lvl, RP_PER_LEVEL.get(lvl, 8)):
            worst = max(rp_by[lvl], key=lambda p: pitcher_priority(p, lvl))
            rp_by[lvl].remove(worst)
            next_idx = i + 1
            if next_idx < len(LEVELS) and next_idx <= worst['_bot']:
                rp_by[LEVELS[next_idx]].append(worst)
            else:
                overflow.append(worst)

    rp_assigned = {p['name'] for lvl in LEVELS for p in rp_by[lvl]}

    # Step 5: overflow — collect anyone not placed by SP or RP cascade.
    overflow.extend(rp_leftover)
    overflow_names = {p['name'] for p in overflow}
    for p in valid:
        if (p['name'] not in sp_assigned
                and p['name'] not in rp_assigned
                and p['name'] not in overflow_names):
            overflow.append(p)
            overflow_names.add(p['name'])

    # Step 5a: HP enforcement. Mirrors the hitter Step 3. The cascade alone
    # can drop a high-potential prospect into overflow when their _bot level
    # is full of non-HPs with better current pwOBA — but the HP's projection
    # is the reason to keep them around. Run AFTER Step 5 so it can see
    # everyone who didn't make a roster, including SP cascade leftovers.
    # Per-role (SP separately from RP) so an HP SP doesn't get matched
    # against an RP slot.
    sp_pool_names = {p['name'] for p in sp_pool}
    rp_pool_names = {p['name'] for p in rp_pool}
    _enforce_hp_pitchers(sp_by, sp_slots, sp_pool_names, overflow)
    _enforce_hp_pitchers(rp_by, rp_slots, rp_pool_names, overflow)

    # Step 5a.1: release-pool push-down. Any SP / RP slot still under
    # target after cascade + pull-up + HP enforcement gets filled from
    # `overflow`, ignoring `_top` and respecting only `_bot`. Mirrors
    # the hitter Step 3.6 PASS 3. Run BEFORE the R(DLR) split so any
    # released arms reach R(DLR) before chunking into sub-teams.
    _push_down_from_overflow(sp_by, sp_slots, overflow, role='SP')
    _push_down_from_overflow(rp_by, rp_slots, overflow, role='RP')

    # Step 5a.2: re-enforce LHP balance. The push-down can fill an
    # LHP-reserved bullpen slot with a non-LHP (push-down sees only
    # `_bot`, not handedness), undoing Step 4b's work. Re-run the LHP
    # balance + over-cap rebalance to restore the invariant — any
    # slots that genuinely have no LHP filler available end up tagged
    # `sign_lhp` again rather than silently filled by a RHP.
    lhp_shortfalls = _enforce_lhp_balance(rp_by, overflow, rp_slots)
    for i, lvl in enumerate(LEVELS):
        if lvl not in rp_by:
            continue
        while len(rp_by[lvl]) > rp_slots.get(lvl, RP_PER_LEVEL.get(lvl, 8)):
            worst = max(rp_by[lvl], key=lambda p: pitcher_priority(p, lvl))
            rp_by[lvl].remove(worst)
            next_idx = i + 1
            if next_idx < len(LEVELS) and next_idx <= worst['_bot']:
                rp_by[LEVELS[next_idx]].append(worst)
            else:
                overflow.append(worst)

    # NOTE: Step 5a.3 (two-way pin) was retired in R-10. Two-way pitchers
    # are now treated as pure pitchers in the cascade — their position=1
    # OOTP designation is the primary role, and their bat is informational.
    # The previous pin promoted marginal-MLB pitchers (e.g. BOS Tolle
    # pwOBA=.337) over competitively-better non-HP non-two-way arms
    # (e.g. Bello pwOBA=.322); a sync to the better-skill level
    # over-rode fair cascade competition. With the pin gone, two-way
    # pitchers cascade naturally per their pitcher_priority and
    # `is_two_way` survives only as a display flag (e.g. show wOBAP
    # as a badge on the pitcher view).

    # Step 5b: split R(DLR) into n_dsl sub-teams (best, …, rest) by
    # pitcher_priority blend. Each DSL affiliate gets its own staff:
    # SP_PER_LEVEL['R(DLR)'] rotation + RP_PER_LEVEL['R(DLR)'] bullpen.
    # For n_dsl == 1 this is a no-op and the single 'R(DLR)' key is preserved.
    if n_dsl >= 2 and 'R(DLR)' in sp_by:
        dsl_sp = SP_PER_LEVEL['R(DLR)']
        dsl_rp = RP_PER_LEVEL['R(DLR)']
        sp_full = sorted(sp_by.pop('R(DLR)'), key=lambda p: pitcher_priority(p, 'R(DLR)'))
        rp_full = sorted(rp_by.pop('R(DLR)'), key=lambda p: pitcher_priority(p, 'R(DLR)'))
        for k in range(n_dsl):
            sp_by[f'R(DLR){k+1}'] = sp_full[k*dsl_sp:(k+1)*dsl_sp]
            rp_by[f'R(DLR){k+1}'] = rp_full[k*dsl_rp:(k+1)*dsl_rp]

    # Tag roles + present each level's lists in blend order (best first).
    # Iterate the actual keys (not LEVELS) so the R(DLR) split is preserved.
    rosters = {}
    for lvl in sp_by.keys():
        # R(DLR) sub-team keys (R(DLR)1 etc.) get the same priority blend
        # as the base R(DLR) level — collapse the suffix for the blend lookup.
        sort_lvl = 'R(DLR)' if lvl.startswith('R(DLR)') else lvl
        sp_by[lvl].sort(key=lambda p: pitcher_priority(p, sort_lvl))
        rp_by[lvl].sort(key=lambda p: pitcher_priority(p, sort_lvl))
        for p in sp_by[lvl]:
            p['_role'] = 'SP'
        for p in rp_by[lvl]:
            p['_role'] = 'RP'
        # For R(DLR) sub-teams the per-team capacity is the standard
        # SP_PER_LEVEL['R(DLR)'] / RP_PER_LEVEL['R(DLR)']; for un-split
        # levels we use the slots_for value (already accounts for any
        # scaling).
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
            # Number of bullpen slots intentionally left open because no
            # strict-eligible LHP could fill them. Renderers show these as
            # "Sign LHP" (vs generic "Sign FA"). Always 0 for non-MLB/AAA/AA.
            'sign_lhp': lhp_shortfalls.get(lvl, 0),
        }

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
