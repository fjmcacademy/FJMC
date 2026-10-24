from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from io import BytesIO
import json, csv, os, re, datetime, tempfile, shutil
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

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "frontend").is_dir() else HERE.parent
FRONTEND_DIR = ROOT / "frontend"
if not FRONTEND_DIR.is_dir():
    FRONTEND_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="FJMC Academy Smart OMR")
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
DATA_DIR = Path(os.environ.get("OMR_DATA_DIR", str(ROOT / "data"))).resolve()
SHEETS_DIR = DATA_DIR / "students"
SHEETS_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_FILE = DATA_DIR / "results.json"

W_MM, H_MM = 210.0, 297.0
IMG_W, IMG_H = 1240, 1754
OPTIONS = "ABCD"


def load_saved_results():
    try:
        data = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_result(result):
    records = load_saved_results()
    records.append(result)
    tmp = RESULTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(RESULTS_FILE)


def dense_rank(results):
    scores = sorted({float(r.get("marks", 0)) for r in results}, reverse=True)
    ranks = {score: i + 1 for i, score in enumerate(scores)}
    output = []
    for item in results:
        r = dict(item)
        r["rank"] = ranks.get(float(r.get("marks", 0)), "")
        output.append(r)
    return sorted(output, key=lambda r: (int(r.get("rank") or 10**9), str(r.get("roll_number") or "")))


@app.get("/", response_class=HTMLResponse)
def home():
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        return HTMLResponse("<h1>FJMC Academy Smart OMR</h1><p>Place index.html in the frontend folder.</p>")
    return index.read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    return {"ok": True, "app": "FJMC Academy Smart OMR"}


@app.get("/ocr-status")
def ocr_status():
    import shutil as sh
    path = sh.which("tesseract")
    if pytesseract is None:
        return {"installed": False, "path": path, "error": "pytesseract package is not installed"}
    try:
        return {"installed": True, "path": path, "version": str(pytesseract.get_tesseract_version())}
    except Exception as exc:
        return {"installed": False, "path": path, "error": str(exc)}


@app.post("/api/template")
def template(payload: dict):
    try:
        n = int(payload.get("questions", 50))
    except (TypeError, ValueError):
        raise HTTPException(400, "Questions must be an integer.")
    if not 25 <= n <= 200:
        raise HTTPException(400, "Questions must be between 25 and 200.")
    title = str(payload.get("title", "FJMC Academy Test"))[:80]
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(w / 2, h - 18 * mm, "FJMC ACADEMY")
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(w / 2, h - 25 * mm, title)
    c.setFont("Helvetica", 8)
    c.drawString(18 * mm, h - 34 * mm, "Name: __________________________________")
    c.setFont("Helvetica-Bold", 7)
    c.drawString(18 * mm, h - 41 * mm, "ROLL NUMBER (8 digits): Fill ONE bubble in each column")
    roll_x0, roll_dx = 42 * mm, 17 * mm
    roll_top, roll_dy = h - 47 * mm, 2.65 * mm
    for col in range(8):
        x = roll_x0 + col * roll_dx
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(x, roll_top + 1.4 * mm, str(col + 1))
        for digit in range(10):
            y = roll_top - digit * roll_dy
            c.setLineWidth(0.55)
            c.circle(x, y, 1.15 * mm, stroke=1, fill=0)
            c.setFont("Helvetica", 4.5)
            c.drawCentredString(x, y - 0.45 * mm, str(digit))
    c.setFont("Helvetica", 7)
    c.drawString(18 * mm, h - 76 * mm, f"Questions: {n}    Fill ONE bubble per question.")
    marker = 7 * mm
    for x, y in [(8 * mm, h - 15 * mm), (w - 15 * mm, h - 15 * mm), (8 * mm, 8 * mm), (w - 15 * mm, 8 * mm)]:
        c.setFillColorRGB(0, 0, 0)
        c.rect(x, y, marker, marker, fill=1, stroke=0)
    cols = 3
    rows = (n + cols - 1) // cols
    top, bottom = h - 81 * mm, 18 * mm
    row_h = min(7.0 * mm, (top - bottom) / rows)
    col_w = (w - 28 * mm) / cols
        for q in range(n):
        col, row = q // rows, q % rows
        x0 = 14 * mm + col * col_w
        y = top - row * row_h

        c.setFont("Helvetica", 7)
        c.drawRightString(x0 + 8 * mm, y, str(q + 1))

        for j, opt in enumerate(OPTIONS):
            bx = x0 + 12 * mm + j * 7.1 * mm
            by = y - 1.6 * mm

            c.setLineWidth(0.65)
            c.circle(bx, by, 1.8 * mm, stroke=1, fill=0)

            # Option label outside the bubble
            c.setFont("Helvetica", 5)
            c.drawCentredString(
                bx + 2.45 * mm,
                by - 1.5,
                opt
            )

    c.setFont("Helvetica", 7)
    c.drawCentredString(
        w / 2,
        10 * mm,
        "FJMC OMR | Print at 100% scale | Do not fold or cover markers"
    )

    c.save()
    return Response(
        buf.getvalue(),
        media_type="application/pdf",
        headers={
            "Content-Disposition":
            'attachment; filename="fjmc-omr-template.pdf"'
        }
    )
def read_image(data: bytes, filename: str):
    if filename.lower().endswith(".pdf"):
        try:
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception:
            raise HTTPException(400, "Could not open the uploaded PDF.")
        try:
            if len(doc) > 1000:
                raise HTTPException(400, "Maximum 1000 PDF pages per batch.")
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                yield cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        finally:
            doc.close()
        return
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "Could not read image. Use JPG, PNG or PDF.")
    yield img


def normalize_page(img):
    """Resize to template proportions. This does not correct perspective/cropping."""
    h, w = img.shape[:2]
    if w > h:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    return cv2.resize(img, (IMG_W, IMG_H), interpolation=cv2.INTER_CUBIC)


def dark_fraction(gray, cx, cy, radius, threshold=150):
    h, w = gray.shape[:2]
    x1, x2 = max(0, cx-radius), min(w, cx+radius+1)
    y1, y2 = max(0, cy-radius), min(h, cy+radius+1)
    if x1 >= x2 or y1 >= y2:
        return 0.0
    yy, xx = np.ogrid[y1:y2, x1:x2]
    mask = (xx-cx)**2 + (yy-cy)**2 <= radius**2
    crop = gray[y1:y2, x1:x2]
    count = int(np.count_nonzero(mask))
    return float(np.count_nonzero((crop < threshold) & mask)) / count if count else 0.0


def detect_roll_number(gray):
    h, w = gray.shape[:2]
    sx, sy = w / W_MM, h / H_MM
    digits, confidence, scores_all = [], [], []
    for col in range(8):
        cx = int((42.0 + col * 17.0) * sx)
        scores = []
        for digit in range(10):
            cy = int((47.0 + digit * 2.65) * sy)
            radius = max(2, int(0.42 * min(sx, sy)))
            scores.append(dark_fraction(gray, cx, cy, radius, 145))
        order = sorted(range(10), key=lambda d: scores[d], reverse=True)
        best, second = order[0], order[1]
        gap = scores[best] - scores[second]
        digits.append(str(best) if scores[best] >= 0.28 and gap >= 0.10 else "?")
        confidence.append(round(gap, 3))
        scores_all.append([round(v, 3) for v in scores])
    roll = "".join(digits)
    return (roll if "?" not in roll else None, digits, confidence, scores_all)


def detect_student_name(img):
    if pytesseract is None:
        return None
    try:
        h, w = img.shape[:2]
        x1, x2 = int(w * 18 / W_MM), int(w * 108 / W_MM)
        y1, y2 = int(h * 30 / H_MM), int(h * 39 / H_MM)
        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        text = pytesseract.image_to_string(gray, config="--psm 7")
        text = re.sub(r"[^A-Za-z .'-]", "", text).strip(" .-' ")
        text = re.sub(r"(?i)^name\s*:?\s*", "", text).strip()
        return text[:80] or None if len(re.sub(r"[^A-Za-z]", "", text)) >= 3 else None
    except Exception:
        return None

def detect_answer_bubble(gray, cx, cy, scale):
    # Measure only the central fill area.
    # Avoid the printed outline and the option label.
    radius = max(2, int(0.35 * scale))

    score = dark_fraction(
        gray, cx, cy, radius, threshold=100
    )

    return score



def score_page(img, key, marks, negative):
    img = normalize_page(img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    roll_number, roll_digits, roll_confidence, roll_scores = detect_roll_number(gray)
    student_name = detect_student_name(img)
    n = len(key)
    rows = (n + 2) // 3
    col_left = [(14 + 12) / W_MM, (14 + 182 / 3 + 12) / W_MM, (14 + 2 * 182 / 3 + 12) / W_MM]
    col_step = 7.1 / W_MM
    row_step_mm = min(7.0, 198.0 / rows)
    first_y = 82.6 / H_MM
    scale = min(IMG_W / W_MM, IMG_H / H_MM)
    answers = []
    correct = wrong = blank = multiple = review = 0
    total_marks = 0.0
    # Conservative starter thresholds; verify with actual printed/scanned sheets.
    BLANK_THRESHOLD = 0.08
    MARK_THRESHOLD = 0.13
    MULTI_THRESHOLD = 0.13
    MIN_GAP = 0.09

    for q in range(n):
        col, row = q // rows, q % rows
        cy = int((first_y + row * row_step_mm / H_MM) * IMG_H)
        cx0 = int(col_left[col] * IMG_W)
        vals = [detect_answer_bubble(gray, int(cx0 + j * col_step * IMG_W), cy, scale) for j in range(4)]
        order = sorted(range(4), key=lambda j: vals[j], reverse=True)
        first, second = order[0], order[1]
        best, second_best = vals[first], vals[second]
        gap = best - second_best
        detected, status = "—", "Review required"

        # FIX: second-best darkness alone does NOT mean multiple marks.
        # Require both bubbles to be dark and nearly tied.
        if best < BLANK_THRESHOLD:
            blank += 1
            detected, status = "—", "Blank"
        elif best >= MARK_THRESHOLD and second_best >= MULTI_THRESHOLD and gap < MIN_GAP:
            multiple += 1
            detected, status = "MULTI", "Multiple marks"
        elif best >= MARK_THRESHOLD and gap >= MIN_GAP:
            detected = OPTIONS[first]
            if detected == key[q]:
                correct += 1
                total_marks += marks
                status = "Correct"
            else:
                wrong += 1
                total_marks -= negative
                status = "Wrong"
        else:
            review += 1
            detected, status = "REVIEW", "Review required"

        if q < 10:
            print(f"[Q{q+1}] scores={[round(v, 3) for v in vals]}, best={best:.3f}, second={second_best:.3f}, gap={gap:.3f}, detected={detected}, status={status}")
        answers.append({"question": q + 1, "detected": detected, "key": key[q], "status": status, "bubble_darkness": [round(v, 3) for v in vals]})

    processed = correct + wrong + blank + multiple + review
    return {
        "questions": n, "roll_number": roll_number, "student_name": student_name,
        "roll_digits": roll_digits, "roll_confidence": roll_confidence, "roll_scores": roll_scores,
        "correct": correct, "wrong": wrong, "blank": blank, "multiple": multiple,
        "review_count": review, "processed": processed, "unprocessed": n - processed,
        "marks": round(total_marks, 2), "maximum": round(n * marks, 2), "answers": answers,
        "review_required": bool(multiple or review or not roll_number or not student_name)
    }


def save_page_artifacts(img, result):
    roll = result.get("roll_number") or "UNREADABLE"
    safe_roll = re.sub(r"[^0-9A-Za-z_-]", "_", roll)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = SHEETS_DIR / safe_roll / stamp
    folder.mkdir(parents=True, exist_ok=True)
    original_path = folder / "omr-original.jpg"
    cv2.imwrite(str(original_path), img, [cv2.IMWRITE_JPEG_QUALITY, 94])
    pdf_path = folder / "result.pdf"
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, rightMargin=18, leftMargin=18, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    story = [Paragraph("FJMC ACADEMY — OMR RESULT", styles["Title"]), Spacer(1, 8),
             Paragraph(f"Student name: <b>{result.get('student_name') or 'MANUAL REVIEW REQUIRED'}</b>", styles["Normal"]),
             Paragraph(f"Roll number: <b>{roll}</b>", styles["Normal"]),
             Paragraph(f"Scanned at (UTC): {stamp}", styles["Normal"]), Spacer(1, 10)]
    summary = [["Marks", "Maximum", "Correct", "Wrong", "Blank", "Multiple", "Review"],
               [str(result["marks"]), str(result["maximum"]), str(result["correct"]), str(result["wrong"]), str(result["blank"]), str(result["multiple"]), str(result["review_count"])]]
    table = Table(summary, repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7efff")), ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#ccd6e5")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 7), ("PADDING", (0, 0), (-1, -1), 5)]))
    story += [table, Spacer(1, 12)]
    data = [["Q", "Detected", "Key", "Status"]]
    data += [[str(a["question"]), str(a["detected"]), str(a["key"]), str(a["status"])] for a in result["answers"]]
    answer_table = Table(data, repeatRows=1, colWidths=[35, 65, 55, 170])
    answer_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7efff")), ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#d8e0eb")), ("FONTSIZE", (0, 0), (-1, -1), 7), ("PADDING", (0, 0), (-1, -1), 4)]))
    story.append(answer_table)
    doc.build(story)
    result["original_file"] = str(original_path.relative_to(DATA_DIR))
    result["result_pdf"] = str(pdf_path.relative_to(DATA_DIR))
    result["scanned_at"] = stamp


@app.post("/api/scan")
async def scan(files: list[UploadFile] = File(...), answer_key: str = Form(...), marks: float = Form(1), negative: float = Form(0)):
    key = "".join(ch for ch in answer_key.upper() if ch in OPTIONS)
    if not 25 <= len(key) <= 200:
        raise HTTPException(400, "Answer key must contain 25–200 A/B/C/D letters.")
    if marks < 0 or negative < 0:
        raise HTTPException(400, "Marks cannot be negative.")
    if not files:
        raise HTTPException(400, "Upload at least one image or PDF.")
    results, total_bytes = [], 0
    batch_dir = Path(tempfile.mkdtemp(prefix="omr-batch-", dir=str(DATA_DIR)))
    try:
        index = 0
        for file in files:
            data = await file.read()
            total_bytes += len(data)
            if total_bytes > 100 * 1024 * 1024:
                raise HTTPException(413, "Combined upload limit is 100 MB.")
            for page_index, img in enumerate(read_image(data, file.filename or "upload.jpg"), 1):
                index += 1
                if index > 1000:
                    raise HTTPException(400, "Maximum 1000 sheets per batch.")
                temp_path = batch_dir / f"page-{index:04d}.jpg"
                cv2.imwrite(str(temp_path), img)
                result = score_page(img, key, marks, negative)
                result.update({"page": index, "source_page": page_index, "filename": file.filename or "upload", "paper_title": "FJMC Academy Test", "_temp_path": str(temp_path)})
                results.append(result)
        ranked = dense_rank(results)
        for result in ranked:
            img = cv2.imread(result.pop("_temp_path"))
            save_page_artifacts(img, result)
            save_result(result)
        return {"results": ranked, "count": len(ranked), "storage": "persistent-directory-configurable"}
    finally:
        shutil.rmtree(batch_dir, ignore_errors=True)


@app.get("/api/results")
def results_list():
    return {"results": dense_rank(load_saved_results())}


@app.post("/api/export")
def export(payload: dict):
    output = BytesIO()
    writer = csv.writer(output)
    writer.writerow(["Rank", "Student Name", "Roll Number", "Marks", "Maximum", "Correct", "Wrong", "Blank", "Multiple", "Review", "Unprocessed", "Filename", "Original OMR", "Result PDF"])
    for r in dense_rank(payload.get("results", [])):
        writer.writerow([r.get("rank"), r.get("student_name") or "NAME REVIEW", r.get("roll_number") or "UNREADABLE", r.get("marks"), r.get("maximum"), r.get("correct"), r.get("wrong"), r.get("blank"), r.get("multiple"), r.get("review_count", 0), r.get("unprocessed", 0), r.get("filename"), r.get("original_file"), r.get("result_pdf")])
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="fjmc-omr-results.csv"'})


@app.get("/api/results/pdf")
def export_results_pdf():
    results = dense_rank(load_saved_results())
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=18, leftMargin=18, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    story = [Paragraph("FJMC ACADEMY — ALL STUDENTS RESULTS", styles["Title"]), Spacer(1, 12)]
    rows = [["Rank", "Name", "Roll No.", "Marks", "Max", "Correct", "Wrong", "Blank", "Multi", "Review"]]
    for r in results:
        rows.append([str(r.get("rank", "")), str(r.get("student_name") or "REVIEW"), str(r.get("roll_number") or "UNREADABLE"), str(r.get("marks", 0)), str(r.get("maximum", 0)), str(r.get("correct", 0)), str(r.get("wrong", 0)), str(r.get("blank", 0)), str(r.get("multiple", 0)), str(r.get("review_count", 0))])
    table = Table(rows, repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7efff")), ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#ccd6e5")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 7), ("PADDING", (0, 0), (-1, -1), 4)]))
    story.append(table)
    doc.build(story)
    return Response(buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="fjmc-all-students-results.pdf"'})
