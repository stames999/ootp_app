# LAA Roster Construction — Handoff for Claude Code

## Goal

Build a 7-level hitter roster system for LAA in OOTP Baseball: MLB → AAA → AA → A+ → A → R → R(DLR). Place 142 LAA hitters across these levels (95 active slots), with the rest going to overflow/release.

---

## Files

| File | Purpose |
|---|---|
| `outputs/hitters.json` | Source data: 7,143 hitters across all orgs; 142 LAA |
| `outputs/pitchers.json` | Source data: 5,729 pitchers across all orgs; 103 LAA |
| `build_system.py` | Hitter algorithm — placement, position assignment, HP enforcement, platoon lineups |
| `build_pitcher_system.py` | Pitcher algorithm — WAR-tier SP/RP allocation per level |
| `build_excel.py` | Excel report generator (hitter + pitcher sheets) |
| `outputs/LAA_roster_system.xlsx` | Current output |

Run order (from repo root): `python build_system.py` (prints hitter rosters), `python build_pitcher_system.py` (prints pitcher rosters), then `python build_excel.py` (writes the combined xlsx).

---

## Data shape (per player)

Key fields:
- `name`, `age`, `org`, `pa`
- `minor`: **0 = MLB roster slot OR international complex**, **1 = actual minor leagues**. Critical: data does not distinguish MLB regulars from int'l complex by this flag alone — use `minor=0 AND age<20` to identify complex players.
- `wOBA`: current MLB-equivalent bat
- `wOBAP`: projected MLB-equivalent bat
- `war_hitting`, `war_hittingP`: current/projected hitting WAR
- `pos_adj`: player's primary position
- For each pos (1B, 2B, 3B, SS, C, CF, LF, RF, DH):
  - `{pos}`: raw position WAR (current)
  - `{pos}_adj`: pos WAR with positional defensive bonus
  - `{pos}_fld`: fielding-only WAR
- `field`: comma-separated list of positions player can play
- `best`, `bestP`, `best_adj`: best-position summary stats

**Important: fielding does NOT develop in this game. Only batting (wOBA → wOBAP) develops.**

---

## Roster sizes

| Level | Slots |
|---|---|
| MLB | 13 |
| AAA | 13 |
| AA | 13 |
| A+ | 13 |
| A | 13 |
| R | 15 |
| R(DLR) | 15 |
| **Total** | **95** |

Each level needs 9 starters (one per position) + 4–6 bench. 2 catchers per level.

---

## Algorithm (current state)

### Step 0: Filter international complex + injured list
Players with `minor=0 AND age<20` are excluded entirely. They're at the int'l complex, not playing in DSL this year. Once promoted they become `minor=1` and re-enter the system.

Injured players are pulled out of active placement. Two sources, additive:
1. **Auto from OOTP**: `_load_injured_names()` reads `players.csv` and pulls anyone whose `injury_is_injured == 1`. Picked up automatically each run — no manual maintenance.
2. **Manual override `injured.txt`** (one name per line, `#` comments) — for marking someone unavailable for a non-injury reason (held out, contract, etc.).

Both feed into the same exclusion. Excluded players appear on the `Flagged` / `Flagged_P` xlsx sheets so you can see who's out. `build_system.main()` and `build_pitcher_system.main()` return `(rosters, overflow, flagged)`.

This is **separate** from the `flag` column / `flagged.txt` mechanism — that one is a display marker for the HTML reports (see `reader.is_flagged`) and intentionally NOT used for roster exclusion.

### Step 1: Catcher pre-allocation
2 catchers per level (14 total). Single score function `catcher_alloc_score(p)` is used both here and for Backup C bench selection in Step 6:

```python
score = wOBA + C_FLD_WEIGHT * C_fld + AGE_WEIGHT * min(age, AGE_CAP)
# defaults: C_FLD_WEIGHT = 0.05, AGE_WEIGHT = 0.002, AGE_CAP = 30
```

Three components:
1. **Current `wOBA`** (not age-weighted `priority`) — using `priority` would let a young high-projection catcher outrank a more mature catcher with a better current bat at AA, but development should put the projection-heavy one at A+ where their bat plays. HP enforcement still ensures every HP catcher starts somewhere; this just decides the WHICH-LEVEL question.
2. **`C_fld` (not `C_adj`)** — `C_adj` already folds the bat into its value, so combining it with `wOBA` would double-count offence and wrongly demote a great-glove / weak-bat backup (e.g. Flores: C_fld +3.67 but C_adj −0.33).
3. **Small age tiebreak** — older catchers preferred for higher levels because they have less developmental runway. Capped at 30 so a journeyman vet doesn't get unbounded boost. This mirrors the philosophy already encoded in non-catcher cascade-down via `priority` weights.

All catchers ranked by score, then assigned greedy top-down to levels respecting **strict** `_top ≤ i ≤ _bot`. There is no longer a `_top - 1` relaxation — that admitted overmatched bats (e.g. Quintero .229 wOBA at AAA's .250 floor) which limits hitting development. Borderline cases (Rogers .27966 vs MLB's .280) are now handled by the position-aware `PREMIUM_WOBA_RELAX` rule in `woba_max_level` (see Step 2), which lowers the wOBA threshold by .005 for primary C / SS / CF — capturing the position-scarcity adjustment from real baseball without admitting major overmatches.

If a level can't fill 2 catcher slots from strict-eligible arms, it stays short — same convention as the bullpen's "Sign FA" gaps.

**Fallthrough**: catchers not picked for any level (more than 14 catchers in the org) fall through to the non-catcher pool in Step 2 instead of going straight to overflow. A bat-first catcher with viable secondary positions (OF/1B/DH) can earn a bench slot via the Hungarian on those positions rather than being released. `is_catcher()` still returns True for them downstream, so HP-swap pairing and sheet labels behave correctly.

### Step 2: Cascade by wOBA
Each non-catcher placed at their max-eligible level by wOBA threshold:

```python
WOBA_MIN = {
    'MLB': 0.280, 'AAA': 0.250, 'AA': 0.220, 'A+': 0.210,
    'A': 0.200, 'R': 0.165, 'R(DLR)': -1.0
}
```

The lower-minors floors (A+/A/R) were tightened from .195/.170/.140 — and A was bumped a second time to .200 — because the prior values were placing very-low-bat prospects (e.g. an 18yo at MLB-eq wOBA .186) at full-season A where they'd be over-matched. The new steps keep raw signees and the lowest-tier bats at R/R(DLR) until their bat plays up.

Ceiling is current wOBA only — no wOBAP blend. We tried blending wOBAP for young players to lift high-projection bats but it over-promoted prospects into levels their current bats couldn't handle and forced the cascade to displace proven mature players (a 31yo .304 wOBA regular dropped out of MLB so a 21yo .287 prospect could be cascaded back down). The HP system already covers true prospects without inflating `_top`.

**Premium-position bat relaxation** (`PREMIUM_WOBA_RELAX`): the threshold for a level is lowered by .005 wOBA points when the player's `pos_adj` is C, SS, or CF — the up-the-middle defensive premiums in real baseball. A defensive-first profile at any of those plays at a level slightly above their pure-bat eligibility because the glove value at scarce positions offsets a borderline bat. Kept small (.005 ≈ +0.25 WAR equivalent) so a TRULY overmatched bat still can't sneak up — this admits "essentially at the threshold" cases (Rogers C .27966 vs MLB .280, Flores C .24999 vs AAA .250, TJ Ford CF .197 vs A .200) without re-creating the broad relaxation we removed. The rule lives in `woba_max_level()` so it propagates everywhere `_top` is used (Step 1 catcher allocation, Step 2 placement, HP cascade, bench refinement). Tunable per position if some need looser admission than others.

If a level overflows, lowest-priority players cascade down. Priority is age-weighted blend of wOBA and wOBAP:

```python
def priority(p):
    age = p['age']
    if age <= 19: return 0.3*wOBA + 0.7*wOBAP
    elif age <= 21: return 0.5*wOBA + 0.5*wOBAP
    elif age <= 23: return 0.7*wOBA + 0.3*wOBAP
    else: return 0.9*wOBA + 0.1*wOBAP
```

### Step 3: Age caps (UPPER only)
Cascade enforces these maxes:

```python
MAX_AGE = {'R(DLR)': 21, 'R': 22, 'A': 23, 'A+': 24, 'AA': 99, 'AAA': 99, 'MLB': 99}
```

A player too old for a level cascades UP, not down. If can't be placed anywhere → released to overflow.

### Step 4: High-Potential (HP) enforcement
**HP definition:**
```python
HP_MAX_AGE = 23
PREMIUM_FLD_MIN = 1.5  # min {pos}_fld to claim the premium-position discount

def is_high_potential(p):
    if p.get('minor') != 1: return False
    if p['age'] > HP_MAX_AGE: return False  # excludes 24+ AAAA-types
    wobap = p.get('wOBAP') or 0
    pos = p.get('pos_adj')
    if pos in {'C','2B','3B','SS','CF'}:
        fld = p.get(f'{pos}_fld')
        # The premium discount (.300 vs .320) goes ONLY to prospects who
        # actually defend the premium position competently. A "SS-eligible"
        # player with SS_fld +0.4 won't really stick at SS as they develop —
        # they'll move to a corner — so they don't earn the discount.
        threshold = 0.300 if (fld is not None and fld >= PREMIUM_FLD_MIN) else 0.320
    else:
        threshold = 0.320
    return wobap >= threshold
```

**HP rule:** Every HP must START somewhere — *except at MLB*. MLB is needs-must (winning is the goal there, not development), so an HP can be benched at MLB without being demoted back to AAA. The HP cascade applies at AAA, AA, A+, and A; R / R(DLR) skip is unrelated (those levels apply the +10 HP bonus inside Hungarian so HPs always start by construction).

An HP triggers the cascade if EITHER (a) they're benched in the standard Hungarian, OR (b) they're a standard starter but DROPPED from the vs-RHP lineup. RHB face righties about 3x as often as lefties so vs-RHP is the dominant matchup signal; movement within OF / between similar slots is fine — only a straight drop from the vs-RHP nine flags overmatching. Non-HPs aren't subject to this — the existing Hungarian + bench-role pass routes them to 1B / DH / bench when they don't earn a positional starting slot. Either trigger uses the same demote logic:
- Try to demote one level (e.g. AA → A+). When picking a swap target the candidate must be: non-HP, wOBA-eligible at X (`_top ≤ X`), age-eligible at X, and the same catcher / non-catcher status as the HP.
- **wOBA-vs-potential justification**: the swap only promotes the candidate to X if the HP's projection advantage (`hp.wOBAP − cand.wOBAP`) is at least as large as the candidate's current-bat advantage (`cand.wOBA − hp.wOBA`). When the trade is justified the swap fires and the HP goes down with the candidate coming up; otherwise the HP demotes alone (the upper level slot stays open for this iteration). This stops a high-projection-but-currently-weak prospect from displacing a meaningfully-better current bat.
- If can't demote at all (age cap blocks the lower level): force-start at current level via `_force_start` flag.
- At R/R(DLR): `fill_starters` auto-prioritizes HPs via +10 score bonus.

Pull-up (filling empty MLB/AAA slots from below) also enforces the wOBA ceiling: a player whose `_top` is below the target level won't be pulled up. This keeps thin upper levels from being padded with sub-threshold filler and prevents an HP from being dragged into a level where they'd just bench.

### Step 5b: Platoon lineups (vs RHP / vs LHP)
After the standard starting nine is set, two more Hungarians run on the same roster using platoon-adjusted position scores:

```python
pos_adj_split(p, pos, vs) = pos_adj + (wOBA_split − wOBA) * WAR_PER_WOBA_POINT
```

where `wOBA_split` is `wOBAR` for vs RHP and `wOBAL` for vs LHP, and `WAR_PER_WOBA_POINT = RUNS_PER_GAME_HITTING_COEFF / RUNS_PER_WIN ≈ 55.48` (the linear coefficient the pipeline uses to convert wOBA to hitting WAR — see `metrics_hitting.calc_hitting_metrics`). The formula is **additive** in the wOBA delta, not multiplicative on `war_hitting`. A multiplicative form would flip sign for below-replacement hitters (`war_hit < 0`), making a player who hits BETTER vs L look WORSE on the platoon score — exactly backwards. Players with `wOBA == 0` or no split data (e.g. prospects with no MLB PA where `wOBAR == wOBAL == wOBA`) collapse back to `pos_adj`, so their lineup spot doesn't change.

The platoon lineup intentionally **omits** the +10 HP / `_force_start` bonus — these are tactical matchup decisions on a fixed roster, not roster-construction calls, so the actual best-bat-vs-this-handedness wins regardless of development priority. At R / R(DLR) this means the platoon lineup can differ substantially from the standard lineup (which forces HPs to start). At MLB / AAA the only difference between standard and platoon scoring is the wOBA → wOBAR/wOBAL swap.

The result is exposed as `rosters[lvl]['starters_vsR']` and `rosters[lvl]['starters_vsL']`. The Excel sheet renders both as separate sections under the standard starters block, with a "swap from X" note flagging positions where the platoon optimum differs from the standard nine. The bench is not platoon-aware — its named-role composition is the same regardless of opponent.

### Step 5: Position assignment (Hungarian)
`scipy.optimize.linear_sum_assignment` over 9 positions. Score function:

```python
def score(p, pos):
    if pos == 'DH' and is_high_potential(p) and p['pos_adj'] != 'DH':
        return None  # see DH-block note below
    pwar = projected_pos_adj(p, pos) if level not in ('MLB','AAA') else p[f'{pos}_adj']
    natural_bonus = 0.5 if p['pos_adj'] == pos else 0
    return pwar + natural_bonus + (10 if HP_force_start else 0)
```

`projected_pos_adj(p, pos) = current pos_adj + (war_hittingP − war_hitting)` — adds bat development runway, fielding stays put. **Applied only to HPs** at AA-and-below; non-HPs use current `pos_adj`. The projection-based score is a development affordance — it counts a real prospect's future bat against position WAR. A non-HP at this level is here on current ability and shouldn't ride a flukily-large bat-dev delta into a positional spot they'd lose under platoon-current scoring (the platoon Hungarians always use current, so a projection-favoured non-HP would be benched in both matchups — exactly the symptom that prompted this rule). MLB/AAA already use current for everyone (mature evaluation).

**DH / 1B block for misplaced HPs**: an HP whose primary position is positional (2B/3B/SS/LF/CF/RF/C) cannot be assigned to DH or 1B. Both are "fallback" positions Hungarian uses when a surplus HP can't get their natural slot — neither rewards the athleticism that made them a prospect. Without this block, Hungarian dumps surplus HPs there (e.g. when 4 CF prospects compete for 1 CF slot, the loser DHs despite a deeply-negative DH_adj). The block forces them into the bench category, which lets HP enforcement cascade them down a level where they can play their actual position. DH and 1B then fill with a true 1B/DH prospect (`pos_adj in {'1B','DH'}`) or the highest leftover bat among non-HPs.

### Step 6: Bench composition (named roles)
After Hungarian picks 9 starters, the bench is ordered by `classify_bench()` into four named roles, then any remaining players are labelled `Depth`:

1. **Backup C** — best non-starting catcher by `catcher_alloc_score` (the same wOBA + glove + age formula used for Step 1 level allocation, so the "best available catcher for the higher slot" notion is consistent across the system).
2. **Utility IF** — non-starter with the most viable IF positions among {2B, 3B, SS}; tiebreak by sum of those `_adj` values. Falls back to single-position IF if no multi-position option exists; if no bench player has any IF capability the slot is left empty (`(none)`).
3. **Utility OF** — same logic over {LF, CF, RF}, with a +1 score bonus for CF eligibility (CF range is the closest proxy in the data for "speed / pinch-runner" potential — there is no dedicated speed field).
4. **Best bat** — highest `priority(p)` among whoever's left.

The result is exposed as `rosters[lvl]['bench_roles']`, a list of `(role_label, player)` tuples that the Excel writer renders one per row with the role label in the leftmost column. At the 13-roster levels (MLB through A) the four named slots fill the bench exactly; at R/R(DLR) (15-roster) the remaining slots are labelled `Depth`.

**Bench-role refinement** runs between HP enforcement and the final Hungarian. The priority cascade picks rosters by bat alone, so a level can end up with a "Utility IF" who only plays one IF position (e.g. Meckler at MLB with 3B as his sole IF) while a true super-utility (Jarvis: SS / 2B / 3B) sits at AAA. The refinement walks top-down and, for each utility role, swaps up if the next level has a strictly more flexible candidate eligible at the upper level (`_top ≤ i`, age cap OK, not a catcher). At AAA-and-below the candidate pool also excludes HPs (they need to start). At **MLB** the HP exclusion is dropped — winning is the only true goal at MLB, so an HP from AAA who'd dominate as MLB Util IF / Util OF comes up even if it costs them their AAA starting reps (paired with the HP-cascade skip at MLB above so they don't immediately get sent back). Backup C and Best bat aren't refined: Backup C is already optimised in Step 1, and Best bat is by definition the bat-leader of whoever is left.

Refinement is always a **1-for-1 swap** so roster sizes are preserved. If the role we want to fill is currently empty (`(none)` in the bench), the refinement displaces the lowest-priority bench player who isn't holding another named role. If everyone on the bench fills a named role and no displaceable depth piece exists, the refinement leaves the role empty rather than evict a contributor.

---

## Current results (as of handoff)

### Counts
- **95** placed (13/13/13/13/13/15/15)
- **38** overflow (release pool)
- **9** complex (excluded)
- **Total: 142** ✓
- **24 HPs**, all starting

### MLB lineup
| Pos | Player | Age | wOBA | pos_adj |
|---|---|---|---|---|
| C | Cooper Ingle | 25 | .325 | 4.01 |
| 1B | Nolan Schanuel | 25 | .347 | 1.30 |
| 2B | Caleb Durbin | 27 | .332 | 2.58 |
| 3B | Zach Neto | 26 | .363 | 5.84 |
| SS | Andres Gimenez | 28 | .315 | 7.72 |
| LF | Mike Trout | 35 | .325 | 2.31 |
| CF | Alek Thomas | 26 | .309 | 4.42 |
| RF | Christian Moore | 24 | .356 | 6.23 |
| DH | Max Kepler | 34 | .339 | 0.50 |

MLB bench: Mangum, D'Orazio, Rogers, Gobbel.

### AAA lineup
| Pos | Player | Age | wOBA | wOBAP |
|---|---|---|---|---|
| C | Gustavo Campero | 29 | .306 | .314 |
| 1B | Rubel Cespedes | 26 | .293 | .304 |
| 2B | Denzer Guzman | 23 | .284 | .317 |
| 3B | Adrian Santana | 21 | .287 | .329 |
| SS | Jim Jarvis | 26 | .297 | .293 |
| LF | Nelson Rada | 21 | .287 | .334 |
| CF | Bryce Teodosio | 27 | .295 | .298 |
| RF | Wade Meckler | 26 | .301 | .307 |
| DH | Niko Kavadas | 28 | .291 | .267 |

---

## Pitcher system (`build_pitcher_system.py`)

A separate, simpler module for pitchers. The pipeline already does most of the role-fit work — `sp_warP` is populated only when stamina + rating clear `SP_WAR_MIN_STAMINA` and `PITCHER_RATING_FLOOR`; `rp_warP` is populated for any pitcher above the rating floor. So `is_sp_viable(p) = p['sp_warP'] is not None`, etc.

**Roster targets**: 5 starters + 8 relievers = 13 pitchers per level × 7 levels = 91 active slots.

**Algorithm** mirrors the hitter system's threshold + age-weighted-blend pattern:

1. **Filter international complex** (`minor=0 AND age<20`) — same as hitters.
2. **Eligibility window**: each pitcher gets `_top = max(pwoba_top_level(p), age_top_level_pitcher(p))` and `_bot` (oldest level by `MAX_AGE`). Two ceilings combine:
   - `pwoba_top_level` against `PWOBA_MAX` thresholds — current-stuff ceiling.
   - `age_top_level_pitcher` against `PITCHER_AGE_TOP` — age ceiling for very young arms. The pipeline's pwOBA caps out around .403 because it clamp-extrapolates below the lowest-rated sim observation, so a 17-year-old whose true ability would be .500 looks identical to a stable 22-year-old at .403. Age is the only signal we have to break that tie, so `PITCHER_AGE_TOP` caps very young arms at developmental levels regardless of their (probably-floored) pwOBA. Mature pitchers (23+) get no age ceiling. Note this is unique to pitchers — hitters explicitly reject age-based level caps because their wOBA is sim-derived without a comparable clamp issue.

```python
PITCHER_AGE_TOP = {17: 6, 18: 5, 19: 5, 20: 3, 21: 2, 22: 1}  # 23+ unconstrained
```

(19 is held at rookie ball alongside 18 — the pwOBA cap masks true ability for both, and a 19-year-old whose nominal pwOBA puts them at full-season A is more likely to be an undeveloped arm than a fully-formed A-ball starter.)
3. **SP cascade**: place each SP-viable pitcher at their `_top`; for each level top-down, while overfull, pop the worst by `pitcher_priority` and cascade to the next level (or overflow if age cap blocks). `pitcher_priority(p)` is the age-weighted blend of `pwOBA` and `pwOBAP` that mirrors the hitter `priority` weights (30/70 at ≤19, 50/50 at 20-21, 70/30 at 22-23, 90/10 at 24+) — so a young high-projection arm outranks an older same-pwOBA arm with no upside.
4. **SP pull-up**: walk levels top-down; under-filled levels pull the best-blend pitcher from below who is also `_top`-eligible at the upper level (their current pwOBA + age cap already qualify them there). Sub-threshold pitchers stay where they are — the user prefers an empty slot they can fill via free agency over an overmatched young arm being dragged into a level they won't perform at. The Excel writer flags empty slots with a "Sign FA" note.
5. **RP cascade + pull-up**: same shape with `RP_PER_LEVEL` slots over RP-viable pitchers minus SPs.
6. **Overflow**: anyone unplaced.

**`PWOBA_MAX` thresholds** (calibrated against league wOBA ≈ .320; tune if rosters look over- or under-matched):
```python
PWOBA_MAX = {
    'MLB': 0.345, 'AAA': 0.370, 'AA': 0.385, 'A+': 0.395,
    'A': 0.405, 'R': 0.420, 'R(DLR)': 1.000,
}
```

**Why both threshold AND blend matter**: a pure-current-pwOBA cascade let Kendri Fana (age 18, pwOBA .401, pwOBAP .307) miss the R rotation by .002 over older pitchers with the same current stuff but no projection upside. The blend correctly weights her into the A rotation. Conversely, a pure-projection cascade (which an earlier version used) over-promoted prospects to AA / AAA where their *current* stuff would get crushed — the threshold prevents that by capping each pitcher at the level their pwOBA actually supports.

**Known gaps / v2 candidates**:
- **No SP↔RP comparative override**. A 6th-best MLB SP cascades to AAA SP rather than possibly being a better fit as MLB RP. For LAA most SP-viable pitchers have `rp_warP < sp_warP` so the case rarely fires; revisit if cascade output looks off.
- **No platoon staff variants** — `pwOBAR` / `pwOBAL` are present and could power vs-RHB / vs-LHB rotation choices the same way the hitter system does for lineups.
- **No bullpen role tagging** (closer / setup / LOOGY). Bullpens are listed in `rp_warP` order.
- **Bottom levels can under-fill** — at R(DLR) the pitcher pool naturally runs dry; the bullpen will show empty slots rather than padding with overflow.

The Excel writer adds one sheet per level with the suffix `_P` (e.g. `MLB_P`, `R_DLR_P`), stacked above the existing hitter sheets, plus a `Release_Pool_P` sheet for pitcher overflow.

---

## Iteration history (decisions made along the way)

**v1 — `best`-driven:** Used current best-position WAR. Catchers misclassified (C_adj not used).

**v2 — `best_adj`-driven:** SS positional bonus inflated marginal SS prospects to MLB starters.

**v3 — Hybrid:** C_adj for catchers, `best` for others. Worked for placement but didn't address bat development.

**v4 — wOBA cascade (current):** wOBA-driven level placement with looser thresholds, HP enforcement, projected pos_adj at minor levels.

### Key user feedback integrated
1. wOBA crucial; bestP misleading (mixes batting and unadjusted fielding)
2. Looser wOBA limits with overflow mechanism
3. Don't get hung up on age — upper caps only, no lower caps
4. HPs MUST start; benched HP → move down a level; rookie ball = force start
5. HP definition: position-aware wOBAP threshold (.300 premium / .320 non-premium)
6. **Fielding does NOT develop, only batting does**
7. International complex (minor=0 + age<20) excluded entirely from rosters
8. HP filter should not exclude based on current wOBA — only `minor=1` + wOBAP threshold

---

## Open questions / potential next steps

1. **Overflow management**: ~38 players in release pool — some may be roster-stash candidates rather than releases. Could split by age/wOBAP gap.

2. **Display tweaks**: Excel currently shows `pos_adj` at MLB/AAA and `projected pos_adj` at minor levels. Could add side-by-side current/projected columns for AA and below.

3. **Pipeline integration**: `build_system.py` reads `outputs/hitters.json` directly. Eventually it should consume the `df` produced by `main.py` (after `calc_war`) so the roster construction is part of the same pipeline run rather than a separate step against a stale JSON snapshot. (See Phase B in the next-phase plan.)

4. **Multi-team support**: Currently hard-coded to LAA via `load_laa()` / `load_laa_pitchers()`. To run for any team, parameterise to `load_team(org)` and thread `org` through `build_excel.main_build()` so the xlsx is named `outputs/{org}_roster_system.xlsx`. (Phase B Step 1.)

---

## Code locations (key sections)

- `build_system.py:1-50`: Constants (LEVELS, ROSTER_SIZES, WOBA_MIN, MAX_AGE, POSITIONS)
- `build_system.py:50-90`: `projected_pos_adj`, `fill_starters` (Hungarian)
- `build_system.py:90-105`: `is_high_potential`, `PREMIUM_POS`
- `build_system.py:105-130`: `priority`, `is_catcher`
- `build_system.py:135-160`: `main()` — Step 0 (filter complex), Step 1 (catchers)
- `build_system.py:160-195`: Step 2 (cascade), age cap handling
- `build_system.py:195-230`: Step 3 (HP enforcement)
- `build_system.py:230-end`: Output assembly

- `build_excel.py:30-80`: per-level sheet writer with conditional pos_adj column

---

## Quick smoke test

```bash
python build_system.py | grep "==="    # should print 7 level headers
python -c "
from build_system import main, LEVELS, is_high_potential
r, ov, fl = main()
n = sum(len(r[l]['all']) for l in LEVELS)
hp_b = sum(len([p for p in r[l]['bench'] if is_high_potential(p)]) for l in LEVELS)
print(f'Placed: {n}, Overflow: {len(ov)}, Flagged: {len(fl)}, Benched HPs: {hp_b}')
"
# Expected: Placed: 95, Overflow: ~38, Benched HPs: 0
```
