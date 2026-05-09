"""Show top 10 per position from the regenerated export."""
import json
import pandas as pd

POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]

with open("outputs/hitters.json") as f:
    data = json.load(f)
df = pd.DataFrame(data["rows"], columns=data["columns"])

# Pool sizes
print("Pool sizes (where pos_adj is each position's best WAR):")
print(df["pos_adj"].value_counts().to_string())
print()

print("=" * 80)
for pos in POSITIONS:
    sub = df[df["pos_adj"] == pos].sort_values("best_adj", ascending=False).head(10)
    print(f"\n--- TOP 10 {pos} ---")
    print(f"{'Player':<26s} {'Org':<5s} {'wOBA':>6s} {'best_adj':>9s} {'field':<40s}")
    for _, r in sub.iterrows():
        name = str(r.get("name", "?"))[:26]
        org = str(r.get("org", "?"))[:4]
        wOBA = r.get("wOBA", float("nan"))
        ba = r.get("best_adj", float("nan"))
        fld = str(r.get("field", ""))[:40]
        print(f"{name:<26s} {org:<5s} {wOBA:>6.3f} {ba:>+9.2f} {fld:<40s}")
