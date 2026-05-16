"""End-to-end roster-builder invariant tests.

This suite locks in the placement correctness that today's pipeline
produces. Every recent user-spotted bug — Soderstrom (Step-4 displacement),
Heineman (Backup C refinement gap), Adrian Rodriguez (`_bot` enforcement
holes) — would have been caught here. Running the harness across all
30 MLB orgs after any builder change tells you immediately whether
the change introduced a regression.

How to run:
    pytest tests/                       # full suite (~60s, all 30 orgs)
    pytest tests/ -k hitter             # hitter invariants only
    pytest tests/ -k 'svc or top'       # eligibility-window invariants only
    pytest tests/ -k OAK                # one org's invariants only

Each test is parametrized over the org list discovered from
outputs/hitters.json (see conftest.py). A failing test names the org
and the offending player(s) directly so the regression is debuggable
without re-running anything.

The tests assume `outputs/hitters.json` and `outputs/pitchers.json`
exist (i.e. the pipeline has been run at least once). They're skipped
automatically if the JSONs are missing.
"""
import json

from build_system import (
    LEVELS as H_LEVELS,
    is_high_potential,
    total_service_years,
)
from build_pitcher_system import is_high_potential_pitcher, is_sp_viable


def _level_index(lvl_name):
    """Map a roster key to its base LEVELS index. R(DLR) sub-team keys
    (R(DLR)1, R(DLR)2 from the multi-DSL split) collapse to the R(DLR)
    base level."""
    base = lvl_name if lvl_name in H_LEVELS else 'R(DLR)'
    return H_LEVELS.index(base)


# =============================================================================
# HITTER INVARIANTS
# =============================================================================

def test_hitter_no_service_violations(org, hitter_results):
    """No hitter is placed at level i where i > _bot.

    `_bot` combines age, service-time, and DSL-eligibility floors — the
    most restrictive wins. Violation means a player is below the lowest
    level they're allowed to play at, e.g. a service-exhausted player at
    R when service blocks R/R(DLR).

    Bug pattern caught: Adrian Rodriguez (AZ, svc=4, _bot=A) was being
    placed at R via Step-4 utility refinement that didn't check _bot.
    Three demote sites in main() needed the same fix; this catches a
    regression at any of them.
    """
    rosters, _, _ = hitter_results[org]
    violations = []
    for lvl_name, r in rosters.items():
        i = _level_index(lvl_name)
        for p in r['all']:
            bot = p.get('_bot')
            if bot is not None and i > bot:
                violations.append(
                    f"  {p['name']} at {lvl_name} (i={i}); "
                    f"_bot={H_LEVELS[bot]} (i={bot}); "
                    f"svc={total_service_years(p)}, age={p['age']}"
                )
    assert not violations, (
        f"{org} hitter service-floor violations:\n" + "\n".join(violations)
    )


# NOTE: `test_hitter_no_top_violations` was retired 2026-05-10. It used
# to enforce strict `_top <= i` (no wOBA stretch above the player's
# qualifying level). Step 3.6 PASS 3 (release-pool push-down) now
# intentionally relaxes that — under-filled levels accept any overflow
# body whose `_bot` permits it, regardless of `_top`. The
# `test_hitter_no_service_violations` test above already enforces `_bot`,
# which is the OOTP hard rule and the only invariant that still matters.


def test_hitter_no_over_capacity(org, hitter_results):
    """No level's hitter roster exceeds its target capacity.

    Targets are `ROSTER_SIZES[lvl]` with R(DLR) scaled by the org's DSL
    team count (`compute_roster_sizes`). HP demote-without-swap and
    Step-4 refinement can grow a level temporarily; Step 3.5 / 3.6 / 4.6
    rebalance passes are supposed to bring it back to target. Violation
    means one of those rebalance passes failed.
    """
    rosters, _, _ = hitter_results[org]
    violations = [
        f"  {lvl}: {len(r['all'])} hitters > target {r['target']}"
        for lvl, r in rosters.items()
        if len(r['all']) > r['target']
    ]
    assert not violations, (
        f"{org} hitter rosters over capacity:\n" + "\n".join(violations)
    )


def test_hitter_hp_no_double_count(org, hitter_results):
    """Each high-potential hitter appears on exactly one level's roster.

    HP enforcement does swaps (HP up, non-HP down) and demote-without-swap
    paths — both are sites where a faulty add-without-remove could leave
    an HP duplicated across two levels. Catches that class of bug.
    """
    rosters, _, _ = hitter_results[org]
    seen = {}
    for lvl_name, r in rosters.items():
        for p in r['all']:
            if is_high_potential(p):
                seen.setdefault(p['name'], []).append(lvl_name)
    duplicates = {n: lvls for n, lvls in seen.items() if len(lvls) > 1}
    assert not duplicates, f"{org} HP hitters on multiple levels: {duplicates}"


def test_hitter_no_lost_players(org, hitter_results, org_loaded_counts,
                                  org_complex_counts):
    """placed + overflow + flagged + complex-filtered == loaded org size.

    Step 0 of main() filters international-complex players (minor=0 AND
    age<20) — those never appear in rosters, overflow, OR flagged, so
    the test counts them from the raw JSON as a separate bucket.

    Catches: any code path that drops a player on the floor (e.g. a swap
    that removes from one list but fails to re-add to another).
    """
    rosters, overflow, flagged = hitter_results[org]
    placed = sum(len(r['all']) for r in rosters.values())
    h_loaded, _ = org_loaded_counts[org]
    h_complex, _ = org_complex_counts[org]
    accounted = placed + len(overflow) + len(flagged) + h_complex
    assert accounted == h_loaded, (
        f"{org} hitter accounting mismatch: "
        f"placed={placed} + overflow={len(overflow)} + flagged={len(flagged)} "
        f"+ complex={h_complex} = {accounted}, but loaded={h_loaded} "
        f"(diff: {h_loaded - accounted})"
    )


def test_hitter_mlb_filled_to_13(org, hitter_results):
    """Every org's MLB hitter roster has exactly 13 players.

    13 is the MLB position-player count (2 catchers + 5 IF + 4 OF + DH +
    bench). A short MLB suggests Step 3.6 backfill or Step 4 refinement
    failed to find enough wOBA-eligible candidates — usually a sign of
    a bigger upstream issue.
    """
    rosters, _, _ = hitter_results[org]
    mlb_size = len(rosters.get('MLB', {}).get('all', []))
    assert mlb_size == 13, (
        f"{org} MLB hitter roster has {mlb_size} players, expected 13"
    )


# =============================================================================
# PITCHER INVARIANTS
# =============================================================================

def test_pitcher_no_service_violations(org, pitcher_results):
    """No pitcher is placed at level i where i > _bot.

    Pitcher cascade, pull-up, handedness-balance, and Step-4c rebalance
    all check _bot today — this test locks that in. Same shape as the
    hitter invariant.
    """
    rosters, _, _ = pitcher_results[org]
    violations = []
    for lvl_name, r in rosters.items():
        i = _level_index(lvl_name)
        for p in r.get('all', []):
            bot = p.get('_bot')
            if bot is not None and i > bot:
                violations.append(
                    f"  {p['name']} at {lvl_name} (i={i}); "
                    f"_bot={H_LEVELS[bot]} (i={bot}); age={p['age']}"
                )
    assert not violations, (
        f"{org} pitcher service-floor violations:\n" + "\n".join(violations)
    )


# NOTE: `test_pitcher_top_within_one_stretch` was retired 2026-05-10.
# `_push_down_from_overflow` (the pitcher PASS 3 release-pool push-down)
# intentionally allows unlimited `_top` stretch — under-filled SP/RP
# slots accept any release-pool arm whose `_bot` permits it. `_bot`
# (age + service) is still enforced via the existing pitcher tests
# below, which is the OOTP hard rule.


def test_pitcher_no_over_capacity(org, pitcher_results):
    """No level's SP or RP roster exceeds its per-level target.

    Targets come from the SP_PER_LEVEL / RP_PER_LEVEL constants, with
    R(DLR) scaled by DSL team count. The Step-4c rebalance after LHP
    handedness adjustment is the most common site that could overrun;
    this test catches that.
    """
    rosters, _, _ = pitcher_results[org]
    violations = []
    for lvl_name, r in rosters.items():
        if len(r.get('starters', [])) > r.get('sp_target', 0):
            violations.append(
                f"  {lvl_name} SP: {len(r['starters'])} > target {r['sp_target']}"
            )
        if len(r.get('bullpen', [])) > r.get('rp_target', 0):
            violations.append(
                f"  {lvl_name} RP: {len(r['bullpen'])} > target {r['rp_target']}"
            )
    assert not violations, (
        f"{org} pitcher rosters over capacity:\n" + "\n".join(violations)
    )


def test_pitcher_sp_stamina_gate(org, pitcher_results):
    """Every placed SP must be `is_sp_viable` (sp_warP is not None).

    Stamina itself isn't persisted to outputs/pitchers.json — the metrics
    layer applies SP_WAR_MIN_STAMINA as a NaN-gate on sp_war / sp_warP,
    so post-pipeline the invariant becomes `sp_warP is not None`.
    `is_sp_viable(p)` is exactly that test. A violation means an arm
    that the metrics layer judged unable-to-start somehow ended up in
    the rotation.
    """
    rosters, _, _ = pitcher_results[org]
    violations = []
    for lvl_name, r in rosters.items():
        for p in r.get('starters', []):
            if not is_sp_viable(p):
                violations.append(
                    f"  {p['name']} at {lvl_name} SP, sp_warP={p.get('sp_warP')!r} "
                    f"(stamina-gated NaN — should not be in rotation)"
                )
    assert not violations, (
        f"{org} SPs below stamina gate:\n" + "\n".join(violations)
    )


def test_pitcher_hp_no_double_count(org, pitcher_results):
    """Each high-potential pitcher appears on exactly one level's roster.

    Mirror of the hitter HP test. Pitcher HP enforcement (`_enforce_hp_pitchers`)
    does displacement swaps; this catches add-without-remove regressions.
    """
    rosters, _, _ = pitcher_results[org]
    seen = {}
    for lvl_name, r in rosters.items():
        for p in r.get('all', []):
            if is_high_potential_pitcher(p):
                seen.setdefault(p['name'], []).append(lvl_name)
    duplicates = {n: lvls for n, lvls in seen.items() if len(lvls) > 1}
    assert not duplicates, f"{org} HP pitchers on multiple levels: {duplicates}"


def test_pitcher_no_lost_players(org, pitcher_results, org_loaded_counts,
                                   org_complex_counts):
    """placed + overflow + flagged + complex-filtered == loaded pitcher count.

    Same accounting shape as the hitter version. Catches: lossy code
    paths in cascade / pull-up / LHP balance / HP enforcement that
    remove a pitcher from one list and fail to re-add elsewhere.
    """
    rosters, overflow, flagged = pitcher_results[org]
    placed = sum(len(r.get('all', [])) for r in rosters.values())
    _, p_loaded = org_loaded_counts[org]
    _, p_complex = org_complex_counts[org]
    accounted = placed + len(overflow) + len(flagged) + p_complex
    assert accounted == p_loaded, (
        f"{org} pitcher accounting mismatch: "
        f"placed={placed} + overflow={len(overflow)} + flagged={len(flagged)} "
        f"+ complex={p_complex} = {accounted}, but loaded={p_loaded} "
        f"(diff: {p_loaded - accounted})"
    )


def test_pitcher_lhp_balance(org, pitcher_results):
    """For every full MLB / AAA / AA bullpen, LHP count is in [2, 4]
    OR a sign_lhp shortfall accounts for the gap.

    LEFTY_MIN=2, LEFTY_MAX=4 (LEFTY_TARGET=3 is soft). The hard MIN
    swap-in passes use STRICT eligibility (no +1 stretch); if no
    qualified LHP exists we drop a worst-priority RHP and tag the slot
    as `sign_lhp`. A bullpen with len < target gets skipped (under-fill
    indicates a different problem already). HARD MAX (>4 LHP) should
    NEVER occur — that's the assertion.

    KNOWN FAILURE — TB / AZ rotating data-drift flake at AAA (sometimes
    AA): the LHP-balance re-enforcement after rescue / push-down
    produces a full bullpen with 1 LHP and `sign_lhp=0` even though
    plenty of LHP candidates exist in the org pool. Root cause is in
    `_enforce_lhp_balance`s interaction with the R-28 rescue pass and
    is a real (small-magnitude) bug, not a test issue. Recorded as a
    known failure in HANDOFF so test runs match the documented status;
    a proper fix would address the LHP-balance pass directly.
    """
    rosters, _, _ = pitcher_results[org]
    violations = []
    for lvl in ('MLB', 'AAA', 'AA'):
        r = rosters.get(lvl)
        if r is None:
            continue
        bullpen = r.get('bullpen', [])
        n_lhp = sum(1 for p in bullpen if p.get('throws') == 2)
        if n_lhp > 4:
            violations.append(
                f"  {lvl}: {n_lhp} LHP in bullpen (LEFTY_MAX=4)"
            )
            continue
        target = r.get('rp_target', 8)
        if len(bullpen) < target:
            continue
        if r.get('sign_lhp', 0) > 0:
            continue
        if n_lhp < 2:
            violations.append(
                f"  {lvl}: {n_lhp} LHP in bullpen (LEFTY_MIN=2), "
                f"sign_lhp shortfall=0 (no excuse)"
            )
    assert not violations, (
        f"{org} bullpen LHP balance violations:\n" + "\n".join(violations)
    )


def test_pitcher_role_distribution(org, pitcher_results):
    """Each level's roster respects SP_PER_LEVEL[lvl] / RP_PER_LEVEL[lvl]:
    either exactly at target, or under-target with a clearly-recorded
    `sign_lhp` shortfall on the RP side. Over-target is always a bug —
    cascade and rebalance loops should have prevented it.

    Was missing before R-33: a bug in the swingman pull-up or the rescue
    pass could have produced an over-target bullpen and the test would
    pass anyway (only `test_pitcher_capacity` and `test_pitcher_lhp_balance`
    looked at full-level totals, not the role split).
    """
    from config import SP_PER_LEVEL, RP_PER_LEVEL
    rosters, _, _ = pitcher_results[org]
    violations = []
    for lvl, r in rosters.items():
        # Strip R(DLR) sub-team suffix (R(DLR)1, R(DLR)2) for the lookup.
        base_lvl = 'R(DLR)' if str(lvl).startswith('R(DLR)') else lvl
        sp_target = SP_PER_LEVEL[base_lvl]
        rp_target = RP_PER_LEVEL[base_lvl]
        n_sp = len(r.get('starters', []))
        n_rp = len(r.get('bullpen', []))
        if n_sp > sp_target:
            violations.append(f"  {lvl}: SP {n_sp} > target {sp_target}")
        if n_rp > rp_target:
            violations.append(f"  {lvl}: RP {n_rp} > target {rp_target}")
    assert not violations, (
        f"{org} pitcher role-distribution violations:\n" + "\n".join(violations)
    )
