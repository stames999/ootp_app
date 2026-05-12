"""Sabermetric lineup optimizer (Tom Tango's "The Book").

Takes the 9 starters at an org's MLB level and orders them per modern
sabermetric principles. Produces separate vs-RHP and vs-LHP lineups
using the platoon-split slash stats (AVGR/OBPR/SLGR vs AVGL/OBPL/SLGL).

The Book's optimal-lineup rules (Tom Tango / Mitchel Lichtman / Andrew
Dolphin, "The Book: Playing the Percentages in Baseball"):

  Slots 1, 2, 4 are the highest-leverage spots — most PAs over the
  season AND best run-scoring environment.

  Three of your top four hitters should bat 1, 2, and 4. Among those
  three:
    - Highest OBP → leadoff (#1). Most PAs in the season, you want
      him on base.
    - Best overall hitter (highest OPS) → #2. Second-most PAs, good
      run-scoring context with #3-4-5 behind him.
    - Highest SLG → cleanup (#4). Drives in runners from #1-3.

  Slot 3 is a *lower-leverage* spot than tradition suggests — fewer
  runners on, fewer RBI ops than #4 or #5. Modern teams put their 5th
  or 6th best hitter at #3, not their best contact bat.

  Slot 5 gets your next-best slugger after #4.

  Slots 6-9 descend in OPS. #9 ideally has higher OBP than #8 because
  #9 functions as a "second leadoff" who turns the lineup over to #1.

Usage:
  python -X utf8 lineup_optimizer.py --org NYY
  python -X utf8 lineup_optimizer.py --org LAD --side R
  python -X utf8 lineup_optimizer.py --org ALL          # every MLB org
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

HITTERS_JSON = _ROOT / "outputs" / "hitters.json"


def load_starters(org: str) -> list[dict]:
    """Return the 9 starters for an org's MLB roster using build_system.
    Each entry has the player's row from hitters.json + assigned position."""
    import build_system
    levels, _, _ = build_system.main(org)
    mlb = levels.get("MLB", {})
    if not isinstance(mlb, dict):
        return []
    # Use 'starters' (the standard, non-platoon Hungarian assignment) as
    # the 9-player pool — these are the players we're ordering.
    starters = mlb.get("starters", [])
    return starters


def starter_pool(org: str, side: str) -> list[dict]:
    """Return the 9 starters for the side-specific lineup
    (starters_vsR / starters_vsL). build_system stores these as
    {position: player_dict}, so each player carries an `assigned_pos`
    key for display (the fielding position they were Hungarian-assigned
    to, which may differ from their pos_adj)."""
    import build_system
    levels, _, _ = build_system.main(org)
    mlb = levels.get("MLB", {})
    if not isinstance(mlb, dict):
        return []
    key = f"starters_vs{side}"
    raw = mlb.get(key)
    if raw is None:
        return []
    if isinstance(raw, dict):
        out = []
        for assigned_pos, player in raw.items():
            if isinstance(player, dict):
                copy = dict(player)
                copy["assigned_pos"] = assigned_pos
                out.append(copy)
        return out
    return list(raw)


def pick(stat: str, side: str) -> str:
    """Build the column name for a given stat and side ('R' or 'L')."""
    return f"{stat}{side}"


def order_lineup(starters: list[dict], side: str) -> list[dict]:
    """Apply The Book's lineup-construction rules to the 9 starters
    using the platoon-split slash stats for the chosen side ('R' = vs
    RHP, 'L' = vs LHP). Returns the 9 starters in batting-order
    sequence (index 0 = leadoff, index 8 = #9 hitter)."""
    if len(starters) < 9:
        return list(starters)

    obp_col = pick("OBP", side)
    slg_col = pick("SLG", side)

    # OPS = OBP + SLG. Primary ranking metric.
    def ops(p):
        return (p.get(obp_col) or 0) + (p.get(slg_col) or 0)

    # Rank all 9 by OPS descending; index 0 = best hitter.
    ranked = sorted(starters, key=ops, reverse=True)

    # Slots 1, 2, 4 get the top 3 hitters (Book rule).
    # Within those:
    #   - Best overall hitter (highest OPS) → #2 (highest-leverage spot
    #     among the three; best run-scoring environment).
    #   - From the remaining two: highest SLG → cleanup (#4, the
    #     run-driver). The "leftover" goes to leadoff (#1) — in
    #     practice this is usually the higher OBP-to-SLG profile guy
    #     anyway, which is what you want at #1.
    # Symmetric with the slot-5 selection (also highest-SLG from rank
    # 3-4) and matches classical cleanup-as-slugger intuition.
    top3 = ranked[:3]
    two_hole = top3[0]  # best OPS → #2
    remaining = top3[1:]
    cleanup = max(remaining, key=lambda p: p.get(slg_col) or 0)
    leadoff = [p for p in remaining if p is not cleanup][0]

    # Slot 5 = next-best slugger after #4 (use ranks 3 and 4, pick the
    # higher SLG). Slot 3 gets the leftover — the "lesser of the top 5".
    next2 = ranked[3:5]
    five_hole = max(next2, key=lambda p: p.get(slg_col) or 0)
    three_hole = [p for p in next2 if p is not five_hole][0]

    # Slots 6-9: ranks 5..8 descending by OPS.
    six_to_eight = ranked[5:8]   # ranks 5, 6, 7
    nine_hole_candidate = ranked[8]

    # #9 is "second leadoff" — swap with #8 if #8's OBP is meaningfully
    # higher than #9's (turns the lineup over to #1 better).
    if (six_to_eight[-1].get(obp_col) or 0) > (nine_hole_candidate.get(obp_col) or 0) + 0.010:
        six_to_eight, nine_hole = (
            six_to_eight[:-1] + [nine_hole_candidate],
            six_to_eight[-1],
        )
    else:
        nine_hole = nine_hole_candidate

    return [leadoff, two_hole, three_hole, cleanup, five_hole,
            *six_to_eight, nine_hole]


def fmt_player(p: dict, side: str) -> str:
    """Compact display line for a lineup slot."""
    name = (p.get("name") or "?")[:22]
    # Prefer assigned_pos (where they're actually playing in this lineup)
    # over pos_adj (their globally-best position).
    pos = p.get("assigned_pos") or p.get("pos_adj") or p.get("pos") or "?"
    avg = p.get(pick("AVG", side)) or 0
    obp = p.get(pick("OBP", side)) or 0
    slg = p.get(pick("SLG", side)) or 0
    iso = p.get(pick("ISO", side)) or 0
    ops = obp + slg
    return (f"{name:<22s} {pos:<3s} "
            f"{avg:>.3f}/{obp:>.3f}/{slg:>.3f}  "
            f"ISO {iso:>.3f}  OPS {ops:>.3f}")


def show_lineup(org: str, side: str) -> None:
    starters = starter_pool(org, side)
    if len(starters) < 9:
        print(f"  {org} vs {side}HP: only {len(starters)} starters in pool (need 9). Skipping.")
        return
    lineup = order_lineup(starters, side)
    label = "vs RHP" if side == "R" else "vs LHP"
    print(f"\n=== {org} {label} (Book-optimal order) ===")
    for i, p in enumerate(lineup, start=1):
        print(f"  {i}. {fmt_player(p, side)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", required=True,
                    help="3-letter org abbreviation (e.g. NYY, LAD) or 'ALL'")
    ap.add_argument("--side", choices=["R", "L", "BOTH"], default="BOTH",
                    help="vs RHP (R), vs LHP (L), or BOTH (default)")
    args = ap.parse_args()

    if not HITTERS_JSON.exists():
        print(f"Missing {HITTERS_JSON}. Run `python app.py refresh` first.")
        sys.exit(1)

    if args.org == "ALL":
        d = json.load(open(HITTERS_JSON))
        orgs = sorted({r["org"] for r in d["rows"]
                       if r.get("org") and r.get("minor") == 0
                       and r.get("org") != "Free"})
    else:
        orgs = [args.org.upper()]

    for org in orgs:
        if args.side in ("R", "BOTH"):
            show_lineup(org, "R")
        if args.side in ("L", "BOTH"):
            show_lineup(org, "L")


if __name__ == "__main__":
    main()
