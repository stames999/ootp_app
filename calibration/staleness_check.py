"""Calibration staleness check.

Reads `calibration/CALIBRATION_META.json` and fails loudly if the
recorded sim-sweep / FG-snapshot dates are older than the tolerances
defined here. Intended to be run before any re-calibration session as a
"do I trust the anchor data?" gate.

Usage:
    python -X utf8 calibration/staleness_check.py

Tolerances (days):
    sim_sweep    180 (6 months)       — warn
    sim_sweep    365 (12 months)      — fail
    fg_snapshot  365                  — warn
    fg_snapshot  730                  — fail

These are conservative; OOTP's component behaviour doesn't shift fast
day-to-day, but a year-old sweep means the model is calibrated against
a snapshot that may not match the current sim build. Same for FG: per-
position production drifts season-to-season as MLB shifts.

R-33: this script + CALIBRATION_META.json sidecar were added to make
the calibration provenance explicit. Earlier the dates were tribal
knowledge (best guesses from commit logs).
"""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


META_PATH = Path(__file__).resolve().parent / 'CALIBRATION_META.json'

SIM_WARN_DAYS = 180
SIM_FAIL_DAYS = 365
FG_WARN_DAYS = 365
FG_FAIL_DAYS = 730


def _days_since(iso_date: str) -> int:
    d = datetime.fromisoformat(iso_date).date()
    return (date.today() - d).days


def main() -> int:
    if not META_PATH.exists():
        print(f"ERROR: {META_PATH} missing. Calibration provenance "
              f"is required before trusting any recalibration script.",
              file=sys.stderr)
        return 2

    meta = json.loads(META_PATH.read_text(encoding='utf-8'))
    issues_fatal = []
    issues_warn = []

    sim_d = _days_since(meta['sim_sweep_date'])
    if sim_d > SIM_FAIL_DAYS:
        issues_fatal.append(
            f"sim_sweep_date {meta['sim_sweep_date']} is {sim_d} days old "
            f"(> {SIM_FAIL_DAYS} fail threshold). Re-run team-of-clones "
            f"sweeps before recalibrating."
        )
    elif sim_d > SIM_WARN_DAYS:
        issues_warn.append(
            f"sim_sweep_date {meta['sim_sweep_date']} is {sim_d} days old "
            f"(> {SIM_WARN_DAYS} warn threshold)."
        )

    fg_d = _days_since(meta['fg_snapshot_date'])
    if fg_d > FG_FAIL_DAYS:
        issues_fatal.append(
            f"fg_snapshot_date {meta['fg_snapshot_date']} is {fg_d} days "
            f"old (> {FG_FAIL_DAYS} fail threshold). Re-snapshot the FG "
            f"reference CSVs into calibration/fg_2025/."
        )
    elif fg_d > FG_WARN_DAYS:
        issues_warn.append(
            f"fg_snapshot_date {meta['fg_snapshot_date']} is {fg_d} days "
            f"old (> {FG_WARN_DAYS} warn threshold)."
        )

    print(f"Pistachio calibration provenance:")
    print(f"  OOTP version:           {meta.get('ootp_version')}")
    print(f"  Sim sweep date:         {meta['sim_sweep_date']} ({sim_d} days ago)")
    print(f"  FG snapshot year/date:  {meta['fg_snapshot_year']} / {meta['fg_snapshot_date']} ({fg_d} days ago)")
    print(f"  RUNS_PER_WIN_HITTING:   {meta.get('wins_above_replacement_per_run')}")

    if issues_warn:
        print("\nWARNINGS:")
        for w in issues_warn:
            print(f"  - {w}")

    if issues_fatal:
        print("\nFATAL:", file=sys.stderr)
        for w in issues_fatal:
            print(f"  - {w}", file=sys.stderr)
        return 1

    if not issues_warn and not issues_fatal:
        print("\nAll calibration anchors fresh.")

    return 0


if __name__ == '__main__':
    sys.exit(main())
