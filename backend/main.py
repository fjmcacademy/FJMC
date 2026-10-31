import os
import io
import json
import csv
import uuid
from pathlib import Path
from datetime import datetime, timezone

import cv2
import fitz
import numpy as np

from fastapi import (
    FastAPI, UploadFile, File, Form, HTTPException
)
from fastapi.responses import (
    JSONResponse, StreamingResponse, FileResponse
)
from fastapi.staticfiles import StaticFiles

from backend.image_pipeline import prepare_mobile_photo
from backend.omr_engine import analyze_sheet, calculate_score
from backend.ocr_engine import recognize_name


ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
DATA_DIR = ROOT / "data"
RESULTS_FILE = DATA_DIR / "results.json"

DATA_DIR.mkdir(exist_ok=True)

app = FastAPI(
    title="FJMC Academy Smart OMR",
    version="2.0.0"
)

if FRONTEND.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(FRONTEND)),
        name="static"
    )


def load_results():
    if not RESULTS_FILE.exists():
        return []

    try:
        return json.loads(
            RESULTS_FILE.read_text(encoding="utf-8")
        )
    except Exception:
        return []


def save_results(results):
    temp = RESULTS_FILE.with_suffix(".tmp")

    temp.write_text(
        json.dumps(
            results,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    temp.replace(RESULTS_FILE)


def decode_uploaded_image(data):
    arr = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    if image is None:
        raise ValueError("Invalid image.")

    return image


def pdf_to_images(data):
    document = fitz.open(
        stream=data,
        filetype="pdf"
    )

    if len(document) > 100:
        raise ValueError(
            "Maximum 100 PDF pages per upload."
        )

    pages = []

    for page in document:
        pix = page.get_pixmap(
            matrix=fitz.Matrix(2, 2),
            alpha=False
        )

        image_data = pix.tobytes("png")
        pages.append(decode_uploaded_image(image_data))

    document.close()
    return pages


def make_dense_ranks(results):
    valid = [
        r for r in results
        if isinstance(r.get("score"), (int, float))
    ]

    scores = sorted(
        {r["score"] for r in valid},
        reverse=True
    )

    rank_map = {
        score: index + 1
        for index, score in enumerate(scores)
    }

    for item in results:
        if item in valid:
            item["rank"] = rank_map[item["score"]]


@app.get("/")
def home():
    index_file = FRONTEND / "index.html"

    if not index_file.exists():
        return JSONResponse({
            "message": "FJMC Smart OMR API is running."
        })

    return FileResponse(index_file)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "FJMC Academy Smart OMR",
        "version": "2.0.0"
    }


@app.get("/api/results")
def get_results():
    results = load_results()

    results.sort(
        key=lambda r: (
            r.get("rank") is None,
            r.get("rank") or 999999
        )
    )

    return {
        "count": len(results),
        "results": results
    }


@app.delete("/api/results")
def clear_results():
    save_results([])
    return {"success": True, "message": "Results cleared."}


@app.post("/api/scan")
async def scan_omr(
    files: list[UploadFile] = File(...),
    answer_key: str = Form("{}"),
    marks: float = Form(2.0),
    negative: float = Form(0.5)
):
    if not files:
        raise HTTPException(
            status_code=400,
            detail="Upload at least one image or PDF."
        )

    try:
        key = json.loads(answer_key)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Answer key must be valid JSON."
        )

    if not isinstance(key, dict):
        raise HTTPException(
            status_code=400,
            detail="Answer key must be a JSON object."
        )

    normalized_key = {}

    for question, answer in key.items():
        try:
            q = int(question)
        except Exception:
            continue

        a = str(answer).strip().upper()

        if 1 <= q <= 100 and a in ("A", "B", "C", "D"):
            normalized_key[str(q)] = a

    if not normalized_key:
        raise HTTPException(
            status_code=400,
            detail="Enter a valid answer key for questions 1-100."
        )

    if marks < 0 or negative < 0:
        raise HTTPException(
            status_code=400,
            detail="Marks and negative marks cannot be negative."
        )

    existing = load_results()
    processed = []
    page_count = 0

    for uploaded in files:
        raw = await uploaded.read()

        if len(raw) > 25 * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail=f"{uploaded.filename} exceeds 25 MB."
            )

        filename = uploaded.filename or "upload"

        try:
            if filename.lower().endswith(".pdf"):
                pages = pdf_to_images(raw)
            else:
                pages = [decode_uploaded_image(raw)]

        except Exception as exc:
            processed.append({
                "filename": filename,
                "error": str(exc)
            })
            continue

        for page_index, original in enumerate(pages, start=1):
            page_count += 1

            if page_count > 100:
                raise HTTPException(
                    status_code=413,
                    detail="Maximum 100 pages per scan request."
                )

            try:
                # Normalize image through the same pipeline.
                ok, encoded = cv2.imencode(
                    ".jpg", original
                )

                prepared = prepare_mobile_photo(
                    encoded.tobytes()
                )

                image = prepared.image

                omr = analyze_sheet(image)
                name_data = recognize_name(image)

                scoring = calculate_score(
                    omr["answers"],
                    normalized_key,
                    marks_per_question=marks,
                    negative_per_question=negative
                )

                needs_review = (
                    omr["review_required"] or
                    name_data["review_required"] or
                    not prepared.page_detected
                )

                record = {
                    "id": str(uuid.uuid4()),
                    "filename": filename,
                    "page": page_index,
                    "name": name_data["name"],
                    "name_ocr": name_data,
                    "roll_number": omr["roll"]["roll_number"],
                    "roll_review_required": omr["roll"]["review_required"],
                    "answers": omr["answers"],
                    "review_questions": omr["review_questions"],
                    "scoring": scoring,
                    "score": scoring["score"],
                    "correct": scoring["correct"],
                    "wrong": scoring["wrong"],
                    "blank": scoring["blank"],
                    "unclear": scoring["unclear"],
                    "page_detected": prepared.page_detected,
                    "alignment_method": prepared.method,
                    "warnings": prepared.warnings,
                    "review_required": needs_review,
                    "created_at": datetime.now(
                        timezone.utc
                    ).isoformat()
                }

                processed.append(record)
                existing.append(record)

            except Exception as exc:
                processed.append({
                    "filename": filename,
                    "page": page_index,
                    "error": str(exc)
                })

    make_dense_ranks(existing)
    save_results(existing)

    # Return the records generated in this request,
    # including their updated ranks.
    rank_lookup = {
        item["id"]: item.get("rank")
        for item in existing
        if item.get("id")
    }

    for item in processed:
        if item.get("id"):
            item["rank"] = rank_lookup.get(item["id"])

    return {
        "success": True,
        "processed_pages": page_count,
        "results": processed
    }


@app.get("/api/export")
def export_csv():
    results = load_results()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Rank", "Name", "Roll Number",
        "Score", "Correct", "Wrong",
        "Blank", "Unclear", "Review Required",
        "Filename"
    ])

    for item in sorted(
        results,
        key=lambda r: r.get("rank") or 999999
    ):
        writer.writerow([
            item.get("rank", ""),
            item.get("name", ""),
            item.get("roll_number", ""),
            item.get("score", ""),
            item.get("correct", ""),
            item.get("wrong", ""),
            item.get("blank", ""),
            item.get("unclear", ""),
            item.get("review_required", ""),
            item.get("filename", "")
        ])

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition":
            "attachment; filename=FJMC_OMR_Results.csv"
        }
    )


@app.get("/api/template")
def template_info():
    return {
        "paper": "FJMC Academy CSIR NET Mathematics Mock Test",
        "questions": 100,
        "options": ["A", "B", "C", "D"],
        "roll_digits": 8,
        "page_width": 1240,
        "page_height": 1754
              }
