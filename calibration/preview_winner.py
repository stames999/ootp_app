"""Preview top players and pool stats for the grid-sweep winner."""
import json
import pandas as pd

# Same family as the top-10 sweep winners; using #9 because its C=+12.5
# matches FG convention (the C value barely affects scoring since all C-test
# players are catcher-only — picking a defensible value).
WINNER = {
    "C":  12.5, "1B": -12.5, "2B": 8.0, "3B": 0.0, "SS": 12.5,
    "LF": -10.0, "CF": -2.0, "RF": -14.0, "DH": -10.0,
}
RPW_F = 9.53
POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]

with open("outputs/hitters.json") as f:
    data = json.load(f)
df = pd.DataFrame(data["rows"], columns=data["columns"])

# Recompute *_adj_NEW
for pos in POSITIONS:
    df[f"{pos}_adj_NEW"] = df[pos] + WINNER[pos] / RPW_F

adj_cols = [f"{p}_adj_NEW" for p in POSITIONS]
df["best_NEW"] = df[adj_cols].max(axis=1)
df["pos_NEW"] = (
    df[adj_cols].idxmax(axis=1).str.replace("_adj_NEW", "", regex=False)
)

print("Pool sizes under WINNER pos_adj:")
print(df["pos_NEW"].value_counts().to_string())
print(f"\nTotal positioned: {df['pos_NEW'].notna().sum()}")

print()
print("=" * 70)
for pos in POSITIONS:
    sub = df[df["pos_NEW"] == pos].sort_values(f"{pos}_adj_NEW", ascending=False).head(10)
    print(f"\n--- TOP 10 {pos}  (pos_adj={WINNER[pos]:+.1f} runs) ---")
    print(f"{'Player':<28s} {'Org':<5s} {'wOBA':>6s} {'NEW':>6s} {'OLD':>6s} {'Δ':>6s}")
    for _, r in sub.iterrows():
        name = str(r.get("name", "?"))[:28]
        org = str(r.get("org", "?"))[:4]
        wOBA = r.get("wOBA", float("nan"))
        new_v = r[f"{pos}_adj_NEW"]
        old_v = r.get(f"{pos}_adj", float("nan"))
        delta = new_v - old_v if pd.notna(old_v) else float("nan")
        print(f"{name:<28s} {org:<5s} {wOBA:>6.3f} {new_v:>+6.2f} {old_v:>+6.2f} {delta:>+6.2f}")
