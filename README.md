# FJMC Academy OMR Pro

Standalone HTML/CSS/JavaScript prototype. It does not modify your existing FJMC Academy website.

## Features
- Exam name, exam date, paper ID, subject/course, batch/class.
- 25–200 questions.
- Per-question MCQ (one correct answer) or MSQ (multiple correct answers).
- Separate answer key and student response data.
- Print OMR sheet with student name, roll number, exam date, paper ID and registration marks.
- Upload a photo/scan; a basic template-coordinate bubble reader proposes answers and flags uncertain responses for review.
- Evaluate with positive/negative marks; MCQ/MSQ exact-set matching.
- Results, printable reports, CSV import/export, JSON backup.
- Machine-export CSV import format documented below.

## Run
Extract ZIP and open `index.html` in a modern browser. For best results use a static web server or separate GitHub Pages repo.

## CSV for OMR machine import
Header example:
`examPaperId,studentName,rollNumber,answers`
- MCQ answers: a sequence such as `ACBDAC`.
- MSQ answers: comma-separated question entries, with multiple choices separated by `|`, e.g. `"A|C,B|D,A,,C|D"`.
The CSV should include `examPaperId` matching the exam in the app. Key must be set first.

## Honest limitations
- Automatic bubble detection uses approximate normalized coordinates of this app's own printable sheet. It is an initial reader, not a validated industrial OMR engine. Flat, aligned scans are most likely to work; angled phone photos, cropping, scaling, pen types and print differences can cause errors. Always review detections.
- Registration-mark based perspective correction and calibrated OpenCV detection are not included.
- PDF is accepted as a reference file name only; automatic extraction of questions/solutions from PDF is not included. Enter/verify the answer key manually.
- CSV machine import works with the documented format. Direct USB/serial machine control and proprietary formats depend on model.
- Data is stored in browser localStorage only, not shared across devices. For production, add authentication and a secure backend (e.g. Firebase) with rules.

## Recommended production steps
1. Test with 10–20 sheets printed at 100% and scanned flat at multiple resolutions.
2. Compare all detected responses against the marked sheets; tune/calibrate coordinates and thresholds.
3. Add corner-marker detection and perspective correction, then confidence-based review.
4. Add login, cloud database/storage, audit logs, and duplicate-sheet prevention.
5. Confirm actual scanner make/model and sample exports.
