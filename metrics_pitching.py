import pandas as pd
from config import (
    BASE_PITCHING_RATES,
    PITCHING_COMPONENTS_ADJUST_MAP,
    PITCHING_WOBA_WEIGHTS,
    HANDEDNESS_WEIGHTS,
    MINIMUM_STARTER_STAMINA,
    PITCHER_RATING_FLOOR,
    RUNS_PER_GAME_PITCHING_COEFF,
    RUNS_PER_GAME_PITCHING_CONST,
    RUNS_PER_WIN,
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

    # Establish role using OOTP's classifier (position == 1) plus a single
    # stamina threshold for SP vs RP. Pitch-count is no longer in the gate —
    # stamina alone determines whether a pitcher can carry a starter's
    # workload. Below MINIMUM_STARTER_STAMINA they're a reliever; at or
    # above they're a potential starter regardless of pitch-mix breadth.
    def identify_role(row):
        if row.get("position") != 1:
            return ""
        if row["stamina"] >= MINIMUM_STARTER_STAMINA:
            return "sp"
        return "rp"

    df["sprp"] = df.apply(identify_role, axis=1)

    # Helper function to adjust rates
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
                # Clamp to [min_key, max_key]. Mirrors metrics_hitting.py and
                # avoids the previous sub-floor x10 amplification, which
                # produced mathematically impossible pwOBA (>1.0) for low-rated
                # pitchers and absurdly-negative rp_war.
                if pd.isna(value):
                    clamped = min_key
                else:
                    clamped = max(min_key, min(int(value), max_key))
                adj = table[str(clamped)]

            rates["hr_vs"] += adj["hr_vs_adj"]
            rates["bb_vs"] += adj["bb_vs_adj"]
            rates["k_vs"] += adj["k_vs_adj"]
            rates["h_nothr_vs"] += adj["h_nothr_vs_adj"]

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

    # Compute pwOBA for any OOTP-labelled pitcher (position == 1). Position
    # players have other position codes; their emergency-pitcher ratings
    # are uniform low values that aren't meaningful as MLB metrics.
    pitcher_capable = df["position"] == 1

    df["pwOBAR"] = (
        PITCHING_WOBA_WEIGHTS["hr_vs_wOBA_weight"] * df["hr_vsR"] +
        PITCHING_WOBA_WEIGHTS["bb_vs_wOBA_weight"] * df["bb_vsR"] +
        PITCHING_WOBA_WEIGHTS["h_nothr_vs_wOBA_weight"] * df["h_nothr_vsR"]
    ).where(pitcher_capable)

    df["pwOBAL"] = (
        PITCHING_WOBA_WEIGHTS["hr_vs_wOBA_weight"] * df["hr_vsL"] +
        PITCHING_WOBA_WEIGHTS["bb_vs_wOBA_weight"] * df["bb_vsL"] +
        PITCHING_WOBA_WEIGHTS["h_nothr_vs_wOBA_weight"] * df["h_nothr_vsL"]
    ).where(pitcher_capable)

    df["pwOBA"] = (
        df["pwOBAR"] * HANDEDNESS_WEIGHTS["R"] +
        df["pwOBAL"] * HANDEDNESS_WEIGHTS["L"]
    ).where(pitcher_capable)

    # Base WAR at full-season (SP) IP. Both sp_war and rp_war are populated
    # for every eligible pitcher so users can compare role-fit: an SP with
    # rp_war higher than the marginal RP's rp_war might be better suited for
    # the pen, and an RP with high sp_war might be a stretch-out candidate.
    #
    # pwOBA / pwOBAR / pwOBAL are intentionally NOT gated by PITCHER_RATING_FLOOR
    # — they're bounded (post-clamp-fix) and useful as raw skill-quality
    # metrics for minor league system planning, where ratings <35 are common.
    base_war = (
        -((df["pwOBA"] * RUNS_PER_GAME_PITCHING_COEFF) - RUNS_PER_GAME_PITCHING_CONST)
        / RUNS_PER_WIN
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

    # Establish potential role using OOTP's classifier (position == 1)
    # plus stamina alone for SP vs RP. Mirrors the current-side gate —
    # stamina is the binding constraint for rotation viability.
    def identify_role(row):
        if row.get("position") != 1:
            return ""
        if row["stamina"] >= MINIMUM_STARTER_STAMINA:
            return "sp"
        return "rp"

    df["sprpP"] = df.apply(identify_role, axis=1)

    # Helper function to adjust rates using potential ratings (no handedness)
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
                # Clamp to [min_key, max_key]. See calc_pitching_metrics for
                # why the prior x10 sub-floor amplification was removed.
                if pd.isna(value):
                    clamped = min_key
                else:
                    clamped = max(min_key, min(int(value), max_key))
                adj = table[str(clamped)]

            rates["hr_vs"] += adj["hr_vs_adj"]
            rates["bb_vs"] += adj["bb_vs_adj"]
            rates["k_vs"] += adj["k_vs_adj"]
            rates["h_nothr_vs"] += adj["h_nothr_vs_adj"]

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
    base_warP = (
        -((df["pwOBAP"] * RUNS_PER_GAME_PITCHING_COEFF) - RUNS_PER_GAME_PITCHING_CONST)
        / RUNS_PER_WIN
    ).round(1)

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
    df["war_pitchingP"] = (
        df["sp_warP"].fillna(0) * df["is_spP"]
        + df["rp_warP"].fillna(0) * df["is_rpP"]
    ).where(df["sp_warP"].notna())

    non_pitcher = ~df["sprpP"].isin(["sp", "rp"])
    df.loc[non_pitcher, ["war_pitchingP", "sp_warP", "rp_warP"]] = pd.NA

    return df