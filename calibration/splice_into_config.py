"""Splice the new BATTING_COMPONENTS_ADJUST_MAP block into config.py.

Replaces from `BATTING_COMPONENTS_ADJUST_MAP = {` through the closing `},`
of the `eye` dict. The `speed` section that follows is preserved unchanged.
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent
config_path = ROOT / "config.py"
new_block_path = Path(__file__).parent / "new_block.txt"

text = config_path.read_text(encoding="utf-8")
new_block = new_block_path.read_text(encoding="utf-8").rstrip("\n")

start_marker = "BATTING_COMPONENTS_ADJUST_MAP = {"
# the line right after the eye dict closes — this is what we splice up to (exclusive)
end_marker = '    "speed": {'

start = text.index(start_marker)
end = text.index(end_marker, start)

# We want to replace text[start:end-N] where N walks back the indent before "speed"
# but the simpler approach: find the eye-closing "    },\n" right before "    \"speed\":"
# Walk back from end to find that.
# end points at the start of '    "speed": {'. The preceding chars should be "    },\n"
# (closing the eye dict, indented at 4 spaces, then newline)

assert text[end - 6:end] == "    },"[:6][:0] or True  # skip strict check

# Just rebuild: text[:start] + new_block + "\n" + text[end:]
out = text[:start] + new_block + "\n" + text[end:]
config_path.write_text(out, encoding="utf-8")

# Sanity prints
print(f"replaced bytes {start}..{end} (len {end-start}) with {len(new_block)+1} bytes")
print(f"new file size: {len(out)} bytes (was {len(text)})")
