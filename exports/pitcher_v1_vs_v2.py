"""A/B compare metrics_pitching (v1) vs metrics_pitching_v2 (regression-derived).

For each of the 8,377 pitchers in the active save, run both pipelines
and compare pwOBA against each other plus against the 95-pitcher OOTP
in-game projection sample.
"""
import io
from pathlib import Path

import numpy as np
import pandas as pd

import metrics_pitching         # v1
import metrics_pitching_v2      # v2

from reader import (
    add_hitting_career_stats, add_pitching_career_stats,
    add_scouted_ratings, add_years_at_level, load_players, count_pitches,
)

from exports.pitcher_outcome_regressions import DATA_TSV, parse_pct


OUT_PATH = Path("outputs/pitcher_v1_vs_v2.xlsx")


def build_pool() -> pd.DataFrame:
    df = load_players()
    df = add_scouted_ratings(df)
    df = add_years_at_level(df)
    df = add_hitting_career_stats(df)
    df = add_pitching_career_stats(df)
    # pitchers = position 1 OR has pitching ratings (two-way)
    df = df[df["position"] == 1].copy()
    df = count_pitches(df)
    return df


def parse_ref_sample():
    df = pd.read_csv(io.StringIO(DATA_TSV), sep="\t")
    for c in ("K%", "BB%", "HR%", "HR/FB"):
        df[c] = df[c].apply(parse_pct)
    for c in df.columns:
        if c not in ("Name", "Org", "Level", "Throws"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def err_stats(name, refs, df, version_label):
    """Return per-version mean abs error vs ref sample."""
    errs = {"K%": [], "BB%": [], "HR%": [], "BABIP-against": [], "pwOBA-against": []}
    for _, ref in refs.iterrows():
        sub = df[df["name"] == ref["Name"]]
        if sub.empty:
            continue
        r = sub.iloc[0]
        # v1 / v2 output columns: pwOBA (overall), hr_vs (per-PA HR rate),
        # bb_vs (per-PA BB rate), k_vs (per-PA K rate). vsR + vsL avg
        # weighted by HANDEDNESS_WEIGHTS to get aggregate.
        from config import HANDEDNESS_WEIGHTS
        hr_pred = r.get("hr_vsR", 0) * HANDEDNESS_WEIGHTS["R"] + r.get("hr_vsL", 0) * HANDEDNESS_WEIGHTS["L"]
        bb_pred = r.get("bb_vsR", 0) * HANDEDNESS_WEIGHTS["R"] + r.get("bb_vsL", 0) * HANDEDNESS_WEIGHTS["L"]
        k_pred  = r.get("k_vsR", 0)  * HANDEDNESS_WEIGHTS["R"] + r.get("k_vsL", 0)  * HANDEDNESS_WEIGHTS["L"]
        h_pred  = r.get("h_nothr_vsR", 0) * HANDEDNESS_WEIGHTS["R"] + r.get("h_nothr_vsL", 0) * HANDEDNESS_WEIGHTS["L"]
        bip_pct = max(0.0, 1.0 - k_pred - bb_pred - 0.009 - hr_pred)
        babip_pred = h_pred / bip_pct if bip_pct > 0 else np.nan
        pwoba_pred = r.get("pwOBA", np.nan)

        errs["K%"].append(abs(k_pred - ref["K%"]))
        errs["BB%"].append(abs(bb_pred - ref["BB%"]))
        errs["HR%"].append(abs(hr_pred - ref["HR%"]))
        errs["BABIP-against"].append(abs(babip_pred - ref["BABIP-against"]))
        errs["pwOBA-against"].append(abs(pwoba_pred - ref["pwOBA-against"]))
    return {k: (np.mean(v), np.max(v)) for k, v in errs.items() if v}


def main():
    pool = build_pool()
    print(f"Pool size: {len(pool)} pitchers")
    refs = parse_ref_sample()
    print(f"Reference sample: {len(refs)} pitchers with projections")

    df_v1 = metrics_pitching.calc_pitching_metrics(pool.copy())
    df_v2 = metrics_pitching_v2.calc_pitching_metrics(pool.copy())

    # ----------------------------------------------------------------
    # 1. Aggregate pool comparison
    # ----------------------------------------------------------------
    print("\n" + "=" * 72)
    print("1. POOL-WIDE COMPARISON")
    print("=" * 72)

    keep = ["player_id", "name", "org", "pwOBA", "pwOBAR", "pwOBAL"]
    d1 = df_v1[keep].rename(columns={c: f"{c}_v1" for c in keep[3:]})
    d2 = df_v2[keep].rename(columns={c: f"{c}_v2" for c in keep[3:]})
    diff = d1.merge(d2[["player_id"] + [f"{c}_v2" for c in keep[3:]]], on="player_id")
    diff["d_pwOBA"] = diff["pwOBA_v2"] - diff["pwOBA_v1"]

    for col in ("pwOBA", "pwOBAR", "pwOBAL"):
        m1, m2 = diff[f"{col}_v1"].mean(), diff[f"{col}_v2"].mean()
        s1, s2 = diff[f"{col}_v1"].std(), diff[f"{col}_v2"].std()
        corr = diff[f"{col}_v1"].corr(diff[f"{col}_v2"])
        rmse = np.sqrt(((diff[f"{col}_v2"] - diff[f"{col}_v1"])**2).mean())
        print(f"  {col:<6}  v1 mean={m1:.4f} std={s1:.4f}  |  "
              f"v2 mean={m2:.4f} std={s2:.4f}  |  corr={corr:+.4f}  "
              f"RMSE={rmse:.5f}")

    # ΔpwOBA distribution
    print()
    dwoba = diff["d_pwOBA"].dropna()
    print(f"  ΔpwOBA (v2 − v1) distribution:")
    print(f"    mean = {dwoba.mean():+.5f}")
    print(f"    median = {dwoba.median():+.5f}")
    print(f"    std = {dwoba.std():.5f}")
    abs_d = dwoba.abs()
    for q in (0.50, 0.75, 0.90, 0.95, 0.99):
        print(f"    p{int(q*100)} of |Δ| = {abs_d.quantile(q):.5f}")
    print(f"    max |Δ| = {abs_d.max():.5f}")

    # ----------------------------------------------------------------
    # 2. Reference comparison
    # ----------------------------------------------------------------
    print("\n" + "=" * 72)
    print("2. REFERENCE SAMPLE — mean |error| vs OOTP in-game projection")
    print("=" * 72)
    v1_err = err_stats("v1", refs, df_v1, "v1")
    v2_err = err_stats("v2", refs, df_v2, "v2")
    print(f"\n  {'stat':<18}  {'v1 mean|err|':>14}  {'v2 mean|err|':>14}  winner")
    winners = {"v1": 0, "v2": 0}
    for stat in v1_err:
        v1m, v1max = v1_err[stat]
        v2m, v2max = v2_err[stat]
        w = "v1" if v1m < v2m else "v2"
        winners[w] += 1
        print(f"  {stat:<18}  {v1m:>14.5f}  {v2m:>14.5f}  {w}")
    print(f"\n  Aggregate: v1 wins {winners['v1']}, v2 wins {winners['v2']}")

    # ----------------------------------------------------------------
    # 3. Top movers (v1 vs v2)
    # ----------------------------------------------------------------
    print("\n" + "=" * 72)
    print("3. TOP-15 LARGEST MOVERS (|ΔpwOBA|)")
    print("=" * 72)
    big = diff.nlargest(15, "d_pwOBA")[["name", "org", "pwOBA_v1", "pwOBA_v2", "d_pwOBA"]]
    print("\n  Largest positive (v2 > v1):")
    print(big.to_string(index=False))
    small = diff.nsmallest(15, "d_pwOBA")[["name", "org", "pwOBA_v1", "pwOBA_v2", "d_pwOBA"]]
    print("\n  Largest negative (v2 < v1):")
    print(small.to_string(index=False))

    # ----------------------------------------------------------------
    # 4. Per-player check on the reference sample
    # ----------------------------------------------------------------
    print("\n" + "=" * 72)
    print("4. PER-PLAYER REFERENCE COMPARISON (top 10 well-known names)")
    print("=" * 72)
    famous = ["Tarik Skubal","Garrett Crochet","Paul Skenes","Mason Miller",
              "Aroldis Chapman","Logan Webb","Jacob deGrom","Yoshinobu Yamamoto",
              "Edwin Diaz","Tarik Skubal"]
    rows = []
    for name in famous:
        rsub = refs[refs["Name"] == name]
        v1sub = df_v1[df_v1["name"] == name]
        v2sub = df_v2[df_v2["name"] == name]
        if rsub.empty or v1sub.empty or v2sub.empty:
            continue
        r = rsub.iloc[0]; p1 = v1sub.iloc[0]; p2 = v2sub.iloc[0]
        rows.append({
            "name": name,
            "ref_pwOBA": round(r["pwOBA-against"], 3),
            "v1_pwOBA": round(p1["pwOBA"], 3),
            "v2_pwOBA": round(p2["pwOBA"], 3),
            "|v1−ref|": round(abs(p1["pwOBA"] - r["pwOBA-against"]), 3),
            "|v2−ref|": round(abs(p2["pwOBA"] - r["pwOBA-against"]), 3),
            "winner": "v2" if abs(p2["pwOBA"] - r["pwOBA-against"]) < abs(p1["pwOBA"] - r["pwOBA-against"]) else "v1",
        })
    rdf = pd.DataFrame(rows)
    print(rdf.to_string(index=False))

    # Save full diff to xlsx
    OUT_PATH.parent.mkdir(exist_ok=True)
    diff.sort_values("d_pwOBA").to_excel(
        OUT_PATH, sheet_name="v1_vs_v2", index=False, engine="openpyxl"
    )
    print(f"\nFull diff written to {OUT_PATH}")


if __name__ == "__main__":
    main()
