"""Sim vs FanGraphs 2025 per-position WAR ceiling gap report.

Loads `outputs/fg_2025_pos_ceilings.json` (built by
`calibration/fg_2025_reference.py`) and compares each FG p0.999 ceiling
to our sim's MLB-only p0.999 for the corresponding column:

  Batting:  FG  Batting/RPW    vs sim  war_hitting  (DH_hitting for DH)
  Fielding: FG  Fielding/RPW   vs sim  <pos>_def
  Def+pos:  FG  Defense/RPW    vs sim  <pos>_fld
  Total:    FG  WAR            vs sim  <pos>_adj

The sim side uses `load_floored_df()` (regenerated via main.compute_df()
so we have access to the `_def` columns), filtered to MLB-only
(`minor == 0`) and non-pitcher (or two-way) rows.

Writes a markdown report to `outputs/calibration_gap_report.md`. Re-run
this script whenever new positions are added to `calibration/fg_2025/`
and `fg_2025_reference.py` is re-run.

Usage:
  python -X utf8 calibration/sim_vs_fg_gap.py
  python -X utf8 calibration/sim_vs_fg_gap.py --positions C 1B 2B
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

# Reuse the existing helper that monkey-patches the floor and returns the
# full position-player df with _def columns intact.
from calibration.war_dist_per_pos import load_floored_df

FG_JSON = Path("outputs/fg_2025_pos_ceilings.json")
OUT_MD = Path("outputs/calibration_gap_report.md")

POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]

# OOTP position codes — used to filter the sim pool to natural-position
# players, so the sim bat ceiling for "C" comes from sim catchers (not
# from Aaron Judge etc.), matching how FG's per-position CSVs filter.
OOTP_POSITION_CODE = {
    "C": 2, "1B": 3, "2B": 4, "3B": 5, "SS": 6,
    "LF": 7, "CF": 8, "RF": 9, "DH": 10,
}


def sim_ceiling(series: pd.Series) -> dict:
    s = series.dropna()
    if s.empty:
        return {"n": 0, "max": float("nan"), "p0_999": float("nan")}
    return {
        "n": int(s.size),
        "max": float(s.max()),
        "p0_999": float(s.quantile(0.999)),
    }


def per_pos_sim_stats(df: pd.DataFrame, pos: str) -> dict:
    """Sim p0.999 / max for: war_hitting (bat), <pos>_def (fld),
    <pos>_fld (fld+pos), <pos>_adj (total) — restricted to players
    whose OOTP natural position matches `pos` (apples-to-apples with
    FG's per-position CSV, which is filtered to players who played
    that position)."""
    bat_col = "DH_hitting" if pos == "DH" else "war_hitting"
    out = {"bat": {}, "def": {}, "fld_with_pos_adj": {}, "adj": {}}

    pos_code = OOTP_POSITION_CODE.get(pos)
    sub = df[df["position"] == pos_code] if pos_code is not None else df

    if bat_col in sub.columns:
        out["bat"] = sim_ceiling(sub[bat_col])

    def_col = f"{pos}_def"
    if def_col in sub.columns:
        out["def"] = sim_ceiling(sub[def_col])
    elif pos == "DH":
        out["def"] = {"n": int(sub.shape[0]), "max": 0.0, "p0_999": 0.0}

    fld_col = f"{pos}_fld"
    if fld_col in sub.columns:
        out["fld_with_pos_adj"] = sim_ceiling(sub[fld_col])

    adj_col = f"{pos}_adj"
    if adj_col in sub.columns:
        out["adj"] = sim_ceiling(sub[adj_col])

    out["n_pos_players"] = int(len(sub))
    return out


def fg_war(stats: dict, key: str) -> tuple[float, float]:
    """Pull max and p0.999 in WAR units from a fg ceilings stats block.
    For 'WAR' the values are already WAR; for everything else use
    war_units sub-dict (runs / RPW)."""
    block = stats.get(key, {})
    if not block or block.get("n", 0) == 0:
        return float("nan"), float("nan")
    if "war_units" in block:
        return block["war_units"]["max"], block["war_units"]["p0_999"]
    return block.get("max", float("nan")), block.get("p0_999", float("nan"))


def build_gap_table(fg: dict, sim_by_pos: dict, positions: list[str]) -> str:
    """Build the markdown gap table."""
    lines = []
    header = (
        "| Pos | FG_bat_max | Sim_bat_p999 | Δ_bat |"
        " FG_fld_max | Sim_fld_p999 | Δ_fld |"
        " FG_def_max | Sim_fld_pos_p999 | Δ_def |"
        " FG_WAR_max | Sim_adj_p999 | Δ_WAR |"
    )
    sep = "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    lines.append(header)
    lines.append(sep)

    for pos in positions:
        if pos not in fg:
            continue
        bv = fg[pos]["batting_value"]
        sim = sim_by_pos.get(pos, {})

        fg_bat_max, _ = fg_war(bv, "Batting")
        fg_fld_max, _ = fg_war(bv, "Fielding")
        fg_def_max, _ = fg_war(bv, "Defense")
        fg_war_max, _ = fg_war(bv, "WAR")

        sim_bat = sim.get("bat", {}).get("p0_999", float("nan"))
        sim_def = sim.get("def", {}).get("p0_999", float("nan"))
        sim_fld = sim.get("fld_with_pos_adj", {}).get("p0_999", float("nan"))
        sim_adj = sim.get("adj", {}).get("p0_999", float("nan"))

        d_bat = sim_bat - fg_bat_max if pd.notna(sim_bat) else float("nan")
        d_fld = sim_def - fg_fld_max if pd.notna(sim_def) else float("nan")
        d_def = sim_fld - fg_def_max if pd.notna(sim_fld) else float("nan")
        d_war = sim_adj - fg_war_max if pd.notna(sim_adj) else float("nan")

        def fmt(x):
            return "—" if pd.isna(x) else f"{x:+.2f}"

        lines.append(
            f"| **{pos}** "
            f"| {fmt(fg_bat_max)} | {fmt(sim_bat)} | {fmt(d_bat)} "
            f"| {fmt(fg_fld_max)} | {fmt(sim_def)} | {fmt(d_fld)} "
            f"| {fmt(fg_def_max)} | {fmt(sim_fld)} | {fmt(d_def)} "
            f"| {fmt(fg_war_max)} | {fmt(sim_adj)} | {fmt(d_war)} |"
        )

    return "\n".join(lines)


def diagnose_gaps(fg: dict, sim_by_pos: dict, positions: list[str]) -> str:
    """Markdown bullets pointing at the biggest gaps and which config.py
    knobs they implicate."""
    bullets = []
    for pos in positions:
        if pos not in fg:
            continue
        bv = fg[pos]["batting_value"]
        sim = sim_by_pos.get(pos, {})

        fg_bat_max, _ = fg_war(bv, "Batting")
        fg_fld_max, _ = fg_war(bv, "Fielding")
        fg_war_max, _ = fg_war(bv, "WAR")

        sim_bat = sim.get("bat", {}).get("p0_999", float("nan"))
        sim_def = sim.get("def", {}).get("p0_999", float("nan"))
        sim_adj = sim.get("adj", {}).get("p0_999", float("nan"))

        d_bat = (sim_bat - fg_bat_max) if pd.notna(sim_bat) else float("nan")
        d_fld = (sim_def - fg_fld_max) if pd.notna(sim_def) else float("nan")
        d_war = (sim_adj - fg_war_max) if pd.notna(sim_adj) else float("nan")

        notes = []
        if pd.notna(d_bat) and abs(d_bat) >= 0.5:
            sign = "undershoots" if d_bat < 0 else "overshoots"
            notes.append(f"**bat** {sign} FG by {abs(d_bat):.2f} WAR "
                         f"→ candidate knob: `RUNS_PER_WIN_HITTING` "
                         f"(config.py:200) / `RUNS_PER_GAME_HITTING_COEFF` "
                         f"(config.py:243)")
        if pd.notna(d_fld) and abs(d_fld) >= 0.5:
            sign = "undershoots" if d_fld < 0 else "overshoots"
            implicates = {
                "C": "FIELDING_RUN_VALUES_VS_REPLACEMENT['C'] (framing plateau)",
                "2B": "FIELDING_SATURATION['2B']",
                "3B": "FIELDING_SATURATION['3B']",
                "SS": "FIELDING_SATURATION['SS']",
            }.get(pos, f"FIELDING_RUN_VALUES_VS_REPLACEMENT['{pos}']")
            notes.append(f"**fld** {sign} FG by {abs(d_fld):.2f} WAR "
                         f"→ candidate knob: `{implicates}`")
        if pd.notna(d_war) and abs(d_war) >= 1.0:
            sign = "undershoots" if d_war < 0 else "overshoots"
            notes.append(f"**total** {sign} FG by {abs(d_war):.2f} WAR "
                         f"(combined effect of bat + fld + pos_adj)")

        if notes:
            bullets.append(f"- **{pos}**:")
            for n in notes:
                bullets.append(f"  - {n}")
        else:
            bullets.append(f"- **{pos}**: all components within 0.5 WAR of FG ceiling — well-calibrated.")

    return "\n".join(bullets)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--positions", nargs="*", default=POSITIONS)
    args = ap.parse_args()

    if not FG_JSON.exists():
        print(f"Missing {FG_JSON}. Run calibration/fg_2025_reference.py first.")
        sys.exit(1)

    fg = json.load(open(FG_JSON))
    fg_positions = [p for p in args.positions if p in fg]
    if not fg_positions:
        print(f"No FG reference data for any requested positions: {args.positions}")
        sys.exit(1)

    print(f"Regenerating sim df via main.compute_df()...")
    df = load_floored_df()
    # MLB-only for like-for-like comparison with FG MLB data
    df = df[df["minor"] == 0].copy()
    print(f"MLB-only position-player pool: n = {len(df)}")

    sim_by_pos = {pos: per_pos_sim_stats(df, pos) for pos in fg_positions}
    for pos in fg_positions:
        n = sim_by_pos[pos].get("n_pos_players", 0)
        print(f"  {pos}: {n} natural-position MLB players in sim")

    table_md = build_gap_table(fg, sim_by_pos, fg_positions)
    diagnosis_md = diagnose_gaps(fg, sim_by_pos, fg_positions)

    # Console print
    print()
    print(table_md)
    print()
    print("Diagnosis:")
    print(diagnosis_md)

    # Markdown report
    report_lines = [
        "# Calibration Gap Report — FanGraphs 2025 vs Sim",
        "",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M:%S}_  ",
        f"Sim pool: **MLB-only** (`minor == 0`), n = {len(df)}.  ",
        f"FG reference RPW: {fg[fg_positions[0]]['rpw']} (runs → WAR divisor).",
        "",
        "## Per-position p0.999 / max comparison",
        "",
        ("All values in WAR units. **FG_** columns are 2025 single-position "
         "maxes (the per-position MLB ceiling, from FG's per-position CSV). "
         "**Sim_** columns are p0.999 of the corresponding sim column, "
         "filtered to **MLB-only AND OOTP natural-position match** "
         "(`minor == 0 AND position == <code>`). This makes the sim's bat "
         "ceiling at C come from sim catchers (not Aaron Judge), matching "
         "how FG's per-position CSV is filtered. Δ = Sim − FG (negative "
         "means our sim undershoots MLB)."),
        "",
        table_md,
        "",
        "## Diagnosis",
        "",
        diagnosis_md,
        "",
        "## Reference knobs (from the plan, for follow-up)",
        "",
        "| Type of gap | Candidate knobs (config.py) |",
        "|---|---|",
        "| Overall bat scale low | `RUNS_PER_WIN_HITTING = 10.28` (line 200); `RUNS_PER_GAME_HITTING_COEFF = 496.84` (line 243) |",
        "| Overall fld scale low | `RUNS_PER_WIN_FIELDING = 9.53` (line 202) |",
        "| IF fld ceiling low (2B/3B/SS) | `FIELDING_SATURATION` (config.py:1928+); rerun `calibration/fit_saturation.py` |",
        "| C fld ceiling low (framing plateau) | `FIELDING_RUN_VALUES_VS_REPLACEMENT['C']` (config.py:1433+), `Cfram` in particular |",
        "| Positional adjustments off | `POSITIONAL_ADJUSTMENT_RUNS` (config.py:130-140) |",
        "",
        "## Coverage",
        "",
        f"Positions processed: {', '.join(fg_positions)}.",
        f"Positions still pending: {', '.join(p for p in POSITIONS if p not in fg)}.",
        "",
        ("Drop additional `<POS>_batting_value.csv` and `<POS>_adv_fielding.csv` "
         "files into `calibration/fg_2025/`, then re-run "
         "`calibration/fg_2025_reference.py` followed by this script."),
    ]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\nSaved: {OUT_MD.resolve()}")


if __name__ == "__main__":
    main()
