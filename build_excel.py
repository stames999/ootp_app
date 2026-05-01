"""Build Excel output and markdown summary."""
from build_system import main, LEVELS, POSITIONS, ROSTER_SIZES, is_catcher, projected_pos_adj
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

OUTFILE = 'outputs/LAA_hitter_system.xlsx'

# Styles
HEADER_FONT = Font(name='Arial', bold=True, color='FFFFFF', size=11)
HEADER_FILL = PatternFill('solid', start_color='1F4E78')
SECTION_FONT = Font(name='Arial', bold=True, size=11, color='FFFFFF')
SECTION_FILL = PatternFill('solid', start_color='2E75B6')
DEFAULT_FONT = Font(name='Arial', size=10)
PROSPECT_FILL = PatternFill('solid', start_color='E2EFDA')  # light green for high-pot prospects
THIN = Side(border_style='thin', color='CCCCCC')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

LEVEL_COLORS = {
    'MLB': 'C00000',
    'AAA': 'ED7D31',
    'AA': 'FFC000',
    'A+': '70AD47',
    'A': '5B9BD5',
    'R': '7030A0',
    'R(DLR)': '595959',
}

def write_level_sheet(ws, lvl, roster):
    starters = roster['starters']
    bench = roster['bench']
    
    ws['A1'] = f'{lvl} Roster'
    ws['A1'].font = Font(name='Arial', bold=True, size=14, color='FFFFFF')
    ws['A1'].fill = PatternFill('solid', start_color=LEVEL_COLORS[lvl])
    ws.merge_cells('A1:I1')
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 24
    
    use_projected = lvl not in ('MLB', 'AAA')
    pos_label = 'projected pos_adj' if use_projected else 'pos_adj'
    headers = ['Slot', 'Name', 'Age', 'Pos', 'wOBA', 'wOBAP', 'Gap', pos_label, 'Notes']
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=3, column=col, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal='center')
        c.border = BORDER
    
    row = 4
    sec = ws.cell(row=row, column=1, value='STARTERS')
    sec.font = SECTION_FONT
    sec.fill = SECTION_FILL
    sec.alignment = Alignment(horizontal='center')
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
    row += 1
    
    def write_player_row(row, p, slot_label):
        if p:
            woba = p.get('wOBA') or 0
            wobap = p.get('wOBAP') or 0
            gap = wobap - woba
            note = ''
            if gap >= 0.10: note = 'High dev gap (prospect)'
            elif woba >= 0.320: note = 'Above-avg MLB bat'
            ws.cell(row=row, column=1, value=slot_label)
            ws.cell(row=row, column=2, value=p['name'])
            ws.cell(row=row, column=3, value=p['age'])
            ws.cell(row=row, column=4, value=p['pos_adj'])
            ws.cell(row=row, column=5, value=round(woba, 3))
            ws.cell(row=row, column=6, value=round(wobap, 3))
            ws.cell(row=row, column=7, value=round(gap, 3))
            # Pos value: at minor levels show projected (current pos_adj + bat dev), else current
            if use_projected:
                # Use projected at player's primary position
                pos_val = projected_pos_adj(p, p['pos_adj']) or 0
            else:
                pos_val = p.get('best_adj') or 0
            ws.cell(row=row, column=8, value=round(pos_val, 2))
            ws.cell(row=row, column=9, value=note)
            if gap >= 0.10:
                for col in range(1, 10):
                    ws.cell(row=row, column=col).fill = PROSPECT_FILL
            elif woba >= 0.320:
                for col in range(1, 10):
                    ws.cell(row=row, column=col).fill = PatternFill('solid', start_color='FFF2CC')
        else:
            ws.cell(row=row, column=1, value=slot_label)
            ws.cell(row=row, column=2, value='-- empty --').font = Font(name='Arial', italic=True, color='999999')
        ws.cell(row=row, column=1).font = Font(name='Arial', bold=True, size=10)
        for col in range(1, 10):
            ws.cell(row=row, column=col).border = BORDER
            if not ws.cell(row=row, column=col).font.bold:
                ws.cell(row=row, column=col).font = DEFAULT_FONT
    
    for pos in POSITIONS:
        write_player_row(row, starters.get(pos), pos)
        row += 1
    
    sec = ws.cell(row=row, column=1, value='BENCH / DEPTH')
    sec.font = SECTION_FONT
    sec.fill = SECTION_FILL
    sec.alignment = Alignment(horizontal='center')
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
    row += 1
    
    for p in bench:
        write_player_row(row, p, '—')
        gap = (p.get('wOBAP') or 0) - (p.get('wOBA') or 0)
        if gap >= 0.10:
            ws.cell(row=row, column=9, value='Prospect (depth)')
        elif is_catcher(p):
            ws.cell(row=row, column=9, value='Backup C')
        else:
            ws.cell(row=row, column=9, value='Depth')
        row += 1
    
    widths = [8, 26, 6, 7, 8, 9, 7, 8, 22]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64+i)].width = w
    
    row += 1
    ws.cell(row=row, column=1, value=f'Total: {len(roster["all"])} players (target {ROSTER_SIZES[lvl]})').font = Font(name='Arial', italic=True, size=9, color='666666')

def write_summary(ws, rosters, overflow):
    ws['A1'] = 'LAA Hitter System - Summary'
    ws['A1'].font = Font(name='Arial', bold=True, size=14)
    ws.merge_cells('A1:F1')
    
    headers = ['Level', 'Total', 'Catchers', 'Top Prospect', 'Avg Best', 'Avg BestP']
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=3, column=col, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal='center')
        c.border = BORDER
    
    row = 4
    for lvl in LEVELS:
        all_p = rosters[lvl]['all']
        cs = [p for p in all_p if is_catcher(p)]
        top = max(all_p, key=lambda p: p['bestP'] or -99)
        avg_best = sum(p['best'] or 0 for p in all_p) / len(all_p) if all_p else 0
        avg_pot = sum(p['bestP'] or 0 for p in all_p) / len(all_p) if all_p else 0
        ws.cell(row=row, column=1, value=lvl).font = Font(name='Arial', bold=True, color=LEVEL_COLORS[lvl])
        ws.cell(row=row, column=2, value=len(all_p))
        ws.cell(row=row, column=3, value=len(cs))
        ws.cell(row=row, column=4, value=f"{top['name']} ({top['age']}, {top['bestP']:.1f})")
        ws.cell(row=row, column=5, value=round(avg_best, 2))
        ws.cell(row=row, column=6, value=round(avg_pot, 2))
        for col in range(1, 7):
            ws.cell(row=row, column=col).border = BORDER
            if col != 1: ws.cell(row=row, column=col).font = DEFAULT_FONT
        row += 1
    
    # Overflow row
    ws.cell(row=row, column=1, value='Release Pool').font = Font(name='Arial', bold=True, color='999999')
    ws.cell(row=row, column=2, value=len(overflow))
    ws.cell(row=row, column=3, value=sum(1 for p in overflow if is_catcher(p)))
    if overflow:
        top = max(overflow, key=lambda p: p['bestP'] or -99)
        ws.cell(row=row, column=4, value=f"{top['name']} ({top['age']}, {top['bestP']:.1f})")
    avg_best = sum(p['best'] or 0 for p in overflow) / len(overflow) if overflow else 0
    avg_pot = sum(p['bestP'] or 0 for p in overflow) / len(overflow) if overflow else 0
    ws.cell(row=row, column=5, value=round(avg_best, 2))
    ws.cell(row=row, column=6, value=round(avg_pot, 2))
    for col in range(1, 7):
        ws.cell(row=row, column=col).border = BORDER
        if col != 1: ws.cell(row=row, column=col).font = DEFAULT_FONT
    
    widths = [14, 8, 10, 32, 12, 12]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64+i)].width = w
    
    # Methodology notes
    row += 3
    ws.cell(row=row, column=1, value='Methodology').font = Font(name='Arial', bold=True, size=12)
    row += 1
    notes = [
        'Hybrid level assignment combines:',
        '  - Age developmental floor (typical age-by-level expectations)',
        '  - Current ability ceiling (best WAR projection prevents overmatching)',
        '  - Potential bump (top prospects pushed up 1 level)',
        '',
        'Roster sizes: MLB/AAA/AA/A+/A = 13, R/R(DLR) = 15. Hitters only (95 total).',
        '',
        'Catchers: 2 per level (starter + backup), pre-allocated before non-catchers.',
        '',
        'Starter selection:',
        '  - MLB & AAA: position-adjusted WAR drives selection (performance focus)',
        '  - AA and below: bestP drives selection (development focus)',
        '',
        'Light-green rows = top prospects (bestP >= 3.0).',
    ]
    for n in notes:
        ws.cell(row=row, column=1, value=n).font = Font(name='Arial', size=10)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        row += 1

def write_overflow(ws, overflow):
    ws['A1'] = 'Release / Overflow Pool'
    ws['A1'].font = Font(name='Arial', bold=True, size=14, color='FFFFFF')
    ws['A1'].fill = PatternFill('solid', start_color='595959')
    ws.merge_cells('A1:E1')
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 22
    
    headers = ['Name', 'Age', 'Pos', 'Best', 'BestP']
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=3, column=col, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.border = BORDER
    
    row = 4
    overflow_sorted = sorted(overflow, key=lambda p: (p['bestP'] or -99), reverse=True)
    for p in overflow_sorted:
        ws.cell(row=row, column=1, value=p['name'])
        ws.cell(row=row, column=2, value=p['age'])
        ws.cell(row=row, column=3, value=p['pos_adj'])
        ws.cell(row=row, column=4, value=round(p['best'], 1))
        ws.cell(row=row, column=5, value=round(p['bestP'], 1))
        for col in range(1, 6):
            ws.cell(row=row, column=col).border = BORDER
            ws.cell(row=row, column=col).font = DEFAULT_FONT
        row += 1
    
    widths = [26, 6, 8, 10, 10]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64+i)].width = w

def main_build():
    rosters, overflow = main()
    wb = Workbook()
    wb.remove(wb.active)
    
    # Summary first
    ws = wb.create_sheet('Summary')
    write_summary(ws, rosters, overflow)
    
    # Each level
    for lvl in LEVELS:
        sheet_name = lvl.replace('(', '_').replace(')', '')
        ws = wb.create_sheet(sheet_name)
        write_level_sheet(ws, lvl, rosters[lvl])
    
    # Overflow
    ws = wb.create_sheet('Release_Pool')
    write_overflow(ws, overflow)
    
    wb.save(OUTFILE)
    print(f'Saved: {OUTFILE}')

if __name__ == '__main__':
    main_build()
