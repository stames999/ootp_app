"""Pistachio CLI — single entry point for the OOTP roster-construction app.

Subcommands:
  refresh                      Rerun the upstream metrics pipeline. Regenerates
                               outputs/hitters.json, outputs/pitchers.json, the
                               HTML/JSON pages, and the default org-report.
  rosters [--team ABBR]        Build outputs/{team}_roster_system.xlsx from the
                               cached hitters.json + pitchers.json. Defaults to
                               config.team_managed.
  org-report [--team ABBR]     Run exporter.export_org_report for the given
                               team. Re-computes the df via main.compute_df()
                               since the org-report needs the in-memory frame.
  all [--team ABBR]            refresh -> rosters -> org-report, in that order.

Examples:
  python app.py refresh
  python app.py rosters --team NYY
  python app.py org-report --team LAD
  python app.py all
"""
import argparse
import sys


def cmd_refresh(args):
    from main import main as pipeline_main
    pipeline_main()


def cmd_rosters(args):
    from build_excel import main_build
    main_build(org=args.team)


def cmd_org_report(args):
    from main import compute_df
    from exporter import export_org_report
    df = compute_df()
    export_org_report(df, org_abbr=args.team)


def cmd_all(args):
    cmd_refresh(args)
    cmd_rosters(args)
    cmd_org_report(args)


def build_parser():
    p = argparse.ArgumentParser(prog='app', description='Pistachio OOTP roster-construction CLI.')
    sub = p.add_subparsers(dest='cmd', required=True)

    sub.add_parser('refresh', help='Rerun the upstream metrics pipeline.').set_defaults(func=cmd_refresh)

    pr = sub.add_parser('rosters', help='Build the team roster xlsx.')
    pr.add_argument('--team', default=None, help='Org abbreviation (default: config.team_managed).')
    pr.set_defaults(func=cmd_rosters)

    po = sub.add_parser('org-report', help='Build the team org-report HTML.')
    po.add_argument('--team', default=None, help='Org abbreviation (default: config.team_managed).')
    po.set_defaults(func=cmd_org_report)

    pa = sub.add_parser('all', help='refresh -> rosters -> org-report.')
    pa.add_argument('--team', default=None, help='Org abbreviation (default: config.team_managed).')
    pa.set_defaults(func=cmd_all)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main()
