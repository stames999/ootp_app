"""A/B compare metrics_hitting (v1, hand-tuned tables) vs
metrics_hitting_v2 (regression-derived closed-form).

Runs both on the full league hitter pool from the active save, then
reports:
  1. Aggregate stats: mean / median / std of wOBA per version
  2. Correlation between v1 and v2 wOBA
  3. Distribution of Δ wOBA (v2 − v1)
  4. Largest movers (top 20 each direction)
  5. Per-tier breakdown (league level)
  6. Comparison vs the in-game projection sample for the headline names

Saves the full per-player diff to `outputs/hitter_v1_vs_v2.xlsx`.
"""
from pathlib import Path

import numpy as np
import pandas as pd

import metrics_hitting           # v1
import metrics_hitting_v2        # v2

from reader import (
    add_hitting_career_stats,
    add_pitching_career_stats,
    add_scouted_ratings,
    add_years_at_level,
    load_players,
)


OUT_PATH = Path("outputs/hitter_v1_vs_v2.xlsx")


def build_pool() -> pd.DataFrame:
    """Replicate main.compute_df up to the point where hitting metrics
    are computed — same input both versions see."""
    df = load_players()
    df = add_scouted_ratings(df)
    df = add_years_at_level(df)
    df = add_hitting_career_stats(df)
    df = add_pitching_career_stats(df)
    # Filter to actual hitters (position != 1) for fair comparison.
    df = df[df["position"] != 1].copy()
    return df


def main() -> None:
    pool = build_pool()
    print(f"Pool size: {len(pool)} hitters")

    # Independent copies so the two pipelines don't share computed cols
    df_v1 = pool.copy()
    df_v2 = pool.copy()

    df_v1 = metrics_hitting.calc_hitting_metrics(df_v1)
    df_v2 = metrics_hitting_v2.calc_hitting_metrics(df_v2)

    # Join on player_id for a clean diff
    keep = ["player_id", "name", "org", "position", "age",
            "wOBA", "wOBAR", "wOBAL", "AVG", "OBP", "SLG", "ISO"]
    d1 = df_v1[keep].rename(columns={c: f"{c}_v1" for c in keep[5:]})
    d2 = df_v2[keep].rename(columns={c: f"{c}_v2" for c in keep[5:]})
    diff = d1.merge(d2[["player_id"] + [f"{c}_v2" for c in keep[5:]]],
                    on="player_id", how="inner")

    diff["d_wOBA"]  = diff["wOBA_v2"]  - diff["wOBA_v1"]
    diff["d_wOBAR"] = diff["wOBAR_v2"] - diff["wOBAR_v1"]
    diff["d_wOBAL"] = diff["wOBAL_v2"] - diff["wOBAL_v1"]
    diff["d_AVG"]   = diff["AVG_v2"]   - diff["AVG_v1"]
    diff["d_OBP"]   = diff["OBP_v2"]   - diff["OBP_v1"]
    diff["d_SLG"]   = diff["SLG_v2"]   - diff["SLG_v1"]

    print()
    print("=" * 72)
    print("1. AGGREGATE — distribution of wOBA across the pool")
    print("=" * 72)
    for label, col_v1, col_v2 in [
        ("wOBA",  "wOBA_v1",  "wOBA_v2"),
        ("wOBAR", "wOBAR_v1", "wOBAR_v2"),
        ("wOBAL", "wOBAL_v1", "wOBAL_v2"),
        ("AVG",   "AVG_v1",   "AVG_v2"),
        ("OBP",   "OBP_v1",   "OBP_v2"),
        ("SLG",   "SLG_v1",   "SLG_v2"),
    ]:
        m1, m2 = diff[col_v1].mean(), diff[col_v2].mean()
        med1, med2 = diff[col_v1].median(), diff[col_v2].median()
        s1, s2 = diff[col_v1].std(), diff[col_v2].std()
        corr = diff[col_v1].corr(diff[col_v2])
        print(f"  {label}:  v1 mean={m1:.4f} med={med1:.4f} std={s1:.4f}  |  "
              f"v2 mean={m2:.4f} med={med2:.4f} std={s2:.4f}  |  corr={corr:+.4f}")

    print()
    print("=" * 72)
    print("2. Δ wOBA distribution (v2 − v1) across the pool")
    print("=" * 72)
    dwoba = diff["d_wOBA"].dropna()
    print(f"  n = {len(dwoba)}")
    print(f"  mean ΔwOBA   = {dwoba.mean():+.5f}")
    print(f"  median       = {dwoba.median():+.5f}")
    print(f"  std          = {dwoba.std():.5f}")
    print(f"  abs(ΔwOBA) percentiles:")
    abs_d = dwoba.abs()
    for q in (0.50, 0.75, 0.90, 0.95, 0.99):
        print(f"    p{int(q*100):>3} = {abs_d.quantile(q):.5f}")
    print(f"  max |Δ|      = {abs_d.max():.5f}")
    print(f"  fraction with |Δ| > 0.020 = {(abs_d > 0.020).mean()*100:.1f}%")
    print(f"  fraction with |Δ| > 0.010 = {(abs_d > 0.010).mean()*100:.1f}%")

    print()
    print("=" * 72)
    print("3. TOP-20 LARGEST POSITIVE MOVERS (v2 > v1)")
    print("=" * 72)
    top_pos = diff.nlargest(20, "d_wOBA")[
        ["name", "org", "age", "wOBA_v1", "wOBA_v2", "d_wOBA",
         "AVG_v1", "AVG_v2", "SLG_v1", "SLG_v2"]
    ]
    print(top_pos.to_string(index=False))

    print()
    print("=" * 72)
    print("4. TOP-20 LARGEST NEGATIVE MOVERS (v2 < v1)")
    print("=" * 72)
    top_neg = diff.nsmallest(20, "d_wOBA")[
        ["name", "org", "age", "wOBA_v1", "wOBA_v2", "d_wOBA",
         "AVG_v1", "AVG_v2", "SLG_v1", "SLG_v2"]
    ]
    print(top_neg.to_string(index=False))

    print()
    print("=" * 72)
    print("5. PROJECTION REFERENCE — headline players from the OOTP sample")
    print("=" * 72)
    REF = {
        "Aaron Judge":      0.442,
        "Shohei Ohtani":    0.444,
        "Juan Soto":        0.415,
        "Mike Trout":       0.348,
        "Luis Arraez":      0.324,
        "Bobby Witt Jr.":   0.367,
        "Kyle Schwarber":   0.374,
        "Pete Alonso":      0.389,
        "Yordan Alvarez":   0.399,
        "Ronald Acuna Jr.": 0.405,
    }
    rows = []
    for name, ref in REF.items():
        sub = diff[diff["name"] == name]
        if len(sub) == 0:
            continue
        r = sub.iloc[0]
        v1 = r["wOBA_v1"]; v2 = r["wOBA_v2"]
        rows.append({
            "name": name, "org": r["org"],
            "ref_wOBA": ref, "v1_wOBA": round(v1, 3), "v2_wOBA": round(v2, 3),
            "|v1-ref|": round(abs(v1-ref), 3),
            "|v2-ref|": round(abs(v2-ref), 3),
            "winner": "v2" if abs(v2-ref) < abs(v1-ref) else "v1" if abs(v1-ref) < abs(v2-ref) else "tie",
        })
    refdf = pd.DataFrame(rows)
    print(refdf.to_string(index=False))
    print(f"\n  v1 mean |error| vs ref = {refdf['|v1-ref|'].mean():.3f}")
    print(f"  v2 mean |error| vs ref = {refdf['|v2-ref|'].mean():.3f}")
    print(f"  v2 wins on {(refdf['winner']=='v2').sum()} / {len(refdf)} players")

    print()
    print("=" * 72)
    print("6. SCATTER STATS — v2 vs v1 wOBA")
    print("=" * 72)
    # Compute bias and slope of v2 on v1
    valid = diff.dropna(subset=["wOBA_v1", "wOBA_v2"])
    from numpy.polynomial import polynomial as P
    slope, intercept = np.polyfit(valid["wOBA_v1"], valid["wOBA_v2"], 1)
    print(f"  v2_wOBA ≈ {intercept:+.4f} + {slope:.4f} × v1_wOBA")
    print(f"  Pearson r = {valid['wOBA_v1'].corr(valid['wOBA_v2']):+.4f}")
    print(f"  RMSE between v1 and v2 wOBA = "
          f"{np.sqrt(((valid['wOBA_v2'] - valid['wOBA_v1'])**2).mean()):.5f}")

    # Save full diff
    OUT_PATH.parent.mkdir(exist_ok=True)
    cols_to_save = [
        "name", "org", "age", "position",
        "wOBA_v1", "wOBA_v2", "d_wOBA",
        "wOBAR_v1", "wOBAR_v2", "d_wOBAR",
        "wOBAL_v1", "wOBAL_v2", "d_wOBAL",
        "AVG_v1", "AVG_v2", "d_AVG",
        "OBP_v1", "OBP_v2", "d_OBP",
        "SLG_v1", "SLG_v2", "d_SLG",
    ]
    diff[cols_to_save].sort_values("d_wOBA").to_excel(
        OUT_PATH, sheet_name="v1_vs_v2", index=False, engine="openpyxl"
    )
    print(f"\n  Full per-player diff written to {OUT_PATH}")


if __name__ == "__main__":
    main()
