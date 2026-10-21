from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from io import BytesIO
import json, csv
import cv2
import numpy as np
import fitz
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="FJMC OMR Scanner")
app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")

@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

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
    c.drawString(118*mm, h-34*mm, "Roll No.: __________________")
    c.drawString(18*mm, h-41*mm, f"Questions: {n}    Fill ONE bubble per question.")
    # markers (for future perspective correction)
    s=7*mm
    for x,y in [(8*mm, h-8*mm-s),(w-8*mm-s,h-8*mm-s),(8*mm,8*mm),(w-8*mm-s,8*mm)]:
        c.setFillColorRGB(0,0,0); c.rect(x,y,s,s,fill=1,stroke=0)
    # Three columns; up to 200 questions, 70 per column maximum.
    cols = 3
    rows_per_col = (n + cols - 1)//cols
    top = h - 53*mm
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
        if len(doc) > 30:
            raise HTTPException(400, "Please upload a PDF with 30 pages or fewer per batch.")
        out=[]
        for page in doc:
            pix=page.get_pixmap(matrix=fitz.Matrix(2,2), alpha=False)
            arr=np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
            out.append(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
        return out
    arr=np.frombuffer(data,dtype=np.uint8)
    img=cv2.imdecode(arr,cv2.IMREAD_COLOR)
    if img is None: raise HTTPException(400,"Could not read image. Use JPG, PNG or scanned PDF.")
    return [img]


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
    row_step_mm = min(7.0, 226.0 / rows)
    first_y = 54.6 / 297.0

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
        "correct": correct,
        "wrong": wrong,
        "blank": blank,
        "multiple": multi,
        "marks": round(total, 2),
        "maximum": round(n * marks, 2),
        "answers": answers,
        "review_required": bool(multi or blank)
    }


@app.post("/api/scan")
async def scan(file: UploadFile=File(...), answer_key: str=Form(...),
               marks: float=Form(1), negative: float=Form(0)):
    key="".join(ch for ch in answer_key.upper() if ch in "ABCD")
    if not 25 <= len(key) <= 200:
        raise HTTPException(400,"Answer key must contain 25–200 letters A/B/C/D.")
    if marks < 0 or negative < 0:
        raise HTTPException(400,"Marks cannot be negative.")
    data=await file.read()
    if len(data)>25*1024*1024: raise HTTPException(413,"File too large (maximum 25 MB).")
    pages=read_image(data,file.filename or "upload.jpg")
    results=[]
    for i,img in enumerate(pages):
        result=score_page(img,key,marks,negative)
        result["page"]=i+1
        result["filename"]=file.filename
        results.append(result)
    return {"results":results}

@app.post("/api/export")
def export(payload: dict):
    output=BytesIO()
    writer=csv.writer(output)
    writer.writerow(["Page","Filename","Question","Detected","Answer key","Status"])
    for result in payload.get("results",[]):
        for a in result.get("answers",[]):
            writer.writerow([result.get("page"),result.get("filename"),a["question"],a["detected"],a["key"],a["status"]])
    return Response(output.getvalue(),media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":'attachment; filename="fjmc-omr-results.csv"'})
