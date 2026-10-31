
const $ = id => document.getElementById(id);

let selectedFiles = [];
let cameraStream = null;
let cameraBlob = null;
let latestResults = [];

let cvReady = false;
let cvPromise = null;
let selectedPreviewURL = null;

/* --------------------------------
   OPENCV INITIALIZATION
-------------------------------- */

function waitForOpenCV(timeout = 30000) {
  if (cvReady && window.cv && cv.Mat) {
    return Promise.resolve(true);
  }

  if (cvPromise) return cvPromise;

  cvPromise = new Promise((resolve, reject) => {
    const started = Date.now();

    const timer = setInterval(() => {
      if (
        window.__opencvReady &&
        window.cv &&
        typeof cv.Mat === "function"
      ) {
        cvReady = true;
        clearInterval(timer);
        $("scannerStatus").textContent =
          "Browser scanner ready · OpenCV loaded";
        resolve(true);
        return;
      }

      if (Date.now() - started > timeout) {
        clearInterval(timer);
        cvPromise = null;

        $("scannerStatus").textContent =
          "Scanner library could not load. Check internet connection.";

        reject(new Error(
          "OpenCV could not load. Refresh the website and try again."
        ));
      }
    }, 300);
  });

  return cvPromise;
}

window.addEventListener("load", () => {
  waitForOpenCV().catch(error => {
    console.error(error);
  });
});

/* --------------------------------
   ANSWER KEY
-------------------------------- */

function cleanKey(s) {
  return (s || "").toUpperCase().replace(/[^ABCD]/g, "");
}

function updateCount() {
  const key = cleanKey($("key").value);

  $("keyCount").textContent =
    `${key.length} answers entered · expected ${$("questions").value}`;
}

$("key").addEventListener("input", updateCount);
$("questions").addEventListener("change", updateCount);

$("fillDemo").onclick = () => {
  const n = Number($("questions").value);

  $("key").value =
    "ABCD".repeat(Math.ceil(n / 4)).slice(0, n);

  updateCount();
};

/* --------------------------------
   CREATE PAPER
-------------------------------- */

$("makePaper").onclick = async () => {
  const n = Number($("questions").value);
  const key = cleanKey($("key").value);

  if (key.length !== n) {
    msg(
      "paperMsg",
      `Enter exactly ${n} answers. Current: ${key.length}.`,
      true
    );
    return;
  }

  try {
    const response = await fetch("/api/template", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        title: $("title").value,
        questions: n
      })
    });

    if (!response.ok) {
      const data = await response.json();
      throw new Error(
        data.detail || "Template generation failed."
      );
    }

    downloadBlob(
      await response.blob(),
      "fjmc-omr-template-8-digit-roll.pdf"
    );

    msg(
      "paperMsg",
      "Template downloaded. Print at 100% scale. Fill bubbles clearly.",
      false
    );

  } catch (error) {
    msg("paperMsg", error.message, true);
  }
};

/* --------------------------------
   IMAGE PREVIEW
-------------------------------- */

function showPreview(file, info = "") {
  const area = $("scanPreview");
  const image = $("previewImage");

  if (selectedPreviewURL) {
    URL.revokeObjectURL(selectedPreviewURL);
  }

  selectedPreviewURL = URL.createObjectURL(file);

  image.src = selectedPreviewURL;
  $("previewInfo").textContent = info;

  area.hidden = false;
}

function clearPreview() {
  if (selectedPreviewURL) {
    URL.revokeObjectURL(selectedPreviewURL);
    selectedPreviewURL = null;
  }

  $("previewImage").removeAttribute("src");
  $("scanPreview").hidden = true;
}

/* --------------------------------
   FILE UPLOAD
-------------------------------- */

$("file").addEventListener("change", event => {
  selectedFiles = Array.from(event.target.files || []);
  cameraBlob = null;

  const firstImage = selectedFiles.find(file =>
    file.type.startsWith("image/")
  );

  if (firstImage) {
    showPreview(firstImage, "Original uploaded image");
  } else {
    clearPreview();
  }

  $("fileName").textContent = selectedFiles.length
    ? `${selectedFiles.length} file(s) selected`
    : "No sheet selected";

  const size = selectedFiles.reduce(
    (sum, file) => sum + file.size,
    0
  );

  $("fileHint").textContent = selectedFiles.length
    ? `${(size / 1048576).toFixed(2)} MB total · each PDF page is one sheet`
    : "Upload images or a multi-page PDF to begin";

  msg("scanMsg", "", false);
});

/* --------------------------------
   CAMERA
-------------------------------- */

$("cameraBtn").onclick = async () => {
  try {
    if (!navigator.mediaDevices ||
        !navigator.mediaDevices.getUserMedia) {
      throw new Error("Camera requires HTTPS or localhost.");
    }

    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 1920 },
        height: { ideal: 1080 }
      },
      audio: false
    });

    $("video").srcObject = cameraStream;
    $("video").hidden = false;
    $("cameraActions").hidden = false;

    await $("video").play();

    msg(
      "scanMsg",
      "Camera ready. Keep the complete OMR sheet flat and inside the frame.",
      false
    );

  } catch (error) {
    console.error(error);

    msg(
      "scanMsg",
      error.message ||
      "Camera unavailable. Allow permission or upload a photo instead.",
      true
    );
  }
};

$("capture").onclick = () => {
  const video = $("video");
  const canvas = $("canvas");

  if (!video.videoWidth) {
    msg("scanMsg", "Camera is not ready.", true);
    return;
  }

  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;

  const context = canvas.getContext("2d");

  context.drawImage(
    video,
    0,
    0,
    canvas.width,
    canvas.height
  );

  canvas.toBlob(blob => {
    if (!blob) {
      msg("scanMsg", "Could not capture photo. Try again.", true);
      return;
    }

    cameraBlob = blob;
    selectedFiles = [];

    $("fileName").textContent = "Camera capture.jpg";
    $("fileHint").textContent =
      "Photo captured · ready for page detection";

    showPreview(blob, "Camera capture · original photo");

    stopCamera();

    msg(
      "scanMsg",
      "Photo captured. Scanner will straighten the page before analysis.",
      false
    );

  }, "image/jpeg", 0.95);
};

function stopCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach(track => track.stop());
  }

  cameraStream = null;

  $("video").srcObject = null;
  $("video").hidden = true;
  $("cameraActions").hidden = true;
}

$("stopCamera").onclick = stopCamera;

/* --------------------------------
   OPENCV POINT ORDERING
-------------------------------- */

function orderCorners(points) {
  const sums = points.map(p => p.x + p.y);
  const diffs = points.map(p => p.y - p.x);

  const tl = points[sums.indexOf(Math.min(...sums))];
  const br = points[sums.indexOf(Math.max(...sums))];
  const tr = points[diffs.indexOf(Math.min(...diffs))];
  const bl = points[diffs.indexOf(Math.max(...diffs))];

  const unique = new Set([tl, tr, br, bl]);

  if (unique.size !== 4) {
    return null;
  }

  return [tl, tr, br, bl];
}

/* --------------------------------
   DOCUMENT PAGE DETECTION
-------------------------------- */

async function enhanceOMRPhoto(blob) {
  await waitForOpenCV();

  const image = new Image();
  const objectURL = URL.createObjectURL(blob);

  let src = null;
  let gray = null;
  let blurred = null;
  let edges = null;
  let contours = null;
  let hierarchy = null;
  let best = null;
  let bestApprox = null;

  try {
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = () => reject(
        new Error("Could not read uploaded image.")
      );
      image.src = objectURL;
    });

    const canvas = document.createElement("canvas");

    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;

    const context = canvas.getContext("2d", {
      willReadFrequently: true
    });

    context.drawImage(image, 0, 0);

    src = cv.imread(canvas);

    if (src.cols < 300 || src.rows < 300) {
      throw new Error("Image resolution is too small.");
    }

    gray = new cv.Mat();
    blurred = new cv.Mat();
    edges = new cv.Mat();
    contours = new cv.MatVector();
    hierarchy = new cv.Mat();

    cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY);

    cv.GaussianBlur(
      gray,
      blurred,
      new cv.Size(5, 5),
      0
    );

    cv.Canny(blurred, edges, 50, 150);

    const kernel = cv.getStructuringElement(
      cv.MORPH_RECT,
      new cv.Size(5, 5)
    );

    cv.dilate(
      edges,
      edges,
      kernel,
      new cv.Point(-1, -1),
      2
    );

    kernel.delete();

    cv.findContours(
      edges,
      contours,
      hierarchy,
      cv.RETR_EXTERNAL,
      cv.CHAIN_APPROX_SIMPLE
    );

    const imageArea = src.cols * src.rows;

    let bestArea = 0;

    for (let i = 0; i < contours.size(); i++) {
      const contour = contours.get(i);

      const perimeter = cv.arcLength(contour, true);
      const approx = new cv.Mat();

      cv.approxPolyDP(
        contour,
        approx,
        0.02 * perimeter,
        true
      );

      const area = Math.abs(cv.contourArea(approx));

      if (
        approx.rows === 4 &&
        area > imageArea * 0.18 &&
        area < imageArea * 0.98 &&
        area > bestArea
      ) {
        if (bestApprox) bestApprox.delete();

        bestApprox = approx.clone();
        bestArea = area;
      }

      approx.delete();
      contour.delete();
    }

    let resultCanvas;

    if (bestApprox) {
      const values = bestApprox.data32S;
      const points = [];

      for (let i = 0; i < 4; i++) {
        points.push({
          x: values[i * 2],
          y: values[i * 2 + 1]
        });
      }

      const ordered = orderCorners(points);

      if (!ordered) {
        throw new Error(
          "Page corners could not be ordered. Try another photo."
        );
      }

      const [tl, tr, br, bl] = ordered;

      const widthA = Math.hypot(
        br.x - bl.x,
        br.y - bl.y
      );

      const widthB = Math.hypot(
        tr.x - tl.x,
        tr.y - tl.y
      );

      const heightA = Math.hypot(
        tr.x - br.x,
        tr.y - br.y
      );

      const heightB = Math.hypot(
        tl.x - bl.x,
        tl.y - bl.y
      );

      const detectedWidth = Math.max(widthA, widthB);
      const detectedHeight = Math.max(heightA, heightB);

      const ratio = detectedWidth / detectedHeight;

      if (
        !Number.isFinite(ratio) ||
        detectedWidth < 200 ||
        detectedHeight < 200 ||
        ratio < 0.45 ||
        ratio > 1.15
      ) {
        throw new Error(
          "Detected page shape is not suitable. Retake the photo in portrait orientation."
        );
      }

      const outputWidth = 1240;
      const outputHeight = 1754;

      const sourcePoints = cv.matFromArray(
        4,
        1,
        cv.CV_32FC2,
        [
          tl.x, tl.y,
          tr.x, tr.y,
          br.x, br.y,
          bl.x, bl.y
        ]
      );

      const destinationPoints = cv.matFromArray(
        4,
        1,
        cv.CV_32FC2,
        [
          0, 0,
          outputWidth - 1, 0,
          outputWidth - 1, outputHeight - 1,
          0, outputHeight - 1
        ]
      );

      const transform = cv.getPerspectiveTransform(
        sourcePoints,
        destinationPoints
      );

      const warped = new cv.Mat();

      cv.warpPerspective(
        src,
        warped,
        transform,
        new cv.Size(outputWidth, outputHeight),
        cv.INTER_CUBIC,
        cv.BORDER_REPLICATE
      );

      resultCanvas = document.createElement("canvas");

      resultCanvas.width = outputWidth;
      resultCanvas.height = outputHeight;

      cv.imshow(resultCanvas, warped);

      sourcePoints.delete();
      destinationPoints.delete();
      transform.delete();
      warped.delete();

    } else {
      /*
       * No reliable page boundary found.
       * Do not pretend that perspective correction succeeded.
       * Original photo is passed to the backend.
       */

      resultCanvas = canvas;
    }

    const correctedBlob = await new Promise(resolve => {
      resultCanvas.toBlob(
        resolve,
        "image/jpeg",
        0.95
      );
    });

    if (!correctedBlob) {
      throw new Error("Could not create corrected image.");
    }

    return {
      blob: correctedBlob,
      pageDetected: Boolean(bestApprox),
      originalWidth: image.naturalWidth,
      originalHeight: image.naturalHeight
    };

  } finally {
    URL.revokeObjectURL(objectURL);

    if (src) src.delete();
    if (gray) gray.delete();
    if (blurred) blurred.delete();
    if (edges) edges.delete();
    if (contours) contours.delete();
    if (hierarchy) hierarchy.delete();
    if (best) best.delete();
    if (bestApprox) bestApprox.delete();
  }
}

/* --------------------------------
   SCAN AND EVALUATE
-------------------------------- */

$("runScan").onclick = async () => {
  const key = cleanKey($("key").value);
  const n = Number($("questions").value);

  if (key.length !== n) {
    msg(
      "scanMsg",
      `Enter exactly ${n} answer-key letters.`,
      true
    );
    return;
  }

  const files = cameraBlob
    ? [
        new File(
          [cameraBlob],
          "camera-capture.jpg",
          { type: "image/jpeg" }
        )
      ]
    : selectedFiles;

  if (!files.length) {
    msg(
      "scanMsg",
      "Select a photo/PDF or capture a camera image first.",
      true
    );
    return;
  }

  const totalSize = files.reduce(
    (sum, file) => sum + file.size,
    0
  );

  if (totalSize > 100 * 1024 * 1024) {
    msg(
      "scanMsg",
      "Batch size exceeds 100 MB.",
      true
    );
    return;
  }

  const form = new FormData();

  $("runScan").disabled = true;
  $("runScan").textContent = "Preparing scanner...";

  try {
    const imageFiles = files.filter(file =>
      file.type.startsWith("image/")
    );

    if (imageFiles.length) {
      await waitForOpenCV();
    }

    for (let i = 0; i < files.length; i++) {
      const file = files[i];

      if (file.type.startsWith("image/")) {
        $("runScan").textContent =
          `Correcting image ${i + 1}/${files.length}...`;

        const corrected = await enhanceOMRPhoto(file);

        form.append(
          "files",
          corrected.blob,
          file.name.replace(/\.[^.]+$/, "") + "-scanned.jpg"
        );

        if (!corrected.pageDetected) {
          console.warn(
            "Page boundary not detected:",
            file.name
          );
        }

      } else if (
        file.type === "application/pdf" ||
        file.name.toLowerCase().endsWith(".pdf")
      ) {
        form.append("files", file, file.name);

      } else {
        throw new Error(
          `Unsupported file format: ${file.name}`
        );
      }
    }

    form.append("answer_key", key);
    form.append("marks", $("marks").value || "1");
    form.append("negative", $("negative").value || "0");

    $("runScan").textContent = "Analyzing batch...";

    msg(
      "scanMsg",
      "Corrected images are being sent to the OMR backend for evaluation...",
      false
    );

    const response = await fetch("/api/scan", {
      method: "POST",
      body: form
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.detail || "Scan failed."
      );
    }

    latestResults = data.results || [];

    renderResults(latestResults);

    msg(
      "scanMsg",
      `Processed ${latestResults.length} sheet(s). Check all flagged results.`,
      false
    );

    $("results").scrollIntoView({
      behavior: "smooth"
    });

  } catch (error) {
    console.error(error);

    msg(
      "scanMsg",
      error.message || "Scan failed.",
      true
    );

  } finally {
    $("runScan").disabled = false;
    $("runScan").textContent =
      "Analyze & calculate marks";
  }
};

/* --------------------------------
   RESULT HELPERS
-------------------------------- */

function num(result, key) {
  return Number(result[key] || 0);
}

function processedCount(result) {
  return num(result, "correct") +
    num(result, "wrong") +
    num(result, "blank") +
    num(result, "multiple") +
    num(result, "review_count");
}

function unprocessedCount(result) {
  const total = num(result, "questions");

  return Math.max(
    num(result, "unprocessed"),
    total ? total - processedCount(result) : 0
  );
}

function needsReview(result) {
  return Boolean(
    result.review_required ||
    !result.roll_number ||
    !result.student_name ||
    num(result, "multiple") > 0 ||
    num(result, "review_count") > 0 ||
    unprocessedCount(result) > 0
  );
}

/* --------------------------------
   RENDER RESULTS
-------------------------------- */

function renderResults(results) {
  const area = $("resultArea");

  if (!results.length) {
    area.className = "empty";

    area.innerHTML =
      '<div class="emptyicon">▥</div><b>No results found</b>';

    return;
  }

  const ranked = [...results].sort((a, b) =>
    (Number(a.rank) || 999999) -
    (Number(b.rank) || 999999)
  );

  const rows = ranked.map((r, i) => `
    <tr>
      <td>${esc(r.rank ?? i + 1)}</td>
      <td>${esc(r.student_name || "NAME REVIEW")}</td>
      <td>${esc(r.roll_number || "UNREADABLE — REVIEW")}</td>
      <td><b>${esc(r.marks ?? 0)}</b> / ${esc(r.maximum ?? 0)}</td>
      <td>${num(r, "correct")}</td>
      <td>${num(r, "wrong")}</td>
      <td>${num(r, "blank")}</td>
      <td>${num(r, "multiple")}</td>
      <td>${num(r, "review_count")}</td>
      <td>${unprocessedCount(r)}</td>
      <td>
        <button class="btn secondary small" data-review="${i}">
          ${needsReview(r) ? "Review" : "OK"}
        </button>
      </td>
    </tr>
  `).join("");

  const details = ranked.map((r, i) => {
    const answerRows = (r.answers || []).map(a => `
      <tr>
        <td>${esc(a.question)}</td>
        <td><b>${esc(a.detected)}</b></td>
        <td>${esc(a.key)}</td>
        <td>${esc(a.status)}</td>
        <td>${(a.bubble_darkness || [])
          .map(value => esc(value))
          .join(" / ")}</td>
      </tr>
    `).join("");

    return `
      <details id="omr-review-${i}"
        style="margin-top:12px;border:1px solid #e2e9f3;
        border-radius:10px;padding:12px">

        <summary style="cursor:pointer;font-size:13px;font-weight:700">
          ${esc(r.student_name || "NAME REVIEW")} ·
          ${esc(r.roll_number || "UNREADABLE")} ·
          Rank ${esc(r.rank ?? "—")} ·
          ${esc(r.marks ?? 0)} marks
        </summary>

        <p>
          Total: ${num(r, "questions")} ·
          Processed: ${processedCount(r)} ·
          Unprocessed: ${unprocessedCount(r)}
        </p>

        <p>
          Correct: ${num(r, "correct")} ·
          Wrong: ${num(r, "wrong")} ·
          Blank: ${num(r, "blank")} ·
          Multiple: ${num(r, "multiple")} ·
          Review: ${num(r, "review_count")}
        </p>

        <p>Roll digits: ${esc((r.roll_digits || []).join(" "))}</p>

        <p>Roll confidence:
          ${esc((r.roll_confidence || []).join(" / "))}
        </p>

        <div style="overflow:auto;max-height:350px">
          <table class="resulttable">
            <thead>
              <tr>
                <th>Q</th>
                <th>Detected</th>
                <th>Key</th>
                <th>Status</th>
                <th>Bubble scores A/B/C/D</th>
              </tr>
            </thead>
            <tbody>${answerRows}</tbody>
          </table>
        </div>

        <p>
          Original scan: ${esc(r.original_file || "Not saved")}<br>
          Result PDF: ${esc(r.result_pdf || "Not saved")}
        </p>
      </details>
    `;
  }).join("");

  const reviewTotal = ranked.filter(needsReview).length;

  const blankTotal = ranked.reduce(
    (s, r) => s + num(r, "blank"),
    0
  );

  const correctTotal = ranked.reduce(
    (s, r) => s + num(r, "correct"),
    0
  );

  area.className = "";

  area.innerHTML = `
    <div class="resulttop">

      <div class="resultmetric">
        <small>Sheets processed</small>
        <strong>${ranked.length}</strong>
      </div>

      <div class="resultmetric">
        <small>Need review</small>
        <strong>${reviewTotal}</strong>
      </div>

      <div class="resultmetric">
        <small>Total correct</small>
        <strong>${correctTotal}</strong>
      </div>

      <div class="resultmetric">
        <small>Total blank</small>
        <strong>${blankTotal}</strong>
      </div>

    </div>

    <h3>Rank list</h3>

    <div style="overflow:auto;max-height:450px">
      <table class="resulttable">
        <thead>
          <tr>
            <th>Rank</th>
            <th>Student name</th>
            <th>Roll number</th>
            <th>Marks</th>
            <th>Correct</th>
            <th>Wrong</th>
            <th>Blank</th>
            <th>Multiple</th>
            <th>Review count</th>
            <th>Unprocessed</th>
            <th>Review</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>

    <h3 style="margin-top:24px">Question-wise review</h3>

    ${details}

    <div class="result-actions">
      <button class="btn secondary" id="exportCsv">
        Export this batch CSV
      </button>
    </div>
  `;

  area.querySelectorAll("[data-review]").forEach(button => {
    button.addEventListener("click", () => {
      const detail = $("omr-review-" +
        Number(button.dataset.review));

      if (detail) {
        detail.open = true;

        detail.scrollIntoView({
          behavior: "smooth",
          block: "start"
        });
      }
    });
  });

  $("exportCsv").onclick = () =>
    exportCsv(
      latestResults,
      "fjmc-omr-batch-results.csv"
    );
}

/* --------------------------------
   CSV EXPORT
-------------------------------- */

async function exportCsv(results, filename) {
  const response = await fetch("/api/export", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ results })
  });

  if (!response.ok) {
    msg("scanMsg", "CSV export failed.", true);
    return;
  }

  downloadBlob(
    await response.blob(),
    filename
  );
}

/* --------------------------------
   LOAD SAVED RESULTS
-------------------------------- */

$("refreshResults").onclick = async () => {
  try {
    const response = await fetch("/api/results");
    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.detail || "Could not load results."
      );
    }

    latestResults = data.results || [];

    renderResults(latestResults);

    msg(
      "scanMsg",
      `Loaded ${latestResults.length} saved records.`,
      false
    );

  } catch (error) {
    msg("scanMsg", error.message, true);
  }
};

$("exportAllCsv").onclick = async () => {
  try {
    const response = await fetch("/api/results");
    const data = await response.json();

    if (!response.ok) {
      throw new Error("Could not load saved results.");
    }

    await exportCsv(
      data.results || [],
      "fjmc-all-students-results.csv"
    );

  } catch (error) {
    msg("scanMsg", error.message, true);
  }
};

/* --------------------------------
   UTILITIES
-------------------------------- */

function msg(id, text, error) {
  $(id).textContent = text;

  $(id).className =
    "message" + (error ? " error" : "");
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);

  const link = document.createElement("a");

  link.href = url;
  link.download = filename;

  document.body.appendChild(link);

  link.click();
  link.remove();

  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[char]));
}

updateCount();
