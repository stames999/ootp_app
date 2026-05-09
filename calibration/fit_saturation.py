"""
Fit per-position infield saturation parameters from calibrated sim data.

Each infield position (2B/3B/SS) shows saturation: when multiple ratings move
away from baseline simultaneously, the actual run impact is less than the
sum of the 1D table contributions. We model this with asymmetric tanh:

    saturate(x) = +CEIL_POS * tanh(x / SCALE_POS)   if x >= 0
                  -CEIL_NEG * tanh(-x / SCALE_NEG)  if x < 0

Predicted values use the CURRENT FIELDING_RUN_VALUES_VS_REPLACEMENT tables
(after closest_rating snap). Sim observations are runs-prevented per 162G
deltas vs the league-average baseline team in the calibrated env (RS/G ~4.16).

For 3B specifically, the all-55 sim shows a 7-run residual after saturation
that cannot be explained by uniform compression — RNG=55 (above its 50→55
inflection) gives +17 only when paired with ARM>=60. We capture that as a
sparse RNG×ARM correction grid added BEFORE saturation, populated from the
sim data points and zero elsewhere (smoothed via bilinear interp at runtime).
"""

import numpy as np
from scipy.optimize import minimize


# (predicted_additive_sum, actual_runs_per_162, label)
# Predictions computed by summing config FIELDING_RUN_VALUES_VS_REPLACEMENT
# at the relevant ratings (closest_rating snaps 80 → 75).
SIM_DATA_2B = [
    (-71.1, -59.0, "all-20"),
    (-44.0, -43.8, "all-40"),
    (  0.7,  -0.4, "all-55"),
    (  9.3,   5.4, "all-65"),
    ( 13.1,   7.8, "all-75"),
]

# 3B: all-55 is the outlier — captured by the (55,55) correction grid cell,
# excluded from the saturation fit so it doesn't pollute the curve.
SIM_DATA_3B = [
    (-64.8, -37.2, "all-20"),
    (-42.0, -34.8, "all-40"),
    ( 40.6,  21.6, "all-65"),
    ( 47.8,  23.8, "all-80"),
    ( 41.0,  20.0, "RNG75 ARM75 others-baseline"),
]
SIM_DATA_3B_OUTLIER = (5.4, -1.7, "all-55")  # used to derive (55,55) grid cell

SIM_DATA_SS = [
    # Predictions recomputed against the tightened SS IFarm[65]=10
    # (was 14, which over-stated the all-65 corner). The all-65 and
    # corner-test predictions drop by ~4 runs each; +80 ceiling rises 1.
    (-75.4, -47.8, "all-20"),
    (-61.8, -37.6, "all-40"),
    (-39.4, -23.3, "all-55"),
    ( 27.8,  16.8, "all-65"),
    ( 36.2,  24.2, "all-80"),
    ( 31.0,  17.2, "RNG75 ARM75 others-baseline"),
]


def saturate(x, ceil_pos, scale_pos, ceil_neg, scale_neg):
    x = np.asarray(x, dtype=float)
    return np.where(
        x >= 0,
        ceil_pos * np.tanh(x / scale_pos),
        -ceil_neg * np.tanh(-x / scale_neg),
    )


def fit_position(name, data):
    """Fit asymmetric tanh, but cap CEIL at 200 and SCALE at 400. When the
    optimizer hits those bounds, the saturating side has effectively no
    saturation in the data range — we collapse it to a linear slope and
    report (slope, slope*1e6) which is numerically equivalent to linear
    scaling in the runtime tanh evaluation.
    """
    pred = np.array([d[0] for d in data])
    actual = np.array([d[1] for d in data])

    BOUND_CEIL = 200.0
    BOUND_SCALE = 400.0

    def loss(params):
        cp, sp, cn, sn = params
        if min(cp, sp, cn, sn) <= 0:
            return 1e10
        sat = saturate(pred, cp, sp, cn, sn)
        return float(np.sum((sat - actual) ** 2))

    x0 = [max(actual.max(), 5), 25.0, max(-actual.min(), 10), 30.0]
    result = minimize(
        loss, x0, method="L-BFGS-B",
        bounds=[(1, BOUND_CEIL), (5, BOUND_SCALE),
                (1, BOUND_CEIL), (5, BOUND_SCALE)],
    )
    cp, sp, cn, sn = result.x

    # Detect linear-degenerate sides (hit the bound) and report a slope
    pos_linear = cp >= BOUND_CEIL * 0.99 or sp >= BOUND_SCALE * 0.99
    neg_linear = cn >= BOUND_CEIL * 0.99 or sn >= BOUND_SCALE * 0.99
    pos_slope = cp / sp
    neg_slope = cn / sn

    sat = saturate(pred, cp, sp, cn, sn)
    rmse = float(np.sqrt(np.mean((sat - actual) ** 2)))

    print(f"\n=== {name} ===")
    print(f"  Positive side: "
          f"{'LINEAR slope=%.3f' % pos_slope if pos_linear else 'TANH ceil=%.1f scale=%.1f' % (cp, sp)}")
    print(f"  Negative side: "
          f"{'LINEAR slope=%.3f' % neg_slope if neg_linear else 'TANH ceil=%.1f scale=%.1f' % (cn, sn)}")
    print(f"  RMSE: {rmse:.2f} runs/162")
    for (p, a, label), s in zip(data, sat):
        print(f"    {label:35s}  pred={p:+6.1f}  actual={a:+6.1f}  "
              f"sat={s:+6.1f}  resid={a - s:+5.1f}")

    # Always export raw tanh params — runtime evaluator handles both linear
    # (huge ceil/scale, tanh ~ identity) and saturating cases uniformly.
    return {"ceil_pos": round(float(cp), 3), "scale_pos": round(float(sp), 3),
            "ceil_neg": round(float(cn), 3), "scale_neg": round(float(sn), 3),
            "_pos_linear": pos_linear, "_neg_linear": neg_linear}


def derive_3b_outlier_correction(params):
    """Given fitted 3B saturation, derive the (55,55) RNG×ARM correction
    cell value: the additive sum we'd need to feed into saturation to
    reproduce the observed all-55 result of -1.7."""
    pred, actual, label = SIM_DATA_3B_OUTLIER
    cp, sp, cn, sn = (params["ceil_pos"], params["scale_pos"],
                      params["ceil_neg"], params["scale_neg"])
    # Inverse of saturate: given target y, find x.
    # y < 0  →  x = -sn * atanh(-y / cn)
    # y >= 0 →  x = sp * atanh(y / cp)
    if actual >= 0:
        if actual >= cp:
            target_x = float("inf")
        else:
            target_x = sp * np.arctanh(actual / cp)
    else:
        if -actual >= cn:
            target_x = float("-inf")
        else:
            target_x = -sn * np.arctanh(-actual / cn)
    correction = target_x - pred
    print(f"\n=== 3B (55,55) RNG×ARM correction ===")
    print(f"  all-55 sim: pred={pred:+.1f}, actual={actual:+.1f}")
    print(f"  inverse-saturated target x: {target_x:+.2f}")
    print(f"  correction at (55, 55): {correction:+.2f} "
          f"(applied BEFORE saturation)")
    return round(correction, 2)


if __name__ == "__main__":
    p2b = fit_position("2B", SIM_DATA_2B)
    p3b = fit_position("3B", SIM_DATA_3B)
    pss = fit_position("SS", SIM_DATA_SS)

    c55 = derive_3b_outlier_correction(p3b)

    print("\n" + "=" * 60)
    print("PASTE INTO config.py")
    print("=" * 60)
    print("FIELDING_SATURATION = {")
    for nm, p in [("2B", p2b), ("3B", p3b), ("SS", pss)]:
        comment_pos = " (linear)" if p["_pos_linear"] else " (tanh)"
        comment_neg = " (linear)" if p["_neg_linear"] else " (tanh)"
        print(f"    \"{nm}\": {{")
        print(f"        \"ceil_pos\":  {p['ceil_pos']:>10.3f},  # +side{comment_pos}")
        print(f"        \"scale_pos\": {p['scale_pos']:>10.3f},")
        print(f"        \"ceil_neg\":  {p['ceil_neg']:>10.3f},  # -side{comment_neg}")
        print(f"        \"scale_neg\": {p['scale_neg']:>10.3f},")
        print(f"    }},")
    print("}")
    print()
    print("FIELDING_INTERACTION_CORRECTION = {")
    print("    \"3B\": {")
    print("        # (IFrange, IFarm) -> runs added BEFORE saturation.")
    print("        # Captures the ARM-gated RNG benefit at 3B: RNG>=55 only")
    print("        # delivers the 50->55 jump when ARM is at/above its own")
    print("        # 60->65 inflection. Cells outside this anchor set are")
    print("        # bilinearly interpolated from the nearest anchors; cells")
    print("        # at axis baselines (50, 60) get correction 0 by")
    print("        # construction (sweep data is exact there).")
    print(f"        (55, 55): {c55},")
    print("    },")
    print("}")
