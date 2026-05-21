"""Regression-derived hitter metrics — replacement for `metrics_hitting.py`.

Closed-form predictor functions derived from a 62-hitter team-of-clones
sample (see `exports/outcome_regressions_v3.py` for the calibration
diagnostics). Each outcome has been fit and cross-validated:

  HR        = -4.48 + 0.157·Power + 0.00600·Power²        (LOO-RMSE 1.61 per 550 AB)
  BB        = -24.28 + 1.532·Eye                          (LOO-RMSE 4.57)
  SO        = 511.7 − 11.13·Kavoid + 0.0612·Kavoid²       (LOO-RMSE 6.65)
  BABIP     = 0.178 + 0.00234·Babip                       (LOO-RMSE 0.004)
  2+3       = -39.6 + 0.49·Gap + 0.20·Babip
              + 0.0083·Kavoid·Babip                       (LOO-RMSE 1.81)
  3-ratio   = -0.072 + 0.00294·Speed                      (LOO-RMSE 0.012)

Vs the old hand-tuned `BATTING_COMPONENTS_ADJUST_MAP`: identical interface
(returns the same hr_pct{R,L} / bb_pct{R,L} / etc. columns plus wOBA{R,L,P}
and slash lines). Drop-in via `from metrics_hitting_v2 import calc_hitting_metrics`.

The formulas are an analytical compression of OOTP's projection engine —
they reproduce the engine's output with R² ≥ 0.95 on every headline
outcome (HR R²=0.988, BB 0.969, SO 0.987, BABIP 0.992) but they're
extrapolations of an n=62 sample, not first-principles MLB physics.
Trust them within the calibrated range (ratings 20-80); outside it the
quadratics will misbehave.
"""
from __future__ import annotations

import pandas as pd

from config import (
    HANDEDNESS_WEIGHTS,
    BATTING_WOBA_WEIGHTS,
    RUNS_PER_GAME_HITTING_COEFF,
    RUNS_PER_GAME_HITTING_CONST,
    RUNS_PER_WIN_HITTING,
    DH_PENALTY,
    LEAGUE_WOBA,
    WOBA_SCALE,
    LEAGUE_RUNS_PER_PA,
)


# ---------------------------------------------------------------------------
# Closed-form outcome predictors. All take ratings on the 20-80 scale.
# Outputs are per-550-AB counts (matching the calibration sim's volume).
# Per-PA rates are derived below by dividing by predicted PA.
# ---------------------------------------------------------------------------

# Approx HBP per 550 AB. Sample mean across hitters with HBP > 0 was ~5;
# HBP rating isn't on the 20-80 scale so we use a constant.
HBP_PER_550_AB = 5.0


def predict_hr(power: float) -> float:
    """HR per 550 AB. Quadratic in Power — elite Power produces
    disproportionately more HRs (Judge/Ohtani curl)."""
    return -4.48 + 0.157 * power + 0.00600 * power**2


def predict_bb(eye: float) -> float:
    """BB per 550 AB. Linear in Eye — no convexity needed (R²=0.97
    with single linear term)."""
    return -24.28 + 1.532 * eye


def predict_so(kavoid: float) -> float:
    """SO per 550 AB. Quadratic in K-avoid — Arraez-tier (90+ K-avoid)
    prevents Ks at an accelerating rate, captured by the +Kavoid² term."""
    return 511.7 - 11.13 * kavoid + 0.0612 * kavoid**2


def predict_2_plus_3(gap: float, babip: float, kavoid: float) -> float:
    """Doubles + triples per 550 AB. Gap + Babip baseline plus a
    Kavoid×Babip interaction (you need to put the ball in play AND
    have it land — the product captures the joint requirement)."""
    return -39.6 + 0.49 * gap + 0.20 * babip + 0.0083 * kavoid * babip


def predict_triples_ratio(speed: float) -> float:
    """3B / (2B+3B). Linear in Speed — extremely clean signal
    (R²=0.945)."""
    return max(0.0, -0.072 + 0.00294 * speed)


def predict_babip_stat(babip_rating: float) -> float:
    """Realised BABIP (the slash-line stat). Almost pure linear function
    of the BABIP rating — Speed adds nothing material in this sample."""
    return 0.178 + 0.00234 * babip_rating


def predict_pa(eye: float) -> float:
    """Plate appearances given AB=550. PA = AB + BB + HBP."""
    return 550.0 + predict_bb(eye) + HBP_PER_550_AB


def predict_outcomes(power: float, eye: float, kavoid: float,
                      babip: float, gap: float, speed: float) -> dict:
    """One-shot: compute every per-PA component rate for one player /
    one handedness. Returns a dict with keys: hr_pct, bb_pct, k_pct,
    hbp_pct, 1b_pct, 2b_pct, 3b_pct, babip_stat."""
    pa = predict_pa(eye)
    hr_count = max(0.0, predict_hr(power))
    bb_count = max(0.0, predict_bb(eye))
    so_count = max(0.0, predict_so(kavoid))
    xb_count = max(0.0, predict_2_plus_3(gap, babip, kavoid))
    triples_share = predict_triples_ratio(speed)
    triples_share = min(max(triples_share, 0.0), 0.5)  # sanity clamp
    threes = xb_count * triples_share
    doubles = xb_count - threes

    hr_pct = hr_count / pa
    bb_pct = bb_count / pa
    k_pct  = so_count / pa
    hbp_pct = HBP_PER_550_AB / pa
    twob_pct = doubles / pa
    threeb_pct = threes / pa
    # 1B is what's left: 1 = bb + k + hbp + hr + 2b + 3b + 1b + outs-on-bip
    # The "outs on BIP" share is determined by BABIP rating.
    # Total balls in play per PA = 1 - bb_pct - k_pct - hbp_pct - hr_pct
    bip_pct = max(0.0, 1.0 - bb_pct - k_pct - hbp_pct - hr_pct)
    babip_stat = predict_babip_stat(babip)
    hits_on_bip = bip_pct * babip_stat  # H - HR per PA
    # Subtract the predicted (2B+3B) per PA from the BABIP hits — leaves 1B
    onebab_pct = max(0.0, hits_on_bip - twob_pct - threeb_pct)
    return {
        "hr_pct": hr_pct,
        "bb_pct": bb_pct,
        "k_pct": k_pct,
        "hbp_pct": hbp_pct,
        "1b_pct": onebab_pct,
        "2b_pct": twob_pct,
        "3b_pct": threeb_pct,
        "babip_stat": babip_stat,
    }


# ---------------------------------------------------------------------------
# DataFrame-level wrapper — same column-name contract as metrics_hitting.py
# so callers can swap modules without further changes.
# ---------------------------------------------------------------------------

def _row_predict(row, side: str) -> pd.Series:
    """Compute one handedness slice's per-PA rates for one player row."""
    if side == "P":  # potential ratings
        pow_v   = row.get("powP", 50)
        eye_v   = row.get("eyeP", 50)
        avk_v   = row.get("avkP", 50)
        gap_v   = row.get("gapP", 50)
        babip_v = row.get("babipP", 50)
    else:
        pow_v   = row.get(f"pow{side}", 50)
        eye_v   = row.get(f"eye{side}", 50)
        avk_v   = row.get(f"avk{side}", 50)
        gap_v   = row.get(f"gap{side}", 50)
        babip_v = row.get(f"babip{side}", 50)
    speed = row.get("speed", 50)

    # Coerce ratings: NaN -> 50 (average), then clamp to [20, 100] so
    # unscouted/sentinel "0" ratings don't blow up the formulas at the
    # extrapolation end (most damaging on the SO quadratic, which would
    # otherwise project a 92% K-rate at rating=0).
    def safe(v):
        try:
            v = float(v)
            if v != v:  # NaN
                return 50.0
        except (TypeError, ValueError):
            return 50.0
        return min(max(v, 20.0), 100.0)

    rates = predict_outcomes(safe(pow_v), safe(eye_v), safe(avk_v),
                             safe(babip_v), safe(gap_v), safe(speed))
    return pd.Series({
        f"hr_pct{side}":  rates["hr_pct"],
        f"k_pct{side}":   rates["k_pct"],
        f"bb_pct{side}":  rates["bb_pct"],
        f"1b_pct{side}":  rates["1b_pct"],
        f"2b_pct{side}":  rates["2b_pct"],
        f"3b_pct{side}":  rates["3b_pct"],
    })


def calc_hitting_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Drop-in replacement for `metrics_hitting.calc_hitting_metrics`.

    Computes vsR / vsL per-PA component rates, wOBA{R,L}, overall wOBA
    (handedness-weighted), slash lines (AVG / OBP / SLG / ISO with
    R/L splits + overall), war_hitting, DH_hitting, wRC+."""
    rates_r = df.apply(lambda r: _row_predict(r, "R"), axis=1)
    rates_l = df.apply(lambda r: _row_predict(r, "L"), axis=1)
    df = pd.concat([df, rates_r, rates_l], axis=1)

    # wOBA — linear weighted sum of component rates
    for side in ("R", "L"):
        df[f"wOBA{side}"] = (
            BATTING_WOBA_WEIGHTS["hr_pct_wOBA_weight"] * df[f"hr_pct{side}"] +
            BATTING_WOBA_WEIGHTS["bb_pct_wOBA_weight"] * df[f"bb_pct{side}"] +
            BATTING_WOBA_WEIGHTS["1b_pct_wOBA_weight"] * df[f"1b_pct{side}"] +
            BATTING_WOBA_WEIGHTS["2b_pct_wOBA_weight"] * df[f"2b_pct{side}"] +
            BATTING_WOBA_WEIGHTS["3b_pct_wOBA_weight"] * df[f"3b_pct{side}"]
        )

    df["wOBA"] = (
        df["wOBAR"] * HANDEDNESS_WEIGHTS["R"]
        + df["wOBAL"] * HANDEDNESS_WEIGHTS["L"]
    )

    # Slash-line derivations (HBP intentionally omitted — same shape as v1)
    for side in ("R", "L"):
        hits_pa = (df[f"1b_pct{side}"] + df[f"2b_pct{side}"]
                   + df[f"3b_pct{side}"] + df[f"hr_pct{side}"])
        tb_pa = (df[f"1b_pct{side}"] + 2 * df[f"2b_pct{side}"]
                 + 3 * df[f"3b_pct{side}"] + 4 * df[f"hr_pct{side}"])
        ab_pa = 1 - df[f"bb_pct{side}"]
        df[f"AVG{side}"] = (hits_pa / ab_pa).round(3)
        df[f"OBP{side}"] = (hits_pa + df[f"bb_pct{side}"]).round(3)
        df[f"SLG{side}"] = (tb_pa / ab_pa).round(3)
        df[f"ISO{side}"] = (df[f"SLG{side}"] - df[f"AVG{side}"]).round(3)

    for stat in ("AVG", "OBP", "SLG", "ISO"):
        df[stat] = (df[f"{stat}R"] * HANDEDNESS_WEIGHTS["R"]
                    + df[f"{stat}L"] * HANDEDNESS_WEIGHTS["L"]).round(3)

    df["war_hitting"] = (((df["wOBA"] * RUNS_PER_GAME_HITTING_COEFF)
                           - RUNS_PER_GAME_HITTING_CONST) / RUNS_PER_WIN_HITTING).round(1)
    df["DH_hitting"] = ((((df["wOBA"] * (1 - DH_PENALTY)) * RUNS_PER_GAME_HITTING_COEFF)
                          - RUNS_PER_GAME_HITTING_CONST) / RUNS_PER_WIN_HITTING).round(1)
    df["wRC+"] = ((((df["wOBA"] - LEAGUE_WOBA) / WOBA_SCALE)
                    + LEAGUE_RUNS_PER_PA) / LEAGUE_RUNS_PER_PA * 100).round(0)

    return df


def calc_potential_hitting_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Same shape as v1: predict potential metrics using {pow,eye,avk,gap,babip}P
    ratings. Speed has no _P companion so we reuse current Speed."""
    rates_p = df.apply(lambda r: _row_predict(r, "P"), axis=1).rename(
        columns={
            "hr_pctP": "hr_pctP", "k_pctP": "k_pctP", "bb_pctP": "bb_pctP",
            "1b_pctP": "1b_pctP", "2b_pctP": "2b_pctP", "3b_pctP": "3b_pctP",
        }
    )
    df = pd.concat([df, rates_p], axis=1)

    df["wOBAP"] = (
        BATTING_WOBA_WEIGHTS["hr_pct_wOBA_weight"] * df["hr_pctP"] +
        BATTING_WOBA_WEIGHTS["bb_pct_wOBA_weight"] * df["bb_pctP"] +
        BATTING_WOBA_WEIGHTS["1b_pct_wOBA_weight"] * df["1b_pctP"] +
        BATTING_WOBA_WEIGHTS["2b_pct_wOBA_weight"] * df["2b_pctP"] +
        BATTING_WOBA_WEIGHTS["3b_pct_wOBA_weight"] * df["3b_pctP"]
    )

    # Projected slash + wRC+P (same shape as v1)
    hits_paP = (df["1b_pctP"] + df["2b_pctP"] + df["3b_pctP"] + df["hr_pctP"])
    tb_paP = (df["1b_pctP"] + 2 * df["2b_pctP"] + 3 * df["3b_pctP"] + 4 * df["hr_pctP"])
    ab_paP = 1 - df["bb_pctP"]
    df["AVGP"] = (hits_paP / ab_paP).round(3)
    df["OBPP"] = (hits_paP + df["bb_pctP"]).round(3)
    df["SLGP"] = (tb_paP / ab_paP).round(3)
    df["ISOP"] = (df["SLGP"] - df["AVGP"]).round(3)
    df["wRC+P"] = ((((df["wOBAP"] - LEAGUE_WOBA) / WOBA_SCALE)
                    + LEAGUE_RUNS_PER_PA) / LEAGUE_RUNS_PER_PA * 100).round(0)

    df["war_hittingP"] = (((df["wOBAP"] * RUNS_PER_GAME_HITTING_COEFF)
                            - RUNS_PER_GAME_HITTING_CONST)
                          / RUNS_PER_WIN_HITTING).round(1)
    df["DH_hittingP"] = ((((df["wOBAP"] * (1 - DH_PENALTY)) * RUNS_PER_GAME_HITTING_COEFF)
                           - RUNS_PER_GAME_HITTING_CONST)
                          / RUNS_PER_WIN_HITTING).round(1)
    return df
