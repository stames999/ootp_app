"""Regression tests for `_flag_two_way_best_side` (R-33 DH-penalty fix).

The pre-R-33 implementation compared raw `war_hitting` vs
`max(sp_war, rp_war)`, which biased the routing toward hitter for any
SP-viable two-way: such players are forced to DH on the hitter side
(via `_restrict_two_way_sp_to_dh` later in compute_df), so their real
hitter-side contribution is `DH_adj` — meaningfully smaller than
`war_hitting` because DH_PENALTY shaves the bat by ~7% and the DH
positional adjustment is the most negative in the system.

R-33 changed the comparison to use `best_adj` (scarcity-adjusted WAR
at the player's best hitting position) vs the pitcher side. These
tests verify the new logic at the two-way decision boundary.
"""
import pandas as pd
import pytest

from main import _flag_two_way_best_side


def _two_way_row(*, best_adj, sp_war=None, rp_war=None,
                 war_hitting=None, is_two_way=True):
    """Construct a minimal player dict with the columns `_flag_two_way_best_side`
    inspects. Defaults are chosen so unused fields don't accidentally tip the
    comparison."""
    return {
        'name': 'Test',
        'is_two_way': is_two_way,
        'best_adj': best_adj,
        'sp_war': sp_war if sp_war is not None else float('nan'),
        'rp_war': rp_war if rp_war is not None else float('nan'),
        'war_hitting': war_hitting if war_hitting is not None else best_adj,
    }


def _route(rows):
    """Run the flag helper on a list of player dicts and return the resulting
    tw_best_side per row."""
    df = pd.DataFrame(rows)
    df = _flag_two_way_best_side(df)
    return list(df['tw_best_side'])


def test_non_two_way_unaffected():
    """Players with is_two_way=False get tw_best_side='' regardless of WAR."""
    rows = [_two_way_row(is_two_way=False, best_adj=10.0, sp_war=1.0)]
    assert _route(rows) == ['']


def test_clear_hitter_routes_hitter():
    """Hitter-dominant two-way (best_adj >> pitcher side) -> hitter."""
    rows = [_two_way_row(best_adj=6.0, sp_war=2.0)]
    assert _route(rows) == ['hitter']


def test_clear_pitcher_routes_pitcher():
    """Pitcher-dominant two-way -> pitcher."""
    rows = [_two_way_row(best_adj=1.0, sp_war=5.0)]
    assert _route(rows) == ['pitcher']


def test_tied_routes_pitcher():
    """Tie-breaker: `<=` puts the tie on pitcher side."""
    rows = [_two_way_row(best_adj=3.0, sp_war=3.0)]
    assert _route(rows) == ['pitcher']


def test_marginal_case_dh_penalty_flips_routing():
    """A marginal SP-viable two-way whose raw war_hitting beats sp_war but
    whose DH-penalised best_adj does NOT. Pre-R-33 logic would have routed
    to hitter (using war_hitting=4.5 vs sp_war=4.4); R-33 routes correctly
    to pitcher (using best_adj=3.5 vs sp_war=4.4).
    """
    rows = [_two_way_row(best_adj=3.5, sp_war=4.4, war_hitting=4.5)]
    assert _route(rows) == ['pitcher']


def test_max_of_sp_rp_used_for_pitcher_side():
    """Pitcher side takes max(sp_war, rp_war) so a stronger RP role wins
    over a weaker SP role."""
    rows = [_two_way_row(best_adj=2.0, sp_war=1.5, rp_war=2.5)]
    assert _route(rows) == ['pitcher']


def test_nan_pitcher_side_routes_hitter():
    """A hitter-only two-way (no SP / RP viability) routes to hitter as long
    as best_adj clears the implicit -99 floor."""
    rows = [_two_way_row(best_adj=2.0, sp_war=None, rp_war=None)]
    assert _route(rows) == ['hitter']
