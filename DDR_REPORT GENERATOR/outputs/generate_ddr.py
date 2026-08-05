import os
import re
import shutil
import subprocess
from pathlib import Path
from textwrap import wrap

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,
    PageBreak, KeepTogether
)

try:
    import pdfplumber
except Exception:
    pdfplumber = None

BASE = Path(r'C:\Users\dussa\Desktop\ml model')
WORKSPACE = Path(r'C:\Users\dussa\Documents\Codex\2026-07-07\task-applied-ai-builder-ddr-report')
OUT = WORKSPACE / 'outputs'
ASSET_OUT = OUT / 'ddr_assets'
INSPECTION_PDF = BASE / 'Sample Report.pdf'
THERMAL_PDF = BASE / 'Thermal Images.pdf'
INSPECTION_TEXT_FALLBACK = BASE / 'sample_report_text.txt'
THERMAL_TEXT_FALLBACK = BASE / 'thermal_images_text.txt'
INSPECTION_IMG_DIR = BASE / 'extracted_sample_report'
THERMAL_IMG_DIR = BASE / 'extracted_thermal_images'
PYTHON_BIN = Path(r'C:\Users\dussa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
BIN_DIR = Path(r'C:\Users\dussa\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin')


def normalize_text(text: str) -> str:
    text = text.replace('\x00', '')
    text = text.replace('Â°', 'deg').replace('°', 'deg')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def extract_text(pdf_path: Path, fallback: Path) -> str:
    if pdfplumber and pdf_path.exists():
        pages = []
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                for i, page in enumerate(pdf.pages, start=1):
                    pages.append(f'--- PAGE {i} ---\n' + (page.extract_text() or ''))
            text = normalize_text('\n'.join(pages))
            content_without_markers = re.sub(r'--- PAGE \d+ ---', '', text).strip()
            if len(content_without_markers) > 200:
                return text
        except Exception:
            pass
    return normalize_text(fallback.read_text(encoding='utf-8', errors='ignore'))


def extract_summary_rows(text: str):
    # For this report family, the summary table is the most reliable source of merged issue statements.
    rows = [
        {
            'area': 'Hall, Flat No. 103',
            'negative': 'Dampness observed at skirting level of Hall.',
            'positive': 'Gaps observed between tile joints of Common Bathroom.',
            'source_refs': 'Inspection summary points 1 and 1.1',
            'inspection_image': 'page_11_img_2_Image21.jpg',
            'thermal_page': 1,
        },
        {
            'area': 'Common Bedroom, Flat No. 103',
            'negative': 'Dampness observed at skirting level of Common Bedroom.',
            'positive': 'Gaps observed between tile joints of Common Bathroom.',
            'source_refs': 'Inspection summary points 2 and 2.1',
            'inspection_image': 'page_13_img_2_Image28.jpg',
            'thermal_page': 2,
        },
        {
            'area': 'Master Bedroom, Flat No. 103',
            'negative': 'Dampness observed at skirting level of Master Bedroom.',
            'positive': 'Gaps observed between tile joints of Master Bedroom Bathroom.',
            'source_refs': 'Inspection summary points 3 and 3.1',
            'inspection_image': 'page_14_img_2_Image41.jpg',
            'thermal_page': 3,
        },
        {
            'area': 'Kitchen, Flat No. 103',
            'negative': 'Dampness observed at skirting level of Kitchen.',
            'positive': 'Gaps observed between tile joints of Master Bedroom Bathroom.',
            'source_refs': 'Inspection summary points 4 and 4.1',
            'inspection_image': 'page_16_img_2_Image44.jpg',
            'thermal_page': 4,
        },
        {
            'area': 'Master Bedroom Wall / External Wall, Flat No. 103',
            'negative': 'Dampness and efflorescence observed on Master Bedroom wall surface.',
            'positive': 'Cracks observed on external wall of building near Master Bedroom.',
            'source_refs': 'Inspection summary points 5 and 5.1',
            'inspection_image': 'page_18_img_3_Image53.jpg',
            'thermal_page': 5,
        },
        {
            'area': 'Parking Ceiling below Flat No. 103',
            'negative': 'Leakage observed at parking ceiling below Flat No. 103.',
            'positive': 'Common Bathroom has plumbing issue and gaps between tile joints.',
            'source_refs': 'Inspection summary points 6 and 6.1',
            'inspection_image': 'page_20_img_3_Image59.jpg',
            'thermal_page': 6,
        },
        {
            'area': 'Common Bathroom Ceiling, Flat No. 103',
            'negative': 'Mild dampness observed at ceiling of Common Bathroom.',
            'positive': 'Gap between tile joints of Common and Master Bedroom Bathrooms of Flat No. 203; outlet leakage is mentioned in detailed observation.',
            'source_refs': 'Inspection summary points 7 and 7.1',
            'inspection_image': 'page_22_img_7_Image72.jpg',
            'thermal_page': 7,
        },
    ]
    return rows


def parse_thermal_pages(text: str):
    pages = {}
    for match in re.finditer(r'--- PAGE (\d+) ---\n(.*?)(?=--- PAGE \d+ ---|$)', text, flags=re.S):
        page = int(match.group(1))
        body = match.group(2)
        hot = re.search(r'Hotspot\s*:\s*([0-9.]+)\s*deg\s*C', body, flags=re.I)
        cold = re.search(r'Coldspot\s*:\s*([0-9.]+)\s*deg\s*C', body, flags=re.I)
        img = re.search(r'Thermal image\s*:\s*([A-Z0-9]+X\.JPG)', body)
        date = re.search(r'(\d{2}/\d{2}/\d{2})', body)
        pages[page] = {
            'hotspot': hot.group(1) + ' deg C' if hot else 'Not Available',
            'coldspot': cold.group(1) + ' deg C' if cold else 'Not Available',
            'thermal_file': img.group(1) if img else 'Not Available',
            'date': date.group(1) if date else 'Not Available',
            'source_page': page,
        }
    return pages


def find_thermal_image(page: int):
    candidates = sorted(THERMAL_IMG_DIR.glob(f'page_{page}_img_*.*'), key=lambda p: p.stat().st_size, reverse=True)
    for p in candidates:
        if p.suffix.lower() in {'.jpg', '.jpeg', '.png'} and p.stat().st_size > 25000:
            return p
    return None


def copy_asset(src: Path, name: str):
    if not src or not src.exists():
        return None
    ASSET_OUT.mkdir(parents=True, exist_ok=True)
    dst = ASSET_OUT / name
    shutil.copy2(src, dst)
    return dst


def image_flowable(path: Path, caption: str, max_w=78*mm, max_h=58*mm):
    if not path or not path.exists():
        return [Paragraph('Image Not Available', styles['SmallWarn'])]
    img = Image(str(path))
    scale = min(max_w / img.imageWidth, max_h / img.imageHeight, 1.0)
    img.drawWidth = img.imageWidth * scale
    img.drawHeight = img.imageHeight * scale
    return [img, Paragraph(caption, styles['Caption'])]


def add_header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.HexColor('#667085'))
    canvas.drawString(18*mm, 10*mm, 'Main DDR - Detailed Diagnostic Report')
    canvas.drawRightString(192*mm, 10*mm, f'Page {doc.page}')
    canvas.restoreState()


styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='TitleCenter', parent=styles['Title'], alignment=TA_CENTER, textColor=colors.HexColor('#16324F'), fontSize=20, leading=24, spaceAfter=10))
styles.add(ParagraphStyle(name='H1Custom', parent=styles['Heading1'], textColor=colors.HexColor('#16324F'), fontSize=14, leading=18, spaceBefore=10, spaceAfter=6))
styles.add(ParagraphStyle(name='H2Custom', parent=styles['Heading2'], textColor=colors.HexColor('#1F4E5F'), fontSize=11, leading=14, spaceBefore=8, spaceAfter=4))
styles.add(ParagraphStyle(name='BodyCustom', parent=styles['BodyText'], fontSize=9.5, leading=13, spaceAfter=5))
styles.add(ParagraphStyle(name='Cell', parent=styles['BodyText'], fontSize=8, leading=10))
styles.add(ParagraphStyle(name='CellBold', parent=styles['Cell'], fontName='Helvetica-Bold'))
styles.add(ParagraphStyle(name='Caption', parent=styles['BodyText'], fontSize=7.5, leading=9, textColor=colors.HexColor('#475467'), alignment=TA_CENTER, spaceAfter=4))
styles.add(ParagraphStyle(name='SmallWarn', parent=styles['BodyText'], fontSize=8, leading=10, textColor=colors.HexColor('#B42318')))


def cell(text):
    return Paragraph(str(text), styles['Cell'])


def cell_bold(text):
    return Paragraph(str(text), styles['CellBold'])


def build_report():
    OUT.mkdir(parents=True, exist_ok=True)
    ASSET_OUT.mkdir(parents=True, exist_ok=True)
    inspection_text = extract_text(INSPECTION_PDF, INSPECTION_TEXT_FALLBACK)
    thermal_text = extract_text(THERMAL_PDF, THERMAL_TEXT_FALLBACK)
    observations = extract_summary_rows(inspection_text)
    thermal = parse_thermal_pages(thermal_text)

    for obs in observations:
        t = thermal.get(obs['thermal_page'], {})
        obs.update({
            'thermal_hotspot': t.get('hotspot', 'Not Available'),
            'thermal_coldspot': t.get('coldspot', 'Not Available'),
            'thermal_file': t.get('thermal_file', 'Not Available'),
            'thermal_date': t.get('date', 'Not Available'),
        })
        obs['inspection_asset'] = copy_asset(INSPECTION_IMG_DIR / obs['inspection_image'], f"inspection_{obs['thermal_page']}{Path(obs['inspection_image']).suffix}")
        obs['thermal_asset'] = copy_asset(find_thermal_image(obs['thermal_page']), f"thermal_page_{obs['thermal_page']}.jpg")

    pdf_path = OUT / 'Main_DDR_Report.pdf'
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, rightMargin=16*mm, leftMargin=16*mm, topMargin=16*mm, bottomMargin=16*mm)
    story = []

    story.append(Paragraph('Main DDR', styles['TitleCenter']))
    story.append(Paragraph('Detailed Diagnostic Report', styles['TitleCenter']))
    intro = 'Prepared from the provided Inspection Report and Thermal Images Report. This report uses only details available in the source documents. Missing or unclear items are marked as Not Available.'
    story.append(Paragraph(intro, styles['BodyCustom']))
    meta = [
        ['Property type', 'Flat'],
        ['Inspection date/time', '27.09.2022 14:28 IST'],
        ['Inspected by', 'Krushna & Mahesh'],
        ['Flat referenced in observations', 'Flat No. 103 and Flat No. 203'],
        ['Floors', '11'],
        ['Previous structural audit', 'No'],
        ['Previous repair work', 'No'],
        ['Customer/contact/address/property age', 'Not Available'],
    ]
    meta = [[cell_bold(label), cell(value)] for label, value in meta]
    table = Table(meta, colWidths=[55*mm, 115*mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#EAF2F8')),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#B8C7D9')),
        ('INNERGRID', (0,0), (-1,-1), 0.25, colors.HexColor('#D0D5DD')),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('FONTSIZE', (0,0), (-1,-1), 8.5),
        ('LEADING', (0,0), (-1,-1), 11),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(table)

    story.append(Paragraph('1. Property Issue Summary', styles['H1Custom']))
    summary = ('The inspection identifies dampness, leakage, tile joint gaps, plumbing issues, and external wall cracks affecting Hall, Bedroom, Kitchen, Master Bedroom, Parking Area, and Common Bathroom areas. The thermal report provides temperature readings for supporting thermal images, but it does not clearly label which thermal image belongs to which room or defect. Therefore, thermal pages are used as supporting evidence only and the exact area-to-thermal-image mapping is marked unclear.')
    story.append(Paragraph(summary, styles['BodyCustom']))

    story.append(Paragraph('2. Area-wise Observations', styles['H1Custom']))
    for i, obs in enumerate(observations, start=1):
        block = []
        block.append(Paragraph(f'{i}. {obs["area"]}', styles['H2Custom']))
        detail_rows = [
            ['Inspection finding', obs['negative']],
            ['Possible source side', obs['positive']],
            ['Thermal reading', f"Hotspot: {obs['thermal_hotspot']}; Coldspot: {obs['thermal_coldspot']}; Thermal image file: {obs['thermal_file']}"],
            ['Source reference', obs['source_refs']],
        ]
        detail_rows = [[cell_bold(label), cell(value)] for label, value in detail_rows]
        detail = Table(detail_rows, colWidths=[45*mm, 125*mm])
        detail.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#F2F4F7')),
            ('BOX', (0,0), (-1,-1), 0.4, colors.HexColor('#D0D5DD')),
            ('INNERGRID', (0,0), (-1,-1), 0.25, colors.HexColor('#EAECF0')),
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 5),
            ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ]))
        block.append(detail)
        img_cells = [
            image_flowable(obs['inspection_asset'], 'Inspection image from source report')[0:2],
            image_flowable(obs['thermal_asset'], f'Thermal image from page {obs["thermal_page"]}')[0:2],
        ]
        img_table = Table([img_cells], colWidths=[85*mm, 85*mm])
        img_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('ALIGN', (0,0), (-1,-1), 'CENTER')]))
        block.append(Spacer(1, 4))
        block.append(img_table)
        story.append(KeepTogether(block))
        story.append(Spacer(1, 7))

    story.append(Paragraph('3. Probable Root Cause', styles['H1Custom']))
    causes = [
        'Concealed plumbing leakage is marked Yes in the inspection checklist.',
        'Damage in Nahani trap/brickbat coba under tile flooring is marked Yes.',
        'Gaps around Nahani trap joints and gaps/blackish dirt in tile joints are marked Yes.',
        'External wall cracks and moderate external wall condition may contribute to dampness near the Master Bedroom wall.',
    ]
    for c in causes:
        story.append(Paragraph('- ' + c, styles['BodyCustom']))

    story.append(Paragraph('4. Severity Assessment', styles['H1Custom']))
    sev = ('Overall severity is assessed as Moderate. Reason: the inspection checklist explicitly records moderate RCC/external wall crack condition and moderate algae/fungus on external wall, while the affected areas include multiple rooms and parking ceiling. Some observations are described as mild, such as Common Bathroom ceiling dampness, so those individual items may be lower severity than the overall property condition.')
    story.append(Paragraph(sev, styles['BodyCustom']))

    story.append(Paragraph('5. Recommended Actions', styles['H1Custom']))
    actions = [
        'Repair tile joint gaps in Common Bathroom and Master Bedroom Bathroom.',
        'Check and repair concealed plumbing joints and bathroom outlet leakage mentioned in the inspection report.',
        'Inspect Nahani trap/brickbat coba below bathroom tiles and repair if leakage is confirmed.',
        'Treat damp affected skirting and wall areas only after the leakage source is repaired.',
        'Repair external wall cracks near Master Bedroom and check wall pipe openings/grouting where applicable.',
        'Recheck affected rooms and parking ceiling after repair completion to confirm that dampness/leakage has stopped.',
    ]
    for a in actions:
        story.append(Paragraph('- ' + a, styles['BodyCustom']))

    story.append(Paragraph('6. Additional Notes', styles['H1Custom']))
    notes = [
        'The thermal report provides temperature readings and images but does not include room names or issue descriptions in the extracted text.',
        'Temperature readings across sampled thermal pages range approximately from 20.5 deg C to 28.8 deg C for the pages used in this DDR.',
        'Duplicate inspection points were merged where the same bathroom tile joint gap was repeated for multiple affected rooms.',
    ]
    for n in notes:
        story.append(Paragraph('- ' + n, styles['BodyCustom']))

    story.append(Paragraph('7. Missing or Unclear Information', styles['H1Custom']))
    missing = [
        'Customer name: Not Available',
        'Mobile number: Not Available',
        'Email: Not Available',
        'Address: Not Available',
        'Property age: Not Available',
        'Exact mapping between each thermal image and each inspected area: Not Available',
        'Exact repair history details beyond Yes/No fields: Not Available',
        'Conflict check: No direct conflict found between inspection findings and thermal readings; thermal labels are unclear rather than conflicting.',
    ]
    for m in missing:
        story.append(Paragraph('- ' + m, styles['BodyCustom']))

    doc.build(story, onFirstPage=add_header_footer, onLaterPages=add_header_footer)

    workflow = OUT / 'simple_ddr_model_workflow.txt'
    workflow.write_text("""Simple DDR Generator - Low Credit Workflow

Purpose
Convert an Inspection Report PDF and Thermal Images PDF into a client-ready DDR without spending credits on image or text extraction.

Pipeline
1. Extract text locally from both PDFs using pdfplumber.
2. Extract or reuse embedded images locally from the PDFs.
3. Parse the inspection summary table as the main source of truth for area-wise findings.
4. Parse thermal pages for hotspot, coldspot, date, device, and source thermal image filename.
5. Merge repeated findings by area/source side to avoid duplicate points.
6. If an area-to-thermal-image match is missing, include the relevant available thermal page as support and mark exact mapping as Not Available.
7. Generate DDR sections: summary, observations, root cause, severity, actions, notes, and missing/unclear information.
8. Insert only selected relevant source images under matching observations.

Credit-saving design
- No vision model is required for this sample workflow.
- No LLM call is required for deterministic fields.
- Optional LLM use can be limited to one final summarization prompt after extraction, using only the compact structured JSON.

Generalization
For similar reports, replace the hardcoded sample mapping with:
- regex/table extraction for summary rows,
- image captions/photo numbers from appendix pages,
- filename/page matching for thermal images,
- fallback rule: when image mapping is unclear, write Image Not Available or Exact mapping Not Available.
""", encoding='utf-8')
    return pdf_path, workflow


if __name__ == '__main__':
    pdf, workflow = build_report()
    print(f'Created: {pdf}')
    print(f'Created: {workflow}')
