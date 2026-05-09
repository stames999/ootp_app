"""Pistachio CLI — single entry point for the OOTP roster-construction app.

Subcommands:
  refresh [--csv-dir PATH]     Rerun the upstream metrics pipeline against the
                               OOTP CSVs. Regenerates outputs/hitters.json,
                               outputs/pitchers.json, and the HTML/JSON pages.
                               --csv-dir overrides config.filepath; defaults to
                               config.filepath if not given.
  rosters [--team ABBR]        Build outputs/{team}_roster_system.xlsx from the
                               cached hitters.json + pitchers.json. The xlsx
                               includes batting order + R/G estimate per
                               platoon lineup (migrated from the old org-report).
                               Defaults to config.team_managed.
  all [--csv-dir PATH] [--team ABBR]
                               refresh -> rosters, in that order.

Examples:
  python app.py refresh
  python app.py refresh --csv-dir D:/ootp_export
  python app.py rosters --team NYY
  python app.py all --team LAD
"""
import argparse
from pathlib import Path


def _apply_csv_dir(args):
    """Override config.filepath if --csv-dir was given, then auto-detect the
    save's head-scout coach_id and apply it to config.ID. Auto-detect runs
    unconditionally (with or without --csv-dir) — the repo default for
    config.ID matches the LAA save the repo shipped with, and silently
    diverges for any other save. Auto-detect catches that drift before the
    pipeline filters every player's ratings to NaN."""
    import config
    if getattr(args, 'csv_dir', None):
        config.filepath = Path(args.csv_dir)
    from reader import detect_head_scout_id
    detected = detect_head_scout_id(config.filepath)
    if detected is not None and detected != config.ID:
        config.ID = detected
        print(f'Using head-scout coach_id {detected} (auto-detected).')


def cmd_refresh(args):
    _apply_csv_dir(args)
    from main import main as pipeline_main
    pipeline_main()


def cmd_rosters(args):
    from build_excel import main_build
    main_build(org=args.team)


def cmd_all(args):
    cmd_refresh(args)
    cmd_rosters(args)


def build_parser():
    p = argparse.ArgumentParser(prog='app', description='Pistachio OOTP roster-construction CLI.')
    sub = p.add_subparsers(dest='cmd', required=True)

    pre = sub.add_parser('refresh', help='Rerun the upstream metrics pipeline.')
    pre.add_argument('--csv-dir', default=None, help='Path to the OOTP CSV export dir (default: config.filepath).')
    pre.set_defaults(func=cmd_refresh)

    pr = sub.add_parser('rosters', help='Build the team roster xlsx.')
    pr.add_argument('--team', default=None, help='Org abbreviation (default: config.team_managed).')
    pr.set_defaults(func=cmd_rosters)

    pa = sub.add_parser('all', help='refresh -> rosters.')
    pa.add_argument('--csv-dir', default=None, help='Path to the OOTP CSV export dir (default: config.filepath).')
    pa.add_argument('--team', default=None, help='Org abbreviation (default: config.team_managed).')
    pa.set_defaults(func=cmd_all)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main()
