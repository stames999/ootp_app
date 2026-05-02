"""Pistachio Streamlit front-end.

Run with:
    streamlit run streamlit_app.py

The app is fully self-contained — it does not need any files at a
specific local path. Drop the four OOTP CSVs into the sidebar uploader
and click "Process upload"; the pipeline writes hitters.json and
pitchers.json in the project's outputs/ folder and the rosters render.

Talks to the same functions as the CLI (`app.py`):
- main.compute_df()                  — full pipeline (slow, ~30s)
- build_system.main(org)             — hitter rosters from cached JSON
- build_pitcher_system.main(org)     — pitcher rosters from cached JSON
- build_excel.main_build(org)        — write the team xlsx
"""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from build_system import main as build_hitters, LEVELS, is_high_potential
from build_pitcher_system import main as build_pitchers, is_high_potential_pitcher
from build_excel import main_build, _platoon_lineup_extras

POSITIONS = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH']
HITTERS_JSON = 'outputs/hitters.json'
PITCHERS_JSON = 'outputs/pitchers.json'

REQUIRED_CSVS = {
    'players.csv',
    'players_scouted_ratings.csv',
}
# These two are accepted but optional — they only populate the IP / PA
# display columns in pitcher / hitter tables. No projection uses them.
OPTIONAL_CSVS = {
    'players_career_pitching_stats.csv',
    'players_career_batting_stats.csv',
}
ACCEPTED_CSVS = REQUIRED_CSVS | OPTIONAL_CSVS

st.set_page_config(page_title='Pistachio', layout='wide', page_icon='⚾')


# ---------- Cached data layer ----------

@st.cache_data
def get_orgs():
    """All org abbreviations present in the cached hitters.json."""
    rows = json.load(open(HITTERS_JSON))['rows']
    return sorted({r['org'] for r in rows if r.get('org')})


@st.cache_data(show_spinner='Building rosters…')
def get_rosters(team: str):
    """Build hitter + pitcher rosters for a team. Cheap once cached."""
    rh, oh, fh = build_hitters(org=team)
    rp, op, fp = build_pitchers(org=team)
    return rh, oh, fh, rp, op, fp


def humanise_age(seconds: float) -> str:
    if seconds < 60: return f'{int(seconds)}s ago'
    if seconds < 3600: return f'{int(seconds/60)}m ago'
    if seconds < 86400: return f'{int(seconds/3600)}h ago'
    return f'{int(seconds/86400)}d ago'


def data_age_str() -> str:
    if not os.path.exists(HITTERS_JSON):
        return 'never'
    mtime = os.path.getmtime(HITTERS_JSON)
    return humanise_age((datetime.now() - datetime.fromtimestamp(mtime)).total_seconds())


def has_cached_data() -> bool:
    return os.path.exists(HITTERS_JSON) and os.path.exists(PITCHERS_JSON)


def process_uploaded(uploaded_files):
    """Save the uploads to a temp dir, point config.filepath at it, and run
    the full metrics pipeline. Outputs (hitters.json, pitchers.json, etc.)
    land in the normal outputs/ dir."""
    tmpdir = Path(tempfile.mkdtemp(prefix='pistachio_'))
    for f in uploaded_files:
        if f.name in ACCEPTED_CSVS:
            (tmpdir / f.name).write_bytes(f.getbuffer())
    config.filepath = tmpdir
    from main import main as pipeline_main
    pipeline_main()


def render_upload_widget(*, expanded: bool):
    """Sidebar block: file uploader + Process button. Returns True if the
    pipeline ran (caller should clear cache + rerun)."""
    with st.expander('🔄 Upload OOTP CSVs', expanded=expanded):
        st.caption('Drop in the OOTP CSVs from your save game. Pipeline runs once on upload; results are cached until the next upload.')
        uploaded = st.file_uploader(
            'CSV files',
            accept_multiple_files=True,
            type='csv',
            label_visibility='collapsed',
        )
        if not uploaded:
            st.caption('**Required**: ' + ', '.join(sorted(REQUIRED_CSVS)))
            st.caption('**Optional** (adds IP / PA display columns only): ' + ', '.join(sorted(OPTIONAL_CSVS)))
            return False

        names = {f.name for f in uploaded}
        missing = REQUIRED_CSVS - names
        if missing:
            st.warning('Missing required CSV(s): ' + ', '.join(sorted(missing)))
            return False

        extra = names - ACCEPTED_CSVS
        if extra:
            st.info('Will ignore: ' + ', '.join(sorted(extra)))

        if st.button('Process upload (~30s)', width='stretch', type='primary'):
            with st.spinner('Running pipeline…'):
                process_uploaded(uploaded)
            st.success('Pipeline finished. Refreshing…')
            return True
    return False


# ---------- Sidebar ----------

with st.sidebar:
    st.title('⚾ Pistachio')
    st.caption('OOTP roster construction')

    if not has_cached_data():
        st.warning('No data loaded yet. Upload the OOTP CSVs to begin.')
        if render_upload_widget(expanded=True):
            st.cache_data.clear()
            st.rerun()
        st.stop()  # nothing else makes sense without data

    orgs = get_orgs()
    default_team = 'LAA' if 'LAA' in orgs else orgs[0]
    team = st.selectbox('Team', orgs, index=orgs.index(default_team))

    st.markdown('---')
    st.caption(f'Data refreshed {data_age_str()}')

    if render_upload_widget(expanded=False):
        st.cache_data.clear()
        st.rerun()

    if st.button('📊 Build xlsx', width='stretch',
                 help='Write outputs/{team}_roster_system.xlsx.'):
        with st.spinner(f'Writing {team}_roster_system.xlsx…'):
            main_build(org=team)
        st.success(f'Saved outputs/{team}_roster_system.xlsx')

    xlsx_path = Path(f'outputs/{team}_roster_system.xlsx')
    if xlsx_path.exists():
        with open(xlsx_path, 'rb') as f:
            st.download_button(
                f'⬇️ Download {team}.xlsx',
                f.read(),
                file_name=xlsx_path.name,
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                width='stretch',
            )


# ---------- Main panel ----------

rh, oh, fh, rp, op, fp = get_rosters(team)

# KPI cards
n_h_placed = sum(len(rh[l]['all']) for l in LEVELS)
n_p_placed = sum(len(rp[l]['all']) for l in LEVELS)
n_overflow = len(oh) + len(op)
hps = [p for l in LEVELS for p in rh[l]['all'] if is_high_potential(p)]

st.title(f'{team} organisation')

c1, c2, c3, c4 = st.columns(4)
c1.metric('Hitters placed', n_h_placed)
c2.metric('Pitchers placed', n_p_placed)
c3.metric('High-potential prospects', len(hps))
c4.metric('Release pool', n_overflow)

tab_overview, tab_rosters = st.tabs(['Overview', 'Rosters by level'])

# ---------- Overview tab ----------

with tab_overview:
    col_lineup, col_hps = st.columns([3, 2])

    with col_lineup:
        st.subheader('MLB starting nine')
        rows = []
        for pos in POSITIONS:
            p = rh['MLB']['starters'].get(pos)
            if p:
                rows.append({
                    'Pos': pos,
                    'Player': p['name'],
                    'Age': p['age'],
                    'wOBA': round(p.get('wOBA') or 0, 3),
                    'pos_adj': round(p.get(f'{pos}_adj') or 0, 2),
                })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')

        # Platoon batting orders + R/G — the migrated org-report bits
        st.markdown('**Batting orders**')
        for label, vs_key in [('vs RHP', 'wOBAR'), ('vs LHP', 'wOBAL')]:
            split_starters = rh['MLB'].get(f'starters_vs{vs_key[-1]}', {})
            name_to_slot, rpg = _platoon_lineup_extras(split_starters, vs_key)
            order_rows = []
            for pos in POSITIONS:
                p = split_starters.get(pos)
                if not p:
                    continue
                slot = name_to_slot.get(p['name'])
                order_rows.append({
                    'Slot': slot,
                    'Pos': pos,
                    'Player': p['name'],
                    vs_key: round(p.get(vs_key) or 0, 3),
                })
            df = pd.DataFrame(order_rows).sort_values('Slot')
            st.markdown(f'**{label}** — Est. R/G **{rpg:.2f}**')
            st.dataframe(df, hide_index=True, width='stretch')

    with col_hps:
        st.subheader('HP hitters')
        if hps:
            hp_rows = []
            for lvl in LEVELS:
                for p in rh[lvl]['all']:
                    if is_high_potential(p):
                        hp_rows.append({
                            'Player': p['name'],
                            'Lvl': lvl,
                            'Age': p['age'],
                            'Pos': p.get('pos_adj'),
                            'wOBA': round(p.get('wOBA') or 0, 3),
                            'wOBAP': round(p.get('wOBAP') or 0, 3),
                        })
            hp_df = pd.DataFrame(hp_rows).sort_values('wOBAP', ascending=False)
            st.dataframe(hp_df, hide_index=True, width='stretch', height=400)
        else:
            st.info(f'No high-potential hitters in {team}.')

    # Second row: HP pitchers + currently unavailable players.
    col_hpp, col_inj = st.columns(2)

    with col_hpp:
        st.subheader('HP pitchers')
        hp_pitchers = []
        for lvl in LEVELS:
            for p in rp[lvl]['all']:
                if is_high_potential_pitcher(p):
                    hp_pitchers.append({
                        'Player': p['name'],
                        'Lvl': lvl,
                        'Age': p['age'],
                        'Role': p.get('_role', '?'),
                        'pwOBA': round(p.get('pwOBA') or 0, 3),
                        'pwOBAP': round(p.get('pwOBAP') or 0, 3),
                    })
        if hp_pitchers:
            hpp_df = pd.DataFrame(hp_pitchers).sort_values('pwOBAP')
            st.dataframe(hpp_df, hide_index=True, width='stretch', height=400)
        else:
            st.info(f'No high-potential pitchers in {team}.')

    with col_inj:
        st.subheader('Currently unavailable')
        st.caption('Pulled out of placement via OOTP injury flag or `injured.txt`. Re-runs include them once the flag clears.')
        inj_rows = []
        for p in fh:
            inj_rows.append({
                'Player': p['name'],
                'Type': 'Hitter',
                'Age': p['age'],
                'Pos / Role': p.get('pos_adj') or '',
                'wOBA / pwOBA': round(p.get('wOBA') or 0, 3),
            })
        for p in fp:
            inj_rows.append({
                'Player': p['name'],
                'Type': 'Pitcher',
                'Age': p['age'],
                'Pos / Role': p.get('_role') or 'P',
                'wOBA / pwOBA': round(p.get('pwOBA') or 0, 3),
            })
        if inj_rows:
            inj_df = pd.DataFrame(inj_rows).sort_values(['Type', 'Player'])
            st.dataframe(inj_df, hide_index=True, width='stretch', height=400)
        else:
            st.success(f'No flagged players in {team}.')


# ---------- Rosters tab ----------

with tab_rosters:
    st.subheader(f'{team} rosters by level')
    for lvl in LEVELS:
        with st.expander(f'{lvl}  —  {len(rh[lvl]["all"])} hitters / {len(rp[lvl]["all"])} pitchers',
                         expanded=(lvl == 'MLB')):
            col_h, col_p = st.columns(2)

            with col_h:
                st.markdown('**Hitters — starters**')
                rows = []
                for pos in POSITIONS:
                    p = rh[lvl]['starters'].get(pos)
                    if p:
                        rows.append({
                            'Pos': pos,
                            'Player': p['name'],
                            'Age': p['age'],
                            'wOBA': round(p.get('wOBA') or 0, 3),
                            'wOBAP': round(p.get('wOBAP') or 0, 3),
                        })
                st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')

                st.markdown('**Bench**')
                brows = []
                for role, p in rh[lvl]['bench_roles']:
                    if p:
                        brows.append({
                            'Role': role,
                            'Player': p['name'],
                            'Age': p['age'],
                            'wOBA': round(p.get('wOBA') or 0, 3),
                        })
                    else:
                        brows.append({'Role': role, 'Player': '(none)', 'Age': None, 'wOBA': None})
                st.dataframe(pd.DataFrame(brows), hide_index=True, width='stretch')

            with col_p:
                st.markdown('**Pitchers**')
                prows = []
                for p in rp[lvl]['all']:
                    role = p.get('_role', '?')
                    metric = p.get('pwOBA')
                    prows.append({
                        'Role': role,
                        'Player': p['name'],
                        'Age': p['age'],
                        'pwOBA': round(metric, 3) if metric is not None else None,
                        'pwOBAP': round(p.get('pwOBAP') or 0, 3) if p.get('pwOBAP') is not None else None,
                    })
                prows.sort(key=lambda r: (r['Role'] != 'SP', r.get('pwOBA') or 9))
                st.dataframe(pd.DataFrame(prows), hide_index=True, width='stretch')
