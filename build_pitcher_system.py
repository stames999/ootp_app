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
from __future__ import annotations  # PEP 604 unions (`str | None`) — Python 3.9 (Streamlit Cloud) compat

import json

from roster_common import (
    LEVELS, MAX_AGE,
    age_lowest_level, service_lowest_level, dsl_eligible_lowest_level,
    _load_injured_names, _count_dsl_teams, is_player_injured,
    cascade as _shared_cascade,
    overflow_rebalance as _shared_overflow_rebalance,
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
    PITCHER_SWINGMAN_PRIORITY_MARGIN, DEVELOPMENTAL_MAX_AGE,
    HP_MIN_LEVEL_INDEX,
    PRIORITY_BLEND_CURRENT_WEIGHT, PRIORITY_BLEND_PROJECTED_WEIGHT,
    BLOCKER_CEILING_DELTA, BLOCKER_MLB_PWOBA, BLOCKER_PENALTY_SCALE,
)

PITCHERS_JSON = 'outputs/pitchers.json'

# Derived: SP+RP slots per level. Kept here (not in config) because it's
# trivially derived from the two SP/RP per-level dicts and only
# build_excel imports it. Now a {level: int} dict since SP_PER_LEVEL /
# RP_PER_LEVEL became per-level dicts in the 2026-05 expansion.
PITCHER_ROSTER_SIZE = {lvl: SP_PER_LEVEL[lvl] + RP_PER_LEVEL[lvl] for lvl in LEVELS}


def load_team_pitchers(org: str | None = None) -> list[dict]:
    """Load pitchers for a single org. Defaults to config.team_managed."""
    if org is None:
        from config import team_managed
        org = team_managed
    d = json.load(open(PITCHERS_JSON))
    return [r for r in d['rows'] if r['org'] == org]


def pitcher_priority(p: dict, level: str | None = None) -> float:
    """Cascade-ordering key for pitchers. Lower = better (matches the
    pwOBA convention). Mirrors the hitter `priority` blend:
      - MLB: pure current pwOBA. Projection upside doesn't help an active-
        roster arm hold a slot — only current stuff matters.
      - Every other level: 85/15 current/projected (R-30, was 70/30).
        Projection still nudges close-priority HPs up, but the weight is
        small enough that an arm with clearly-better current stuff keeps
        his slot. The earlier 70/30 mix was demoting solid org-depth arms
        (e.g. Armstrong .362/.362 → A) below HPs whose current pwOBA
        wasn't yet competitive (.368-.377 with .320-.338 projection).

    R-32 blocker penalty: a non-HP arm at his ceiling (pwOBA ≈ pwOBAP)
    whose ceiling is sub-MLB (pwOBAP > .345) blocks HPs at development
    levels while only contributing org-depth value. His priority gets
    penalised by `BLOCKER_PENALTY_SCALE * (pwOBAP − .345)` — distance
    from MLB-tier, scaled (default 0.5×). The scale preserves the
    "worse ceiling = harsher penalty" gradient while keeping the
    magnitude bounded so the penalty can't overwhelm natural priority
    gaps between fringe arms (the unscaled penalty grew to ~.030 for
    arms at pwOBAP .376-.380, large enough to release players whose
    raw pwOBA was actually better than the slot's worst held arm).
    Keeps the single-rule invariant from R-31 — the penalty is part of
    the priority blend, not a separate ranking rule."""
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


def _cascade(pool, slots_for, war_key=None):
    """Thin wrapper around `roster_common.cascade()` (R-33 consolidation).
    Kept as a module-local name so existing callers in this file stay
    readable. `war_key` is preserved for backwards-compat signature but
    unused since R-27.

    Cascade uses pitcher_priority (lower = better, matches the pwOBA
    convention) so no priority-inversion is needed. See the shared
    helper's docstring for the full algorithm + history."""
    del war_key  # legacy param, see docstring
    return _shared_cascade(pool, slots_for, pitcher_priority)


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
    # Hard HP block: HP pitchers can't be promoted above HP_MIN_LEVEL_INDEX
    # (defaults to AAA = 1, so MLB is blocked).
    if HP_MIN_LEVEL_INDEX > 0 and i < HP_MIN_LEVEL_INDEX and is_high_potential_pitcher(p):
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
                    # Hard HP block — HPs never pulled up above
                    # HP_MIN_LEVEL_INDEX (default 1 = AAA), so they
                    # can't backfill an MLB slot via the strict pull-up.
                    if (HP_MIN_LEVEL_INDEX > 0 and i < HP_MIN_LEVEL_INDEX
                            and is_high_potential_pitcher(p)):
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
    target after cascade + pull-up gets filled from `overflow` with arms
    whose `_top` already qualifies them for the level. Respects `_bot`
    (OOTP hard rule: age + service + DSL nation) AND `_top` (R-34 fix:
    don't push arms whose stuff is multiple levels below the slot up
    just to fill it).

    Pre-R-34 the push-down had no `_top` constraint — the original
    justification was "an empty slot is worse for org-depth display
    than a sub-threshold release-pool arm". After the R-34 swingman
    pull-up was enabled by default, AAA/AA SP slots got vacated more
    often, and the unlimited stretch was pulling deep-overflow arms
    (e.g. pwOBA .410, `_top=R`) up multiple levels into AAA SP. The
    user's call: an honest "Sign FA" empty-slot display beats showing
    a pitcher whose stuff structurally doesn't play at the level.

    `role` is 'SP' or 'RP' so the right viability check applies.
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
                and p.get('_top', i) <= i  # R-34: stuff must qualify for the level
            ]
            if not candidates:
                break
            best = min(candidates, key=lambda p: pitcher_priority(p, lvl))
            overflow.remove(best)
            by_level[lvl].append(best)
            by_level[lvl].sort(key=lambda p: pitcher_priority(p, lvl))


def _promote_natural_sps_from_rp(sp_by, rp_by, sp_slots):
    """Fill any under-target SP slot at level `lvl` with the best
    sp_viable arm currently in `rp_by[lvl]` whose `_top <= lvl_idx`
    (strict eligibility). Mutates `sp_by` and `rp_by` in place.

    Why this exists: SP cascade compression can dump natural-_top arms
    into the RP pool. Concrete case (CWS Dynasty, mid-2026): cascade
    fills R SP with A+/A arms that cascaded down (priority .380-.395),
    pushing the R-natural arms (Wynk / Banks / Darden, priority
    .397-.400) out to overflow. Those arms enter RP cascade and land
    at R bullpen. Then swingman pull-up moves the cascaded-in A+/A
    arms OUT of R SP into higher-level bullpens — leaving R SP empty.
    Without this pass, the re-run SP pull-up fills the vacated R SP
    slots via +1 stretch from R(DLR) (Suarez / Marte / Rodriguez at
    priority .416-.435), even though *better-priority* natural-_top
    arms are sitting one level over in `rp_by[R]`.

    Runs between `_swingman_pullup` and the re-run `_pull_up` so the
    natural arms get first claim on vacated slots; stretches only
    apply after natural fits are exhausted. Keeps the single-rule
    invariant (R-31) within each level.
    """
    for i, lvl in enumerate(LEVELS):
        target = sp_slots.get(lvl, 0)
        while len(sp_by.get(lvl, [])) < target:
            candidates = [
                p for p in rp_by.get(lvl, [])
                if is_sp_viable(p)
                and p.get('_top', i + 1) <= i
            ]
            if not candidates:
                break
            best = min(candidates, key=lambda p: pitcher_priority(p, lvl))
            rp_by[lvl].remove(best)
            sp_by.setdefault(lvl, []).append(best)
            sp_by[lvl].sort(key=lambda p: pitcher_priority(p, lvl))


def _swingman_pullup(sp_by, rp_by, rp_slots, overflow):
    """Pull non-MLB SP-viable non-HP arms up to the MLB bullpen if their
    MLB pitcher_priority (= pure current pwOBA per the priority
    function's MLB branch) is strictly better than the worst MLB RP.
    Catches the case of an SP cascaded out of the MLB rotation whose
    current stuff would still beat the fringe MLB bullpen arms — e.g.
    older SPs whose projection is muted but whose pwOBA is genuinely
    MLB-bullpen-grade.

    ON by default since R-34 (was opt-in pre-R-34). The original
    OFF-by-default concern was that the rp_warP-projection gate biased
    toward developmental upside over current-year roster value; R-34
    switched to pitcher_priority (current-stuff at MLB) and the bias
    is gone. PITCHER_SWINGMAN_PULLUP_MIN_WARP_DELTA is now unused.

    Constraints honoured:
      - Skips HP candidates (HP enforcement owns those slots; HPs are
        developmental SPs by intent, not bullpen filler).
      - Skips swaps that would push MLB LHP count outside [LEFTY_MIN,
        LEFTY_MAX] — handedness balance takes priority.
      - Demoted MLB RP cascades to AAA bullpen (or further down to
        first level <= their _bot, or overflow if blocked).

    Side effect: candidate's old SP slot at AAA / lower is left empty
    (not auto-backfilled). Real-world equivalent is signing a FA / new
    call-up to fill that AAA rotation slot. Acceptable because the
    point of the call-up is the MLB upgrade.

    R-34 generalisation: this now runs for every level's bullpen
    (MLB / AAA / AA / A+ / A — R / R(DLR) are developmental tiers
    and excluded). The original MLB-only behaviour was a special
    case; the same logic applies anywhere a cascaded-down SP would
    beat the worst RP at a higher level. Catches cases like
    Jonathan Cannon (CWS, pwOBA .352, _top=AAA) cascading from
    AAA SP -> AA SP -> A+ SP because each rotation was full with
    marginally-better arms, when his priority trivially beats the
    worst RP at AAA / AA / A+.

    Mutates sp_by, rp_by, overflow in place. No-op when toggle is OFF."""
    if not PITCHER_SWINGMAN_PULLUP_ENABLED:
        return

    target_levels = ['MLB', 'AAA', 'AA', 'A+', 'A']
    for target_lvl in target_levels:
        if target_lvl not in rp_by or not rp_by[target_lvl]:
            continue
        target_idx = LEVELS.index(target_lvl)

        for _iter in range(20):  # bound per-level iterations
            changed = False
            target_pen = rp_by[target_lvl]
            if not target_pen:
                break
            worst_rp = max(target_pen, key=lambda p: pitcher_priority(p, target_lvl))
            worst_pri = pitcher_priority(worst_rp, target_lvl)

            # Best SP-viable non-HP non-developmental candidate from BELOW
            # target_lvl, sorted ASC by pitcher_priority at the target level
            # (lowest = best stuff).
            #
            # "Developmental" gate (R-34): exclude arms whose pwOBAP is
            # MLB-tier (<= BLOCKER_MLB_PWOBA = .345) AND who still have
            # development runway (age <= DEVELOPMENTAL_MAX_AGE = 27).
            # Both conditions must hold — an older arm (e.g. Fedde at
            # 33 with pwOBAP .344) has theoretical projection but no
            # real runway and shouldn't be stranded as an AAA SP.
            # Same shape as HP gate but with looser thresholds:
            #   HP:  minor=1, age<=24, pwOBAP<=.335 — true prospects
            #   Dev: any minor status, age<=27, pwOBAP<=.345 — almost-prospects
            cands = []
            for lvl, lst in sp_by.items():
                lvl_canonical = 'R(DLR)' if str(lvl).startswith('R(DLR)') else lvl
                lvl_idx = LEVELS.index(lvl_canonical)
                if lvl_idx <= target_idx:
                    continue
                for p in lst:
                    if is_high_potential_pitcher(p):
                        continue
                    if p.get('pwOBA') is None:
                        continue
                    pwobap = p.get('pwOBAP')
                    age = p.get('age', 99)
                    if (pwobap is not None
                            and pwobap <= BLOCKER_MLB_PWOBA
                            and age <= DEVELOPMENTAL_MAX_AGE):
                        continue  # MLB-tier projection + runway = real prospect
                    cands.append((p, lvl))
            if not cands:
                break
            cands.sort(key=lambda c: pitcher_priority(c[0], target_lvl))

            for cand, cand_lvl in cands:
                cand_pri = pitcher_priority(cand, target_lvl)
                if cand_pri >= worst_pri - PITCHER_SWINGMAN_PRIORITY_MARGIN:
                    break  # Sorted ASC — no further candidate clears the margin

                # Validate LHP balance post-swap — only at LHP_LEVELS.
                if target_lvl in LHP_LEVELS:
                    cand_is_lhp = (cand.get('throws') == 2)
                    inc_is_lhp = (worst_rp.get('throws') == 2)
                    cur_lhp = sum(1 for p in target_pen if p.get('throws') == 2)
                    new_lhp = cur_lhp - (1 if inc_is_lhp else 0) + (1 if cand_is_lhp else 0)
                    if not (LEFTY_MIN <= new_lhp <= LEFTY_MAX):
                        continue  # Would break balance; try next candidate

                # Execute swap.
                sp_by[cand_lvl].remove(cand)
                target_pen.remove(worst_rp)
                target_pen.append(cand)

                # Demoted RP cascades to next level below target if _bot allows;
                # otherwise walk further down; otherwise overflow.
                demote_idx = target_idx + 1
                bot = worst_rp.get('_bot', len(LEVELS) - 1)
                if demote_idx > bot:
                    demote_idx = None
                    for k in range(target_idx + 1, len(LEVELS)):
                        if k <= bot:
                            demote_idx = k
                            break
                if demote_idx is None:
                    overflow.append(worst_rp)
                else:
                    demote_lvl = LEVELS[demote_idx]
                    if demote_lvl in rp_by:
                        rp_by[demote_lvl].append(worst_rp)
                    else:
                        overflow.append(worst_rp)

                # Rebalance: cascade any over-cap level (the demoted RP just
                # joined the level below target, possibly pushing it over).
                _shared_overflow_rebalance(rp_by, rp_slots, pitcher_priority, overflow)

                changed = True
                break  # break candidate-for-loop; re-evaluate iter from scratch

            if not changed:
                break  # break iter-for-loop; no more swaps possible at this level


def _rescue_overflow_sps(sp_by, rp_by, rp_slots, overflow):
    """Safety net for the service-cap removal (R-28).

    With SERVICE_CAP_ENABLED=False, vets formerly pinned to AA/A+ are
    fully cascadable, which can push some of them all the way to
    overflow (release). This pass gives any overflowing SP-viable arm
    one chance: walk from their `_top` down, find the highest level
    where their `pitcher_priority` blend beats the worst displaceable
    RP, and swap them in as a bullpen arm. The displaced RP cascades
    to the next level — over-cap ripple gets cleaned up by the loop
    below (same shape as Step 4c).

    Mirror of `_swingman_pullup` in reverse: pulls SP arms DOWN into
    a bullpen slot instead of UP. Always runs (unlike swingman pull-up
    which is opt-in) because it's the structural complement of
    service-cap removal — without it, the cap removal would create
    spurious releases.

    Constraints:
      - LHP balance protected: at LHP_LEVELS (MLB/AAA/AA) with
        LHP count at LEFTY_MIN, won't displace an LHP unless the
        incoming SP is also LHP. At LEFTY_MAX, won't add a LHP.
      - Don't rescue into MLB (the existing R-03 swingman pull-up
        owns that path — keeps the two passes from fighting).
      - Don't rescue into R(DLR) (it's the foreign-developmental
        tier; rescuing a US/Canadian SP there is meaningless because
        DSL eligibility blocks it via `_bot`, and rescuing a foreign
        SP there is below the rescue's purpose).

    Mutates sp_by (no-op — SPs come from overflow), rp_by, overflow.
    """
    rescue_targets = sorted(
        [p for p in overflow if is_sp_viable(p)],
        key=lambda p: pitcher_priority(p, 'AA'),
    )

    for sp in rescue_targets:
        if sp not in overflow:
            continue  # paranoia — shouldn't happen, but guards against double-rescue
        sp_top = sp.get('_top', 0)
        sp_bot = sp.get('_bot', len(LEVELS) - 1)
        sp_is_lhp = is_lhp(sp)
        placed = False

        # Walk levels from the highest the SP qualifies for, downward, until
        # they find one where they can outrank the worst displaceable RP.
        for i, lvl in enumerate(LEVELS):
            if i < sp_top or i > sp_bot:
                continue
            if lvl == 'MLB' or lvl == 'R(DLR)':
                continue

            existing = rp_by.get(lvl, [])
            if not existing:
                continue  # empty bullpen — push-down fills these, not rescue

            n_lhp = sum(1 for p in existing if is_lhp(p))
            sp_pri = pitcher_priority(sp, lvl)

            # Pick the worst displaceable RP, with LHP-balance guard.
            # At LHP_LEVELS with LHP count at LEFTY_MIN, the only LHP is
            # protected unless the incoming arm is also LHP.
            protect_only_lhp = (lvl in LHP_LEVELS
                                and n_lhp <= LEFTY_MIN
                                and not sp_is_lhp)
            candidates = [p for p in existing
                          if not (protect_only_lhp and is_lhp(p))]
            if not candidates:
                continue

            worst_rp = max(candidates, key=lambda p: pitcher_priority(p, lvl))
            if sp_pri >= pitcher_priority(worst_rp, lvl):
                continue  # SP doesn't outrank — try next level

            # At LEFTY_MAX, refuse a swap that adds an LHP without dropping one.
            if (lvl in LHP_LEVELS and sp_is_lhp and not is_lhp(worst_rp)
                    and n_lhp >= LEFTY_MAX):
                continue

            # Execute swap.
            rp_by[lvl].remove(worst_rp)
            rp_by[lvl].append(sp)
            overflow.remove(sp)

            # Cascade displaced RP to next level (or overflow if blocked).
            next_idx = i + 1
            displaced_bot = worst_rp.get('_bot', len(LEVELS) - 1)
            if (next_idx < len(LEVELS)
                    and next_idx <= displaced_bot
                    and LEVELS[next_idx] in rp_by):
                rp_by[LEVELS[next_idx]].append(worst_rp)
            else:
                overflow.append(worst_rp)
            placed = True
            break

        # If we couldn't place this SP anywhere, leave them in overflow —
        # they truly weren't competitive even as a swingman.

    # Over-cap ripple: a displaced RP that cascades to a level already at
    # capacity needs to keep cascading. Shared helper.
    _shared_overflow_rebalance(rp_by, rp_slots, pitcher_priority, overflow)


def _block_hps_at_mlb(by_level):
    """Hard HP block: move any HP pitcher currently at MLB to AAA.
    Run AFTER cascade and AFTER pull-up — prospects develop in the
    minors regardless of projection or pull-up signals.

    Destination is HP_MIN_LEVEL_INDEX (default 1 = AAA). If `_bot` is
    somehow lower than that (very rare for an HP), the HP is left at
    MLB. Mirrors the hitter pre-Step-3 block in build_system.py."""
    if HP_MIN_LEVEL_INDEX <= 0:
        return
    mlb_lvl = LEVELS[0]
    mlb_hps = [p for p in by_level.get(mlb_lvl, [])
               if is_high_potential_pitcher(p)]
    for hp in mlb_hps:
        target_idx = HP_MIN_LEVEL_INDEX
        bot = hp.get('_bot')
        if bot is not None and bot < target_idx:
            continue  # _bot blocks AAA — leave at MLB
        target_lvl = LEVELS[target_idx]
        by_level[mlb_lvl].remove(hp)
        by_level.setdefault(target_lvl, []).append(hp)


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
        # Hard block: HP pitchers never start at MLB regardless of `_top`.
        # Skip the MLB level by clamping the search range to start at
        # max(HP_MIN_LEVEL_INDEX, hp._top). Defaults to AAA (index 1).
        start_idx = max(hp['_top'], HP_MIN_LEVEL_INDEX) if HP_MIN_LEVEL_INDEX > 0 else hp['_top']
        for idx in range(start_idx, hp['_bot'] + 1):
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
            # Level is full — swap with the worst non-HP at this level,
            # but only if the HP's BLENDED priority at this level is
            # strictly better than that non-HP's blended priority. This
            # keeps HP enforcement consistent with the cascade's ranking
            # (R-31): one ranking rule for the whole system. The earlier
            # `gain − loss` swap test effectively re-weighted projection
            # at 1:1 vs current, letting HPs override blended-priority
            # cascade decisions and demote better-priority non-HPs.
            non_hps = [p for p in by_level[lvl] if not is_high_potential_pitcher(p)]
            if not non_hps:
                continue
            target = max(non_hps, key=lambda p: pitcher_priority(p, lvl))
            if pitcher_priority(hp, lvl) < pitcher_priority(target, lvl):
                by_level[lvl].remove(target)
                by_level[lvl].append(hp)
                overflow.remove(hp)
                overflow.append(target)
                by_level[lvl].sort(key=lambda p: pitcher_priority(p, lvl))
                hp['_force_start'] = lvl
                break


def _filter_complex_and_injured(laa):
    """Step 0: drop international-complex (minor=0 + age<20) and the
    injured pool. Returns (valid_for_placement, flagged_injured).

    Extracted from main() for testability (R-33 decomposition)."""
    laa = [p for p in laa if not (p.get('minor') == 0 and p['age'] < 20)]
    injured = _load_injured_names()
    flagged_players = [p for p in laa if is_player_injured(p, injured)]
    valid = [p for p in laa if not is_player_injured(p, injured)]
    return valid, flagged_players


def _compute_eligibility_window(pool):
    """Step 1: set `_top` (pwOBA-derived best level) and `_bot`
    (age + service + DSL floor) on every player. Returns
    (valid, immediate_overflow) — players with `_top > _bot` have no
    placement window and go straight to overflow.

    Extracted from main() for testability (R-33 decomposition)."""
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
    """Build per-level SP/RP slot dicts, scaling R(DLR) by the org's
    actual DSL team count. Extracted from main() for testability
    (R-33 decomposition)."""
    sp_slots = {lvl: SP_PER_LEVEL[lvl] for lvl in LEVELS}
    rp_slots = {lvl: RP_PER_LEVEL[lvl] for lvl in LEVELS}
    n_dsl = max(1, _count_dsl_teams(org))
    sp_slots['R(DLR)'] = SP_PER_LEVEL['R(DLR)'] * n_dsl
    rp_slots['R(DLR)'] = RP_PER_LEVEL['R(DLR)'] * n_dsl
    return sp_slots, rp_slots, n_dsl


def main(org: str | None = None) -> tuple[dict, list[dict], list[dict]]:
    """Build the pitcher staff for one org. Returns
    (rosters_by_level, overflow, flagged_players) where:
      - rosters_by_level: {lvl: {'starters': [...], 'bullpen': [...], 'all',
                                 'sp_target', 'rp_target', 'sign_lhp'}}
      - overflow: list of pitcher dicts that didn't place anywhere
      - flagged_players: injury-list arms held out of placement
    """
    laa = load_team_pitchers(org)
    for p in laa:
        p.pop('_role', None)

    # Step 0: filter international complex (minor=0 + age<20) and the
    # injured pool (OOTP injury flag + manual injured.txt).
    laa, flagged_players = _filter_complex_and_injured(laa)

    # Step 1: eligibility window. `_top` = current pwOBA ceiling only;
    # `_bot` = min(age, service-time, DSL-eligibility) floor. Players
    # with `_top > _bot` have no feasible placement and overflow now.
    valid, overflow = _compute_eligibility_window(laa)

    # Per-org pitcher capacities. R(DLR) scales by DSL team count.
    sp_slots, rp_slots, n_dsl = _per_org_slot_capacities(org)

    # Step 2-3: SP cascade + pull-up
    sp_pool = [p for p in valid if is_sp_viable(p)]
    sp_by, _sp_leftover = _cascade(sp_pool, sp_slots)
    _block_hps_at_mlb(sp_by)         # hard HP block — see helper
    _pull_up(sp_by, sp_slots)
    _block_hps_at_mlb(sp_by)         # in case pull-up promoted any back
    sp_assigned = {p['name'] for lvl in LEVELS for p in sp_by[lvl]}

    # Step 4: RP cascade + pull-up
    # Exclude SP-viable HPs that didn't make the SP cascade — they're
    # developmental starters by intent, not RP candidates. Without this
    # guard the RP cascade would scoop them up before HP enforcement
    # (Step 5a) gets a chance to place them as SP via swap. They'll
    # land in overflow if SP HP enforcement can't find them a slot,
    # and the R-28 rescue pass becomes their fallback to RP.
    rp_pool = [
        p for p in valid
        if is_rp_viable(p)
        and p['name'] not in sp_assigned
        and not (is_sp_viable(p) and is_high_potential_pitcher(p))
    ]
    rp_by, rp_leftover = _cascade(rp_pool, rp_slots)
    _block_hps_at_mlb(rp_by)
    _pull_up(rp_by, rp_slots)
    _block_hps_at_mlb(rp_by)

    # Step 4a: opt-in swingman pull-up (R-03; default-ON since R-34).
    # Runs BEFORE LHP balance so any AAA imbalance the swingman swap
    # creates (cascading the demoted RP can push out an LHP) is then
    # repaired by the LHP balance pass at the next step.
    _swingman_pullup(sp_by, rp_by, rp_slots, overflow)

    # Step 4a.0a: promote natural-_top sp_viable arms from rp_by into
    # vacant sp_by slots at the same level, BEFORE the re-run pull-up
    # falls back on +1 stretches. Fixes cascade-compression inversion
    # where R-natural arms get pushed to R bullpen by A+/A arms
    # cascading down, then the cascaded-in arms get pulled away to
    # higher bullpens by swingman, leaving R SP to be filled via
    # stretch from R(DLR) — even though better-priority R-natural
    # arms are sitting right there in rp_by[R]. See helper docstring
    # for the full Banks/Darden/Wynk trace.
    _promote_natural_sps_from_rp(sp_by, rp_by, sp_slots)

    # Step 4a.1 (R-34): re-run SP pull-up to refill any AAA / lower SP
    # slots the swingman pull-up vacated. Without this the empty slots
    # would later be filled by `_push_down_from_overflow`, which used
    # to accept arms multiple levels above their `_top` (Maldonado
    # at AA-tier going to AAA = +1 stretch is OK; Banks at R-tier
    # going to AAA = +4 stretch is not). The pull-up's strict + +1
    # stretch discipline gets us a proper backfill (best non-HP AA
    # SP promoted to AAA, etc.) without crossing multi-level gaps.
    # HPs stay excluded from the stretch — they keep developing at
    # their natural _top.
    _pull_up(sp_by, sp_slots)
    _block_hps_at_mlb(sp_by)

    # Step 4b: bullpen handedness balance — MLB / AAA / AA only.
    # Hard MIN uses strict eligibility only; if no qualified LHP exists,
    # the slot is left open and tagged in `lhp_shortfalls` so the renderer
    # can show "Sign LHP" instead of generic "Sign FA".
    lhp_shortfalls = _enforce_lhp_balance(rp_by, overflow, rp_slots)

    # Step 4c: rebalance any level the LHP shortfall pushed over capacity.
    # When MLB or AAA drops a RHP to make room for "Sign LHP" placeholders,
    # the demoted RHP cascades to the next level — which can then run over
    # its rp_target. Shared helper trims top-down.
    _shared_overflow_rebalance(rp_by, rp_slots, pitcher_priority, overflow)

    # Recompute sp_assigned: the original set above was built right after
    # the first SP pull-up, but `_swingman_pullup` moves SP arms into
    # bullpens and `_promote_natural_sps_from_rp` moves RP arms into
    # rotation. Using the stale set in Step 5 would re-add promoted arms
    # to overflow (they weren't in the original `sp_assigned`) and the
    # downstream push-down would then put them back into a bullpen slot,
    # creating duplicates between sp_by and rp_by.
    sp_assigned = {p['name'] for lvl in LEVELS for p in sp_by[lvl]}
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

    # Step 5a.1b: SP rescue pass (R-28). Service-cap removal can push
    # vets all the way to overflow when every level below their old pin
    # is at capacity. Give each overflowing SP a last-chance bullpen
    # audition: walk down from their _top, win an RP slot if they
    # outrank the worst displaceable RP at that level. Mirror of R-03
    # swingman pull-up in the demote direction. See helper docstring
    # for full constraints (LHP balance, MLB / R(DLR) exclusions).
    _rescue_overflow_sps(sp_by, rp_by, rp_slots, overflow)

    # Step 5a.2: re-enforce LHP balance. The push-down can fill an
    # LHP-reserved bullpen slot with a non-LHP (push-down sees only
    # `_bot`, not handedness), undoing Step 4b's work. Re-run the LHP
    # balance + over-cap rebalance to restore the invariant — any
    # slots that genuinely have no LHP filler available end up tagged
    # `sign_lhp` again rather than silently filled by a RHP.
    lhp_shortfalls = _enforce_lhp_balance(rp_by, overflow, rp_slots)
    _shared_overflow_rebalance(rp_by, rp_slots, pitcher_priority, overflow)

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

    # Defence-in-depth: assert no player ended up below their `_bot`.
    # Every placement site already checks, but a future placement path
    # could forget; this catches it loudly.
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
