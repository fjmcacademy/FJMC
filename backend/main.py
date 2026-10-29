from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from io import BytesIO
import json, csv, os, re, datetime, tempfile, shutil, base64, urllib.request, urllib.error
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
    c.drawString(18 * mm, h - 28 * mm, "Name: __________________________________")
    c.setFont("Helvetica-Bold", 7)
    c.drawString(18 * mm, h - 35 * mm, "ROLL NUMBER (8 digits): Fill ONE bubble in each column")
    roll_x0, roll_dx = 42 * mm, 17 * mm
    roll_top, roll_dy = h - 40 * mm, 2.65 * mm
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
    c.drawString(18 * mm, h - 68 * mm, f"Questions: {n}    Fill ONE bubble per question.")
    marker = 7 * mm
    for x, y in [(8 * mm, h - 15 * mm), (w - 15 * mm, h - 15 * mm), (8 * mm, 8 * mm), (w - 15 * mm, 8 * mm)]:
        c.setFillColorRGB(0, 0, 0)
        c.rect(x, y, marker, marker, fill=1, stroke=0)
    cols = 3
    rows = (n + cols - 1) // cols
    top, bottom = h - 74.5 * mm, 22 * mm
    row_h = min(7.0 * mm, (top - bottom) / rows)
    col_w = (w - 28 * mm) / cols
    for q in range(n):
        col, row = q // rows, q % rows
        x0 = 14 * mm + col * col_w
        y = top - row * row_h
        c.setFont("Helvetica", 7)
        c.drawRightString(x0 + 8 * mm, y, str(q + 1))
        for j, opt in enumerate(OPTIONS):
            bx, by = x0 + 12 * mm + j * 7.1 * mm, y - 1.6 * mm
            c.setLineWidth(0.65)
            c.circle(bx, by, 1.8 * mm, stroke=1, fill=0)
            c.setFont("Helvetica", 5.5)
            c.drawCentredString(bx, by - 0.7 * mm, opt)
    c.setFont("Helvetica", 7)
    c.drawCentredString(w / 2, 10 * mm, "FJMC OMR | Print at 100% scale | Do not fold or cover markers")
    c.save()
    return Response(buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="fjmc-omr-template.pdf"'})


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
    """Perspective-correct the sheet from its four registration squares; tolerate camera resolutions."""
    h, w = img.shape[:2]
    if w > h:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        h, w = img.shape[:2]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Black registration blocks remain detectable across ordinary phone resolutions.
    bw = cv2.threshold(gray, 90, 255, cv2.THRESH_BINARY_INV)[1]
    contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    short = min(h, w)
    min_side, max_side = max(8, int(short * 0.018)), int(short * 0.095)
    found = {}
    for contour in contours:
        x, y, ww, hh = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        if not (min_side <= ww <= max_side and min_side <= hh <= max_side
                and 0.65 <= ww / max(hh, 1) <= 1.5
                and area >= min_side * min_side * 0.45):
            continue
        # Approximate solid square blocks, not text strokes or small printed circles.
        fill_ratio = area / max(1, ww * hh)
        if fill_ratio < 0.48:
            continue
        cx, cy = x + ww / 2.0, y + hh / 2.0
        corner = None
        if cx < 0.28 * w and cy < 0.28 * h:
            corner = "tl"
        elif cx > 0.72 * w and cy < 0.28 * h:
            corner = "tr"
        elif cx < 0.28 * w and cy > 0.72 * h:
            corner = "bl"
        elif cx > 0.72 * w and cy > 0.72 * h:
            corner = "br"
        if corner and (corner not in found or area > found[corner][0]):
            found[corner] = (area, (cx, cy))

    if len(found) == 4:
        src = np.float32([found[k][1] for k in ("tl", "tr", "bl", "br")])
        # The four marks in the printed template are centred at these A4 coordinates.
        dst = np.float32([
            (11.5 / W_MM * IMG_W, 11.5 / H_MM * IMG_H),
            (198.5 / W_MM * IMG_W, 11.5 / H_MM * IMG_H),
            (11.5 / W_MM * IMG_W, 285.5 / H_MM * IMG_H),
            (198.5 / W_MM * IMG_W, 285.5 / H_MM * IMG_H),
        ])
        matrix = cv2.getPerspectiveTransform(src, dst)
        return cv2.warpPerspective(img, matrix, (IMG_W, IMG_H), flags=cv2.INTER_CUBIC,
                                   borderMode=cv2.BORDER_REPLICATE)

    # Keep the fallback fast. Circle-centre alignment below handles small residual skew.
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


def _generic_ink_fraction(gray, img, cx, cy, radius=3):
    """Colour-independent centre ink score for blue, black, red and other ordinary pens."""
    h, w = gray.shape[:2]
    cx, cy = int(cx), int(cy)
    radius = max(2, int(radius))
    x1, x2 = max(0, cx-radius), min(w, cx+radius+1)
    y1, y2 = max(0, cy-radius), min(h, cy+radius+1)
    if x1 >= x2 or y1 >= y2:
        return 0.0
    yy, xx = np.ogrid[y1:y2, x1:x2]
    disk = (xx-cx)**2 + (yy-cy)**2 <= radius**2
    patch = gray[y1:y2, x1:x2]
    # Local paper estimate compensates for shadows/uneven lighting on phone photos.
    xa, xb = max(0, cx-9), min(w, cx+10)
    ya, yb = max(0, cy-9), min(h, cy+10)
    yy2, xx2 = np.ogrid[ya:yb, xa:xb]
    dist2 = (xx2-cx)**2 + (yy2-cy)**2
    ring = (dist2 >= (radius+3)**2) & (dist2 <= 8**2)
    local = gray[ya:yb, xa:xb]
    vals = local[ring]
    # Absolute dark-ink detection is essential for black pens: a filled mark can
    # make the surrounding annulus dark too, which would defeat local-background subtraction.
    # Saturation below supplements it for bright red/blue/green pens.
    dark = patch < 145
    colour = np.zeros_like(dark, dtype=bool)
    if img is not None:
        hsv = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
        # Saturated ink catches coloured pens whose grayscale value is relatively bright.
        colour = (hsv[:, :, 1] >= 100) & (hsv[:, :, 2] <= 230)
    ink = (dark | colour) & disk
    count = int(np.count_nonzero(disk))
    return float(np.count_nonzero(ink)) / count if count else 0.0


def _cluster_positions(values, max_gap):
    """Group repeated circle detections into one centre per printed row."""
    groups = []
    for value in sorted(int(v) for v in values):
        if not groups or value - float(np.median(groups[-1])) > max_gap:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [int(round(float(np.median(group)))) for group in groups]


def _find_hough_circles(gray, roll=False):
    try:
        work = cv2.medianBlur(gray, 3 if roll else 5)
        if roll:
            circles = cv2.HoughCircles(work, cv2.HOUGH_GRADIENT, dp=1.2, minDist=10,
                                       param1=100, param2=16, minRadius=5, maxRadius=11)
        else:
            circles = cv2.HoughCircles(work, cv2.HOUGH_GRADIENT, dp=1.2, minDist=20,
                                       param1=100, param2=18, minRadius=6, maxRadius=14)
        if circles is None:
            return []
        return [tuple(map(int, c)) for c in np.round(circles[0]).astype(int)]
    except Exception:
        return []


def _blue_ink_fraction(hsv, cx, cy, radius=4):
    h, w = hsv.shape[:2]
    x1, x2 = max(0, cx-radius), min(w, cx+radius+1)
    y1, y2 = max(0, cy-radius), min(h, cy+radius+1)
    if x1 >= x2 or y1 >= y2:
        return 0.0
    yy, xx = np.ogrid[y1:y2, x1:x2]
    mask = (xx-cx)**2 + (yy-cy)**2 <= radius**2
    crop = hsv[y1:y2, x1:x2]
    ink = (crop[:, :, 0] >= 90) & (crop[:, :, 0] <= 150) & (crop[:, :, 1] >= 40) & (crop[:, :, 2] < 220)
    count = int(np.count_nonzero(mask))
    return float(np.count_nonzero(ink & mask)) / count if count else 0.0


def _roll_mark_score(gray, img, cx, cy):
    """Detect a solid fill blob while suppressing the thin printed digit inside each roll bubble."""
    h, w = gray.shape[:2]
    cx, cy = int(cx), int(cy)
    r = 5
    x1, x2 = max(0, cx-r), min(w, cx+r+1)
    y1, y2 = max(0, cy-r), min(h, cy+r+1)
    g = gray[y1:y2, x1:x2]
    if g.size == 0:
        return 0.0
    ink = (g < 115).astype(np.uint8) * 255
    if img is not None:
        hsv = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
        coloured = ((hsv[:, :, 1] >= 70) & (hsv[:, :, 2] <= 230)).astype(np.uint8) * 255
        ink = cv2.bitwise_or(ink, coloured)
    # A pen-filled bubble leaves a broad solid region; a printed digit is mostly thin strokes.
    opened = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return float(np.count_nonzero(opened)) / float(opened.size)


def detect_roll_number(gray, img=None):
    """Read eight roll digits independently of blue/black/red pen colour."""
    h, w = gray.shape[:2]
    circles = _find_hough_circles(gray, roll=True)
    sx, sy = w / W_MM, h / H_MM
    digits, confidence, scores_all = [], [], []
    # This printed sheet's first roll bubble is near 45 mm from the top.
    # Restrict Hough candidates to the roll grid, excluding heading text above it.
    for col in range(8):
        xnom = int((41.0 + col * 17.0) * sx)
        candidates = [(x, y, r) for x, y, r in circles
                      if abs(x-xnom) <= max(12, int(4.5*sx)) and int(0.14*h) <= y <= int(0.25*h)]
        row_centres = _cluster_positions([y for x, y, r in candidates], max(4, int(1.5*sy)))
        # If Hough misses a circle, use the nominal row and snap to any nearby detected circle.
        nominal_ys = [int((45.0 + digit * 2.65) * sy) for digit in range(10)]
        if len(row_centres) == 10:
            y_guesses = row_centres
        else:
            y_guesses = []
            for ynom in nominal_ys:
                near = [y for y in row_centres if abs(y-ynom) <= max(8, int(2.0*sy))]
                y_guesses.append(min(near, key=lambda y: abs(y-ynom)) if near else ynom)
        scores = []
        for yguess in y_guesses:
            nearby = [(x, y, r) for x, y, r in candidates if abs(y-yguess) <= max(5, int(1.2*sy))]
            if nearby:
                cx, cy, _ = min(nearby, key=lambda item: abs(item[0]-xnom) + 1.5*abs(item[1]-yguess))
            else:
                cx, cy = xnom, yguess
            scores.append(_roll_mark_score(gray, img, cx, cy))
        order = sorted(range(10), key=lambda d: scores[d], reverse=True)
        best, second = order[0], order[1]
        gap = scores[best] - scores[second]
        valid = scores[best] >= 0.28 and gap >= 0.18
        digits.append(str(best) if valid else "?")
        confidence.append(round(float(gap), 3))
        scores_all.append([round(float(v), 3) for v in scores])
    roll = "".join(digits)
    return (roll if "?" not in roll else None, digits, confidence, scores_all)


def _google_vision_name(crop):
    """Optional handwriting-capable OCR. Only sends the name crop if an API key is configured."""
    api_key = os.environ.get("GOOGLE_CLOUD_VISION_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            return None
        payload = {
            "requests": [{
                "image": {"content": base64.b64encode(encoded.tobytes()).decode("ascii")},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION", "maxResults": 1}],
                "imageContext": {"languageHints": ["en"]}
            }]
        }
        req = urllib.request.Request(
            "https://vision.googleapis.com/v1/images:annotate?key=" + api_key,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=3.5) as response:
            result = json.loads(response.read().decode("utf-8"))
        responses = result.get("responses", [])
        text = responses[0].get("fullTextAnnotation", {}).get("text", "") if responses else ""
        # This crop contains only the name line; strip any printed field label.
        text = re.sub(r"(?i)\bname\s*:?", " ", text)
        lines = [re.sub(r"[^A-Za-z .'-]", "", line).strip(" .'- ") for line in text.splitlines()]
        lines = [line for line in lines if len(re.sub(r"[^A-Za-z]", "", line)) >= 3]
        return max(lines, key=len)[:80] if lines else None
    except Exception:
        return None


def detect_student_name(img):
    """Read the name line with several fast local OCR passes; cloud OCR remains optional."""
    h, w = img.shape[:2]
    # Crop the name-writing area, excluding the printed 'Name:' label.
    x1, x2 = int(w * 26 / W_MM), int(w * 90 / W_MM)
    y1, y2 = int(h * 29.5 / H_MM), int(h * 37 / H_MM)
    crop = img[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
    if crop.size == 0:
        return None

    cloud_text = _google_vision_name(crop)
    if cloud_text:
        return cloud_text
    if pytesseract is None:
        return None

    try:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        variants = [gray, cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]]
        candidates = []
        for variant in variants:
            enlarged = cv2.resize(variant, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
            enlarged = cv2.copyMakeBorder(enlarged, 18, 18, 18, 18, cv2.BORDER_CONSTANT, value=255)
            for psm in (7, 13, 8):
                try:
                    raw = pytesseract.image_to_string(
                        enlarged,
                        config=f"--oem 1 --psm {psm}",
                        timeout=1.2)
                except Exception:
                    continue
                text = re.sub(r"(?i)\bname\b", " ", raw)
                text = re.sub(r"[^A-Za-z '-]", " ", text)
                text = re.sub(r"\s+", " ", text).strip(" '-")
                letters = re.sub(r"[^A-Za-z]", "", text)
                if len(letters) >= 3:
                    candidates.append((len(letters), text.upper()))
        if not candidates:
            return None
        # Prefer plausible multi-word names over fragments and label leftovers.
        candidates.sort(key=lambda item: (item[0], " " in item[1]), reverse=True)
        best = candidates[0][1]
        return best[:80] if best else None
    except Exception:
        return None

def detect_answer_bubble(gray, cx, cy, scale, img=None):
    """Measure a wider inner disk so printed option letters don't look like filled marks."""
    radius = max(4, int(0.85 * scale))
    return _generic_ink_fraction(gray, img, cx, cy, radius)


def find_question_bubble_centres(gray, n):
    """Find common question rows across all three columns after page normalization."""
    rows = (n + 2) // 3
    sx = IMG_W / W_MM
    col_left_mm = [26.0, 14.0 + (210.0 - 28.0) / 3.0 + 12.0,
                   14.0 + 2.0 * (210.0 - 28.0) / 3.0 + 12.0]
    nominal_x = [[int(round((col_left_mm[col] + j * 7.1) * sx)) for j in range(4)]
                 for col in range(3)]
    all_x = [x for column in nominal_x for x in column]
    circles = _find_hough_circles(gray, roll=False)
    relevant = [(x, y, r) for x, y, r in circles
                if 390 <= y <= IMG_H - 50 and min(abs(x - xc) for xc in all_x) <= 16]

    # Group circles by row. Require evidence at multiple option positions to reject
    # stray Hough detections from heading text.
    grouped = []
    for x, y, r in sorted(relevant, key=lambda c: c[1]):
        if not grouped or y - float(np.median([c[1] for c in grouped[-1]])) > 10:
            grouped.append([(x, y, r)])
        else:
            grouped[-1].append((x, y, r))
    supported_rows = []
    for group in grouped:
        bins = set()
        for x, y, r in group:
            nearest = min(range(len(all_x)), key=lambda i: abs(all_x[i] - x))
            if abs(all_x[nearest] - x) <= 16:
                bins.add(nearest)
        if len(bins) >= 3:
            supported_rows.append(int(round(float(np.median([c[1] for c in group])))))

    if len(supported_rows) == rows:
        row_ys = supported_rows
    elif len(supported_rows) > rows:
        best_run, best_cost = None, float("inf")
        for start in range(len(supported_rows) - rows + 1):
            run = supported_rows[start:start + rows]
            gaps = np.diff(run)
            med = float(np.median(gaps)) if len(gaps) else 0.0
            cost = float(np.mean(np.abs(gaps - med))) if len(gaps) else 0.0
            if cost < best_cost:
                best_run, best_cost = run, cost
        row_ys = best_run if best_run else supported_rows[:rows]
    elif len(supported_rows) >= max(3, rows - 3):
        step = float(np.median(np.diff(supported_rows)))
        row_ys = [int(round(supported_rows[0] + i * step)) for i in range(rows)]
    else:
        # Fallbacks for the two common FJMC template layouts; row detection is preferred.
        step_mm = min(7.0, 200.5 / rows)
        start_mm = 82.4 if n == 100 else 76.1
        row_ys = [int(round((start_mm + i * step_mm) * IMG_H / H_MM)) for i in range(rows)]

    centres = {}
    for col in range(3):
        count = min(rows, max(0, n - col * rows))
        for row in range(count):
            centres[(col, row)] = [(x, row_ys[row]) for x in nominal_x[col]]
    return centres

def score_page(img, key, marks, negative):
    img = normalize_page(img)
    raw_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(raw_gray, (3, 3), 0)
    roll_number, roll_digits, roll_confidence, roll_scores = detect_roll_number(raw_gray, img)
    student_name = detect_student_name(img)
    n = len(key)
    rows = (n + 2) // 3
    scale = min(IMG_W / W_MM, IMG_H / H_MM)
    bubble_centres = find_question_bubble_centres(raw_gray, n)
    answers = []
    correct = wrong = blank = multiple = review = 0
    total_marks = 0.0

    # Centre alignment makes empty outlines score near zero and a genuinely filled
    # bubble score high. Ambiguous cases are reviewed, never silently guessed.
    BLANK_THRESHOLD = 0.42
    MARK_THRESHOLD = 0.42
    MULTI_THRESHOLD = 0.62
    MIN_GAP = 0.16

    for q in range(n):
        col, row = q // rows, q % rows
        centres = bubble_centres.get((col, row))
        if centres is None:
            # Defensive fallback for unusual question counts.
            step = min(7.0, 198.0 / rows)
            start_y = [81.5, 79.8, 79.8][col]
            cy = int((start_y + row * step) * IMG_H / H_MM)
            col_left_mm = [26.0, 14.0 + 182.0 / 3.0 + 12.0, 14.0 + 2.0 * 182.0 / 3.0 + 12.0]
            centres = [(int((col_left_mm[col] + j * 7.1) * IMG_W / W_MM), cy) for j in range(4)]
        vals = [detect_answer_bubble(raw_gray, cx, cy, scale, img) for cx, cy in centres]
        order = sorted(range(4), key=lambda j: vals[j], reverse=True)
        first, second = order[0], order[1]
        best, second_best = vals[first], vals[second]
        gap = best - second_best
        detected, status = "REVIEW", "Review required"

        if best < BLANK_THRESHOLD:
            blank += 1
            detected, status = "—", "Blank"
        elif best < MARK_THRESHOLD:
            review += 1
        elif second_best >= MULTI_THRESHOLD and gap < MIN_GAP:
            multiple += 1
            detected, status = "MULTI", "Multiple marks"
        elif gap >= MIN_GAP:
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

        answers.append({"question": q + 1, "detected": detected, "key": key[q], "status": status,
                        "bubble_darkness": [round(v, 3) for v in vals]})

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
