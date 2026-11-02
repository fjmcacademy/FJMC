const $ = id => document.getElementById(id);

let selectedFiles = [];
let cameraStream = null;
let cameraBlob = null;
let latestResults = [];

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

$("makePaper").onclick = async () => {
  const n = Number($("questions").value);
  const key = cleanKey($("key").value);

  if (key.length !== n) {
    msg("paperMsg", `Enter exactly ${n} answers. Current: ${key.length}.`, true);
    return;
  }

  try {
    const response = await fetch("/api/template", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: $("title").value,
        questions: n
      })
    });

    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.detail || "Template generation failed.");
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

$("file").addEventListener("change", event => {
  selectedFiles = Array.from(event.target.files || []);
  cameraBlob = null;

  $("fileName").textContent = selectedFiles.length
    ? `${selectedFiles.length} file(s) selected`
    : "No sheet selected";

  const size = selectedFiles.reduce((sum, file) => sum + file.size, 0);

  $("fileHint").textContent = selectedFiles.length
    ? `${(size / 1048576).toFixed(2)} MB total · each PDF page is one sheet`
    : "Upload images or a multi-page PDF to begin";

  msg("scanMsg", "", false);
});

$("cameraBtn").onclick = async () => {
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false
    });

    $("video").srcObject = cameraStream;
    $("video").hidden = false;
    $("cameraActions").hidden = false;

    msg(
      "scanMsg",
      "Camera ready. Keep the complete OMR sheet flat and inside the frame.",
      false
    );
  } catch (error) {
    msg(
      "scanMsg",
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
  canvas.getContext("2d").drawImage(video, 0, 0);

  canvas.toBlob(blob => {
    if (!blob) {
      msg("scanMsg", "Could not capture photo. Try again.", true);
      return;
    }

    cameraBlob = blob;
    selectedFiles = [];

    $("fileName").textContent = "Camera capture.jpg";
    $("fileHint").textContent = "Photo captured · ready to analyze";

    stopCamera();
  }, "image/jpeg", 0.95);
};

function stopCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach(track => track.stop());
  }

  cameraStream = null;
  $("video").hidden = true;
  $("cameraActions").hidden = true;
}

$("stopCamera").onclick = stopCamera;

$("runScan").onclick = async () => {
  const key = cleanKey($("key").value);
  const n = Number($("questions").value);

  if (key.length !== n) {
    msg("scanMsg", `Enter exactly ${n} answer-key letters.`, true);
    return;
  }

  const files = cameraBlob
    ? [new File([cameraBlob], "camera-capture.jpg", {
        type: "image/jpeg"
      })]
    : selectedFiles;

  if (!files.length) {
    msg("scanMsg", "Select a photo/PDF or capture a camera image first.", true);
    return;
  }

  const form = new FormData();

  files.forEach(file => form.append("files", file));
  form.append("answer_key", key);
  form.append("marks", $("marks").value || "1");
  form.append("negative", $("negative").value || "0");

  $("runScan").disabled = true;
  $("runScan").textContent = "Analyzing batch…";

  msg(
    "scanMsg",
    "Reading bubbles, evaluating answers and saving results…",
    false
  );

  try {
    const response = await fetch("/api/scan", {
      method: "POST",
      body: form
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Scan failed.");
    }

    latestResults = data.results || [];
    renderResults(latestResults);

    msg(
      "scanMsg",
      `Processed ${latestResults.length} sheet(s). Check all flagged results.`,
      false
    );

    $("results").scrollIntoView({ behavior: "smooth" });
  } catch (error) {
    msg("scanMsg", error.message || "Scan failed.", true);
  } finally {
    $("runScan").disabled = false;
    $("runScan").textContent = "Analyze & calculate marks";
  }
};

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
        <p>Roll confidence: ${esc((r.roll_confidence || []).join(" / "))}</p>

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
  const blankTotal = ranked.reduce((s, r) => s + num(r, "blank"), 0);
  const correctTotal = ranked.reduce((s, r) => s + num(r, "correct"), 0);

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
      const detail = $("omr-review-" + Number(button.dataset.review));

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
    exportCsv(latestResults, "fjmc-omr-batch-results.csv");
}

async function exportCsv(results, filename) {
  const response = await fetch("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ results })
  });

  if (!response.ok) {
    msg("scanMsg", "CSV export failed.", true);
    return;
  }

  downloadBlob(await response.blob(), filename);
}

$("refreshResults").onclick = async () => {
  try {
    const response = await fetch("/api/results");
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Could not load results.");
    }

    latestResults = data.results || [];
    renderResults(latestResults);
    msg("scanMsg", `Loaded ${latestResults.length} saved records.`, false);
  } catch (error) {
    msg("scanMsg", error.message, true);
  }
};

$("exportAllCsv").onclick = async () => {
  try {
    const response = await fetch("/api/results");
    const data = await response.json();

    if (!response.ok) throw new Error("Could not load saved results.");

    await exportCsv(data.results || [], "fjmc-all-students-results.csv");
  } catch (error) {
    msg("scanMsg", error.message, true);
  }
};

function msg(id, text, error) {
  $(id).textContent = text;
  $(id).className = "message" + (error ? " error" : "");
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
