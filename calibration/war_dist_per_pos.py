"""Raw per-position WAR distribution across all position players.

Reads `outputs/hitters.json` and, for every defensive position, plots the
distribution of the raw (NOT scarcity-adjusted) per-position WAR value —
the "if this player played this position full-season at current ratings,
what's their WAR?" number.

NaN entries mean the player fails the position's 40-rating defensive
floor (or is exempt-only at 1B/DH) and are excluded from that position's
distribution.

Outputs:
  - outputs/war_dist_per_pos.png   (9-panel histogram grid)
  - console summary table          (n, mean, median, p10/p25/p75/p90, max)

Run from the project root:
  python -X utf8 calibration/war_dist_per_pos.py

Optional flags:
  --adj          plot the scarcity-adjusted columns (`<POS>_adj`) instead
  --level MLB    restrict to MLB-level players only (filter on minor==0)
  --org AZ       restrict to a single org
  --no-floor     bypass the 40-rating POSITION_FLOOR so every position
                 player is scored at every position (no NaN gating).
                 Regenerates the df via main.compute_df() with
                 metrics_war._apply_position_floor monkey-patched out.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow importing project modules when invoked as `python calibration/war_dist_per_pos.py`.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]
HITTERS_JSON = Path("outputs/hitters.json")
OUT_DIR = Path("outputs")


def out_path(*, metric: str, no_floor: bool) -> Path:
    """Route to a unique filename per (metric, floor) combo."""
    parts = ["war_dist_per_pos"]
    if metric != "raw":
        parts.append(metric)
    if no_floor:
        parts.append("no_floor")
    return OUT_DIR / ("_".join(parts) + ".png")


def load() -> pd.DataFrame:
    d = json.load(open(HITTERS_JSON))
    df = pd.DataFrame(d["rows"], columns=d["columns"])
    # Drop two-way pitchers' hitter-side rows? No — keep them; they're position
    # players on the hitter side and contribute to the distribution.
    return df


def load_floored_df() -> pd.DataFrame:
    """Regenerate the metrics pipeline with the standard floor in place,
    and return the full live df so callers can access `_def` / `_fld`
    columns (which aren't in the cached JSON)."""
    import main
    df = main.compute_df()
    is_pitcher = df["position"] == 1
    is_two_way = df.get("is_two_way", pd.Series(False, index=df.index)).fillna(False)
    df = df[(~is_pitcher) | is_two_way].copy()
    return df


def load_unfloored() -> pd.DataFrame:
    """Regenerate the metrics pipeline with the 40-rating position floor
    disabled, so every player gets a per-position WAR at every position
    regardless of their defensive ratings. Used by `--no-floor`.

    Filters to position players (and two-way hitter-side) so the output
    matches the floored JSON's row set.
    """
    import metrics_war
    # Replace the floor with a no-op for this run. compute_df() reads the
    # function via module-level lookup so monkey-patching the attribute is
    # sufficient.
    original = metrics_war._apply_position_floor
    metrics_war._apply_position_floor = lambda df: None
    try:
        import main
        df = main.compute_df()
    finally:
        metrics_war._apply_position_floor = original
    # Mirror exporter.py's hitter filter: position != 1 OR is_two_way
    is_pitcher = df["position"] == 1
    is_two_way = df.get("is_two_way", pd.Series(False, index=df.index)).fillna(False)
    df = df[(~is_pitcher) | is_two_way].copy()
    return df


def pick_series(df: pd.DataFrame, pos: str, suffix: str) -> pd.Series:
    """Return the Series for (position, suffix), routing the special
    `_BAT` sentinel to `war_hitting` (or `DH_hitting` for DH)."""
    if suffix == "_BAT":
        col = "DH_hitting" if pos == "DH" else "war_hitting"
    else:
        col = f"{pos}{suffix}"
    if col in df.columns:
        return df[col].dropna()
    return pd.Series(dtype=float)


def summarize(values: pd.Series, pos: str) -> dict:
    if values.empty:
        return {"pos": pos, "n": 0}
    return {
        "pos": pos,
        "n": int(values.size),
        "mean": float(values.mean()),
        "median": float(values.median()),
        "p10": float(values.quantile(0.10)),
        "p25": float(values.quantile(0.25)),
        "p75": float(values.quantile(0.75)),
        "p90": float(values.quantile(0.90)),
        "min": float(values.min()),
        "max": float(values.max()),
    }


def plot_grid(df: pd.DataFrame, col_suffix: str, title: str, out: Path) -> None:
    fig, axes = plt.subplots(3, 3, figsize=(14, 10), sharex=True)
    axes = axes.flatten()
    # Global x-axis range based on all positions' combined min/max so panels
    # are visually comparable.
    all_vals = pd.concat([pick_series(df, p, col_suffix) for p in POSITIONS])
    xmin, xmax = all_vals.min(), all_vals.max()
    bins = np.linspace(xmin, xmax, 50)

    for ax, pos in zip(axes, POSITIONS):
        vals = pick_series(df, pos, col_suffix)
        ax.hist(vals, bins=bins, color="#3B7DD8", edgecolor="white", linewidth=0.4)
        med = vals.median() if not vals.empty else float("nan")
        if not np.isnan(med):
            ax.axvline(med, color="#D8453B", lw=1.2, ls="--",
                       label=f"median {med:.2f}")
            ax.legend(fontsize=8, loc="upper right", frameon=False)
        ax.set_title(f"{pos}  (n={vals.size})", fontsize=11)
        ax.set_xlabel("WAR")
        ax.set_ylabel("players")
        ax.grid(alpha=0.25)

    fig.suptitle(title, fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    print(f"\nSaved: {out.resolve()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adj", action="store_true",
                    help="use scarcity-adjusted columns (`<POS>_adj`)")
    ap.add_argument("--level", choices=["MLB", "minors", "all"], default="all",
                    help="filter to MLB only, minors only, or all (default)")
    ap.add_argument("--org", default=None,
                    help="restrict to a single org abbreviation")
    ap.add_argument("--no-floor", action="store_true",
                    help="bypass POSITION_FLOOR — score every player at "
                         "every position")
    ap.add_argument("--fld", action="store_true",
                    help="plot the fielding-only component (`<POS>_def`, "
                         "defensive runs/WAR with NO bat and NO positional "
                         "adjustment). DH is constant 0 by definition.")
    ap.add_argument("--bat", action="store_true",
                    help="plot the batting-only component (`war_hitting` "
                         "for fielding positions, `DH_hitting` for DH). "
                         "Batting is position-agnostic so the 8 fielding "
                         "panels will be identical — DH differs because of "
                         "the DH penalty.")
    args = ap.parse_args()
    mutex = sum([args.fld, args.adj, args.bat])
    if mutex > 1:
        ap.error("--fld, --adj, --bat are mutually exclusive")

    # Fielding-only (_def) and batting-only (war_hitting / DH_hitting)
    # views need columns that aren't always in the JSON, so we regenerate
    # via compute_df() when those flags are set. --no-floor regenerates
    # without the POSITION_FLOOR gate; otherwise the standard pipeline.
    if args.no_floor or args.fld or args.bat:
        df = load_unfloored() if args.no_floor else load_floored_df()
    else:
        df = load()
    title_bits = []
    if args.level == "MLB":
        df = df[df["minor"] == 0]
        title_bits.append("MLB only")
    elif args.level == "minors":
        df = df[df["minor"] == 1]
        title_bits.append("minors only")
    else:
        title_bits.append("all levels")
    if args.org:
        df = df[df["org"] == args.org]
        title_bits.append(f"org={args.org}")

    if args.fld:
        suffix = "_def"
        metric_label = "fielding-only WAR (def runs only, no bat, no pos_adj)"
        metric_key = "fld"
    elif args.bat:
        # Batting is position-agnostic except DH (penalty applied). We
        # route via a special "_BAT" sentinel that plot_grid expands to
        # `war_hitting` for fielding positions and `DH_hitting` for DH.
        suffix = "_BAT"
        metric_label = "batting-only WAR (war_hitting; DH uses DH_hitting)"
        metric_key = "bat"
    elif args.adj:
        suffix = "_adj"
        metric_label = "scarcity-adjusted WAR (bat + def + pos_adj)"
        metric_key = "adj"
    else:
        suffix = ""
        metric_label = "raw WAR (bat + def, no pos_adj)"
        metric_key = "raw"
    if args.no_floor:
        title_bits.append("NO FLOOR")
    title = f"Per-position {metric_label} — {', '.join(title_bits)} (n={len(df)})"
    out = out_path(metric=metric_key, no_floor=args.no_floor)

    # Console summary
    rows = []
    for pos in POSITIONS:
        vals = pick_series(df, pos, suffix)
        rows.append(summarize(vals, pos))
    summary = pd.DataFrame(rows).set_index("pos")
    print(title)
    print()
    print(summary.to_string(float_format=lambda x: f"{x:6.2f}"))

    plot_grid(df, suffix, title, out)


if __name__ == "__main__":
    main()
