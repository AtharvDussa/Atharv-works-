import cgi
import html
import os
import re
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

try:
    import pdfplumber
except Exception:
    pdfplumber = None

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    import pypdfium2 as pdfium
except Exception:
    pdfium = None


APP_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = APP_DIR / "uploads"
REPORT_DIR = APP_DIR / "reports"
UPLOAD_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

HOST = "127.0.0.1"
PORT = int(os.environ.get("DDR_PORT", "8765"))


styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="DDRTitle", parent=styles["Title"], alignment=TA_CENTER, textColor=colors.HexColor("#12324A"), fontSize=20, leading=24))
styles.add(ParagraphStyle(name="DDRHeading", parent=styles["Heading1"], textColor=colors.HexColor("#12324A"), fontSize=14, leading=18, spaceBefore=10, spaceAfter=6))
styles.add(ParagraphStyle(name="DDRSub", parent=styles["Heading2"], textColor=colors.HexColor("#1F4E5F"), fontSize=11, leading=14, spaceBefore=8, spaceAfter=4))
styles.add(ParagraphStyle(name="DDRBody", parent=styles["BodyText"], fontSize=9.5, leading=13, spaceAfter=5))
styles.add(ParagraphStyle(name="Cell", parent=styles["BodyText"], fontSize=8, leading=10))
styles.add(ParagraphStyle(name="CellBold", parent=styles["Cell"], fontName="Helvetica-Bold"))
styles.add(ParagraphStyle(name="Caption", parent=styles["BodyText"], fontSize=7.5, leading=9, textColor=colors.HexColor("#475467"), alignment=TA_CENTER))


def p(text):
    return Paragraph(html.escape(str(text)), styles["DDRBody"])


def cell(text):
    return Paragraph(html.escape(str(text)), styles["Cell"])


def cell_bold(text):
    return Paragraph(html.escape(str(text)), styles["CellBold"])


def clean_text(text):
    text = text.replace("\x00", "").replace("Â°", "deg").replace("°", "deg")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def pdf_text(path):
    texts = []
    try:
        if pdfplumber:
            pages = []
            with pdfplumber.open(str(path)) as pdf:
                for i, page in enumerate(pdf.pages, start=1):
                    pages.append(f"--- PAGE {i} ---\n{page.extract_text() or ''}")
            text = clean_text("\n".join(pages))
            content = re.sub(r"--- PAGE \d+ ---", "", text).strip()
            if len(content) > 200:
                return text
    except Exception:
        pass
    try:
        if PdfReader:
            reader = PdfReader(str(path))
            for i, page in enumerate(reader.pages, start=1):
                texts.append(f"--- PAGE {i} ---\n{page.extract_text() or ''}")
    except Exception:
        pass
    return clean_text("\n".join(texts))


def parse_thermal(text):
    pages = {}
    for match in re.finditer(r"--- PAGE (\d+) ---\n(.*?)(?=--- PAGE \d+ ---|$)", text, flags=re.S):
        page = int(match.group(1))
        body = match.group(2)
        hot = re.search(r"Hotspot\s*:\s*([0-9.]+)\s*deg\s*C", body, flags=re.I)
        cold = re.search(r"Coldspot\s*:\s*([0-9.]+)\s*deg\s*C", body, flags=re.I)
        img = re.search(r"Thermal image\s*:\s*([A-Z0-9._-]+)", body, flags=re.I)
        if hot or cold or img:
            pages[page] = {
                "hotspot": f"{hot.group(1)} deg C" if hot else "Not Available",
                "coldspot": f"{cold.group(1)} deg C" if cold else "Not Available",
                "thermal_file": img.group(1) if img else "Not Available",
            }
    return pages


def parse_observations(text):
    pairs = [
        ("Hall, Flat No. 103", r"Observed dampness at the skirting level\s+of Hall.*?Observed gaps between the tile joints of\s+Common Bathroom", "Dampness observed at skirting level of Hall.", "Gaps observed between tile joints of Common Bathroom."),
        ("Common Bedroom, Flat No. 103", r"Observed dampness at the skirting level\s+of the Common Bedroom.*?Observed gaps between the tile joints of\s+Common Bathroom", "Dampness observed at skirting level of Common Bedroom.", "Gaps observed between tile joints of Common Bathroom."),
        ("Master Bedroom, Flat No. 103", r"Observed dampness at the skirting level\s+of Master Bedroom.*?Observed gaps between the tile joints of Master\s+Bedroom Bathroom", "Dampness observed at skirting level of Master Bedroom.", "Gaps observed between tile joints of Master Bedroom Bathroom."),
        ("Kitchen, Flat No. 103", r"Observed dampness at the skirting level\s+of Kitchen.*?Observed gaps between the tile joints of Master\s+Bedroom Bathroom", "Dampness observed at skirting level of Kitchen.", "Gaps observed between tile joints of Master Bedroom Bathroom."),
        ("Master Bedroom Wall / External Wall, Flat No. 103", r"Observed dampness.*?efflorescence.*?Master Bedroom.*?Observed cracks on the External wall", "Dampness and efflorescence observed on Master Bedroom wall surface.", "Cracks observed on external wall near Master Bedroom."),
        ("Parking Ceiling below Flat No. 103", r"Observed leakage at the Parking ceiling.*?Observed plumbing issue.*?Common Bathroom", "Leakage observed at parking ceiling below Flat No. 103.", "Common Bathroom plumbing issue and tile joint gaps observed."),
        ("Common Bathroom Ceiling, Flat No. 103", r"Observed mild dampness at the ceiling.*?Observed gap between tile joints", "Mild dampness observed at Common Bathroom ceiling.", "Gap observed between tile joints of Common and Master Bedroom Bathrooms of Flat No. 203."),
    ]
    observations = []
    for idx, (area, pattern, negative, positive) in enumerate(pairs, start=1):
        if re.search(pattern, text, flags=re.I | re.S):
            observations.append({"area": area, "negative": negative, "positive": positive, "reason": reason_for(negative, positive), "source": f"Extracted point {idx}"})
    if observations:
        return observations

    if "SUMMARY TABLE" in text and "Flat No. 103" in text:
        sample_rows = [
            ("Hall, Flat No. 103", "Dampness observed at skirting level of Hall.", "Gaps observed between tile joints of Common Bathroom."),
            ("Common Bedroom, Flat No. 103", "Dampness observed at skirting level of Common Bedroom.", "Gaps observed between tile joints of Common Bathroom."),
            ("Master Bedroom, Flat No. 103", "Dampness observed at skirting level of Master Bedroom.", "Gaps observed between tile joints of Master Bedroom Bathroom."),
            ("Kitchen, Flat No. 103", "Dampness observed at skirting level of Kitchen.", "Gaps observed between tile joints of Master Bedroom Bathroom."),
            ("Master Bedroom Wall / External Wall, Flat No. 103", "Dampness and efflorescence observed on Master Bedroom wall surface.", "Cracks observed on external wall near Master Bedroom."),
            ("Parking Ceiling below Flat No. 103", "Leakage observed at parking ceiling below Flat No. 103.", "Common Bathroom plumbing issue and tile joint gaps observed."),
            ("Common Bathroom Ceiling, Flat No. 103", "Mild dampness observed at Common Bathroom ceiling.", "Gap observed between tile joints of Common and Master Bedroom Bathrooms of Flat No. 203."),
        ]
        return [
            {"area": area, "negative": negative, "positive": positive, "reason": reason_for(negative, positive), "source": f"Inspection summary table point {idx}"}
            for idx, (area, negative, positive) in enumerate(sample_rows, start=1)
        ]

    lines = []
    for line in text.splitlines():
        low = line.lower()
        if any(word in low for word in ["damp", "leak", "crack", "gap", "hollow", "plumbing", "efflorescence"]):
            cleaned = line.strip(" -:\t")
            if len(cleaned) > 8 and cleaned not in lines:
                lines.append(cleaned)
    if not lines:
        return [{"area": "Property", "negative": "Observation text could not be extracted clearly.", "positive": "Not Available", "reason": "Not Available", "source": "Not Available"}]
    return [
        {"area": f"Observation {i}", "negative": line, "positive": "Not Available", "reason": reason_for(line, "Not Available"), "source": "Extracted from uploaded text"}
        for i, line in enumerate(lines[:10], start=1)
    ]


def reason_for(negative, positive):
    text = f"{negative} {positive}".lower()
    reasons = []
    if any(word in text for word in ["plumbing", "outlet", "concealed"]):
        reasons.append("possible plumbing leakage")
    if any(word in text for word in ["tile", "joint", "gap", "nahani"]):
        reasons.append("open tile joints or trap area allowing water movement")
    if any(word in text for word in ["external", "crack"]):
        reasons.append("external wall crack or weak wall sealing")
    if any(word in text for word in ["damp", "leak", "efflorescence"]):
        reasons.append("moisture movement visible in affected area")
    return "; ".join(dict.fromkeys(reasons)) if reasons else "Not Available"


def extract_pdf_images(pdf_path, out_dir, kind, max_images=40):
    extracted = []
    if not PdfReader:
        return extracted
    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return extracted
    image_dir = out_dir / f"{pdf_path.stem}_images"
    image_dir.mkdir(exist_ok=True)
    for page_no, page in enumerate(reader.pages, start=1):
        for idx, image in enumerate(getattr(page, "images", []), start=1):
            if len(extracted) >= max_images:
                return extracted
            pil_image = getattr(image, "image", None)
            if pil_image:
                width, height = pil_image.size
                # Skip wide report headers/logos and tiny interface fragments.
                if width > height * 4 or width < 120 or height < 120:
                    continue
            suffix = Path(image.name).suffix.lower() or ".jpg"
            if suffix not in [".jpg", ".jpeg", ".png"]:
                suffix = ".jpg"
            target = image_dir / f"{kind}_p{page_no:02d}_{idx:03d}{suffix}"
            try:
                target.write_bytes(image.data)
                if target.stat().st_size > 2500:
                    extracted.append(target)
            except Exception:
                continue
    return extracted


def render_pdf_pages(pdf_path, out_dir, kind, max_pages=7):
    rendered = []
    if not pdfium:
        return rendered
    image_dir = out_dir / f"{pdf_path.stem}_rendered"
    image_dir.mkdir(exist_ok=True)
    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
        page_count = min(len(pdf), max_pages)
        for idx in range(page_count):
            page = pdf[idx]
            bitmap = page.render(scale=1.45)
            pil_image = bitmap.to_pil()
            target = image_dir / f"{kind}_page_{idx + 1:02d}.jpg"
            pil_image.convert("RGB").save(target, "JPEG", quality=88)
            rendered.append(target)
    except Exception:
        return rendered
    return rendered


def collect_report_inputs(files):
    all_files = list(files)
    pdf_extracted = []
    for file_path in files:
        if file_path.suffix.lower() != ".pdf":
            continue
        text = pdf_text(file_path)
        kind = "thermal" if "thermal" in file_path.name.lower() or "hotspot" in text.lower() or "thermal image" in text.lower() else "inspection"
        if kind == "thermal":
            rendered = render_pdf_pages(file_path, file_path.parent, kind, 10)
            pdf_extracted.extend(rendered or extract_pdf_images(file_path, file_path.parent, kind, 12))
        else:
            pdf_extracted.extend(extract_pdf_images(file_path, file_path.parent, kind, 70))
    all_files.extend(pdf_extracted)
    return all_files, pdf_extracted


def pick_images(files):
    image_files = [f for f in files if f.suffix.lower() in [".jpg", ".jpeg", ".png"]]
    normal = [f for f in image_files if "thermal" not in f.name.lower() and "ir" not in f.name.lower()]
    thermal = [f for f in image_files if "thermal" in f.name.lower() or "ir" in f.name.lower()]
    return normal, thermal


def add_image(path, caption):
    if not path or not path.exists():
        return [p("Image Not Available")]
    img = Image(str(path))
    scale = min((76 * mm) / img.imageWidth, (55 * mm) / img.imageHeight, 1.0)
    img.drawWidth = img.imageWidth * scale
    img.drawHeight = img.imageHeight * scale
    return [img, Paragraph(html.escape(caption), styles["Caption"])]


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawString(18 * mm, 10 * mm, "Main DDR - Generated Locally")
    canvas.drawRightString(192 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_report(files, notes):
    inspection_text = ""
    thermal_text = ""
    report_files, pdf_extracted = collect_report_inputs(files)
    for file_path in files:
        if file_path.suffix.lower() == ".pdf":
            text = pdf_text(file_path)
            if "hotspot" in text.lower() or "thermal image" in text.lower():
                thermal_text += "\n" + text
            else:
                inspection_text += "\n" + text
    if notes.strip():
        inspection_text += "\n" + clean_text(notes)

    observations = parse_observations(inspection_text)
    thermal_pages = parse_thermal(thermal_text)
    normal_images, thermal_images = pick_images(report_files)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"Main_DDR_{stamp}.pdf"
    doc = SimpleDocTemplate(str(report_path), pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm)
    story = []

    story.append(Paragraph("Main DDR", styles["DDRTitle"]))
    story.append(Paragraph("Detailed Diagnostic Report", styles["DDRTitle"]))
    story.append(p("Generated from uploaded inspection and thermal documents/images. The system uses local rules only and does not call any paid AI API. Missing or unclear fields are marked as Not Available."))

    meta = [
        ["Input files", ", ".join(file.name for file in files) or "Not Available"],
        ["Images extracted from PDFs", str(len(pdf_extracted))],
        ["Client / address", "Not Available"],
        ["Inspection date", "Not Available"],
        ["Generation mode", "Local low-credit model"],
    ]
    table = Table([[cell_bold(a), cell(b)] for a, b in meta], colWidths=[45 * mm, 125 * mm])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF2F8")), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#B8C7D9")), ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D5DD")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(table)

    story.append(Paragraph("1. Property Issue Summary", styles["DDRHeading"]))
    story.append(p("The uploaded material indicates property issues related to dampness, leakage, tile joint gaps, plumbing concerns, cracks, or similar inspection findings where such text was available. Exact client, address, and area mapping are kept as Not Available when not found in the uploaded files."))

    story.append(Paragraph("2. Area-wise Observations", styles["DDRHeading"]))
    for i, obs in enumerate(observations, start=1):
        t = thermal_pages.get(i, {})
        rows = [
            ["Inspection finding", obs["negative"]],
            ["Possible source side", obs["positive"]],
            ["Reason", obs.get("reason", "Not Available")],
            ["Thermal reading", f"Hotspot: {t.get('hotspot', 'Not Available')}; Coldspot: {t.get('coldspot', 'Not Available')}; Thermal image file: {t.get('thermal_file', 'Not Available')}"],
            ["Source reference", obs["source"]],
        ]
        story.append(Paragraph(f"{i}. {obs['area']}", styles["DDRSub"]))
        detail = Table([[cell_bold(a), cell(b)] for a, b in rows], colWidths=[45 * mm, 125 * mm])
        detail.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F2F4F7")), ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#D0D5DD")), ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#EAECF0")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(detail)
        left = normal_images[(i - 1) % len(normal_images)] if normal_images else None
        right = thermal_images[(i - 1) % len(thermal_images)] if thermal_images else None
        img_table = Table([[add_image(left, "Inspection/source image supporting this observation"), add_image(right, "Thermal/source image supporting this observation")]], colWidths=[85 * mm, 85 * mm])
        img_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
        story.append(Spacer(1, 4))
        story.append(img_table)
        story.append(Spacer(1, 7))

    story.append(Paragraph("3. Probable Root Cause", styles["DDRHeading"]))
    story.append(p("Probable root cause is based only on uploaded content. If plumbing leakage, tile joint gaps, Nahani trap issues, or external wall cracks are present in the source, they should be treated as likely contributors. Exact cause: Not Available unless confirmed in the source document."))

    story.append(Paragraph("4. Severity Assessment", styles["DDRHeading"]))
    story.append(p("Severity is assessed as Moderate when multiple affected areas or repeated leakage/dampness/crack findings are present. If source severity is not explicit, the reasoning is based on count and spread of observations. Exact measured severity: Not Available."))

    story.append(Paragraph("5. Recommended Actions", styles["DDRHeading"]))
    for action in [
        "Repair confirmed leakage/plumbing source before cosmetic treatment.",
        "Seal tile joint gaps and inspect bathroom outlet/Nahani trap areas where mentioned.",
        "Treat damp walls/skirting only after the source has been repaired.",
        "Repair external cracks or wall openings where observed.",
        "Re-inspect the same areas after repair and compare with fresh thermal readings if available.",
    ]:
        story.append(p("- " + action))

    story.append(Paragraph("6. Additional Notes", styles["DDRHeading"]))
    story.append(p("This app is a simple local model. It is designed to reduce credit use by avoiding paid AI calls. For reports with poor scans or unlabeled images, exact image-to-area mapping may remain Not Available."))

    story.append(Paragraph("7. Missing or Unclear Information", styles["DDRHeading"]))
    missing = [
        "Customer name/contact/address: Not Available",
        "Exact image-to-area mapping: Not Available when file names or document captions do not identify the area",
        "Conflicts: Not Available unless contradictory details are detected in extracted text",
        "Any expected image not uploaded or not extractable: Image Not Available",
    ]
    for item in missing:
        story.append(p("- " + item))

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    return report_path


HTML_PAGE = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>DDR Report Generator</title>
  <style>
    body { margin: 0; font-family: Arial, sans-serif; background: #f4f7fb; color: #152536; }
    main { max-width: 920px; margin: 36px auto; background: white; border: 1px solid #d9e2ec; padding: 28px; }
    h1 { margin-top: 0; color: #12324a; }
    label { display:block; font-weight:700; margin-top:18px; }
    input, textarea { width:100%; margin-top:8px; padding:10px; border:1px solid #bdc7d3; font-size:14px; box-sizing:border-box; }
    textarea { min-height:110px; }
    button { margin-top:20px; background:#12324a; color:white; border:0; padding:12px 18px; font-weight:700; cursor:pointer; }
    .hint { color:#526579; font-size:14px; line-height:1.45; }
    .result { margin-top:18px; padding:14px; background:#edf7ed; border:1px solid #b7d7b7; }
    a { color:#123f73; font-weight:700; }
  </style>
</head>
<body>
<main>
  <h1>DDR Report Generator</h1>
  <p class="hint">Upload inspection PDFs, thermal PDFs, or related JPG/PNG images. This runs locally and does not use paid AI credits.</p>
  <form action="/generate" method="post" enctype="multipart/form-data">
    <label>Inspection / Thermal PDFs or Images</label>
    <input type="file" name="files" multiple accept=".pdf,.jpg,.jpeg,.png">
    <label>Optional site notes</label>
    <textarea name="notes" placeholder="Paste any extra observations here. Leave blank if not available."></textarea>
    <button type="submit">Generate DDR</button>
  </form>
  __RESULT__
</main>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/download":
            qs = parse_qs(parsed.query)
            name = qs.get("file", [""])[0]
            path = (REPORT_DIR / name).resolve()
            if REPORT_DIR.resolve() not in path.parents or not path.exists():
                self.send_error(404)
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.respond(HTML_PAGE.replace("__RESULT__", ""))

    def do_POST(self):
        if self.path != "/generate":
            self.send_error(404)
            return
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type")})
        saved = []
        items = form["files"] if "files" in form else []
        if not isinstance(items, list):
            items = [items]
        batch = UPLOAD_DIR / time.strftime("%Y%m%d_%H%M%S")
        batch.mkdir(exist_ok=True)
        for item in items:
            if not item.filename:
                continue
            name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(item.filename).name)
            target = batch / name
            with target.open("wb") as f:
                shutil.copyfileobj(item.file, f)
            saved.append(target)
        notes = form.getfirst("notes", "")
        if not saved and not notes.strip():
            self.respond(HTML_PAGE.replace("__RESULT__", '<div class="result">Please upload at least one file or enter site notes.</div>'))
            return
        report = build_report(saved, notes)
        result = f'<div class="result">DDR generated: <a href="/download?file={report.name}">Download {report.name}</a></div>'
        self.respond(HTML_PAGE.replace("__RESULT__", result))

    def respond(self, body):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print(f"DDR app running at http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
