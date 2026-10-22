from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from io import BytesIO
import json, csv, os, re, hashlib, datetime, tempfile, shutil
import cv2
import numpy as np
import fitz

try:
    import pytesseract
except ImportError:
    pytesseract = None
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# Supports both layouts:
# 1) Docker: /app/main.py and /app/frontend/
# 2) Native Python with Root Directory=backend: repo/backend/main.py and repo/frontend/
HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "frontend").is_dir() else HERE.parent
FRONTEND_DIR = ROOT / "frontend"
app = FastAPI(title="FJMC OMR Scanner")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
DATA_DIR = Path(os.environ.get("OMR_DATA_DIR", str(ROOT / "data"))).resolve()
SHEETS_DIR = DATA_DIR / "students"
SHEETS_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_FILE = DATA_DIR / "results.json"

def load_saved_results():
    try:
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8")) if RESULTS_FILE.exists() else []
    except (OSError, json.JSONDecodeError):
        return []

def save_result(result):
    records = load_saved_results()
    # Do not silently overwrite a previously scanned roll number. Keep the newest attempt in records
    # but save each physical sheet under a timestamped attempt directory.
    records.append(result)
    tmp = RESULTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(RESULTS_FILE)

def dense_rank(results):
    scores = sorted({float(r.get("marks", 0)) for r in results}, reverse=True)
    ranks = {score: i + 1 for i, score in enumerate(scores)}
    for r in results:
        r["rank"] = ranks.get(float(r.get("marks", 0)), "")
    return sorted(results, key=lambda r: (int(r.get("rank", 10**9)), str(r.get("roll_number", ""))))

@app.get("/", response_class=HTMLResponse)
def home():
    return (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

@app.get("/api/health")
def health():
    return {"ok": True, "app": "FJMC OMR Scanner"}

@app.post("/api/template")
def template(payload: dict):
    n = int(payload.get("questions", 50))
    if not 25 <= n <= 200:
        raise HTTPException(400, "Questions must be between 25 and 200.")
    title = str(payload.get("title", "FJMC Academy Test"))[:80]
    options = ["A", "B", "C", "D"]
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    # Registration squares and a fixed layout matching scanner coordinates.
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(w/2, h-18*mm, "FJMC ACADEMY")
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(w/2, h-25*mm, title)
    c.setFont("Helvetica", 8)
    c.drawString(18*mm, h-34*mm, "Name: __________________________________")
    c.setFont("Helvetica-Bold", 7)
    c.drawString(18*mm, h-41*mm, "ROLL NUMBER (8 digits): Fill ONE bubble in each column")
    # 8 columns, digits 0-9 down each column. The selected row in each column forms the roll number.
    roll_x0, roll_dx = 42*mm, 17*mm
    roll_top, roll_dy = h-47*mm, 2.65*mm
    for digit_col in range(8):
        x = roll_x0 + digit_col*roll_dx
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(x, roll_top+1.4*mm, str(digit_col+1))
        for digit in range(10):
            y = roll_top - digit*roll_dy
            c.setLineWidth(0.55)
            c.circle(x, y, 1.15*mm, stroke=1, fill=0)
            c.setFont("Helvetica", 4.5)
            c.drawCentredString(x, y-0.45*mm, str(digit))
    c.setFont("Helvetica", 7)
    c.drawString(18*mm, h-76*mm, f"Questions: {n}    Fill ONE bubble per question.")
    # markers (for future perspective correction)
    s=7*mm
    for x,y in [(8*mm, h-8*mm-s),(w-8*mm-s,h-8*mm-s),(8*mm,8*mm),(w-8*mm-s,8*mm)]:
        c.setFillColorRGB(0,0,0); c.rect(x,y,s,s,fill=1,stroke=0)
    # Three columns; up to 200 questions, 70 per column maximum.
    cols = 3
    rows_per_col = (n + cols - 1)//cols
    top = h - 81*mm
    bottom = 18*mm
    row_h = min(7.0*mm, (top-bottom)/rows_per_col)
    col_w = (w-28*mm)/cols
    for q in range(n):
        col = q // rows_per_col
        row = q % rows_per_col
        x0 = 14*mm + col*col_w
        y = top - row*row_h
        c.setFont("Helvetica", 7)
        c.drawRightString(x0+8*mm, y, str(q+1))
        for j,opt in enumerate(options):
            bx = x0 + 12*mm + j*7.1*mm
            by = y - 1.6*mm
            c.setLineWidth(0.65)
            c.circle(bx, by, 1.8*mm, stroke=1, fill=0)
            c.setFont("Helvetica", 5.5)
            c.drawCentredString(bx, by-0.7*mm, opt)
    c.setFont("Helvetica", 7)
    c.drawCentredString(w/2, 10*mm, "FJMC OMR • Print at 100% scale • Do not fold or cover corner markers")
    c.save()
    return Response(buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="fjmc-omr-template.pdf"'})

def read_image(data: bytes, filename: str):
    if filename.lower().endswith(".pdf"):
        doc = fitz.open(stream=data, filetype="pdf")
        if len(doc) > 1000:
            raise HTTPException(400, "Please upload a PDF with 1000 pages or fewer per batch.")
        for page in doc:
            pix=page.get_pixmap(matrix=fitz.Matrix(2,2), alpha=False)
            arr=np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
            yield cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        doc.close()
    arr=np.frombuffer(data,dtype=np.uint8)
    img=cv2.imdecode(arr,cv2.IMREAD_COLOR)
    if img is None: raise HTTPException(400,"Could not read image. Use JPG, PNG or scanned PDF.")
    yield img


def detect_student_name(img):
    """Best-effort OCR for the handwritten/printed name line on the generated template."""
    if pytesseract is None:
        return None
    try:
        height, width = img.shape[:2]
        # The template name line is near the top-left, around x=18..108 mm, y=31..38 mm.
        x1, x2 = int(width * 18 / 210), int(width * 108 / 210)
        y1, y2 = int(height * 30 / 297), int(height * 39 / 297)
        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        text = pytesseract.image_to_string(gray, config="--psm 7")
        text = re.sub(r"[^A-Za-z .'-]", "", text).strip(" .-'\t\r\n")
        # Avoid returning the printed field label or empty/noisy OCR.
        if text.lower().startswith("name"):
            text = re.sub(r"(?i)^name\s*:?\s*", "", text).strip()
        return text[:80] or None
    except Exception:
        return None


@app.get("/ocr-status")
def ocr_status():
    """Diagnostic endpoint; OCR is optional and never prevents OMR scoring."""
    path = shutil.which("tesseract")
    if pytesseract is None:
        return {"installed": False, "path": path, "error": "pytesseract Python package is not installed"}
    try:
        version = pytesseract.get_tesseract_version()
        return {"installed": True, "path": path, "version": str(version)}
    except Exception as exc:
        return {"installed": False, "path": path, "error": str(exc)}


def detect_roll_number(bw):
    """Read the 8-column, 0-9 roll-number grid on this app's generated template."""
    height, width = bw.shape[:2]
    x0_mm, dx_mm = 42.0, 17.0
    top_y_mm, dy_mm = 47.0, 2.65
    digits = []
    confidences = []
    for col in range(8):
        values = []
        cx = int((x0_mm + col * dx_mm) / 210.0 * width)
        for digit in range(10):
            # PDF y is measured from the bottom; image y from the top.
            cy = int((297.0 - (top_y_mm - digit * dy_mm)) / 297.0 * height)
            radius = max(3, int(width * 0.0045))
            roi = bw[max(0, cy-radius):min(height, cy+radius+1), max(0, cx-radius):min(width, cx+radius+1)]
            values.append(float(np.count_nonzero(roi)) / max(1, roi.size))
        order = sorted(range(10), key=lambda d: values[d], reverse=True)
        best, second = order[0], order[1]
        # Require a clearly dark selected bubble and separation from the next darkest bubble.
        if values[best] >= 0.30 and values[best] - values[second] >= 0.07:
            digits.append(str(best))
            confidences.append(round(values[best] - values[second], 3))
        else:
            digits.append("?")
            confidences.append(round(values[best] - values[second], 3))
    roll = "".join(digits)
    return (roll if "?" not in roll else None), digits, confidences

def score_page(img, key, marks, negative):
    import cv2
    import numpy as np

    h, w = img.shape[:2]

    # Rotate landscape scans to portrait
    if w > h:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)

    # Normalize to the generated A4 template size
    img = cv2.resize(img, (1240, 1754),
                     interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Reduce image noise before thresholding
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    bw = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 31, 10
    )

    roll_number, roll_digits, roll_confidence = detect_roll_number(bw)
    student_name = detect_student_name(img)

    n = len(key)
    cols = 3
    rows = (n + cols - 1) // cols

    # Bubble centers measured from the generated A4 PDF layout
    # Actual bubble-center positions for all 3 PDF columns
    # Bubble coordinates
    col_left = [
        26.0 / 210.0,
        (26.0 + 182.0 / 3.0) / 210.0,
        (26.0 + 2.0 * 182.0 / 3.0) / 210.0
    ]
    col_step = 7.1 / 210.0

    # Row spacing
    row_step_mm = min(7.0, 234.0 / rows)
    first_y = 82.6 / 297.0

    answers = []
    correct = wrong = blank = multi = 0
    total = 0.0

    for q in range(n):
        col = q // rows
        row = q % rows

        cy = int((first_y + row * row_step_mm / 297.0)
                 * 1754)
        cx0 = int(col_left[col] * 1240)

        vals = []

        for j in range(4):
            cx = int(cx0 + j * col_step * 1240)

            # Measure darkness inside the central bubble area
            radius = 6
            roi = bw[
                max(0, cy-radius):min(1754, cy+radius+1),
                max(0, cx-radius):min(1240, cx+radius+1)
            ]

            vals.append(
                float(np.count_nonzero(roi)) / max(1, roi.size)
            )

        ranked = sorted(range(4),
                        key=lambda j: vals[j], reverse=True)
        first, second = ranked[0], ranked[1]

        # Conservative detection: uncertain marks require review
        chosen = ""
        if vals[first] > 0.30 and vals[first] - vals[second] > 0.10:
            chosen = "ABCD"[first]
        elif vals[first] > 0.30 and vals[second] > 0.30:
            chosen = "MULTI"

        if chosen == "MULTI":
            multi += 1
            status = "Multiple marks"
        elif not chosen:
            blank += 1
            status = "Blank"
        elif chosen == key[q]:
            correct += 1
            total += marks
            status = "Correct"
        else:
            wrong += 1
            total -= negative
            status = "Wrong"

        answers.append({
            "question": q + 1,
            "detected": chosen or "—",
            "key": key[q],
            "status": status,
            "bubble_darkness": [round(v, 3) for v in vals]
        })

    return {
        "questions": n,
        "roll_number": roll_number,
        "student_name": student_name,
        "roll_digits": roll_digits,
        "roll_confidence": roll_confidence,
        "correct": correct,
        "wrong": wrong,
        "blank": blank,
        "multiple": multi,
        "marks": round(total, 2),
        "maximum": round(n * marks, 2),
        "answers": answers,
        "review_required": bool(multi or blank)
    }


def save_page_artifacts(img, result):
    roll = result.get("roll_number") or "UNREADABLE"
    safe_roll = re.sub(r"[^0-9A-Za-z_-]", "_", roll)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = SHEETS_DIR / safe_roll / stamp
    folder.mkdir(parents=True, exist_ok=True)
    # Save the original scan as uploaded/rendered for audit; result PDF is one page per student.
    original_path = folder / "omr-original.jpg"
    cv2.imwrite(str(original_path), img, [int(cv2.IMWRITE_JPEG_QUALITY), 94])
    pdf_path = folder / "result.pdf"
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, rightMargin=18, leftMargin=18, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    story = [Paragraph("FJMC ACADEMY — OMR RESULT", styles["Title"]), Spacer(1, 8)]
    story.append(Paragraph(f"Roll number: <b>{roll or 'UNREADABLE — MANUAL REVIEW REQUIRED'}</b>", styles["Normal"]))
    story.append(Paragraph(f"Scanned at (UTC): {stamp}", styles["Normal"]))
    story.append(Spacer(1, 10))
    summary = [["Marks", "Maximum", "Rank", "Correct", "Wrong", "Blank", "Multiple"], [str(result.get("marks")), str(result.get("maximum")), str(result.get("rank", "Pending")), str(result.get("correct")), str(result.get("wrong")), str(result.get("blank")), str(result.get("multiple"))]]
    t = Table(summary, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e7efff")), ("GRID", (0,0), (-1,-1), .4, colors.HexColor("#ccd6e5")), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 8), ("PADDING", (0,0), (-1,-1), 6)]))
    story += [t, Spacer(1, 12)]
    data = [["Q", "Detected", "Key", "Status"]]
    for a in result.get("answers", []): data.append([str(a.get("question")), str(a.get("detected")), str(a.get("key")), str(a.get("status"))])
    at = Table(data, repeatRows=1, colWidths=[35, 65, 55, 170])
    at.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e7efff")), ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#d8e0eb")), ("FONTSIZE", (0,0), (-1,-1), 7), ("PADDING", (0,0), (-1,-1), 4)]))
    story.append(at)
    doc.build(story)
    result["original_file"] = str(original_path.relative_to(DATA_DIR))
    result["result_pdf"] = str(pdf_path.relative_to(DATA_DIR))
    result["scanned_at"] = stamp

@app.post("/api/scan")
async def scan(files: list[UploadFile] = File(...), answer_key: str=Form(...),
               marks: float=Form(1), negative: float=Form(0)):
    key="".join(ch for ch in answer_key.upper() if ch in "ABCD")
    if not 25 <= len(key) <= 200:
        raise HTTPException(400,"Answer key must contain 25–200 letters A/B/C/D.")
    if marks < 0 or negative < 0:
        raise HTTPException(400,"Marks cannot be negative.")
    if not files: raise HTTPException(400, "Upload at least one image or PDF.")
    total_bytes = 0
    results=[]
    # Keep only one rendered page in memory at a time; temporary page images are deleted after saving.
    batch_dir = Path(tempfile.mkdtemp(prefix="omr-batch-", dir=str(DATA_DIR)))
    try:
        global_index = 0
        for file in files:
            data = await file.read()
            total_bytes += len(data)
            if total_bytes > 100*1024*1024: raise HTTPException(413,"Combined upload limit is 100 MB per batch.")
            for page_index, img in enumerate(read_image(data, file.filename or "upload.jpg"), 1):
                global_index += 1
                if global_index > 1000: raise HTTPException(400, "Maximum 1000 sheets per batch.")
                temp_path = batch_dir / f"page-{global_index:04d}.jpg"
                cv2.imwrite(str(temp_path), img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                result=score_page(img,key,marks,negative)
                result["page"] = global_index
                result["source_page"] = page_index
                result["filename"] = file.filename or "upload"
                result["paper_title"] = "FJMC Academy Test"
                result["answers"] = result.get("answers", [])
                result["_temp_path"] = str(temp_path)
                results.append(result)
        # Dense rank within this batch: 100,100 -> 1, 95 -> 2.
        ranked = dense_rank(results)
        for r in ranked:
            img = cv2.imread(r.pop("_temp_path"))
            save_page_artifacts(img, r)
            save_result(r)
        return {"results": ranked, "count": len(ranked), "storage": "persistent-directory-configurable"}
    finally:
        shutil.rmtree(batch_dir, ignore_errors=True)

@app.get("/api/results")
def results_list():
    return {"results": dense_rank(load_saved_results())}

@app.post("/api/export")
def export(payload: dict):
    output=BytesIO()
    writer=csv.writer(output)
    writer.writerow(["Rank","Roll Number","Marks","Maximum","Correct","Wrong","Blank","Multiple","Filename","Original OMR","Result PDF"])
    results=dense_rank(payload.get("results",[]))
    for r in results:
        writer.writerow([r.get("rank"),r.get("roll_number") or "UNREADABLE",r.get("marks"),r.get("maximum"),r.get("correct"),r.get("wrong"),r.get("blank"),r.get("multiple"),r.get("filename"),r.get("original_file"),r.get("result_pdf")])
    return Response(output.getvalue(),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":'attachment; filename="fjmc-omr-results.csv"'})

@app.get("/api/results/pdf")
def export_results_pdf():
    results=dense_rank(load_saved_results())
    buf=BytesIO()
    doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=24,leftMargin=24,topMargin=28,bottomMargin=28)
    styles=getSampleStyleSheet()
    story=[Paragraph("FJMC ACADEMY — ALL STUDENTS RESULTS",styles["Title"]),Spacer(1,12)]
    rows=[["Rank","Roll No.","Marks","Max","Correct","Wrong","Blank"]]
    for r in results:
        rows.append([str(r.get("rank","")),str(r.get("roll_number") or "UNREADABLE"),str(r.get("marks",0)),str(r.get("maximum",0)),str(r.get("correct",0)),str(r.get("wrong",0)),str(r.get("blank",0))])
    table=Table(rows,repeatRows=1,colWidths=[40,90,55,50,50,50,45])
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e7efff")),("GRID",(0,0),(-1,-1),.4,colors.HexColor("#ccd6e5")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),("PADDING",(0,0),(-1,-1),5)]))
    story.append(table);doc.build(story)
    return Response(buf.getvalue(),media_type="application/pdf",headers={"Content-Disposition":'attachment; filename="fjmc-all-students-results.pdf"'})
