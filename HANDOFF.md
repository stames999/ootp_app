# Pistachio — Handover

## What this is

OOTP Baseball roster-construction tool. Takes the user's CSV exports from any
OOTP save, runs a metrics pipeline, then assigns every player to one of 7
levels (MLB → AAA → AA → A+ → A → R → R(DLR)) with positional Hungarian,
high-potential prospect enforcement, platoon-aware lineups, per-position
depth charts, and bullpen handedness balance. Renders to xlsx and a
Streamlit web UI.

## Where the work lives

- Branch `main` on the `pistachio` repo (this directory).
- Local raw sim data lives at `OOTP simulation/OOTP sims.xlsx` (committed).
- Previous HEAD before this session's overhaul: `e2770d4`. This session has
  not yet been committed — substantial uncommitted changes across `config.py`,
  `metrics_pitching.py`, `metrics_war.py`, `metrics_fielding.py`,
  `metrics_hitting.py`, `build_pitcher_system.py`, `build_system.py`,
  `exporter.py`, `reader.py`. New calibration scripts in `calibration/`. Two
  legacy calibration scripts deleted (`compare_adjustments.py`,
  `skill_aware_adj.py`).

## How to run

From PowerShell, in the project directory:

```powershell
python -m streamlit run streamlit_app.py
```

Browser opens at `http://localhost:8501`. Session-scoped gate forces a
fresh upload every browser tab — drop in OOTP CSVs from
`saved_games/<save>.lg/import_export/csv/`. Required: `players.csv`,
`players_scouted_ratings.csv`. Recommended: the two
`players_career_*_stats.csv` files (drive service-time data) **and
`teams.csv`** (drives R(DLR) DSL-team count for the best/rest split).

CLI: `python app.py refresh --csv-dir <path>` then
`python app.py rosters --team COL`.

## What changed this session (major)

This session refit large portions of the model from new OOTP team-of-clones
sim data run in a calibrated environment (BABIP .293, ERA 3.85, RS/G ~4.15-4.4
depending on which sim). The fielding system was rebuilt end-to-end from sim
sweeps; pitcher and hitter WAR formulas were recalibrated; positional
adjustments were replaced with a fixed sim-derived scheme; DSL eligibility
filter was added; etc.

### Pitching model (multiplicative + component-aware WAR)

- `config.BASE_PITCHING_RATES` refit from sim baseline (3 reps, 100k G each):
  HR 0.027, BB 0.075, K 0.214, contact 0.214 (was hand-tuned higher).
- `config.PITCHING_COMPONENTS_ADJUST_MAP` switched from additive to
  **multiplicative** ratios (`*_vs_mult` keys, was `*_vs_adj`). HRA × CTRL = 20/20
  interaction sim confirmed multiplicative wins (predicted pwOBA 0.472, actual
  0.468; additive predicted 0.489).
- CTRL and HRA: full sim sweeps, refit. PBABIP and Stamina: zeroed (sims
  showed minimal effect on rate stats). Stuff: mechanically converted from
  old additive table using OLD base rates.
- New `config.PITCHING_WAR_COEFFS`: component-aware WAR formula. Replaces
  the old single-coefficient pwOBA regression. Coefficients fit to OOTP
  Editor WAR across 23 sim points (RMSE 0.15 WAR), then scaled by 0.83
  (= 200/224 IP × 10/10.76 runs/win) to give realistic 200-IP target with
  sim-empirical runs/win.
- `RUNS_PER_GAME_PITCHING_COEFF` and `RUNS_PER_GAME_PITCHING_CONST` removed.
- All-50 SP now lands ~2.6 WAR. Top SPs (Skubal/Crochet/Skenes) at ~4.7-5.6.

### Hitting model (refit constants)

- `config.RUNS_PER_GAME_HITTING_COEFF`: 554.79 → **496.84** (12% slope
  correction). Empirical from `calibration/sim_data.csv` regression.
- `config.RUNS_PER_GAME_HITTING_CONST`: 178.91 → **144.08** (= COEFF × 0.290
  replacement-level wOBA, FG convention). Old value implied replacement at
  wOBA=0.322 — above league average — clearly miscalibrated.
- `config.REPLACEMENT_LEVEL_WOBA`: 0.300 → **0.290** (FG-standard).
- New `config.RUNS_PER_WIN_HITTING = 10.28` (sim-empirical, was using generic
  `RUNS_PER_WIN = 10`).
- `metrics_hitting.py` now uses `RUNS_PER_WIN_HITTING` instead of `RUNS_PER_WIN`.
- `config.DH_PENALTY`: 0.023 → **0.030** (empirically derived from rest-engineered
  sim showing per-PA wOBA gap of 0.0092 between non-DH and DH).
- League-avg hitter (wOBA 0.318) now lands ~+1.4 WAR. Soto/Tucker/Ohtani at
  +5.7-6.9. Replacement (wOBA 0.290) at exactly 0.0.

### Fielding system (full rebuild from sim sweeps)

All 8 positions' `FIELDING_RUN_VALUES_VS_REPLACEMENT` tables replaced with
sim-derived values. Each position has its baseline (anchor) plus per-rating
contributions:

| Position | Baseline | Method |
|---|---|---|
| C | 55/55/55 | FRM full sweep + BLK/ARM floor-ceiling. Additive. |
| 1B | 35/35/35/35 | All ratings floor-ceiling. Only RNG meaningful. Additive. |
| 2B | 55/55/50/55 | RNG/TDP full sweeps + ERR/ARM floor-ceiling. **Saturation flagged.** |
| 3B | 50/55/60/50 | RNG/ARM full sweeps + ERR/TDP floor-ceiling. **Saturation flagged.** |
| SS | 60/60/60/60 | RNG/ARM full sweeps + ERR/TDP floor-ceiling. **Saturation flagged.** |
| CF | 60/50/55 | RNG full sweep + ARM/ERR floor-ceiling. Additive. |
| LF | 50/50/50 | RNG full sweep + ARM/ERR floor-ceiling. Additive. |
| RF | 50/50/50 | RNG/ARM full sweeps + ERR floor-ceiling. Additive. |

Fielding `metrics_fielding.calc_fielding_metrics` was vectorized (175× speedup,
output identical). Cross-position validation: each position's individual rating
sums match cross-position floor/ceiling within sim noise EXCEPT for the
infield positions (2B/3B/SS) which have ~30-50% saturation at extremes.
This is documented in `metrics_fielding.INTERACTION_HANDLERS` comment.

### Cross-position adjustments (fixed values, replaces scarcity bonus)

- New `config.POSITIONAL_ADJUSTMENT_RUNS`: SS +6.5, 2B +4.8, C +3.4, 3B +2.9,
  CF +2.4, RF −2.0, LF −5.4, 1B −12.5, DH −17.5. Sum to zero across 8
  fielding positions; DH from FG convention.
- Replaces `_skill_aware_bonus` and `_compute_positional_distribution` in
  `metrics_war.py` (both removed). Old `POSITION_ADJ_REFERENCE` and
  `SCARCITY_SKILL_GAMMA` constants removed.
- Applied as flat per-position WAR adjustment. Validated in
  `calibration/test_fixed_pos_adj.py`.

### New constants in `config.py`

- `RUNS_PER_WIN = 10` (kept as legacy/default)
- `RUNS_PER_WIN_HITTING = 10.28` (sim-empirical, used by `metrics_hitting.py`)
- `RUNS_PER_WIN_PITCHING = 10.76` (informational; pitcher coefficients are
  pre-scaled, formula doesn't reference this)
- `RUNS_PER_WIN_FIELDING = 9.53` (informational; `metrics_fielding.py` still
  uses `RUNS_PER_WIN = 10` divisor — see "open questions" below)
- `POSITIONAL_ADJUSTMENT_RUNS` (dict, 9 positions)
- `PITCHING_WAR_COEFFS` (dict, intercept + 4 coefs)
- `DSL_INELIGIBLE_NATIONS = {206, 36}` — USA, Canada (in `build_system.py`)

### DSL eligibility (US/Canadian players blocked from R(DLR))

- New `build_system.dsl_eligible_lowest_level(p)` returns R for USA (206) /
  Canadian (36) players; R(DLR) for everyone else. `build_system.py:300+`.
- `_bot` calculation in both build files now: `min(age_lowest_level,
  service_lowest_level, dsl_eligible_lowest_level)`.
- `nation_id` added to `PLAYERS_COLUMNS` in config and to both
  `hitters.html` / `pitchers.html` `EXPORT_PAGES` column lists.
- Validated: 0 US/CAN players in R(DLR) across COL/AZ/LAA/NYY/BOS.

### Pitcher HP enforcement

- New `_enforce_hp_pitchers` function in `build_pitcher_system.py:411+`,
  mirrors hitter Step 3 HP enforcement. For HP pitchers in overflow, attempts
  to swap with worst non-HP at target level if pwOBAP gain ≥ pwOBA loss.
- Added as Step 5a (after the Step 5 catch-all).
- Validated: Slawinski (LAA HP, pwOBA 0.469, pwOBAP 0.324) now placed at
  R(DLR) RP via swap. Some HP pitchers may still remain in overflow if no
  swap is viable — that's correct behavior.

### Removed legacy code

- `_skill_aware_bonus`, `_compute_positional_distribution`,
  `_all_floor_baseline` functions in `metrics_war.py`
- `POSITION_ADJ_REFERENCE`, `SCARCITY_SKILL_GAMMA`, `ADJ_STDEV_FLOOR`
  constants
- `RUNS_PER_GAME_PITCHING_COEFF`, `RUNS_PER_GAME_PITCHING_CONST` constants
- Files deleted: `calibration/compare_adjustments.py`,
  `calibration/skill_aware_adj.py`
- `war_pitchingP` gating in `metrics_pitching.py`: replaced
  `(...).where(sp_warP.notna())` with role-based mask matching the current-side
  pattern

### Other fixes

- Cleaned up `xlsx` Front-of-rotation note thresholds at
  `build_excel.py:396-405`. Old thresholds (>=2.0 = "Front-of-rotation")
  produced "everyone is front-of-rotation" with the new WAR scale. New:
  >=4.0 = Front, >=2.0 = Mid, >=0.5 = Back-end. RP: >=1.5 = High leverage,
  >=0.5 = Mid, else Low/depth.
- Catcher tables: legacy `_fld` (scarcity-adjusted) inflates ~+3 WAR over
  `_def`. The legacy scarcity math was removed; current `_fld` = `_def` +
  fixed pos-adj. Behavior should be cleaner now.

## Critical files

| File | Role |
|---|---|
| `config.py` | All constants. `BASE_PITCHING_RATES`, `PITCHING_COMPONENTS_ADJUST_MAP` (multiplicative), `PITCHING_WAR_COEFFS`, `POSITIONAL_ADJUSTMENT_RUNS`, `FIELDING_RUN_VALUES_VS_REPLACEMENT` (rebuilt all 8 positions), DSL_INELIGIBLE_NATIONS, RUNS_PER_WIN_HITTING/PITCHING/FIELDING, DH_PENALTY = 0.030 |
| `metrics_pitching.py` | Multiplicative `adjust_rates`, component-aware WAR formula, role-mask gating |
| `metrics_hitting.py` | Uses `RUNS_PER_WIN_HITTING` |
| `metrics_war.py` | Fixed positional adjustments only (no more scarcity bonus). Cleaner. |
| `metrics_fielding.py` | Vectorized (175× speedup). 2B/3B/SS saturation flagged in INTERACTION_HANDLERS comment. |
| `build_system.py` | Hitter rosters. New `dsl_eligible_lowest_level` helper. |
| `build_pitcher_system.py` | Pitcher rosters. New `_enforce_hp_pitchers` (Step 5a). DSL eligibility added. |
| `build_excel.py` | xlsx renderer. Recalibrated rotation/leverage thresholds. |
| `streamlit_app.py` | 5-tab UI. No structural changes this session. |
| `exporter.py` | `nation_id` added to hitters and pitchers EXPORT_PAGES. |
| `reader.py` | `nation_id` added to PLAYERS_COLUMNS via config. |
| `calibration/fit_pitcher_v2.py` | Pitcher refit script (analysis only) |
| `calibration/validate_pitcher_v2.py` | Sim cross-check (predict each sim row, compare actual) |
| `calibration/test_fixed_pos_adj.py` | Side-by-side test of fixed vs scarcity pos-adj |
| `calibration/release_pool_check.py` | Overflow analysis tool |
| `calibration/sim_data.csv` | Hitter calibration sim data (legacy) |
| `calibration/fielding_sim.csv` | Fielding calibration data (legacy LSQ source — superseded by direct sim sweeps this session) |

## Sample WAR values (post-refit)

### Top SPs (200 IP target, sim-empirical runs/win)
| Pitcher | sp_war |
|---|---|
| Tarik Skubal (LAA) | 5.6 |
| Garrett Crochet (BOS) | 4.9 |
| Paul Skenes (PIT) | 4.7 |
| Logan Webb (SF) | 4.3 |
| Chris Sale (ATL) | 3.8 |
| (all-50 baseline SP) | 2.6 |

### Top RPs (RP IP = 0.333 × SP IP ≈ 67 IP)
| Pitcher | rp_war |
|---|---|
| Griffin Jax (TB), Jhoan Duran (PHI) | 1.7 |
| Mason Miller (HOU), Cade Smith (CLE) | 1.5 |
| (no leverage adjustment — multiply by 1.5-2× for FG-comparable closer WAR) | |

### Top hitters (with new positional adjustments)
| Player | wOBA | best_adj |
|---|---|---|
| Kyle Tucker (LAD, RF) | .408 | 8.90 |
| Roman Anthony (BOS, CF) | .392 | 8.24 |
| Corey Seager (TEX, SS), Francisco Lindor (NYM, SS) | .37 | 7.75 |
| Soto (NYM, RF) | .433 | 6.90 |
| (league avg, wOBA 0.318) | | ~1.4 (bat only) |

### Top defensive catchers (raw fielding only)
| Catcher | Cfram | C_def |
|---|---|---|
| Patrick Bailey (SF) | 80 | 1.2 |
| Alejandro Kirk (TOR) | 75 | 1.2 |
| Austin Hedges (FA) | 70 | 1.1 |
| (Edgar Quero, CWS — worst) | 45 | −1.4 |

(Quero matches FG's −15 FRV almost exactly. Bailey is OOTP-engine-compressed
vs FG +30 — the engine plateaus framing above 65; documented as engine quirk.)

## Known limitations

### Infield saturation (2B/3B/SS) — DEFERRED for future work

`metrics_fielding.INTERACTION_HANDLERS` comment documents this. All three
infield positions show ~30-50% saturation at extreme rating combos:
- 2B: 17% floor / 45% ceiling (validated all-65 sim)
- 3B: 43% floor / 50% ceiling
- SS: 36% floor / 31% ceiling (legacy SS_INTERACTION_CORRECTION grid still
  applied as partial correction, but calibrated against OLD 1D tables — stale)

Effect: elite IF defenders' WAR is ~0.3-0.5 too high in absolute terms.
**Relative rankings within each position are preserved.** Cross-position
comparisons via the +12.5/−12.5 pos-adj may slightly favor IF over OF.

Two paths to fix later:
1. Position-specific saturation function (multiplier on summed contributions)
2. Refit interaction grids (2D RNG×ARM for 3B, refit SS grid against new tables)

A diagnostic 3B sim was suggested earlier (RNG=80×ARM=80 with others at
baseline) — would tell whether RNG×ARM is the dominant 2D interaction at 3B.
Not yet run.

### Catcher framing engine plateau

OOTP's engine plateaus framing value above Cfram=65 (+8 runs ceiling regardless
of higher rating). Real MLB FRV says elite framers worth +30 runs. This is a
genuine OOTP engine limitation (the doc flagged it; matches the +3.4 catcher
pos-adj vs FG's +12.5). Decision: trust the sim. Catcher fielding WAR will be
"compressed" vs FG-comparable values for elite framers but accurate for the
floor side (Quero matches FG within 1 run).

### LF essentially eliminated as `pos_adj`

With the new positional adjustments (RF −2.0 vs LF −5.4) and similar OF
fielding values for both positions, RF strictly dominates LF for any player
with adequate arm. Result: 0 players have `pos_adj=LF` after refit. This
matches the side-by-side test prediction. LF still gets computed but rarely
chosen — only players whose RF is NaN'd by floor (no arm) end up at LF.

### Pitcher RP WAR is workload-only, no leverage adjustment

`rp_war = sp_war × 0.3333` implies ~67 IP for an RP. Doesn't apply
FanGraphs' leverage multiplier for closers/setup men. To match FG-displayed
closer WAR (3-4 fWAR for elite seasons), multiply elite RP WAR by ~1.5-2×.
Could add a leverage layer in the future.

### Pitching coefficient asymmetry

Pitcher WAR uses single-coefficient regression. Per the calibration: HRA-driven
pwOBA changes give ~74 WAR/pwOBA, CTRL-driven give ~101 WAR/pwOBA. Single
fitted coefficient is the average. Pure HR-suppressors slightly undervalued,
control-only specialists slightly overvalued. Acceptable as known limitation.

### Calibration file `fielding_sim.csv` is stale

The legacy `calibration/fielding_sim.csv` was the data source for the OLD
LSQ-fit fielding tables. The new tables came from direct sim sweeps in the
calibrated environment (data was pasted into chat, not stored in CSV). The
`fielding_sim.csv` file is now just historical artifact.

## Quick smoke test

```powershell
python app.py refresh

# Hitters
python -X utf8 -c "from build_system import main; r,o,f=main(org='COL'); print(f'COL: rosters={list(r.keys())}, placed={sum(len(r[l][chr(34)+\"all\"+chr(34)]) for l in r)}, overflow={len(o)}')"

# Pitchers + LHP balance
python -X utf8 -c "from build_pitcher_system import main, is_lhp; r,o,f=main(org='AZ'); [print(lvl, sum(1 for p in r[lvl]['bullpen'] if is_lhp(p)),'L /', sum(1 for p in r[lvl]['bullpen'] if not is_lhp(p)),'R, sign_lhp=',r[lvl].get('sign_lhp',0)) for lvl in ('MLB','AAA','AA')]"

# Pitcher sim cross-check
cd calibration && python -X utf8 validate_pitcher_v2.py
```

Expected: COL hitters ~94 placed / ~23 overflow. AZ MLB bullpen 2L/6R sign_lhp=0.

## What's still pending

1. **2B/3B/SS saturation correction** — flagged in INTERACTION_HANDLERS comment
2. **3B RNG×ARM diagnostic sim** suggested but not yet run (tests whether 2D
   interaction grid like SS is the right fix)
3. **SS_INTERACTION_CORRECTION grid re-derivation** — the existing 100-cell
   grid was calibrated against OLD 1D tables, currently stale
4. **`metrics_fielding.py` runs/win** still uses `RUNS_PER_WIN = 10`, not
   `RUNS_PER_WIN_FIELDING = 9.53` — held off because user said wait for full
   fielding rebuild. Now that the rebuild is done, this 5% scaling could be
   applied. Effect: fielding WAR scales up ~5% uniformly.
4. **Optional `nation_id` for `hit_prospects.html`** — currently missing from
   that EXPORT_PAGES entry. Doesn't break anything (hit_prospects.json isn't
   read by build systems) but inconsistent with the other two pages.
5. **Per-stamina IP scaling for pitcher WAR** — explicitly held off to avoid
   prospect distortion. Current model: SP=200 IP, RP=67 IP (constants). Could
   model dynamic IP based on STAM rating but introduces other issues.
6. **Pitcher RP leverage adjustment** — would let elite closers' rp_war match
   FG's leverage-adjusted ~3-4 WAR.
7. **Run history + git commit** — this session's changes are uncommitted.
   Worth a single commit summarizing the rebuild before next chat.

## Worktree branch / remote

```
local branch:  main
remote:        ootp_app/main
HEAD commit:   e2770d4 (pre-session)
uncommitted:   substantial — see "What changed this session"
```
