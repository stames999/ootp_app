"""A/B-compare build_pitcher_system (v1) vs build_pitcher_system_v2 (v2).

Runs both placement modules against the active OOTP save's pitcher pool
(reads outputs/pitchers.json — run `python app.py refresh` first if you
want to point at a different save). Reports:

  1. Per-org summary table: total moves, SP/RP role swaps, releases
     gained, releases lost, slot-fill diff.
  2. Per-org detail file in outputs/v1_vs_v2/<ORG>.md: every pitcher
     whose level OR role changed.
  3. Aggregate stats across all 30 MLB orgs.
  4. Targeted invariants on v2: per-level, no RP-pool arm has better
     priority than the worst starter at the same level (= "no priority
     inversion within a level").

Usage:
    python -X utf8 compare_pitcher_placement.py            # all 30 orgs
    python -X utf8 compare_pitcher_placement.py --org CWS  # one org
    python -X utf8 compare_pitcher_placement.py --csv-dir <path>
        # point at a non-canonical save (refreshes outputs first)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import config

OUT_DIR = Path('outputs/v1_vs_v2')


def _refresh_if_needed(csv_dir: str | None) -> None:
    if csv_dir is None:
        return
    config.filepath = Path(csv_dir)
    # Re-run the pipeline to write pitchers.json for this save.
    import app
    app.refresh()  # writes outputs/pitchers.json


def _all_orgs() -> list[str]:
    return sorted([v for v in config.club_lookup.values() if v != 'FREE'])


def _build_v1(org: str):
    import build_pitcher_system as v1
    return v1.main(org=org)


def _build_v2(org: str):
    import build_pitcher_system_v2 as v2
    return v2.main(org=org)


def _flatten(rosters) -> dict[str, tuple[str, str]]:
    """Map name → (level, role) from a rosters dict."""
    out = {}
    for lvl, info in rosters.items():
        if not isinstance(info, dict):
            continue
        for p in info.get('starters', []):
            out[p['name']] = (lvl, 'SP')
        for p in info.get('bullpen', []):
            out[p['name']] = (lvl, 'RP')
    return out


def _diff_org(org: str) -> dict:
    """Run both versions; return a summary dict + per-arm diff list."""
    import build_pitcher_system as v1_mod
    rosters_v1, overflow_v1, flagged_v1 = _build_v1(org)
    rosters_v2, overflow_v2, flagged_v2 = _build_v2(org)

    placed_v1 = _flatten(rosters_v1)
    placed_v2 = _flatten(rosters_v2)
    overflow_v1_names = {p['name'] for p in overflow_v1 if isinstance(p, dict)}
    overflow_v2_names = {p['name'] for p in overflow_v2 if isinstance(p, dict)}

    all_names = (set(placed_v1) | set(placed_v2)
                 | overflow_v1_names | overflow_v2_names)

    diffs = []
    for name in sorted(all_names):
        v1_state = placed_v1.get(name, ('OVERFLOW', '-') if name in overflow_v1_names else ('?', '-'))
        v2_state = placed_v2.get(name, ('OVERFLOW', '-') if name in overflow_v2_names else ('?', '-'))
        if v1_state == v2_state:
            continue
        diffs.append({
            'name': name,
            'v1_level': v1_state[0],
            'v1_role': v1_state[1],
            'v2_level': v2_state[0],
            'v2_role': v2_state[1],
        })

    # Slot fill summary (target vs actual).
    def fill(rosters, role_key, target_key):
        rows = []
        for lvl, info in rosters.items():
            if isinstance(info, dict):
                rows.append((lvl, len(info.get(role_key, [])), info.get(target_key, 0)))
        return rows

    return {
        'org': org,
        'placed_v1': len(placed_v1),
        'placed_v2': len(placed_v2),
        'overflow_v1': len(overflow_v1_names),
        'overflow_v2': len(overflow_v2_names),
        'flagged_v1': len(flagged_v1),
        'flagged_v2': len(flagged_v2),
        'diffs': diffs,
        'fill_sp_v1': fill(rosters_v1, 'starters', 'sp_target'),
        'fill_sp_v2': fill(rosters_v2, 'starters', 'sp_target'),
        'fill_rp_v1': fill(rosters_v1, 'bullpen', 'rp_target'),
        'fill_rp_v2': fill(rosters_v2, 'bullpen', 'rp_target'),
        'rosters_v1': rosters_v1,
        'rosters_v2': rosters_v2,
    }


def _check_v2_invariants(org: str, result: dict) -> list[str]:
    """Targeted v2 correctness checks. Returns list of violation strings
    (empty means clean)."""
    import build_pitcher_system_v2 as v2
    violations = []
    rosters = result['rosters_v2']

    for lvl, info in rosters.items():
        if not isinstance(info, dict):
            continue
        sort_lvl = 'R(DLR)' if lvl.startswith('R(DLR)') else lvl

        # 1. No-inversion (modulo HP-first reservation): no NON-HP bullpen
        # sp_viable arm has better priority than the worst NON-HP starter.
        # HP starters claim slots first (by design), so an HP starter can
        # have worse priority than non-HP RP candidates — that's intended,
        # not a bug.
        starters = info.get('starters', [])
        bullpen = info.get('bullpen', [])
        non_hp_starters = [p for p in starters
                            if not v2.is_high_potential_pitcher(p)]
        if non_hp_starters:
            worst_starter = max(non_hp_starters,
                                key=lambda p: v2.pitcher_priority(p, sort_lvl))
            worst_starter_pri = v2.pitcher_priority(worst_starter, sort_lvl)
            for p in bullpen:
                if not v2.is_sp_viable(p):
                    continue
                if v2.is_high_potential_pitcher(p):
                    continue
                pri = v2.pitcher_priority(p, sort_lvl)
                if pri < worst_starter_pri:
                    violations.append(
                        f'{org} {lvl}: priority inversion — '
                        f'bullpen non-HP sp_viable {p["name"]} pri={pri:.4f} '
                        f'< worst non-HP starter {worst_starter["name"]} pri={worst_starter_pri:.4f}'
                    )

        # 2. HP MLB block.
        if lvl == 'MLB':
            for p in info.get('all', []):
                if v2.is_high_potential_pitcher(p) and p.get('_bot', 0) >= 1:
                    violations.append(
                        f'{org} MLB: HP at MLB despite _bot allowing AAA: {p["name"]}'
                    )

        # 3. LHP balance at LHP_LEVELS.
        from config import LHP_LEVELS, LEFTY_MIN, LEFTY_MAX
        if lvl in LHP_LEVELS:
            n_lhp = sum(1 for p in bullpen if v2.is_lhp(p))
            sign_lhp = info.get('sign_lhp', 0)
            target = info.get('rp_target', 0)
            # If bullpen is full, LHP count must be in [LEFTY_MIN, LEFTY_MAX]
            # or shortfall must explain the gap.
            if len(bullpen) == target:
                if n_lhp > LEFTY_MAX:
                    violations.append(
                        f'{org} {lvl}: LHP count {n_lhp} > LEFTY_MAX {LEFTY_MAX}'
                    )
                if n_lhp + sign_lhp < LEFTY_MIN:
                    violations.append(
                        f'{org} {lvl}: LHP count {n_lhp} + sign_lhp {sign_lhp} < LEFTY_MIN {LEFTY_MIN}'
                    )

        # 4. Capacity not exceeded.
        if len(starters) > info.get('sp_target', 0):
            violations.append(
                f'{org} {lvl}: SP over capacity: {len(starters)}/{info["sp_target"]}'
            )
        if len(bullpen) > info.get('rp_target', 0):
            violations.append(
                f'{org} {lvl}: RP over capacity: {len(bullpen)}/{info["rp_target"]}'
            )

    return violations


def _write_org_report(result: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / f'{result["org"]}.md'
    lines = [f'# {result["org"]} — v1 vs v2 placement diff', '']

    # Summary
    lines += [
        f'- Placed: v1={result["placed_v1"]}  v2={result["placed_v2"]}',
        f'- Overflow: v1={result["overflow_v1"]}  v2={result["overflow_v2"]}',
        f'- Flagged (injured): v1={result["flagged_v1"]}  v2={result["flagged_v2"]}',
        f'- Pitchers with different (level, role): **{len(result["diffs"])}**',
        '',
        '## Slot fill (v1 → v2)',
        '',
        '| Level | SP v1 | SP v2 | SP target | RP v1 | RP v2 | RP target |',
        '|---|---|---|---|---|---|---|',
    ]
    fill_v1 = {f[0]: f for f in result['fill_sp_v1']}
    fill_v2 = {f[0]: f for f in result['fill_sp_v2']}
    fill_rp_v1 = {f[0]: f for f in result['fill_rp_v1']}
    fill_rp_v2 = {f[0]: f for f in result['fill_rp_v2']}
    levels = sorted(set(fill_v1) | set(fill_v2))
    for lvl in levels:
        f1 = fill_v1.get(lvl, (lvl, 0, 0))
        f2 = fill_v2.get(lvl, (lvl, 0, 0))
        r1 = fill_rp_v1.get(lvl, (lvl, 0, 0))
        r2 = fill_rp_v2.get(lvl, (lvl, 0, 0))
        lines.append(f'| {lvl} | {f1[1]} | {f2[1]} | {f1[2]} | {r1[1]} | {r2[1]} | {r1[2]} |')

    # Per-arm diff
    if result['diffs']:
        lines += ['', '## Pitcher-level diff', '',
                  '| Name | v1 Level | v1 Role | v2 Level | v2 Role |',
                  '|---|---|---|---|---|']
        for d in result['diffs']:
            lines.append(
                f'| {d["name"]} | {d["v1_level"]} | {d["v1_role"]} '
                f'| {d["v2_level"]} | {d["v2_role"]} |'
            )

    p.write_text('\n'.join(lines), encoding='utf-8')
    return p


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--org', help='Single org abbreviation (e.g. CWS)')
    parser.add_argument('--csv-dir', help='OOTP CSV dir (refreshes pitchers.json first)')
    parser.add_argument('--no-reports', action='store_true',
                        help='Skip per-org markdown files (aggregate only)')
    args = parser.parse_args()

    _refresh_if_needed(args.csv_dir)

    orgs = [args.org] if args.org else _all_orgs()
    print(f'Comparing v1 vs v2 across {len(orgs)} org(s)...')

    summary_rows = []
    total_diffs = 0
    total_v2_violations = 0
    all_violations: list[str] = []

    for org in orgs:
        try:
            result = _diff_org(org)
        except Exception as e:
            print(f'  {org}: ERROR — {e}')
            continue

        violations = _check_v2_invariants(org, result)
        all_violations.extend(violations)

        if not args.no_reports:
            _write_org_report(result)

        summary_rows.append({
            'org': org,
            'diffs': len(result['diffs']),
            'overflow_delta': result['overflow_v2'] - result['overflow_v1'],
            'violations': len(violations),
        })
        total_diffs += len(result['diffs'])
        total_v2_violations += len(violations)

    # Aggregate summary
    print()
    print(f'{"Org":6}  {"Moves":>6}  {"Δoverflow":>10}  {"v2 inv":>7}')
    print('-' * 36)
    for row in sorted(summary_rows, key=lambda r: -r['diffs']):
        print(f'{row["org"]:6}  {row["diffs"]:>6}  {row["overflow_delta"]:>+10}  {row["violations"]:>7}')
    print('-' * 36)
    print(f'TOTAL  {total_diffs:>6}                {total_v2_violations:>7}')
    print()

    if all_violations:
        print('v2 invariant violations:')
        for v in all_violations[:50]:
            print(f'  - {v}')
        if len(all_violations) > 50:
            print(f'  ... and {len(all_violations) - 50} more')
    else:
        print('v2 invariants: all clean.')

    if not args.no_reports and not args.org:
        print(f'\nPer-org reports written to {OUT_DIR}/<ORG>.md')


if __name__ == '__main__':
    main()
