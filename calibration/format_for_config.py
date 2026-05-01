"""Emit the new BATTING_COMPONENTS_ADJUST_MAP body in exact Pistachio style.

Reads the freshly generated dict from new_config_values.py, reorders to match
the existing config order (babip, avk, gap, pow, eye), and prints it formatted
to match the rest of config.py (4/8/12 indent, no leading +).
"""

from pathlib import Path
import importlib.util

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("new_vals", HERE / "new_config_values.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

NEW = mod.BATTING_COMPONENTS_ADJUST_MAP
ORDER = ["babip", "avk", "gap", "pow", "eye"]
COMPS = ["hr", "k", "bb", "1b", "2b", "3b"]
TABLE_VALUES = [20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]


def fmt(v):
    # Match Pistachio style: 4 decimals, no leading +, but preserve signed zero handling
    if v == 0:
        return "0.0000"
    if v < 0:
        return f"{v:.4f}"
    return f"{v:.4f}"


lines = []
lines.append("BATTING_COMPONENTS_ADJUST_MAP = {")
for rating in ORDER:
    lines.append(f'    "{rating}": {{')
    for v in TABLE_VALUES:
        key = str(v)
        if key not in NEW[rating]:
            continue
        row = NEW[rating][key]
        lines.append(f'        "{key}": {{')
        for c in COMPS:
            lines.append(f'            "{c}_pct_adj": {fmt(row[f"{c}_pct_adj"])},')
        lines.append("        },")
    lines.append("    },")

print("\n".join(lines))
