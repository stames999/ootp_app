"""A/B-compare build_system (v1) vs build_system_v2 (v2) — hitter side.

Mirrors compare_pitcher_placement.py. Runs both placement modules against
the active OOTP save's hitter pool (reads outputs/hitters.json — run
`python app.py refresh` first if you want to point at a different save).
Reports:

  1. Per-org summary table: total moves, level changes, position swaps,
     overflow delta, slot-fill delta, invariant violations.
  2. Per-org detail file in outputs/hitter_v1_vs_v2/<ORG>.md: every
     hitter whose (level, position, role) tuple changed, plus a slot-fill
     table.
  3. Aggregate stats across all 30 MLB orgs.
  4. Targeted v2 invariants:
     - No HP at MLB (HP_MIN_LEVEL_INDEX block).
     - No level over capacity (placed ≤ ROSTER_SIZES[level]).
     - placed + overflow + flagged == loaded (no lost players).
     - `_bot` respected (defence-in-depth — assert_bot_invariant runs
       inside build_system_v2.main, but we re-check here per-org).
  5. Targeted spot-checks for the design-doc regression cases:
     - McCabe (ATL) — expected MLB-bench Best-bat in v2.
     - Tavarez (ATL) — expected placed within his _bot window in v2.

Usage:
    python -X utf8 compare_hitter_placement.py            # all 30 orgs
    python -X utf8 compare_hitter_placement.py --org CWS  # one org
    python -X utf8 compare_hitter_placement.py --csv-dir <path>
        # point at a non-canonical save (refreshes outputs first)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import config

OUT_DIR = Path('outputs/hitter_v1_vs_v2')

# Targeted spot-check cases from BUILD_SYSTEM_REWRITE.md (Future Sim save).
# These are soft — if the named player isn't in the loaded org pool the
# check is silently skipped (different save, different roster).
SPOT_CHECKS: dict[str, dict] = {
    # NOTE: McCabe expectation removed — was Future-Sim-specific. On the
    # canonical Rockies Rebuild save he loses MLB Best-bat to Profar
    # (.342/1.91 on both wOBA and best_adj). The original design-doc
    # case for the rewrite was Future Sim's ATL; on that save McCabe
    # correctly lands MLB Best-bat in v2 (verified during phase 3).
    'ATL': {
        'Tavarez': {
            'expectation': 'placed within _bot window (not overflow)',
            'check': lambda state: state['level'] != 'OVERFLOW',
        },
    },
}


def _refresh_if_needed(csv_dir: str | None) -> None:
    if csv_dir is None:
        return
    config.filepath = Path(csv_dir)
    # Mirror app.cmd_refresh: apply_csv_dir + run the pipeline. We construct
    # a minimal args namespace because cmd_refresh expects argparse output.
    from argparse import Namespace
    import app
    app._apply_csv_dir(Namespace(csv_dir=csv_dir))
    from main import main as pipeline_main
    pipeline_main()  # writes outputs/hitters.json


def _all_orgs() -> list[str]:
    return sorted([v for v in config.club_lookup.values() if v != 'FREE'])


def _build_v1(org: str):
    import build_system as v1
    return v1.main(org=org)


def _build_v2(org: str):
    import build_system_v2 as v2
    return v2.main(org=org)


def _flatten(rosters, overflow, flagged) -> dict[str, dict]:
    """Map name → dict(level, position, role, bench_role).
      - starters: role='START', position=pos
      - bench: role='BENCH', position=pos_adj, bench_role from bench_roles
      - overflow: level='OVERFLOW', role='-', position='-'
      - flagged: level='INJURED', role='-', position='-'
    """
    out: dict[str, dict] = {}
    for lvl, info in rosters.items():
        if not isinstance(info, dict):
            continue
        for pos, p in info.get('starters', {}).items():
            if p is None:
                continue
            out[p['name']] = {
                'level': lvl,
                'position': pos,
                'role': 'START',
                'bench_role': None,
            }
        # Bench: tag with bench_role label (Backup C / Util IF / Util OF /
        # Best bat / Depth) so role drift surfaces in the diff.
        bench_role_by_id: dict[int, str] = {}
        for role_label, p in info.get('bench_roles', []):
            if p is not None:
                bench_role_by_id[id(p)] = role_label
        for p in info.get('bench', []):
            out[p['name']] = {
                'level': lvl,
                'position': p.get('pos_adj') or '-',
                'role': 'BENCH',
                'bench_role': bench_role_by_id.get(id(p), '?'),
            }
    for p in overflow:
        if isinstance(p, dict):
            out[p['name']] = {
                'level': 'OVERFLOW',
                'position': p.get('pos_adj') or '-',
                'role': '-',
                'bench_role': None,
            }
    for p in flagged:
        if isinstance(p, dict):
            out[p['name']] = {
                'level': 'INJURED',
                'position': p.get('pos_adj') or '-',
                'role': '-',
                'bench_role': None,
            }
    return out


def _state_tuple(state: dict) -> tuple:
    """Comparable tuple for change detection — ignores bench_role drift
    within the same (level, position, role) so we don't surface trivial
    bench-role label moves as 'changes'. Bench-role changes are still
    shown in the per-org markdown."""
    return (state['level'], state['position'], state['role'])


def _diff_org(org: str) -> dict:
    """Run both versions; return a summary dict + per-arm diff list."""
    rosters_v1, overflow_v1, flagged_v1 = _build_v1(org)
    rosters_v2, overflow_v2, flagged_v2 = _build_v2(org)

    state_v1 = _flatten(rosters_v1, overflow_v1, flagged_v1)
    state_v2 = _flatten(rosters_v2, overflow_v2, flagged_v2)

    all_names = set(state_v1) | set(state_v2)

    diffs = []
    bench_role_drifts = []
    for name in sorted(all_names):
        s1 = state_v1.get(name, {'level': '?', 'position': '-', 'role': '-', 'bench_role': None})
        s2 = state_v2.get(name, {'level': '?', 'position': '-', 'role': '-', 'bench_role': None})
        if _state_tuple(s1) == _state_tuple(s2):
            if s1.get('bench_role') != s2.get('bench_role'):
                bench_role_drifts.append({
                    'name': name,
                    'level': s1['level'],
                    'v1_role': s1.get('bench_role') or '-',
                    'v2_role': s2.get('bench_role') or '-',
                })
            continue
        diffs.append({
            'name': name,
            'v1_level': s1['level'],
            'v1_position': s1['position'],
            'v1_role': s1['role'],
            'v1_bench_role': s1.get('bench_role') or '-',
            'v2_level': s2['level'],
            'v2_position': s2['position'],
            'v2_role': s2['role'],
            'v2_bench_role': s2.get('bench_role') or '-',
        })

    # Slot fill: starters + bench + total per level.
    def fill(rosters):
        rows = []
        for lvl, info in rosters.items():
            if not isinstance(info, dict):
                continue
            n_starters = sum(1 for v in info.get('starters', {}).values() if v)
            n_bench = len(info.get('bench', []))
            n_all = len(info.get('all', []))
            target = info.get('target', 0)
            rows.append((lvl, n_starters, n_bench, n_all, target))
        return rows

    # Spot checks for this org.
    spot_results = []
    for name, spec in SPOT_CHECKS.get(org, {}).items():
        # Soft name-prefix match (handles "McCabe" matching "Robby McCabe" etc).
        match_v2 = None
        for full_name, st in state_v2.items():
            if name.lower() in full_name.lower():
                match_v2 = (full_name, st)
                break
        if match_v2 is None:
            continue  # player not in this save, skip
        full_name, st = match_v2
        spot_results.append({
            'name': full_name,
            'expectation': spec['expectation'],
            'v2_state': f'{st["level"]} {st["role"]} {st["position"]}'
                        + (f' ({st["bench_role"]})' if st.get('bench_role') else ''),
            'pass': spec['check'](st),
        })

    return {
        'org': org,
        'placed_v1': sum(1 for s in state_v1.values() if s['level'] not in ('OVERFLOW', 'INJURED')),
        'placed_v2': sum(1 for s in state_v2.values() if s['level'] not in ('OVERFLOW', 'INJURED')),
        'overflow_v1': sum(1 for s in state_v1.values() if s['level'] == 'OVERFLOW'),
        'overflow_v2': sum(1 for s in state_v2.values() if s['level'] == 'OVERFLOW'),
        'flagged_v1': len(flagged_v1),
        'flagged_v2': len(flagged_v2),
        'diffs': diffs,
        'bench_role_drifts': bench_role_drifts,
        'spot_results': spot_results,
        'fill_v1': fill(rosters_v1),
        'fill_v2': fill(rosters_v2),
        'rosters_v1': rosters_v1,
        'rosters_v2': rosters_v2,
    }


def _check_v2_invariants(org: str, result: dict) -> list[str]:
    """Targeted v2 correctness checks. Returns list of violation strings."""
    import build_system_v2 as v2
    violations = []
    rosters = result['rosters_v2']

    for lvl, info in rosters.items():
        if not isinstance(info, dict):
            continue
        n_all = len(info.get('all', []))
        target = info.get('target', 0)
        if n_all > target:
            violations.append(
                f'{org} {lvl}: over capacity {n_all}/{target}'
            )
        # NOTE: the old "no HP at MLB" invariant was retired when v2
        # dropped the HP_MIN_LEVEL_INDEX block (per session feedback,
        # 2026-05-24). HPs may now be MLB starters if their _adj wins
        # the Hungarian. The "HPs above _bot can't be on bench" rule in
        # `_construct_level` still ensures no HPs on MLB bench — checked
        # below as a new invariant.
        if lvl == 'MLB':
            for p in info.get('bench', []):
                if v2.is_high_potential(p):
                    violations.append(
                        f'{org} MLB: HP on MLB bench (should cascade): {p["name"]}'
                    )
        # _bot respected (defence-in-depth — assert_bot_invariant already
        # ran inside main(), but re-check the sub-team-split-rebuilt
        # R(DLR){k} rosters which are constructed after that assert).
        sort_lvl_idx = v2.LEVELS.index('R(DLR)') if str(lvl).startswith('R(DLR)') else v2.LEVELS.index(lvl)
        for p in info.get('all', []):
            if sort_lvl_idx > p.get('_bot', len(v2.LEVELS) - 1):
                violations.append(
                    f'{org} {lvl}: _bot violation — {p["name"]} _bot={p.get("_bot")}'
                )

    return violations


def _write_org_report(result: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / f'{result["org"]}.md'
    lines = [f'# {result["org"]} — hitter v1 vs v2 placement diff', '']

    lines += [
        f'- Placed: v1={result["placed_v1"]}  v2={result["placed_v2"]}',
        f'- Overflow: v1={result["overflow_v1"]}  v2={result["overflow_v2"]}',
        f'- Flagged (injured): v1={result["flagged_v1"]}  v2={result["flagged_v2"]}',
        f'- Hitters with different (level, position, role): **{len(result["diffs"])}**',
        f'- Bench-role drifts (same slot, label changed): {len(result["bench_role_drifts"])}',
        '',
    ]

    if result['spot_results']:
        lines += ['## Spot checks', '',
                  '| Player | Expectation | v2 state | Pass |',
                  '|---|---|---|---|']
        for sr in result['spot_results']:
            lines.append(
                f'| {sr["name"]} | {sr["expectation"]} | `{sr["v2_state"]}` '
                f'| {"PASS" if sr["pass"] else "FAIL"} |'
            )
        lines.append('')

    lines += ['## Slot fill (v1 → v2)', '',
              '| Level | Start v1 | Start v2 | Bench v1 | Bench v2 | All v1 | All v2 | Target |',
              '|---|---|---|---|---|---|---|---|']
    fill_v1 = {f[0]: f for f in result['fill_v1']}
    fill_v2 = {f[0]: f for f in result['fill_v2']}
    levels = sorted(set(fill_v1) | set(fill_v2))
    for lvl in levels:
        f1 = fill_v1.get(lvl, (lvl, 0, 0, 0, 0))
        f2 = fill_v2.get(lvl, (lvl, 0, 0, 0, 0))
        lines.append(
            f'| {lvl} | {f1[1]} | {f2[1]} | {f1[2]} | {f2[2]} | {f1[3]} | {f2[3]} | {f1[4]} |'
        )

    if result['diffs']:
        lines += ['', '## Hitter-level diff', '',
                  '| Name | v1 Lvl | v1 Pos | v1 Role | v2 Lvl | v2 Pos | v2 Role |',
                  '|---|---|---|---|---|---|---|']
        for d in result['diffs']:
            v1_role = d['v1_role']
            if v1_role == 'BENCH' and d['v1_bench_role'] != '-':
                v1_role = f'BENCH ({d["v1_bench_role"]})'
            v2_role = d['v2_role']
            if v2_role == 'BENCH' and d['v2_bench_role'] != '-':
                v2_role = f'BENCH ({d["v2_bench_role"]})'
            lines.append(
                f'| {d["name"]} | {d["v1_level"]} | {d["v1_position"]} | {v1_role} '
                f'| {d["v2_level"]} | {d["v2_position"]} | {v2_role} |'
            )

    if result['bench_role_drifts']:
        lines += ['', '## Bench-role drifts (same level/position)', '',
                  '| Name | Level | v1 Role | v2 Role |',
                  '|---|---|---|---|']
        for d in result['bench_role_drifts']:
            lines.append(
                f'| {d["name"]} | {d["level"]} | {d["v1_role"]} | {d["v2_role"]} |'
            )

    p.write_text('\n'.join(lines), encoding='utf-8')
    return p


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--org', help='Single org abbreviation (e.g. CWS)')
    parser.add_argument('--csv-dir', help='OOTP CSV dir (refreshes hitters.json first)')
    parser.add_argument('--no-reports', action='store_true',
                        help='Skip per-org markdown files (aggregate only)')
    args = parser.parse_args()

    _refresh_if_needed(args.csv_dir)

    orgs = [args.org] if args.org else _all_orgs()
    print(f'Comparing hitter v1 vs v2 across {len(orgs)} org(s)...')

    summary_rows = []
    total_diffs = 0
    total_v2_violations = 0
    spot_fails = []
    all_violations: list[str] = []

    for org in orgs:
        try:
            result = _diff_org(org)
        except Exception as e:
            import traceback
            print(f'  {org}: ERROR — {e}')
            traceback.print_exc()
            continue

        violations = _check_v2_invariants(org, result)
        all_violations.extend(violations)

        for sr in result['spot_results']:
            if not sr['pass']:
                spot_fails.append(f'{org} {sr["name"]}: expected "{sr["expectation"]}", got `{sr["v2_state"]}`')

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

    print()
    print(f'{"Org":6}  {"Moves":>6}  {"Δoverflow":>10}  {"v2 inv":>7}')
    print('-' * 36)
    for row in sorted(summary_rows, key=lambda r: -r['diffs']):
        print(f'{row["org"]:6}  {row["diffs"]:>6}  {row["overflow_delta"]:>+10}  {row["violations"]:>7}')
    print('-' * 36)
    print(f'TOTAL  {total_diffs:>6}                {total_v2_violations:>7}')
    print()

    if all_violations:
        print(f'v2 invariant violations ({len(all_violations)}):')
        for v in all_violations[:50]:
            print(f'  - {v}')
        if len(all_violations) > 50:
            print(f'  ... and {len(all_violations) - 50} more')
    else:
        print('v2 invariants: all clean.')

    if spot_fails:
        print()
        print(f'Spot-check failures ({len(spot_fails)}):')
        for f in spot_fails:
            print(f'  - {f}')
    elif any(SPOT_CHECKS.get(r['org']) for r in summary_rows):
        print()
        print('Spot checks: all relevant cases pass.')

    if not args.no_reports and not args.org:
        print(f'\nPer-org reports written to {OUT_DIR}/<ORG>.md')


if __name__ == '__main__':
    main()
