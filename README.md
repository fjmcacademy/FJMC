# FJMC Academy OMR Scanner — starter website

## What is included
- Separate static website (does not modify the existing FJMC Academy site).
- Create papers with 25–200 questions and positive/negative marking.
- Manually create and export answer keys.
- Print an A4 OMR answer-sheet template.
- Upload an OMR photo from a phone or desktop and review answers manually.
- Import bulk scanner-exported CSV rows (`studentId,studentName,answers`).
- Evaluate scores, show results, print an individual report, export CSV and backup JSON.
- Saves prototype data in the current browser's localStorage.

## Run it
1. Extract the ZIP.
2. Open `index.html` in a modern browser, or publish the folder to a separate GitHub Pages repository.
3. Create a paper, save its answer key, then print the sheet at 100% scale.
4. For a manual scan, choose the paper, enter the student ID, optionally upload a photo, and select answers in the review grid.
5. For bulk import, upload a CSV with headers such as:

```csv
studentId,studentName,answers
FJMC-001,Student One,ABCDABCD
FJMC-002,Student Two,"A,B,C,D,A,B,C,D"
```

`answers` should contain up to the paper's number of answers, using A/B/C/D; blank or missing values are treated as blank. Ensure the answer key has been saved before importing.

## Important limitations
This is a working browser-based starter/prototype, not a production-grade optical reader:
- Uploaded photos are previewed, but arbitrary phone images are **not automatically bubble-detected** in this starter. Answers are manually confirmed in the review grid.
- Printed template includes registration marks, but perspective correction, bubble detection and confidence scoring must be added and calibrated with real sample scans before relying on automatic marking.
- The PDF upload currently records the file's name and size in the paper metadata. It does not extract questions or infer the correct answers. PDF parsing/OCR and answer-key verification are a separate implementation step.
- Bulk machine import works with CSV exports in the documented format. Direct machine control and proprietary formats depend on the exact make/model and vendor software.
- Browser localStorage is local to one browser/device and is not shared or appropriate for multi-admin production data.

## Production deployment checklist
1. Create a Firebase project and enable Firebase Authentication, Firestore and Storage.
2. Add sign-in and role-based admin authorization.
3. Move paper metadata, answer keys, results and upload metadata to Firestore; store PDFs/images in Storage.
4. Add strict Firestore/Storage security rules. Do not put service-account credentials in frontend code.
5. Add PDF text extraction/OCR with a manual confirmation workflow.
6. Implement OMR image normalization (corner detection, perspective correction, thresholding, bubble ROI calibration, confidence score) and test on multiple real printed/scanned sheets.
7. Confirm machine output format and validate large-batch import with the actual machine.
8. Test scoring edge cases: unanswered key, multiple marks, incomplete keys, negative totals and duplicate sheet IDs.

## Deploy to separate GitHub Pages
Create a new repository (for example `fjmc-omr-scanner`), upload the extracted files to its root, then enable Pages from the repository settings. Keep this repository separate from `fjmcacademy.github.io` if you want zero changes to the existing site.
