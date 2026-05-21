"""Tighter rating-to-outcome models: collinearity diagnostics + nonlinear
terms + interaction tests. Goal is to squeeze the residuals out of the
HR/BB/SO/BABIP/2+3 models we built off the in-game prediction sample.
"""
import io

import numpy as np
import pandas as pd
from numpy.linalg import lstsq
from scipy import stats

from exports.gap_speed_regression import DATA_TSV


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
    rmse = np.sqrt(ss_res / n)
    return {"labels": labels, "coef": beta, "se": se, "t": t, "p": p,
            "r2": r2, "n": n, "rmse": rmse, "yhat": yhat,
            "adj_r2": 1 - (1 - r2) * (n - 1) / (n - k)}


def print_ols(result: dict, title: str) -> None:
    print(f"\n--- {title} ---")
    print(f"  n = {result['n']}  R^2 = {result['r2']:.4f}  "
          f"Adj-R^2 = {result['adj_r2']:.4f}  RMSE = {result['rmse']:.3f}")
    for lab, c, s, t, p in zip(result["labels"], result["coef"],
                                result["se"], result["t"], result["p"]):
        print(f"    {lab:<18}  coef={c:+.5f}  SE={s:.5f}  "
              f"t={t:+6.2f}  p={p:.2e}")


def vif(X: np.ndarray, labels: list[str]) -> pd.DataFrame:
    """Variance inflation factor for each non-intercept column."""
    rows = []
    for j, lab in enumerate(labels):
        if lab == "intercept":
            continue
        # Regress column j on all other non-intercept columns
        other = [k for k in range(X.shape[1])
                 if k != j and labels[k] != "intercept"]
        if not other:
            rows.append({"predictor": lab, "VIF": float("nan")})
            continue
        Xj = np.column_stack([np.ones(X.shape[0]), X[:, other]])
        y = X[:, j]
        b, _, _, _ = lstsq(Xj, y, rcond=None)
        r2 = 1 - np.sum((y - Xj @ b)**2) / np.sum((y - y.mean())**2)
        rows.append({"predictor": lab, "VIF": 1 / (1 - r2)})
    return pd.DataFrame(rows)


def main() -> None:
    df = pd.read_csv(io.StringIO(DATA_TSV), sep="\t")
    for c in ("2+3", "3_ratio", "HR", "BB", "SO", "BABIP", "PA", "AB", "1B", "2B", "3B",
              "BABIPvR", "BABIPvL", "K-avoidvR", "K-avoidvL",
              "PowervR", "PowervL", "EyevR", "EyevL", "GapvR", "GapvL", "Speed"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["three_ratio"] = np.where(df["2+3"] > 0, df["3B"] / df["2+3"], np.nan)

    n = len(df)
    print(f"Sample: {n} hitters\n")

    # ================================================================
    # 1. Correlation matrix of split ratings
    # ================================================================
    rating_cols = ["BABIPvR", "BABIPvL", "K-avoidvR", "K-avoidvL",
                   "PowervR", "PowervL", "EyevR", "EyevL",
                   "GapvR", "GapvL", "Speed"]
    print("=" * 70)
    print("1. Pearson correlations between vsR and vsL halves of each rating")
    print("=" * 70)
    pairs = [("BABIPvR", "BABIPvL"), ("K-avoidvR", "K-avoidvL"),
             ("PowervR", "PowervL"), ("EyevR", "EyevL"), ("GapvR", "GapvL")]
    for r, l in pairs:
        c = df[r].corr(df[l])
        print(f"  corr({r}, {l}) = {c:+.4f}")
    print("\n  -> vsR/vsL splits are near-identical (r > .94) for most skills.")
    print("     This causes collinearity when both are used as predictors.")

    # ================================================================
    # 2. VIF on the multivariate models
    # ================================================================
    print("\n" + "=" * 70)
    print("2. VIF (variance inflation) for the split-handedness models")
    print("=" * 70)
    for primary in ["Power", "Eye", "K-avoid", "BABIP", "Gap"]:
        r = f"{primary}vR"
        l = f"{primary}vL"
        X = np.column_stack([np.ones(n), df[r].values, df[l].values])
        v = vif(X, ["intercept", r, l])
        print(f"  {primary}: VIF({r})={v.iloc[0]['VIF']:.1f}  "
              f"VIF({l})={v.iloc[1]['VIF']:.1f}")
    print("\n  -> Anything > 10 means the split-handedness coefficients are")
    print("     unstable / hard to interpret separately.")

    # ================================================================
    # 3. Compare model variants for HR (the canonical "single-rating
    #    dominant" outcome)
    # ================================================================
    print("\n" + "=" * 70)
    print("3. Model variants for HR")
    print("=" * 70)

    df["PowerAvg"] = (df["PowervR"] + df["PowervL"]) / 2
    df["EyeAvg"]   = (df["EyevR"]   + df["EyevL"])   / 2
    df["KavoidAvg"]= (df["K-avoidvR"]+ df["K-avoidvL"]) / 2
    df["BabipAvg"] = (df["BABIPvR"] + df["BABIPvL"]) / 2
    df["GapAvg"]   = (df["GapvR"]   + df["GapvL"])   / 2

    variants_HR = [
        ("HR ~ PowerAvg", ["PowerAvg"]),
        ("HR ~ PowervR + PowervL", ["PowervR", "PowervL"]),
        ("HR ~ PowerAvg + PowerAvg^2", ["PowerAvg", "PowerAvg^2"]),
        ("HR ~ PowerAvg + EyeAvg", ["PowerAvg", "EyeAvg"]),
        ("HR ~ PowerAvg + PowerAvg*EyeAvg", ["PowerAvg", "Power*Eye"]),
        ("HR ~ PowerAvg + EyeAvg + KavoidAvg", ["PowerAvg", "EyeAvg", "KavoidAvg"]),
    ]
    df["PowerAvg^2"] = df["PowerAvg"]**2
    df["Power*Eye"] = df["PowerAvg"] * df["EyeAvg"]
    for title, cols in variants_HR:
        X = np.column_stack([np.ones(n)] + [df[c].values for c in cols])
        r = ols(X, df["HR"].values, ["intercept"] + cols)
        print(f"  {title:<48}  R²={r['r2']:.4f}  Adj-R²={r['adj_r2']:.4f}  "
              f"RMSE={r['rmse']:.2f}")

    # The best HR model — full diagnostics
    print()
    X = np.column_stack([np.ones(n), df["PowerAvg"].values, df["PowerAvg^2"].values])
    print_ols(
        ols(X, df["HR"].values, ["intercept", "PowerAvg", "PowerAvg^2"]),
        "HR ~ PowerAvg + PowerAvg^2 (quadratic — captures elite curl)",
    )

    # ================================================================
    # 4. Same drill for BB, SO, BABIP, 2+3
    # ================================================================
    print("\n" + "=" * 70)
    print("4. Variant scan: BB / SO / BABIP / 2+3")
    print("=" * 70)

    df["EyeAvg^2"] = df["EyeAvg"]**2
    df["KavoidAvg^2"] = df["KavoidAvg"]**2
    df["BabipAvg^2"] = df["BabipAvg"]**2
    df["GapAvg^2"] = df["GapAvg"]**2
    df["Gap*BABIP"] = df["GapAvg"] * df["BabipAvg"]

    scans = [
        ("BB", [
            ("EyeAvg", ["EyeAvg"]),
            ("EyevR + EyevL", ["EyevR", "EyevL"]),
            ("EyeAvg + EyeAvg^2", ["EyeAvg", "EyeAvg^2"]),
            ("EyeAvg + PowerAvg", ["EyeAvg", "PowerAvg"]),
        ]),
        ("SO", [
            ("KavoidAvg", ["KavoidAvg"]),
            ("K-avoidvR + K-avoidvL", ["K-avoidvR", "K-avoidvL"]),
            ("KavoidAvg + KavoidAvg^2", ["KavoidAvg", "KavoidAvg^2"]),
            ("KavoidAvg + PowerAvg + EyeAvg", ["KavoidAvg", "PowerAvg", "EyeAvg"]),
        ]),
        ("BABIP", [
            ("BabipAvg", ["BabipAvg"]),
            ("BABIPvR + BABIPvL", ["BABIPvR", "BABIPvL"]),
            ("BabipAvg + Speed", ["BabipAvg", "Speed"]),
            ("BabipAvg + GapAvg", ["BabipAvg", "GapAvg"]),
            ("BabipAvg + BabipAvg^2", ["BabipAvg", "BabipAvg^2"]),
        ]),
        ("2+3", [
            ("GapAvg", ["GapAvg"]),
            ("GapvR + GapvL", ["GapvR", "GapvL"]),
            ("GapAvg + BabipAvg", ["GapAvg", "BabipAvg"]),
            ("GapAvg + BabipAvg + Gap*BABIP", ["GapAvg", "BabipAvg", "Gap*BABIP"]),
            ("GapAvg + BabipAvg + PowerAvg + KavoidAvg",
             ["GapAvg", "BabipAvg", "PowerAvg", "KavoidAvg"]),
        ]),
    ]
    for ycol, variants in scans:
        d = df.dropna(subset=[ycol])
        print(f"\n  Outcome: {ycol}")
        for title, cols in variants:
            X = np.column_stack([np.ones(len(d))] + [d[c].values for c in cols])
            r = ols(X, d[ycol].values, ["intercept"] + cols)
            print(f"    {title:<44}  R²={r['r2']:.4f}  Adj-R²={r['adj_r2']:.4f}  "
                  f"RMSE={r['rmse']:.3f}")

    # ================================================================
    # 5. Cross-validated comparison: do extra terms generalise?
    # ================================================================
    print("\n" + "=" * 70)
    print("5. Leave-one-out cross-validated RMSE")
    print("    (more honest than in-sample R² — penalises overfitting)")
    print("=" * 70)

    def loo_rmse(d, ycol, cols):
        y = d[ycol].values
        X = np.column_stack([np.ones(len(d))] + [d[c].values for c in cols])
        n = len(d)
        errors = []
        for i in range(n):
            idx = np.arange(n) != i
            Xtr, ytr = X[idx], y[idx]
            beta, _, _, _ = lstsq(Xtr, ytr, rcond=None)
            yh = X[i] @ beta
            errors.append((y[i] - yh)**2)
        return np.sqrt(np.mean(errors))

    cv_specs = [
        ("HR", [
            ("PowerAvg", ["PowerAvg"]),
            ("PowervR + PowervL", ["PowervR", "PowervL"]),
            ("PowerAvg + PowerAvg^2", ["PowerAvg", "PowerAvg^2"]),
        ]),
        ("BB", [
            ("EyeAvg", ["EyeAvg"]),
            ("EyevR + EyevL", ["EyevR", "EyevL"]),
            ("EyeAvg + EyeAvg^2", ["EyeAvg", "EyeAvg^2"]),
        ]),
        ("SO", [
            ("KavoidAvg", ["KavoidAvg"]),
            ("K-avoidvR + K-avoidvL", ["K-avoidvR", "K-avoidvL"]),
            ("KavoidAvg + KavoidAvg^2", ["KavoidAvg", "KavoidAvg^2"]),
            ("KavoidAvg + PowerAvg + EyeAvg",
             ["KavoidAvg", "PowerAvg", "EyeAvg"]),
        ]),
        ("BABIP", [
            ("BabipAvg", ["BabipAvg"]),
            ("BABIPvR + BABIPvL", ["BABIPvR", "BABIPvL"]),
            ("BabipAvg + GapAvg", ["BabipAvg", "GapAvg"]),
        ]),
        ("2+3", [
            ("GapAvg", ["GapAvg"]),
            ("GapAvg + BabipAvg", ["GapAvg", "BabipAvg"]),
            ("GapvR + GapvL + BabipAvg", ["GapvR", "GapvL", "BabipAvg"]),
        ]),
    ]
    for ycol, variants in cv_specs:
        d = df.dropna(subset=[ycol])
        print(f"\n  Outcome: {ycol}  (LOO-RMSE — lower is better)")
        for title, cols in variants:
            r = loo_rmse(d, ycol, cols)
            print(f"    {title:<44}  LOO-RMSE = {r:.3f}")


if __name__ == "__main__":
    main()
