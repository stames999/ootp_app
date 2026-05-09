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
- Local raw sim data at `OOTP simulation/OOTP sims.xlsx` (committed).
- Recent HEAD progression:
  - `e2770d4` — pre-session baseline before the WAR/fielding rebuild
  - `513e928` — WAR recalibration + fielding tables rebuilt from sim sweeps
  - `8a83b60` — IF saturation + LF/RF pos_adj fix + SS IFarm[65] tightening
  - `afe62c7` — POSITIONAL_ADJUSTMENT_RUNS grid-sweep recalibration + HP rule
  - HEAD (uncommitted) — pipeline review fixes (RUNS_PER_WIN consistency)

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

## Current state of the model

### Pipeline (data flow)

```
load_players → add_career_stats → add_years_at_level
            → add_scouted_ratings → count_pitches → is_flagged
calc_pitching_metrics  (component-aware WAR; PITCHING_WAR_COEFFS)
calc_potential_pitching_metrics
calc_hitting_metrics   (linear wOBA→runs; uses RUNS_PER_WIN_HITTING)
calc_potential_hitting_metrics
calc_fielding_metrics  (saturation + RUNS_PER_WIN_FIELDING)
calc_war               (per-position WAR + pos_adj/RUNS_PER_WIN_FIELDING
                        + FIELD_VIABILITY_GAP filter on the displayed `field`)
   ├── exporter        (HTML + JSON; *_fld and *_adj cols, no _def in display)
   ├── build_system    (hitter rosters; HP via bestP_adj OR wOBAP)
   ├── build_pitcher_system (pitcher rosters; pitcher HP via pwOBAP)
   ├── build_excel     (xlsx renderer; uses org_report for platoon WAR)
   └── streamlit_app   (web UI; shows *_fld and *_adj)
```

### Runs-per-win conventions (post pipeline review)

Each metric component has its own runs/win value, empirically derived from
the calibration sims in that component's run environment:

- `RUNS_PER_WIN_HITTING = 10.28` — used by `metrics_hitting`, `org_report`,
  `build_system.WAR_PER_WOBA_POINT`
- `RUNS_PER_WIN_PITCHING = 10.76` — informational; pitcher coefficients are
  pre-scaled, formula doesn't reference this directly
- `RUNS_PER_WIN_FIELDING = 9.53` — used by `metrics_fielding._def` divisor
  AND `metrics_war` for `pos_adj` conversion (chain stays internally
  consistent in the fielding sim's run environment)
- `RUNS_PER_WIN = 10` — kept as legacy/default; no module reads it now

### Fielding saturation (asymmetric tanh per IF position)

`metrics_fielding._apply_saturation` applies an asymmetric tanh to the
additive 1D-table sum. Calibrated from sim sweeps (see
`calibration/fit_saturation.py`):

| Position | Positive side | Negative side | RMSE |
|---|---|---|---|
| 2B | linear ~0.589× | tanh asymptote −73 | 0.37 runs/162 |
| 3B | tanh asymptote +46 | tanh asymptote −38 | 0.56 runs/162 |
| SS | linear ~0.618× | linear ~0.628× | 1.38 runs/162 |

Plus a 3B (RNG=55, ARM=55) interaction correction of −6.58 runs added
BEFORE saturation — captures the ARM-gated RNG inflection that uniform
compression couldn't explain.

`SS_INTERACTION_CORRECTION` (legacy 100-cell grid) is no longer imported;
SS uses uniform scalar saturation now.

### Positional adjustments (current values)

Recalibrated 2026-05-09 via a 173k-combination grid sweep
(`calibration/pos_adj_sweep.py`) scoring against:
- MLB DRS leaders 2024 landing at their MLB primary position (test set
  of 35 elite-glove players)
- Pool-balance + extreme-pool penalties
- Olson-must-not-be-CF hard fail
- Judge / Acuna at RF as soft signals (no hard force)

```python
POSITIONAL_ADJUSTMENT_RUNS = {
    "C":   7.5, "1B": -13.0, "2B": 10.0, "3B":  2.0,
    "SS": 12.5, "LF":  -9.0, "CF":  -2.0, "RF": -11.0,
    "DH": -10.0,
}
```

Match rate: 26/35 = 74% of elite-glove DRS leaders correctly placed.
The 9 stubborn misplacements (Gimenez, Edman, Hayes, Urias, Garcia, etc.)
are OOTP rating-driven — their IF range/arm genuinely qualifies them at
SS and no pos_adj setting reconciles them with their MLB primary.

Notable improvements vs prior team-of-clones-derived values:
- SS premium +6.5→+12.5 (Witt-tier WAR up ~0.65 to 6.51)
- RF penalty −3.7→−11.0 (RF pool dropped from 3535 → 1791)
- DH at −10 (was −17.5; pool now 682, was 0 — nobody preferred DH before)
- 3B at +2 (was 0; pool 291→453, gives 3B/2B more balance)

p99 across the 8 fielding positions clusters tightly in [+3.1, +4.1] —
pos_adj equalizes top-tier value across positions cleanly.

### High-potential rule

In `build_system.is_high_potential`:
```python
return (minor=1 AND age <= 23) AND (
    bestP_adj >= HP_BESTP_ADJ_THRESHOLD (2.0)  # league-average regular
    OR wOBAP >= HP_WOBA_THRESHOLD (0.340)       # bat-elite safety net
)
```

The OR rule replaces the prior wOBAP-only threshold (.300 with premium
glove or .320 without). Effect: ~227 elite-glove SS/CF prospects
GAIN HP status (Daniel Pierce, Druw Jones, Jose Devers, Dylan Cupp,
Yasser Mercedes — defensive elites whose wOBAP just missed .300);
~77 1B/DH/LF bat-only borderlines LOSE it (Antonio Sanchez, David
Martinez, etc. — bestP_adj only 1.0-1.3 despite wOBAP .335+).

Pitcher HP rule unchanged — `is_high_potential_pitcher` still uses
pwOBAP because pitchers don't have defense to disambiguate.

### Field viability filter

`FIELD_VIABILITY_GAP = 2.0`. The displayed `field` column shows only
positions whose adjusted WAR is within 2.0 WAR of the player's best.
All per-position WARs are still computed and exported. Effect:
- Cal Raleigh's `field`: was `C, 1B` → `C` (1B more than 2 WAR below)
- Witt's `field`: was 7 positions → `SS, 2B, 3B`
- Olson's `field`: was 7 positions → `CF, RF, LF, SS, 2B, 1B`

`POSITION_FLOOR = 40` is the actual eligibility gate (any rating < 40
NaN's the position). `FIELD_VIABILITY_GAP` only affects display.

## Critical files

| File | Role |
|---|---|
| `config.py` | All constants. `POSITIONAL_ADJUSTMENT_RUNS` (grid-sweep), `FIELDING_SATURATION`, `FIELDING_INTERACTION_CORRECTION`, `FIELD_VIABILITY_GAP=2`, `HP_BESTP_ADJ_THRESHOLD=2.0`, `HP_WOBA_THRESHOLD=0.34`, `RUNS_PER_WIN_HITTING/PITCHING/FIELDING`, `FIELDING_RUN_VALUES_VS_REPLACEMENT` (full 1D tables) |
| `metrics_pitching.py` | Multiplicative `adjust_rates`, component-aware WAR, role-mask gating |
| `metrics_hitting.py` | Linear `wOBA → runs → WAR` via RUNS_PER_WIN_HITTING |
| `metrics_fielding.py` | Vectorized table lookup + 3B (55,55) correction + asymmetric-tanh saturation, RUNS_PER_WIN_FIELDING |
| `metrics_war.py` | Per-position bat+def+pos_adj; `field` built post-pos_adj with FIELD_VIABILITY_GAP filter |
| `build_system.py` | Hitter rosters. New HP rule via bestP_adj OR wOBAP. WAR_PER_WOBA_POINT now imported from config (no more stale hard-coded constant) |
| `build_pitcher_system.py` | Pitcher rosters. `is_high_potential_pitcher` via pwOBAP, unchanged. |
| `build_excel.py` | xlsx renderer. Uses org_report for platoon WAR + lineup. |
| `org_report.py` | Platoon-WAR helpers + lineup builder. `_war_from_woba` now uses RUNS_PER_WIN_HITTING (was a bug). |
| `streamlit_app.py` | 5-tab UI. Hitters tab shows `*_fld` (adjusted fielding) — no `_def` columns anywhere. |
| `exporter.py` | Adds `bestP_adj` to hitters export so build_system can read it. |
| `calibration/fit_saturation.py` | Per-position saturation fit |
| `calibration/pos_adj_sweep.py` | Grid sweep that produced current POSITIONAL_ADJUSTMENT_RUNS |
| `calibration/scarcity_check_unfiltered.py` | Empirical p99 / scarcity per position |
| `calibration/top10_per_pos.py` | Spot-check the top players per position post-export |

## Sample WAR values (post-recalibration)

### Top SS (formerly the headline issue, now reasonable)
| Player | best_adj |
|---|---|
| Bobby Witt Jr. (KC) | **6.51** |
| Jacob Wilson (OAK) | 6.31 |
| Geraldo Perdomo (AZ) | 5.41 |
| Maikel Garcia (KC) | 5.31 |
| Marcelo Mayer (BOS) | 5.31 |
| Francisco Lindor (NYM) | 4.91 |

### Top 3B
Seager 6.21, De La Cruz 6.11, Chapman 5.71, Henderson 5.51, Ramirez 4.91
(Note: Seager/De La Cruz/Henderson are MLB SS but their OOTP IF
range/arm gives them slightly more 3B value than SS — borderline cases.)

### Top RF
Tucker 7.15, Soto 6.25, Ohtani 6.25, Judge 5.75, Tatis 5.75, Betts 5.65

### Top CF
Roman Anthony 7.69 (rookie), Merrill 6.09, Buxton 5.99, J Rodriguez 5.69

### Top C
Raleigh 5.39, Kirk 5.09, Wells 4.89, Baldwin 4.09, Contreras 3.99

### Top SP / RP (unchanged from prior session)
| Pitcher | sp_war |
|---|---|
| Tarik Skubal (LAA) | ~5.6 |
| Garrett Crochet (BOS) | ~4.9 |
| Paul Skenes (PIT) | ~4.7 |

## Pool sizes (where each player's best position lands)

| Pos | Pool |
|---|---|
| RF | 1791 |
| C | 1116 |
| 2B | 919 |
| CF | 741 |
| DH | 682 |
| 1B | 609 |
| LF | 599 |
| 3B | 453 |
| SS | 206 |

DH alive (was 0 pre-recalibration), SS realistic (was 27), RF no longer
absurdly dominant (was 3535).

## Known limitations (carried forward)

### Infield cross-position routing of MLB-locked players
Some MLB-2B Gold Glovers (Gimenez, Turang, Donovan) and MLB-3B Gold
Glovers (Hayes, Urias, Garcia) route to SS in our model because their
OOTP IF range/arm makes them SS-eligible AND SS pos_adj is highest.
No pos_adj setting fixes this — it's an OOTP-engine rating distribution
quirk. ~9 misplacements out of 35 elite-glove DRS leaders.

### Catcher framing engine plateau
OOTP's engine plateaus framing value above Cfram=65 (+8 runs ceiling
regardless of higher rating). Real MLB FRV says elite framers worth +30.
Genuine OOTP engine limitation. C pos_adj is +7.5 vs FG's +12.5 partly
because of this.

### OOTP wOBA distribution differs from MLB
OOTP's wOBA distribution runs ~22 points lower than MLB for star hitters
(Witt OOTP .354 vs MLB .376). Plus our hitting slope (496.84) is flatter
than MLB-equivalent (~520). Net effect: elite hitters land ~1-2 WAR
below FG-comparable MLB values. Acceptable as an internal-consistency
choice — WAR comparisons within an OOTP save are correct.

### Pitcher RP WAR is workload-only, no leverage adjustment
`rp_war = sp_war × 0.3333` implies ~67 IP for an RP. Doesn't apply
FanGraphs' leverage multiplier for closers/setup men. Multiply elite
RP WAR by ~1.5-2× to get FG-comparable.

### `calibration/fielding_sim.csv` is stale
The legacy LSQ-fit fielding tables were calibrated from this file. The
current 1D tables came from direct sim sweeps in chat (data pasted in,
not stored in CSV).

## What's still pending

1. **2B/3B/SS interaction-grid refinement** — the current saturation +
   3B (55,55) cell handles most cases, but Hayes/Urias/Garcia routing
   to SS suggests 3B might benefit from a richer 2D RNG×ARM grid.
   Would need new sim data.
2. **OF fielding tables: RF table edge over LF** — at typical OF skill
   levels RF gives ~3 runs more than LF, structurally favoring RF in
   pool size. Mitigated by pos_adj but not eliminated.
3. **Pitcher RP leverage adjustment** — would let elite closers'
   `rp_war` match FG's leverage-adjusted ~3-4 WAR.
4. **`metrics_fielding._vec_closest_rating` fallback baselines** — hard-
   coded 50, 60 in metrics_fielding.py for missing IFrange/IFarm columns.
   Safe fallback (rarely hit) but should reference config constants.

## Quick smoke test

```powershell
python app.py refresh

# COL hitters
python -X utf8 -c "from build_system import main, is_high_potential; r,o,_=main(org='COL'); placed=sum(len(r[lvl]['all']) for lvl in r); hps=sum(1 for lvl in r for p in r[lvl]['all'] if is_high_potential(p)); print(f'COL: placed={placed}, overflow={len(o)}, HPs={hps}')"

# AZ pitchers
python -X utf8 -c "from build_pitcher_system import main; r,o,_=main(org='AZ'); print(f'AZ: rosters={list(r.keys())}, overflow={len(o)}')"

# Top players per position (visual check)
python -X utf8 calibration/top10_per_pos.py
```

Expected: COL 94 placed / 40 overflow / ~22 HPs; AZ pitchers all 7
levels populated. Top SS = Witt 6.51, top RF = Tucker 7.15.
