# Pitcher Component Covariance — Methodology Review

## Status

**Open question.** Documented here for future investigation; can't be
resolved in-session because the validation requires new OOTP team-of-
clones sim sweeps.

## The concern

The pitcher metric pipeline (`metrics_pitching.py`) is structured as:

1. **Multiplicative adjustment of base rates by component ratings.** Each
   skill rating (CTRL, pBABIP, HRA, Stuff, Stamina) is mapped through
   `PITCHING_COMPONENTS_ADJUST_MAP` to a multiplicative factor on the
   base HR / BB / K / contact rates:

   ```
   rate_X = base_X × ctrl_adj × pbabip_adj × hra_adj × stuff_adj × stamina_adj
   ```

   This shape was empirically validated on a **pairwise** sweep (the
   HRA × CTRL 20/20 case, see metrics_pitching.py:53 comment) — the
   sim engine's interaction at the corner of two ratings matches the
   product of the two single-rating coefficients.

2. **Linear-in-rates WAR formula.** `sp_war` and `rp_war` are then
   computed as:

   ```
   WAR = b0 + b_HR × HR%  +  b_BB × BB%  +  b_K × K%  +  b_C × contact%
   ```

   Coefficients (`PITCHING_WAR_COEFFS`) were fit from sim sweeps where
   each rating was moved **in isolation** while the others were held
   at fixed midpoints.

## Why this might not transfer to real prospect pools

Real OOTP prospect distributions don't have independent ratings. They
have **strong positive correlations** between stuff-family skills (a
high-stuff pitcher usually has decent control; a low-stuff arm typically
has bad control too). Specific archetypes exhibit:

- **Power archetypes**: high Stuff (60+), high HRA (50+), moderate-low
  CTRL (40-45). High K / high HR / moderate BB.
- **Crafty archetypes**: low Stuff (35-45), high CTRL (55+), high pBABIP
  (50+). Low K / low HR / low BB.
- **Pure heat with no command**: high Stuff, low CTRL, moderate HRA. High
  K and high BB simultaneously.

The independent-sweep coefficient fit assumes the marginal effect of each
rating is the same regardless of where the other ratings are. If the sim
engine's actual interactions are non-trivial (e.g., a high-stuff pitcher
gets disproportionate value from also having high CTRL, beyond the
multiplicative model), our linear WAR formula will **under-credit or
over-credit specific archetypes**.

## What to validate

Run a focused sweep with **correlated ratings** mimicking real prospect
covariance, and compare:

1. **Component-level**: do the per-rate predictions (HR%, BB%, K%, contact%)
   match the sim's component output? If yes, the multiplicative shape is
   correct under covariance — only the WAR-from-components step needs
   re-checking.

2. **WAR-level**: does the linear formula predict sim WAR within
   tolerance for each archetype? Or are there systematic residuals?

### Proposed sweep design

For each archetype (power / crafty / wild-heat / balanced — 4 baseline
cases), run **5 correlated-ratings draws** per archetype around a centroid
defined by FG percentile bands. For each draw, simulate one team-of-clones
season (~162 starts) and record observed HR / BB / K / contact rates and
WAR.

Output: per-archetype residual plot — predicted WAR vs sim WAR. A clean
linear-with-zero-intercept fit (R² > 0.95, mean residual < 0.3 WAR) is
"model holds". Larger residuals or systematic bias means recalibration.

### Effort estimate

- Build the 4 archetypes + correlated-ratings draws: 1-2 hours.
- Run sims (manual via OOTP UI or AutoIt script): 1-2 days wall time
  (sims are slow, ~5-10 min each, can run unattended).
- Analyse + report: 2-3 hours.

Total: 3-4 working days realistic if sim time is the bottleneck.

## What we'd do if there's drift

The most likely failure mode: **interaction between Stuff and CTRL/HRA**
isn't fully captured by the multiplicative shape. The fix would be a
2D `Stuff × CTRL` correction table (analogous to the 3B fielding 55/55
patch in `metrics_fielding.py`) — small interaction term added to the
multiplicative product. Cleaner: refit the linear-in-rates coefficients
on the correlated-rating data so the fit absorbs the interaction
implicitly.

A more invasive option: switch to a non-linear WAR formula (e.g.,
component-aware with cross-terms, or a small ensemble of per-archetype
linear models). Not recommended unless the correlated sweep shows
the linear model has structural breakdown.

## How to know it's worth running

This validation is worth doing if **either**:

- You're seeing prospect-pool roster results that feel "off" for a
  specific archetype (e.g., crafty-low-stuff pitchers consistently
  ranked too high or too low across orgs), OR
- You're considering re-tuning HP gates (`HP_PITCHER_MAX_PWOBAP` etc.)
  and want confidence that the WAR coefficients are still trustworthy.

In the absence of those triggers, the current single-rating-sweep
coefficients are probably "good enough" — the pairwise validation
showed the multiplicative shape holds, and Real™ MLB statistics confirm
the linear-in-rates approximation is robust at scale.

R-33: this review was prompted by the methodology audit. Conclusion:
defer the empirical validation until a triggering observation surfaces,
keep the current model with this doc as the recorded uncertainty.
