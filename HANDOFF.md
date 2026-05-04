# Pistachio — Handover

## What this is

OOTP Baseball roster-construction tool. Takes the user's CSV exports from any
OOTP save, runs a metrics pipeline, then assigns every player to one of 7
levels (MLB → AAA → AA → A+ → A → R → R(DLR)) with positional Hungarian,
high-potential prospect enforcement, and platoon-aware lineups. Renders to
xlsx and a Streamlit web UI.

## Where the work lives

- **Active worktree**: `.claude/worktrees/distracted-benz-9c4f3a` (branch
  `claude/distracted-benz-9c4f3a`)
- **Remote**: `ootp_app` → https://github.com/stames999/ootp_app
- Latest commit on the branch is the canonical state; `ootp_app/main` mirrors it
- A second worktree exists (`upgrade-v1`) but its work has been merged in;
  you can ignore it
- **All work continues in the benz worktree.** Run `git worktree list` if unsure.

## How to run

From PowerShell, in the worktree:

```powershell
python -m streamlit run streamlit_app.py
```

Browser opens at `http://localhost:8501`. The session-scoped gate forces a
fresh upload every browser tab — drop in OOTP CSVs from
`saved_games/<save>.lg/import_export/csv/`. Required: `players.csv`,
`players_scouted_ratings.csv`, `teams.csv`. Recommended: the two
`players_career_*_stats.csv` files (drive service-time data).

CLI alternative: `python app.py refresh --csv-dir <path>` then
`python app.py rosters --team COL`.

## Critical files

| File | Role |
|---|---|
| `build_system.py` | Hitter rosters — wOBA cascade, catcher allocation, HP enforcement, platoon Hungarians, bench refinement, service-time floor, overflow backfill |
| `build_pitcher_system.py` | Pitcher rosters — pwOBA cascade, SP/RP split, +1 stretch, overflow handling |
| `build_excel.py` | xlsx renderer; batting orders + R/G estimate per platoon block |
| `streamlit_app.py` | Single-page UI: Overview / Rosters by level / Release pool / Scout hitters / Scout pitchers tabs |
| `main.py` | `compute_df()` runs the full metrics pipeline; `main()` adds JSON / HTML exports |
| `reader.py` | OOTP CSV loaders. `add_years_at_level` builds service-time columns |
| `metrics_pitching.py` | pwOBA / sprp using `position == 1` + stamina ≥ 40 |
| `metrics_war.py` | Scarcity-adjusted positional WAR; `_hitter_mask` uses `pitches == 0` |
| `config.py` | Constants. `pistachio_filepath = Path(__file__).parent`; `filepath` is OOTP CSV dir, runtime-overridable |
| `app.py` | argparse CLI |
| `outputs/hitters.json` / `outputs/pitchers.json` | Pipeline output, consumed by build_system / build_pitcher_system |
| `outputs/{org}_roster_system.xlsx` | Final per-team xlsx |

## Current algorithm

### Pipeline (main.compute_df)

1. `load_players` — players.csv → df, drops retired
2. `add_pitching_career_stats`, `add_hitting_career_stats` — IP / PA columns (display only; optional)
3. `add_years_at_level` — yrs_MLB / yrs_AAA / … / yrs_R(DLR) (one year per calendar season, credited to highest level reached). Optional; zero-fills when career CSVs missing
4. `add_scouted_ratings` — filtered to `config.ID` (head scout). The Streamlit toggle monkey-patches this to `-1` for OSA
5. `count_pitches`, `is_flagged`, `calc_*_metrics`, `calc_war` — computes pwOBA / wOBA / WAR / `_def` / `_adj` / `_fld` / `pos_adj`
6. `export_html_pages`, `export_json_pages` — write outputs/

### Hitter placement (build_system.main)

- **Step 0**: filter international complex (minor=0 + age<20); separate injured (OOTP `injury_is_injured == 1` AND NOT `injury_dtd_injury == 1` — DTD players keep playing)
- **Step 1**: catcher allocation. Score `wOBA + 0.05·C_fld + 0.002·min(age, 30)`, strict `_top` eligibility, `is_catcher_candidate` filters out players whose pos_adj isn't C and whose best-other-fld exceeds C_fld by > 1.5
- **Step 2**: non-catcher cascade. Each player placed at `_top = woba_max_level(p)` (with `PREMIUM_WOBA_RELAX` of .005 for primary C / SS / CF). `_bot = min(age_lowest_level, service_lowest_level)` — service-time limits (`SERVICE_LIMITS = {'A+':5, 'A':4, 'R':3, 'R(DLR)':3}`, inclusive — 5 yrs total still admits A+) hard-floor placement upward
- **Step 3**: HP enforcement. Every HP must START except at MLB. Demote alone if no swap target eligible
- **Step 3.5**: rebalance — pop over-target levels (created by HP demotions) back down or to overflow
- **Step 3.6**: overflow backfill — pull highest-priority eligible players out of overflow into any under-target level
- **Step 4**: bench refinement. Util IF / Util OF roles use score `(positions_playable, 0.6·fld_sum + 0.4·war_hitting)`; refinement uses the same shape. Multi-position is hard prerequisite; weighted glove+bat resolves within a tied position count
- **Step 5**: per-level Hungarian + vs-RHP / vs-LHP variants

### Pitcher placement (build_pitcher_system.main)

- **Classifier**: `position == 1` (OOTP's own field) → pitcher. SP if stamina ≥ 40, else RP. No more pitch-count thresholds (deprecated).
- **`_top`**: `pwoba_top_level(p)` only (no age cap). `_bot = min(age_lowest_level, service_lowest_level)`.
- **`pitcher_priority`**: `0.9·pwOBA + 0.1·pwOBAP` — current dominant, projection light tiebreak. (Was age-tiered blend; over-promoted projection-elite arms above better-current pitchers.)
- **Cascade + pull-up**: `_cascade` and `_pull_up` accept per-level `slots_for` dicts. Strict `_top ≤ i` plus a non-HP +1 stretch pass for backfill.

### Per-org level capacities

`compute_roster_sizes(org)` (in build_system) reads `teams.csv` and scales
R(DLR) by the count of org-affiliated DSL teams (league_id 234). Most orgs
have 2 DSL teams → R(DLR) hitter cap 30. Pitcher capacities mirror —
`SP_PER_LEVEL × n_dsl` rotations, `RP_PER_LEVEL × n_dsl` bullpen at R(DLR).
Per-level targets stored on rosters dict (`target`, `sp_target`, `rp_target`)
so xlsx + Streamlit display matches.

## Key constants (tunable)

| Constant | Value | Where | What it does |
|---|---|---|---|
| `WOBA_MIN` | dict per level | build_system | wOBA threshold per level (.280 MLB → .165 R) |
| `MAX_AGE` | dict per level | build_system | Age cap per level (R(DLR)=21, R=22, A=23, A+=24, AA+=99) |
| `SERVICE_LIMITS` | A+=5, A=4, R=3, R(DLR)=3 | build_system | OOTP cumulative service caps; inclusive (5 yrs still allowed at A+) |
| `C_FLD_WEIGHT` | 0.05 | build_system | C_fld weight in catcher_alloc_score |
| `AGE_WEIGHT` | 0.002 | build_system | Older-catcher tiebreak |
| `C_FLD_GAP_MAX` | 1.5 | build_system | Catcher candidate filter — exclude if best_other_fld − C_fld > this |
| `PREMIUM_WOBA_RELAX` | 0.005 for C/SS/CF | build_system | Hitter wOBA threshold relaxation for premium positions |
| `HP_MAX_AGE` | 23 | build_system | HP age cutoff (hitters) |
| `PWOBA_MAX` | dict per level | build_pitcher_system | pwOBA ceiling per level (.345 MLB → 1.000 R(DLR)) |
| `MINIMUM_STARTER_STAMINA` | 40 | config | Stamina ≥ this → SP-viable |
| `HP_PITCHER_MAX_PWOBAP` | 0.330 | build_pitcher_system | HP pitcher projection threshold |
| `SP_PER_LEVEL` / `RP_PER_LEVEL` | 5 / 8 | build_pitcher_system | Default per-level pitcher counts (R(DLR) scales by DSL count) |
| `MINIMUM_RELIEVER_PITCHES` / `MINIMUM_STARTER_PITCHES` | deprecated | config | No longer used; kept for back-compat |

## Streamlit UI

5 tabs: **Overview** (KPI cards + MLB lineup + bench + rotation + bullpen +
HP hitters + HP pitchers + Currently unavailable), **Rosters by level**
(per-level expanders with hitters / pitchers / vs-RHP / vs-LHP batting
orders + R/G), **Release pool** (overflow with Top level column),
**Scout hitters** / **Scout pitchers** (cross-org filterable scouting view).

Sidebar: team picker, ratings source toggle (Head Scout / OSA — auto-detects
non-OSA scouting_coach_id from CSV; Recalc button re-runs pipeline),
upload widget (session-gated; new tab requires fresh upload), download xlsx.

## What was done this session (changelog)

In rough order:
1. Catcher logic refinement: strict `_top`, `AGE_WEIGHT`, `PREMIUM_WOBA_RELAX`,
   `is_catcher_candidate` glove-gap test
2. Streamlit front-end built; xlsx absorbed batting-order + R/G from the
   retired org-report
3. CLI parameterised (any team, any save)
4. CSV upload flow with session gate; ratings toggle; scout-id auto-detect
5. Career-stats CSVs made optional; pitches replaced ip as hitter-mask
6. DTD injuries excluded from flagged list
7. Pitcher age cap removed; pwOBA alone gates `_top`
8. Service-time data layer (`add_years_at_level` collapses multi-level
   years to highest reached)
9. Service-time as hard constraint via `_bot` floor
10. Step 3.5 rebalance + Step 3.6 overflow backfill (closes the
    AA-bulge / under-filled-AAA gap)
11. Pitcher classification: `position == 1` + stamina-only gate
    (drops MINIMUM_*_PITCHES)
12. `pitcher_priority` to 90/10 current/projection (was age-tiered blend)
13. Utility IF/OF 60/40 fld-to-bat scoring (in WAR units)
14. Bench refinement aligned with classify_bench
15. Per-org R(DLR) capacity scales by DSL team count

Latest commit: `d77bb7f` "Scale R(DLR) capacity by DSL team count per org".

## Open / next-up

**Split R(DLR) into two physical teams.** Currently R(DLR) for a
2-DSL org is one combined level with capacity 30. The user wants
each DSL team to be its own level slot (e.g. R(DLR) → R(DLR1) +
R(DLR2)) so:
- Each team has its own roster
- xlsx renders separate sheets per DSL team
- Streamlit per-level expander shows each separately

This is non-trivial because:
- `LEVELS` list and `WOBA_MIN` / `PWOBA_MAX` / etc. are module-level
  constants; making them per-org would require refactoring everywhere
  that iterates `LEVELS`
- Sheet naming, JSON shape, Streamlit tab layout all assume a fixed
  level set
- HP / cascade / refinement loops all index by level name

Possible approaches:
1. **Org-aware LEVELS list**: `compute_levels(org)` returns
   `[..., 'R(DLR)1', 'R(DLR)2']` for 2-DSL orgs, plain `R(DLR)` otherwise.
   All modules iterate the org-specific list.
2. **Sub-level grouping**: keep LEVELS as-is, but the rosters dict
   for R(DLR) gains a sub-roster per DSL team, distributed by some rule
   (alphabetical / age / random). Less invasive but doesn't actually
   create separate sheets.

Option 1 is what the user wants. Bigger refactor. Start by mapping
every consumer of `LEVELS` and threading an org through.

## Worktree hygiene

Stale worktrees in `.claude/worktrees/`:
- `distracted-benz-9c4f3a` ← active
- `upgrade-v1` ← merged, can `git worktree remove`
- a few older ones (`elastic-sutherland`, `flamboyant-sammet`, `relaxed-*`)
  unrelated to current work — safe to remove if you want to clean up

## Quick smoke test

```powershell
cd C:\Users\sfwea\OneDrive\Documents\Antigravity\pistachio\.claude\worktrees\distracted-benz-9c4f3a
python -X utf8 app.py refresh --csv-dir "C:/Users/sfwea/OneDrive/Documents/Out of the Park Developments/OOTP Baseball 27/saved_games/Rockies Rebuild.lg/import_export/csv"
python -X utf8 -c "from build_system import main, LEVELS; r,o,f = main(org='COL'); print(f'COL: placed={sum(len(r[l][chr(34)+\"all\"+chr(34)]) for l in LEVELS)}, overflow={len(o)}, flagged={len(f)}')"
```

Expected for Rockies save: COL placed ~95-110, overflow ~20-25.

## Worktree branch / remote

```
local branch:  claude/distracted-benz-9c4f3a
remote:        ootp_app/main (=ootp_app/upgrade-v1)
HEAD commit:   d77bb7f
```
