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
    is_high_potential,
    apply_hp_premium_fit_override,
    projected_pos_adj,
    woba_max_level,
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
)


# Disaster-floor for the Best-bat bench seat. A bat with overall
# scarcity-adjusted WAR below this floor can't claim Best-bat even with
# top-shelf raw wOBA — keeps a -3 WAR glove from holding the pinch-hit
# slot. -1.0 = "clearly-below-replacement defender". Tuned empirically.
BEST_BAT_BEST_ADJ_FLOOR = -1.0


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
      - HP MLB hard-block: HPs not placed above HP_MIN_LEVEL_INDEX unless
        their `_bot` is also above (pathological).
    """
    out = []
    for p in available:
        if level_idx > p.get('_bot', len(LEVELS) - 1):
            continue
        if (level_idx < HP_MIN_LEVEL_INDEX
                and is_high_potential(p)
                and p.get('_bot', 0) >= HP_MIN_LEVEL_INDEX):
            continue
        out.append(p)
    return out


def _construct_level(pool, level, roster_size):
    """Build one level's roster: 9 starters + 4 named bench roles +
    `(roster_size - 13)` Depth slots.

    Returns (starters_dict, bench_roles_list, placed_ids_set).
      - starters_dict: {pos: player or None} from Hungarian
      - bench_roles_list: [(role_label, player_or_None), ...] in order
        Backup C / Utility IF / Utility OF / Best bat / Depth*
      - placed_ids_set: ids of all players placed at this level
    """
    # 1. Starters via Hungarian on `_adj`. fill_starters returns the
    #    starter dict + the "everyone else in the pool" bench list.
    starters, _bench_remainder = fill_starters(pool, level)
    placed_ids = {id(p) for p in starters.values() if p}
    remaining = [p for p in pool if id(p) not in placed_ids]

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
            eligible, lvl, roster_sizes[lvl],
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
            starters, bench_roles, _ = _construct_level(chunk, 'R(DLR)', chunk_size)
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
