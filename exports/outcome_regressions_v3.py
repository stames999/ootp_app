"""Exhaustive rating-to-outcome diagnostic and tightening pass.

Tests covered:
  1. Sample diagnostics  — rating coverage by predictor range, outlier
     influence (Cook's distance) on the headline HR/BB/SO models.
  2. Per-PA rates        — re-fit each outcome as a per-PA rate (more
     natural than counts because PA varies a little).
  3. All-pairs interactions — scan every (rating_i × rating_j) product
     against every outcome; promote anything that beats the parent model
     by > 0.005 LOO-RMSE.
  4. Drop-outlier sensitivity — drop the top-5 by outcome, refit, see
     if coefficients move materially.
  5. Logit transform on rate outcomes (HR/PA, BB/PA, SO/PA) — does the
     bounded transform help at the elite tail?
  6. Residual cross-correlation — do the model residuals correlate
     across outcomes? Hidden shared variable check.
  7. Derived outcomes (1B count, wOBA) — calibrate directly.
  8. Sample-size verdict — bootstrap confidence intervals on the
     headline coefficients; flag any that aren't robustly distinguishable
     from zero.
"""
import io

import numpy as np
import pandas as pd
from numpy.linalg import lstsq
from scipy import stats

from exports.gap_speed_regression import DATA_TSV


def ols(X, y, labels):
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
            "r2": r2, "n": n, "rmse": np.sqrt(ss_res / n),
            "adj_r2": 1 - (1 - r2) * (n - 1) / (n - k), "yhat": yhat,
            "resid": y - yhat}


def loo_rmse(d, ycol, cols):
    y = d[ycol].values
    X = np.column_stack([np.ones(len(d))] + [d[c].values for c in cols])
    n = len(d)
    errors = []
    for i in range(n):
        idx = np.arange(n) != i
        beta, _, _, _ = lstsq(X[idx], y[idx], rcond=None)
        errors.append((y[i] - X[i] @ beta)**2)
    return float(np.sqrt(np.mean(errors)))


def cooks(X, y):
    """Cook's distance: influence of each observation on the fit."""
    beta, _, _, _ = lstsq(X, y, rcond=None)
    n, k = X.shape
    yhat = X @ beta
    resid = y - yhat
    mse = np.sum(resid**2) / (n - k)
    XtX_inv = np.linalg.inv(X.T @ X)
    H = X @ XtX_inv @ X.T
    h_ii = np.diag(H)
    cooks_d = resid**2 / (k * mse) * h_ii / (1 - h_ii)**2
    return cooks_d


def main():
    df = pd.read_csv(io.StringIO(DATA_TSV), sep="\t")
    for c in ("2+3", "3_ratio", "HR", "BB", "SO", "BABIP", "PA", "AB", "1B", "2B", "3B",
              "HBP", "GO+FO",
              "BABIPvR", "BABIPvL", "K-avoidvR", "K-avoidvL",
              "PowervR", "PowervL", "EyevR", "EyevL", "GapvR", "GapvL", "Speed"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df["three_ratio"] = np.where(df["2+3"] > 0, df["3B"] / df["2+3"], np.nan)
    df["PowerAvg"]  = (df["PowervR"] + df["PowervL"]) / 2
    df["EyeAvg"]    = (df["EyevR"]   + df["EyevL"])   / 2
    df["KavoidAvg"] = (df["K-avoidvR"] + df["K-avoidvL"]) / 2
    df["BabipAvg"]  = (df["BABIPvR"] + df["BABIPvL"]) / 2
    df["GapAvg"]    = (df["GapvR"]   + df["GapvL"])   / 2
    df["PowerAvg2"] = df["PowerAvg"]**2
    df["EyeAvg2"]   = df["EyeAvg"]**2
    df["KavoidAvg2"] = df["KavoidAvg"]**2
    df["BabipAvg2"]  = df["BabipAvg"]**2
    df["GapAvg2"]    = df["GapAvg"]**2

    # Per-PA rates
    df["HR_pa"]   = df["HR"]   / df["PA"]
    df["BB_pa"]   = df["BB"]   / df["PA"]
    df["SO_pa"]   = df["SO"]   / df["PA"]
    df["2+3_pa"]  = df["2+3"]  / df["PA"]

    n = len(df)
    print(f"Sample: n={n}, mean PA={df['PA'].mean():.0f}, mean AB={df['AB'].mean():.0f}")
    print(f"  AB std = {df['AB'].std():.1f}  (constant 550 in every row -> fixed-volume sim)")
    print(f"  PA std = {df['PA'].std():.1f}  (varies with BB+HBP, so per-PA is a finer scale than per-AB)")

    # ================================================================
    # 1. Rating coverage diagnostics
    # ================================================================
    print("\n" + "=" * 72)
    print("1. RATING COVERAGE — does the sample span the full 20-80 range?")
    print("=" * 72)
    for col in ("PowerAvg", "EyeAvg", "KavoidAvg", "BabipAvg", "GapAvg", "Speed"):
        v = df[col].values
        q = np.quantile(v, [0, 0.1, 0.5, 0.9, 1.0])
        print(f"  {col:<12}  min={q[0]:.1f}  p10={q[1]:.1f}  med={q[2]:.1f}  "
              f"p90={q[3]:.1f}  max={q[4]:.1f}  unique vals = {len(np.unique(v))}")
    print()
    print("  Caveat: predictor coverage is densest in 30-50 (where 80% of MLB+AAA")
    print("  players sit) and thinnest in 65+ (Judge/Soto territory).")
    print("  Quadratic terms therefore extrapolate from very few data points.")

    # ================================================================
    # 2. Outlier influence — Cook's distance on the headline HR model
    # ================================================================
    print("\n" + "=" * 72)
    print("2. OUTLIER INFLUENCE (Cook's distance > 4/n = " f"{4/n:.3f} flags concern)")
    print("=" * 72)
    for ycol, cols in [
        ("HR",  ["PowerAvg", "PowerAvg2"]),
        ("BB",  ["EyeAvg"]),
        ("SO",  ["KavoidAvg", "KavoidAvg2"]),
        ("BABIP", ["BabipAvg"]),
        ("2+3", ["GapAvg", "BabipAvg"]),
    ]:
        d = df.dropna(subset=[ycol] + cols)
        X = np.column_stack([np.ones(len(d))] + [d[c].values for c in cols])
        cd = cooks(X, d[ycol].values)
        threshold = 4 / len(d)
        high = d.iloc[cd > threshold][["Name", ycol] + cols].copy()
        high["Cook"] = cd[cd > threshold]
        high = high.sort_values("Cook", ascending=False)
        print(f"\n  Outcome {ycol}: {len(high)} influential observations")
        if len(high):
            print(high.head(8).to_string(index=False))

    # ================================================================
    # 3. Per-PA rates vs per-550-AB counts — does the rate form fit better?
    # ================================================================
    print("\n" + "=" * 72)
    print("3. PER-PA RATES vs COUNTS — which form gives tighter LOO-RMSE?")
    print("=" * 72)

    rate_specs = [
        ("HR",   "HR_pa",  ["PowerAvg", "PowerAvg2"]),
        ("BB",   "BB_pa",  ["EyeAvg"]),
        ("SO",   "SO_pa",  ["KavoidAvg", "KavoidAvg2"]),
        ("2+3",  "2+3_pa", ["GapAvg", "BabipAvg"]),
    ]
    count_specs = [
        ("HR",   "HR",     ["PowerAvg", "PowerAvg2"]),
        ("BB",   "BB",     ["EyeAvg"]),
        ("SO",   "SO",     ["KavoidAvg", "KavoidAvg2"]),
        ("2+3",  "2+3",    ["GapAvg", "BabipAvg"]),
    ]
    print(f"  {'Outcome':<10} {'Count LOO-RMSE':>16}  {'Rate LOO-RMSE':>16}  "
          f"{'Rate / mean(PA)':>16}")
    mean_pa = df["PA"].mean()
    for (n1, yc, cols), (_, yr, _) in zip(count_specs, rate_specs):
        d_c = df.dropna(subset=[yc] + cols)
        d_r = df.dropna(subset=[yr] + cols)
        rc = loo_rmse(d_c, yc, cols)
        rr = loo_rmse(d_r, yr, cols)
        # Convert rate LOO back to count-scale for fair comparison
        rr_count = rr * mean_pa
        print(f"  {n1:<10} {rc:>16.3f}  {rr:>16.5f}  {rr_count:>16.3f}")
    print("\n  -> If rate LOO-RMSE × mean(PA) < count LOO-RMSE, the per-PA form is tighter.")

    # ================================================================
    # 4. All-pairs interaction scan
    # ================================================================
    print("\n" + "=" * 72)
    print("4. ALL-PAIRS INTERACTIONS — does (rating_i × rating_j) help?")
    print("=" * 72)
    main_ratings = ["PowerAvg", "EyeAvg", "KavoidAvg", "BabipAvg", "GapAvg", "Speed"]
    outcome_specs = [
        ("HR", ["PowerAvg", "PowerAvg2"], "HR ~ Power + Power²"),
        ("BB", ["EyeAvg"],                "BB ~ Eye"),
        ("SO", ["KavoidAvg", "KavoidAvg2"],"SO ~ Kavoid + Kavoid²"),
        ("BABIP", ["BabipAvg"],            "BABIP ~ Babip"),
        ("2+3", ["GapAvg", "BabipAvg"],   "2+3 ~ Gap + Babip"),
    ]
    for ycol, base_cols, label in outcome_specs:
        d = df.dropna(subset=[ycol] + base_cols)
        base = loo_rmse(d, ycol, base_cols)
        improvements = []
        for i in range(len(main_ratings)):
            for j in range(i, len(main_ratings)):
                r1, r2 = main_ratings[i], main_ratings[j]
                ix = f"{r1}__x__{r2}"
                d[ix] = d[r1] * d[r2]
                with_ix = loo_rmse(d, ycol, base_cols + [ix])
                d.drop(columns=[ix], inplace=True)
                if with_ix < base - 0.002:  # meaningful improvement
                    improvements.append((r1, r2, base - with_ix, with_ix))
        improvements.sort(key=lambda t: -t[2])
        print(f"\n  {label}  (baseline LOO-RMSE = {base:.3f})")
        if improvements:
            for r1, r2, gain, new in improvements[:5]:
                print(f"    + {r1} × {r2}:  Δ LOO-RMSE = {-gain:+.3f}  -> {new:.3f}")
        else:
            print("    (no interaction term improves LOO-RMSE by > 0.002)")

    # ================================================================
    # 5. Logit transform on rate outcomes
    # ================================================================
    print("\n" + "=" * 72)
    print("5. LOGIT TRANSFORM on bounded rate outcomes")
    print("=" * 72)
    def safe_logit(p):
        p = np.clip(p, 0.001, 0.999)
        return np.log(p / (1 - p))
    for outcome, rate_col, cols in [
        ("HR",  "HR_pa",  ["PowerAvg"]),
        ("BB",  "BB_pa",  ["EyeAvg"]),
        ("SO",  "SO_pa",  ["KavoidAvg"]),
    ]:
        d = df.dropna(subset=[rate_col] + cols).copy()
        d["logit"] = safe_logit(d[rate_col])
        r_plain = loo_rmse(d, rate_col, cols)
        # Logit-LOO RMSE — transform back to compare
        y_logit = d["logit"].values
        X = np.column_stack([np.ones(len(d))] + [d[c].values for c in cols])
        errs = []
        for i in range(len(d)):
            idx = np.arange(len(d)) != i
            beta, _, _, _ = lstsq(X[idx], y_logit[idx], rcond=None)
            yhat_logit = X[i] @ beta
            yhat_p = 1 / (1 + np.exp(-yhat_logit))
            errs.append((d[rate_col].iloc[i] - yhat_p)**2)
        r_logit = np.sqrt(np.mean(errs))
        print(f"  {outcome:<6}  linear-rate LOO-RMSE={r_plain:.5f}  "
              f"logit LOO-RMSE={r_logit:.5f}")

    # ================================================================
    # 6. Residual cross-correlations
    # ================================================================
    print("\n" + "=" * 72)
    print("6. RESIDUAL CROSS-CORRELATIONS — shared latent factor check")
    print("=" * 72)
    residuals = {}
    for ycol, cols in [
        ("HR",  ["PowerAvg", "PowerAvg2"]),
        ("BB",  ["EyeAvg"]),
        ("SO",  ["KavoidAvg", "KavoidAvg2"]),
        ("BABIP", ["BabipAvg"]),
        ("2+3", ["GapAvg", "BabipAvg"]),
    ]:
        d = df.dropna(subset=[ycol] + cols)
        X = np.column_stack([np.ones(len(d))] + [d[c].values for c in cols])
        r = ols(X, d[ycol].values, ["intercept"] + cols)
        residuals[ycol] = pd.Series(r["resid"], index=d.index)
    res_df = pd.DataFrame(residuals).dropna()
    print(res_df.corr().round(3).to_string())

    # ================================================================
    # 7. Drop-elite sensitivity
    # ================================================================
    print("\n" + "=" * 72)
    print("7. DROP-ELITE SENSITIVITY — exclude top-5 by outcome, refit")
    print("=" * 72)
    for ycol, cols in [
        ("HR",  ["PowerAvg", "PowerAvg2"]),
        ("BB",  ["EyeAvg"]),
        ("SO",  ["KavoidAvg", "KavoidAvg2"]),
        ("2+3", ["GapAvg", "BabipAvg"]),
    ]:
        d_full = df.dropna(subset=[ycol] + cols)
        d_drop = d_full.sort_values(ycol, ascending=False).iloc[5:]
        Xf = np.column_stack([np.ones(len(d_full))] + [d_full[c].values for c in cols])
        Xd = np.column_stack([np.ones(len(d_drop))] + [d_drop[c].values for c in cols])
        f = ols(Xf, d_full[ycol].values, ["intercept"] + cols)
        e = ols(Xd, d_drop[ycol].values, ["intercept"] + cols)
        print(f"\n  {ycol}:")
        print(f"    full (n={f['n']:>2}, R²={f['r2']:.3f}): "
              f"coefs = {dict(zip(cols, [f'{c:+.4f}' for c in f['coef'][1:]]))}")
        print(f"    drop5 (n={e['n']:>2}, R²={e['r2']:.3f}): "
              f"coefs = {dict(zip(cols, [f'{c:+.4f}' for c in e['coef'][1:]]))}")
        # Relative change
        rel = [abs(e["coef"][i] - f["coef"][i]) / abs(f["coef"][i] + 1e-9)
               for i in range(1, len(cols) + 1)]
        for c, r in zip(cols, rel):
            note = " <-- coef shifts > 25%" if r > 0.25 else ""
            print(f"      {c}: |Δcoef| / |coef| = {r:.1%}{note}")

    # ================================================================
    # 8. Bootstrap confidence intervals on headline coefficients
    # ================================================================
    print("\n" + "=" * 72)
    print("8. BOOTSTRAP CIs (B=1000) — robust ranges on headline coefficients")
    print("=" * 72)
    rng = np.random.default_rng(42)
    for ycol, cols in [
        ("HR",  ["PowerAvg", "PowerAvg2"]),
        ("BB",  ["EyeAvg"]),
        ("SO",  ["KavoidAvg", "KavoidAvg2"]),
        ("BABIP",["BabipAvg"]),
        ("2+3", ["GapAvg", "BabipAvg"]),
    ]:
        d = df.dropna(subset=[ycol] + cols)
        n_d = len(d)
        X = np.column_stack([np.ones(n_d)] + [d[c].values for c in cols])
        y = d[ycol].values
        beta_full, _, _, _ = lstsq(X, y, rcond=None)
        boot = np.zeros((1000, len(beta_full)))
        for b in range(1000):
            idx = rng.integers(0, n_d, size=n_d)
            Xb, yb = X[idx], y[idx]
            beta_b, _, _, _ = lstsq(Xb, yb, rcond=None)
            boot[b] = beta_b
        print(f"\n  {ycol}  (n={n_d})")
        for i, lab in enumerate(["intercept"] + cols):
            lo, hi = np.quantile(boot[:, i], [0.025, 0.975])
            pct_se = (hi - lo) / 2 / 1.96
            stable = "robust" if abs(beta_full[i]) > 2 * pct_se else "wide CI"
            print(f"    {lab:<12} {beta_full[i]:+.5f}  95% CI [{lo:+.5f}, {hi:+.5f}]  ({stable})")

    # ================================================================
    # 9. Derived outcomes — 1B and wOBA
    # ================================================================
    print("\n" + "=" * 72)
    print("9. DERIVED OUTCOMES — 1B and wOBA")
    print("=" * 72)

    # 1B is what's left after BB+HBP+SO+HR+(2+3) are subtracted from PA.
    # It's mostly driven by BABIP rating (more balls in play that fall).
    for ycol, cols in [
        ("1B", ["BabipAvg"]),
        ("1B", ["BabipAvg", "KavoidAvg"]),
        ("1B", ["BabipAvg", "KavoidAvg", "PowerAvg"]),
        ("wOBA", ["PowerAvg", "EyeAvg", "BabipAvg"]),
        ("wOBA", ["PowerAvg", "PowerAvg2", "EyeAvg", "BabipAvg", "KavoidAvg"]),
    ]:
        d = df.dropna(subset=[ycol] + cols)
        X = np.column_stack([np.ones(len(d))] + [d[c].values for c in cols])
        r = ols(X, d[ycol].values, ["intercept"] + cols)
        loo = loo_rmse(d, ycol, cols)
        print(f"  {ycol} ~ {' + '.join(cols):<48}  "
              f"R²={r['r2']:.4f}  LOO-RMSE={loo:.4f}")


if __name__ == "__main__":
    main()
