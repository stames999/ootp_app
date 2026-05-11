# Calibration Gap Report — FanGraphs 2025 vs Sim

_Generated 2026-05-11 20:59:25_  
Sim pool: **MLB-only** (`minor == 0`), n = 3581.  
FG reference RPW: 9.77 (runs → WAR divisor).

## Per-position p0.999 / max comparison

All values in WAR units. **FG_** columns are 2025 single-position maxes (the per-position MLB ceiling, from FG's per-position CSV). **Sim_** columns are p0.999 of the corresponding sim column, filtered to **MLB-only AND OOTP natural-position match** (`minor == 0 AND position == <code>`). This makes the sim's bat ceiling at C come from sim catchers (not Aaron Judge), matching how FG's per-position CSV is filtered. Δ = Sim − FG (negative means our sim undershoots MLB).

| Pos | FG_bat_max | Sim_bat_p999 | Δ_bat | FG_fld_max | Sim_fld_p999 | Δ_fld | FG_def_max | Sim_fld_pos_p999 | Δ_def | FG_WAR_max | Sim_adj_p999 | Δ_WAR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **C** | +4.76 | +3.60 | -1.16 | +2.70 | +2.80 | +0.10 | +3.60 | +4.11 | +0.51 | +8.58 | +6.72 | -1.86 |
| **1B** | +3.56 | +4.83 | +1.27 | +0.84 | +0.93 | +0.09 | +0.18 | -0.38 | -0.56 | +4.71 | +3.56 | -1.15 |
| **2B** | +1.94 | +3.84 | +1.89 | +1.04 | +1.04 | +0.00 | +1.27 | +1.30 | +0.03 | +4.62 | +4.46 | -0.16 |
| **3B** | +2.22 | +3.90 | +1.68 | +1.74 | +1.76 | +0.02 | +1.97 | +2.03 | +0.06 | +5.50 | +5.53 | +0.03 |
| **SS** | +3.27 | +3.80 | +0.53 | +1.71 | +1.80 | +0.09 | +2.42 | +2.59 | +0.17 | +7.78 | +5.87 | -1.91 |
| **LF** | +2.00 | +5.56 | +3.55 | +1.52 | +1.40 | -0.12 | +0.82 | +0.61 | -0.20 | +3.26 | +4.43 | +1.17 |
| **CF** | +2.28 | +3.35 | +1.07 | +1.71 | +1.75 | +0.05 | +1.91 | +2.01 | +0.10 | +5.77 | +4.86 | -0.91 |
| **RF** | +5.82 | +6.57 | +0.75 | +1.23 | +1.30 | +0.07 | +0.60 | +0.51 | -0.09 | +7.22 | +6.66 | -0.56 |
| **DH** | +6.26 | +6.09 | -0.17 | — | +0.00 | — | -0.01 | +0.00 | +0.01 | +7.24 | +4.25 | -2.99 |

## Diagnosis

- **C**:
  - **bat** undershoots FG by 1.16 WAR → candidate knob: `RUNS_PER_WIN_HITTING` (config.py:200) / `RUNS_PER_GAME_HITTING_COEFF` (config.py:243)
  - **total** undershoots FG by 1.86 WAR (combined effect of bat + fld + pos_adj)
- **1B**:
  - **bat** overshoots FG by 1.27 WAR → candidate knob: `RUNS_PER_WIN_HITTING` (config.py:200) / `RUNS_PER_GAME_HITTING_COEFF` (config.py:243)
  - **total** undershoots FG by 1.15 WAR (combined effect of bat + fld + pos_adj)
- **2B**:
  - **bat** overshoots FG by 1.89 WAR → candidate knob: `RUNS_PER_WIN_HITTING` (config.py:200) / `RUNS_PER_GAME_HITTING_COEFF` (config.py:243)
- **3B**:
  - **bat** overshoots FG by 1.68 WAR → candidate knob: `RUNS_PER_WIN_HITTING` (config.py:200) / `RUNS_PER_GAME_HITTING_COEFF` (config.py:243)
- **SS**:
  - **bat** overshoots FG by 0.53 WAR → candidate knob: `RUNS_PER_WIN_HITTING` (config.py:200) / `RUNS_PER_GAME_HITTING_COEFF` (config.py:243)
  - **total** undershoots FG by 1.91 WAR (combined effect of bat + fld + pos_adj)
- **LF**:
  - **bat** overshoots FG by 3.55 WAR → candidate knob: `RUNS_PER_WIN_HITTING` (config.py:200) / `RUNS_PER_GAME_HITTING_COEFF` (config.py:243)
  - **total** overshoots FG by 1.17 WAR (combined effect of bat + fld + pos_adj)
- **CF**:
  - **bat** overshoots FG by 1.07 WAR → candidate knob: `RUNS_PER_WIN_HITTING` (config.py:200) / `RUNS_PER_GAME_HITTING_COEFF` (config.py:243)
- **RF**:
  - **bat** overshoots FG by 0.75 WAR → candidate knob: `RUNS_PER_WIN_HITTING` (config.py:200) / `RUNS_PER_GAME_HITTING_COEFF` (config.py:243)
- **DH**:
  - **total** undershoots FG by 2.99 WAR (combined effect of bat + fld + pos_adj)

## Reference knobs (from the plan, for follow-up)

| Type of gap | Candidate knobs (config.py) |
|---|---|
| Overall bat scale low | `RUNS_PER_WIN_HITTING = 10.28` (line 200); `RUNS_PER_GAME_HITTING_COEFF = 496.84` (line 243) |
| Overall fld scale low | `RUNS_PER_WIN_FIELDING = 9.53` (line 202) |
| IF fld ceiling low (2B/3B/SS) | `FIELDING_SATURATION` (config.py:1928+); rerun `calibration/fit_saturation.py` |
| C fld ceiling low (framing plateau) | `FIELDING_RUN_VALUES_VS_REPLACEMENT['C']` (config.py:1433+), `Cfram` in particular |
| Positional adjustments off | `POSITIONAL_ADJUSTMENT_RUNS` (config.py:130-140) |

## Coverage

Positions processed: C, 1B, 2B, 3B, SS, LF, CF, RF, DH.
Positions still pending: .

Drop additional `<POS>_batting_value.csv` and `<POS>_adv_fielding.csv` files into `calibration/fg_2025/`, then re-run `calibration/fg_2025_reference.py` followed by this script.