"""
Validate the new pitcher model against the sim sweeps.
Predicts each sim row's HR%/BB%/K%/contact%/pwOBA/WAR using the production
model and compares to the actual sim values.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    BASE_PITCHING_RATES,
    PITCHING_COMPONENTS_ADJUST_MAP,
    PITCHING_WOBA_WEIGHTS,
    PITCHING_WAR_COEFFS,
    HANDEDNESS_WEIGHTS,
)


def predict(ctrl, hra, pbabip, stuff, stamina):
    """Predict (HR%, BB%, K%, contact%, pwOBA, WAR) for a pitcher with these
    ratings on both sides (vs R and vs L identical)."""
    rates = {
        "hr_vs": BASE_PITCHING_RATES["hr_vs_baserate"],
        "bb_vs": BASE_PITCHING_RATES["bb_vs_baserate"],
        "k_vs": BASE_PITCHING_RATES["k_vs_baserate"],
        "h_nothr_vs": BASE_PITCHING_RATES["h_nothr_vs_baserate"],
    }
    ratings = {
        "Control": ctrl,
        "pBABIP": pbabip,
        "HRA": hra,
        "Stuff": stuff,
        "Stamina": stamina,
    }
    for cat, val in ratings.items():
        table = PITCHING_COMPONENTS_ADJUST_MAP[cat]
        keys = list(map(int, table.keys()))
        min_k, max_k = min(keys), max(keys)
        if cat == "Stamina":
            sk = str(val)
            if sk not in table:
                continue
            adj = table[sk]
        else:
            clamped = max(min_k, min(int(val), max_k))
            adj = table[str(clamped)]
        rates["hr_vs"] *= adj["hr_vs_mult"]
        rates["bb_vs"] *= adj["bb_vs_mult"]
        rates["k_vs"] *= adj["k_vs_mult"]
        rates["h_nothr_vs"] *= adj["h_nothr_vs_mult"]

    pwoba = (
        PITCHING_WOBA_WEIGHTS["hr_vs_wOBA_weight"] * rates["hr_vs"]
        + PITCHING_WOBA_WEIGHTS["bb_vs_wOBA_weight"] * rates["bb_vs"]
        + PITCHING_WOBA_WEIGHTS["h_nothr_vs_wOBA_weight"] * rates["h_nothr_vs"]
    )
    war = (
        PITCHING_WAR_COEFFS["intercept"]
        + PITCHING_WAR_COEFFS["hr_pct_coef"] * rates["hr_vs"] * 100
        + PITCHING_WAR_COEFFS["bb_pct_coef"] * rates["bb_vs"] * 100
        + PITCHING_WAR_COEFFS["k_pct_coef"] * rates["k_vs"] * 100
        + PITCHING_WAR_COEFFS["h_nothr_pct_coef"] * rates["h_nothr_vs"] * 100
    )
    return (
        rates["hr_vs"] * 100,
        rates["bb_vs"] * 100,
        rates["k_vs"] * 100,
        rates["h_nothr_vs"] * 100,
        pwoba,
        war,
    )


# Sim data: (label, ctrl, hra, pbabip, stuff, stamina, actual HR%, BB%, K%, contact%, pwOBA, WAR)
SIM = [
    ("baseline",        50, 50, 50, 50, 50, 2.7, 7.5, 21.4, 21.3, 0.318, 3.1),
    ("CTRL=20",         20, 50, 50, 50, 50, 2.3, 21.7, 17.8, 17.7, 0.376, -2.8),
    ("CTRL=25",         25, 50, 50, 50, 50, 2.4, 16.6, 19.0, 19.0, 0.355, -0.7),
    ("CTRL=30",         30, 50, 50, 50, 50, 2.5, 14.5, 19.6, 19.5, 0.346, 0.2),
    ("CTRL=35",         35, 50, 50, 50, 50, 2.6, 12.3, 20.1, 20.2, 0.339, 1.1),
    ("CTRL=40",         40, 50, 50, 50, 50, 2.6, 10.2, 20.7, 20.8, 0.330, 2.0),
    ("CTRL=45",         45, 50, 50, 50, 50, 2.7,  8.7, 21.1, 21.0, 0.322, 2.6),
    ("CTRL=55",         55, 50, 50, 50, 50, 2.7,  7.0, 21.5, 21.5, 0.317, 3.4),
    ("CTRL=60",         60, 50, 50, 50, 50, 2.8,  6.4, 21.6, 21.5, 0.313, 3.6),
    ("CTRL=70",         70, 50, 50, 50, 50, 2.8,  5.3, 22.1, 21.7, 0.308, 4.0),
    ("CTRL=80",         80, 50, 50, 50, 50, 2.9,  4.1, 22.3, 22.1, 0.304, 4.5),
    ("HRA=20",          50, 20, 50, 50, 50, 9.7,  7.4, 21.7, 19.0, 0.430, -4.8),
    ("HRA=25",          50, 25, 50, 50, 50, 7.1,  7.5, 21.5, 19.9, 0.389, -1.9),
    ("HRA=30",          50, 30, 50, 50, 50, 6.0,  7.6, 21.5, 20.2, 0.371, -0.6),
    ("HRA=35",          50, 35, 50, 50, 50, 4.9,  7.6, 21.5, 20.5, 0.352,  0.5),
    ("HRA=40",          50, 40, 50, 50, 50, 3.9,  7.6, 21.4, 20.8, 0.336,  1.6),
    ("HRA=45",          50, 45, 50, 50, 50, 3.2,  7.5, 21.3, 21.1, 0.327,  2.6),
    ("HRA=55",          50, 55, 50, 50, 50, 2.5,  7.6, 21.4, 21.4, 0.314,  3.4),
    ("HRA=60",          50, 60, 50, 50, 50, 2.2,  7.6, 21.5, 21.4, 0.309,  3.8),
    ("HRA=70",          50, 70, 50, 50, 50, 1.7,  7.5, 21.5, 21.5, 0.301,  4.5),
    ("HRA=80",          50, 80, 50, 50, 50, 1.3,  7.6, 21.3, 21.7, 0.295,  5.2),
    ("CTRL=20+HRA=20",  20, 20, 50, 50, 50, 8.0, 21.5, 18.0, 15.9, 0.468, -8.8),
    ("PBABIP=20",       50, 50, 20, 50, 50, 2.7,  7.5, 21.5, 22.7, 0.332,  2.7),
    ("STAM=40",         50, 50, 50, 50, 40, 2.7,  7.5, 21.5, 21.3, 0.318,  3.1),
    ("STAM=60",         50, 50, 50, 50, 60, 2.8,  7.5, 21.4, 21.3, 0.318,  3.1),
    ("STAM=80",         50, 50, 50, 50, 80, 2.8,  7.5, 21.3, 21.3, 0.319,  3.1),  # STAM=80 not in table -> skip
]

print(f"{'label':>16} | {'HR%':>11} {'BB%':>11} {'K%':>11} {'C%':>11} {'pwOBA':>13} {'WAR':>13}")
print(f"{'':>16} | {'pred / act':>11} {'pred / act':>11} {'pred / act':>11} {'pred / act':>11} {'pred / act':>13} {'pred / act':>13}")
print("-" * 110)

errors = {"hr": [], "bb": [], "k": [], "c": [], "pwoba": [], "war": []}
for label, ctrl, hra, pbabip, stuff, stamina, ahr, abb, ak, ac, apwoba, awar in SIM:
    phr, pbb, pk, pc, ppwoba, pwar = predict(ctrl, hra, pbabip, stuff, stamina)
    print(f"{label:>16} | "
          f"{phr:>4.1f}/{ahr:>4.1f}  "
          f"{pbb:>4.1f}/{abb:>4.1f}  "
          f"{pk:>4.1f}/{ak:>4.1f}  "
          f"{pc:>4.1f}/{ac:>4.1f}  "
          f"{ppwoba:>5.3f}/{apwoba:>5.3f}  "
          f"{pwar:>5.2f}/{awar:>5.2f}")
    errors["hr"].append(phr - ahr)
    errors["bb"].append(pbb - abb)
    errors["k"].append(pk - ak)
    errors["c"].append(pc - ac)
    errors["pwoba"].append(ppwoba - apwoba)
    errors["war"].append(pwar - awar)

print()
print("Error summary (predicted - actual):")
import statistics
for key in errors:
    vals = errors[key]
    print(f"  {key:>6}: mean={statistics.mean(vals):+7.3f}  rms={(sum(v*v for v in vals)/len(vals))**0.5:>7.3f}  max|err|={max(abs(v) for v in vals):>7.3f}")
