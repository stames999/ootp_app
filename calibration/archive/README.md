# Archived calibration scripts and data

These files were moved here on 2026-05-10 as part of the janitor cleanup
documented in `outputs/PIPELINE_REVIEW.md` (M-08). They are not imported
or read by the active pipeline; nothing in `metrics_*` / `build_*` /
`reader.py` / `org_report.py` references them.

## Why archived (not deleted)

Provenance. They represent earlier methodology choices that informed
the current calibration but were superseded:

- **calibrate.py** — legacy team-of-clones-derived hitting calibration.
  Replaced by direct sim sweeps (whose outputs live in `config.py` as
  `BASE_HITTING_RATES` / `BATTING_COMPONENTS_ADJUST_MAP`).
- **calibrate_fielding.py** — legacy LSQ-fit fielding tables, fed by
  `fielding_sim.csv`. Replaced by direct 1D sim sweeps; current tables
  in `config.py:FIELDING_RUN_VALUES_VS_REPLACEMENT` come from those.
- **calibrate_ss.py / calibrate_ss_lsq.py** — legacy SS-specific
  overrides for the Gimenez/Turang/Hayes routing problem. Replaced by
  the uniform grid-sweep methodology (`pos_adj_sweep.py`) which
  subsumed all positions including SS.
- **rebuild_from_full_sim.py** — utility for regenerating
  `fielding_sim.csv` from raw sim text. Now stale because `fielding_sim.csv`
  itself is no longer the source of truth.
- **fielding_sim.csv** — input data for `calibrate_fielding.py`. Stale.
- **ss_sim.csv** / **ss_for_combined.csv** — input data for the SS
  override scripts. Stale.

## Restoring

If you ever want to re-run one of these (e.g. to validate a hypothesis
against the legacy approach), `git mv` it back to `calibration/`. The
imports they expect (mostly `config`) still work.

## Active calibration scripts (kept in `calibration/`)

- `pos_adj_sweep.py` — produces current `POSITIONAL_ADJUSTMENT_RUNS`
- `fit_saturation.py` — produces current `FIELDING_SATURATION` +
  3B interaction correction
- `fit_pitcher_v2.py` — produces current `PITCHING_WAR_COEFFS`
- `validate.py` — hitting model regression test (against `sim_data.csv`)
- `validate_pitcher_v2.py` — pitcher model regression test
- `test_fixed_pos_adj.py` — pos_adj test set against MLB DRS leaders
- Plus a handful of analysis / spot-check helpers (`top10_per_pos.py`,
  `scarcity_check.py`, `release_pool_check.py`, etc.)
