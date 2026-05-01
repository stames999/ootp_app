"""Splice the regenerated FIELDING_RUN_VALUES_VS_REPLACEMENT blocks into config.py.

Reads new_fielding_blocks.txt (output of calibrate_fielding.py) and replaces
each position's body in config.FIELDING_RUN_VALUES_VS_REPLACEMENT. Preserves
the explanatory comments above each position block.

Run: python calibration/splice_fielding_into_config.py
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "config.py"
NEW_BLOCKS = Path(__file__).parent / "new_fielding_blocks.txt"

# Read regenerated blocks, splitting by position
new_text = NEW_BLOCKS.read_text(encoding="utf-8")
blocks = {}
current_pos = None
current_lines = []
for line in new_text.splitlines():
    # Position-block start is at 4-space indent ("    \"POS\": {")
    m = re.match(r'^    "(\w+)":\s*\{$', line)
    if m and len(m.group(1)) <= 3:
        if current_pos is not None:
            blocks[current_pos] = "\n".join(current_lines)
        current_pos = m.group(1)
        current_lines = [line]
    elif current_pos is not None:
        current_lines.append(line)
        # Outer-block end: exactly "    }," (4-space indent), which is shallower
        # than the inner-attribute closes ("        },").
        if line == "    },":
            blocks[current_pos] = "\n".join(current_lines)
            current_pos = None
            current_lines = []

print(f"Parsed positions from new blocks: {sorted(blocks.keys())}")

# Read config.py
config_text = CONFIG.read_text(encoding="utf-8")

# For each position, replace its block in FIELDING_RUN_VALUES_VS_REPLACEMENT.
# We need to preserve the explanatory comments above each block.
# Find each position's block by matching `    "POS": {` ... `    },`.

for pos, new_block in blocks.items():
    # Match the existing block (between `    "POS": {` and the closing `    },`)
    pattern = re.compile(
        r'(    "' + re.escape(pos) + r'": \{\n)(.*?)(\n    \},)',
        re.DOTALL,
    )
    matches = pattern.findall(config_text)
    if not matches:
        print(f"  ! WARN: no match for position {pos}")
        continue
    if len(matches) > 1:
        print(f"  ! WARN: {len(matches)} matches for {pos} — using first")

    # Build replacement: strip the leading "    \"POS\": {\n" and trailing "\n    },"
    new_body_lines = new_block.split("\n")
    # new_body_lines[0] is `    "POS": {`, [-1] is `    },`
    # Keep just middle lines as the body
    body_inner = "\n".join(new_body_lines[1:-1])

    config_text = pattern.sub(
        lambda m: m.group(1) + body_inner + m.group(3),
        config_text,
        count=1,
    )
    print(f"  ✓ Spliced {pos}")

CONFIG.write_text(config_text, encoding="utf-8")
print(f"\nUpdated {CONFIG}")
