"""v2 hitter placement — role-by-role per-level construction.

Replaces v1's cascade-first architecture (initial cascade → 3-pass pull-up
→ release-pool push-down → bench refinement → premium-fit pull-up →
HP enforcement → re-enforce HP → final Hungarian) with a clean per-level
role-by-role construction loop.

Algorithm (per level top-down, MLB → AAA → AA → A+ → A → R → R(DLR)):

  pool = bats `_bot`-eligible for this level (and not HP-blocked at MLB).
  1. Starting 9: Hungarian on `_adj` scores via fill_starters().
  2. Backup C:   best catcher_alloc_score among remaining.
  3. Utility IF: best sum(2B/3B/SS _adj) among remaining.
  4. Utility OF: best sum(LF/CF/RF _adj) among remaining.
  5. Best bat:   best wOBA among remaining (with `best_adj >= -1.0` floor
                 so a -3 WAR glove can't hold the pinch-hit seat).
  6. Depth:      remaining `(ROSTER_SIZES[level] - 13)` slots, ranked by
                 `bat_priority` (85/15 wOBA/wOBAP blend — same metric v1
                 used for Depth ordering). MLB has 0 Depth slots (13-13);
                 AAA/AA have 2; A+/A/R/R(DLR) have 3.
  Remaining players → next level pool (overflow cascade).

Each level holds at most 9 starters + 4 named bench roles + ROSTER_SIZES
Depth slots.
The named-role slots that can't be filled (no catcher, no IF-capable, etc.)
stay empty and the role tuple still appears with player=None so callers
render an empty slot consistently. Same convention as v1.classify_bench().

Semantic shift vs v1: `_top` (current-wOBA-derived best level) is computed
for diagnostic / display compatibility but no longer gates placement.
Only `_bot` (age + service + DSL) binds. A thin org's best bats fill MLB
regardless of how their wOBA compares to MLB thresholds.

Return shape identical to v1's build_system.main() — drop-in via import
swap. Imports stateless helpers (catcher_alloc_score, fill_starters, etc.)
from v1 verbatim; the only new code is the per-level construction loop
and the Best-bat disaster-floor gate.

Per user direction: NO HP forcing, NO HP _bot priority bonus. The algorithm
already gives every HP fair shot at every role at every level — they win
roles where their `_adj` / `wOBA` / score functions beat the competition,
and cascade naturally otherwise.
"""
from __future__ import annotations  # PEP 604 unions for Python 3.9 (Streamlit Cloud) compat

# Reuse stateless v1 primitives verbatim — none have construction side-effects.
# Several of these are re-exported below so downstream consumers (build_excel,
# streamlit_app, lineup_optimizer, tests) can import the full public surface
# from a single module (build_system_v2) without touching v1.
from build_system import (  # noqa: F401  (re-exports for downstream consumers)
    # I/O and pool prep
    load_team,
    compute_roster_sizes,
    _filter_complex_and_injured,
    _compute_eligibility_window,
    # Player-level helpers
    bat_priority,
    is_catcher,
    catcher_alloc_score,
    apply_hp_premium_fit_override,
    projected_pos_adj,
    woba_max_level,
    # NOTE: is_high_potential is NOT imported from v1 here — v2 uses its
    # own definition (below) that drops the `minor=1` requirement so a
    # young MLB-rostered player with high bestP_adj can still get the
    # HP cascade-vs-anchor + boost treatment.
    # Per-level Hungarian primitives
    fill_starters,
    fill_starters_split,
    fill_backups,
    # Constants
    POSITIONS,
)
from roster_common import (  # noqa: F401  (re-exports)
    LEVELS,
    MAX_AGE,
    SERVICE_LIMITS,
    total_service_years,
    _count_dsl_teams,
    assert_bot_invariant,
)
from config import (  # noqa: F401  (re-exports)
    ROSTER_SIZES_HITTER as ROSTER_SIZES,
    WOBA_MIN_HITTER as WOBA_MIN,
    HP_MIN_LEVEL_INDEX,
    IF_POSITIONS,
    OF_POSITIONS,
    HP_MAX_AGE,
    HP_BESTP_ADJ_THRESHOLD,
    HP_WOBA_THRESHOLD,
)


# v2-local HP detection. Drops the `minor=1` requirement that v1's
# `is_high_potential` enforces — per session feedback, a young MLB-
# rostered player (minor=0, on 40-man / out of options) with high
# bestP_adj should still get the HP cascade-vs-anchor + _bot boost
# treatment. Age + projection are the substantive criteria; roster
# status is incidental.
#
# Same threshold logic as v1: age <= HP_MAX_AGE (24) AND EITHER
# bestP_adj >= HP_BESTP_ADJ_THRESHOLD (2.0, league-average regular)
# OR wOBAP >= HP_WOBA_THRESHOLD (.340, elite bat projection).
def is_high_potential(p: dict) -> bool:
    """v2 HP detection — age + projection, NOT roster status."""
    if p['age'] > HP_MAX_AGE:
        return False
    bestP_adj = p.get('bestP_adj') or float('-inf')
    wobap = p.get('wOBAP') or 0
    return (bestP_adj >= HP_BESTP_ADJ_THRESHOLD
            or wobap >= HP_WOBA_THRESHOLD)


# Disaster-floor for the Best-bat bench seat. A bat with overall
# scarcity-adjusted WAR below this floor can't claim Best-bat even with
# top-shelf raw wOBA — keeps a -3 WAR glove from holding the pinch-hit
# slot. -1.0 = "clearly-below-replacement defender". Tuned empirically.
BEST_BAT_BEST_ADJ_FLOOR = -1.0

# Per-level wOBA floor — empirically derived from v2 all-placed p10s
# across 30 orgs (Future Sim, ~3,700 placed bats). A player whose wOBA
# is below the floor for level X cascades to level X+1 — same semantic
# as v1's `WOBA_MIN_HITTER` but calibrated to the actual observed
# distribution at each level rather than hand-tuned safety margins.
#
# Replaces v2's earlier "drop _top entirely" stance per session feedback
# (Marquart-class outliers: .173 wOBA winning A+ SS starter on glove
# alone). The floor restores the "your bat plays at this level" gate
# that v1 had via WOBA_MIN_HITTER, but at tighter empirical values.
#
# HPs at their `_bot` are EXEMPT — they have to be placed somewhere, so
# the floor doesn't apply at their developmental floor level. Above
# `_bot`, HPs obey the floor like everyone else (cascading down until
# they reach a level whose floor they clear OR their `_bot`).
WOBA_LEVEL_FLOOR = {
    # Initial floors (empirical p10s) were 1f4166d landing point:
    #   MLB .280, AAA .267, AA .241, A+ .225, A .205, R .160, R(DLR) .112.
    # All floors lowered by .010 per session feedback — the tight
    # empirical p10s were rejecting glove-first profiles (e.g. Nasim
    # Nuñez .277 with sum-of-IF-_adj +2.67 was blocked from WSH MLB
    # Util IF). The .010 cushion lets elite-glove sub-floor bats in
    # without dropping the floor's structural role.
    'MLB':    0.270,
    'AAA':    0.257,
    'AA':     0.231,
    'A+':     0.215,
    'A':      0.195,
    'R':      0.150,
    # R(DLR) has NO floor — it's the deepest tier of pro ball, so a
    # sub-floor bat has nowhere lower to cascade to. The empirical p10
    # (.112) was survivor-biased (measured the already-placed pool),
    # not the actual unfiltered DSL signing class. v1's original
    # WOBA_MIN_HITTER['R(DLR)'] = -1.0 had the same semantic.
    'R(DLR)': -1.0,
}

# HP _bot priority boost — applied to all `<pos>_adj` fields of an HP
# when constructing at their `_bot` level. Mirrors pitcher v3's
# `HP_BOT_PRIORITY_BONUS = 0.015` adapted to hitter WAR scale.
#
# Why: HPs whose CURRENT bat doesn't yet beat established non-HPs in
# Hungarian would otherwise cascade through every level and land in
# overflow / release — even though they have real developmental upside.
# v1's solution was a separate HP-enforcement pass that displaced
# non-HPs. v2's simpler equivalent: bias the Hungarian at the HP's
# developmental floor so they win the marginal slot competition that
# decides whether they're starting at, e.g., A vs. on the AA bench.
#
# Boost only fires AT the HP's _bot level. Above _bot, HPs cascade
# without help (this is the rewrite's central premise — HPs above _bot
# never end up on bench because they aren't considered for bench roles
# at all; see `_construct_level` filter).
#
# Magnitude sweep TBD. 3.0 WAR is a defensible starting point: large
# enough to swing typical marginal Hungarian decisions at lower levels
# (where most _adj scores are below 1 WAR) without overpowering true
# elite non-HP starters (whose _adj > 2 WAR would still win on raw).
HP_BOT_ADJ_BOOST = 3.0


# ---------------------------------------------------------------------------
# Per-level role score functions — Backup C / Utility IF / Utility OF.
# Best-bat uses raw wOBA + disaster floor inline.
# ---------------------------------------------------------------------------

def _if_score(p):
    """Sum of scarcity-adjusted WAR at 2B / 3B / SS for the positions the
    player can actually play. Returns None for players with no IF position."""
    vals = [p.get(f'{pos}_adj') for pos in IF_POSITIONS]
    valid = [v for v in vals if v is not None]
    return sum(valid) if valid else None


def _of_score(p):
    """Same shape over LF / CF / RF. Returns None for no-OF players."""
    vals = [p.get(f'{pos}_adj') for pos in OF_POSITIONS]
    valid = [v for v in vals if v is not None]
    return sum(valid) if valid else None


def _best_bat_score(p):
    """Raw wOBA, gated on best_adj >= disaster floor. Returns None for
    players who fail the floor — keeps elite-bat-disaster-glove players
    from holding the pinch-hit seat."""
    best_adj = p.get('best_adj')
    if best_adj is None or best_adj < BEST_BAT_BEST_ADJ_FLOOR:
        return None
    return p.get('wOBA') or 0


def _greedy_take(pool, score_fn):
    """Pick the player from `pool` with the highest score under `score_fn`.
    Returns (picked_or_None, remaining_pool). score_fn returns None to
    disqualify (e.g. non-catcher for Backup C); if no candidate scores,
    returns (None, pool unchanged)."""
    scored = [(score_fn(p), p) for p in pool]
    scored = [(s, p) for s, p in scored if s is not None]
    if not scored:
        return None, pool
    _, best = max(scored, key=lambda sp: sp[0])
    return best, [p for p in pool if id(p) != id(best)]


# ---------------------------------------------------------------------------
# Per-level construction — the actual algorithm.
# ---------------------------------------------------------------------------

def _eligible_for_level(available, level_idx):
    """Filter `available` to bats eligible for placement at `level_idx`:
      - `_bot` covers this level (level_idx <= _bot)
      - wOBA >= WOBA_LEVEL_FLOOR[level]. HPs at their `_bot` are exempt
        (they must be placed somewhere, even if their current bat is
        below the level's empirical floor — projection / developmental
        runway justifies the slot).

    NOTE: HP→MLB hard-block from R-20 (HP_MIN_LEVEL_INDEX) was removed
    per session feedback. HPs now compete at MLB on raw _adj like
    everyone else. An HP whose current stuff is MLB-competitive can win
    starter via Hungarian; one whose isn't loses and CASCADES (per the
    "HPs above _bot can't be on bench" rule in `_construct_level`). Net
    effect: HPs at MLB only as starters, never bench — the v2 "must
    start" invariant naturally enforces R-20's developmental intent
    without an explicit block.
    """
    out = []
    lvl_name = LEVELS[level_idx]
    floor = WOBA_LEVEL_FLOOR[lvl_name]
    for p in available:
        if level_idx > p.get('_bot', len(LEVELS) - 1):
            continue
        # wOBA floor — exempt HPs at their `_bot` level.
        woba = p.get('wOBA') or 0
        if woba < floor:
            hp_at_bot = (is_high_potential(p)
                         and p.get('_bot') == level_idx)
            if not hp_at_bot:
                continue
        out.append(p)
    return out


def _apply_hp_bot_boost(pool, level_idx):
    """Temporarily add HP_BOT_ADJ_BOOST to every `<pos>_adj` field of HPs
    whose `_bot` equals this level. Returns a list of (player_dict, {pos:
    original_value}) so the boost can be reverted after Hungarian runs.

    Boost is applied per-position (not just to `pos_adj`) because
    Hungarian considers every player at every position. Their natural
    spot will still typically win because that's where _adj was already
    highest pre-boost.
    """
    saved = []
    for p in pool:
        if not is_high_potential(p):
            continue
        if p.get('_bot') != level_idx:
            continue
        per_pos = {}
        for pos in POSITIONS:
            v = p.get(f'{pos}_adj')
            if v is not None:
                per_pos[pos] = v
                p[f'{pos}_adj'] = v + HP_BOT_ADJ_BOOST
        saved.append((p, per_pos))
    return saved


def _restore_hp_bot_boost(saved):
    """Undo the mutation from _apply_hp_bot_boost. Call in a `finally`
    so player dicts return to their original state even if Hungarian
    raises."""
    for p, per_pos in saved:
        for pos, v in per_pos.items():
            p[f'{pos}_adj'] = v


def _construct_level(pool, level, level_idx, roster_size):
    """Build one level's roster: 9 starters + 4 named bench roles +
    `(roster_size - 13)` Depth slots.

    HP cascade-vs-anchor logic:
      - HPs at their `_bot` (level_idx == p['_bot']) get an
        HP_BOT_ADJ_BOOST during Hungarian so they typically win the
        marginal starter slot at their developmental floor.
      - HPs above their `_bot` (level_idx < p['_bot']) who don't win
        starter via Hungarian are EXCLUDED from bench/Depth selection —
        they cascade to the next level for another shot. Prevents
        v1-style "HP stuck as AAA bench Utility IF" placements when
        their `_bot` is much deeper.

    Returns (starters_dict, bench_roles_list, placed_ids_set).
    """
    # 1. Starters via Hungarian on `_adj`, with HP `_bot` boost applied.
    hp_boost_state = _apply_hp_bot_boost(pool, level_idx)
    try:
        starters, _bench_remainder = fill_starters(pool, level)
    finally:
        _restore_hp_bot_boost(hp_boost_state)
    placed_ids = {id(p) for p in starters.values() if p}

    # HPs above their `_bot` who lost starter Hungarian must cascade —
    # exclude them from this level's bench/Depth pool.
    remaining = [
        p for p in pool
        if id(p) not in placed_ids
        and not (
            is_high_potential(p)
            and level_idx < p.get('_bot', len(LEVELS) - 1)
        )
    ]

    # 2. Backup C
    backup_c, remaining = _greedy_take(
        remaining,
        lambda p: catcher_alloc_score(p) if is_catcher(p) else None,
    )
    if backup_c is not None:
        placed_ids.add(id(backup_c))

    # 3. Utility IF
    util_if, remaining = _greedy_take(remaining, _if_score)
    if util_if is not None:
        placed_ids.add(id(util_if))

    # 4. Utility OF
    util_of, remaining = _greedy_take(remaining, _of_score)
    if util_of is not None:
        placed_ids.add(id(util_of))

    # 5. Best bat — pure wOBA among remaining, with disaster floor.
    best_bat, remaining = _greedy_take(remaining, _best_bat_score)
    if best_bat is not None:
        placed_ids.add(id(best_bat))

    bench_roles = [
        ('Backup C', backup_c),
        ('Utility IF', util_if),
        ('Utility OF', util_of),
        ('Best bat', best_bat),
    ]

    # 6. Depth — remaining slots by bat_priority (v1's 85/15 blend).
    # IMPORTANT: count Depth against actually-filled named roles, not the
    # nominal 4. When a named role fires empty (e.g. Best-bat at a thin
    # level where every remaining bat fails the disaster floor), Depth
    # absorbs the freed slot so the level still fills its target.
    n_starters_filled = sum(1 for v in starters.values() if v)
    n_named_filled = sum(1 for _r, p in bench_roles if p is not None)
    depth_slots = roster_size - n_starters_filled - n_named_filled
    if depth_slots > 0 and remaining:
        remaining.sort(key=lambda p: bat_priority(p, level), reverse=True)
        for depth_player in remaining[:depth_slots]:
            placed_ids.add(id(depth_player))
            bench_roles.append(('Depth', depth_player))

    return starters, bench_roles, placed_ids


def _construct_all_levels(valid, roster_sizes):
    """Top-down loop: at each level, run _construct_level on the eligible
    pool. Whoever isn't placed cascades to the next level's pool.

    Returns (rosters_by_level, overflow).
      rosters_by_level: {lvl: {'starters': {pos: p}, 'bench_roles': [...],
                               'placed': [p, ...]}}
      overflow: players still unplaced after R(DLR).
    """
    by_level: dict[str, dict] = {}
    available = list(valid)

    for i, lvl in enumerate(LEVELS):
        eligible = _eligible_for_level(available, i)
        starters, bench_roles, placed_ids = _construct_level(
            eligible, lvl, i, roster_sizes[lvl],
        )
        placed_players = [p for p in eligible if id(p) in placed_ids]
        by_level[lvl] = {
            'starters_dict': starters,
            'bench_roles': bench_roles,
            'placed': placed_players,
        }
        # Cascade everyone not placed at this level to the next level's pool.
        available = [p for p in available if id(p) not in placed_ids]

    return by_level, available


# ---------------------------------------------------------------------------
# Public entry point — matches build_system.main() return shape.
# ---------------------------------------------------------------------------

def main(org: str | None = None) -> tuple[dict, list[dict], list[dict]]:
    """Build the hitter roster for one org (v2). Returns
    (rosters_by_level, overflow, flagged_players) — same shape as
    build_system.main() so callers can swap with a one-line import flip.
    """
    laa = load_team(org)
    laa, complex_players, flagged_players = _filter_complex_and_injured(laa)

    # HP premium-fit pos_adj override — same as v1, mutates player dicts.
    for p in laa:
        apply_hp_premium_fit_override(p)

    # Compute _top + _bot. _top is informational only (display / diagnostics);
    # construction gates on _bot.
    valid, immediate_overflow = _compute_eligibility_window(laa)

    roster_sizes = compute_roster_sizes(org)

    # Top-down per-level construction.
    constructed, leftover = _construct_all_levels(valid, roster_sizes)
    overflow = list(immediate_overflow) + list(leftover)

    # Build the final rosters dict in v1's return shape. fill_starters_split
    # / fill_backups need the "all players at this level" list — pull from
    # `placed` (starters + named bench + depth).
    rosters: dict[str, dict] = {}
    for lvl in LEVELS:
        info = constructed[lvl]
        starters = info['starters_dict']
        bench_roles = info['bench_roles']
        placed = info['placed']
        bench = [p for _role, p in bench_roles if p is not None]
        # Platoon variants run on the full placed list (starters + bench).
        sR = fill_starters_split(placed, lvl, 'R', standard_starters=starters)
        sL = fill_starters_split(placed, lvl, 'L', standard_starters=starters)
        rosters[lvl] = {
            'starters': starters,
            'starters_vsR': sR,
            'starters_vsL': sL,
            'backups_vsR': fill_backups(placed, sR, 'R'),
            'backups_vsL': fill_backups(placed, sL, 'L'),
            'bench': bench,
            'bench_roles': bench_roles,
            'all': placed,
            'target': roster_sizes[lvl],
        }

    # Defence-in-depth: every placed player must respect their `_bot`.
    by_level_for_assert = {lvl: rosters[lvl]['all'] for lvl in LEVELS}
    assert_bot_invariant(by_level_for_assert, role_label='hitter')

    # R(DLR) sub-team split — same shape as v1 (chunks the placed list).
    n_dsl = _count_dsl_teams(org)
    if n_dsl >= 2 and 'R(DLR)' in rosters:
        full_all = rosters.pop('R(DLR)')['all']
        # Rank by best_adj (the same _adj scale used everywhere else).
        ranked = sorted(full_all, key=lambda p: p.get('best_adj') or 0, reverse=True)
        chunk_size = ROSTER_SIZES['R(DLR)']
        for k in range(n_dsl):
            chunk = ranked[k * chunk_size:(k + 1) * chunk_size]
            # Re-run the per-level construction on each chunk so each DSL
            # sub-team independently picks starters + bench roles.
            # R(DLR) sub-team: use LEVELS index of R(DLR) for HP `_bot`
            # boost matching (sub-team keys like 'R(DLR)1' aren't in LEVELS).
            starters, bench_roles, _ = _construct_level(
                chunk, 'R(DLR)', LEVELS.index('R(DLR)'), chunk_size,
            )
            placed_ids = {id(p) for p in starters.values() if p}
            for _role, p in bench_roles:
                if p is not None:
                    placed_ids.add(id(p))
            placed = [p for p in chunk if id(p) in placed_ids]
            # Any chunk members not picked by the sub-team's Hungarian +
            # named roles + Depth fall to overflow — don't silently drop
            # them (was a v2 leak: 14/16 sub-team would lose 2 players).
            chunk_leftover = [p for p in chunk if id(p) not in placed_ids]
            overflow.extend(chunk_leftover)
            bench = [p for _role, p in bench_roles if p is not None]
            sR = fill_starters_split(placed, 'R(DLR)', 'R', standard_starters=starters)
            sL = fill_starters_split(placed, 'R(DLR)', 'L', standard_starters=starters)
            rosters[f'R(DLR){k+1}'] = {
                'starters': starters,
                'starters_vsR': sR,
                'starters_vsL': sL,
                'backups_vsR': fill_backups(placed, sR, 'R'),
                'backups_vsL': fill_backups(placed, sL, 'L'),
                'bench': bench,
                'bench_roles': bench_roles,
                'all': placed,
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
                print(f"  {pos}: {p['name']:25} age={p['age']:2} wOBA={woba:.3f} {pos}_adj={pa:5.2f}")
            else:
                print(f"  {pos}: -- empty --")
        print(f"  Bench roles:")
        for role, p in r['bench_roles']:
            if p:
                print(f"    {role:12} {p['name']:25} wOBA={p.get('wOBA') or 0:.3f}")
            else:
                print(f"    {role:12} -- empty --")
    print(f"\nOverflow/release: {len(overflow)}")
    print(f"Flagged (injured): {len(flagged)}")
