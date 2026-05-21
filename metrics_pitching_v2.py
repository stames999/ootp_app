"""Regression-derived pitcher metrics — drop-in alternative to
`metrics_pitching.py`. Same output columns; per-PA rate predictions
come from closed-form formulas fit on a 95-pitcher OOTP in-game
projection sample (see exports/pitcher_outcome_regressions_v2.py).

Formula fits (R² in-sample, n=81):

  K%             = -0.1383 + 0.00934·Stuff − 0.0000479·Stuff²
                          + 0.00425·NumPitches                 (R²=0.974)
  BB%            =  0.4026 − 0.01015·Control + 0.0000746·Control²  (R²=0.942)
  HR%            =  0.1662 − 0.00433·HRA + 0.0000326·HRA²
                          − 0.0000901·BestFB                  (R²=0.824)
  BABIP-against  =  0.3250 − 0.000609·pBABIP                  (R²=0.891)

Pipeline:
  1. Compute K%, BB%, HR%, BABIP-against per side (vsR / vsL) using
     each side's ratings (StuffvR for vsR K%, StuffvL for vsL K%, etc.).
  2. Derive BIP rate = 1 − K% − BB% − HBP% − HR%.
  3. h_nothr_vs = BIP × BABIP-against (non-HR hits).
  4. wOBA-weighted sum → pwOBA per side and overall.
  5. Same role-tagging / WAR pipeline as v1.

Note: like hitter v2, this uses per-side ratings naively (same formula
coefficients applied with vsR/vsL inputs). The empirical vsR/vsL mix
in the data is noisier than hitters (66-79% there vs 21-79% here), so
the per-side splits should be read as approximate. For the aggregate
pwOBA the prediction is solid.
"""
from __future__ import annotations

import pandas as pd

from config import (
    PITCHING_WOBA_WEIGHTS,
    PITCHING_WAR_COEFFS,
    HANDEDNESS_WEIGHTS,
    MINIMUM_STARTER_STAMINA,
    MIN_PITCHES_FOR_SP,
    PITCHER_RATING_FLOOR,
    RELIEVER_VS_STARTER_AVERAGE_IP,
    SP_WAR_MIN_STAMINA,
    PITCHER_SPLIT_SPECIALIST_THRESHOLD,
    PITCHER_SPLIT_NEUTRAL_THRESHOLD,
)


# Pitch columns expected on the DataFrame (after the reader's renames,
# they come in as e.g. "fastball", "slider", etc. — but the existing
# pipeline uses the raw scouted-rating column names. Let me check both
# conventions: reader.py renames `pitching_ratings_pitches_fastball`
# to a shorter key, but I'll match whichever is present).
PITCH_COL_CANDIDATES = {
    "Fastball":     ("fastball", "pitching_ratings_pitches_fastball"),
    "Slider":       ("slider",   "pitching_ratings_pitches_slider"),
    "Curveball":    ("curveball","pitching_ratings_pitches_curveball"),
    "Changeup":     ("changeup", "pitching_ratings_pitches_changeup"),
    "Sinker":       ("sinker",   "pitching_ratings_pitches_sinker"),
    "Splitter":     ("splitter", "pitching_ratings_pitches_splitter"),
    "Cutter":       ("cutter",   "pitching_ratings_pitches_cutter"),
    "CircleCh":     ("circlechange", "pitching_ratings_pitches_circlechange"),
    "Knucklecurve": ("knucklecurve", "pitching_ratings_pitches_knucklecurve"),
    "Knuckleball":  ("knuckleball",  "pitching_ratings_pitches_knuckleball"),
    "Forkball":     ("forkball", "pitching_ratings_pitches_forkball"),
    "Screwball":    ("screwball","pitching_ratings_pitches_screwball"),
}


def _resolve_pitch_cols(df: pd.DataFrame) -> dict[str, str]:
    out = {}
    for label, candidates in PITCH_COL_CANDIDATES.items():
        for c in candidates:
            if c in df.columns:
                out[label] = c
                break
    return out


# Closed-form formulas. Inputs are 20-80 ratings; outputs are per-PA rates.
def _predict_k(stuff: float, num_pitches: float) -> float:
    return -0.138268 + 0.0093415*stuff + (-0.0000479)*(stuff**2) + 0.0042522*num_pitches


def _predict_bb(control: float) -> float:
    return 0.402573 - 0.0101487*control + 0.0000746*(control**2)


def _predict_hr(hra: float, best_fb: float) -> float:
    return 0.166205 - 0.0043337*hra + 0.0000326*(hra**2) - 0.0000901*best_fb


def _predict_babip_against(pbabip: float) -> float:
    return 0.324995 - 0.0006087*pbabip


HBP_PER_PA = 0.009  # league-average HBP rate per plate appearance


PITCHER_SKILL_COLS_CURRENT = [
    "ctrlR", "ctrlL", "pbabipR", "pbabipL",
    "hraR", "hraL", "stuffR", "stuffL",
]
PITCHER_SKILL_COLS_POTENTIAL = ["ctrlP", "pbabipP", "hraP", "stuffP"]


def calc_pitching_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """v2 pitcher metrics. Same output column contract as
    metrics_pitching.calc_pitching_metrics."""

    # Resolve pitch column names (reader renames may vary).
    pitch_cols = _resolve_pitch_cols(df)
    fb_types = [pitch_cols[k] for k in ("Fastball","Sinker","Cutter") if k in pitch_cols]
    all_pitch_cols = list(pitch_cols.values())

    def safe(v, default=50.0):
        try:
            v = float(v)
            if v != v:
                return default
        except (TypeError, ValueError):
            return default
        return min(max(v, 20.0), 100.0)

    # Pitch-mix features for each row
    def row_arsenal(row):
        if not all_pitch_cols:
            return 3.0, 50.0
        vals = [row.get(c, 0) or 0 for c in all_pitch_cols]
        num_pitches = sum(1 for v in vals if v and v > 0)
        if fb_types:
            best_fb = max((row.get(c, 0) or 0) for c in fb_types)
        else:
            best_fb = 50
        return float(num_pitches), float(best_fb)

    # Role tagging — same as v1
    def identify_role(row):
        if pd.isna(row.get("stamina")):
            return ""
        if (row["stamina"] >= MINIMUM_STARTER_STAMINA and
                (row.get("pitches") or 0) >= MIN_PITCHES_FOR_SP):
            return "sp"
        return "rp"

    df["sprp"] = df.apply(identify_role, axis=1)

    # Compute per-side rates using the closed-form formulas.
    def compute_side_rates(row, side: str) -> pd.Series:
        stuff   = safe(row.get(f"stuff{side}"))
        control = safe(row.get(f"ctrl{side}"))
        hra     = safe(row.get(f"hra{side}"))
        pbabip  = safe(row.get(f"pbabip{side}"))
        num_pitches, best_fb = row_arsenal(row)

        k_pct  = max(0.0, _predict_k(stuff, num_pitches))
        bb_pct = max(0.0, _predict_bb(control))
        hr_pct = max(0.0, _predict_hr(hra, best_fb))
        babip_against = max(0.0, _predict_babip_against(pbabip))

        bip_pct = max(0.0, 1.0 - k_pct - bb_pct - HBP_PER_PA - hr_pct)
        h_nothr_pct = bip_pct * babip_against

        return pd.Series({
            f"hr_vs{side}":      hr_pct,
            f"bb_vs{side}":      bb_pct,
            f"k_vs{side}":       k_pct,
            f"h_nothr_vs{side}": h_nothr_pct,
        })

    rates_r = df.apply(lambda r: compute_side_rates(r, "R"), axis=1)
    rates_l = df.apply(lambda r: compute_side_rates(r, "L"), axis=1)
    df = pd.concat([df, rates_r, rates_l], axis=1)

    # pwOBAR / pwOBAL — same wOBA-weighted sum as v1
    df["pwOBAR"] = (
        PITCHING_WOBA_WEIGHTS["hr_vs_wOBA_weight"]    * df["hr_vsR"] +
        PITCHING_WOBA_WEIGHTS["bb_vs_wOBA_weight"]    * df["bb_vsR"] +
        PITCHING_WOBA_WEIGHTS["h_nothr_vs_wOBA_weight"] * df["h_nothr_vsR"]
    )
    df["pwOBAL"] = (
        PITCHING_WOBA_WEIGHTS["hr_vs_wOBA_weight"]    * df["hr_vsL"] +
        PITCHING_WOBA_WEIGHTS["bb_vs_wOBA_weight"]    * df["bb_vsL"] +
        PITCHING_WOBA_WEIGHTS["h_nothr_vs_wOBA_weight"] * df["h_nothr_vsL"]
    )
    df["pwOBA"] = (
        df["pwOBAR"] * HANDEDNESS_WEIGHTS["R"]
        + df["pwOBAL"] * HANDEDNESS_WEIGHTS["L"]
    )

    # Platoon split tagging (identical to v1)
    df["pwOBA_split"] = df["pwOBAR"] - df["pwOBAL"]

    def _classify_split(row):
        split = row.get("pwOBA_split")
        if pd.isna(split):
            return pd.NA
        abs_split = abs(split)
        if abs_split >= PITCHER_SPLIT_SPECIALIST_THRESHOLD:
            return "vsR_specialist" if split < 0 else "vsL_specialist"
        if abs_split > PITCHER_SPLIT_NEUTRAL_THRESHOLD:
            return "slight_vsR_split" if split < 0 else "slight_vsL_split"
        return "neutral"

    df["pitcher_split_tag"] = df.apply(_classify_split, axis=1)

    # WAR — same component-aware formula as v1
    hr_pct = (df["hr_vsR"] * HANDEDNESS_WEIGHTS["R"] + df["hr_vsL"] * HANDEDNESS_WEIGHTS["L"]) * 100
    bb_pct = (df["bb_vsR"] * HANDEDNESS_WEIGHTS["R"] + df["bb_vsL"] * HANDEDNESS_WEIGHTS["L"]) * 100
    k_pct  = (df["k_vsR"]  * HANDEDNESS_WEIGHTS["R"] + df["k_vsL"]  * HANDEDNESS_WEIGHTS["L"]) * 100
    c_pct  = (df["h_nothr_vsR"] * HANDEDNESS_WEIGHTS["R"] + df["h_nothr_vsL"] * HANDEDNESS_WEIGHTS["L"]) * 100

    base_war = (
        PITCHING_WAR_COEFFS["intercept"]
        + PITCHING_WAR_COEFFS["hr_pct_coef"] * hr_pct
        + PITCHING_WAR_COEFFS["bb_pct_coef"] * bb_pct
        + PITCHING_WAR_COEFFS["k_pct_coef"] * k_pct
        + PITCHING_WAR_COEFFS["h_nothr_pct_coef"] * c_pct
    ).round(1)

    df["sp_war"] = base_war
    df["rp_war"] = (base_war * RELIEVER_VS_STARTER_AVERAGE_IP).round(1)

    # Sub-floor gate (same as v1)
    existing_skill_cols = [c for c in PITCHER_SKILL_COLS_CURRENT if c in df.columns]
    if existing_skill_cols:
        sub_floor = (df[existing_skill_cols].fillna(0) < PITCHER_RATING_FLOOR).any(axis=1)
        df.loc[sub_floor, ["sp_war", "rp_war"]] = pd.NA

    if "stamina" in df.columns:
        too_short = df["stamina"].fillna(0) < SP_WAR_MIN_STAMINA
        df.loc[too_short, "sp_war"] = pd.NA

    if "pitches" in df.columns:
        too_few = df["pitches"].fillna(0) < MIN_PITCHES_FOR_SP
        df.loc[too_few, "sp_war"] = pd.NA

    df["is_sp"] = (df["sprp"] == "sp").astype(int)
    return df


def calc_potential_pitching_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """v2 potential pitching metrics. Uses potential (P) ratings; same
    output column contract as v1."""
    pitch_cols = _resolve_pitch_cols(df)
    fb_types = [pitch_cols[k] for k in ("Fastball","Sinker","Cutter") if k in pitch_cols]
    all_pitch_cols = list(pitch_cols.values())

    def safe(v, default=50.0):
        try:
            v = float(v)
            if v != v:
                return default
        except (TypeError, ValueError):
            return default
        return min(max(v, 20.0), 100.0)

    def compute_potential_rates(row) -> pd.Series:
        stuff   = safe(row.get("stuffP"))
        control = safe(row.get("ctrlP"))
        hra     = safe(row.get("hraP"))
        pbabip  = safe(row.get("pbabipP"))

        if all_pitch_cols:
            vals = [row.get(c, 0) or 0 for c in all_pitch_cols]
            num_pitches = float(sum(1 for v in vals if v and v > 0))
            best_fb = float(max((row.get(c, 0) or 0) for c in fb_types)) if fb_types else 50.0
        else:
            num_pitches, best_fb = 3.0, 50.0

        k_pct  = max(0.0, _predict_k(stuff, num_pitches))
        bb_pct = max(0.0, _predict_bb(control))
        hr_pct = max(0.0, _predict_hr(hra, best_fb))
        babip_against = max(0.0, _predict_babip_against(pbabip))

        bip_pct = max(0.0, 1.0 - k_pct - bb_pct - HBP_PER_PA - hr_pct)
        h_nothr_pct = bip_pct * babip_against
        return pd.Series({
            "hr_vsP": hr_pct, "bb_vsP": bb_pct, "k_vsP": k_pct,
            "h_nothr_vsP": h_nothr_pct,
        })

    rates_p = df.apply(compute_potential_rates, axis=1)
    df = pd.concat([df, rates_p], axis=1)

    df["pwOBAP"] = (
        PITCHING_WOBA_WEIGHTS["hr_vs_wOBA_weight"]    * df["hr_vsP"] +
        PITCHING_WOBA_WEIGHTS["bb_vs_wOBA_weight"]    * df["bb_vsP"] +
        PITCHING_WOBA_WEIGHTS["h_nothr_vs_wOBA_weight"] * df["h_nothr_vsP"]
    )

    # Potential WAR with same coefficients
    hr_pct = df["hr_vsP"] * 100
    bb_pct = df["bb_vsP"] * 100
    k_pct  = df["k_vsP"]  * 100
    c_pct  = df["h_nothr_vsP"] * 100
    base_warP = (
        PITCHING_WAR_COEFFS["intercept"]
        + PITCHING_WAR_COEFFS["hr_pct_coef"] * hr_pct
        + PITCHING_WAR_COEFFS["bb_pct_coef"] * bb_pct
        + PITCHING_WAR_COEFFS["k_pct_coef"] * k_pct
        + PITCHING_WAR_COEFFS["h_nothr_pct_coef"] * c_pct
    ).round(1)

    df["sp_warP"] = base_warP
    df["rp_warP"] = (base_warP * RELIEVER_VS_STARTER_AVERAGE_IP).round(1)

    # Same gates as v1
    existing = [c for c in PITCHER_SKILL_COLS_POTENTIAL if c in df.columns]
    if existing:
        sub_floor = (df[existing].fillna(0) < PITCHER_RATING_FLOOR).any(axis=1)
        df.loc[sub_floor, ["sp_warP", "rp_warP"]] = pd.NA

    if "stamina" in df.columns:
        too_short = df["stamina"].fillna(0) < SP_WAR_MIN_STAMINA
        df.loc[too_short, "sp_warP"] = pd.NA

    if "pitches" in df.columns:
        too_few = df["pitches"].fillna(0) < MIN_PITCHES_FOR_SP
        df.loc[too_few, "sp_warP"] = pd.NA

    return df
