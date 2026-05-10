"""Shared pytest plumbing for the roster-invariants suite.

Discovers the org list from outputs/hitters.json at collection time so
each invariant test runs once per (invariant × org) — gives granular
failure messages ("AZ violates service-floor: Adrian Rodriguez at R…")
rather than a single bundled assertion that buries which org broke.

Fixtures are session-scoped so build_system.main() / build_pitcher_system.main()
run AT MOST once per org per pytest invocation, not once per test
function. With ~30 orgs × ~10 invariants the alternative would be 300
roster builds; session scope keeps it at 60 (one hitter + one pitcher
build per org).
"""
import json
from pathlib import Path

import pytest

HITTERS_JSON = Path('outputs/hitters.json')
PITCHERS_JSON = Path('outputs/pitchers.json')


def _discover_orgs():
    """Scan hitters.json for the set of org abbreviations to test against.
    Returns [] if the file is missing — pytest_generate_tests then leaves
    the parametrize empty and the tests are skipped at collection time."""
    if not HITTERS_JSON.exists():
        return []
    rows = json.load(open(HITTERS_JSON))['rows']
    return sorted({r['org'] for r in rows
                   if r.get('org') and r['org'] != 'Free'})


def pytest_generate_tests(metafunc):
    """Parametrize any test that takes an `org` argument over every MLB org
    discovered in the cached JSON. Skips parametrization (and so the test)
    if the JSON is absent — typically means the user hasn't run
    `python app.py refresh` yet."""
    if 'org' in metafunc.fixturenames:
        orgs = _discover_orgs()
        if orgs:
            metafunc.parametrize('org', orgs)
        else:
            metafunc.parametrize(
                'org', [],
                ids=['outputs/hitters.json missing — run app.py refresh'],
            )


@pytest.fixture(scope='session')
def all_orgs():
    """All MLB org abbreviations present in the cached hitters.json."""
    orgs = _discover_orgs()
    if not orgs:
        pytest.skip(f'{HITTERS_JSON} missing; run `python app.py refresh` first.')
    return orgs


@pytest.fixture(scope='session')
def hitter_results(all_orgs):
    """`{org: (rosters, overflow, flagged)}` from build_system.main(org=org).
    Built once per pytest session — main() takes ~1s per org so this is
    the dominant cost of running the suite (~30s for 30 orgs)."""
    from build_system import main as hitter_main
    return {org: hitter_main(org=org) for org in all_orgs}


@pytest.fixture(scope='session')
def pitcher_results(all_orgs):
    """`{org: (rosters, overflow, flagged)}` from build_pitcher_system.main."""
    from build_pitcher_system import main as pitcher_main
    return {org: pitcher_main(org=org) for org in all_orgs}


@pytest.fixture(scope='session')
def org_loaded_counts(all_orgs):
    """`{org: (n_hitters, n_pitchers)}` raw player counts from the JSONs.
    Used by the "no lost players" invariant to verify
    placed + overflow + flagged + complex-filtered == loaded."""
    h_rows = json.load(open(HITTERS_JSON))['rows']
    p_rows = json.load(open(PITCHERS_JSON))['rows']
    return {
        org: (
            sum(1 for r in h_rows if r.get('org') == org),
            sum(1 for r in p_rows if r.get('org') == org),
        )
        for org in all_orgs
    }


@pytest.fixture(scope='session')
def org_complex_counts(all_orgs):
    """`{org: (n_hitter_complex, n_pitcher_complex)}` — count of players
    filtered out at Step 0 of main() because they're international-complex
    (minor=0 AND age<20). These never appear in rosters / overflow /
    flagged, so the no-lost-players accounting needs them as a separate
    bucket."""
    h_rows = json.load(open(HITTERS_JSON))['rows']
    p_rows = json.load(open(PITCHERS_JSON))['rows']
    return {
        org: (
            sum(1 for r in h_rows
                if r.get('org') == org
                and r.get('minor') == 0
                and r.get('age', 99) < 20),
            sum(1 for r in p_rows
                if r.get('org') == org
                and r.get('minor') == 0
                and r.get('age', 99) < 20),
        )
        for org in all_orgs
    }
