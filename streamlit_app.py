"""Pistachio Streamlit front-end.

Run with:
    streamlit run streamlit_app.py

Talks to the same functions as the CLI (`app.py`):
- compute_df()                       — full pipeline (slow, ~30s)
- build_system.main(org)             — hitter rosters from cached JSON
- build_pitcher_system.main(org)     — pitcher rosters from cached JSON
- build_excel.main_build(org)        — write the team xlsx
"""
import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from build_system import main as build_hitters, LEVELS, is_high_potential
from build_pitcher_system import main as build_pitchers
from build_excel import main_build, _platoon_lineup_extras

POSITIONS = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH']
HITTERS_JSON = 'outputs/hitters.json'
PITCHERS_JSON = 'outputs/pitchers.json'

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


# ---------- Sidebar ----------

with st.sidebar:
    st.title('⚾ Pistachio')
    st.caption('OOTP roster construction')

    orgs = get_orgs()
    default_team = 'LAA' if 'LAA' in orgs else orgs[0]
    team = st.selectbox('Team', orgs, index=orgs.index(default_team))

    st.markdown('---')
    st.caption(f'Data refreshed {data_age_str()}')

    if st.button('🔄 Refresh data', width='stretch',
                 help='Rerun the full metrics pipeline. Takes ~30 seconds.'):
        with st.spinner('Running pipeline (~30s)…'):
            from main import main as pipeline_main
            pipeline_main()
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
        st.subheader('High-potential prospects')
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
            st.dataframe(hp_df, hide_index=True, width='stretch', height=600)
        else:
            st.info(f'No high-potential prospects in {team}.')


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
                # rp[lvl]['all'] holds the placed pitchers; sort by role then pwOBA
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
                # SP first, then RP
                prows.sort(key=lambda r: (r['Role'] != 'SP', r.get('pwOBA') or 9))
                st.dataframe(pd.DataFrame(prows), hide_index=True, width='stretch')
