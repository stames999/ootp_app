"""Rebuild fielding_sim.csv from the user's complete sim run.

Reads the raw sim text (pasted into full_sim_raw.txt), parses each row, and
emits a clean fielding_sim.csv. Then diffs against the previous CSV to
report any added/changed/removed rows.

Run: python calibration/rebuild_from_full_sim.py
"""

import csv
import re
from pathlib import Path

HERE = Path(__file__).parent
RAW = HERE / "full_sim_raw.txt"
OLD_CSV = HERE / "fielding_sim.csv"
NEW_CSV = HERE / "fielding_sim.csv"

# Position-tag canonicalization. Sim has "X-Systematic" sometimes; collapse to base position.
POS_CANON = {
    "SS": "SS", "1B": "1B", "2B": "2B", "3B": "3B",
    "CF": "CF", "CF-Systematic": "CF",
    "LF": "LF", "LF-Systematic": "LF",
    "RF": "RF", "RF-Systematic": "RF",
    "C": "C", "C-Systematic": "C",
}


def is_baseline_row(name: str) -> bool:
    """True for rows that mark the simulation baseline rather than a varied scenario."""
    return name.lower().startswith("baseline")


def parse_line(line: str):
    """Parse a single tab/whitespace-separated row.

    Returns (pos, name, rng, err, arm, tdp, delta) or None if not a data row.
    `tdp` is "" if N/A (outfield + catcher positions).
    `delta` is None for baseline rows that don't carry a delta.
    """
    # Split on tabs first, fall back to whitespace.
    fields = re.split(r"\t+|\s{2,}", line.strip())
    if len(fields) < 6:
        return None

    pos_raw = fields[0].strip()
    if pos_raw not in POS_CANON:
        return None
    pos = POS_CANON[pos_raw]
    name = fields[1].strip()

    # Skip "Baseline Average" rows — they're aggregations, not sim observations.
    if name.lower() == "baseline average":
        return None

    try:
        rng = int(fields[2])
        err = int(fields[3])
        arm = int(fields[4])
    except ValueError:
        return None

    tdp_raw = fields[5].strip()
    if tdp_raw.upper() == "N/A" or tdp_raw == "":
        tdp = ""
    else:
        try:
            tdp = str(int(tdp_raw))
        except ValueError:
            tdp = ""

    # Baseline rows: always delta=0 regardless of how many trailing columns exist.
    # The sim format omits the delta columns for some baselines and writes "n/a" for
    # the "Baseline Average" — both should map to delta=0.
    if is_baseline_row(name):
        return (pos, "Baseline", rng, err, arm, tdp, 0.0)

    # For non-baseline rows, the delta is the last numeric field.
    delta_raw = fields[-1].strip() if fields else ""
    if not delta_raw or delta_raw.lower() in ("n/a", "—"):
        return None
    try:
        delta = float(delta_raw)
    except ValueError:
        return None

    return (pos, name, rng, err, arm, tdp, delta)


def main():
    if not RAW.exists():
        raise SystemExit(f"Missing input: {RAW}\nPaste the full sim into that file first.")

    rows = []
    with open(RAW, encoding="utf-8") as f:
        for line in f:
            parsed = parse_line(line)
            if parsed is not None:
                rows.append(parsed)

    # Dedupe baselines per position (keep just one)
    seen_baseline = set()
    out_rows = []
    for r in rows:
        pos, name, rng, err, arm, tdp, delta = r
        if name == "Baseline":
            if pos in seen_baseline:
                continue
            seen_baseline.add(pos)
        out_rows.append(r)

    # Diff against existing CSV
    old = []
    if OLD_CSV.exists():
        with open(OLD_CSV, newline="") as f:
            for r in csv.DictReader(f):
                old.append((r["position"], r["name"], int(r["rng"]), int(r["err"]),
                            int(r["arm"]), r["tdp"], float(r["delta"])))

    # Match by (position, rng, err, arm, tdp) — ignore name differences
    # (e.g. "SYS_X" vs "X" — same data, just renamed in earlier imports).
    old_by_tuple = {}
    for (p, n, rng, err, arm, tdp, delta) in old:
        key = (p, rng, err, arm, tdp)
        # If duplicate tuples (legitimate reruns), keep both as a list.
        old_by_tuple.setdefault(key, []).append((n, delta))
    new_by_tuple = {}
    for (p, n, rng, err, arm, tdp, delta) in out_rows:
        key = (p, rng, err, arm, tdp)
        new_by_tuple.setdefault(key, []).append((n, delta))

    added_keys = sorted(set(new_by_tuple.keys()) - set(old_by_tuple.keys()))
    removed_keys = sorted(set(old_by_tuple.keys()) - set(new_by_tuple.keys()))
    changed = []
    for k in sorted(set(new_by_tuple.keys()) & set(old_by_tuple.keys())):
        old_deltas = sorted(d for (_, d) in old_by_tuple[k])
        new_deltas = sorted(d for (_, d) in new_by_tuple[k])
        if old_deltas != new_deltas:
            changed.append((k, old_deltas, new_deltas))

    added = [(*k, new_by_tuple[k][0][1]) for k in added_keys]
    removed = [(*k, old_by_tuple[k][0][1]) for k in removed_keys]

    print(f"Parsed {len(out_rows)} rows from full sim.")
    print(f"Existing CSV: {len(old)} rows.")
    print()
    print(f"Added:   {len(added)} rows (truly new (pos, rng, err, arm, tdp) tuples)")
    for entry in added:
        print(f"  + {entry}")
    print(f"Removed: {len(removed)} rows (no longer in sim)")
    for entry in removed:
        print(f"  - {entry}")
    print(f"Changed: {len(changed)} rows (same tuple, different delta)")
    for (k, old_v, new_v) in changed:
        print(f"  ~ {k}: deltas {old_v}  ->  {new_v}")

    # Write the rebuilt CSV
    with open(NEW_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["position", "name", "rng", "err", "arm", "tdp", "delta"])
        w.writeheader()
        for (pos, name, rng, err, arm, tdp, delta) in out_rows:
            w.writerow({"position": pos, "name": name, "rng": rng, "err": err,
                        "arm": arm, "tdp": tdp, "delta": delta})

    print()
    print(f"Wrote rebuilt fielding_sim.csv with {len(out_rows)} rows.")


if __name__ == "__main__":
    main()
