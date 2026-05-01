# LAA Roster Construction — Handoff for Claude Code

## Goal

Build a 7-level hitter roster system for LAA in OOTP Baseball: MLB → AAA → AA → A+ → A → R → R(DLR). Place 142 LAA hitters across these levels (95 active slots), with the rest going to overflow/release.

---

## Files

| File | Purpose |
|---|---|
| `outputs/hitters.json` | Source data: 7,143 hitters across all orgs; 142 LAA |
| `build_system.py` | Core algorithm — placement, position assignment, HP enforcement |
| `build_excel.py` | Excel report generator |
| `outputs/LAA_hitter_system.xlsx` | Current output |

Run order (from repo root): `python build_system.py` (prints rosters), then `python build_excel.py` (writes xlsx).

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

### Step 0: Filter international complex
Players with `minor=0 AND age<20` are excluded entirely (9 players). They're at the int'l complex, not playing in DSL this year. Once promoted they become `minor=1` and re-enter the system.

### Step 1: Catcher pre-allocation
2 catchers per level (14 total). Score = `priority(p) + 0.05 * C_adj` (age-weighted bat plus a small framing/defense nudge). Greedy assignment within each catcher's eligible level range (per wOBA thresholds).

### Step 2: Cascade by wOBA
Each non-catcher placed at their max-eligible level by wOBA threshold:

```python
WOBA_MIN = {
    'MLB': 0.280, 'AAA': 0.250, 'AA': 0.220, 'A+': 0.195,
    'A': 0.170, 'R': 0.140, 'R(DLR)': -1.0
}
```

For young players (≤21) the effective wOBA used for the ceiling is blended with wOBAP (60/40 at age ≤19, 80/20 at age 20-21, current-only at 22+) so a high-projection bat below the HP threshold isn't stranded under their potential. The blend only ever raises the ceiling, never lowers it.

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
def is_high_potential(p):
    if p.get('minor') != 1: return False
    wobap = p.get('wOBAP') or 0
    pos = p.get('pos_adj')
    threshold = 0.300 if pos in {'C','2B','3B','SS','CF'} else 0.320
    return wobap >= threshold
```

**HP rule:** Every HP must START somewhere. If benched at level X:
- Demote one level (e.g. AA → A+; swap with the lowest-priority non-HP there, age permitting)
- If can't demote (age cap blocks at the lower level): force-start at current level via `_force_start` flag
- At R/R(DLR): `fill_starters` auto-prioritizes HPs via +10 score bonus

Pull-up (filling empty MLB/AAA slots from below) also enforces the wOBA ceiling: a player whose `_top` is below the target level won't be pulled up. This keeps thin upper levels from being padded with sub-threshold filler and prevents an HP from being dragged into a level where they'd just bench.

### Step 5: Position assignment (Hungarian)
`scipy.optimize.linear_sum_assignment` over 9 positions. Score function:

```python
def score(p, pos):
    pwar = projected_pos_adj(p, pos) if level not in ('MLB','AAA') else p[f'{pos}_adj']
    natural_bonus = 0.5 if p['pos_adj'] == pos else 0
    return pwar + natural_bonus + (10 if HP_force_start else 0)
```

`projected_pos_adj(p, pos) = current pos_adj + (war_hittingP − war_hitting)` — adds bat development runway, fielding stays put. Used at AA and below; current pos_adj used at MLB/AAA (mature evaluation).

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

1. **Catcher logic at AAA**: Campero (age 29, C_adj=0.15) starts at AAA while Rogers (age 31, MLB-quality C, minor=0) sits MLB bench. Logic: Rogers is minor=0 so eligible only for MLB; Campero is the best minor=1 catcher for AAA. Check if this is intended.

2. **Pitcher rosters**: This system handles hitters only. Pitchers (SP/RP) need a parallel system. Different fields, different position constraints.

3. **Overflow management**: 38 players in release pool — some may be roster-stash candidates rather than releases. Could split by age/wOBAP gap.

4. **Display tweaks**: Excel currently shows `pos_adj` at MLB/AAA and `projected pos_adj` at minor levels. Could add side-by-side current/projected columns for AA and below.

5. **Pipeline integration**: `build_system.py` reads `outputs/hitters.json` directly. Eventually it should consume the `df` produced by `main.py` (after `calc_war`) so the roster construction is part of the same pipeline run rather than a separate step against a stale JSON snapshot.

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
python3 build_system.py | grep "==="    # should print 7 level headers
python3 -c "
from build_system import main, LEVELS, is_high_potential
r, ov = main()
n = sum(len(r[l]['all']) for l in LEVELS)
hp_b = sum(len([p for p in r[l]['bench'] if is_high_potential(p)]) for l in LEVELS)
print(f'Placed: {n}, Overflow: {len(ov)}, Benched HPs: {hp_b}')
"
# Expected: Placed: 95, Overflow: 38, Benched HPs: 0
```
