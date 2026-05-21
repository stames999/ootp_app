"""Test bias-correction paths for v2 hitter metrics vs v1 and vs the
OOTP projection reference. Goal: find the correction that gets the
tightest projections overall.

Reports:
  1. Baseline error vs v1 — per-stat (wOBA / AVG / OBP / SLG)
  2. Path A: correct wOBA only — does it help just wOBA? does it
     incidentally help the others?
  3. Path B: correct each stat independently — does it help all four?
  4. Path C: correct the per-PA component rates — does that propagate
     improvement to derived stats?
  5. Vs the OOTP reference sample (10 elite players) — does any
     correction make v2 beat v1?
"""
from pathlib import Path

import numpy as np
import pandas as pd

import metrics_hitting           # v1 hand-tuned tables
import metrics_hitting_v2        # v2 regression-derived

from reader import (
    add_hitting_career_stats, add_pitching_career_stats,
    add_scouted_ratings, add_years_at_level, load_players,
)


REF = {
    "Aaron Judge":      {"wOBA": 0.442, "AVG": 0.296, "OBP": 0.412, "SLG": 0.622},
    "Shohei Ohtani":    {"wOBA": 0.444, "AVG": 0.300, "OBP": 0.389, "SLG": 0.656},
    "Juan Soto":        {"wOBA": 0.415, "AVG": 0.282, "OBP": 0.414, "SLG": 0.542},
    "Mike Trout":       {"wOBA": 0.348, "AVG": 0.240, "OBP": 0.351, "SLG": 0.433},
    "Luis Arraez":      {"wOBA": 0.324, "AVG": 0.304, "OBP": 0.342, "SLG": 0.393},
    "Bobby Witt Jr.":   {"wOBA": 0.367, "AVG": 0.284, "OBP": 0.336, "SLG": 0.515},
    "Kyle Schwarber":   {"wOBA": 0.374, "AVG": 0.235, "OBP": 0.349, "SLG": 0.509},
    "Pete Alonso":      {"wOBA": 0.389, "AVG": 0.282, "OBP": 0.352, "SLG": 0.549},
    "Yordan Alvarez":   {"wOBA": 0.399, "AVG": 0.293, "OBP": 0.383, "SLG": 0.538},
    "Ronald Acuna Jr.": {"wOBA": 0.405, "AVG": 0.291, "OBP": 0.402, "SLG": 0.529},
}


def build_pool() -> pd.DataFrame:
    df = load_players()
    df = add_scouted_ratings(df)
    df = add_years_at_level(df)
    df = add_hitting_career_stats(df)
    df = add_pitching_career_stats(df)
    df = df[df["position"] != 1].copy()
    return df


def lin_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """OLS y = a + b*x. Returns (a, b)."""
    b, a = np.polyfit(x, y, 1)
    return a, b


def err_stats(label: str, name: str, pred: float, ref: float) -> dict:
    return {"label": label, "name": name, "pred": pred, "ref": ref,
            "err": pred - ref, "abs_err": abs(pred - ref)}


def evaluate_vs_ref(diff: pd.DataFrame, version_cols: dict) -> pd.DataFrame:
    """For each REF player, collect predictions from each version and
    return mean |error| per stat per version."""
    rows = []
    for stat in ("wOBA", "AVG", "OBP", "SLG"):
        for ver_label, col_pattern in version_cols.items():
            errs = []
            for name, refs in REF.items():
                sub = diff[diff["name"] == name]
                if sub.empty:
                    continue
                pred = sub.iloc[0][col_pattern.format(stat=stat)]
                errs.append(abs(pred - refs[stat]))
            rows.append({"stat": stat, "version": ver_label,
                          "mean_|err|": np.mean(errs),
                          "max_|err|": np.max(errs)})
    return pd.DataFrame(rows)


def main() -> None:
    pool = build_pool()
    print(f"Pool size: {len(pool)} hitters")

    df_v1 = metrics_hitting.calc_hitting_metrics(pool.copy())
    df_v2 = metrics_hitting_v2.calc_hitting_metrics(pool.copy())

    keep_id = ["player_id", "name", "org"]
    keep_stats = ["wOBA", "AVG", "OBP", "SLG",
                  "hr_pctR", "bb_pctR", "k_pctR", "1b_pctR", "2b_pctR", "3b_pctR"]

    d1 = df_v1[keep_id + keep_stats].rename(columns={c: f"{c}_v1" for c in keep_stats})
    d2 = df_v2[keep_id + keep_stats].rename(columns={c: f"{c}_v2" for c in keep_stats})
    diff = d1.merge(d2[["player_id"] + [f"{c}_v2" for c in keep_stats]],
                    on="player_id")

    print()
    print("=" * 78)
    print("0. BASELINE — uncorrected v1 vs v2")
    print("=" * 78)
    for stat in ("wOBA", "AVG", "OBP", "SLG"):
        m1, m2 = diff[f"{stat}_v1"].mean(), diff[f"{stat}_v2"].mean()
        corr = diff[f"{stat}_v1"].corr(diff[f"{stat}_v2"])
        rmse = np.sqrt(((diff[f"{stat}_v2"] - diff[f"{stat}_v1"])**2).mean())
        print(f"  {stat:<5}  v1 mean={m1:.4f}  v2 mean={m2:.4f}  corr={corr:+.4f}  "
              f"RMSE(v2 vs v1)={rmse:.5f}")

    # ================================================================
    # PATH A — correct wOBA only (v2 -> v1)
    # ================================================================
    print()
    print("=" * 78)
    print("PATH A: correct wOBA only — linear fit v2 -> v1")
    print("=" * 78)
    a_w, b_w = lin_fit(diff["wOBA_v2"].values, diff["wOBA_v1"].values)
    diff["wOBA_A"] = a_w + b_w * diff["wOBA_v2"]
    print(f"  Correction: wOBA_corrected = {a_w:+.5f} + {b_w:.5f} × wOBA_v2")
    rmse_after = np.sqrt(((diff["wOBA_A"] - diff["wOBA_v1"])**2).mean())
    print(f"  RMSE vs v1 after correction: {rmse_after:.5f}")
    print(f"  AVG/OBP/SLG are unchanged — they're still derived from "
          f"uncorrected components.")

    # ================================================================
    # PATH B — correct each stat independently
    # ================================================================
    print()
    print("=" * 78)
    print("PATH B: independent linear correction per stat (v2 -> v1)")
    print("=" * 78)
    coefs_B = {}
    for stat in ("wOBA", "AVG", "OBP", "SLG"):
        a, b = lin_fit(diff[f"{stat}_v2"].values, diff[f"{stat}_v1"].values)
        diff[f"{stat}_B"] = a + b * diff[f"{stat}_v2"]
        rmse = np.sqrt(((diff[f"{stat}_B"] - diff[f"{stat}_v1"])**2).mean())
        coefs_B[stat] = (a, b)
        print(f"  {stat:<5}  {stat}_corr = {a:+.5f} + {b:.5f} × {stat}_v2   "
              f"RMSE vs v1 = {rmse:.5f}")

    # ================================================================
    # PATH C — correct per-PA component rates, then re-derive
    # ================================================================
    print()
    print("=" * 78)
    print("PATH C: correct per-PA component rates (hr_pct, bb_pct, k_pct, "
          "1b_pct, 2b_pct, 3b_pct), then re-derive wOBA / AVG / OBP / SLG")
    print("=" * 78)
    component_rates = ["hr_pctR", "bb_pctR", "k_pctR", "1b_pctR", "2b_pctR", "3b_pctR"]
    coefs_C = {}
    for rate in component_rates:
        a, b = lin_fit(diff[f"{rate}_v2"].values, diff[f"{rate}_v1"].values)
        diff[f"{rate}_C"] = a + b * diff[f"{rate}_v2"]
        # Clamp at 0 (can't have negative rates)
        diff[f"{rate}_C"] = diff[f"{rate}_C"].clip(lower=0)
        coefs_C[rate] = (a, b)
        rmse = np.sqrt(((diff[f"{rate}_C"] - diff[f"{rate}_v1"])**2).mean())
        print(f"  {rate:<10}  corr = {a:+.5f} + {b:.5f} × v2   "
              f"RMSE vs v1 = {rmse:.6f}")

    # Re-derive slash lines from corrected components
    from config import BATTING_WOBA_WEIGHTS, HANDEDNESS_WEIGHTS
    # Apply same correction shape to L splits (assume similar bias)
    diff["wOBA_C"] = (
        BATTING_WOBA_WEIGHTS["hr_pct_wOBA_weight"] * diff["hr_pctR_C"] +
        BATTING_WOBA_WEIGHTS["bb_pct_wOBA_weight"] * diff["bb_pctR_C"] +
        BATTING_WOBA_WEIGHTS["1b_pct_wOBA_weight"] * diff["1b_pctR_C"] +
        BATTING_WOBA_WEIGHTS["2b_pct_wOBA_weight"] * diff["2b_pctR_C"] +
        BATTING_WOBA_WEIGHTS["3b_pct_wOBA_weight"] * diff["3b_pctR_C"]
    )
    hits_pa = diff["1b_pctR_C"] + diff["2b_pctR_C"] + diff["3b_pctR_C"] + diff["hr_pctR_C"]
    tb_pa = (diff["1b_pctR_C"] + 2 * diff["2b_pctR_C"]
              + 3 * diff["3b_pctR_C"] + 4 * diff["hr_pctR_C"])
    ab_pa = 1 - diff["bb_pctR_C"]
    diff["AVG_C"] = (hits_pa / ab_pa).round(3)
    diff["OBP_C"] = (hits_pa + diff["bb_pctR_C"]).round(3)
    diff["SLG_C"] = (tb_pa / ab_pa).round(3)

    for stat in ("wOBA", "AVG", "OBP", "SLG"):
        rmse = np.sqrt(((diff[f"{stat}_C"] - diff[f"{stat}_v1"])**2).mean())
        m = diff[f"{stat}_C"].mean()
        print(f"  Derived {stat:<5}  mean={m:.4f}  RMSE vs v1={rmse:.5f}")

    # ================================================================
    # vs the OOTP REFERENCE — does any correction make v2 better than v1?
    # ================================================================
    print()
    print("=" * 78)
    print("REFERENCE EVAL — mean |error| vs OOTP projection (10 elite players)")
    print("=" * 78)
    eval_df = evaluate_vs_ref(diff, {
        "v1":          "{stat}_v1",
        "v2":          "{stat}_v2",
        "v2 Path A":   "{stat}_A" if "_A" in diff.columns else "{stat}_v2",  # only wOBA
        "v2 Path B":   "{stat}_B",
        "v2 Path C":   "{stat}_C",
    })
    pivot = eval_df.pivot(index="stat", columns="version", values="mean_|err|").round(4)
    print(pivot.to_string())
    print()
    print("(Path A only adjusts wOBA — its AVG/OBP/SLG mirror v2 baseline.)")

    # Detail: per-player table for reference
    print()
    print("=" * 78)
    print("Per-player wOBA vs reference (lower = better)")
    print("=" * 78)
    rows = []
    for name, refs in REF.items():
        sub = diff[diff["name"] == name]
        if sub.empty:
            continue
        r = sub.iloc[0]
        rows.append({
            "name": name,
            "ref": refs["wOBA"],
            "v1": round(r["wOBA_v1"], 3),
            "v2": round(r["wOBA_v2"], 3),
            "v2_A": round(r["wOBA_A"], 3),
            "v2_B": round(r["wOBA_B"], 3),
            "v2_C": round(r["wOBA_C"], 3),
        })
    print(pd.DataFrame(rows).to_string(index=False))

    # ================================================================
    # Final recommendation: which path produces tightest predictions?
    # ================================================================
    print()
    print("=" * 78)
    print("VERDICT")
    print("=" * 78)
    print(f"\n  Best path per stat (lowest mean |err| vs OOTP reference):")
    best = pivot.idxmin(axis=1)
    for stat, ver in best.items():
        err = pivot.loc[stat, ver]
        print(f"    {stat}: {ver} ({err:.4f})")

    print()
    print("  Coefficients to embed if you want Path C:")
    for rate, (a, b) in coefs_C.items():
        print(f"    {rate}: corr = {a:+.5f} + {b:.5f} × v2_rate")


if __name__ == "__main__":
    main()
