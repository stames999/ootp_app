"""
Read-only fit of new pitcher model from sim sweeps.

Outputs:
  - new BASE_PITCHING_RATES
  - multiplicative CTRL and HRA tables
  - component-aware WAR coefficients (anchored)

Does NOT write to config or production code.
"""
import numpy as np

# ============================================================
# Sim data: (HR%, BB%, K%, contact%, pwOBA, OOTP_WAR)
# ============================================================

BASELINE_REPS = [
    (2.7, 7.5, 21.4, 21.4, 0.318, 3.1),
    (2.7, 7.5, 21.4, 21.4, 0.318, 3.1),
    (2.7, 7.5, 21.4, 21.3, 0.318, 3.1),
]

CTRL_SWEEP = {
    20: (2.3, 21.7, 17.8, 17.7, 0.376, -2.8),
    25: (2.4, 16.6, 19.0, 19.0, 0.355, -0.7),
    30: (2.5, 14.5, 19.6, 19.5, 0.346, 0.2),
    35: (2.6, 12.3, 20.1, 20.2, 0.339, 1.1),
    40: (2.6, 10.2, 20.7, 20.8, 0.330, 2.0),
    45: (2.7, 8.7, 21.1, 21.0, 0.322, 2.6),
    50: (2.7, 7.5, 21.4, 21.3, 0.318, 3.1),
    55: (2.7, 7.0, 21.5, 21.5, 0.317, 3.4),
    60: (2.8, 6.4, 21.6, 21.5, 0.313, 3.6),
    70: (2.8, 5.3, 22.1, 21.7, 0.308, 4.0),
    80: (2.9, 4.1, 22.3, 22.1, 0.304, 4.5),
}

HRA_SWEEP = {
    20: (9.7, 7.4, 21.7, 19.0, 0.430, -4.8),
    25: (7.1, 7.5, 21.5, 19.9, 0.389, -1.9),
    30: (6.0, 7.6, 21.5, 20.2, 0.371, -0.6),
    35: (4.9, 7.6, 21.5, 20.5, 0.352, 0.5),
    40: (3.9, 7.6, 21.4, 20.8, 0.336, 1.6),
    45: (3.2, 7.5, 21.3, 21.1, 0.327, 2.6),
    50: (2.7, 7.5, 21.4, 21.3, 0.318, 3.1),
    55: (2.5, 7.6, 21.4, 21.4, 0.314, 3.4),
    60: (2.2, 7.6, 21.5, 21.4, 0.309, 3.8),
    70: (1.7, 7.5, 21.5, 21.5, 0.301, 4.5),
    80: (1.3, 7.6, 21.3, 21.7, 0.295, 5.2),
}

# Interaction probe + PBABIP - both validation only (not used in fit)
INTERACTION = (8.0, 21.5, 18.0, 15.9, 0.468, -8.8)
PBABIP_20 = (2.7, 7.5, 21.5, 22.7, 0.332, 2.7)

# ============================================================
# 1. New BASE_PITCHING_RATES (avg of 3 baseline reps)
# ============================================================

base_arr = np.array([r[:4] for r in BASELINE_REPS])
base_avg = base_arr.mean(axis=0)
HR0, BB0, K0, C0 = base_avg / 100.0  # convert from % to fraction
print("="*60)
print("BASE_PITCHING_RATES (refitted)")
print("="*60)
print(f"  hr_vs_baserate:        {HR0:.4f}  (was 0.0326)")
print(f"  bb_vs_baserate:        {BB0:.4f}  (was 0.0714)")
print(f"  k_vs_baserate:         {K0:.4f}  (was 0.2078)")
print(f"  h_nothr_vs_baserate:   {C0:.4f}  (was 0.2050)")
print()

# ============================================================
# 2. CTRL multiplicative table
# ============================================================

print("="*60)
print("CTRL multiplicative ratios (component_at_rating / component_at_50)")
print("="*60)
print(f"{'CTRL':>5} {'HR_mult':>10} {'BB_mult':>10} {'K_mult':>10} {'C_mult':>10}")
for rating in sorted(CTRL_SWEEP.keys()):
    hr, bb, k, c, _, _ = CTRL_SWEEP[rating]
    print(f"{rating:>5} {hr/base_avg[0]:>10.4f} {bb/base_avg[1]:>10.4f} "
          f"{k/base_avg[2]:>10.4f} {c/base_avg[3]:>10.4f}")
print()

# ============================================================
# 3. HRA multiplicative table
# ============================================================

print("="*60)
print("HRA multiplicative ratios")
print("="*60)
print(f"{'HRA':>5} {'HR_mult':>10} {'BB_mult':>10} {'K_mult':>10} {'C_mult':>10}")
for rating in sorted(HRA_SWEEP.keys()):
    hr, bb, k, c, _, _ = HRA_SWEEP[rating]
    print(f"{rating:>5} {hr/base_avg[0]:>10.4f} {bb/base_avg[1]:>10.4f} "
          f"{k/base_avg[2]:>10.4f} {c/base_avg[3]:>10.4f}")
print()

# ============================================================
# 4. Component-aware WAR fit
#
# Strategy: fit WAR = b0 + b_HR*HR% + b_BB*BB% + b_K*K% + b_C*contact%
# from CTRL+HRA pooled data (22 points + 1 interaction = 23).
# ============================================================

points = []
for sweep in (CTRL_SWEEP, HRA_SWEEP):
    for r, (hr, bb, k, c, _, war) in sweep.items():
        points.append((hr, bb, k, c, war))
points.append(INTERACTION[:4] + (INTERACTION[5],))  # 20/20

# Drop duplicate baseline (CTRL=50 == HRA=50)
seen = set()
uniq = []
for p in points:
    key = tuple(round(x, 4) for x in p[:4])
    if key not in seen:
        seen.add(key)
        uniq.append(p)
points = uniq

X = np.array([[hr, bb, k, c] for hr, bb, k, c, _ in points])
y = np.array([war for _, _, _, _, war in points])

# Pure regression (4 free coefficients)
A = np.hstack([np.ones((X.shape[0], 1)), X])
coef_pure, *_ = np.linalg.lstsq(A, y, rcond=None)
pred_pure = A @ coef_pure

print("="*60)
print("WAR fit option A: pure regression (b0 + b_HR + b_BB + b_K + b_C)")
print("="*60)
print(f"  intercept:  {coef_pure[0]:>8.4f}")
print(f"  HR%:        {coef_pure[1]:>8.4f}")
print(f"  BB%:        {coef_pure[2]:>8.4f}")
print(f"  K%:         {coef_pure[3]:>8.4f}")
print(f"  contact%:   {coef_pure[4]:>8.4f}")
print(f"  RMSE:       {np.sqrt(np.mean((y - pred_pure)**2)):>8.4f}")
print(f"  max |err|:  {np.max(np.abs(y - pred_pure)):>8.4f}")
print()

# Anchored: fix K and contact to baseball linear weights, fit HR/BB/intercept
# Linear weights (Tango 2024-ish): HR=1.40, BB=0.33, K=-0.27, single=0.46
# Convert from runs/PA to WAR: divide by 10 runs/win, multiply by ~600 PA/full-season-SP
# At ~6 IP/start * 32 starts * 4 BF/inning = ~770 BF for ace SP; ~700 for avg
# Use 600 BF as the conversion (close to OOTP baseline's BF for 50/50 SP: 482k/100k = 4.83 BF/G * 162 = 782; per pitcher / 5 rotation = 156 G eligible / 5 = ~720 BF)
# Actually compute it backwards from baseline: 50/50 SP = 3.1 WAR @ pwOBA 0.318
# Use anchored weights only for K and contact, fit b0/b_HR/b_BB freely.

# Linear weights in runs/PA (per FanGraphs standard):
W_K = -0.27       # strikeout
W_C = 0.46        # average single (proxy for hits-not-HR; mix of 1B/2B/3B)

# Convert run weight to WAR coefficient:
# WAR = (runs prevented vs replacement) / runs_per_win
# A pitcher giving up X% K rate over BF batters produces X% * W_K * BF runs.
# So WAR per percentage-point of K = (W_K / 100) * BF / 10
# Per the sim: ~482 BF in 100k games for 50/50 SP -> per 162 games = 0.78 BF
# But OOTP "WAR" is total over what looks like a 32-start (224 IP) season.
# Solve for the IP scaling factor empirically using baseline.

# At baseline: WAR=3.1, components fixed. We need K and contact fixed contributions
# to be subtracted from WAR before fitting HR and BB.

# Simpler: just do constrained least squares.
# Fit: y - W_K_war*K - W_C_war*contact = b0 + b_HR*HR + b_BB*BB
# Where W_K_war and W_C_war are derived from linear weights and an IP scale.

# IP scale: we don't know it cleanly. Try fitting it from the data.
# Two-stage: first fit pure regression, see if K and contact coefficients are reasonable.
print(f"Pure-regression K coef:       {coef_pure[3]:.4f} (literature ~-0.27 * scale)")
print(f"Pure-regression contact coef: {coef_pure[4]:.4f} (literature ~+0.46 * scale)")
print(f"Implied IP/BF scale from K:   {coef_pure[3] / -0.27 * 10:.2f}")
print(f"Implied IP/BF scale from C:   {coef_pure[4] / 0.46 * 10:.2f}")
print()

# Sanity check: predict the held-out points
print("="*60)
print("Validation: predicted WAR at out-of-fit points")
print("="*60)
print(f"PBABIP=20:  actual={PBABIP_20[5]:>5.2f}, "
      f"pred={A[0,0] + coef_pure[1]*PBABIP_20[0] + coef_pure[2]*PBABIP_20[1] + coef_pure[3]*PBABIP_20[2] + coef_pure[4]*PBABIP_20[3]:>5.2f} "
      f"(intercept={coef_pure[0]:.3f})")
pbabip_pred = coef_pure[0] + coef_pure[1]*PBABIP_20[0] + coef_pure[2]*PBABIP_20[1] + coef_pure[3]*PBABIP_20[2] + coef_pure[4]*PBABIP_20[3]
print(f"PBABIP=20:  actual={PBABIP_20[5]:>5.2f}, pred={pbabip_pred:>5.2f}")

# Stuff additive → multiplicative conversion
# Converts existing additive Stuff table using OLD base rates (since those
# were the calibration anchors for the original Stuff fit).
OLD_BASE = {"hr": 0.0326, "bb": 0.0714, "k": 0.2078, "c": 0.2050}
STUFF_OLD = {
    35: (-0.0001, -0.0015, -0.0726, +0.0224),
    40: (-0.0003, -0.0014, -0.0395, +0.0157),
    45: (+0.0003, +0.0001, -0.0154, +0.0048),
    50: (0.0, 0.0, 0.0, 0.0),
    55: (0.0000, -0.0005, +0.0310, -0.0096),
    60: (-0.0001, -0.0002, +0.0478, -0.0120),
    65: (-0.0006, -0.0006, +0.0565, -0.0220),
    70: (-0.0002, -0.0004, +0.0752, -0.0217),
    75: (-0.0004, -0.0001, +0.0881, -0.0261),
    80: (-0.0001, -0.0001, +0.1081, -0.0316),
}

print()
print("="*60)
print("Stuff multiplicative ratios (converted from old additive table)")
print("="*60)
print(f"{'STF':>5} {'HR_mult':>10} {'BB_mult':>10} {'K_mult':>10} {'C_mult':>10}")
for r in sorted(STUFF_OLD.keys()):
    hr, bb, k, c = STUFF_OLD[r]
    hr_m = (OLD_BASE["hr"] + hr) / OLD_BASE["hr"]
    bb_m = (OLD_BASE["bb"] + bb) / OLD_BASE["bb"]
    k_m = (OLD_BASE["k"] + k) / OLD_BASE["k"]
    c_m = (OLD_BASE["c"] + c) / OLD_BASE["c"]
    print(f"{r:>5} {hr_m:>10.4f} {bb_m:>10.4f} {k_m:>10.4f} {c_m:>10.4f}")
print()

# Old model comparison
print("="*60)
print("Old model WAR at sim points (for comparison)")
print("="*60)
COEF = 646.6961042
CONST = 206.0579547
def old_war(pwoba):
    return -((pwoba * COEF) - CONST) / 10

for sweep_name, sweep in [("CTRL", CTRL_SWEEP), ("HRA", HRA_SWEEP)]:
    print(f"\n{sweep_name}:")
    print(f"{'rating':>6} {'pwOBA':>7} {'OOTP_WAR':>10} {'old_model':>10} {'diff':>8}")
    for r in sorted(sweep.keys()):
        _, _, _, _, pwoba, war = sweep[r]
        ow = old_war(pwoba)
        print(f"{r:>6} {pwoba:>7.3f} {war:>10.2f} {ow:>10.2f} {war-ow:>+8.2f}")
