"""Apply per-position fielding multipliers to config.py.

Reads the multipliers from `outputs/fielding_calibration_proposal.json`
(produced by `calibration/fielding_calibration.py`), then:
  1. Backs up config.py to config.py.bak.<timestamp>
  2. In-place rewrites every numeric value inside
       FIELDING_RUN_VALUES_VS_REPLACEMENT[pos]
     by `value * multipliers[pos]`. Preserves comments, indent, structure.
  3. In-place rewrites the four params (ceil_pos, scale_pos, ceil_neg,
     scale_neg) for each position in FIELDING_SATURATION by the same
     per-position multiplier. (Preserves the asymmetric-tanh curve shape:
     sat'(k*x) with all params scaled by k = k * sat(x).)
  4. Prints a diff summary.

Usage:
  python -X utf8 calibration/apply_fielding_calibration.py             # dry-run
  python -X utf8 calibration/apply_fielding_calibration.py --apply     # actually write
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

CONFIG_PY = _ROOT / "config.py"
PROPOSAL_JSON = _ROOT / "outputs/fielding_calibration_proposal.json"


def find_block(lines: list[str], marker: str) -> tuple[int, int]:
    """Return (start_index, end_index_inclusive) of a top-level dict
    starting with `marker = {` and ending with the next column-0 `}`."""
    start = None
    for i, l in enumerate(lines):
        if l.startswith(marker):
            start = i
            break
    if start is None:
        raise RuntimeError(f"{marker} not found in config.py")
    end = None
    for i in range(start + 1, len(lines)):
        if lines[i].rstrip() == "}":
            end = i
            break
    if end is None:
        raise RuntimeError(f"Closing brace for {marker} not found")
    return start, end


# Match an inner-dict position header: `    "C": {` (and same for 2-letter / 3-letter codes)
POSITION_RE = re.compile(r'^    "(C|1B|2B|3B|SS|LF|CF|RF|DH)": \{')

# Match a rating-value line:  `            20: -2.0,` or `            55: 0,`
# Captures: leading-indent, rating-key, value, trailing-text (incl. comment)
RATING_RE = re.compile(
    r'^(\s+)(-?\d+):\s*(-?\d+(?:\.\d+)?),(\s*.*)$'
)

# Match a saturation-parameter line: `        "ceil_pos":  200.000,  # comment`
SAT_PARAM_RE = re.compile(
    r'^(\s+)"(ceil_pos|scale_pos|ceil_neg|scale_neg)":\s+'
    r'(-?\d+(?:\.\d+)?),(\s*.*)$'
)

# Match the closing of an inner position dict: `    },`
INNER_CLOSE_RE = re.compile(r'^    \},?\s*$')


def fmt_value(v: float) -> str:
    """Format a multiplied value to match the existing style:
    keep 1 decimal for FIELDING_RUN_VALUES_VS_REPLACEMENT,
    3 decimals for FIELDING_SATURATION."""
    return f"{v:.1f}"


def fmt_sat_value(v: float) -> str:
    return f"{v:.3f}"


def transform_run_values(
    lines: list[str],
    start: int,
    end: int,
    multipliers: dict[str, float],
) -> tuple[list[str], dict[str, int]]:
    """Multiply every rating-value entry inside each per-position
    sub-dict by the per-position multiplier. Returns (new_lines, counts)."""
    out = list(lines)
    counts = {pos: 0 for pos in multipliers}
    current_pos = None

    for i in range(start, end + 1):
        line = out[i]
        m_pos = POSITION_RE.match(line)
        if m_pos:
            current_pos = m_pos.group(1)
            continue
        if INNER_CLOSE_RE.match(line):
            current_pos = None
            continue
        if current_pos is None or current_pos not in multipliers:
            continue
        m = RATING_RE.match(line)
        if not m:
            continue
        indent, rating_key, value, suffix = m.groups()
        new_val = float(value) * multipliers[current_pos]
        new_line = f"{indent}{rating_key}: {fmt_value(new_val)},{suffix}\n"
        out[i] = new_line
        counts[current_pos] += 1
    return out, counts


def transform_saturation(
    lines: list[str],
    start: int,
    end: int,
    multipliers: dict[str, float],
) -> tuple[list[str], dict[str, int]]:
    """Multiply the four saturation params (ceil_pos, scale_pos,
    ceil_neg, scale_neg) for 2B / 3B / SS by their per-position
    multiplier. Preserves the tanh curve shape exactly (scaling input,
    ceiling, and scale by k yields output * k)."""
    out = list(lines)
    counts = {pos: 0 for pos in multipliers}
    current_pos = None

    for i in range(start, end + 1):
        line = out[i]
        m_pos = POSITION_RE.match(line)
        if m_pos:
            current_pos = m_pos.group(1)
            continue
        if INNER_CLOSE_RE.match(line):
            current_pos = None
            continue
        if current_pos is None or current_pos not in multipliers:
            continue
        m = SAT_PARAM_RE.match(line)
        if not m:
            continue
        indent, param_key, value, suffix = m.groups()
        new_val = float(value) * multipliers[current_pos]
        new_line = f'{indent}"{param_key}":  {fmt_sat_value(new_val)},{suffix}\n'
        out[i] = new_line
        counts[current_pos] += 1
    return out, counts


def load_multipliers() -> dict[str, float]:
    if not PROPOSAL_JSON.exists():
        raise SystemExit(
            f"Missing {PROPOSAL_JSON}. Run "
            f"`python -X utf8 calibration/fielding_calibration.py --top-n 10` first."
        )
    proposal = json.load(open(PROPOSAL_JSON))
    out = {}
    for pos, entry in proposal["positions"].items():
        m = entry.get("multiplier")
        if m is not None:
            out[pos] = float(m)
    if not out:
        raise SystemExit("No multipliers in proposal — nothing to apply.")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually write config.py (otherwise dry-run preview)")
    args = ap.parse_args()

    multipliers = load_multipliers()
    print("Per-position multipliers (from proposal JSON):")
    for pos in ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"):
        if pos in multipliers:
            print(f"  {pos}: x{multipliers[pos]:.4f}")
    print()

    text = CONFIG_PY.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    rv_start, rv_end = find_block(lines, "FIELDING_RUN_VALUES_VS_REPLACEMENT")
    sat_start, sat_end = find_block(lines, "FIELDING_SATURATION")
    print(f"FIELDING_RUN_VALUES_VS_REPLACEMENT: lines {rv_start+1}..{rv_end+1}")
    print(f"FIELDING_SATURATION: lines {sat_start+1}..{sat_end+1}")

    new_lines, rv_counts = transform_run_values(lines, rv_start, rv_end, multipliers)
    # FIELDING_SATURATION only has 2B/3B/SS entries — pass only those multipliers
    sat_mults = {p: multipliers[p] for p in ("2B", "3B", "SS") if p in multipliers}
    new_lines, sat_counts = transform_saturation(new_lines, sat_start, sat_end, sat_mults)

    print(f"\nFIELDING_RUN_VALUES_VS_REPLACEMENT entries rewritten per position:")
    for pos, n in rv_counts.items():
        print(f"  {pos}: {n} entries")
    print(f"\nFIELDING_SATURATION params rewritten per position:")
    for pos, n in sat_counts.items():
        print(f"  {pos}: {n} params")

    # Show diff sample
    print("\nSample diff (first changed line in each section):")
    changed = 0
    for i, (old, new) in enumerate(zip(lines, new_lines)):
        if old != new and changed < 10:
            print(f"  line {i+1}:")
            print(f"    -  {old.rstrip()}")
            print(f"    +  {new.rstrip()}")
            changed += 1

    if not args.apply:
        print("\nDRY-RUN. Re-run with --apply to write config.py.")
        return

    # Backup
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = CONFIG_PY.with_suffix(f".py.bak.{ts}")
    shutil.copy(CONFIG_PY, backup_path)
    print(f"\nBacked up original to: {backup_path.name}")

    CONFIG_PY.write_text("".join(new_lines), encoding="utf-8")
    print(f"Wrote new {CONFIG_PY.name}")


if __name__ == "__main__":
    main()
