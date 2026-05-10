from typing import Optional

import pandas as pd

from config import COLUMNS_TO_BLANK_BEFORE_EXPORT, export_filepath


def export_advanced_html(
    df, filename, columns, title="Data Table", row_filter=None, page_len=100
):
    """
    Export df[columns] to an HTML file with DataTables (using the searchbuilder extension).
    """
    working_df = df.copy()
    if row_filter is not None:
        working_df = working_df[row_filter].copy()

    working_df = working_df[columns]

    # Clean NaN values in configured columns for proper HTML sorting
    clean_cols = [c for c in COLUMNS_TO_BLANK_BEFORE_EXPORT if c in working_df.columns]
    working_df[clean_cols] = working_df[clean_cols].fillna("")

    # Define a safe formatter that leaves non-numeric values unchanged and
    # renders NaN as blank (not the literal "nan" — which "{:.1f}".format
    # produces for float('nan') without raising).
    def safe_format(fmt_func):
        def wrapped(val):
            try:
                if pd.isna(val):
                    return ""
            except (TypeError, ValueError):
                pass
            try:
                return fmt_func(val)
            except Exception:
                return val

        return wrapped

    # Apply baseball-style formatting
    fmt = {}
    for col in working_df.columns:
        if col in (
            "best",
            "bestP",
            "war_hitting",
            "sp_war",
            "rp_war",
            "sp_warP",
            "rp_warP",
            "DH",
            "C",
            "CF",
            "RF",
            "LF",
            "SS",
            "2B",
            "3B",
            "1B",
            "DHP",
            "1BP",
            "2BP",
            "3BP",
            "SSP",
            "LFP",
            "CFP",
            "RFP",
            "CP",
            "best_adj",
            "bestP_adj",
        ):
            fmt[col] = safe_format("{:.1f}".format)
        elif col.endswith("_def"):
            fmt[col] = safe_format("{:.1f}".format)
        elif col.endswith("_adj"):
            fmt[col] = safe_format("{:.1f}".format)
        elif col.endswith("_fld"):
            fmt[col] = safe_format("{:.1f}".format)
        elif col in ("war_hitting", "war_hittingP", "DH_hitting", "DH_hittingP"):
            fmt[col] = safe_format("{:.1f}".format)
        elif "wOBA" in col:
            fmt[col] = safe_format("{:.3f}".format)
        elif col in ("pWOBA", "pWOBAR", "pWOBAL"):
            fmt[col] = safe_format("{:.3f}".format)
        elif "wRC+" in col:
            fmt[col] = safe_format("{:.0f}".format)

    # na_rep="" catches any NaN cell (including columns without an explicit
    # formatter, e.g. `org` for free agents) so nothing renders as "nan".
    styled = working_df.style.format(fmt, na_rep="")
    html_table = styled.to_html(index=False, escape=False)
    # Ensure the table has the id DataTables expects:
    html_table = html_table.replace("<table ", '<table id="data" ', 1)

    full = HTML_DARK_TEMPLATE.format(title=title, table=html_table, page_len=page_len)
    path = export_filepath / filename
    with open(path, "w", encoding="utf-8") as f:
        f.write(full)
    print(f"✅ Exported {title} → {path}")


def export_hitters(df):
    """
    Wrapper to export the hitters page.
    """
    cols = [
        "name",
        "org",
        "age",
        "pa",
        "best",
        "pos",
        "wRC+",
        "wOBA",
        "wOBAR",
        "wOBAL",
        "DH",
        "C",
        "CF",
        "RF",
        "LF",
        "SS",
        "2B",
        "3B",
        "1B",
        "wOBAP",
        "flag",
    ]
    filt = df["wOBA"] > 0.270
    export_advanced_html(
        df,
        filename="hitters.html",
        columns=cols,
        title="Hitters",
        row_filter=filt,
        page_len=100,
    )


EXPORT_PAGES = [
    {
        "filename": "hitters.html",
        "title": "Hitters",
        "columns": [
            # player_id is included so downstream code (build_system,
            # tests) can match players unambiguously rather than by
            # name string — name collisions across orgs (e.g. multiple
            # "Jose Rodriguez") otherwise cause cross-org confusion.
            "player_id",
            # Two-way detection (position==1 with meaningful potential
            # batting). Both builders see two-way players; tw_target_lvl
            # is the better-of-two-skills level ceiling that pins them
            # to the same level on both sides.
            "is_two_way",
            "tw_target_lvl",
            "position",
            "name",
            "org",
            "minor",
            "age",
            "pa",
            "best_adj",
            "bestP_adj",
            "pos_adj",
            "best",
            "bestP",
            "pos",
            "field",
            "wRC+",
            "wOBA",
            "wOBAR",
            "wOBAL",
            "wOBAP",
            # Bat-only WAR (additive with any *_fld below to compose totals)
            "war_hitting",
            "war_hittingP",
            "DH_hitting",
            # Fielding-only WAR per position (with scarcity adjustment baked in).
            # Same value for current and potential — fielding ratings are static.
            "1B_fld",
            "2B_fld",
            "3B_fld",
            "SS_fld",
            "LF_fld",
            "CF_fld",
            "RF_fld",
            "C_fld",
            # Combined per-position totals (bat + fld). Kept for ranking convenience.
            "DH",
            "1B",
            "2B",
            "3B",
            "SS",
            "LF",
            "CF",
            "RF",
            "C",
            # Scarcity-adjusted counterparts (1B is anchor → 1B_adj == 1B)
            "DH_adj",
            "1B_adj",
            "2B_adj",
            "3B_adj",
            "SS_adj",
            "LF_adj",
            "CF_adj",
            "RF_adj",
            "C_adj",
            # Service-time: years played at each level (derived from
            # career-stats CSVs; zeroed if those aren't uploaded).
            "yrs_MLB",
            "yrs_AAA",
            "yrs_AA",
            "yrs_A+",
            "yrs_A",
            "yrs_R",
            "yrs_R(DLR)",
            # Nationality — used by build_system to block US (206) / Canadian (36)
            # players from R(DLR) per OOTP DSL eligibility rules.
            "nation_id",
            "flag",
        ],
        # Include any non-pitcher with a computed wOBAP (regardless of
        # value). The previous `> 0.200` cutoff hid deep-R / R(DLR)
        # projects whose scouted ratings produce a sub-replacement wOBAP
        # — e.g. Robert Lantigua (AZ ACL, age 18, ratings 25-30 → wOBAP
        # 0.185). The `position != 1` gate keeps regular pitchers out;
        # two-way players (position == 1 AND is_two_way) are admitted
        # since they need to appear in both hitter and pitcher pools.
        "filter": lambda df: ((df["position"] != 1) | df.get("is_two_way", False)) & df["wOBAP"].notna(),
        "page_len": 100,
    },
    {
        "filename": "pitchers.html",
        "title": "Pitchers",
        "columns": [
            "player_id",  # see hitters page for rationale
            "is_two_way",
            "tw_target_lvl",
            "position",
            "name",
            "org",
            "minor",
            "age",
            "throws",
            "ip",
            "sp_war",
            "rp_war",
            "pwOBA",
            "pwOBAR",
            "pwOBAL",
            "sp_warP",
            "rp_warP",
            "pwOBAP",
            # Service-time: years at each level (career-stats derivation)
            "yrs_MLB",
            "yrs_AAA",
            "yrs_AA",
            "yrs_A+",
            "yrs_A",
            "yrs_R",
            "yrs_R(DLR)",
            # Nationality — see hitters.html columns above for rationale.
            "nation_id",
            "flag",
        ],
        # Same shape as the hitter filter — include any pitcher with
        # a computed pwOBAP. The old `< 1.000` cutoff was effectively
        # the same as notna() since pwOBAP tops out around 0.5 even for
        # the worst arms, but explicit notna is clearer about intent.
        "filter": lambda df: df["pwOBAP"].notna(),
        "page_len": 100,
    },
    {
        "filename": "hit_prospects.html",
        "title": "Hitter prospects",
        "columns": [
            "player_id",  # see hitters page for rationale
            "name",
            "org",
            "minor",
            "age",
            "pa",
            "bestP_adj",
            "posP_adj",
            "best",
            "bestP",
            "posP",
            "field",
            "wOBA",
            "wOBAR",
            "wOBAL",
            "wOBAP",
            # Bat-only potential WAR
            "war_hittingP",
            "DH_hittingP",
            # Fielding-only WAR per position (same as current — fielding static)
            "1B_fld",
            "2B_fld",
            "3B_fld",
            "SS_fld",
            "LF_fld",
            "CF_fld",
            "RF_fld",
            "C_fld",
            # Combined potential per-position totals (bat_potential + fld)
            "DHP",
            "1BP",
            "2BP",
            "3BP",
            "SSP",
            "LFP",
            "CFP",
            "RFP",
            "CP",
            # Scarcity-adjusted counterparts
            "DHP_adj",
            "1BP_adj",
            "2BP_adj",
            "3BP_adj",
            "SSP_adj",
            "LFP_adj",
            "CFP_adj",
            "RFP_adj",
            "CP_adj",
            "Cfram",
            "flag",
        ],
        # Include any non-pitcher with a computed wOBAP (regardless of
        # value). The previous `> 0.200` cutoff hid deep-R / R(DLR)
        # projects whose scouted ratings produce a sub-replacement wOBAP
        # — e.g. Robert Lantigua (AZ ACL, age 18, ratings 25-30 → wOBAP
        # 0.185). The `position != 1` gate keeps regular pitchers out;
        # two-way players (position == 1 AND is_two_way) are admitted
        # since they need to appear in both hitter and pitcher pools.
        "filter": lambda df: ((df["position"] != 1) | df.get("is_two_way", False)) & df["wOBAP"].notna(),
        "page_len": 100,
    },
    # More pages can be added here
]


def export_html_pages(df):
    """
    Export multiple pages using the EXPORT_PAGES definitions.
    """
    for page in EXPORT_PAGES:
        filt = page["filter"](df) if page.get("filter") else None
        export_advanced_html(
            df=df,
            filename=page["filename"],
            columns=page["columns"],
            title=page["title"],
            row_filter=filt,
            page_len=page.get("page_len", 100),
        )


def export_json_pages(df):
    """
    Mirror of export_html_pages that writes the same per-page slices as JSON.

    Each EXPORT_PAGES entry produces a sibling file with the .json extension
    (e.g. hitters.html → hitters.json). The JSON shape is:

        {
            "title": "Hitters",
            "n_rows": 245,
            "columns": [...column order...],
            "rows": [ {col: value, ...}, ... ]
        }

    Designed for downstream programmatic analysis (e.g. feeding to Claude)
    rather than for human reading. NaN values become null. Numeric columns
    keep full precision (no rounding to display format) so an analyst can
    do their own aggregations without re-deriving values.
    """
    import json

    for page in EXPORT_PAGES:
        working = df.copy()
        try:
            filt = page["filter"](working) if page.get("filter") else None
        except KeyError as e:
            print(f"Skipping {page['title']} JSON — filter references missing column {e}")
            continue
        if filt is not None:
            working = working[filt].copy()

        cols_present = [c for c in page["columns"] if c in working.columns]
        working = working[cols_present]

        # Convert NaN → None so JSON serializes them as null. Build the dict
        # manually rather than using df.to_json so we can wrap with metadata.
        rows = []
        for _, row in working.iterrows():
            record = {}
            for c in cols_present:
                v = row[c]
                if pd.isna(v):
                    record[c] = None
                elif hasattr(v, "item"):  # numpy scalars → native Python
                    record[c] = v.item()
                else:
                    record[c] = v
            rows.append(record)

        payload = {
            "title": page["title"],
            "n_rows": len(rows),
            "columns": cols_present,
            "rows": rows,
        }

        out_name = page["filename"].rsplit(".", 1)[0] + ".json"
        path = export_filepath / out_name
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        print(f"Exported {page['title']} → {path} ({len(rows)} rows)")


# ------------------------------------------------------------------
# Organization report export (multi-table HTML)
# ------------------------------------------------------------------


def _safe_format(fmt_func):
    def wrapped(val):
        try:
            return fmt_func(val)
        except Exception:
            return val

    return wrapped


def _pct_formatter(val):
    try:
        if pd.isna(val):
            return ""
        return f"{float(val) * 100:.1f}%"
    except Exception:
        return val


def _df_to_report_table(df: pd.DataFrame, table_id: str) -> str:
    """
    Convert a dataframe to an HTML table for the org report page.
    """
    working_df = df.copy()

    # Define formatters
    fmt = {}
    for col in working_df.columns:
        if (
            col in ("pos_WAR", "sp_war", "rp_war")
            or col.endswith("_war")
            or col.endswith("_WAR")
        ):
            fmt[col] = _safe_format("{:.1f}".format)
        elif col in ("wOBA", "wOBA_vs", "pwOBA", "pwOBAR", "pwOBAL", "wOBAR", "wOBAL"):
            fmt[col] = _safe_format("{:.3f}".format)
        elif col in ("wRC+", "wRC+_vs"):
            fmt[col] = _safe_format("{:.0f}".format)
        elif col in ("BB%", "HR%", "K%"):
            fmt[col] = _pct_formatter
        elif col in ("age", "pa", "ip", "minor", "slot"):
            fmt[col] = _safe_format("{:.0f}".format)

    # na_rep="" catches any NaN cell (including columns without an explicit
    # formatter, e.g. `org` for free agents) so nothing renders as "nan".
    styled = working_df.style.format(fmt, na_rep="")
    html_table = styled.to_html(index=False, escape=False)
    html_table = html_table.replace(
        "<table ", f'<table id="{table_id}" class="report-table" ', 1
    )
    return html_table


HTML_ORG_REPORT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>{title}</title>

  <!-- DataTables core -->
  <link rel="stylesheet" href="https://cdn.datatables.net/1.13.4/css/jquery.dataTables.min.css"/>
  <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap" rel="stylesheet"/>

  <script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
  <script src="https://cdn.datatables.net/1.13.4/js/jquery.dataTables.min.js"></script>

  <style>
    body {{
      background:#1c1c1c;
      color:#e0e0e0;
      margin:0;
      padding:1.25rem;
      font-family: 'Roboto', sans-serif;
    }}

    h1 {{
      margin: 0 0 0.5rem 0;
      font-size: 1.4rem;
      font-weight: 600;
    }}

    .sub {{
      margin: 0 0 1.25rem 0;
      font-size: 0.9rem;
      opacity: 0.85;
    }}

    .section {{
      margin: 1.25rem 0 2rem 0;
      padding-top: 0.5rem;
      border-top: 1px solid rgba(255,255,255,0.08);
    }}

    .section h2 {{
      margin: 0 0 0.75rem 0;
      font-size: 1.05rem;
      font-weight: 500;
    }}

    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 0.75rem;
      margin: 0.75rem 0 1rem 0;
    }}

    .card {{
      background: #262626;
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 10px;
      padding: 0.75rem 0.9rem;
    }}

    .card .k {{
      font-size: 0.8rem;
      opacity: 0.8;
      margin-bottom: 0.25rem;
    }}

    .card .v {{
      font-size: 1.1rem;
      font-weight: 600;
    }}

    table.dataTable {{
      background:#1c1c1c;
      color:#e0e0e0;
      font-size:0.82rem;
    }}

    table.dataTable thead th {{
      background:#2f2f2f;
      color:#e0e0e0;
    }}

    table.dataTable tbody tr:nth-child(odd)  {{ background:#262626; }}
    table.dataTable tbody tr:nth-child(even) {{ background:#1e1e1e; }}
    table.dataTable tbody tr:hover {{ background: rgba(255,255,255,0.05); }}

    /* remove the "Show X entries" / search bar for small report tables */
    div.dataTables_length, div.dataTables_filter, div.dataTables_info, div.dataTables_paginate {{
      display: none;
    }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p class="sub">{subtitle}</p>

  <div class="summary">
    {summary_cards}
  </div>

  {sections}

<script>
$(document).ready(function(){{
  $('table.report-table').each(function(){{
    $(this).DataTable({{
      paging: false,
      searching: false,
      info: false,
      ordering: true,
      order: []
    }});
  }});
}});
</script>
</body>
</html>
"""


def export_org_report(df: pd.DataFrame, org_abbr: Optional[str] = None) -> None:
    """
    Build and export a single-page org report with:
      - A 13-batter (default) roster-aware platoon plan:
          * Core lineup vs RHP (core 9)
          * Best lineup vs LHP restricted to a max-batters roster cap
          * Bench roles (backup C, utility IF, backup OF, flex)
      - Batting orders vs RHP and vs LHP
      - Runs/game estimates for each lineup
      - 5-man rotation and 8-man bullpen
    """
    from config import team_managed
    from org_report import build_pitching_staff, build_roster_constrained_plan

    org = org_abbr or team_managed

    plan = build_roster_constrained_plan(df, org_abbr=org, max_batters=13)
    rotation, bullpen = build_pitching_staff(df, org_abbr=org, n_sp=5, n_rp=8)

    # Summaries
    def _sum_numeric(series):
        try:
            return float(pd.to_numeric(series, errors="coerce").fillna(0).sum())
        except Exception:
            return 0.0

    sum_lineup_r = float(plan.lineup_war_r or 0.0)
    sum_lineup_l = float(plan.lineup_war_l or 0.0)
    sum_rot = _sum_numeric(rotation.get("sp_war"))
    sum_pen = _sum_numeric(bullpen.get("rp_war"))

    runs_r = plan.runs_pg_r
    runs_l = plan.runs_pg_l

    roster_count = int(len(plan.roster)) if plan.roster is not None else 0

    # ✅ FIXED: use "\n".join(...) on ONE line (no broken string literal)
    summary_cards = "\n".join(
        [
            f'<div class="card"><div class="k">Org</div><div class="v">{org}</div></div>',
            f'<div class="card"><div class="k">Active Batters Used</div><div class="v">{roster_count} / {plan.max_batters}</div></div>',
            f'<div class="card"><div class="k">Lineup WAR (vs RHP)</div><div class="v">{sum_lineup_r:.1f}</div></div>',
            f'<div class="card"><div class="k">Lineup WAR (vs LHP)</div><div class="v">{sum_lineup_l:.1f}</div></div>',
            f'<div class="card"><div class="k">Runs / Game (vs RHP)</div><div class="v">{runs_r:.2f}</div></div>',
            f'<div class="card"><div class="k">Runs / Game (vs LHP)</div><div class="v">{runs_l:.2f}</div></div>',
            f'<div class="card"><div class="k">Rotation WAR (Top 5)</div><div class="v">{sum_rot:.1f}</div></div>',
            f'<div class="card"><div class="k">Bullpen WAR (Top 8)</div><div class="v">{sum_pen:.1f}</div></div>',
        ]
    )

    # roster table (note already between role and name)
    roster_cols = [
        "role",
        "note",
        "name",
        "minor",
        "age",
        "pa",
        "wOBAR",
        "wOBAL",
        "wOBA",
        "wRC+",
        "starts_vs_R",
        "pos_vs_R",
        "starts_vs_L",
        "pos_vs_L",
        "field",
    ]

    # starting lineup tables: include bat_note + split wRC+ and forced note
    lineup_cols = [
        "pos",
        "note",
        "bat_note",
        "name",
        "age",
        "pa",
        "pos_WAR",
        "wOBA_vs",
        "wRC+_vs",
        "field",
    ]

    # batting order tables: show split wRC+
    order_cols = ["slot", "pos", "name", "wOBA_vs", "wRC+_vs"]
    rot_cols = ["name", "age", "minor", "ip", "sp_war", "pwOBA", "pwOBAR", "pwOBAL"]
    pen_cols = ["name", "age", "minor", "ip", "rp_war", "pwOBA", "pwOBAR", "pwOBAL"]

    roster_disp = (
        plan.roster[[c for c in roster_cols if c in plan.roster.columns]]
        if plan.roster is not None
        else pd.DataFrame()
    )
    lineup_r_disp = (
        plan.lineup_r[[c for c in lineup_cols if c in plan.lineup_r.columns]]
        if plan.lineup_r is not None
        else pd.DataFrame()
    )
    lineup_l_disp = (
        plan.lineup_l[[c for c in lineup_cols if c in plan.lineup_l.columns]]
        if plan.lineup_l is not None
        else pd.DataFrame()
    )
    order_r_disp = (
        plan.order_r[[c for c in order_cols if c in plan.order_r.columns]]
        if plan.order_r is not None
        else pd.DataFrame()
    )
    order_l_disp = (
        plan.order_l[[c for c in order_cols if c in plan.order_l.columns]]
        if plan.order_l is not None
        else pd.DataFrame()
    )
    rotation_disp = rotation[[c for c in rot_cols if c in rotation.columns]]
    bullpen_disp = bullpen[[c for c in pen_cols if c in bullpen.columns]]

    sections_html = []
    sections_html.append(
        '<div class="section"><h2>Active roster batters (cap-aware)</h2>'
        + _df_to_report_table(roster_disp, "roster_batters")
        + "</div>"
    )
    sections_html.append(
        '<div class="section"><h2>Starting lineup (vs RHP)</h2>'
        + _df_to_report_table(lineup_r_disp, "lineup_r")
        + "</div>"
    )
    sections_html.append(
        '<div class="section"><h2>Batting order (vs RHP)</h2>'
        + _df_to_report_table(order_r_disp, "order_r")
        + "</div>"
    )
    sections_html.append(
        '<div class="section"><h2>Starting lineup (vs LHP)</h2>'
        + _df_to_report_table(lineup_l_disp, "lineup_l")
        + "</div>"
    )
    sections_html.append(
        '<div class="section"><h2>Batting order (vs LHP)</h2>'
        + _df_to_report_table(order_l_disp, "order_l")
        + "</div>"
    )
    sections_html.append(
        '<div class="section"><h2>Rotation (Top 5 SP)</h2>'
        + _df_to_report_table(rotation_disp, "rotation")
        + "</div>"
    )
    sections_html.append(
        '<div class="section"><h2>Bullpen (Top 8 RP)</h2>'
        + _df_to_report_table(bullpen_disp, "bullpen")
        + "</div>"
    )

    full = HTML_ORG_REPORT_TEMPLATE.format(
        title=f"{org} Org Report",
        subtitle="Generated by Pistachio (cap-aware platoon roster + projected lineup + staff).",
        summary_cards=summary_cards,
        # ✅ FIXED: join sections with "\n" on ONE line
        sections="\n".join(sections_html),
    )

    path = export_filepath / "org_report.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(full)

    print(f"✅ Exported Org Report → {path}")


# ------------------------------------------------------------------
# Advanced DataTables HTML export (dark theme, compact, SearchBuilder)
# ------------------------------------------------------------------

HTML_DARK_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>{title}</title>
  <!-- DataTables core & extensions -->
  <link rel="stylesheet" href="https://cdn.datatables.net/1.13.4/css/jquery.dataTables.min.css"/>
  <link rel="stylesheet" href="https://cdn.datatables.net/searchbuilder/1.4.0/css/searchBuilder.dataTables.min.css"/>
  <link rel="stylesheet" href="https://cdn.datatables.net/fixedheader/3.3.2/css/fixedHeader.dataTables.min.css"/>
  <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap" rel="stylesheet"/>
  <script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
  <script src="https://cdn.datatables.net/1.13.4/js/jquery.dataTables.min.js"></script>
  <script src="https://cdn.datatables.net/searchbuilder/1.4.0/js/dataTables.searchBuilder.min.js"></script>
  <script src="https://cdn.datatables.net/fixedheader/3.3.2/js/dataTables.fixedHeader.min.js"></script>

  <style>
    /* ----- Dark theme & compact table ----- */
    body {{
      background:#1c1c1c; color:#e0e0e0; margin:0; padding:1rem; font-family:Arial,Helvetica,sans-serif;
      font-family: 'Roboto', sans-serif;
    }}
    table.dataTable {{
      background:#1c1c1c; color:#e0e0e0; font-size:0.8rem;
      font-family: 'Roboto', sans-serif;
    }}
    /* zebra striping with dark tones */
    table.dataTable tbody tr:nth-child(odd)  {{ background:#262626; }}
    table.dataTable tbody tr:nth-child(even) {{ background:#1e1e1e; }}
    /* subtle hover effect */
    table.dataTable tbody tr:hover {{ background: rgba(255,255,255,0.05); }}
    /* header */
    table.dataTable thead th {{
      background:#2f2f2f; color:#e0e0e0;
      box-shadow: 0 2px 4px rgba(0,0,0,0.5);
    }}

    /* inline top controls (search builder, length, filter) */
    #data-searchBuilderContainer,
    div.dataTables_length,
    div.dataTables_filter {{
      display: inline-block;
      vertical-align: middle;
      margin-right: 1rem;
    }}
    /* remove "Custom Search Builder" title */
    #data-searchBuilderContainer .dtsb-header {{
      display: none;
    }}
    /* hide the SearchBuilder title text */
    #data-searchBuilderContainer .dtsb-title {{
      display: none !important;
    }}

    /* style length selector and search input for visibility */
    div.dataTables_length label,
    div.dataTables_filter label {{
      color: #e0e0e0;
    }}
    div.dataTables_length select,
    div.dataTables_filter input {{
      color: #e0e0e0;
      background: #2f2f2f;
      border: none;
    }}
    /* header row layout */
    .header-row {{
      display: flex;
      align-items: center;
      font-size: 1rem;
      margin-bottom: 1rem;
    }}
    .header-row h2 {{
      margin: 0;
      font-size: 1rem;
      font-weight: normal;
      color: #e0e0e0;
    }}
    #header-controls {{
      margin-left: 1rem;
    }}
  </style>
</head>
<body>
  <div class="header-row">
    <h2>{title}</h2>
    <div id="header-controls"></div>
  </div>
  {table}
<script>
$.fn.dataTable.ext.order['numeric-empty-last-asc'] = function(settings, col) {{
    return this.api().column(col, {{order:'index'}}).nodes().map(function(td) {{
        var v = parseFloat($(td).text());
        return isNaN(v) ? Infinity : v;
    }});
}};
$.fn.dataTable.ext.order['numeric-empty-last-desc'] = function(settings, col) {{
    return this.api().column(col, {{order:'index'}}).nodes().map(function(td) {{
        var v = parseFloat($(td).text());
        return isNaN(v) ? -Infinity : v;
    }});
}};
$(document).ready(function(){{
    var ascCols = ['pwOBA','pwOBAR','pwOBAL'];
    // Columns that can contain blanks (position WARs NaN'd by the
    // POSITION_FLOOR filter in calc_war). Use the empty-last-desc
    // sorter so blanks sink to the bottom regardless of sort direction.
    var descCols = ['sp_war','rp_war',
        'C_def','CF_def','RF_def','LF_def','SS_def','2B_def','3B_def',
        'C','CF','RF','LF','SS','2B','3B','1B','DH',
        'CP','CFP','RFP','LFP','SSP','2BP','3BP','1BP','DHP',
        'C_adj','CF_adj','RF_adj','LF_adj','SS_adj','2B_adj','3B_adj','1B_adj','DH_adj',
        'CP_adj','CFP_adj','RFP_adj','LFP_adj','SSP_adj','2BP_adj','3BP_adj','1BP_adj','DHP_adj',
        'C_fld','CF_fld','RF_fld','LF_fld','SS_fld','2B_fld','3B_fld','1B_fld','DH_fld',
        'war_hitting','war_hittingP','DH_hitting','DH_hittingP',
        'best_adj','bestP_adj'];
    var numDefs = ascCols.map(function(name) {{
        return {{
            targets: $('#data thead th').filter(function() {{ return $(this).text() === name; }}).index(),
            orderDataType: 'numeric-empty-last-asc',
            orderSequence: ['asc','desc']
        }};
    }}).concat(descCols.map(function(name) {{
        return {{
            targets: $('#data thead th').filter(function() {{ return $(this).text() === name; }}).index(),
            orderDataType: 'numeric-empty-last-desc',
            orderSequence: ['desc','asc']
        }};
    }}));
  $('#data').DataTable({{
      dom: 'Qlfrtip',            // Q = SearchBuilder, l = length selector, f = search bar, r = processing, t = table, i = info, p = paging
      pageLength: {page_len},
      ordering: true,
      searching: true,
      paging: true,
      fixedHeader: true,
      stripeClasses: ['odd', 'even'],
      searchBuilder: {{ }},
      columnDefs: [ {{ targets: 0, visible: false }} ].concat(numDefs)
  }});
      // move SearchBuilder UI into header controls
      $('#data-searchBuilderContainer').appendTo('#header-controls');
      // rename the add button
      $('.dtsb-add').text('Add search filter');
}});
</script>
</body>
</html>
"""
