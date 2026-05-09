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
from build_pitcher_system import main as build_pitchers, is_high_potential_pitcher, SP_PER_LEVEL, RP_PER_LEVEL
from build_excel import main_build, _platoon_lineup_extras, _hitter_top_level, _pitcher_top_level

POSITIONS = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH']
HITTERS_JSON = 'outputs/hitters.json'
PITCHERS_JSON = 'outputs/pitchers.json'


def hand_label(throws):
    """OOTP throws code to a one-letter label for table display.
    1 → 'R', 2 → 'L', everything else → ''."""
    if throws == 2:
        return 'L'
    if throws == 1:
        return 'R'
    return ''

REQUIRED_CSVS = {
    'players.csv',
    'players_scouted_ratings.csv',
}
# Optional but accepted. The career-stats CSVs populate the IP / PA display
# columns and the years-at-level service-time data. teams.csv drives the
# R(DLR) DSL-team count — without it, every org defaults to 1 DSL team and
# the R(DLR) best/rest split for 2-DSL orgs won't trigger.
OPTIONAL_CSVS = {
    'players_career_pitching_stats.csv',
    'players_career_batting_stats.csv',
    'teams.csv',
}
ACCEPTED_CSVS = REQUIRED_CSVS | OPTIONAL_CSVS

st.set_page_config(page_title='Pistachio', layout='wide', page_icon='⚾')


# ---------- Cached data layer ----------

def _data_signature() -> tuple:
    """A cheap key that changes whenever the cached JSONs change. Used to
    auto-invalidate get_orgs / get_rosters when a fresh upload lands."""
    h = os.path.getmtime(HITTERS_JSON) if os.path.exists(HITTERS_JSON) else 0
    p = os.path.getmtime(PITCHERS_JSON) if os.path.exists(PITCHERS_JSON) else 0
    return (h, p)


@st.cache_data
def get_orgs(_sig: tuple):
    """All org abbreviations present in the cached hitters.json."""
    rows = json.load(open(HITTERS_JSON))['rows']
    return sorted({r['org'] for r in rows if r.get('org')})


@st.cache_data(show_spinner='Building rosters…')
def get_rosters(team: str, _sig: tuple):
    """Build hitter + pitcher rosters for a team. Cheap once cached.
    The _sig tuple (file mtimes) is part of the cache key so the cache
    automatically invalidates whenever the underlying JSONs change —
    important because the hitter/pitcher builders also re-detect injuries
    from the OOTP players.csv on every call, and that detection has to
    line up with the JSON content."""
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


@st.cache_data(show_spinner=False)
def detect_head_scout_id(csv_dir_str: str) -> int | None:
    """Cached Streamlit wrapper around reader.detect_head_scout_id (the
    canonical implementation, also used by app.py refresh)."""
    from reader import detect_head_scout_id as _impl
    return _impl(csv_dir_str)


def process_uploaded(uploaded_files):
    """Save the uploads to a temp dir, point config.filepath at it, set
    config.ID to the detected head scout (or -1 for OSA based on the
    session toggle), and run the full metrics pipeline. Outputs land in
    the normal outputs/ dir."""
    tmpdir = Path(tempfile.mkdtemp(prefix='pistachio_'))
    for f in uploaded_files:
        if f.name in ACCEPTED_CSVS:
            (tmpdir / f.name).write_bytes(f.getbuffer())
    config.filepath = tmpdir
    # Apply the user's ratings-source preference to this pipeline run, so
    # the first build for a new uploader doesn't accidentally use the
    # config.py default coach_id (which is whatever the repo shipped with).
    detected = detect_head_scout_id(str(tmpdir))
    source = st.session_state.get('rating_source', 'Head Scout')
    if source == 'OSA':
        config.ID = -1
    elif detected is not None:
        config.ID = detected
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

    # Session-scoped gate: every new session must upload fresh CSVs before
    # the app renders any data. We don't trust the on-disk JSONs from a
    # prior session because they may be stale or from a different OOTP
    # save than what the user wants to look at this time.
    if not st.session_state.get('data_loaded'):
        st.warning('No data loaded yet. Upload the OOTP CSVs to begin.')
        if render_upload_widget(expanded=True):
            st.session_state.data_loaded = True
            st.cache_data.clear()
            st.rerun()
        st.stop()  # nothing else makes sense without data

    sig = _data_signature()
    orgs = get_orgs(sig)
    default_team = 'LAA' if 'LAA' in orgs else orgs[0]
    team = st.selectbox('Team', orgs, index=orgs.index(default_team))

    st.markdown('---')

    # Ratings source toggle. Pipeline runs only against config.ID, so we
    # apply the user's selection to config every render and offer a Recalc
    # button that re-runs the pipeline if the selection differs from
    # whatever produced the cached JSONs.
    head_scout = detect_head_scout_id(str(config.filepath))
    if head_scout is None:
        st.caption('Ratings source: head-scout id not detectable from CSV')
    else:
        if 'rating_source' not in st.session_state:
            st.session_state.rating_source = 'Head Scout'
        rating_source = st.radio(
            'Ratings',
            options=['Head Scout', 'OSA'],
            captions=[f'coach_id = {head_scout}', 'coach_id = -1 (OSA)'],
            key='rating_source',
            horizontal=True,
        )
        # Apply selection to config immediately so any subsequent pipeline
        # call this session uses it. Cached JSONs may still reflect the
        # OLD config.ID — Recalc updates them.
        config.ID = head_scout if rating_source == 'Head Scout' else -1
        # Track which ID produced the JSON so we can show "(stale)" when
        # the user toggles before recalcing.
        active_id = st.session_state.get('active_rating_id', config.ID)
        if active_id != config.ID:
            st.warning(f'Ratings switched. Click Recalc to refresh data.')
            if st.button('🔁 Recalc (~30s)', width='stretch', type='primary'):
                with st.spinner('Recalculating with new ratings…'):
                    from main import main as pipeline_main
                    pipeline_main()
                st.session_state.active_rating_id = config.ID
                st.cache_data.clear()
                st.rerun()
        else:
            # First load: remember which ID is active
            st.session_state.active_rating_id = config.ID

    st.markdown('---')
    st.caption(f'Data refreshed {data_age_str()}')

    if render_upload_widget(expanded=False):
        st.session_state.active_rating_id = config.ID
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

rh, oh, fh, rp, op, fp = get_rosters(team, sig)

# KPI cards. Iterate the actual roster keys (LEVELS doesn't include the
# R(DLR) sub-team keys produced by the best/rest split for 2+ DSL orgs).
n_h_placed = sum(len(rh[l]['all']) for l in rh.keys())
n_p_placed = sum(len(rp[l]['all']) for l in rp.keys())
n_overflow = len(oh) + len(op)
hps = [p for l in rh.keys() for p in rh[l]['all'] if is_high_potential(p)]
hps_pitchers = [p for l in rp.keys() for p in rp[l]['all'] if is_high_potential_pitcher(p)]

st.title(f'{team} organisation')

c1, c2, c3, c4 = st.columns(4)
c1.metric('Hitters placed', n_h_placed)
c2.metric('Pitchers placed', n_p_placed)
c3.metric('High-potential prospects', len(hps) + len(hps_pitchers),
          help=f'{len(hps)} hitters + {len(hps_pitchers)} pitchers')
c4.metric('Release pool', n_overflow)

tab_overview, tab_rosters, tab_release, tab_scout_h, tab_scout_p = st.tabs(
    ['Overview', 'Rosters by level', 'Release pool', 'Scout hitters', 'Scout pitchers']
)


# ---------- Cached loaders for the scouting tabs ----------
# Cached on the JSON mtime so they auto-invalidate after a refresh.

@st.cache_data
def load_all_hitters_df(_sig: tuple) -> pd.DataFrame:
    rows = json.load(open(HITTERS_JSON))['rows']
    return pd.DataFrame(rows)


@st.cache_data
def load_all_pitchers_df(_sig: tuple) -> pd.DataFrame:
    rows = json.load(open(PITCHERS_JSON))['rows']
    df = pd.DataFrame(rows)
    if 'throws' in df.columns:
        df['Hand'] = df['throws'].map({1: 'R', 2: 'L'}).fillna('')
    return df

# ---------- Overview tab ----------

with tab_overview:
    # Row 1: MLB position players (left, wide) | MLB pitching staff (right)
    col_pos, col_arms = st.columns([3, 2])

    with col_pos:
        st.subheader('MLB position players')

        st.markdown('**Starting nine**')
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

        st.markdown('**Bench (named roles)**')
        brows = []
        for role, p in rh['MLB']['bench_roles']:
            if p:
                brows.append({
                    'Role': role,
                    'Player': p['name'],
                    'Age': p['age'],
                    'wOBA': round(p.get('wOBA') or 0, 3),
                })
            else:
                brows.append({'Role': role, 'Player': '(Sign FA)', 'Age': None, 'wOBA': None})
        st.dataframe(pd.DataFrame(brows), hide_index=True, width='stretch')

        # Platoon batting orders + R/G — the migrated org-report bits.
        # vs RHP / vs LHP rendered side-by-side for easy comparison.
        st.markdown('**Batting orders**')
        sub_r, sub_l = st.columns(2)
        for sub_col, (label, vs_key) in zip(
            [sub_r, sub_l],
            [('vs RHP', 'wOBAR'), ('vs LHP', 'wOBAL')],
        ):
            with sub_col:
                split_starters = rh['MLB'].get(f'starters_vs{vs_key[-1]}', {})
                backups = rh['MLB'].get(f'backups_vs{vs_key[-1]}', {})
                name_to_slot, rpg = _platoon_lineup_extras(split_starters, vs_key)
                order_rows = []
                for pos in POSITIONS:
                    p = split_starters.get(pos)
                    if not p:
                        continue
                    slot = name_to_slot.get(p['name'])
                    bk = backups.get(pos)
                    order_rows.append({
                        'Slot': slot,
                        'Pos': pos,
                        'Player': p['name'],
                        vs_key: round(p.get(vs_key) or 0, 3),
                        'Backup': bk['name'] if bk else '(Sign FA)',
                    })
                df = pd.DataFrame(order_rows).sort_values('Slot')
                st.markdown(f'**{label}** — R/G **{rpg:.2f}**')
                st.dataframe(df, hide_index=True, width='stretch')

    with col_arms:
        st.subheader('MLB pitching staff')

        rotation = rp['MLB']['starters']
        sp_target = rp['MLB'].get('sp_target', SP_PER_LEVEL)
        rp_target = rp['MLB'].get('rp_target', RP_PER_LEVEL)
        st.markdown(f'**Rotation** ({len(rotation)} of {sp_target} filled)')
        rrows = []
        for i in range(sp_target):
            if i < len(rotation):
                p = rotation[i]
                rrows.append({
                    'Slot': f'SP{i+1}',
                    'Player': p['name'],
                    'Age': p['age'],
                    'Hand': hand_label(p.get('throws')),
                    'pwOBA': round(p.get('pwOBA') or 0, 3),
                    'pwOBAP': round(p.get('pwOBAP') or 0, 3),
                })
            else:
                rrows.append({'Slot': f'SP{i+1}', 'Player': '(Sign FA)', 'Age': None, 'Hand': '', 'pwOBA': None, 'pwOBAP': None})
        st.dataframe(pd.DataFrame(rrows), hide_index=True, width='stretch')

        bullpen = rp['MLB']['bullpen']
        sign_lhp = rp['MLB'].get('sign_lhp', 0)
        st.markdown(f'**Bullpen** ({len(bullpen)} of {rp_target} filled)')
        prows = []
        for i in range(rp_target):
            if i < len(bullpen):
                p = bullpen[i]
                prows.append({
                    'Slot': f'RP{i+1}',
                    'Player': p['name'],
                    'Age': p['age'],
                    'Hand': hand_label(p.get('throws')),
                    'pwOBA': round(p.get('pwOBA') or 0, 3),
                    'pwOBAP': round(p.get('pwOBAP') or 0, 3),
                })
            else:
                # Last `sign_lhp` empty slots are LHP shortfalls — flag them
                # explicitly so the user knows what they need to sign.
                empty_idx = i - len(bullpen)
                empty_total = rp_target - len(bullpen)
                placeholder = '(Sign LHP)' if empty_idx >= empty_total - sign_lhp else '(Sign FA)'
                prows.append({'Slot': f'RP{i+1}', 'Player': placeholder, 'Age': None, 'Hand': '', 'pwOBA': None, 'pwOBAP': None})
        st.dataframe(pd.DataFrame(prows), hide_index=True, width='stretch')

    # Row 2: development pipeline — HP hitters | HP pitchers
    col_hph, col_hpp = st.columns(2)

    with col_hph:
        st.subheader('HP hitters')
        if hps:
            hp_rows = []
            for lvl in rh.keys():
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

    with col_hpp:
        st.subheader('HP pitchers')
        hp_pitchers = []
        for lvl in rp.keys():
            for p in rp[lvl]['all']:
                if is_high_potential_pitcher(p):
                    hp_pitchers.append({
                        'Player': p['name'],
                        'Lvl': lvl,
                        'Age': p['age'],
                        'Hand': hand_label(p.get('throws')),
                        'Role': p.get('_role', '?'),
                        'pwOBA': round(p.get('pwOBA') or 0, 3),
                        'pwOBAP': round(p.get('pwOBAP') or 0, 3),
                    })
        if hp_pitchers:
            hpp_df = pd.DataFrame(hp_pitchers).sort_values('pwOBAP')
            st.dataframe(hpp_df, hide_index=True, width='stretch', height=400)
        else:
            st.info(f'No high-potential pitchers in {team}.')

    # Row 3: who's out
    st.subheader('Currently unavailable')
    st.caption('Pulled out of placement via OOTP injury flag or `injured.txt`. They re-enter the system once the flag clears.')
    inj_rows = []
    for p in fh:
        inj_rows.append({
            'Player': p['name'],
            'Type': 'Hitter',
            'Age': p['age'],
            'Hand': '',  # blank for hitters; kept so the joint table aligns
            'Pos / Role': p.get('pos_adj') or '',
            'wOBA / pwOBA': round(p.get('wOBA') or 0, 3),
        })
    for p in fp:
        inj_rows.append({
            'Player': p['name'],
            'Type': 'Pitcher',
            'Age': p['age'],
            'Hand': hand_label(p.get('throws')),
            'Pos / Role': p.get('_role') or 'P',
            'wOBA / pwOBA': round(p.get('pwOBA') or 0, 3),
        })
    if inj_rows:
        inj_df = pd.DataFrame(inj_rows).sort_values(['Type', 'Player'])
        st.dataframe(inj_df, hide_index=True, width='stretch')
    else:
        st.success(f'No flagged players in {team}.')


# ---------- Rosters tab ----------

with tab_rosters:
    st.subheader(f'{team} rosters by level')
    # Iterate the actual rosters keys so R(DLR) sub-teams (R(DLR)1, R(DLR)2,
    # …) introduced for 2+ DSL orgs each get their own expander.
    for lvl in rh.keys():
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
                        'Hand': hand_label(p.get('throws')),
                        'pwOBA': round(metric, 3) if metric is not None else None,
                        'pwOBAP': round(p.get('pwOBAP') or 0, 3) if p.get('pwOBAP') is not None else None,
                    })
                prows.sort(key=lambda r: (r['Role'] != 'SP', r.get('pwOBA') or 9))
                st.dataframe(pd.DataFrame(prows), hide_index=True, width='stretch')

            # Per-level platoon batting orders + R/G — same logic as the
            # Overview tab's MLB block, applied to whichever level we're
            # rendering. Useful at lower levels too: shows which prospect
            # gets the leadoff / cleanup spot in each matchup.
            st.markdown('**Batting orders**')
            sub_r, sub_l = st.columns(2)
            for sub_col, (label, vs_key) in zip(
                [sub_r, sub_l],
                [('vs RHP', 'wOBAR'), ('vs LHP', 'wOBAL')],
            ):
                with sub_col:
                    split_starters = rh[lvl].get(f'starters_vs{vs_key[-1]}', {})
                    backups = rh[lvl].get(f'backups_vs{vs_key[-1]}', {})
                    name_to_slot, rpg = _platoon_lineup_extras(split_starters, vs_key)
                    order_rows = []
                    for pos in POSITIONS:
                        p = split_starters.get(pos)
                        if not p:
                            continue
                        bk = backups.get(pos)
                        order_rows.append({
                            'Slot': name_to_slot.get(p['name']),
                            'Pos': pos,
                            'Player': p['name'],
                            vs_key: round(p.get(vs_key) or 0, 3),
                            'Backup': bk['name'] if bk else '(Sign FA)',
                        })
                    if order_rows:
                        df_order = pd.DataFrame(order_rows).sort_values('Slot')
                        rpg_str = f'{rpg:.2f}' if not (isinstance(rpg, float) and rpg != rpg) else 'n/a'
                        st.markdown(f'**{label}** — R/G **{rpg_str}**')
                        st.dataframe(df_order, hide_index=True, width='stretch')


# ---------- Release pool tab ----------

with tab_release:
    st.subheader(f'{team} release / overflow pool')
    st.caption("Players who didn't fit any level in this run. The 'Top level' column shows where their bat / stuff would project if a slot were available — useful when backfilling roster gaps.")

    col_h_rel, col_p_rel = st.columns(2)

    with col_h_rel:
        st.markdown(f'**Hitters ({len(oh)})**')
        if oh:
            h_rows = []
            for p in oh:
                h_rows.append({
                    'Player': p['name'],
                    'Age': p['age'],
                    'Pos': p.get('pos_adj') or '',
                    'Top level': _hitter_top_level(p),
                    'wOBA': round(p.get('wOBA') or 0, 3),
                    'wOBAP': round(p.get('wOBAP') or 0, 3),
                    'BestP': round(p.get('bestP') or 0, 1),
                })
            h_df = pd.DataFrame(h_rows).sort_values('BestP', ascending=False)
            st.dataframe(h_df, hide_index=True, width='stretch', height=600)
        else:
            st.success('No hitter overflow.')

    with col_p_rel:
        st.markdown(f'**Pitchers ({len(op)})**')
        if op:
            p_rows = []
            for p in op:
                p_rows.append({
                    'Player': p['name'],
                    'Age': p['age'],
                    'Hand': hand_label(p.get('throws')),
                    'Top level': _pitcher_top_level(p),
                    'pwOBA': round(p.get('pwOBA') or 0, 3),
                    'pwOBAP': round(p.get('pwOBAP') or 0, 3),
                    'sp_warP': round(p.get('sp_warP') or 0, 2) if p.get('sp_warP') is not None else None,
                    'rp_warP': round(p.get('rp_warP') or 0, 2) if p.get('rp_warP') is not None else None,
                })
            p_df = pd.DataFrame(p_rows).sort_values('rp_warP', ascending=False, na_position='last')
            st.dataframe(p_df, hide_index=True, width='stretch', height=600)
        else:
            st.success('No pitcher overflow.')


# ---------- Scout hitters tab ----------
# Cross-org searchable / filterable view, mirroring the old hitters.html.

with tab_scout_h:
    st.subheader('All hitters — scouting view')
    st.caption('Cross-org search across the full pipeline output. Filters compose with each other; the table is sortable on every column.')

    df_h_all = load_all_hitters_df(sig)

    f1, f2, f3, f4 = st.columns([2, 2, 2, 1])
    with f1:
        name_q_h = st.text_input('Name contains', '', key='scout_h_name')
    with f2:
        org_opts_h = sorted(df_h_all['org'].dropna().unique().tolist())
        org_filter_h = st.multiselect('Org', org_opts_h, key='scout_h_org')
    with f3:
        pos_opts_h = sorted(df_h_all['pos_adj'].dropna().unique().tolist())
        pos_filter_h = st.multiselect('Primary pos', pos_opts_h, key='scout_h_pos')
    with f4:
        only_minor_h = st.checkbox('Minors only', value=False, key='scout_h_minor')

    age_min_h = int(df_h_all['age'].min())
    age_max_h = int(df_h_all['age'].max())
    age_range_h = st.slider('Age', age_min_h, age_max_h, (age_min_h, age_max_h), key='scout_h_age')

    mask_h = pd.Series(True, index=df_h_all.index)
    if name_q_h:
        mask_h &= df_h_all['name'].str.contains(name_q_h, case=False, na=False)
    if org_filter_h:
        mask_h &= df_h_all['org'].isin(org_filter_h)
    if pos_filter_h:
        mask_h &= df_h_all['pos_adj'].isin(pos_filter_h)
    if only_minor_h:
        mask_h &= df_h_all['minor'] == 1
    mask_h &= df_h_all['age'].between(age_range_h[0], age_range_h[1])

    filtered_h = df_h_all[mask_h]

    # Curated columns — pos_adj as primary; current and projected splits;
    # WAR-relevant fielding for each position. Mirrors the old hitters.html
    # but compact enough to fit on screen.
    h_display_cols = [
        c for c in [
            'name', 'org', 'minor', 'age', 'pa', 'pos_adj', 'field',
            'wOBA', 'wOBAR', 'wOBAL', 'wOBAP',
            'best', 'bestP', 'best_adj',
            'C_fld', 'SS_fld', '2B_fld', '3B_fld', 'CF_fld', 'LF_fld', 'RF_fld', '1B_fld',
        ] if c in filtered_h.columns
    ]
    st.caption(f'{len(filtered_h)} of {len(df_h_all)} hitters match.')
    st.dataframe(
        filtered_h[h_display_cols].sort_values('bestP', ascending=False, na_position='last'),
        hide_index=True,
        width='stretch',
        height=600,
    )


# ---------- Scout pitchers tab ----------

with tab_scout_p:
    st.subheader('All pitchers — scouting view')
    st.caption('Cross-org search across the full pipeline output. Same filter pattern as Scout hitters.')

    df_p_all = load_all_pitchers_df(sig).copy()
    # Derive a role tag from sp_warP / rp_warP presence — pwoba-viable arms
    # land in one of these buckets.
    def _role_tag(row):
        sp = row.get('sp_warP') is not None and not pd.isna(row.get('sp_warP'))
        rp = row.get('rp_warP') is not None and not pd.isna(row.get('rp_warP'))
        if sp and rp: return 'SP+RP'
        if sp:        return 'SP'
        if rp:        return 'RP'
        return '—'
    df_p_all['Role'] = df_p_all.apply(_role_tag, axis=1)

    f1, f2, f3, f4 = st.columns([2, 2, 2, 1])
    with f1:
        name_q_p = st.text_input('Name contains', '', key='scout_p_name')
    with f2:
        org_opts_p = sorted(df_p_all['org'].dropna().unique().tolist())
        org_filter_p = st.multiselect('Org', org_opts_p, key='scout_p_org')
    with f3:
        role_opts_p = ['SP', 'RP', 'SP+RP', '—']
        role_filter_p = st.multiselect('Role', role_opts_p, key='scout_p_role')
    with f4:
        only_minor_p = st.checkbox('Minors only', value=False, key='scout_p_minor')

    age_min_p = int(df_p_all['age'].min())
    age_max_p = int(df_p_all['age'].max())
    age_range_p = st.slider('Age', age_min_p, age_max_p, (age_min_p, age_max_p), key='scout_p_age')

    mask_p = pd.Series(True, index=df_p_all.index)
    if name_q_p:
        mask_p &= df_p_all['name'].str.contains(name_q_p, case=False, na=False)
    if org_filter_p:
        mask_p &= df_p_all['org'].isin(org_filter_p)
    if role_filter_p:
        mask_p &= df_p_all['Role'].isin(role_filter_p)
    if only_minor_p:
        mask_p &= df_p_all['minor'] == 1
    mask_p &= df_p_all['age'].between(age_range_p[0], age_range_p[1])

    filtered_p = df_p_all[mask_p]

    p_display_cols = [
        c for c in [
            'name', 'org', 'minor', 'age', 'Hand', 'ip', 'Role',
            'pwOBA', 'pwOBAR', 'pwOBAL', 'pwOBAP',
            'sp_war', 'sp_warP', 'rp_war', 'rp_warP',
        ] if c in filtered_p.columns
    ]
    st.caption(f'{len(filtered_p)} of {len(df_p_all)} pitchers match.')
    st.dataframe(
        filtered_p[p_display_cols].sort_values('rp_warP', ascending=False, na_position='last'),
        hide_index=True,
        width='stretch',
        height=600,
    )
