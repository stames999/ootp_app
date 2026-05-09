"""Grid sweep over POSITIONAL_ADJUSTMENT_RUNS to find the most sensible combo.

Reuses pre-computed (bat + def) per-position values from the existing
hitters export — only the final pos_adj layer is varied, so each candidate
combination is evaluated in microseconds.

Objective: composite score = MLB-position match rate − pool-imbalance penalty
− extreme-pool penalty. The MLB match rate measures whether well-known stars
land at their actual MLB primary position. Pool-imbalance penalises wildly
uneven distributions. Extreme-pool penalises positions with ~0 or ~50%+
of the population (the failure mode of Option A: empty DH, 1B inflation).
"""
import json
import itertools
import pandas as pd

POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]
RPW_F = 9.53

# Focused 2B/3B sweep — OF/C/SS/1B/DH fixed at the previous sweep's
# winners. The 2B pool was 1056 vs 3B at 291 (3.6× imbalance) and 3B
# DRS leaders Hayes/Urias/Garcia were bleeding to 2B/SS. Try a finer
# grid on 2B/3B to balance.
GRID = {
    "C":  [7.5],
    "1B": [-13.0],
    "2B": [7.0, 8.0, 9.0, 10.0, 11.0],
    "3B": [0.0, 1.0, 2.0, 3.0, 4.0],
    "SS": [12.5],
    "LF": [-9.0],
    "CF": [-2.0],
    "RF": [-11.0],
    "DH": [-10.0],
}

# Defensively-locked test players: 2024 MLB Defensive Runs Saved leaders at
# each position. DRS values approximate (Fangraphs/SIS), used only to pick
# players who are unambiguously locked to their position by their glove
# (rather than by their bat). Bat-driven stars deliberately excluded — their
# OOTP fielding ratings can't be trusted to match an MLB-position assignment
# (Soto, Judge, Acuna, Yordan, Vlad, Ohtani, etc. removed).
ELITE_GLOVES = {
    # === C — top catcher DRS (framing + blocking + arm) ===
    "Patrick Bailey":     {"C"},   # SF  +14 DRS
    "Cal Raleigh":        {"C"},   # SEA  +9
    "Adley Rutschman":    {"C"},   # BAL  +8
    "Sean Murphy":        {"C"},   # ATL  multi-yr top framer
    "Jose Trevino":       {"C"},   # NYY/CIN  framing specialist

    # === 1B — top 1B DRS (limited variance at this position) ===
    "Christian Walker":   {"1B"},  # HOU  +9
    "Matt Olson":         {"1B"},  # ATL  +6

    # === 2B — top 2B DRS ===
    "Andres Gimenez":     {"2B"},  # CLE/TOR  +14
    "Brice Turang":       {"2B"},  # MIL  +13
    "Tommy Edman":        {"2B"},  # LAD  +10 (multi-position)
    "Brendan Donovan":    {"2B"},  # STL  +8

    # === 3B — top 3B DRS ===
    "Matt Chapman":       {"3B"},  # SF  +12
    "Maikel Garcia":      {"3B"},  # KC  +12
    "Ke'Bryan Hayes":     {"3B"},  # PIT  +11
    "Ramon Urias":        {"3B"},  # BAL  +9

    # === SS — top SS DRS ===
    "Bobby Witt Jr.":     {"SS"},  # KC  +14
    "Jose Caballero":     {"SS"},  # TB  +13
    "Masyn Winn":         {"SS"},  # STL  +12
    "Ezequiel Tovar":     {"SS"},  # COL  +9
    "Anthony Volpe":      {"SS"},  # NYY  +9
    "Trea Turner":        {"SS"},  # PHI  +8
    "Dansby Swanson":     {"SS"},  # CHC  +6

    # === LF — top LF DRS ===
    "Steven Kwan":        {"LF"},  # CLE  +9
    "Brandon Marsh":      {"LF"},  # PHI  +9
    "Ian Happ":           {"LF"},  # CHC  +5

    # === CF — top CF DRS (largest defensive variance) ===
    "Pete Crow-Armstrong":{"CF"},  # CHC  +20
    "Brenton Doyle":      {"CF"},  # COL  +18
    "Daulton Varsho":     {"CF", "LF"},  # TOR  +14 (CF time) / split
    "Michael Harris II":  {"CF"},  # ATL  +12
    "Cedric Mullins":     {"CF"},  # BAL  +9

    # === RF — top RF DRS + bat-driven RF locks ===
    "Wilyer Abreu":       {"RF"},  # BOS  +14
    "Fernando Tatis Jr.": {"RF"},  # SD   +12
    "Lane Thomas":        {"RF", "CF"},  # CLE/WSH  +9 (split)
    "Aaron Judge":        {"RF"},  # primary RF — should land here naturally
    "Ronald Acuna":       {"RF"},  # primary RF — should land here naturally
}
# alias used downstream
MLB_STARS = ELITE_GLOVES

# Hard-fail constraints: only used for placements that are physically
# impossible given a player's body type / role. Olson at CF is the
# canonical example — a slow 1B body cannot play CF in MLB regardless
# of rating quirks. Most positional preferences should come out of the
# soft match-rate metric, not be forced via hard constraints.
ANTI_PLACEMENTS = {
    "Matt Olson":  {"forbidden": {"CF"}},   # slow 1B body, never CF
}


def score_combination(pos_adj_runs, df, stars_idx, anti_idx=None):
    """Given a candidate pos_adj dict, compute pool sizes, star match rate,
    anti-placement violations, and a composite score."""
    if anti_idx is None:
        anti_idx = {}
    # Recompute *_adj for each pos
    score_df = df[["name"]].copy()
    for pos in POSITIONS:
        adj_war = pos_adj_runs[pos] / RPW_F
        # bare pos column is NaN'd for floor violators, so NaN propagates
        score_df[f"{pos}_adj_NEW"] = df[pos] + adj_war

    adj_cols = [f"{p}_adj_NEW" for p in POSITIONS]
    score_df["best_NEW"] = score_df[adj_cols].max(axis=1)
    score_df["pos_NEW"] = (
        score_df[adj_cols].idxmax(axis=1).str.replace("_adj_NEW", "", regex=False)
    )

    # Pool sizes
    pool = score_df["pos_NEW"].value_counts().to_dict()
    pool_sizes = {p: pool.get(p, 0) for p in POSITIONS}
    total = sum(pool_sizes.values())

    # Pool imbalance: stddev of pool fractions / mean
    fractions = [n / total for n in pool_sizes.values()]
    mean_frac = sum(fractions) / len(fractions)
    var = sum((f - mean_frac) ** 2 for f in fractions) / len(fractions)
    imbalance = (var ** 0.5) / mean_frac

    # Extreme pool penalty: positions <2% or >35% of total
    extreme_count = sum(1 for f in fractions if f < 0.02 or f > 0.35)

    # OF imbalance: penalise CF being larger than RF or LF (MLB has more
    # corner OFs than CFs — reverse of common bug here).
    of_imbalance = 0.0
    if pool_sizes["RF"] + pool_sizes["LF"] > 0:
        cf_share = pool_sizes["CF"] / (pool_sizes["CF"] + pool_sizes["RF"]
                                       + pool_sizes["LF"])
        of_imbalance = max(0, cf_share - 0.30) * 100

    # Buffer penalty: each position needs a meaningful pool so displaced
    # players have outflow targets. Penalise any pool below the buffer
    # threshold (1.5% of total positioned). Heavily penalise any pool
    # below 0.5%. Avoids the failure mode where a constraint pushes
    # players out of one position with nowhere reasonable to land.
    buffer_threshold = total * 0.015
    severe_threshold = total * 0.005
    buffer_penalty = 0.0
    starved_pools = []
    for p, n in pool_sizes.items():
        if n < severe_threshold:
            buffer_penalty += 100  # very heavy
            starved_pools.append((p, n))
        elif n < buffer_threshold:
            shortfall = (buffer_threshold - n) / buffer_threshold
            buffer_penalty += 30 * shortfall
            starved_pools.append((p, n))

    # Star match rate: of stars matched in our data, how many land at
    # one of their MLB-acceptable positions
    star_matches = 0
    star_total = 0
    star_misplaced = []
    for star_idx, mlb_positions in stars_idx.items():
        if star_idx not in score_df.index:
            continue
        star_total += 1
        our_pos = score_df.loc[star_idx, "pos_NEW"]
        if our_pos in mlb_positions:
            star_matches += 1
        else:
            star_misplaced.append((score_df.loc[star_idx, "name"], our_pos,
                                    sorted(mlb_positions)))
    match_rate = star_matches / star_total if star_total else 0

    # Anti-placement violations (Judge/Soto/Olson at CF, etc.)
    anti_violations = 0
    anti_violators = []
    for player_idx, forbidden_positions in anti_idx.items():
        if player_idx not in score_df.index:
            continue
        our_pos = score_df.loc[player_idx, "pos_NEW"]
        if our_pos in forbidden_positions:
            anti_violations += 1
            anti_violators.append((score_df.loc[player_idx, "name"], our_pos))

    # Composite score: maximize match rate, minimize imbalance/extremes,
    # explicitly punish CF-dominant OF distributions, HARD-fail any
    # anti-placement violations, and starved-pool buffers.
    composite = (
        100 * match_rate
        - 30 * imbalance
        - 50 * extreme_count
        - 30 * of_imbalance
        - 100 * anti_violations
        - buffer_penalty
    )

    return {
        "pos_adj": pos_adj_runs,
        "pool": pool_sizes,
        "imbalance": imbalance,
        "extreme_count": extreme_count,
        "of_imbalance": of_imbalance,
        "match_rate": match_rate,
        "matches": star_matches,
        "star_total": star_total,
        "anti_violations": anti_violations,
        "anti_violators": anti_violators,
        "buffer_penalty": buffer_penalty,
        "starved_pools": starved_pools,
        "composite": composite,
        "misplaced": star_misplaced[:5],  # keep top 5 for display
    }


def main():
    with open("outputs/hitters.json") as f:
        data = json.load(f)
    df = pd.DataFrame(data["rows"], columns=data["columns"])

    # Need bare {pos} columns (= bat + def, NaN-floored). Already in JSON.
    # Resolve MLB stars to df indices
    stars_idx = {}
    for star_name, mlb_positions in MLB_STARS.items():
        matches = df[df["name"].str.contains(star_name, case=False, na=False, regex=False)]
        if len(matches) >= 1:
            stars_idx[matches.index[0]] = mlb_positions

    # Anti-placement player resolution
    anti_idx = {}
    for star_name, spec in ANTI_PLACEMENTS.items():
        matches = df[df["name"].str.contains(star_name, case=False, na=False, regex=False)]
        if len(matches) >= 1:
            anti_idx[matches.index[0]] = spec["forbidden"]

    print(f"Found {len(stars_idx)} of {len(MLB_STARS)} stars in df")
    print(f"Found {len(anti_idx)} of {len(ANTI_PLACEMENTS)} anti-placements")

    # Generate all combinations
    keys = list(GRID.keys())
    value_lists = [GRID[k] for k in keys]
    n_combos = 1
    for v in value_lists:
        n_combos *= len(v)
    print(f"Grid size: {n_combos:,} combinations")

    results = []
    for i, combo_vals in enumerate(itertools.product(*value_lists)):
        pos_adj = dict(zip(keys, combo_vals))
        r = score_combination(pos_adj, df, stars_idx, anti_idx)
        results.append(r)
        if (i + 1) % 5000 == 0:
            print(f"  ...{i+1:,}/{n_combos:,}")

    # Sort by composite score
    results.sort(key=lambda r: r["composite"], reverse=True)

    print()
    print("=" * 100)
    print(f"TOP 10 COMBINATIONS BY COMPOSITE SCORE")
    print("=" * 100)
    for rank, r in enumerate(results[:10], 1):
        adj = r["pos_adj"]
        pool = r["pool"]
        print(f"\n#{rank}  composite={r['composite']:.1f}  "
              f"match={r['matches']}/{r['star_total']} ({r['match_rate']*100:.0f}%)  "
              f"imbalance={r['imbalance']:.2f}  of_imb={r['of_imbalance']:.1f}  "
              f"extremes={r['extreme_count']}  "
              f"anti={r['anti_violations']}  "
              f"buf={r['buffer_penalty']:.1f}")
        print(f"   pos_adj: " + "  ".join(
            f"{p}={adj[p]:+.1f}" for p in POSITIONS))
        print(f"   pools:   " + "  ".join(
            f"{p}={pool[p]}" for p in POSITIONS))
        if r["anti_violators"]:
            print(f"   ANTI-VIOLATIONS: " + "; ".join(
                f"{n}→{got}" for n, got in r["anti_violators"]))
        if r["starved_pools"]:
            print(f"   starved pools: " + "; ".join(
                f"{p}={n}" for p, n in r["starved_pools"]))
        if r["misplaced"]:
            print(f"   misplaced (sample): " + "; ".join(
                f"{n}→{got} (want {','.join(want)})"
                for n, got, want in r["misplaced"]))

    # Also report what's "current" for context
    current = {"C": 3.4, "1B": -12.5, "2B": 4.8, "3B": 2.9, "SS": 6.5,
               "LF": -3.7, "CF": 2.4, "RF": -3.7, "DH": -17.5}
    r_curr = score_combination(current, df, stars_idx, anti_idx)
    print()
    print(f"CURRENT VALUES for reference: composite={r_curr['composite']:.1f}  "
          f"match={r_curr['matches']}/{r_curr['star_total']} "
          f"({r_curr['match_rate']*100:.0f}%)  "
          f"imbalance={r_curr['imbalance']:.2f}  extremes={r_curr['extreme_count']}")
    print(f"   pools: " + "  ".join(f"{p}={r_curr['pool'][p]}" for p in POSITIONS))


if __name__ == "__main__":
    main()
