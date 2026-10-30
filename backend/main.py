from image_pipeline import prepare_mobile_photo
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from pathlib import Path
from io import BytesIO
from html import escape
import json
import csv
import os
import re
import datetime
import tempfile
import shutil
import threading
import math

import cv2
import numpy as np
import fitz

# =========================================================
# OPTIONAL OCR ENGINES
# =========================================================

try:
    import easyocr
    EASY_OCR_AVAILABLE = True
except ImportError:
    easyocr = None
    EASY_OCR_AVAILABLE = False

try:
    import pytesseract
except ImportError:
    pytesseract = None

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer
)
from reportlab.lib.styles import getSampleStyleSheet


# =========================================================
# APPLICATION SETTINGS
# =========================================================

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "frontend").is_dir() else HERE.parent

FRONTEND_DIR = ROOT / "frontend"
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="FJMC Academy Smart OMR")

app.mount(
    "/static",
    StaticFiles(directory=str(FRONTEND_DIR)),
    name="static"
)

DATA_DIR = Path(
    os.environ.get("OMR_DATA_DIR", str(ROOT / "data"))
).resolve()

SHEETS_DIR = DATA_DIR / "students"
SHEETS_DIR.mkdir(parents=True, exist_ok=True)

RESULTS_FILE = DATA_DIR / "results.json"

W_MM = 210.0
H_MM = 297.0

IMG_W = 1240
IMG_H = 1754

OPTIONS = "ABCD"

MAX_UPLOAD_MB = 100
MAX_PAGES = 1000

# OCR settings
OCR_LANGUAGES = ["en"]

_easyocr_reader = None
_easyocr_lock = threading.Lock()

# Scanner state
LAST_SCAN_ERRORS = []


# =========================================================
# EASY OCR INITIALIZATION
# =========================================================

def get_easyocr_reader():

    global _easyocr_reader

    if not EASY_OCR_AVAILABLE:
        return None

    if _easyocr_reader is None:

        with _easyocr_lock:

            if _easyocr_reader is None:

                print("Loading EasyOCR model...")

                _easyocr_reader = easyocr.Reader(
                    OCR_LANGUAGES,
                    gpu=False,
                    verbose=False
                )

                print("EasyOCR model loaded.")

    return _easyocr_reader


# =========================================================
# RESULT STORAGE
# =========================================================

def load_saved_results():

    try:

        if not RESULTS_FILE.exists():
            return []

        data = json.loads(
            RESULTS_FILE.read_text(encoding="utf-8")
        )

        return data if isinstance(data, list) else []

    except Exception as exc:

        print("Result loading error:", exc)
        return []


def save_result(result):

    records = load_saved_results()

    records.append(result)

    tmp = RESULTS_FILE.with_suffix(".tmp")

    tmp.write_text(
        json.dumps(
            records,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    tmp.replace(RESULTS_FILE)


def dense_rank(results):

    scores = sorted(
        {
            round(float(r.get("marks", 0)), 2)
            for r in results
        },
        reverse=True
    )

    ranks = {
        score: i + 1
        for i, score in enumerate(scores)
    }

    output = []

    for item in results:

        r = dict(item)

        score = round(float(r.get("marks", 0)), 2)

        r["rank"] = ranks.get(score, "")

        output.append(r)

    return sorted(
        output,
        key=lambda r: (
            int(r.get("rank") or 10**9),
            str(r.get("roll_number") or "")
        )
    )


# =========================================================
# HOME PAGE
# =========================================================

@app.get("/", response_class=HTMLResponse)
def home():

    index = FRONTEND_DIR / "index.html"

    if not index.exists():

        return HTMLResponse(
            "<h1>FJMC Academy Smart OMR</h1>"
            "<p>Place index.html inside frontend folder.</p>"
        )

    return index.read_text(encoding="utf-8")


@app.get("/api/health")
def health():

    return {
        "ok": True,
        "app": "FJMC Academy Smart OMR",
        "easyocr": EASY_OCR_AVAILABLE
    }


@app.get("/ocr-status")
def ocr_status():

    import shutil as sh

    tesseract_path = sh.which("tesseract")

    easyocr_status = EASY_OCR_AVAILABLE

    return {
        "easyocr_package": easyocr_status,
        "easyocr_model_loaded": _easyocr_reader is not None,
        "tesseract_package": pytesseract is not None,
        "tesseract_path": tesseract_path
    }


# =========================================================
# TEMPLATE GENERATOR
# =========================================================

@app.post("/api/template")
def template(payload: dict):

    try:
        n = int(payload.get("questions", 50))
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid question count.")

    if not 25 <= n <= 200:
        raise HTTPException(
            400,
            "Questions must be between 25 and 200."
        )

    title = str(
        payload.get("title", "FJMC Academy Test")
    )[:80]

    buf = BytesIO()

    c = canvas.Canvas(buf, pagesize=A4)

    w, h = A4

    # Heading
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(
        w / 2,
        h - 18 * mm,
        "FJMC ACADEMY"
    )

    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(
        w / 2,
        h - 25 * mm,
        title
    )

    # Name
    c.setFont("Helvetica", 8)

    c.drawString(
        18 * mm,
        h - 34 * mm,
        "Name: __________________________________"
    )

    # Roll number
    c.setFont("Helvetica-Bold", 7)

    c.drawString(
        18 * mm,
        h - 41 * mm,
        "ROLL NUMBER (8 digits): Fill ONE bubble in each column"
    )

    roll_x0 = 42 * mm
    roll_dx = 17 * mm

    roll_top = h - 47 * mm
    roll_dy = 2.65 * mm

    for col in range(8):

        x = roll_x0 + col * roll_dx

        c.setFont("Helvetica-Bold", 7)

        c.drawCentredString(
            x,
            roll_top + 1.4 * mm,
            str(col + 1)
        )

        for digit in range(10):

            y = roll_top - digit * roll_dy

            c.setLineWidth(0.55)

            c.circle(
                x,
                y,
                1.15 * mm,
                stroke=1,
                fill=0
            )

            c.setFont("Helvetica", 4.5)

            c.drawCentredString(
                x,
                y - 0.45 * mm,
                str(digit)
            )

    c.setFont("Helvetica", 7)

    c.drawString(
        18 * mm,
        h - 76 * mm,
        f"Questions: {n}    Fill ONE bubble per question."
    )

    # Corner markers
    marker = 7 * mm

    for x, y in [
        (8 * mm, h - 15 * mm),
        (w - 15 * mm, h - 15 * mm),
        (8 * mm, 8 * mm),
        (w - 15 * mm, 8 * mm)
    ]:

        c.setFillColorRGB(0, 0, 0)

        c.rect(
            x,
            y,
            marker,
            marker,
            fill=1,
            stroke=0
        )

    # Answer bubbles
    cols = 3

    rows = (n + cols - 1) // cols

    top = h - 81 * mm
    bottom = 18 * mm

    row_h = min(
        7.0 * mm,
        (top - bottom) / rows
    )

    col_w = (w - 28 * mm) / cols

    for q in range(n):

        col = q // rows
        row = q % rows

        x0 = 14 * mm + col * col_w

        y = top - row * row_h

        c.setFont("Helvetica", 7)

        c.drawRightString(
            x0 + 8 * mm,
            y,
            str(q + 1)
        )

        for j, opt in enumerate(OPTIONS):

            bx = x0 + 12 * mm + j * 7.1 * mm
            by = y - 1.6 * mm

            c.setLineWidth(0.65)

            c.circle(
                bx,
                by,
                1.8 * mm,
                stroke=1,
                fill=0
            )

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


# =========================================================
# IMAGE / PDF READING
# =========================================================

def read_image(data: bytes, filename: str):

    if filename.lower().endswith(".pdf"):

        try:

            doc = fitz.open(
                stream=data,
                filetype="pdf"
            )

        except Exception:

            raise HTTPException(
                400,
                "Could not open uploaded PDF."
            )

        try:

            if len(doc) > MAX_PAGES:

                raise HTTPException(
                    400,
                    "Maximum 1000 PDF pages per batch."
                )

            for page in doc:

                pix = page.get_pixmap(
                    matrix=fitz.Matrix(2, 2),
                    alpha=False
                )

                arr = np.frombuffer(
                    pix.samples,
                    dtype=np.uint8
                ).reshape(
                    pix.height,
                    pix.width,
                    pix.n
                )

                yield cv2.cvtColor(
                    arr,
                    cv2.COLOR_RGB2BGR
                )

        finally:

            doc.close()

        return

    arr = np.frombuffer(
        data,
        dtype=np.uint8
    )

    img = cv2.imdecode(
        arr,
        cv2.IMREAD_COLOR
    )

    if img is None:

        raise HTTPException(
            400,
            "Could not read image. Use JPG, PNG or PDF."
        )

    yield img


# =========================================================
# AUTOMATIC PAGE DETECTION
# =========================================================

def find_corner_markers(img):

    """
    Find four black square corner markers.
    Returns centers in TL, TR, BR, BL order.
    """

    h, w = img.shape[:2]

    gray = cv2.cvtColor(
        img,
        cv2.COLOR_BGR2GRAY
    )

    gray = cv2.GaussianBlur(
        gray,
        (5, 5),
        0
    )

    _, binary = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    contours, _ = cv2.findContours(
        binary,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    candidates = []

    min_area = h * w * 0.00015
    max_area = h * w * 0.025

    for contour in contours:

        area = cv2.contourArea(contour)

        if not min_area <= area <= max_area:
            continue

        x, y, cw, ch = cv2.boundingRect(contour)

        ratio = cw / max(ch, 1)

        if not 0.65 <= ratio <= 1.35:
            continue

        if cw < w * 0.008 or ch < h * 0.008:
            continue

        fill_ratio = area / max(cw * ch, 1)

        if fill_ratio < 0.55:
            continue

        M = cv2.moments(contour)

        if M["m00"] == 0:
            continue

        cx = M["m10"] / M["m00"]
        cy = M["m01"] / M["m00"]

        candidates.append(
            (cx, cy, area)
        )

    if len(candidates) < 4:
        return None

    # Search separately in four page regions
    regions = [
        (0, 0, 0.38, 0.38),       # TL
        (0.62, 0, 1.0, 0.38),     # TR
        (0.62, 0.62, 1.0, 1.0),   # BR
        (0, 0.62, 0.38, 1.0)      # BL
    ]

    points = []

    for rx1, ry1, rx2, ry2 in regions:

        region_candidates = []

        for cx, cy, area in candidates:

            nx = cx / w
            ny = cy / h

            if (
                rx1 <= nx <= rx2
                and ry1 <= ny <= ry2
            ):

                region_candidates.append(
                    (cx, cy, area)
                )

        if not region_candidates:
            return None

        # Choose candidate closest to corresponding page corner
        def distance(p):

            cx, cy, area = p

            if rx1 == 0 and ry1 == 0:
                target = (0.055 * w, 0.04 * h)

            elif rx1 > 0 and ry1 == 0:
                target = (0.945 * w, 0.04 * h)

            elif rx1 > 0 and ry1 > 0:
                target = (0.945 * w, 0.96 * h)

            else:
                target = (0.055 * w, 0.96 * h)

            return math.hypot(
                cx - target[0],
                cy - target[1]
            )

        best = min(
            region_candidates,
            key=distance
        )

        points.append(
            [best[0], best[1]]
        )

    return np.float32(points)


def normalize_page(img):

    """
    Correct perspective when all four markers are visible.
    Otherwise use a fallback resize and flag alignment.
    """

    h, w = img.shape[:2]

    if w > h:

        img = cv2.rotate(
            img,
            cv2.ROTATE_90_CLOCKWISE
        )

    points = find_corner_markers(img)

    if points is None:

        print(
            "WARNING: Four corner markers not detected. "
            "Using resize fallback."
        )

        corrected = cv2.resize(
            img,
            (IMG_W, IMG_H),
            interpolation=cv2.INTER_CUBIC
        )

        return corrected, False

    # Marker center coordinates in template
    sx = IMG_W / W_MM
    sy = IMG_H / H_MM

    destination = np.float32([
        [11.5 * sx, 11.5 * sy],
        [198.5 * sx, 11.5 * sy],
        [198.5 * sx, 285.5 * sy],
        [11.5 * sx, 285.5 * sy]
    ])

    matrix = cv2.getPerspectiveTransform(
        points,
        destination
    )

    corrected = cv2.warpPerspective(
        img,
        matrix,
        (IMG_W, IMG_H),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )

    return corrected, True


# =========================================================
# IMAGE PREPROCESSING
# =========================================================

def preprocess_gray(img):

    gray = cv2.cvtColor(
        img,
        cv2.COLOR_BGR2GRAY
    )

    # Local contrast enhancement
    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )

    gray = clahe.apply(gray)

    return gray


# =========================================================
# BUBBLE ANALYSIS
# =========================================================

def circular_mask(shape, cx, cy, inner_radius, outer_radius):

    h, w = shape

    x1 = max(0, int(cx - outer_radius - 1))
    x2 = min(w, int(cx + outer_radius + 2))

    y1 = max(0, int(cy - outer_radius - 1))
    y2 = min(h, int(cy + outer_radius + 2))

    yy, xx = np.ogrid[y1:y2, x1:x2]

    distance = np.sqrt(
        (xx - cx) ** 2 + (yy - cy) ** 2
    )

    mask = (
        (distance >= inner_radius)
        & (distance <= outer_radius)
    )

    return x1, x2, y1, y2, mask


def bubble_ink_score(img, gray, cx, cy, radius_mm):

    """
    Measures ink inside a bubble while avoiding its printed outline.
    Detects dark and reasonably saturated colored pen ink.
    """

    h, w = gray.shape

    sx = w / W_MM
    sy = h / H_MM

    scale = min(sx, sy)

    outer = max(3, int(radius_mm * scale))
    inner = max(1, int(0.18 * outer))

    x1, x2, y1, y2, mask = circular_mask(
        gray.shape,
        cx,
        cy,
        inner,
        outer
    )

    crop = gray[y1:y2, x1:x2]

    if crop.size == 0 or not np.any(mask):
        return 0.0

    # Local background from surrounding paper
    outer_bg = max(outer + 2, int(1.55 * outer))

    bx1 = max(0, cx - outer_bg)
    bx2 = min(w, cx + outer_bg + 1)

    by1 = max(0, cy - outer_bg)
    by2 = min(h, cy + outer_bg + 1)

    background = gray[by1:by2, bx1:bx2]

    if background.size == 0:
        threshold = 180
    else:
        median_bg = float(np.median(background))
        threshold = int(
            np.clip(median_bg - 38, 105, 215)
        )

    hsv = cv2.cvtColor(
        img[y1:y2, x1:x2],
        cv2.COLOR_BGR2HSV
    )

    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]

    dark_pixels = crop < threshold

    colored_pixels = (
        (saturation > 45)
        & (value < 245)
    )

    ink = (
        dark_pixels | colored_pixels
    ) & mask

    total = int(np.count_nonzero(mask))

    return (
        float(np.count_nonzero(ink)) / total
        if total else 0.0
    )


# =========================================================
# ROLL NUMBER DETECTION
# =========================================================

def detect_roll_number(img, gray):

    h, w = gray.shape

    sx = w / W_MM
    sy = h / H_MM

    digits = []
    confidence = []
    scores_all = []

    for col in range(8):

        cx = int(
            (42.0 + col * 17.0) * sx
        )

        scores = []

        for digit in range(10):

            cy = int(
                (47.0 + digit * 2.65) * sy
            )

            # Exclude printed digit in the center.
            # Analyze the ring where shading occurs.
            score = bubble_ink_score(
                img,
                gray,
                cx,
                cy,
                0.95
            )

            scores.append(score)

        order = sorted(
            range(10),
            key=lambda d: scores[d],
            reverse=True
        )

        best = order[0]
        second = order[1]

        best_score = scores[best]
        second_score = scores[second]

        gap = best_score - second_score

        if best_score >= 0.12 and gap >= 0.045:

            digits.append(str(best))

        else:

            digits.append("?")

        confidence.append(
            round(gap, 3)
        )

        scores_all.append(
            [round(v, 3) for v in scores]
        )

    roll = "".join(digits)

    valid_roll = (
        roll if "?" not in roll else None
    )

    return (
        valid_roll,
        digits,
        confidence,
        scores_all
    )


# =========================================================
# EASY OCR: HANDWRITTEN STUDENT NAME
# =========================================================

def detect_student_name(img):

    reader = get_easyocr_reader()

    if reader is None:
        return None

    try:

        h, w = img.shape[:2]

        x1 = int(w * 18 / W_MM)
        x2 = int(w * 125 / W_MM)

        y1 = int(h * 30 / H_MM)
        y2 = int(h * 39 / H_MM)

        crop = img[y1:y2, x1:x2]

        if crop.size == 0:
            return None

        crop = cv2.resize(
            crop,
            None,
            fx=4,
            fy=4,
            interpolation=cv2.INTER_CUBIC
        )

        gray = cv2.cvtColor(
            crop,
            cv2.COLOR_BGR2GRAY
        )

        clahe = cv2.createCLAHE(
            clipLimit=2.0,
            tileGridSize=(8, 8)
        )

        enhanced = clahe.apply(gray)

        enhanced = cv2.fastNlMeansDenoising(
            enhanced,
            None,
            8,
            7,
            21
        )

        results = reader.readtext(
            enhanced,
            detail=1,
            paragraph=False,
            decoder="beamsearch",
            batch_size=1,
            workers=0,
            allowlist=(
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "abcdefghijklmnopqrstuvwxyz .-'"
            )
        )

        candidates = []

        for item in results:

            text = str(item[1])
            confidence = float(item[2])

            text = re.sub(
                r"[^A-Za-z .'-]",
                "",
                text
            ).strip()

            text = re.sub(
                r"(?i)^name\s*:?\s*",
                "",
                text
            ).strip()

            letters = re.sub(
                r"[^A-Za-z]",
                "",
                text
            )

            if len(letters) >= 3:

                candidates.append(
                    (text.upper(), confidence)
                )

        if not candidates:
            return None

        candidates.sort(
            key=lambda x: x[1],
            reverse=True
        )

        name, confidence = candidates[0]

        if confidence < 0.30:
            return None

        return name[:80]

    except Exception as exc:

        print("EasyOCR name error:", exc)

        return None


# =========================================================
# HANDWRITTEN ROLL NUMBER FALLBACK
# =========================================================

def detect_handwritten_roll(img):

    reader = get_easyocr_reader()

    if reader is None:
        return None

    try:

        h, w = img.shape[:2]

        x1 = int(w * 35 / W_MM)
        x2 = int(w * 185 / W_MM)

        y1 = int(h * 43 / H_MM)
        y2 = int(h * 75 / H_MM)

        crop = img[y1:y2, x1:x2]

        if crop.size == 0:
            return None

        crop = cv2.resize(
            crop,
            None,
            fx=2,
            fy=2,
            interpolation=cv2.INTER_CUBIC
        )

        results = reader.readtext(
            crop,
            detail=1,
            paragraph=False,
            allowlist="0123456789"
        )

        candidates = []

        for item in results:

            text = re.sub(
                r"\D",
                "",
                str(item[1])
            )

            confidence = float(item[2])

            if len(text) == 8 and confidence >= 0.50:

                candidates.append(
                    (text, confidence)
                )

        if not candidates:
            return None

        candidates.sort(
            key=lambda x: x[1],
            reverse=True
        )

        return candidates[0][0]

    except Exception as exc:

        print("Roll OCR error:", exc)

        return None


# =========================================================
# ANSWER BUBBLE DETECTION
# =========================================================

def detect_answer_bubble(img, gray, cx, cy):

    return bubble_ink_score(
        img,
        gray,
        cx,
        cy,
        0.85
    )


# =========================================================
# SCORE COMPLETE SHEET
# =========================================================

def score_page(img, key, marks, negative):

    img, alignment_ok = normalize_page(img)

    gray = preprocess_gray(img)

    roll_number, roll_digits, roll_confidence, roll_scores = (
        detect_roll_number(img, gray)
    )

    student_name = detect_student_name(img)

    handwritten_roll = None

    if not roll_number:
        handwritten_roll = detect_handwritten_roll(img)

    if not roll_number and handwritten_roll:
        roll_number = handwritten_roll

    n = len(key)

    rows = (n + 2) // 3

    col_left = [
        26 / W_MM,
        (14 + 182 / 3 + 12) / W_MM,
        (14 + 2 * 182 / 3 + 12) / W_MM
    ]

    col_step = 7.1 / W_MM

    row_step_mm = min(
        7.0,
        198.0 / rows
    )

    first_y = 82.6 / H_MM

    answers = []

    correct = 0
    wrong = 0
    blank = 0
    multiple = 0
    review = 0

    total_marks = 0.0

    BLANK_THRESHOLD = 0.065
    MARK_THRESHOLD = 0.12
    MULTI_THRESHOLD = 0.12
    MIN_GAP = 0.055

    for q in range(n):

        col = q // rows
        row = q % rows

        cy = int(
            (
                first_y
                + row * row_step_mm / H_MM
            ) * IMG_H
        )

        cx0 = int(
            col_left[col] * IMG_W
        )

        vals = []

        for j in range(4):

            cx = int(
                cx0 + j * col_step * IMG_W
            )

            score = detect_answer_bubble(
                img,
                gray,
                cx,
                cy
            )

            vals.append(score)

        order = sorted(
            range(4),
            key=lambda j: vals[j],
            reverse=True
        )

        first = order[0]
        second = order[1]

        best = vals[first]
        second_best = vals[second]

        gap = best - second_best

        detected = "REVIEW"
        status = "Review required"

        if best < BLANK_THRESHOLD:

            blank += 1

            detected = "—"
            status = "Blank"

        elif (
            best >= MARK_THRESHOLD
            and second_best >= MULTI_THRESHOLD
            and gap < MIN_GAP
        ):

            multiple += 1

            detected = "MULTI"
            status = "Multiple marks"

        elif (
            best >= MARK_THRESHOLD
            and gap >= MIN_GAP
        ):

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

            detected = "REVIEW"
            status = "Review required"

        answers.append({
            "question": q + 1,
            "detected": detected,
            "key": key[q],
            "status": status,
            "confidence": round(gap, 3),
            "bubble_darkness": [
                round(v, 3)
                for v in vals
            ]
        })

    processed = (
        correct + wrong + blank + multiple + review
    )

    return {

        "questions": n,

        "roll_number": roll_number,
        "student_name": student_name,

        "roll_digits": roll_digits,
        "roll_confidence": roll_confidence,
        "roll_scores": roll_scores,

        "handwritten_roll": handwritten_roll,

        "alignment_corrected": alignment_ok,

        "correct": correct,
        "wrong": wrong,
        "blank": blank,
        "multiple": multiple,
        "review_count": review,

        "processed": processed,
        "unprocessed": n - processed,

        "marks": round(total_marks, 2),
        "maximum": round(n * marks, 2),

        "answers": answers,

        "review_required": bool(
            multiple
            or review
            or not roll_number
            or not student_name
            or not alignment_ok
        )
    }


# =========================================================
# SAVE STUDENT FILES
# =========================================================

def save_page_artifacts(img, result):

    roll = result.get("roll_number") or "UNREADABLE"

    safe_roll = re.sub(
        r"[^0-9A-Za-z_-]",
        "_",
        roll
    )

    stamp = datetime.datetime.now(
        datetime.timezone.utc
    ).strftime("%Y%m%dT%H%M%S%fZ")

    folder = SHEETS_DIR / safe_roll / stamp

    folder.mkdir(
        parents=True,
        exist_ok=True
    )

    original_path = folder / "omr-original.jpg"

    cv2.imwrite(
        str(original_path),
        img,
        [cv2.IMWRITE_JPEG_QUALITY, 94]
    )

    pdf_path = folder / "result.pdf"

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=18,
        leftMargin=18,
        topMargin=20,
        bottomMargin=20
    )

    styles = getSampleStyleSheet()

    name = escape(
        str(result.get("student_name") or "MANUAL REVIEW REQUIRED")
    )

    story = [
        Paragraph(
            "FJMC ACADEMY — OMR RESULT",
            styles["Title"]
        ),
        Spacer(1, 8),

        Paragraph(
            f"Student name: <b>{name}</b>",
            styles["Normal"]
        ),

        Paragraph(
            f"Roll number: <b>{escape(str(roll))}</b>",
            styles["Normal"]
        ),

        Paragraph(
            f"Alignment corrected: {result.get('alignment_corrected')}",
            styles["Normal"]
        ),

        Paragraph(
            f"Scanned at (UTC): {stamp}",
            styles["Normal"]
        ),

        Spacer(1, 10)
    ]

    summary = [
        [
            "Marks",
            "Maximum",
            "Correct",
            "Wrong",
            "Blank",
            "Multiple",
            "Review"
        ],
        [
            str(result["marks"]),
            str(result["maximum"]),
            str(result["correct"]),
            str(result["wrong"]),
            str(result["blank"]),
            str(result["multiple"]),
            str(result["review_count"])
        ]
    ]

    table = Table(
        summary,
        repeatRows=1
    )

    table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#e7efff")
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                .4,
                colors.HexColor("#ccd6e5")
            ),
            (
                "FONTNAME",
                (0, 0),
                (-1, 0),
                "Helvetica-Bold"
            ),
            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                7
            ),
            (
                "PADDING",
                (0, 0),
                (-1, -1),
                5
            )
        ])
    )

    story.extend([
        table,
        Spacer(1, 12)
    ])

    data = [
        ["Q", "Detected", "Key", "Status"]
    ]

    for a in result["answers"]:

        data.append([
            str(a["question"]),
            str(a["detected"]),
            str(a["key"]),
            str(a["status"])
        ])

    answer_table = Table(
        data,
        repeatRows=1,
        colWidths=[35, 65, 55, 170]
    )

    answer_table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#e7efff")
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                .35,
                colors.HexColor("#d8e0eb")
            ),
            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                7
            ),
            (
                "PADDING",
                (0, 0),
                (-1, -1),
                4
            )
        ])
    )

    story.append(answer_table)

    doc.build(story)

    result["original_file"] = str(
        original_path.relative_to(DATA_DIR)
    )

    result["result_pdf"] = str(
        pdf_path.relative_to(DATA_DIR)
    )

    result["scanned_at"] = stamp


# =========================================================
# SCAN API
# =========================================================

@app.post("/api/scan")
async def scan(
    files: list[UploadFile] = File(...),
    answer_key: str = Form(...),
    marks: float = Form(1),
    negative: float = Form(0)
):

    key = "".join(
        ch for ch in answer_key.upper()
        if ch in OPTIONS
    )

    if not 25 <= len(key) <= 200:

        raise HTTPException(
            400,
            "Answer key must contain 25–200 A/B/C/D letters."
        )

    if marks < 0 or negative < 0:

        raise HTTPException(
            400,
            "Marks cannot be negative."
        )

    if not files:

        raise HTTPException(
            400,
            "Upload at least one image or PDF."
        )

    results = []
    total_bytes = 0

    batch_dir = Path(
        tempfile.mkdtemp(
            prefix="omr-batch-",
            dir=str(DATA_DIR)
        )
    )

    try:

        index = 0

        for file in files:

            data = await file.read()

            total_bytes += len(data)

            if total_bytes > MAX_UPLOAD_MB * 1024 * 1024:

                raise HTTPException(
                    413,
                    "Combined upload limit is 100 MB."
                )

            filename = file.filename or "upload.jpg"

            for page_index, img in enumerate(
                read_image(data, filename),
                1
            ):

                index += 1

                if index > MAX_PAGES:

                    raise HTTPException(
                        400,
                        "Maximum 1000 sheets per batch."
                    )

                temp_path = batch_dir / (
                    f"page-{index:04d}.jpg"
                )

                cv2.imwrite(
                    str(temp_path),
                    img
                )

                result = score_page(
                    img,
                    key,
                    marks,
                    negative
                )

                result.update({

                    "page": index,

                    "source_page": page_index,

                    "filename": filename,

                    "paper_title": "FJMC Academy Test",

                    "_temp_path": str(temp_path)
                })

                results.append(result)

        if not results:

            raise HTTPException(
                400,
                "No readable pages found."
            )

        ranked = dense_rank(results)

        for result in ranked:

            img = cv2.imread(
                result.pop("_temp_path")
            )

            save_page_artifacts(
                img,
                result
            )

            save_result(result)

        return {

            "results": ranked,

            "count": len(ranked),

            "storage": "persistent-directory-configurable",

            "easyocr": EASY_OCR_AVAILABLE
        }

    finally:

        shutil.rmtree(
            batch_dir,
            ignore_errors=True
        )


# =========================================================
# GET ALL RESULTS
# =========================================================

@app.get("/api/results")
def results_list():

    return {
        "results": dense_rank(
            load_saved_results()
        )
    }


# =========================================================
# CSV EXPORT
# =========================================================

@app.post("/api/export")
def export(payload: dict):

    output = BytesIO()

    writer = csv.writer(output)

    writer.writerow([
        "Rank",
        "Student Name",
        "Roll Number",
        "Marks",
        "Maximum",
        "Correct",
        "Wrong",
        "Blank",
        "Multiple",
        "Review",
        "Unprocessed",
        "Filename",
        "Original OMR",
        "Result PDF"
    ])

    for r in dense_rank(
        payload.get("results", [])
    ):

        writer.writerow([

            r.get("rank"),

            r.get("student_name") or "NAME REVIEW",

            r.get("roll_number") or "UNREADABLE",

            r.get("marks"),

            r.get("maximum"),

            r.get("correct"),

            r.get("wrong"),

            r.get("blank"),

            r.get("multiple"),

            r.get("review_count", 0),

            r.get("unprocessed", 0),

            r.get("filename"),

            r.get("original_file"),

            r.get("result_pdf")
        ])

    return Response(
        output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
            'attachment; filename="fjmc-omr-results.csv"'
        }
    )


# =========================================================
# ALL STUDENTS PDF REPORT
# =========================================================

@app.get("/api/results/pdf")
def export_results_pdf():

    results = dense_rank(
        load_saved_results()
    )

    buf = BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=18,
        leftMargin=18,
        topMargin=24,
        bottomMargin=24
    )

    styles = getSampleStyleSheet()

    story = [

        Paragraph(
            "FJMC ACADEMY — ALL STUDENTS RESULTS",
            styles["Title"]
        ),

        Spacer(1, 12)
    ]

    rows = [[
        "Rank",
        "Name",
        "Roll No.",
        "Marks",
        "Max",
        "Correct",
        "Wrong",
        "Blank",
        "Multi",
        "Review"
    ]]

    for r in results:

        rows.append([

            str(r.get("rank", "")),

            escape(str(r.get("student_name") or "REVIEW")),

            escape(str(r.get("roll_number") or "UNREADABLE")),

            str(r.get("marks", 0)),

            str(r.get("maximum", 0)),

            str(r.get("correct", 0)),

            str(r.get("wrong", 0)),

            str(r.get("blank", 0)),

            str(r.get("multiple", 0)),

            str(r.get("review_count", 0))
        ])

    table = Table(
        rows,
        repeatRows=1
    )

    table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#e7efff")
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                .4,
                colors.HexColor("#ccd6e5")
            ),
            (
                "FONTNAME",
                (0, 0),
                (-1, 0),
                "Helvetica-Bold"
            ),
            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                7
            ),
            (
                "PADDING",
                (0, 0),
                (-1, -1),
                4
            )
        ])
    )

    story.append(table)

    doc.build(story)

    return Response(
        buf.getvalue(),
        media_type="application/pdf",
        headers={
            "Content-Disposition":
            'attachment; filename="fjmc-all-students-results.pdf"'
        }
    )


# =========================================================
# STARTUP INFORMATION
# =========================================================

@app.on_event("startup")
def startup_event():

    print("=" * 50)
    print("FJMC ACADEMY SMART OMR")
    print("Frontend:", FRONTEND_DIR)
    print("Data:", DATA_DIR)
    print("EasyOCR package:", EASY_OCR_AVAILABLE)
    print("EasyOCR model: Lazy loading")
    print("=" * 50)
