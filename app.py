"""
Math Report Card Generator v2 — Mr. Youssef Ahmed / Cambridge IGCSE
Features:
  - Dynamic assignment discovery (auto-detects all HW/Quiz/Mock from CSV)
  - Codes from attendance sheet col 0
  - Assistant filter
  - PDF generation via ReportLab
  - Editable preview fields saved back to report
  - WhatsApp direct link with parent number from data CSV col 3
  - IGCSE branding + logo
"""

import os, sys, csv, io, json, re, threading, webbrowser, time
import urllib.parse, zipfile, tempfile, traceback
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, redirect

# ReportLab
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable, KeepTogether)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

app = Flask(__name__)
app.secret_key = 'igcse-math-reports-v2'

# ── Global state ───────────────────────────────────────────────────────────────
STATE = {
    'students': [],          # list of student dicts
    'assignments': [],       # discovered from CSV header
    'recommendations': {},   # name -> {rec, problems, edits:{field->value}}
    'assistants': [],        # list of assistant names
}

# ── Colours ────────────────────────────────────────────────────────────────────
NAVY   = colors.HexColor('#1F3A6E')
GOLD   = colors.HexColor('#C07A00')
RED    = colors.HexColor('#B71C1C')
GREEN  = colors.HexColor('#2E7D32')
BLUE2  = colors.HexColor('#2C5F8A')
LGRAY  = colors.HexColor('#F2F4F8')
LGOLD  = colors.HexColor('#FFF8E7')
LBLUE  = colors.HexColor('#D6E4F7')
WHITE  = colors.white
BLACK  = colors.HexColor('#1A1A2E')
LGREEN = colors.HexColor('#DCFCE7')
LRED   = colors.HexColor('#FEE2E2')
LYEL   = colors.HexColor('#FEF9C3')

# ── CSV Parsing ────────────────────────────────────────────────────────────────
def parse_csv_bytes(data):
    text = data.decode('utf-8-sig', errors='replace')
    return list(csv.reader(io.StringIO(text)))

def discover_assignments(headers):
    """Dynamically find all Hw/Quiz/Mock columns from the grades CSV header.
    Uses a tight regex that matches only the label column (e.g. 'Hw 1', 'Mock 4 Paper 2')
    and not derived columns like 'Mock 4 Paper 2 Grade' or 'Hw 1 Percentage'.
    """
    # Matches exactly: Hw N, Quiz N, Mock N, or Mock N Paper N — nothing after
    LABEL_RE = re.compile(r'^(Hw|Quiz|Mock)\s+\d+(\s+Paper\s+\d+)?$', re.IGNORECASE)
    assignments = []
    for i, h in enumerate(headers):
        hs = h.strip()
        if not LABEL_RE.match(hs):
            continue
        grade_col = i + 1
        outof_col = None
        for j in range(i + 1, min(i + 10, len(headers))):
            if headers[j].strip().lower() == 'out of':
                outof_col = j
                break
        if grade_col < len(headers) and outof_col:
            hl = hs.lower()
            typ = 'hw' if hl.startswith('hw') else ('mock' if hl.startswith('mock') else 'quiz')
            assignments.append({'name': hs, 'label_col': i,
                                'grade_col': grade_col, 'outof_col': outof_col, 'type': typ})
    assignments.sort(key=lambda a: a['label_col'])
    return assignments

def calc_pct(grade, outof):
    try:
        g, o = float(grade), float(outof)
        return f'{round(g/o*100)}%' if o else ''
    except:
        return ''

def is_numeric(s):
    try: float(s); return True
    except: return False

def is_missing(g):     return not g or g.lower() == 'missing'
def is_not_checked(g): return bool(g and 'not checked' in g.lower())

def load_all_data(data_rows, grades_rows, att_rows):
    # ── Discover assignments ──────────────────────────────────────────────────
    assignments = discover_assignments(grades_rows[0])
    STATE['assignments'] = assignments

    # ── Grade lookup by student name ──────────────────────────────────────────
    grade_map = {}       # name.lower() -> row
    assistant_map = {}   # name.lower() -> assistant name
    for row in grades_rows[1:]:
        name = row[1].strip() if len(row) > 1 else ''
        if name:
            grade_map[name.lower()] = row
            assistant_map[name.lower()] = row[0].strip() if row[0].strip() else 'Unassigned'

    # ── Attendance: codes from col 0, dates from row[1][5:] ──────────────────
    att_date_row = att_rows[1] if len(att_rows) > 1 else []
    dates = [d.strip() for d in att_date_row[5:] if d.strip()]
    att_map  = {}   # name.lower() -> row
    code_map = {}   # name.lower() -> code (from att col 0)
    for row in att_rows[2:]:
        name = row[1].strip() if len(row) > 1 else ''
        if name:
            att_map[name.lower()]  = row
            code_map[name.lower()] = row[0].strip()

    # ── Data CSV: parent number from col 3 ───────────────────────────────────
    parent_map = {}  # name.lower() -> parent phone
    for row in data_rows[1:]:
        if not row or not row[1].strip(): continue
        name = row[1].strip()
        phone = row[3].strip() if len(row) > 3 else ''
        parent_map[name.lower()] = phone

    # ── Build student list ────────────────────────────────────────────────────
    students = []
    assistants_seen = set()

    for row in data_rows[1:]:
        if not row or not row[1].strip(): continue
        name  = row[1].strip()
        nl    = name.lower()
        code  = code_map.get(nl, row[0].strip())  # prefer att code
        grow  = grade_map.get(nl)
        aname = assistant_map.get(nl, 'Unassigned')
        assistants_seen.add(aname)
        parent_phone = parent_map.get(nl, '')

        # Grades for each discovered assignment
        grade_data = []
        for asgn in assignments:
            gi, oi = asgn['grade_col'], asgn['outof_col']
            g = grow[gi].strip() if grow and gi < len(grow) else ''
            o = grow[oi].strip() if grow and oi < len(grow) else ''
            grade_data.append({
                'name': asgn['name'],
                'type': asgn['type'],
                'grade': g, 'outof': o,
                'pct': calc_pct(g, o)
            })

        # Attendance
        arow = att_map.get(nl)
        att = []
        if arow:
            for i, d in enumerate(dates):
                val = arow[5+i].strip().lower() if 5+i < len(arow) else ''
                if   val == 'absent': att.append({'date': d, 'excused': False})
                elif val == 'excuse': att.append({'date': d, 'excused': True})

        # Averages
        hw_scored  = [g for g in grade_data if g['type']=='hw' and is_numeric(g['grade']) and is_numeric(g['outof']) and float(g['outof'])>0]
        qm_scored  = [g for g in grade_data if g['type'] in ('quiz','mock') and is_numeric(g['grade']) and is_numeric(g['outof']) and float(g['outof'])>0]
        avg_hw = round(sum(float(g['grade'])/float(g['outof'])*100 for g in hw_scored)/len(hw_scored)) if hw_scored else None
        avg_qm = round(sum(float(g['grade'])/float(g['outof'])*100 for g in qm_scored)/len(qm_scored)) if qm_scored else None

        students.append({
            'name': name, 'code': code, 'assistant': aname,
            'parent_phone': parent_phone,
            'grades': grade_data,
            'att': att, 'absent_count': len(att),
            'avg_hw': avg_hw, 'avg_qm': avg_qm,
        })

    STATE['students']   = students
    STATE['assistants'] = sorted(assistants_seen)
    return students

# ── PDF Generation ─────────────────────────────────────────────────────────────
def build_pdf(student, rec='', problems='', edits=None, tmp_path=None):
    edits = edits or {}
    if tmp_path is None:
        tmp_path = tempfile.mktemp(suffix='.pdf')

    doc = SimpleDocTemplate(
        tmp_path, pagesize=A4,
        leftMargin=1.8*cm, rightMargin=1.8*cm,
        topMargin=1.8*cm,  bottomMargin=1.8*cm
    )

    styles = getSampleStyleSheet()
    W = A4[0] - 3.6*cm  # usable width

    def style(name, **kw):
        s = ParagraphStyle(name, **kw)
        return s

    body_s   = style('body',   fontName='Helvetica',      fontSize=9,  leading=13, textColor=BLACK)
    bold_s   = style('bold',   fontName='Helvetica-Bold',  fontSize=9,  leading=13, textColor=BLACK)
    center_s = style('center', fontName='Helvetica',       fontSize=9,  leading=13, textColor=BLACK, alignment=TA_CENTER)
    head_s   = style('head',   fontName='Helvetica-Bold',  fontSize=9,  leading=13, textColor=WHITE, alignment=TA_CENTER)

    def p(text, s=body_s): return Paragraph(str(text) if text else '', s)
    def sp(h=6): return Spacer(1, h)

    def tbl(data, col_widths, style_cmds, row_heights=None, repeat_hdr=True):
        t = Table(data, colWidths=col_widths, rowHeights=row_heights,
                  repeatRows=1 if repeat_hdr and len(data) > 1 else 0,
                  splitByRow=True)
        t.setStyle(TableStyle(style_cmds))
        return t

    BASE = [
        ('FONTNAME',   (0,0),(-1,-1), 'Helvetica'),
        ('FONTSIZE',   (0,0),(-1,-1), 9),
        ('GRID',       (0,0),(-1,-1), 0.5, colors.HexColor('#CCCCCC')),
        ('VALIGN',     (0,0),(-1,-1), 'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1), 6),
        ('RIGHTPADDING',(0,0),(-1,-1),6),
        ('TOPPADDING', (0,0),(-1,-1), 5),
        ('BOTTOMPADDING',(0,0),(-1,-1),5),
    ]

    def H(bg):  return ('BACKGROUND',(0,0),(-1,0), bg)
    def HFC():  return ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'), ('TEXTCOLOR',(0,0),(-1,0),WHITE)
    def ALT(bg, start=1): return ('ROWBACKGROUNDS',(0,start),(-1,-1),[WHITE, bg])

    story = []

    # ── Header banner ─────────────────────────────────────────────────────────
    # Logo box + title
    LOGO_W = 2.2*cm
    title_data = [[
        # Logo cell
        Paragraph('<b><font size=18 color=white>✦</font></b>', style('lc', fontName='Helvetica-Bold', fontSize=14, textColor=WHITE, alignment=TA_CENTER)),
        # Title cell
        [Paragraph('<b><font size=16 color=white>MATHS REPORT CARD</font></b>',
                   style('t', fontName='Helvetica-Bold', fontSize=16, textColor=WHITE, alignment=TA_CENTER)),
         Paragraph('<font size=9 color=#B0C4DE>Mr. Youssef Ahmed  ·  Cambridge IGCSE Course</font>',
                   style('s', fontName='Helvetica', fontSize=9, textColor=colors.HexColor('#B0C4DE'), alignment=TA_CENTER))],
        # IGCSE badge
        Paragraph('<b><font size=10 color=white>IGCSE</font></b>', style('b', fontName='Helvetica-Bold', fontSize=10, textColor=WHITE, alignment=TA_CENTER)),
    ]]
    banner = tbl(title_data, [LOGO_W, W - LOGO_W - 2*cm, 2*cm], [
        ('BACKGROUND',    (0,0),(-1,-1), NAVY),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ('LEFTPADDING',   (0,0),(-1,-1), 10),
        ('RIGHTPADDING',  (0,0),(-1,-1), 10),
        ('TOPPADDING',    (0,0),(-1,-1), 14),
        ('BOTTOMPADDING', (0,0),(-1,-1), 14),
        ('LINEABOVE',     (0,0),(-1,0),  3, GOLD),
        ('GRID',          (0,0),(-1,-1), 0, WHITE),
    ], row_heights=[1.6*cm])
    story += [banner, sp(8)]

    # ── Student info ──────────────────────────────────────────────────────────
    name_val  = edits.get('name',  student['name'])
    code_val  = edits.get('code',  student['code'])
    asst_val  = edits.get('assistant', student['assistant'])
    info_data = [[
        p('Student Name', head_s), p(name_val, bold_s),
        p('Student Code', head_s), p(code_val, bold_s),
    ]]
    info_tbl = tbl(info_data, [W*0.22, W*0.38, W*0.18, W*0.22], BASE + [
        ('BACKGROUND', (0,0),(0,0), NAVY), ('BACKGROUND', (2,0),(2,0), NAVY),
        ('TEXTCOLOR',  (0,0),(0,0), WHITE), ('TEXTCOLOR', (2,0),(2,0), WHITE),
        ('FONTNAME',   (0,0),(0,0),'Helvetica-Bold'), ('FONTNAME',(2,0),(2,0),'Helvetica-Bold'),
    ])
    story += [info_tbl, sp(10)]

    # ── Helper to make a section header ───────────────────────────────────────
    def hex_color(c):
        if hasattr(c, 'hexval'): return c.hexval()
        if hasattr(c, 'hexColor'): return '#' + ''.join(f'{int(x*255):02x}' for x in c.rgb())
        return '#1F3A6E'

    def section_hdr(text, color):
        return Paragraph(f'<b>{text}</b>',
                         style('sh', fontName='Helvetica-Bold', fontSize=10, leading=14,
                               spaceBefore=10, spaceAfter=3, textColor=color))

    def keep(items):
        """Wrap first header + first few rows together so header never orphans."""
        return KeepTogether(items)

    # ── Homework ──────────────────────────────────────────────────────────────
    hw_grades = [g for g in student['grades'] if g['type'] == 'hw']
    if hw_grades:
        hw_data = [[p('Homework', head_s), p('Submission', head_s),
                    p('Mark', head_s), p('Percentage', head_s)]]
        for i, hw in enumerate(hw_grades):
            key   = edits.get(f'hw_{hw["name"]}_key',  hw['name'])
            grade = edits.get(f'hw_{hw["name"]}_grade', hw['grade'])
            outof = edits.get(f'hw_{hw["name"]}_outof', hw['outof'])
            pct   = calc_pct(grade, outof) or hw['pct']
            miss  = is_missing(grade); nc = is_not_checked(grade)
            sub   = 'Missing' if miss else 'Submitted'
            mark  = f"{grade} / {outof}" if outof else (grade or '—')
            pct_s = '—' if (miss or nc) else (pct or '—')
            bg    = WHITE if i%2==0 else LGRAY
            hw_data.append([
                p(f'<b>{key}</b>', bold_s),
                Paragraph(f'<font color="{"#B71C1C" if miss else "#2E7D32"}"><b>{sub}</b></font>', center_s),
                p(mark, center_s), p(pct_s, center_s)
            ])
        hw_tbl = tbl(hw_data, [W*0.2, W*0.25, W*0.3, W*0.25], BASE + [
            H(NAVY), *HFC(), ALT(LGRAY)
        ])
        # Keep header + table together at start; table itself splits by row cleanly
        story += [keep([section_hdr('HOMEWORK GRADES', NAVY), hw_tbl]), sp(8)]

    # ── Quizzes ───────────────────────────────────────────────────────────────
    quiz_grades = [g for g in student['grades'] if g['type'] == 'quiz']
    mock_grades = [g for g in student['grades'] if g['type'] == 'mock']
    qm_all = quiz_grades + mock_grades
    if qm_all:
        qm_data = [[p('Assessment', head_s), p('Mark', head_s), p('Percentage', head_s)]]
        for i, qm in enumerate(qm_all):
            grade = edits.get(f'qm_{qm["name"]}_grade', qm['grade'])
            outof = edits.get(f'qm_{qm["name"]}_outof', qm['outof'])
            pct   = calc_pct(grade, outof) or qm['pct']
            miss  = is_missing(grade); nc = is_not_checked(grade)
            mark  = f"{grade} / {outof}" if outof else (grade or '—')
            pct_s = '—' if (miss or nc) else (pct or '—')
            qm_data.append([p(f'<b>{qm["name"]}</b>', bold_s), p(mark, center_s), p(pct_s, center_s)])
        qm_tbl = tbl(qm_data, [W*0.4, W*0.3, W*0.3], BASE + [
            H(GOLD), *HFC(), ALT(LGOLD)
        ])
        story += [keep([section_hdr('QUIZZES & MOCK EXAMS', GOLD), qm_tbl]), sp(8)]

    # ── Attendance ────────────────────────────────────────────────────────────
    att = student['att']
    att_data = [[p('Unattended Classes', head_s), p('Excused or Not', head_s)]]
    if not att:
        att_data.append([p('No absences recorded \u2713', bold_s), p('\u2014', center_s)])
    else:
        for i, a in enumerate(att):
            lbl = 'Excused' if a['excused'] else 'Not Excused'
            clr = '#2E7D32' if a['excused'] else '#B71C1C'
            att_data.append([p(a['date'], body_s),
                             Paragraph(f'<font color="{clr}"><b>{lbl}</b></font>', center_s)])
    att_tbl = tbl(att_data, [W*0.5, W*0.5], BASE + [
        H(BLUE2), *HFC(), ALT(LBLUE)
    ])
    story += [keep([section_hdr('ATTENDANCE RECORD', BLUE2), att_tbl]), sp(8)]

    # ── Recommendations ───────────────────────────────────────────────────────
    rec_val  = edits.get('rec',      rec)
    prob_val = edits.get('problems', problems)

    def box_section(label, content, color, light):
        hdr = tbl([[p(label, head_s)]], [W], [('BACKGROUND',(0,0),(-1,-1),color),
              ('FONTNAME',(0,0),(-1,-1),'Helvetica-Bold'),('TEXTCOLOR',(0,0),(-1,-1),WHITE),
              ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
              ('GRID',(0,0),(-1,-1),0.5,colors.HexColor('#CCCCCC'))])
        body_content = content if content and content.strip() else '  '
        bdy = tbl([[p(body_content, body_s)]], [W], [
              ('BACKGROUND',(0,0),(-1,-1),light),
              ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),20),
              ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
              ('GRID',(0,0),(-1,-1),0.5,colors.HexColor('#CCCCCC'))])
        return [hdr, bdy]

    story += [keep(box_section('OUR RECOMMENDATIONS', rec_val, GREEN, LGREEN))]
    story += [sp(6)]
    story += [keep(box_section('Problems That Might Be Facing The Student', prob_val, RED, LRED))]

    # ── Footer ────────────────────────────────────────────────────────────────
    story += [sp(10)]
    story.append(Paragraph('<b>BEST OF LUCK !!</b>',
                           style('ft', fontName='Helvetica-Bold', fontSize=13, textColor=GOLD, alignment=TA_CENTER)))

    doc.build(story)
    return tmp_path

# ── Font registration (done once at startup) ────────────────────────────────────
from reportlab.platypus import Image as RLImage, PageBreak
from reportlab.pdfbase.ttfonts import TTFont

_FONTS_REGISTERED = False
def _register_fonts():
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED: return
    try:
        pdfmetrics.registerFont(TTFont('Poppins-Bold',  '/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf'))
        pdfmetrics.registerFont(TTFont('Lora-Italic',   '/usr/share/fonts/truetype/google-fonts/Lora-Italic-Variable.ttf'))
        pdfmetrics.registerFont(TTFont('Caladea-Bold',  '/usr/share/fonts/truetype/crosextra/Caladea-Bold.ttf'))
        pdfmetrics.registerFont(TTFont('Caladea',       '/usr/share/fonts/truetype/crosextra/Caladea-Regular.ttf'))
        _FONTS_REGISTERED = True
    except Exception as e:
        print(f'Font registration warning: {e}')

# Exact colours extracted from docx XML
_COL_HDR_BLUE  = colors.HexColor('#4D93D9')
_COL_LIGHT_BLUE= colors.HexColor('#C0E6F5')
_COL_TEMPLATE_RED = colors.HexColor('#EE0000')
_COL_ROW_ALT   = colors.HexColor('#F5F5F5')

_APP_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else os.path.abspath('.')

def _logo_path(name):
    """Resolve logo path — works locally and on Railway (static folder)."""
    candidates = [
        os.path.join(_APP_DIR, 'static', name),
        os.path.join('/home/claude/template_extracted/word/media',
                     'image1.png' if name == 'logo_math.png' else 'image3.png'),
    ]
    for p in candidates:
        if os.path.exists(p): return p
    return None

def build_quiz_mock_pdf(student, rec='', problems='', edits=None, tmp_path=None):
    """
    Generates a Quiz/Mock-only report card matching the official template exactly.
    Layout:
      Page 1: Header + logos, student info, quiz/mock grades table
      Page 2: Problems that might be facing the student (with watermark)
      Page 3: OUR RECOMMENDATIONS + BEST OF LUCK !! (with watermark)
    """
    _register_fonts()
    edits = edits or {}
    if tmp_path is None:
        tmp_path = tempfile.mktemp(suffix='.pdf')

    W = A4[0] - 3.6*cm   # usable width (1.8cm margins each side)

    doc = SimpleDocTemplate(
        tmp_path, pagesize=A4,
        leftMargin=1.8*cm, rightMargin=1.8*cm,
        topMargin=1.8*cm,  bottomMargin=1.8*cm
    )

    # ── Style helpers ─────────────────────────────────────────────────────────
    def st(name, **kw): return ParagraphStyle(name + '_qm_' + str(id(kw)), **kw)
    def sp(h): return Spacer(1, h)

    s_title  = st('title',  fontName='Poppins-Bold', fontSize=22, textColor=colors.black, alignment=TA_CENTER)
    s_sub1   = st('sub1',   fontName='Lora-Italic',  fontSize=14, textColor=colors.black, alignment=TA_CENTER, spaceAfter=1)
    s_sub2   = st('sub2',   fontName='Caladea-Bold', fontSize=11, textColor=colors.black, alignment=TA_CENTER)
    s_body   = st('body',   fontName='Caladea',      fontSize=10, textColor=colors.black, alignment=TA_LEFT)
    s_bold   = st('bold',   fontName='Caladea-Bold', fontSize=10, textColor=colors.black, alignment=TA_LEFT)
    s_ctr    = st('ctr',    fontName='Caladea',      fontSize=10, textColor=colors.black, alignment=TA_CENTER)
    s_ctr_b  = st('ctrb',   fontName='Caladea-Bold', fontSize=10, textColor=colors.black, alignment=TA_CENTER)
    s_hdr    = st('hdr',    fontName='Poppins-Bold', fontSize=10, textColor=colors.white, alignment=TA_CENTER)
    s_ahdr   = st('ahdr',   fontName='Poppins-Bold', fontSize=9,  textColor=colors.white, alignment=TA_CENTER)
    s_box_h  = st('boxh',   fontName='Poppins-Bold', fontSize=12, textColor=colors.black, alignment=TA_CENTER)
    s_box_b  = st('boxb',   fontName='Caladea',      fontSize=10, textColor=colors.black, alignment=TA_LEFT)
    s_bol    = st('bol',    fontName='Poppins-Bold', fontSize=18, textColor=colors.black, alignment=TA_CENTER)

    def p(text, style=None):
        return Paragraph(str(text) if text is not None else '', style or s_body)

    # ── Logos ─────────────────────────────────────────────────────────────────
    LOGO_SZ = 2.2*cm
    math_logo_path = _logo_path('logo_math.png')
    ya_logo_path   = _logo_path('logo_ya.png')

    def math_logo(): return RLImage(math_logo_path, width=LOGO_SZ, height=LOGO_SZ) if math_logo_path else p('')
    def ya_logo():   return RLImage(ya_logo_path, width=5.2*cm, height=5.0*cm)     if ya_logo_path   else p('')

    # ── PAGE 1 ────────────────────────────────────────────────────────────────
    story = []

    # Header row: [logo] [title block] [logo]
    title_inner = Table(
        [[p('MATHS REPORT CARD', s_title)],
         [p('Mr. Youssef Ahmed', s_sub1)],
         [p('Cambridge OL course', s_sub2)]],
        colWidths=[W - 2*(LOGO_SZ + 0.4*cm)]
    )
    title_inner.setStyle(TableStyle([
        ('ALIGN',        (0,0),(-1,-1), 'CENTER'),
        ('VALIGN',       (0,0),(-1,-1), 'MIDDLE'),
        ('LEFTPADDING',  (0,0),(-1,-1), 0),
        ('RIGHTPADDING', (0,0),(-1,-1), 0),
        ('TOPPADDING',   (0,0),(-1,-1), 2),
        ('BOTTOMPADDING',(0,0),(-1,-1), 2),
        ('LINEBELOW',    (0,0),(-1,-1), 0, colors.white),
    ]))

    hdr_tbl = Table(
        [[math_logo(), title_inner, math_logo()]],
        colWidths=[LOGO_SZ+0.4*cm, W - 2*(LOGO_SZ+0.4*cm), LOGO_SZ+0.4*cm]
    )
    hdr_tbl.setStyle(TableStyle([
        ('VALIGN',       (0,0),(-1,-1), 'MIDDLE'),
        ('ALIGN',        (0,0),(0,-1),  'LEFT'),
        ('ALIGN',        (2,0),(2,-1),  'RIGHT'),
        ('LEFTPADDING',  (0,0),(-1,-1), 0),
        ('RIGHTPADDING', (0,0),(-1,-1), 0),
        ('TOPPADDING',   (0,0),(-1,-1), 0),
        ('BOTTOMPADDING',(0,0),(-1,-1), 0),
        ('GRID',         (0,0),(-1,-1), 0, colors.white),
    ]))

    story += [hdr_tbl, sp(16)]   # <-- EXTRA SPACE after "MATHS REPORT CARD" header

    # Student info row
    name_val = edits.get('name', student['name'])
    code_val = edits.get('code', student['code'])

    info_tbl = Table(
        [[p('<b>Student\nname:</b>', s_bold),
          p(name_val, s_body),
          p('<b>Group:</b>', s_bold),
          Paragraph('<b><font color="#EE0000">Cambridge O-Level</font></b>', s_ctr_b)]],
        colWidths=[W*0.14, W*0.36, W*0.12, W*0.38]
    )
    info_tbl.setStyle(TableStyle([
        ('BOX',          (0,0),(-1,-1), 1.0, colors.black),
        ('INNERGRID',    (0,0),(-1,-1), 0.8, colors.black),
        ('VALIGN',       (0,0),(-1,-1), 'MIDDLE'),
        ('LEFTPADDING',  (0,0),(-1,-1), 6),
        ('RIGHTPADDING', (0,0),(-1,-1), 6),
        ('TOPPADDING',   (0,0),(-1,-1), 7),
        ('BOTTOMPADDING',(0,0),(-1,-1), 7),
        ('BACKGROUND',   (0,0),(-1,-1), colors.white),
    ]))
    story += [info_tbl, sp(10)]

    # Grades table: header row then quiz rows then mock rows
    quiz_g = [g for g in student['grades'] if g['type'] == 'quiz']
    mock_g = [g for g in student['grades'] if g['type'] == 'mock']
    all_qm = quiz_g + mock_g

    sub_hdr_row = [
        p('Assignment\nName', s_ahdr),
        p('Submission', s_hdr),
        p('Mark', s_hdr),
        p('Percentage', s_hdr),
    ]
    grade_rows = [sub_hdr_row]

    for i, g in enumerate(all_qm):
        is_mock = g['type'] == 'mock'
        grade = edits.get(f'qm_{g["name"]}_grade', g['grade'])
        outof = edits.get(f'qm_{g["name"]}_outof', g['outof'])
        pct   = calc_pct(grade, outof) or g.get('pct', '')

        # Display name
        dn = g['name']
        if re.search(r'paper\s*2', dn, re.I): dn = 'Mock 4 (P2)'
        elif re.search(r'paper\s*4', dn, re.I): dn = 'Mock 4 (P4)'

        miss = is_missing(grade)
        nc   = is_not_checked(grade)
        mark = f'{grade}/{outof}' if (outof and not miss and not nc) else (f'/{outof}' if outof else '')
        pct_s = '' if (miss or nc) else pct

        style_name = s_ctr_b if is_mock else s_ctr
        grade_rows.append([
            p(dn, style_name),
            p('', s_ctr),
            p(f'<b>{mark}</b>', s_ctr_b),
            p(pct_s, s_ctr),
        ])

    col_ws = [W*0.22, W*0.28, W*0.25, W*0.25]
    grade_tbl = Table(grade_rows, colWidths=col_ws, repeatRows=1, splitByRow=True)

    style_cmds = [
        ('BOX',          (0,0),(-1,-1), 1.0, colors.black),
        ('INNERGRID',    (0,0),(-1,-1), 0.5, colors.HexColor('#AAAAAA')),
        ('BACKGROUND',   (0,0),(-1,0),  _COL_HDR_BLUE),
        ('VALIGN',       (0,0),(-1,-1), 'MIDDLE'),
        ('LEFTPADDING',  (0,0),(-1,-1), 5),
        ('RIGHTPADDING', (0,0),(-1,-1), 5),
        ('TOPPADDING',   (0,0),(-1,-1), 6),
        ('BOTTOMPADDING',(0,0),(-1,-1), 6),
    ]
    for i in range(1, len(grade_rows)):
        bg = _COL_ROW_ALT if i % 2 == 0 else colors.white
        style_cmds.append(('BACKGROUND', (0,i),(-1,i), bg))

    grade_tbl.setStyle(TableStyle(style_cmds))
    story.append(KeepTogether([grade_tbl]))

    # ── PAGE 2 — Problems ─────────────────────────────────────────────────────
    story.append(PageBreak())

    prob_val = edits.get('problems', problems)
    prob_box = Table(
        [[p('Problems that might be facing the student:', s_box_h)],
         [p(prob_val or ' ', s_box_b)]],
        colWidths=[W]
    )
    prob_box.setStyle(TableStyle([
        ('BOX',          (0,0),(-1,-1), 1.2, colors.black),
        ('LINEBELOW',    (0,0),(-1,0),  1.0, colors.black),
        ('BACKGROUND',   (0,0),(-1,0),  _COL_LIGHT_BLUE),
        ('BACKGROUND',   (0,1),(-1,-1), colors.white),
        ('LEFTPADDING',  (0,0),(-1,-1), 10),
        ('RIGHTPADDING', (0,0),(-1,-1), 10),
        ('TOPPADDING',   (0,0),(0,0),   10),
        ('BOTTOMPADDING',(0,0),(0,0),   10),
        ('TOPPADDING',   (0,1),(-1,-1), 70),
        ('BOTTOMPADDING',(0,1),(-1,-1), 70),
        ('VALIGN',       (0,0),(-1,-1), 'TOP'),
    ]))
    story.append(prob_box)
    story += [sp(30), ya_logo()]

    # ── PAGE 3 — Recommendations + Best of Luck ───────────────────────────────
    story.append(PageBreak())

    rec_val = edits.get('rec', rec)
    rec_box = Table(
        [[p('OUR RECOMMENDATIONS:', s_box_h)],
         [p(rec_val or ' ', s_box_b)]],
        colWidths=[W]
    )
    rec_box.setStyle(TableStyle([
        ('BOX',          (0,0),(-1,-1), 1.2, colors.black),
        ('LINEBELOW',    (0,0),(-1,0),  1.0, colors.black),
        ('BACKGROUND',   (0,0),(-1,0),  _COL_LIGHT_BLUE),
        ('BACKGROUND',   (0,1),(-1,-1), colors.white),
        ('LEFTPADDING',  (0,0),(-1,-1), 10),
        ('RIGHTPADDING', (0,0),(-1,-1), 10),
        ('TOPPADDING',   (0,0),(0,0),   10),
        ('BOTTOMPADDING',(0,0),(0,0),   10),
        ('TOPPADDING',   (0,1),(-1,-1), 70),
        ('BOTTOMPADDING',(0,1),(-1,-1), 70),
        ('VALIGN',       (0,0),(-1,-1), 'TOP'),
    ]))
    story.append(rec_box)
    story += [sp(20), ya_logo(), sp(20)]
    story.append(p('BEST OF LUCK !!', s_bol))

    doc.build(story)
    return tmp_path


# ── Flask Routes ───────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/debug/routes')
def debug_routes():
    """Debug endpoint to list all registered routes"""
    routes = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint != 'static':
            routes.append({
                'path': rule.rule,
                'methods': ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'})),
                'endpoint': rule.endpoint
            })
    return jsonify({'routes': sorted(routes, key=lambda x: x['path']), 'total': len(routes)})

@app.route('/upload', methods=['POST'])
def upload():
    try:
        data_file   = request.files.get('data')
        grades_file = request.files.get('grades')
        att_file    = request.files.get('att')
        if not all([data_file, grades_file, att_file]):
            return jsonify({'ok': False, 'error': 'All 3 CSV files required.'})

        students = load_all_data(
            parse_csv_bytes(data_file.read()),
            parse_csv_bytes(grades_file.read()),
            parse_csv_bytes(att_file.read())
        )
        STATE['recommendations'] = {}

        hw_count   = sum(1 for a in STATE['assignments'] if a['type']=='hw')
        quiz_count = sum(1 for a in STATE['assignments'] if a['type']=='quiz')
        mock_count = sum(1 for a in STATE['assignments'] if a['type']=='mock')

        return jsonify({
            'ok': True, 'count': len(students),
            'assistants': STATE['assistants'],
            'assignments': {'hw': hw_count, 'quiz': quiz_count, 'mock': mock_count,
                            'total': len(STATE['assignments'])},
            'students': [{'name':s['name'], 'code':s['code'], 'assistant':s['assistant'],
                          'avg_hw':s['avg_hw'], 'avg_qm':s['avg_qm'],
                          'absent_count':s['absent_count'], 'grades':s['grades'], 
                          'att':s['att']} for s in students]
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/student/<int:idx>')
def get_student(idx):
    if idx < 0 or idx >= len(STATE['students']):
        return jsonify({'ok': False, 'error': 'Not found'})
    s  = STATE['students'][idx]
    rd = STATE['recommendations'].get(s['name'], {})
    return jsonify({'ok': True, 'student': s,
                    'rec': rd.get('rec',''), 'problems': rd.get('problems',''),
                    'edits': rd.get('edits', {})})

@app.route('/save_rec', methods=['POST'])
def save_rec():
    d    = request.json
    name = d.get('name','')
    if name not in STATE['recommendations']:
        STATE['recommendations'][name] = {}
    STATE['recommendations'][name]['rec']      = d.get('rec','')
    STATE['recommendations'][name]['problems'] = d.get('problems','')
    STATE['recommendations'][name]['edits']    = d.get('edits', {})
    return jsonify({'ok': True})

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data    = request.json
        indices = data.get('indices', [])
        if indices == 'all': indices = list(range(len(STATE['students'])))
        if not indices: return jsonify({'ok': False, 'error': 'No students selected.'})

        tmp_dir = tempfile.mkdtemp()
        results = []
        for i in indices:
            if i >= len(STATE['students']): continue
            s  = STATE['students'][i]
            rd = STATE['recommendations'].get(s['name'], {})
            try:
                safe  = re.sub(r'[^a-zA-Z0-9 ]', '', s['name']).strip().replace(' ', '_')
                fname = f"{s['code'] or 'S'}_{safe}.pdf"
                fpath = os.path.join(tmp_dir, fname)
                build_pdf(s, rec=rd.get('rec',''), problems=rd.get('problems',''),
                          edits=rd.get('edits',{}), tmp_path=fpath)
                results.append({'fname': fname, 'path': fpath, 'ok': True})
            except Exception as e:
                traceback.print_exc()
                results.append({'name': s['name'], 'ok': False, 'error': str(e)})

        ok_r = [r for r in results if r['ok']]
        zip_path = os.path.join(tmp_dir, 'MathReports_IGCSE.zip')
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for r in ok_r: zf.write(r['path'], r['fname'])
        STATE['_last_zip'] = zip_path
        return jsonify({'ok': True, 'generated': len(ok_r),
                        'failed': len(results)-len(ok_r),
                        'errors': [r for r in results if not r['ok']]})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/generate_qm', methods=['POST'])
def generate_qm():
    """Generate Quiz/Mock-only reports in the official template style."""
    try:
        data    = request.json
        indices = data.get('indices', [])
        if indices == 'all': indices = list(range(len(STATE['students'])))
        if not indices: return jsonify({'ok': False, 'error': 'No students selected.'})

        tmp_dir = tempfile.mkdtemp()
        results = []
        for i in indices:
            if i >= len(STATE['students']): continue
            s  = STATE['students'][i]
            rd = STATE['recommendations'].get(s['name'], {})
            try:
                safe  = re.sub(r'[^a-zA-Z0-9 ]', '', s['name']).strip().replace(' ', '_')
                fname = f"{s['code'] or 'S'}_{safe}_QuizMock.pdf"
                fpath = os.path.join(tmp_dir, fname)
                build_quiz_mock_pdf(s, rec=rd.get('rec',''), problems=rd.get('problems',''),
                                    edits=rd.get('edits',{}), tmp_path=fpath)
                results.append({'fname': fname, 'path': fpath, 'ok': True})
            except Exception as e:
                traceback.print_exc()
                results.append({'name': s['name'], 'ok': False, 'error': str(e)})

        ok_r = [r for r in results if r['ok']]
        zip_path = os.path.join(tmp_dir, 'QuizMockReports_IGCSE.zip')
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for r in ok_r: zf.write(r['path'], r['fname'])
        STATE['_last_qm_zip'] = zip_path
        return jsonify({'ok': True, 'generated': len(ok_r),
                        'failed': len(results)-len(ok_r),
                        'errors': [r for r in results if not r['ok']]})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/download_zip')
def download_zip():
    zp = STATE.get('_last_zip')
    if not zp or not os.path.exists(zp): return 'No ZIP ready', 404
    return send_file(zp, as_attachment=True, download_name='MathReports_IGCSE.zip')

@app.route('/download_qm_zip')
def download_qm_zip():
    zp = STATE.get('_last_qm_zip')
    if not zp or not os.path.exists(zp): return 'No ZIP ready', 404
    return send_file(zp, as_attachment=True, download_name='QuizMockReports_IGCSE.zip')

@app.route('/download_single_qm/<int:idx>')
def download_single_qm(idx):
    if idx < 0 or idx >= len(STATE['students']): return 'Not found', 404
    s  = STATE['students'][idx]
    rd = STATE['recommendations'].get(s['name'], {})
    safe  = re.sub(r'[^a-zA-Z0-9 ]', '', s['name']).strip().replace(' ', '_')
    fname = f"{s['code'] or 'S'}_{safe}_QuizMock.pdf"
    tmp   = tempfile.mktemp(suffix='.pdf')
    build_quiz_mock_pdf(s, rec=rd.get('rec',''), problems=rd.get('problems',''),
                        edits=rd.get('edits',{}), tmp_path=tmp)
    return send_file(tmp, as_attachment=True, download_name=fname)

@app.route('/download_single/<int:idx>')
def download_single(idx):
    if idx < 0 or idx >= len(STATE['students']): return 'Not found', 404
    s  = STATE['students'][idx]
    rd = STATE['recommendations'].get(s['name'], {})
    safe  = re.sub(r'[^a-zA-Z0-9 ]', '', s['name']).strip().replace(' ', '_')
    fname = f"{s['code'] or 'S'}_{safe}.pdf"
    tmp   = tempfile.mktemp(suffix='.pdf')
    build_pdf(s, rec=rd.get('rec',''), problems=rd.get('problems',''),
              edits=rd.get('edits',{}), tmp_path=tmp)
    return send_file(tmp, as_attachment=True, download_name=fname)

@app.route('/whatsapp/<int:idx>')
def whatsapp(idx):
    if idx < 0 or idx >= len(STATE['students']): return 'Not found', 404
    s  = STATE['students'][idx]
    rd = STATE['recommendations'].get(s['name'], {})
    lines = [f"📊 *Math Report — {s['name']}*", f"🆔 Code: {s['code']}", ""]
    if s['avg_hw']  is not None: lines.append(f"📝 *Homework Average: {s['avg_hw']}%*")
    if s['avg_qm']  is not None: lines.append(f"📊 *Quiz/Mock Average: {s['avg_qm']}%*")
    lines.append(f"🗓️ *Total Absences: {s['absent_count']}*")
    if rd.get('rec'):      lines += ["", "💡 *Recommendations:*", rd['rec']]
    if rd.get('problems'): lines += ["", "⚠️ *Areas to Improve:*", rd['problems']]
    lines += ["", "_Mr. Youssef Ahmed · Cambridge IGCSE Math_"]
    msg     = '\n'.join(lines)
    encoded = urllib.parse.quote(msg)
    # Use parent phone number (clean: digits only, add + prefix)
    phone   = re.sub(r'\D', '', s.get('parent_phone', ''))
    if phone:
        wa_url = f"https://wa.me/{phone}?text={encoded}"
    else:
        wa_url = f"https://wa.me/?text={encoded}"
    return redirect(wa_url)

@app.route('/email/<int:idx>')
def email_student(idx):
    if idx < 0 or idx >= len(STATE['students']): return 'Not found', 404
    s  = STATE['students'][idx]
    rd = STATE['recommendations'].get(s['name'], {})
    subject = urllib.parse.quote(f"Math Report Card – {s['name']}")
    lines = [f"Dear Parent of {s['name']},", "",
             "Please find a summary of your child's performance in Cambridge IGCSE Math with Mr. Youssef Ahmed.", ""]
    if s['avg_hw']  is not None: lines.append(f"Homework Average: {s['avg_hw']}%")
    if s['avg_qm']  is not None: lines.append(f"Quiz/Mock Average: {s['avg_qm']}%")
    lines.append(f"Total Absences: {s['absent_count']}")
    if rd.get('rec'):      lines += ["", "Recommendations:", rd['rec']]
    if rd.get('problems'): lines += ["", "Areas to Work On:", rd['problems']]
    lines += ["", "Best regards,", "Mr. Youssef Ahmed", "Cambridge IGCSE Math Team"]
    body = urllib.parse.quote('\n'.join(lines))
    return redirect(f"mailto:?subject={subject}&body={body}")

if __name__ == '__main__':
    def open_browser():
        time.sleep(1.2)
        webbrowser.open('http://127.0.0.1:5050')
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host='127.0.0.1', port=5050, debug=False, use_reloader=False)
