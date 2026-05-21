"""Pitcher regression scan with PITCH ARSENAL included.

Adds to the earlier scan:
  - Count of pitches thrown (non-zero pitch ratings)
  - Each pitch type as a univariate predictor
  - Pitch mix dummies + interactions (does Stuff × num_pitches help?)
  - Best fastball quality (max of fastball/sinker/cutter)
  - Best off-speed quality (max of curve/slider/changeup/split/etc.)
"""
import io

import numpy as np
import pandas as pd
from numpy.linalg import lstsq
from scipy import stats

from exports.pitcher_outcome_regressions import DATA_TSV, parse_pct, ols, loo_rmse


def univariate(df, y_col, predictors):
    rows = []
    y = df[y_col].values
    for p in predictors:
        if p not in df.columns:
            continue
        x = df[p].values
        mask = ~(np.isnan(x) | np.isnan(y))
        if mask.sum() < 10:
            continue
        s, i, r, pv, se = stats.linregress(x[mask], y[mask])
        rows.append({"predictor": p, "slope": s, "intercept": i,
                     "R2": r**2, "p": pv, "n": int(mask.sum())})
    return pd.DataFrame(rows).sort_values("R2", ascending=False)


def main():
    df = pd.read_csv(io.StringIO(DATA_TSV), sep="\t")

    for c in ("K%", "BB%", "HR%", "HR/FB"):
        df[c] = df[c].apply(parse_pct)
    num_cols = ["Age","BF","PA","IP","FIP","WHIP","K","H","HR","BB","HP","ER",
                "K/9","BB/9","HR/9","BABIP-against","pwOBA-against","GO","FO",
                "StuffvR","StuffvL","MovementvR","MovementvL",
                "ControlvR","ControlvL","HRAvR","HRAvL","pBABIPvR","pBABIPvL",
                "Fastball","Slider","Curveball","Changeup","Sinker","Splitter",
                "Cutter","CircleCh","Knucklecurve","Knuckleball","Forkball","Screwball",
                "Velocity","VelocityTgt","ArmSlot","Stamina","GroundFly","Hold",
                "Balk","WildPitch"]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Aggregates
    df["Stuff"]     = (df["StuffvR"] + df["StuffvL"]) / 2
    df["Movement"]  = (df["MovementvR"] + df["MovementvL"]) / 2
    df["Control"]   = (df["ControlvR"] + df["ControlvL"]) / 2
    df["HRA"]       = (df["HRAvR"] + df["HRAvL"]) / 2
    df["pBABIP"]    = (df["pBABIPvR"] + df["pBABIPvL"]) / 2

    PITCHES = ["Fastball","Slider","Curveball","Changeup","Sinker","Splitter",
               "Cutter","CircleCh","Knucklecurve","Knuckleball","Forkball","Screwball"]
    FASTBALL_TYPES = ["Fastball", "Sinker", "Cutter"]
    OFFSPEED_TYPES = ["Slider","Curveball","Changeup","Splitter","CircleCh",
                       "Knucklecurve","Knuckleball","Forkball","Screwball"]

    # Pitch-mix features
    df["NumPitches"]    = (df[PITCHES] > 0).sum(axis=1)
    df["BestFB"]        = df[FASTBALL_TYPES].max(axis=1)
    df["BestOffspeed"]  = df[OFFSPEED_TYPES].max(axis=1)
    df["MeanArsenalQ"]  = df[PITCHES].where(df[PITCHES] > 0).mean(axis=1)
    df["TotalArsenalQ"] = df[PITCHES].sum(axis=1)  # sum of all pitch ratings
    # Binary indicators (does pitcher throw X?)
    for p in PITCHES:
        df[f"Has_{p}"] = (df[p] > 0).astype(int)
    # Specific archetype flags
    df["HasKnuckleball"] = df["Knuckleball"] > 0
    df["HasSplitter"]    = (df["Splitter"] > 0) | (df["Forkball"] > 0)
    df["HasCutter"]      = df["Cutter"] > 0
    df["HasSinker"]      = df["Sinker"] > 0

    n = len(df.dropna(subset=["pwOBA-against"]))
    print(f"Sample: {n} pitchers with complete data\n")
    print(f"Pitch arsenal distribution:")
    print(f"  Avg pitches per arm: {df['NumPitches'].mean():.1f}")
    print(f"  Pitchers with knuckleball: {df['HasKnuckleball'].sum()}")
    print(f"  Pitchers with splitter/forkball: {df['HasSplitter'].sum()}")
    print(f"  Pitchers with cutter: {df['HasCutter'].sum()}")
    print(f"  Pitchers with sinker: {df['HasSinker'].sum()}")

    # ================================================================
    # 1. Does pitch arsenal information add predictive power?
    # ================================================================
    print("\n" + "=" * 78)
    print("1. DOES PITCH ARSENAL INFO HELP? — compare baseline vs +arsenal")
    print("=" * 78)

    arsenal_cols = ["NumPitches", "BestFB", "BestOffspeed", "MeanArsenalQ",
                    "TotalArsenalQ"]
    outcomes = ["K%", "BB%", "HR%", "BABIP-against", "pwOBA-against"]
    base_cols_by_outcome = {
        "K%":             ["Stuff"],
        "BB%":            ["Control"],
        "HR%":            ["HRA"],
        "BABIP-against":  ["pBABIP"],
        "pwOBA-against":  ["Stuff","Movement","Control","HRA","pBABIP"],
    }
    for ycol in outcomes:
        d = df.dropna(subset=[ycol])
        base = loo_rmse(d, ycol, base_cols_by_outcome[ycol])
        print(f"\n  {ycol}  (baseline LOO-RMSE = {base:.5f})")
        for a in arsenal_cols:
            with_a = loo_rmse(d, ycol, base_cols_by_outcome[ycol] + [a])
            delta = with_a - base
            flag = " ← helps" if delta < -0.0001 else ""
            print(f"    + {a:<18}  LOO-RMSE = {with_a:.5f}   Δ = {delta:+.5f}{flag}")

    # ================================================================
    # 2. Univariate scan of every individual pitch rating against
    #    each outcome (does throwing X help for outcome Y?)
    # ================================================================
    print("\n" + "=" * 78)
    print("2. PITCH-LEVEL UNIVARIATE SCAN (each pitch type only — top 5 per outcome)")
    print("=" * 78)
    for ycol in outcomes:
        d = df.dropna(subset=[ycol])
        # Restrict to pitchers who throw the pitch (rating > 0)
        rows = []
        for p in PITCHES:
            mask = (d[p] > 0) & ~d[ycol].isna()
            if mask.sum() < 15:
                continue
            x = d.loc[mask, p].values
            y = d.loc[mask, ycol].values
            s, i, r, pv, _ = stats.linregress(x, y)
            rows.append({"pitch": p, "n_throws": int(mask.sum()),
                         "slope": s, "R2": r**2, "p": pv})
        u = pd.DataFrame(rows).sort_values("R2", ascending=False)
        print(f"\n  {ycol}:")
        print(u.head(5).to_string(index=False))

    # ================================================================
    # 3. Multivariate with pitch arsenal added
    # ================================================================
    print("\n" + "=" * 78)
    print("3. MULTIVARIATE — best model with arsenal features")
    print("=" * 78)

    df["Stuff2"]   = df["Stuff"]**2
    df["Control2"] = df["Control"]**2
    df["HRA2"]     = df["HRA"]**2

    specs = [
        ("K%",            [["Stuff", "Stuff2"],
                            ["Stuff", "Stuff2", "NumPitches"],
                            ["Stuff", "Stuff2", "BestFB"],
                            ["Stuff", "Stuff2", "BestOffspeed"],
                            ["Stuff", "Stuff2", "NumPitches", "BestOffspeed"]]),
        ("BB%",           [["Control", "Control2"],
                            ["Control", "Control2", "NumPitches"],
                            ["Control", "Control2", "BestFB"]]),
        ("HR%",           [["HRA", "HRA2"],
                            ["HRA", "HRA2", "GroundFly"],
                            ["HRA", "HRA2", "GroundFly", "BestOffspeed"],
                            ["HRA", "HRA2", "NumPitches"]]),
        ("BABIP-against", [["pBABIP"],
                            ["pBABIP", "GroundFly"],
                            ["pBABIP", "NumPitches"],
                            ["pBABIP", "BestOffspeed"]]),
        ("pwOBA-against", [["Stuff","Movement","Control","HRA","pBABIP"],
                            ["Stuff","Stuff2","Control","HRA","pBABIP"],
                            ["Stuff","Stuff2","Control","HRA","pBABIP","NumPitches"],
                            ["Stuff","Stuff2","Control","HRA","pBABIP","BestOffspeed"],
                            ["Stuff","Stuff2","Control","Control2","HRA","HRA2","pBABIP"]]),
    ]
    for ycol, variants in specs:
        d = df.dropna(subset=[ycol])
        print(f"\n  {ycol}:")
        for cols in variants:
            cols_present = [c for c in cols if c in d.columns]
            r = loo_rmse(d, ycol, cols_present)
            print(f"    {' + '.join(cols_present):<70}  LOO-RMSE = {r:.5f}")

    # ================================================================
    # 4. Pitch-presence flags as features (binary)
    # ================================================================
    print("\n" + "=" * 78)
    print("4. BINARY 'Has_X' flags (does throwing pitch X shift outcome?)")
    print("    Tested as additions on top of the best multivariate base.")
    print("=" * 78)
    for ycol in outcomes:
        d = df.dropna(subset=[ycol])
        if ycol == "pwOBA-against":
            base = ["Stuff","Stuff2","Control","HRA","pBABIP"]
        elif ycol == "K%":
            base = ["Stuff","Stuff2"]
        elif ycol == "BB%":
            base = ["Control","Control2"]
        elif ycol == "HR%":
            base = ["HRA","HRA2","GroundFly"]
        else:
            base = ["pBABIP"]
        base_rmse = loo_rmse(d, ycol, base)
        rows = []
        for p in PITCHES:
            flag = f"Has_{p}"
            if flag not in d.columns:
                continue
            if d[flag].sum() < 10 or d[flag].sum() > len(d) - 10:
                continue  # need both classes
            new_rmse = loo_rmse(d, ycol, base + [flag])
            rows.append({"pitch": p, "n_with": int(d[flag].sum()),
                         "base_LOO": base_rmse, "new_LOO": new_rmse,
                         "Δ": new_rmse - base_rmse})
        u = pd.DataFrame(rows).sort_values("Δ")
        print(f"\n  {ycol}  (base LOO-RMSE = {base_rmse:.5f})")
        helpful = u[u["Δ"] < -0.0001]
        if not helpful.empty:
            print(helpful.head(5).to_string(index=False))
        else:
            print("    (no Has_X flag improves LOO-RMSE)")


if __name__ == "__main__":
    main()
