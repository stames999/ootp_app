# Build-system rewrite: cascade-first → top-down construction

**Status:** Design note, not yet implemented. Defer to a fresh chat.

## Problem with the current architecture

`build_system.py` today distributes players to levels via a multi-step
cascade *before* constructing each level's roster:

1. Compute `_top` (highest-eligible level by current wOBA) and `_bot`
   (lowest-eligible level by age + service) for every player.
2. Initial cascade: place each player at their `_top`.
3. If a level overflows its slot count, evict the lowest-priority players
   and cascade them down to the next level.
4. After cascade settles, run `fill_starters` (Hungarian assignment) and
   `classify_bench` (role-defined bench seats) at each level.
5. Apply a stack of repair passes — HP enforcement, pull-up, push-down,
   swingman, rescue — to fix cases where the local cascade ordering
   produced a globally-bad placement.

The repair passes exist because the cascade priority is necessarily a
single-dimensional score per player, but the right level for a player
depends on what role they'd play and who else is at each level. Bugs we
hit this session that all trace back to this:

- **Tavarez (Future Sim, ATL):** glove-first SS prospect cascaded out
  of his service-time window because the bat-only priority gave him a
  worse score than a 3B-forced-to-SS by 0.003 of wOBA. Fixed in
  `748406b` by switching cascade priority to overall scarcity-adjusted
  WAR (`best_adj` at MLB, `0.85·best_adj + 0.15·bestP_adj` below).

- **McCabe (Future Sim, ATL):** elite single-position bat (wOBA=.328
  1B-only) cascaded down to AAA starter because his overall WAR (1.21)
  loses to McKinstry's utility-versatility WAR (1.49). His .328 bat is
  wasted at AAA while McKinstry holds the MLB Best bat seat with .308.
  The user wants McCabe on the MLB bench as Best bat — not solvable by
  tuning cascade priority because the conflict is real (overall WAR vs
  bat-only). Needs either a Best-bat pull-up pass or the architectural
  rewrite below.

- **General:** every time a cascade ordering produces a counter-intuitive
  result, we add another repair pass. The repair-pass logic is now
  hundreds of lines and hard to reason about (see `main()` lines
  ~740-870 for HP enforcement; ~1080-1300 for various refinement
  passes).

## Proposed architecture: top-down construction

Invert the order. Build each level from the **whole remaining org pool**,
cascading only what's not selected:

```python
def main(org):
    pool = filter_complex_and_injured(load_org_players(org))
    pool = pin_hps_to_dev_level(pool)   # HPs locked to their dev level

    rosters, available = {}, list(pool)
    for level in LEVELS:                # MLB → AAA → AA → A+ → A → R → R(DLR)
        eligible = [p for p in available
                    if level_in_window(p, level)
                    and not pinned_elsewhere(p, level)]
        starters = fill_starters(eligible, level)
        bench    = classify_bench(eligible - starters.values(), level,
                                  cap=BENCH_SIZE[level])
        rosters[level] = {'starters': starters, 'bench_roles': bench}
        available -= (starters.values() | bench-picked players)
    overflow = available                 # release pool
    return rosters, overflow
```

### Wins from the inversion

- **McCabe case** solved naturally: MLB construction sees the whole org
  pool, so the wOBA-only Best bat criterion picks McCabe over McKinstry.
- **Tavarez case** still works: MLB and AAA SS slots get taken by Rojas
  (best best_adj) and Espinoza (next best); when we hit AA, Tavarez's
  sum-of-IF-positional-WAR cleanly beats Dixon Williams's.
- **No more repair passes.** Pull-up, push-down, HP enforcement,
  swingman, rescue — all gone. One construction step per level.
- **Cascade-priority tuning becomes irrelevant.** The construction at
  each level decides who's at that level; there's no cross-level
  priority comparison.

### Things to handle carefully

1. **HP dev routing.** A 19-year-old HP whose current bat clears MLB
   threshold would get picked for MLB Best bat under naive inversion,
   which is wrong — they need at-bats at their dev level, not pinch-hit
   reps in MLB. Solution: a pre-pass that pins each HP to their dev
   level (their `_bot` minus development runway). Pinned HPs are
   excluded from higher-level construction.

2. **Bench size cap.** Today the "Depth" tail of `classify_bench` is
   unbounded — every leftover from `fill_starters` becomes Depth. Under
   top-down inversion that would mean MLB grabs the entire org as bench
   depth. Need explicit `BENCH_SIZE[level]` caps (or
   `ROSTER_SIZE[level] - 9`, where 9 is the starter count). Already
   exists as `ROSTER_SIZES_HITTER` in config — use it.

3. **Two-way (Ohtani).** Currently admitted to both pools via
   `is_two_way` flag. Under inversion: same flag, same admission, but
   needs to be respected during the construction pool filtering.

4. **R(DLR) sub-team split.** Today R(DLR) is split into multiple
   DSL teams (R(DLR)1, R(DLR)2…) based on DSL team count. The
   sub-team selection happens late in `main()`. Need to preserve this
   under inversion — probably as a special-case at the R(DLR) iteration.

5. **Sub-floor protection.** Currently `_top` gates a sub-floor player
   from being at MLB. Under inversion the eligibility filter
   (`level_in_window`) does the same job — should be fine.

6. **Service-time off-by-one.** Today `reader._detect_as_of_year` fixes
   the mid-season service-time over-counting. Still applies — `_bot`
   computation is unchanged.

7. **Two-way SP-restrict (`_restrict_two_way_sp_to_dh`).** Still in
   `main.py`, runs before build_system sees the data. No changes needed.

### What the rewrite does NOT cover

- Pitcher side (`build_pitcher_system_v3`) keeps its current cascade.
  Same inversion would apply, but do it as a follow-up commit after
  the hitter side is stable.
- Two-way admission logic in main.py is untouched.
- Metrics pipeline (`metrics_hitting`, `metrics_pitching_v2`, etc.) is
  untouched.

## Implementation outline

Roughly 4 phases:

1. **Add the new flow alongside the old.** New function
   `_top_down_construct(org, pool)` in `build_system.py`. Behind a
   `config.BUILD_TOP_DOWN = False` flag initially. Old `main()`
   unchanged.
2. **Wire up the HP pre-pin pass.** Walk HPs, pin each to their dev
   level. Excluded from higher-level construction pools.
3. **A/B test on canonical saves** (Rockies Rebuild, Future Sim, CWS
   Dynasty). Compare per-org rosters; look for regressions vs.
   improvements. Tavarez and McCabe should both end up correctly placed.
4. **Flip the flag, remove the old cascade + repair passes.** Update
   `tests/test_roster_invariants.py` for legitimately-changed
   placements. Delete dead code (cascade, pull-up, push-down,
   swingman, rescue, HP enforcement).

Estimated touch: ~1,500 lines of `build_system.py` deleted, ~300 added.
Net simpler. Test diff probably 50-100 placement changes per save —
walk each and verify.

## Files to read before starting

- `build_system.py` — current cascade + construction. Main entry point
  is `main(org)`; cascade logic lives in `_filter_complex_and_injured`,
  `_compute_top_bot`, the various passes in `main()`.
- `build_pitcher_system_v3.py` — already partially uses a similar
  "no `_top` gate, just `_bot`" pattern. Reference for shape.
- `tests/test_roster_invariants.py` — 372 tests, mostly checking
  per-org `placed + overflow + flagged == loaded`. Most should still
  pass post-rewrite; some specific placement assertions may need
  updating.
- `roster_common.py` — shared `LEVELS`, `MAX_AGE`, `SERVICE_LIMITS`,
  `age_lowest_level`, etc. Stays put.
- `config.py` — `ROSTER_SIZES_HITTER`, `WOBA_MIN_HITTER`, HP constants.
  Stays put.

## Open questions for the rewrite session

- Should HP pre-pinning be exact (single level) or a window (HP can
  play at dev level ± 1)? Today HPs have an implicit window via
  cascade; inversion may need it explicit.
- Bench size: hard cap or soft (overflow allowed)? Probably hard with
  explicit overflow at every level.
- Best-bat seat: literally pure wOBA, or wOBA with a small
  defensive-not-disastrous gate (so a -3 WAR glove can't be MLB Best
  bat even with a .350 bat)? Today there's no such gate. Maybe add.
