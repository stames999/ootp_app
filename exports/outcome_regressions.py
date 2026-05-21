"""Empirical regressions using vsR/vsL ratings separately.

For each outcome (2+3, triples-ratio, HR, BB, SO, BABIP-stat) we run:
  1. Univariate scan against each individual rating (vsR and vsL kept
     separate, plus Speed which has no split).
  2. Multivariate "best" model using both handedness splits of the
     dominant rating + relevant supporting ratings.

The team-of-clones sim plays a mixed-handedness pitching staff, so each
season's outcomes blend exposure to RHP and LHP. The vsR + vsL split
lets us recover the empirical mix weight (in real MLB ~70% vsRHP /
30% vsLHP — the sim should produce coefficients in roughly that ratio
if the engine respects splits).

BABIP added as a 6th outcome (stat, not rating) since you asked.
"""
import io

import numpy as np
import pandas as pd
from numpy.linalg import lstsq
from scipy import stats

from exports.gap_speed_regression import DATA_TSV


def univariate(df: pd.DataFrame, y_col: str, predictors: list[str]) -> pd.DataFrame:
    rows = []
    y = df[y_col].values
    for p in predictors:
        x = df[p].values
        s, i, r, pv, se = stats.linregress(x, y)
        rows.append({
            "predictor": p, "slope": s, "intercept": i,
            "R2": r**2, "p": pv,
        })
    return pd.DataFrame(rows).sort_values("R2", ascending=False)


def ols(X: np.ndarray, y: np.ndarray, labels: list[str]) -> dict:
    beta, _, _, _ = lstsq(X, y, rcond=None)
    yhat = X @ beta
    ss_tot = np.sum((y - y.mean())**2)
    ss_res = np.sum((y - yhat)**2)
    r2 = 1 - ss_res / ss_tot
    n, k = X.shape
    sigma2 = ss_res / (n - k)
    cov = sigma2 * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    t = beta / se
    p = 2 * (1 - stats.t.cdf(np.abs(t), df=n - k))
    return {"labels": labels, "coef": beta, "se": se, "t": t, "p": p,
            "r2": r2, "n": n}


def print_ols(result: dict, title: str) -> None:
    print(f"\n--- {title} ---")
    print(f"  n = {result['n']}, R^2 = {result['r2']:.4f}")
    for lab, c, s, t, p in zip(result["labels"], result["coef"],
                                result["se"], result["t"], result["p"]):
        print(f"    {lab:<12}  coef={c:+.5f}  SE={s:.5f}  t={t:+6.2f}  p={p:.2e}")
    # If a vsR and vsL pair appear, report the implied mix weight
    if all(x in result["labels"] for x in ("vsR", "vsL")):
        ir = result["labels"].index("vsR")
        il = result["labels"].index("vsL")
        cr, cl = result["coef"][ir], result["coef"][il]
        if cr + cl != 0:
            w_r = cr / (cr + cl)
            print(f"    Implied vsR mix: {w_r*100:.1f}% (vsL {(1-w_r)*100:.1f}%)")


def main() -> None:
    df = pd.read_csv(io.StringIO(DATA_TSV), sep="\t")

    # Numeric coercion
    for c in ("2+3", "3_ratio", "HR", "BB", "SO", "BABIP", "PA", "AB",
              "BABIPvR", "BABIPvL", "K-avoidvR", "K-avoidvL",
              "PowervR", "PowervL", "EyevR", "EyevL", "GapvR", "GapvL",
              "Speed"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Clean recompute of triples-ratio (CSV had blanks as "0")
    df["three_ratio"] = np.where(df["2+3"] > 0, df["3B"] / df["2+3"], np.nan)

    SPLIT_PAIRS = {
        "BABIP":   ("BABIPvR", "BABIPvL"),
        "Kavoid":  ("K-avoidvR", "K-avoidvL"),
        "Power":   ("PowervR", "PowervL"),
        "Eye":     ("EyevR", "EyevL"),
        "Gap":     ("GapvR", "GapvL"),
    }
    INDIVIDUAL_PREDICTORS = [
        "BABIPvR", "BABIPvL", "K-avoidvR", "K-avoidvL",
        "PowervR", "PowervL", "EyevR", "EyevL", "GapvR", "GapvL", "Speed",
    ]
    n = len(df)

    print("=" * 80)
    print(f"Sample: {n} hitters, team-of-clones sim, ~550 AB each")
    print("All ratings vsR / vsL kept separate")
    print("=" * 80)

    def run(name: str, ycol: str, primary: str,
            include_secondary: list[str] = None,
            subset: pd.DataFrame = None):
        d = (subset if subset is not None else df).dropna(subset=[ycol])
        print(f"\n========== {name} ==========")
        uni = univariate(d, ycol, INDIVIDUAL_PREDICTORS)
        print(f"\nUnivariate scan (n={len(d)}, top 6):")
        print(uni.head(6).to_string(index=False))

        # Multivariate: vsR + vsL of primary, plus any secondary ratings
        cols = [("vsR", SPLIT_PAIRS[primary][0]),
                ("vsL", SPLIT_PAIRS[primary][1])]
        for sec in (include_secondary or []):
            if sec in SPLIT_PAIRS:
                cols.append((f"{sec}vR", SPLIT_PAIRS[sec][0]))
                cols.append((f"{sec}vL", SPLIT_PAIRS[sec][1]))
            else:
                cols.append((sec, sec))
        labels = ["intercept"] + [c[0] for c in cols]
        X = np.column_stack(
            [np.ones(len(d))] + [d[c[1]].values for c in cols]
        )
        y = d[ycol].values
        title = f"{ycol} ~ {primary}vR + {primary}vL"
        if include_secondary:
            title += " + " + " + ".join(include_secondary)
        print_ols(ols(X, y, labels), title)

    # ----------------------------------------------------------------
    # 1.  2B + 3B
    # ----------------------------------------------------------------
    run("OUTCOME 1: 2B + 3B", "2+3", "Gap", ["BABIP"])

    # ----------------------------------------------------------------
    # 2.  triples ratio = 3B / (2B + 3B)   — primary is Speed (no split)
    # ----------------------------------------------------------------
    sub = df[df["2+3"] >= 10].dropna(subset=["three_ratio"]).copy()
    print("\n========== OUTCOME 2: triples ratio = 3B / (2B+3B) ==========")
    uni = univariate(sub, "three_ratio", INDIVIDUAL_PREDICTORS)
    print(f"\nUnivariate scan (n={len(sub)}, top 6):")
    print(uni.head(6).to_string(index=False))
    # Multivariate: Speed + Gap vsR/vsL (control)
    X = np.column_stack([
        np.ones(len(sub)),
        sub["Speed"].values, sub["GapvR"].values, sub["GapvL"].values,
    ])
    print_ols(
        ols(X, sub["three_ratio"].values,
            ["intercept", "Speed", "GapvR", "GapvL"]),
        "three_ratio ~ Speed + GapvR + GapvL",
    )

    # ----------------------------------------------------------------
    # 3.  HR
    # ----------------------------------------------------------------
    run("OUTCOME 3: HR", "HR", "Power")

    # ----------------------------------------------------------------
    # 4.  BB
    # ----------------------------------------------------------------
    run("OUTCOME 4: BB", "BB", "Eye")

    # ----------------------------------------------------------------
    # 5.  SO
    # ----------------------------------------------------------------
    run("OUTCOME 5: SO", "SO", "Kavoid")

    # ----------------------------------------------------------------
    # 6.  BABIP (stat)  — predicted by BABIP ratings (+ Speed for IF hits)
    # ----------------------------------------------------------------
    run("OUTCOME 6: BABIP (stat)", "BABIP", "BABIP", ["Speed"])

    # ================================================================
    # FINAL: best multivariate per outcome — formula sheet
    # ================================================================
    print("\n" + "=" * 80)
    print("PREDICTOR SUMMARY — split-handedness multivariate per outcome")
    print("=" * 80)

    formulas = [
        ("2B + 3B",  "2+3",          ["GapvR", "GapvL", "BABIPvR", "BABIPvL"], df),
        ("HR",       "HR",           ["PowervR", "PowervL"], df),
        ("BB",       "BB",           ["EyevR", "EyevL"], df),
        ("SO",       "SO",           ["K-avoidvR", "K-avoidvL"], df),
        ("BABIP",    "BABIP",        ["BABIPvR", "BABIPvL", "Speed"], df),
        ("3-ratio",  "three_ratio",  ["Speed", "GapvR", "GapvL"], sub),
    ]
    for name, ycol, preds, data in formulas:
        d = data.dropna(subset=[ycol] + preds)
        X = np.column_stack([np.ones(len(d))] + [d[p].values for p in preds])
        y = d[ycol].values
        beta, _, _, _ = lstsq(X, y, rcond=None)
        yhat = X @ beta
        ss_tot = np.sum((y - y.mean())**2)
        ss_res = np.sum((y - yhat)**2)
        r2 = 1 - ss_res / ss_tot
        eq_parts = [f"{beta[0]:+.4f}"]
        for p, b in zip(preds, beta[1:]):
            eq_parts.append(f"{b:+.5f}*{p}")
        print(f"\n  {name}:")
        print("    " + "  ".join(eq_parts))
        print(f"    R^2 = {r2:.4f}, n = {len(d)}")


if __name__ == "__main__":
    main()
