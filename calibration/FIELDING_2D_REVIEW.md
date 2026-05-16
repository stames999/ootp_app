# Fielding Multi-Dimensional Skill — Methodology Review

## Status

**Open question.** Documented for future investigation; the
implementation requires new OOTP team-of-clones fielding sweeps that
can't be generated in-session.

## The concern

The fielding metric pipeline (`metrics_fielding.py`) treats each
fielding skill as **independent and additive**, then applies an
asymmetric tanh saturation at the elite-glove end. Specifically:

For premium IF positions (SS, 2B, 3B) the model is roughly:
```
fld_runs(pos) = lookup(IFrange) + lookup(IFarm) + lookup(IFerror)
                + lookup(turnDP, if 2B) + tanh_saturate(top end)
```

With one ad-hoc 2D patch at 3B for the specific cell **(RNG=55, ARM=55)**
where the empirical sim WAR diverged from the additive sum by −7 runs
(see `config.py:1891-2042` and the comment block at the patch site).

## Why a 1D-additive model is fragile here

Real defensive value is highly cross-skill-dependent. Concrete examples
the current model probably under-distinguishes:

| Archetype | IFrange | IFarm | IFerror | Naive sum | Real value |
|---|---|---|---|---|---|
| Range-first SS | 75 | 50 | 60 | +X | High at SS (his range covers up to mistakes) |
| Arm-first SS | 50 | 75 | 60 | +X | Lower at SS (can't get to enough balls), better at 3B |
| Veteran error-free | 50 | 50 | 80 | +X | OK everywhere, ceiling capped |

The 1D model gives all three the same `+X` if the sums are equal, but
their actual defensive profiles and best-position fit differ. The
saturation handles the **top end** (all elite ratings) but doesn't
handle **profile imbalances**.

## What's already in place

The `apply_hp_premium_fit_override()` function in `build_system.py`
catches some of this at the roster-construction layer — a CF-capable
HP whose `best_adj` came out as a corner OF gets re-tagged to CF/SS/2B
based on actual position eligibility. This is a post-hoc patch over
the underlying metric.

The R-15 era introduced `apply_fielding_calibration.py` (now
deprecated) which attempted a multiplier-based reshape of the sim
tables. The current approach uses `posadj_shift_calibration.py`
(shift `POSITIONAL_ADJUSTMENT_RUNS` instead of re-fitting the tables)
because the multiplier approach was over-distorting elite OF gloves.

## What to validate

Two related sweeps:

### Sweep A — 2D `RNG × ARM` at SS / 2B

For each of SS, 2B (the two most cross-skill-dependent positions),
run a 5×5 grid of (RNG, ARM) at fixed IFerror=55, turnDP=55 (for 2B).
That's 25 sim runs per position = 50 total. Each run = ~5-10 min sim
time.

Output: a 2D residual surface — observed sim WAR vs predicted 1D-sum
WAR. If residuals are small (< 2 runs) and unstructured, the 1D model
holds and we don't need a 2D table. If residuals are large or have a
clear diagonal/off-diagonal pattern, build a 2D correction lookup.

### Sweep B — IFerror interaction with range

A separate 5×5 of (RNG, IFerror) at ARM=50, with the same residual
analysis. Targets the "veteran with low range / few errors" vs "rangy
with errors" trade-off that the 1D-sum currently treats as equivalent.

### Effort estimate

- 50 + 25 = 75 sim runs at ~10 min each = ~12 hours of unattended
  wall time. Realistically 2-3 days of OOTP running with breaks.
- Sweep design + driver script: 1 day.
- Analysis + 2D-table generation: 1-2 days.

Total: ~1 week of focused work, mostly unattended sim time.

## What we'd do if there's drift

The cleanest implementation: a 2D lookup table per position, with
`fld_runs(pos, RNG, ARM, IFerror, ...) = sum_1d(...) + correction_2D(RNG, ARM)`.
The correction table would be small (5×5 or 6×6 per position) so it's
hand-edible and visible to the user.

A more invasive option: drop the 1D-additive assumption entirely and
fit a small neural / random-forest model per position. Not recommended
— harder to inspect, harder to recalibrate, harder to debug.

## How to know it's worth running

Triggers:

- Roster results consistently mis-position specific archetypes (e.g.,
  a known range-first SS gets routed to 3B because his arm shows weak,
  even though the sim engine would value his SS range above his
  reduced 3B defensive ceiling).
- DRS / OAA-equivalent comparisons against FG fielding leaderboards
  show systematic gaps for specific archetypes — beyond what the
  POSITIONAL_ADJUSTMENT_RUNS shift can absorb.
- You decide to expand the sim engine's fielding model in a way that
  invalidates the current 1D fit.

In the absence of those triggers, the 1D + saturation + 3B patch
combination is doing reasonable work. The R-15/R-16 calibration
shifted `POSITIONAL_ADJUSTMENT_RUNS` to absorb most aggregate-level
mis-fit; the cross-archetype residual is the remaining concern.

R-33: this review was prompted by the methodology audit. Conclusion:
keep the current 1D-additive model + 3B 2D patch; defer the broader
2D sweep until an archetype-mismatch observation triggers it.
