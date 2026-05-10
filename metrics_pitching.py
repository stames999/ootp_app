import pandas as pd
from config import (
    BASE_PITCHING_RATES,
    PITCHING_COMPONENTS_ADJUST_MAP,
    PITCHING_WOBA_WEIGHTS,
    PITCHING_WAR_COEFFS,
    HANDEDNESS_WEIGHTS,
    MINIMUM_STARTER_STAMINA,
    PITCHER_RATING_FLOOR,
    RELIEVER_VS_STARTER_AVERAGE_IP,
    SP_WAR_MIN_STAMINA,
)


# Skill rating columns checked against PITCHER_RATING_FLOOR. Stamina is its
# own dimension (governs SP/RP role identification, not skill quality).
PITCHER_SKILL_COLS_CURRENT = [
    "ctrlR", "ctrlL", "pbabipR", "pbabipL",
    "hraR", "hraL", "stuffR", "stuffL",
]
PITCHER_SKILL_COLS_POTENTIAL = ["ctrlP", "pbabipP", "hraP", "stuffP"]

def calc_pitching_metrics(df: pd.DataFrame) -> pd.DataFrame:

    # Establish role using stamina alone — pwOBA / WAR are now computed
    # for every player so two-way prospects (OOTP `position != 1` with
    # real scouted pitching ratings, e.g. Shohei Ohtani at LAD with
    # position=10 but role=11) get a valid role tag too. Below
    # MINIMUM_STARTER_STAMINA they're a reliever; at or above they're a
    # potential starter regardless of pitch-mix breadth. Position
    # players without scouted pitching ratings will still be filtered
    # out at downstream pool admission (see exporter.py + the sub-floor
    # gate below that NaN's their sp_war / rp_war).
    def identify_role(row):
        if pd.isna(row.get("stamina")):
            return ""
        if row["stamina"] >= MINIMUM_STARTER_STAMINA:
            return "sp"
        return "rp"

    df["sprp"] = df.apply(identify_role, axis=1)

    # Helper function to adjust rates. Multiplicative model: each rating's
    # adjustment is a ratio applied to the running rate (vs old additive form).
    # Confirmed by HRA × CTRL = 20/20 interaction sim.
    def adjust_rates(row, side):
        rates = {
            "hr_vs": BASE_PITCHING_RATES["hr_vs_baserate"],
            "bb_vs": BASE_PITCHING_RATES["bb_vs_baserate"],
            "k_vs": BASE_PITCHING_RATES["k_vs_baserate"],
            "h_nothr_vs": BASE_PITCHING_RATES["h_nothr_vs_baserate"]
        }
        ratings = {
            "Control": row[f"ctrl{side}"],
            "pBABIP": row[f"pbabip{side}"],
            "HRA": row[f"hra{side}"],
            "Stuff": row[f"stuff{side}"],
            "Stamina": row["stamina"]
        }

        for category, value in ratings.items():
            table = PITCHING_COMPONENTS_ADJUST_MAP[category]
            keys = list(map(int, table.keys()))
            min_key = min(keys)
            max_key = max(keys)

            if category == "Stamina":
                # Stamina table is keyed by exact rating, not a continuous range;
                # skip if no entry for this player's stamina value.
                str_value = str(value)
                if str_value not in table:
                    continue
                adj = table[str_value]
            else:
                # Clamp to [min_key, max_key]. Below-floor ratings (especially
                # rare for CTRL/HRA after the 20-table extension) get the
                # min_key multiplier rather than extrapolating into nonsense.
                if pd.isna(value):
                    clamped = min_key
                else:
                    clamped = max(min_key, min(int(value), max_key))
                adj = table[str(clamped)]

            rates["hr_vs"] *= adj["hr_vs_mult"]
            rates["bb_vs"] *= adj["bb_vs_mult"]
            rates["k_vs"] *= adj["k_vs_mult"]
            rates["h_nothr_vs"] *= adj["h_nothr_vs_mult"]

        return pd.Series({
            f"hr_vs{side}": rates["hr_vs"],
            f"bb_vs{side}": rates["bb_vs"],
            f"k_vs{side}": rates["k_vs"],
            f"h_nothr_vs{side}": rates["h_nothr_vs"]
        })

    # Apply rating adjustments to base rates for RHH and LHH
    rates_r = df.apply(lambda row: adjust_rates(row, "R"), axis=1)
    rates_l = df.apply(lambda row: adjust_rates(row, "L"), axis=1)
    df = pd.concat([df, rates_r, rates_l], axis=1)

    # Compute pwOBA for EVERY player (not just `position == 1`). Real
    # two-way players have OOTP `position != 1` but genuine scouted
    # pitching ratings (e.g. Shohei Ohtani: position=10 DH, role=11
    # Starter, stuff=70). They need a computed pwOBA so the symmetric
    # `_flag_two_way_players` heuristic can flag them. Position
    # players with no scouted pitching ratings will produce a
    # very-bad pwOBA from default low ratings — they get filtered out
    # at pool admission (exporter.py: `position == 1 OR is_two_way`)
    # and at the sub-floor gate below that NaN's their sp_war /
    # rp_war.
    df["pwOBAR"] = (
        PITCHING_WOBA_WEIGHTS["hr_vs_wOBA_weight"] * df["hr_vsR"] +
        PITCHING_WOBA_WEIGHTS["bb_vs_wOBA_weight"] * df["bb_vsR"] +
        PITCHING_WOBA_WEIGHTS["h_nothr_vs_wOBA_weight"] * df["h_nothr_vsR"]
    )

    df["pwOBAL"] = (
        PITCHING_WOBA_WEIGHTS["hr_vs_wOBA_weight"] * df["hr_vsL"] +
        PITCHING_WOBA_WEIGHTS["bb_vs_wOBA_weight"] * df["bb_vsL"] +
        PITCHING_WOBA_WEIGHTS["h_nothr_vs_wOBA_weight"] * df["h_nothr_vsL"]
    )

    df["pwOBA"] = (
        df["pwOBAR"] * HANDEDNESS_WEIGHTS["R"] +
        df["pwOBAL"] * HANDEDNESS_WEIGHTS["L"]
    )

    # Base WAR at full-season (SP) IP. Both sp_war and rp_war are populated
    # for every eligible pitcher so users can compare role-fit: an SP with
    # rp_war higher than the marginal RP's rp_war might be better suited for
    # the pen, and an RP with high sp_war might be a stretch-out candidate.
    #
    # pwOBA / pwOBAR / pwOBAL are intentionally NOT gated by PITCHER_RATING_FLOOR
    # — they're bounded (post-clamp-fix) and useful as raw skill-quality
    # metrics for minor league system planning, where ratings <35 are common.
    #
    # Component-aware formula: WAR = b0 + b_HR*HR% + b_BB*BB% + b_K*K% + b_C*contact%
    # Coefficients refit from sim sweeps; old single-coefficient pwOBA regression
    # was systematically off by 2.5-3.5 WAR.
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

    # Apply PITCHER_RATING_FLOOR to the WAR columns only. Sub-floor current WAR
    # isn't meaningful (the table extrapolation in 20-34 is unreliable for
    # ranking against MLB-tier pitchers), but pwOBA stays visible so analysts
    # can still rank minor leaguers on raw skill.
    existing_skill_cols = [c for c in PITCHER_SKILL_COLS_CURRENT if c in df.columns]
    if existing_skill_cols:
        sub_floor = (df[existing_skill_cols].fillna(0) < PITCHER_RATING_FLOOR).any(axis=1)
        df.loc[sub_floor, ["sp_war", "rp_war"]] = pd.NA

    # NaN sp_war for pitchers who physically can't be stretched out.
    # Stamina <= 35 means "if used as SP" is implausible regardless of skill.
    if "stamina" in df.columns:
        too_short = df["stamina"].fillna(0) < SP_WAR_MIN_STAMINA
        df.loc[too_short, "sp_war"] = pd.NA

    # Primary-role WAR: sp_war if classified SP, rp_war if classified RP.
    # Used by org_report.build_pitching_staff for rotation/bullpen ordering.
    df["is_sp"] = (df["sprp"] == "sp").astype(int)
    df["is_rp"] = (df["sprp"] == "rp").astype(int)
    df["war_pitching"] = pd.NA
    sp_mask = df["sprp"] == "sp"
    rp_mask = df["sprp"] == "rp"
    df.loc[sp_mask, "war_pitching"] = df.loc[sp_mask, "sp_war"]
    df.loc[rp_mask, "war_pitching"] = df.loc[rp_mask, "rp_war"]

    return df


# Calculate pitching metrics based on potential ratings (no handedness)
def calc_potential_pitching_metrics(df: pd.DataFrame) -> pd.DataFrame:

    # Establish potential role using stamina alone — pwOBAP / sp_warP /
    # rp_warP are computed for everyone so two-way prospects with
    # `position != 1` (e.g. Ohtani at LAD) still get a valid role tag.
    # Same logic as `calc_pitching_metrics.identify_role`.
    def identify_role(row):
        if pd.isna(row.get("stamina")):
            return ""
        if row["stamina"] >= MINIMUM_STARTER_STAMINA:
            return "sp"
        return "rp"

    df["sprpP"] = df.apply(identify_role, axis=1)

    # Helper function to adjust rates using potential ratings (no handedness).
    # Multiplicative model — see calc_pitching_metrics for rationale.
    def adjust_rates(row):
        rates = {
            "hr_vs": BASE_PITCHING_RATES["hr_vs_baserate"],
            "bb_vs": BASE_PITCHING_RATES["bb_vs_baserate"],
            "k_vs": BASE_PITCHING_RATES["k_vs_baserate"],
            "h_nothr_vs": BASE_PITCHING_RATES["h_nothr_vs_baserate"]
        }
        ratings = {
            "Control": row["ctrlP"],
            "pBABIP": row["pbabipP"],
            "HRA": row["hraP"],
            "Stuff": row["stuffP"],
            "Stamina": row["stamina"]
        }

        for category, value in ratings.items():
            table = PITCHING_COMPONENTS_ADJUST_MAP[category]
            keys = list(map(int, table.keys()))
            min_key = min(keys)
            max_key = max(keys)

            if category == "Stamina":
                str_value = str(value)
                if str_value not in table:
                    continue
                adj = table[str_value]
            else:
                if pd.isna(value):
                    clamped = min_key
                else:
                    clamped = max(min_key, min(int(value), max_key))
                adj = table[str(clamped)]

            rates["hr_vs"] *= adj["hr_vs_mult"]
            rates["bb_vs"] *= adj["bb_vs_mult"]
            rates["k_vs"] *= adj["k_vs_mult"]
            rates["h_nothr_vs"] *= adj["h_nothr_vs_mult"]

        return pd.Series(rates)

    # Apply potential rating adjustments
    rates = df.apply(adjust_rates, axis=1)
    df = pd.concat([df, rates], axis=1)

    # Only calculate pWOBA for valid potential pitchers
    valid_pitcher = df["sprpP"].isin(["sp", "rp"])

    df["pwOBAP"] = (
        PITCHING_WOBA_WEIGHTS["hr_vs_wOBA_weight"] * df["hr_vs"] +
        PITCHING_WOBA_WEIGHTS["bb_vs_wOBA_weight"] * df["bb_vs"] +
        PITCHING_WOBA_WEIGHTS["h_nothr_vs_wOBA_weight"] * df["h_nothr_vs"]
    ).where(valid_pitcher)

    # Base potential WAR at full-season (SP) IP. No PITCHER_RATING_FLOOR
    # applied — potential is meant to show development upside, so even
    # currently-sub-floor pitchers get a meaningful potential projection
    # (sub-floor potentials are clamped to min_key in adjust_rates above).
    #
    # Component-aware formula mirrors current-side WAR (see calc_pitching_metrics).
    hr_pctP = df["hr_vs"] * 100
    bb_pctP = df["bb_vs"] * 100
    k_pctP  = df["k_vs"] * 100
    c_pctP  = df["h_nothr_vs"] * 100

    base_warP = (
        PITCHING_WAR_COEFFS["intercept"]
        + PITCHING_WAR_COEFFS["hr_pct_coef"] * hr_pctP
        + PITCHING_WAR_COEFFS["bb_pct_coef"] * bb_pctP
        + PITCHING_WAR_COEFFS["k_pct_coef"] * k_pctP
        + PITCHING_WAR_COEFFS["h_nothr_pct_coef"] * c_pctP
    ).where(valid_pitcher).round(1)

    # Both sp_warP and rp_warP populated for every eligible pitcher (same
    # reasoning as current: lets users compare role-fit). Primary-role
    # war_pitchingP picks based on potential role classification (sprpP).
    df["sp_warP"] = base_warP
    df["rp_warP"] = (base_warP * RELIEVER_VS_STARTER_AVERAGE_IP).round(1)

    # Same stamina gate as sp_war — OOTP has one stamina rating shared by
    # current and potential, so a permanently-stamina-30 pitcher can't be
    # an SP regardless of skill. NaN'd values render as blank in the HTML
    # via exporter's value_formatter (not as the literal string "nan").
    if "stamina" in df.columns:
        too_short = df["stamina"].fillna(0) < SP_WAR_MIN_STAMINA
        df.loc[too_short, "sp_warP"] = pd.NA

    df["is_spP"] = (df["sprpP"] == "sp").astype(int)
    df["is_rpP"] = (df["sprpP"] == "rp").astype(int)

    # Primary-role potential WAR — mirror the current-side pattern at line 162+
    # (gate by sprpP role, not by sp_warP.notna()). The previous version masked
    # the whole expression on sp_warP existing, which incorrectly NaN'd
    # war_pitchingP for RP-classified pitchers whose sp_warP was NaN due to
    # the SP_WAR_MIN_STAMINA gate.
    df["war_pitchingP"] = pd.NA
    sp_mask_p = df["sprpP"] == "sp"
    rp_mask_p = df["sprpP"] == "rp"
    df.loc[sp_mask_p, "war_pitchingP"] = df.loc[sp_mask_p, "sp_warP"]
    df.loc[rp_mask_p, "war_pitchingP"] = df.loc[rp_mask_p, "rp_warP"]

    non_pitcher = ~df["sprpP"].isin(["sp", "rp"])
    df.loc[non_pitcher, ["sp_warP", "rp_warP"]] = pd.NA

    return df