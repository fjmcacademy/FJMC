const $ = (id) => document.getElementById(id);

let cameraStream = null;
let selectedFiles = [];
let cameraFile = null;

const video = $("video");
const cameraCanvas = $("cameraCanvas");

function setStatus(id, message, error = false) {
  const el = $(id);
  el.textContent = message;
  el.style.color = error ? "#dc2626" : "#64748b";
}

function addFile(file) {
  if (!file) return;

  selectedFiles.push(file);
  renderPreviews();
}

function renderPreviews() {
  const area = $("previewArea");
  const list = $("previewList");

  list.innerHTML = "";

  if (!selectedFiles.length) {
    area.hidden = true;
    return;
  }

  area.hidden = false;

  selectedFiles.forEach((file, index) => {
    const item = document.createElement("div");
    item.className = "preview-item";

    if (file.type.startsWith("image/")) {
      const image = document.createElement("img");
      image.src = URL.createObjectURL(file);
      image.alt = file.name;
      item.appendChild(image);
    } else {
      const placeholder = document.createElement("div");
      placeholder.style.height = "150px";
      placeholder.style.display = "grid";
      placeholder.style.placeItems = "center";
      placeholder.textContent = "PDF";
      item.appendChild(placeholder);
    }

    const name = document.createElement("p");
    name.textContent = `${index + 1}. ${file.name}`;
    item.appendChild(name);

    list.appendChild(item);
  });
}

$("files").addEventListener("change", (event) => {
  const files = Array.from(event.target.files || []);

  selectedFiles = selectedFiles.filter(
    (file) => file !== cameraFile
  );

  cameraFile = null;

  files.forEach(addFile);

  $("fileInfo").textContent =
    `${files.length} file(s) selected.`;
});

async function openCamera() {
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 1920 },
        height: { ideal: 1080 }
      },
      audio: false
    });

    video.srcObject = cameraStream;
    await video.play();

    $("cameraOverlay").hidden = true;
    $("cameraBtn").disabled = true;
    $("captureBtn").disabled = false;
    $("stopCamera").disabled = false;

    setStatus(
      "cameraStatus",
      "Camera ready. Place the complete OMR sheet inside the frame, then tap Scan This Sheet."
    );
  } catch (error) {
    setStatus(
      "cameraStatus",
      "Camera could not open. Allow camera permission or upload a photo.",
      true
    );
  }
}

function stopCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach(
      (track) => track.stop()
    );
    cameraStream = null;
  }

  video.srcObject = null;
  $("cameraBtn").disabled = false;
  $("captureBtn").disabled = true;
  $("stopCamera").disabled = true;
  $("cameraOverlay").hidden = false;

  setStatus("cameraStatus", "Camera stopped.");
}

function captureSheet() {
  if (!cameraStream || !video.videoWidth) {
    setStatus("cameraStatus", "Camera is not ready.", true);
    return;
  }

  cameraCanvas.width = video.videoWidth;
  cameraCanvas.height = video.videoHeight;

  const context = cameraCanvas.getContext("2d");
  context.drawImage(
    video,
    0,
    0,
    cameraCanvas.width,
    cameraCanvas.height
  );

  cameraCanvas.toBlob((blob) => {
    if (!blob) {
      setStatus("cameraStatus", "Could not capture image.", true);
      return;
    }

    if (cameraFile) {
      selectedFiles = selectedFiles.filter(
        (file) => file !== cameraFile
      );
    }

    cameraFile = new File(
      [blob],
      `FJMC_Camera_${Date.now()}.jpg`,
      { type: "image/jpeg" }
    );

    selectedFiles.push(cameraFile);
    renderPreviews();

    setStatus(
      "cameraStatus",
      "Photo captured. Check the preview; capture again if the sheet is tilted, blurred or cut off."
    );
  }, "image/jpeg", 0.94);
}

function parseAnswerKey() {
  const raw = $("answerKey").value
    .trim()
    .toUpperCase();

  const values = raw
    .split(/[\s,;]+/)
    .filter(Boolean);

  if (values.length !== 100) {
    throw new Error(
      `Answer key must contain exactly 100 answers. You entered ${values.length}.`
    );
  }

  const key = {};

  values.forEach((answer, index) => {
    if (!["A", "B", "C", "D"].includes(answer)) {
      throw new Error(
        `Invalid answer at question ${index + 1}: ${answer}`
      );
    }

    key[String(index + 1)] = answer;
  });

  return key;
}

async function processSheets() {
  if (!selectedFiles.length) {
    setStatus("scanStatus", "Choose or capture at least one sheet.", true);
    return;
  }

  let answerKey;

  try {
    answerKey = parseAnswerKey();
  } catch (error) {
    setStatus("scanStatus", error.message, true);
    return;
  }

  const marks = Number($("marks").value);
  const negative = Number($("negative").value);

  if (!Number.isFinite(marks) || !Number.isFinite(negative)) {
    setStatus("scanStatus", "Enter valid marks.", true);
    return;
  }

  const form = new FormData();

  selectedFiles.forEach((file) => {
    form.append("files", file, file.name);
  });

  form.append("answer_key", JSON.stringify(answerKey));
  form.append("marks", String(marks));
  form.append("negative", String(negative));

  $("processBtn").disabled = true;
  $("processBtn").textContent = "Processing...";
  setStatus(
    "scanStatus",
    "Uploading and processing sheets. Large photos or PDFs may take time."
  );

  try {
    const response = await fetch("/api/scan", {
      method: "POST",
      body: form
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.detail || "Scanning failed."
      );
    }

    const successful = data.results.filter(
      (item) => item.id
    ).length;

    const failed = data.results.length - successful;

    setStatus(
      "scanStatus",
      `Completed. Successful pages: ${successful}. Failed pages: ${failed}.`
    );

    renderScanResults(data.results);
    await loadResults();

  } catch (error) {
    setStatus(
      "scanStatus",
      error.message || "Server error.",
      true
    );
  } finally {
    $("processBtn").disabled = false;
    $("processBtn").textContent = "Proceed — Process OMR";
  }
}

function renderScanResults(items) {
  const container = $("results");

  const rows = items.filter((item) => item.id);

  if (!rows.length) {
    container.textContent = "No pages were successfully processed.";
    return;
  }

  container.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Roll</th>
            <th>Score</th>
            <th>Correct</th>
            <th>Wrong</th>
            <th>Review</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((r) => `
            <tr>
              <td>${escapeHTML(r.name || "Unreadable")}</td>
              <td>${escapeHTML(r.roll_number || "")}</td>
              <td>${Number(r.score).toFixed(2)}</td>
              <td>${r.correct}</td>
              <td>${r.wrong}</td>
              <td class="${r.review_required ? "review" : "good"}">
                ${r.review_required ? "Required" : "No"}
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  })[char]);
}

async function loadResults() {
  try {
    const response = await fetch("/api/results");

    if (!response.ok) {
      throw new Error("Could not load results.");
    }

    const data = await response.json();
    const rows = data.results || [];

    if (!rows.length) {
      $("results").textContent = "No saved results yet.";
      return;
    }

    $("results").innerHTML = `
      <p>${rows.length} saved result(s)</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Rank</th>
              <th>Name</th>
              <th>Roll</th>
              <th>Score</th>
              <th>Correct</th>
              <th>Wrong</th>
              <th>Review</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map((r) => `
              <tr>
                <td>${r.rank ?? "-"}</td>
                <td>${escapeHTML(r.name || "Unreadable")}</td>
                <td>${escapeHTML(r.roll_number || "")}</td>
                <td>${Number(r.score).toFixed(2)}</td>
                <td>${r.correct}</td>
                <td>${r.wrong}</td>
                <td class="${r.review_required ? "review" : "good"}">
                  ${r.review_required ? "Required" : "No"}
                </td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  } catch (error) {
    $("results").textContent = error.message;
  }
}

$("cameraBtn").addEventListener("click", openCamera);
$("captureBtn").addEventListener("click", captureSheet);
$("stopCamera").addEventListener("click", stopCamera);
$("processBtn").addEventListener("click", processSheets);
$("refreshBtn").addEventListener("click", loadResults);

loadResults();
