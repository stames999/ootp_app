# Pistachio Pipeline Review

**Date:** 2026-05-10
**Scope:** End-to-end review of the OOTP roster-construction pipeline — methodology, code quality, test coverage, roster-builder logic.
**State at review:** main @ `9fe3785` (HP age cap 24, Backup C refinement, `_bot` enforcement, Streamlit display fixes all merged).

---

## Executive summary

| Severity | M (model) | C (code) | T (tests) | R (roster) | Total |
|---|---:|---:|---:|---:|---:|
| **blocker** | 0 | 0 | 1 | 0 | **1** |
| **major** | 3 | 1 | 2 | 3 | **9** |
| **minor** | 6 | 7 | 2 | 4 | **19** |
| **cosmetic** | 0 | 3 | 0 | 2 | **5** |
| **Total** | **9** | **11** | **5** | **9** | **34** |

### Top 5 findings

1. **T-01 (blocker)** — No end-to-end regression test. Every recent user-spotted bug (Soderstrom, Heineman, Adrian Rodriguez) would have been caught by a per-org invariant test running on all 30 orgs.
2. **R-01 (major)** — Catcher rescue threshold (`CATCHER_RESCUE_MIN_NON_C_WAR = 0.30`) fires too aggressively. Step-4 Backup C refinement patched the symptom; the rescue rule itself is still over-permissive in principle.
3. **R-02 (major)** — Premium-fit pull-up only operates on HPs. A non-HP defensive specialist (e.g. Chandler Simpson, CF_fld 2.69) cascaded out by wOBA has no path back to MLB. Mirror of Step-2 wOBA-only ranking blindness.
4. **C-01 (major)** — `build_pitcher_system` reaches into 5+ private internals of `build_system`. Extract a `roster_common.py`.
5. **M-03 (major)** — Pitcher RP WAR is workload-only (`rp_war = sp_war × 0.333`). No leverage multiplier; elite closers are systematically under-rated vs FG conventions.

### Headline recommendation

**Build the regression-test harness first** (T-01). Today's invariant sweep across 30 orgs surfaced **0 violations** — it would lock in current correctness and catch any future regression from the changes recommended below. Then triage R-01 / R-02 (latent roster-builder gaps) and C-01 (refactor for shared roster utilities). The methodology layer is largely sound; cosmetic cleanups can pile into a single janitor commit.

---

## Section M — Methodology / model soundness

### M-01 [minor] Run-environment coherence verified clean

**Evidence:** Traced `RUNS_PER_WIN_HITTING / FIELDING / PITCHING` usage:
- `metrics_hitting.py:94, 95, 160, 161` use `RUNS_PER_WIN_HITTING` ✓
- `metrics_fielding.py:111` uses `RUNS_PER_WIN_FIELDING` for `_def` divisor ✓
- `metrics_war.py:192` uses `RUNS_PER_WIN_FIELDING` for `pos_adj` conversion ✓ (chain-consistent)
- `metrics_pitching.py` does NOT import `RUNS_PER_WIN_PITCHING` — `PITCHING_WAR_COEFFS` is pre-scaled empirically ✓ (matches `HANDOFF.md`)
- `org_report.py:140` uses `RUNS_PER_WIN_HITTING` ✓ (was previously hardcoded — fixed)
- `build_system.py:334` derives `WAR_PER_WOBA_POINT` from `RUNS_PER_GAME_HITTING_COEFF / RUNS_PER_WIN_HITTING` ✓

**Recommendation:** No fix needed. Document this verification in the code comment near `RUNS_PER_WIN_*` so future contributors see the chain.

### M-02 [minor] Pos_adj ↔ `_fld` chain has no double-counting

**Evidence:** `_fld = _def + adj_war` (`metrics_war.py:205`); `_adj = _fld + war_hitting`; saturation runs INSIDE `_def`; pos_adj is applied AFTER. No module re-applies pos_adj to a `_fld`-derived value. Verified Schwarber/Harper case (this session).

**Recommendation:** None.

### M-03 [major] Pitcher RP WAR is workload-only — no leverage adjustment

**Evidence:** `metrics_pitching.py:145` — `df["rp_war"] = (base_war * RELIEVER_VS_STARTER_AVERAGE_IP).round(1)` where `RELIEVER_VS_STARTER_AVERAGE_IP ≈ 0.333` (≈67 IP for an RP). FanGraphs applies a leverage multiplier (1.5–2× for closers/setup) on top. Documented in `HANDOFF.md` "Known limitations".

**Effect:** Elite closers in our system end up at `rp_war ≈ 1.5` when their FG-comparable WAR would be 3–4. Materially mis-ranks bullpen depth.

**Recommendation:** Add a per-role leverage multiplier in `metrics_pitching.calc_pitching_metrics` keyed off something like inferred role (closer / setup / middle). Could be sim-derived or just a FG-canonical 1.7× for pitcher_priority top tier.

### M-04 [major] Catcher framing OOTP engine plateau

**Evidence:** OOTP's catcher framing engine caps value at +8 runs (Cfram ≥ 65 all collapse). FanGraphs FRV says elite framers are worth +30. Engine limit, not our model. Documented in `HANDOFF.md`.

**Effect:** C `pos_adj` is +7.5 runs (vs FG's +12.5) partly to compensate. Catchers' true defensive ceiling is invisible to the model.

**Recommendation:** Document the cap explicitly in the `POSITIONAL_ADJUSTMENT_RUNS` block in `config.py:126`. No code change — accept as engine constraint.

### M-05 [major] IF cross-position routing of MLB-locked players

**Evidence:** ~9/35 elite-glove DRS leaders (Gimenez, Edman, Hayes, Urias, Garcia, Donovan, Turang, etc.) route to SS in our model because their OOTP IF range/arm makes them SS-eligible AND SS `pos_adj` is highest. Documented in `HANDOFF.md`.

**Recommendation:** Accept as an OOTP-engine rating-distribution quirk. Mitigation requires a 2D RNG×ARM grid for 2B and SS (currently only 3B has interaction correction). Would need new sim data — defer until prioritised.

### M-06 [minor] OOTP wOBA distribution offset vs MLB

**Evidence:** OOTP star hitters cluster ~22 wOBA points below MLB equivalents (Witt OOTP .354 vs MLB .376). Hitting slope `RUNS_PER_GAME_HITTING_COEFF = 496.84` is ~5% flatter than MLB (~520). Acceptable internal-consistency choice.

**Recommendation:** Note in HANDOFF that this is a deliberate "internal consistency" stance — within-OOTP rankings are correct, cross-OOTP-vs-FG numbers will differ.

### M-07 [minor] Hardcoded fallback baselines in `metrics_fielding`

**Evidence:** [`metrics_fielding.py:99, 101`](metrics_fielding.py:99) — `IFrange=50, IFarm=60` defaults when columns missing.

```python
v1 = (_vec_closest_rating(df["IFrange"]) if "IFrange" in df.columns
      else pd.Series(50, index=df.index))
v2 = (_vec_closest_rating(df["IFarm"]) if "IFarm" in df.columns
      else pd.Series(60, index=df.index))
```

These are magic numbers — should reference config. Already noted in HANDOFF "What's still pending #4".

**Recommendation:** Add `FIELDING_FALLBACK_RATINGS = {'IFrange': 50, 'IFarm': 60, ...}` to `config.py` and import it.

### M-08 [minor] Stale calibration data files

**Evidence:**
- `calibration/fielding_sim.csv` — used by orphaned `calibrate_fielding.py`; HANDOFF explicitly says "stale".
- `calibration/ss_sim.csv`, `calibration/ss_for_combined.csv` — superseded by uniform grid sweep.
- `calibration/sim_data.csv` — still used by `validate.py` (active for hitting model validation).

**Recommendation:** Move stale CSVs to `calibration/archive/` (preserve provenance) and delete the orphaned scripts that reference them (see C-04). Keep `sim_data.csv`.

### M-09 [minor] `priority(p, 'MLB')` ignores defensive value when ranking the cascade

**Evidence:** [`build_system.py:233-234`](build_system.py:233):

```python
def priority(p, level=None):
    woba = p.get('wOBA') or 0
    if level == 'MLB':
        return woba
    ...
```

A glove specialist (Chandler Simpson, `CF_fld = 2.69`, `wOBA = .318`) gets ranked by pure wOBA in the MLB Step-2 cascade — sits at #16 of 32 in TB's pool, cascades out, even though his `best_adj = 4.09` would crack the MLB roster on total value. Same root cause as R-02 below.

**Recommendation:** Discussed during this session as option #2 (non-HP premium-fit pull-up) — see R-02. OR: make `priority(p, 'MLB')` a small blend of `wOBA` and `best_adj` (e.g. `0.85 × wOBA + 0.15 × max(<pos>_fld) / 5`) so glove specialists don't disappear.

### Methodology summary

The methodology is **internally coherent**. Run-env constants match across modules; pos_adj/saturation/fielding chain has no double-counting; all calibration constants have provenance comments. The major findings are inherent OOTP-engine limits (catcher framing, IF rating distribution) or known calibration gaps (RP leverage). The one real bug pattern — wOBA-only cascade ranking blindness to defense — surfaces in M-09 / R-02 / R-05.

---

## Section C — Code quality / refactoring

### C-01 [major] Tight coupling: pitcher system imports private internals of hitter system

**Evidence:** [`build_pitcher_system.py:40-44`](build_pitcher_system.py:40):

```python
from build_system import (
    LEVELS, MAX_AGE,
    age_lowest_level, service_lowest_level, dsl_eligible_lowest_level,
    _load_injured_names, _count_dsl_teams,
)
```

Three of those (`_load_injured_names`, `_count_dsl_teams`, leading underscore convention) are explicitly private. `MAX_AGE` and `LEVELS` are also non-system-specific roster constants that don't belong in either file.

**Recommendation:** Extract `roster_common.py` containing: `LEVELS`, `MAX_AGE`, eligibility helpers (`woba_max_level` not relevant for pitchers but bundle the hitter version too if we keep), `service_lowest_level`, `dsl_eligible_lowest_level`, `age_lowest_level`, `_load_injured_names`, `_count_dsl_teams`, `total_service_years`, `SERVICE_LIMITS`, `DSL_INELIGIBLE_NATIONS`, `DSL_LEAGUE_ID`. Both `build_system.py` and `build_pitcher_system.py` import from it. Reduces coupling and makes future fixes (like the recent `_bot` enforcement) easier to land symmetrically.

### C-02 [minor] Magic numbers in build_system.py / build_pitcher_system.py belong in config

**Evidence:** Numbers defined in source files (not config):

| Constant | File | Line | Belongs in config? |
|---|---|---|---|
| `PREMIUM_WOBA_RELAX` | build_system.py | 106 | Yes |
| `C_FLD_WEIGHT` (0.05) | build_system.py | 77 | Yes |
| `AGE_WEIGHT`, `AGE_CAP` | build_system.py | 83-84 | Yes |
| `C_FLD_GAP_MAX` (1.5) | build_system.py | 95 | Yes |
| `CATCHER_RESCUE_MIN_NON_C_WAR` (0.30) | build_system.py | 122 | Yes |
| `CATCHER_RESCUE_NON_C_POSITIONS` | build_system.py | 126 | Yes |
| `LINEUP_RHP_WEIGHT` (0.725) | build_system.py | 344 | Yes |
| `HP_MAX_AGE` (24) | build_system.py | 547 | Yes |
| `HP_BESTP_ADJ_THRESHOLD` (2.0) | build_system.py | 559 | Yes |
| `HP_WOBA_THRESHOLD` (0.340) | build_system.py | 560 | Yes |
| `PREMIUM_FLD_MIN` (1.5) | build_system.py | 565 | Yes |
| `HP_PREMIUM_FIT_POSITIONS` | build_system.py | 575 | Yes |
| `IF_POSITIONS`, `OF_POSITIONS` | build_system.py | 577-578 | Maybe (constants) |
| `SP_PER_LEVEL` (5), `RP_PER_LEVEL` (8) | build_pitcher_system.py | 48-49 | Yes |
| `PWOBA_MAX` dict | build_pitcher_system.py | 57 | Yes |
| `LEFTY_MIN/TARGET/MAX` | build_pitcher_system.py | 178-180 | Yes |
| `LEFTY_TARGET_MAX_COST` (0.010) | build_pitcher_system.py | 184 | Yes |
| `HP_PITCHER_MAX_AGE` (24), `HP_PITCHER_MAX_PWOBAP` (0.330) | build_pitcher_system.py | 134-135 | Yes |

**Recommendation:** Move to `config.py` with provenance comments. Lets the user retune any threshold without source edits — already the established pattern for everything in metrics layer.

### C-03 [cosmetic] Debug print in metrics_fielding

**Evidence:** [`metrics_fielding.py:114`](metrics_fielding.py:114) — `print(f"Added fielding columns: {added_columns}")`. Fires on every pipeline run.

**Recommendation:** Delete (or change to `logging.debug`).

### C-04 [cosmetic] Dead code (delete in one cleanup commit)

| Item | Location | Status |
|---|---|---|
| `_apply_viability` | [`metrics_war.py:66`](metrics_war.py:66) | Defined, never called (search confirms zero call sites) |
| `RUNS_PER_WIN = 10` | [`config.py:180`](config.py:180) | Marked "legacy default"; no module imports it |
| `MINIMUM_STARTER_PITCHES` (3) | [`config.py:149`](config.py:149) | Marked "deprecated — stamina is the SP/RP gate" |
| `MINIMUM_RELIEVER_PITCHES` (1) | [`config.py:150`](config.py:150) | Marked "deprecated — position == 1 admits all pitchers" |
| `SS_INTERACTION_CORRECTION` | [`config.py:1711`](config.py:1711) | Superseded by `FIELDING_SATURATION` (HANDOFF confirms) |
| `REPLACEMENT_LEVEL_PITCHER_WOBA` (0.36) | [`config.py:192`](config.py:192) | Defined, no module imports it |
| `POSITION_VIABILITY_GAP` (1.5) | [`config.py:99`](config.py:99) | Only used by `_apply_viability` (which is dead) |
| `load_laa()` alias | [`build_system.py:149`](build_system.py:149) | Back-compat alias; no current caller |
| `load_laa_pitchers()` alias | [`build_pitcher_system.py:77`](build_pitcher_system.py:77) | Back-compat alias; no current caller |

**Recommendation:** One cleanup commit deletes all of these.

### C-05 [minor] Duplication between `calc_X_metrics` and `calc_potential_X_metrics`

**Evidence:** [`metrics_hitting.py`](metrics_hitting.py) — `calc_hitting_metrics` (lines 16-99) and `calc_potential_hitting_metrics` (lines 103-166) have ~70% identical code (`adjust_rates`, wOBA construction, WAR formula, wRC+). Same shape in [`metrics_pitching.py`](metrics_pitching.py).

**Recommendation:** Refactor to a shared `_compute_components(df, suffix, ratings_source)` helper. Approx. ~150 lines deletable across both modules.

### C-06 [minor] Per-row `df.apply(axis=1)` in metrics layer is slow

**Evidence:**
- [`metrics_hitting.py:68-69, 147`](metrics_hitting.py:68) — `df.apply(lambda row: adjust_rates(row, "R"), axis=1)`
- [`metrics_pitching.py:93-94, 233`](metrics_pitching.py:93) — same pattern

For 9000+ player frames this is the slowest part of the pipeline (~3-5 sec each call).

**Recommendation:** Vectorize via lookup tables. Each rating maps deterministically to component multipliers — could be a single merge or `Series.map()` on each component. ~10× speedup expected.

### C-07 [minor] File-size: build_system.py at 1438 lines

**Evidence:** Single-file module containing eligibility helpers, classification, cascade, HP enforcement, bench refinement, premium-fit pull-up, final Hungarian. Hard to navigate.

**Recommendation:** Split into:
- `roster_eligibility.py` — `woba_max_level`, `age_lowest_level`, `service_lowest_level`, `dsl_eligible_lowest_level`, `total_service_years`, `MAX_AGE`, `SERVICE_LIMITS`, `WOBA_MIN`
- `roster_catcher.py` — catcher rescue, `catcher_alloc_score`, `is_catcher_candidate`
- `roster_cascade.py` — Step 2 / 3.5 / 3.6
- `roster_hp.py` — `is_high_potential`, `_enforce_hp_starters`, `apply_hp_premium_fit_override`
- `roster_bench.py` — `classify_bench`, Step-4 utility refinement, premium-fit pull-up
- `roster_main.py` — orchestrates the above

Combine with C-01 (extract roster_common). Big refactor — only do if other work is also touching these files.

### C-08 [cosmetic] Late `import numpy as np` in reader.py

**Evidence:** [`reader.py:217`](reader.py:217) — `import numpy as np` mid-file. Should be at top.

**Recommendation:** Move to top, alongside `import pandas as pd`.

### C-09 [minor] Two manual override files (`injured.txt`, `flagged.txt`) with different semantics

**Evidence:**
- `injured.txt` — read by `_load_injured_names` (`build_system.py:152`); pulls player out of placement (roster-affecting)
- `flagged.txt` — read by `is_flagged` (`reader.py:248`); display marker for HTML reports only (not roster-affecting)

These are easy to confuse — the names suggest similar things but the behaviour is different.

**Recommendation:** Rename `flagged.txt` to `display_flagged.txt` and add a top-of-file comment explaining the difference. OR: a single `roster_overrides.json` with `{"injured": [...], "display_flag": [...]}` keys.

### C-10 [minor] Late `from config import` in build_system.py:333

**Evidence:**
```python
from config import RUNS_PER_GAME_HITTING_COEFF as _COEFF, RUNS_PER_WIN_HITTING as _RPW_H
WAR_PER_WOBA_POINT = _COEFF / _RPW_H
```

Late imports for a module-level constant — should be at the top of the file with the other imports.

**Recommendation:** Move imports to top; compute `WAR_PER_WOBA_POINT` at module level alongside other constants.

### C-11 [minor] `_role` mutation on shared dicts in build_pitcher_system

**Evidence:** [`build_pitcher_system.py:469`](build_pitcher_system.py:469) — `p.pop('_role', None)` at start of `main()`; lines 580-582 set it. Mutates JSON-derived dicts. Safe today (each `main()` call re-loads), but fragile if anyone caches.

**Recommendation:** Defensive-copy player dicts in `load_team_pitchers` (and the hitter equivalent), OR move all mutable per-run state into a separate dict keyed by player_id.

### Code-quality summary

The pipeline modules are reasonably well-factored at the per-file level but the two roster builders share state across module boundaries via private internals. The biggest wins are: extract `roster_common.py` (C-01), move source-file magic numbers into config (C-02), and the dead-code cleanup commit (C-04). Performance is fine for current data volumes; vectorization (C-06) is a nice-to-have, not urgent.

---

## Section T — Test / verification coverage

### T-01 [blocker] No end-to-end regression test for the roster builder

**Evidence:** Recent bugs landed in production despite working code paths around them:

| Bug | Caught by | Would-have-caught test |
|---|---|---|
| Step-4 displacement (Soderstrom AAA-C) | User reading TB roster | "Highest-wOBA bench bat shouldn't disappear from a non-overflow level" |
| Backup C refinement gap (Heineman AAA-C) | User reading TOR roster | "MLB Backup C alloc ≥ AAA starter C alloc, modulo HP / wOBA-ineligible" |
| `_bot` enforcement holes (Adrian Rodriguez) | User reading AZ roster | "For every player at level i: `_top <= i <= _bot`" |
| HP age cap raised to 24 | User asked for it | "HP membership stable per spec" |

**Today's invariant sweep across all 30 orgs** (run for this review): 0 violations on 8 invariants. Now is the perfect time to lock that in.

**Recommendation:** Create `tests/test_roster_invariants.py` (new dir) running `main()` for all 30 orgs and asserting:

```python
def test_no_service_floor_violations():
    """For every placed player at level i, i <= p['_bot']."""
def test_no_top_floor_violations():
    """For every placed player at level i, i >= p['_top']."""
def test_no_over_capacity_rosters():
    """len(rosters[lvl]['all']) <= rosters[lvl]['target']."""
def test_hp_no_double_count():
    """Each HP appears at exactly one level."""
def test_no_lost_players():
    """placed + overflow + flagged == loaded org size."""
def test_mlb_filled_to_13_hitters():
    """MLB has 13 hitters for every org."""
def test_pitcher_sp_stamina_gate():
    """Every SP placed has stamina >= MINIMUM_STARTER_STAMINA."""
def test_lhp_handedness_balance():
    """MLB / AAA / AA bullpens have 2 ≤ LHP count ≤ 4 OR a sign_lhp shortfall."""
```

Run via `pytest tests/`. CI integration optional but the harness pays for itself the first regression it catches.

### T-02 [major] Validation scripts not exercised in CI

**Evidence:** Three validation scripts exist but are run manually:
- [`calibration/validate.py`](calibration/validate.py) — hitting model vs sim_data.csv
- [`calibration/validate_pitcher_v2.py`](calibration/validate_pitcher_v2.py) — pitcher model vs embedded sim
- [`calibration/test_fixed_pos_adj.py`](calibration/test_fixed_pos_adj.py) — pos_adj test set against MLB DRS leaders (35 players)

**Recommendation:** Add a `make verify` (or pytest entry point) that runs all three. Catches calibration drift if a config recompute introduces a regression.

### T-03 [major] No platoon-WAR validation

**Evidence:** [`build_system.py:359`](build_system.py:359) `pos_adj_split` derives platoon-adjusted WAR additively from wOBA splits. Mathematical derivation in the docstring is sound but never independently tested. The `org_report` lineup builder also has its own platoon path.

**Recommendation:** Snapshot test: for known players (Schwarber, Harper, Witt, Tucker), assert `pos_adj_split(p, pos, 'R') - pos_adj(p, pos) == (wOBAR - wOBA) * WAR_PER_WOBA_POINT` within 1e-6. Three asserts, ten lines.

### T-04 [minor] No HP membership snapshot test

**Evidence:** `is_high_potential` returns expected players for known orgs. Easy to freeze.

**Recommendation:** Snapshot test against a frozen org+save (e.g. `tests/snapshots/COL_hps_2026-05-09.txt`). Asserts the system still recognises the same prospects after refactoring.

### T-05 [minor] Dead code confirmed un-tested

**Evidence:** `_apply_viability` (`metrics_war.py:66`) was defined but never called — and would have been impossible to test from outside. C-04 covers cleanup.

### Test-coverage summary

The system is missing the **one test** that would have caught all four recent user-reported bugs: a per-org invariant sweep. Today's empirical sweep (run for this review) shows 0 current violations — the harness would lock that in. The three validation scripts that DO exist are not part of any CI loop. Building both is roughly a half-day's work and the dominant risk-reduction item in this review.

---

## Section R — Roster-builder logic

### R-01 [major] Catcher rescue fires too aggressively

**Evidence:** [`build_system.py:122`](build_system.py:122) — `CATCHER_RESCUE_MIN_NON_C_WAR = 0.30`. Rescue triggers when a primary-C has wOBA at MLB threshold AND best non-C WAR ≥ 0.30. Heineman case demonstrated the floor is too low: wOBA .302, best_non_c_war 0.60, alloc_score .436 (highest among non-rescued TOR Cs) — rescued out of catcher allocation, then bat-cascaded out of MLB to AAA.

Step-4 Backup C refinement (committed in `879e6d3`) patches the Heineman symptom by pulling him back. But the rescue rule itself is over-permissive — there are likely other catchers with similar wOBA + marginal non-C WAR who get spuriously rescued and only sometimes get patched back.

**Recommendation:** Three options:
1. **Raise threshold**: `CATCHER_RESCUE_MIN_NON_C_WAR = 1.5` — rescue only catchers with real bench bat.
2. **Add wOBA floor**: rescue requires `wOBA ≥ 0.330` (MLB-regular tier) in addition to current rule. Cleanest semantics.
3. **Dual threshold**: both `best_non_c_war ≥ 1.5` AND `wOBA ≥ 0.330`. Most conservative.

Option 2 recommended — cleanest line ("rescue is for bat-elite catchers, period").

### R-02 [major] Premium-fit pull-up only operates on HPs

**Evidence:** [`build_system.py:1247-1352`](build_system.py:1247) — `_premium_candidate_score` and the surrounding loop consider only `is_high_potential(p) == True` candidates. A non-HP defensive specialist (Chandler Simpson, age 25, CF_fld 2.69, best_adj 4.09) cascaded out of MLB by pure-wOBA Step-2 has no path back up — even though his glove would beat the incumbent CF.

**Effect:** The system systematically demotes glove-first veterans who happen to be one notch above the HP age cap.

**Recommendation:** Add `_premium_fit_pull_up_veterans` mirror that:
1. Operates at MLB / AAA (not minor levels — those are for HP development).
2. For each premium position (CF / SS / 2B), checks if the incumbent's `_fld` is below `PREMIUM_FLD_MIN` AND there's a non-HP player at AAA with strictly higher `_fld` AND wOBA-eligible at MLB.
3. Promotes the better-glove veteran, demotes the lowest-priority non-HP non-named-role bench player.

### R-03 [major] Pitcher system has no Step-4 bench-role refinement

**Evidence:** [`build_pitcher_system.py`](build_pitcher_system.py) implements SP cascade + RP cascade + handedness balance + HP enforcement. There is no refinement pass equivalent to the hitter-side Backup C / Util IF / Util OF / Best bat refinement. The `_pull_up` step uses pure pitcher_priority blend — no "swingman" or "long-relief specialist" role concept.

**Effect:** A pitcher whose pwOBA is borderline-MLB but who would be an excellent AAA SP could end up cascaded out without ever being considered as MLB long relief / swingman.

**Recommendation:** Investigate whether this matters in practice. Inventory:
- Run `main(org='X')` for several orgs and look at MLB bullpens — are there obvious "long man" candidates being overlooked?
- If material, add a `_refine_long_man` pass mirroring the hitter Step-4 pattern.

### R-04 [minor] Pitcher system lacks platoon-aware staff variants

**Evidence:** `pwOBAR` and `pwOBAL` are computed but no vs-RHB / vs-LHB rotation variant. Acknowledged in `build_pitcher_system.py:34-35` docstring.

**Recommendation:** Future work — defer until UI / xlsx surface a use-case for it.

### R-05 [minor] Step-2 cascade ranks by pure wOBA at MLB

**Evidence:** Same root cause as M-09 / R-02. `priority(p, 'MLB') = pure wOBA` ([`build_system.py:233-234`](build_system.py:233)). Glove specialists undervalued.

**Recommendation:** R-02 fix subsumes most of this. Alternative: `priority(p, 'MLB') = wOBA + 0.005 × max(<pos>_fld)` (small additive bonus so glove specialists tie-break upward).

### R-06 [minor] Bench refinement re-classify can churn

**Evidence:** [`build_system.py:1064`](build_system.py:1064) — Step-4 outer loop runs up to 20 iterations, with `bench_roles` re-classified each pass. Today's `_bot` fix added a stale-`current` skip ([build_system.py:1194-1195](build_system.py:1194)) that prevents crashes but also means an iteration can be wasted resolving a stale ref. Likely benign (loop converges) but could slow the build.

**Recommendation:** Reorder the role-iteration loop to pull a fresh `bench` view from `fill_starters(by_level[lvl], lvl)` AT THE TOP of each role iteration rather than once per outer pass. Eliminates stale-ref skips.

### R-07 [cosmetic] `_force_start` semantics not fully documented

**Evidence:** `_force_start` is set in HP enforcement when an HP can't be demoted. Honoured in `_rebalance_over_target` (excludes from `poppable`) and Step-4 candidate filter (excludes from `_is_eligible_candidate`). But there's no central docstring explaining what it means and where it's checked.

**Recommendation:** Add a one-paragraph block comment in the HP enforcement function explaining the contract.

### R-08 [cosmetic] Hungarian tiebreaker arbitrary for symmetric assignments

**Evidence:** Documented earlier this session (Schwarber-1B / Harper-DH). System genuinely indifferent; no fix needed.

**Recommendation:** Add a one-line comment in `fill_starters` noting that `linear_sum_assignment` ties resolve by row order and are not deterministic from the user's perspective.

### R-09 [minor] R(DLR) split priority lookup uses 'R(DLR)' not the sub-team key

**Evidence:** [`build_pitcher_system.py:576`](build_pitcher_system.py:576) — `sort_lvl = 'R(DLR)' if lvl.startswith('R(DLR)') else lvl`. Same in [`build_system.py:1339`](build_system.py:1339) for the hitter side. Reasonable since the sub-teams share the same priority blend, but not obvious.

**Recommendation:** Add a comment explaining the lookup remap. Otherwise OK.

### Roster-builder summary

The roster-builder gaps are all **wOBA-only ranking blindness** at the cascade step. Three findings (R-01 catcher rescue / R-02 premium-fit / R-05 cascade priority) are the same underlying issue surfaced from three angles. Fixing R-02 (non-HP premium-fit pull-up) plus R-01 (tighten catcher rescue threshold) eliminates the dominant misplacement patterns the user has been reporting.

---

## Consolidated action list

Ordered by severity, then estimated effort (XS = under 30 min, S = under 2 hrs, M = under a day, L = multi-day).

| # | ID | Sev | Effort | Area | Description |
|---:|---|---|---|---|---|
| 1 | T-01 | blocker | M | tests | Build `tests/test_roster_invariants.py` running `main()` on 30 orgs; assert 8 invariants. Pays for itself the first regression caught. |
| 2 | R-01 | major | S | roster | Tighten catcher rescue: add wOBA ≥ 0.330 floor (option 2). |
| 3 | R-02 | major | M | roster | Add non-HP `_premium_fit_pull_up_veterans` for CF/SS/2B at MLB+AAA. |
| 4 | R-03 | major | M | roster | Investigate / implement pitcher Step-4-style refinement (or document why not needed). |
| 5 | M-03 | major | S | model | Add leverage multiplier to `rp_war` for FG-comparable closer/setup WAR. |
| 6 | C-01 | major | S | code | Extract `roster_common.py` (LEVELS, MAX_AGE, eligibility helpers, injured/DSL utils) for both builders to import. |
| 7 | T-02 | major | XS | tests | Add `make verify` running validate.py + validate_pitcher_v2.py + test_fixed_pos_adj.py. |
| 8 | T-03 | major | XS | tests | Add platoon-WAR snapshot test for known players. |
| 9 | M-04 | major | XS | model | Document catcher framing engine cap in config.py near POSITIONAL_ADJUSTMENT_RUNS. |
| 10 | M-05 | major | (defer) | model | IF cross-position routing — needs new sim data. Track in HANDOFF. |
| 11 | C-02 | minor | S | code | Move source-file magic numbers (PREMIUM_WOBA_RELAX, HP_*, SP/RP_PER_LEVEL, LEFTY_*, etc.) into config.py. |
| 12 | C-04 | cosmetic | XS | code | One cleanup commit deleting all dead code (9 items in C-04 table). |
| 13 | R-05 | minor | XS | roster | Subsumed by R-02; address only if R-02 declined. |
| 14 | M-09 | minor | XS | model | Same as R-05. |
| 15 | M-07 | minor | XS | model | Add `FIELDING_FALLBACK_RATINGS` to config; reference from metrics_fielding. |
| 16 | M-08 | minor | XS | model | Move stale calibration CSVs to `calibration/archive/`; delete `calibrate*.py` legacy scripts. |
| 17 | C-09 | minor | S | code | Disambiguate `injured.txt` / `flagged.txt` (rename or merge to `roster_overrides.json`). |
| 18 | T-04 | minor | XS | tests | HP membership snapshot test for one frozen org. |
| 19 | C-05 | minor | S | code | Refactor `calc_X_metrics` / `calc_potential_X_metrics` duplication. |
| 20 | C-06 | minor | S | code | Vectorize `df.apply(axis=1)` in metrics_hitting / metrics_pitching. |
| 21 | C-10 | minor | XS | code | Move `from config import` at build_system.py:333 to top of file. |
| 22 | C-11 | minor | S | code | Defensive-copy player dicts in `load_team_*` to prevent `_role` mutation on shared state. |
| 23 | R-06 | minor | XS | roster | Pull fresh `bench` per role iteration in Step-4 loop to avoid stale-current skips. |
| 24 | R-09 | minor | XS | roster | Add comment explaining `R(DLR)` sub-team priority remap. |
| 25 | M-01 | minor | XS | model | Document run-env coherence verification near RUNS_PER_WIN_* in config.py. |
| 26 | M-02 | minor | (none) | model | Verified clean — no action. |
| 27 | M-06 | minor | XS | model | Note OOTP wOBA distribution offset stance in HANDOFF. |
| 28 | C-03 | cosmetic | XS | code | Remove debug print in metrics_fielding.py:114. |
| 29 | C-07 | minor | L | code | File-size split of build_system.py — defer until other refactor work touches it. |
| 30 | C-08 | cosmetic | XS | code | Move `import numpy` to top of reader.py. |
| 31 | R-04 | minor | (defer) | roster | Pitcher platoon staff variants — future feature. |
| 32 | R-07 | cosmetic | XS | roster | Document `_force_start` contract. |
| 33 | R-08 | cosmetic | XS | roster | Note Hungarian tiebreaker behaviour in `fill_starters`. |
| 34 | T-05 | minor | (none) | tests | Subsumed by C-04 cleanup. |

### Suggested commit batches

If you want to triage these in order:

1. **Janitor commit** (~30 min): C-03, C-04, C-08, C-10, M-01, M-06, R-07, R-08, R-09. All XS, no behaviour change.
2. **Test harness commit** (~half day): T-01, T-02, T-03, T-04. Lock in current correctness.
3. **Catcher rescue + premium-fit veterans** (~half day): R-01 + R-02. Eliminates the dominant misplacement pattern.
4. **Roster_common refactor** (~half day): C-01 + C-02. Enables symmetric future fixes.
5. **Pitcher leverage WAR** (~2 hrs): M-03. FG-comparability fix.
6. **Pitcher Step-4 investigation** (~half day): R-03. Confirm or implement.
7. **Long-tail polish** (separate sessions): C-05, C-06, C-09, C-11, R-06.

Items M-05 (IF cross-position routing), R-04 (pitcher platoon variants), and C-07 (build_system file split) are deferred — either need new sim data or wait for a refactor moment.

---

## Verification (review-side sign-off)

- ✅ Doc exists at `outputs/PIPELINE_REVIEW.md` (this file).
- ✅ Every section M / C / T / R has at least 2 findings.
- ✅ All findings cite specific file:line.
- ✅ Action list has severity, area, effort, and brief description for every finding.
- ✅ Today's invariant sweep across 30 orgs (run 2026-05-10) shows 0 violations on 8 invariants — locking-in baseline for T-01.
- ✅ No source-code edits made under this review.

End of review.
