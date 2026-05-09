"""
Release pool sense-check.
Read-only analysis of hitter (primary) and pitcher (secondary) overflow
across 3 orgs to verify roster construction is producing sensible results.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DevNull:
    def write(self, _): pass
    def flush(self): pass


# Suppress noisy build logs
old_stdout = sys.stdout
sys.stdout = DevNull()
try:
    from build_system import main as hit_main, is_high_potential, LEVELS, WOBA_MIN, MAX_AGE
    from build_pitcher_system import main as pit_main, is_high_potential_pitcher
finally:
    sys.stdout = old_stdout


ORGS = ["COL", "AZ", "LAA"]


def analyze_org(org):
    """Pull rosters/overflow for one org."""
    sys.stdout = DevNull()
    try:
        h_rosters, h_overflow, h_flagged = hit_main(org=org)
        p_rosters, p_overflow, p_flagged = pit_main(org=org)
    finally:
        sys.stdout = old_stdout
    return h_rosters, h_overflow, p_rosters, p_overflow


def fmt_player_h(p):
    """Format a hitter overflow row."""
    is_hp = is_high_potential(p)
    age = p.get('age', '?')
    pos = p.get('pos_adj', '?')
    woba = p.get('wOBA', 0) or 0
    wobap = p.get('wOBAP', 0) or 0
    bestp = p.get('bestP', 0) or 0
    top_lvl = LEVELS[p['_top']] if 0 <= p.get('_top', -1) < len(LEVELS) else '?'
    bot_lvl = LEVELS[p['_bot']] if 0 <= p.get('_bot', -1) < len(LEVELS) else '?'
    hp_str = "HP" if is_hp else "  "
    return (f"  {hp_str}  {p['name']:<22} age={age:>2} pos={pos:>3}  "
            f"wOBA={woba:.3f} wOBAP={wobap:.3f} bestP={bestp:>5.2f}  "
            f"top={top_lvl:>3} bot={bot_lvl:>3}")


def fmt_player_p(p):
    """Format a pitcher overflow row."""
    is_hp = is_high_potential_pitcher(p)
    age = p.get('age', '?')
    pwoba = p.get('pwOBA', 0) or 0
    pwobap = p.get('pwOBAP', 0) or 0
    sp_warp = p.get('sp_warP') or 0
    rp_warp = p.get('rp_warP') or 0
    hp_str = "HP" if is_hp else "  "
    return (f"  {hp_str}  {p['name']:<22} age={age:>2}  "
            f"pwOBA={pwoba:.3f} pwOBAP={pwobap:.3f} sp_warP={sp_warp:>5.2f} rp_warP={rp_warp:>5.2f}")


def position_breakdown(overflow):
    from collections import Counter
    return Counter(p.get('pos_adj', '?') for p in overflow)


def reason_breakdown(overflow):
    """Categorize WHY each player is in overflow."""
    from collections import Counter
    counts = Counter()
    for p in overflow:
        age = p.get('age', 99)
        # Service-cap victims
        srv_total = sum(p.get(f'yrs_{lvl}', 0) or 0 for lvl in LEVELS)
        if srv_total >= 5:
            counts['service-capped'] += 1
        elif age >= 27:
            counts['old (>=27)'] += 1
        elif age <= 22:
            counts['young (<=22) but bat too weak'] += 1
        else:
            counts['mid-age & wOBA-blocked'] += 1
    return counts


def main():
    print("=" * 100)
    print("RELEASE POOL SENSE-CHECK")
    print("=" * 100)

    summary = []

    for org in ORGS:
        print(f"\n{'=' * 100}")
        print(f"ORG: {org}")
        print(f"{'=' * 100}")

        h_rosters, h_overflow, p_rosters, p_overflow = analyze_org(org)

        # ====== HITTERS ======
        print(f"\n--- HITTERS (primary) ---")
        print(f"Overflow size: {len(h_overflow)}")

        # HP count
        hp_overflow = [p for p in h_overflow if is_high_potential(p)]
        print(f"HPs in overflow: {len(hp_overflow)}")
        if hp_overflow:
            print("  Concerning HP overflow:")
            for p in sorted(hp_overflow, key=lambda x: -(x.get('bestP') or 0))[:5]:
                print(fmt_player_h(p))

        # Top 10 by bestP (the "biggest mistakes" if wrong)
        print(f"\n  Top 10 overflow by bestP:")
        for p in sorted(h_overflow, key=lambda x: -(x.get('bestP') or 0))[:10]:
            print(fmt_player_h(p))

        # Position breakdown
        pos_counts = position_breakdown(h_overflow)
        print(f"\n  Position breakdown: {dict(pos_counts.most_common())}")

        # Reason breakdown
        reasons = reason_breakdown(h_overflow)
        print(f"  Reason breakdown: {dict(reasons.most_common())}")

        # Young-prospect concerns: age <= 22 and wOBA > 0.300
        young_strong = [p for p in h_overflow
                        if (p.get('age', 99) <= 22) and ((p.get('wOBA') or 0) > 0.300)]
        print(f"  Young (<=22) with wOBA > 0.300 in overflow: {len(young_strong)}")
        for p in young_strong[:5]:
            print(fmt_player_h(p))

        # ====== PITCHERS ======
        print(f"\n--- PITCHERS (secondary control) ---")
        print(f"Overflow size: {len(p_overflow)}")
        hp_p_overflow = [p for p in p_overflow if is_high_potential_pitcher(p)]
        print(f"HP pitchers in overflow: {len(hp_p_overflow)}")

        print(f"\n  Top 5 overflow by sp_warP:")
        sortable = [p for p in p_overflow if (p.get('sp_warP') is not None)]
        for p in sorted(sortable, key=lambda x: -(x.get('sp_warP') or -999))[:5]:
            print(fmt_player_p(p))

        # Save to summary
        summary.append({
            'org': org,
            'h_overflow': len(h_overflow),
            'h_hp_overflow': len(hp_overflow),
            'h_young_strong': len(young_strong),
            'p_overflow': len(p_overflow),
            'p_hp_overflow': len(hp_p_overflow),
            'top_h_bestP': max((p.get('bestP') or 0 for p in h_overflow), default=0),
            'top_p_sp_warP': max((p.get('sp_warP') or 0 for p in p_overflow if p.get('sp_warP') is not None), default=0),
        })

    # ====== SUMMARY ======
    print(f"\n{'=' * 100}")
    print("SUMMARY")
    print(f"{'=' * 100}")
    print(f"{'org':>5} | {'h_ovf':>5} {'hp':>3} {'young>.300':>10} {'top_bestP':>10} | "
          f"{'p_ovf':>5} {'hp':>3} {'top_sp_warP':>11}")
    print("-" * 100)
    for s in summary:
        print(f"{s['org']:>5} | {s['h_overflow']:>5} {s['h_hp_overflow']:>3} "
              f"{s['h_young_strong']:>10} {s['top_h_bestP']:>10.2f} | "
              f"{s['p_overflow']:>5} {s['p_hp_overflow']:>3} {s['top_p_sp_warP']:>11.2f}")

    print()
    print("Pass criteria (per plan):")
    print("  Hitter overflow: 10-30 per org / Top bestP < 3 / HPs <= 2 / Young strong <= 2")
    print("  Pitcher overflow: top sp_warP < 1.5")


if __name__ == "__main__":
    main()
