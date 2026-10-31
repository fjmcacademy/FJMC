# FJMC Academy Smart OMR

FastAPI + OpenCV backend with a lightweight browser frontend.

## Processing design

- Browser uploads the original camera photo, gallery image, or PDF. It does not run OpenCV.js and does not pre-warp the page.
- `backend/image_pipeline.py` performs photo normalization on the server.
- `backend/main.py` then aligns the four FJMC corner markers, reads the 8-digit roll number and answer bubbles, optionally reads the handwritten name through a TrOCR HTTP endpoint, and falls back to local Tesseract.
- PDF pages and image uploads pass through the same backend preparation and OMR scoring path.

## Run locally

```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000

## Render deployment

Use the included root `Dockerfile` and set the service runtime to Docker. The app listens on Render's `$PORT`.

Optional environment variables:

- `OMR_DATA_DIR`: directory for saved scans/results. Attach a persistent disk and point this variable to its mount path if records must survive redeploys.
- `TROCR_API_URL`: base URL of a compatible OCR service exposing `POST /ocr` and accepting multipart field `file`.
- `TROCR_API_TOKEN`: optional bearer token for that OCR service.

Without TrOCR configured, handwritten names are attempted with Tesseract. Name OCR is not guaranteed; review unreadable names manually.

## Important print/scan instructions

- Print the generated OMR PDF at 100% / Actual Size. Do not use Fit to Page.
- Keep all four black corner markers visible in the photo/scan.
- Use even lighting, avoid shadows, and capture the entire sheet.
- Review any result flagged for uncertain page alignment, roll number, name, or answer bubbles.

OMR recognition depends on print scale, photo quality, pen marks, and sheet condition. Always manually verify flagged results; no automatic scanner can guarantee 100% accuracy for every photo.
