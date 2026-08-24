(() => {
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");
  const browseBtn = document.getElementById("browse-btn");

  const filePreview = document.getElementById("file-preview");
  const fileIcon = document.getElementById("file-icon");
  const fileNameEl = document.getElementById("file-name");
  const fileSizeEl = document.getElementById("file-size");
  const removeFileBtn = document.getElementById("remove-file-btn");
  const analyzeBtn = document.getElementById("analyze-btn");

  const loadingEl = document.getElementById("loading");
  const loadingText = document.getElementById("loading-text");

  const errorBox = document.getElementById("error-box");
  const errorText = document.getElementById("error-text");

  const resultsEl = document.getElementById("results");
  const extractedMeta = document.getElementById("extracted-meta");
  const extractedTextEl = document.getElementById("extracted-text");
  const statsGrid = document.getElementById("stats-grid");
  const suggestionsList = document.getElementById("suggestions-list");
  const analyzeAnotherBtn = document.getElementById("analyze-another-btn");

  const ALLOWED_EXT = ["pdf", "png", "jpg", "jpeg", "webp", "bmp", "tiff", "gif"];
  const MAX_SIZE_BYTES = 15 * 1024 * 1024;

  let selectedFile = null;

  // -------------------------------------------------------------------
  // UI state helpers
  // -------------------------------------------------------------------
  function resetUI() {
    filePreview.classList.add("hidden");
    loadingEl.classList.add("hidden");
    errorBox.classList.add("hidden");
    resultsEl.classList.add("hidden");
    dropZone.classList.remove("hidden");
    selectedFile = null;
    fileInput.value = "";
  }

  function showError(message) {
    loadingEl.classList.add("hidden");
    errorBox.classList.remove("hidden");
    errorText.textContent = message;
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  }

  function getExt(filename) {
    return filename.includes(".") ? filename.split(".").pop().toLowerCase() : "";
  }

  // -------------------------------------------------------------------
  // File selection
  // -------------------------------------------------------------------
  function handleFileSelected(file) {
    errorBox.classList.add("hidden");

    if (!file) return;

    const ext = getExt(file.name);
    if (!ALLOWED_EXT.includes(ext)) {
      showError(`Unsupported file type ".${ext}". Please upload a PDF or image (PNG, JPG, WEBP, BMP, TIFF, GIF).`);
      return;
    }
    if (file.size > MAX_SIZE_BYTES) {
      showError(`File is too large (${formatBytes(file.size)}). Max size is 15MB.`);
      return;
    }

    selectedFile = file;
    fileIcon.textContent = ext === "pdf" ? "📄" : "🖼️";
    fileNameEl.textContent = file.name;
    fileSizeEl.textContent = formatBytes(file.size);

    dropZone.classList.add("hidden");
    filePreview.classList.remove("hidden");
    resultsEl.classList.add("hidden");
  }

  browseBtn.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("click", (e) => {
    if (e.target === browseBtn) return;
    fileInput.click();
  });

  fileInput.addEventListener("change", (e) => {
    handleFileSelected(e.target.files[0]);
  });

  removeFileBtn.addEventListener("click", () => {
    resetUI();
  });

  // Drag & drop
  ["dragenter", "dragover"].forEach((evt) => {
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add("drag-over");
    });
  });

  ["dragleave", "drop"].forEach((evt) => {
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove("drag-over");
    });
  });

  dropZone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files[0];
    handleFileSelected(file);
  });

  // -------------------------------------------------------------------
  // Analyze
  // -------------------------------------------------------------------
  analyzeBtn.addEventListener("click", async () => {
    if (!selectedFile) return;

    filePreview.classList.add("hidden");
    errorBox.classList.add("hidden");
    resultsEl.classList.add("hidden");
    loadingEl.classList.remove("hidden");

    const ext = getExt(selectedFile.name);
    loadingText.textContent = ext === "pdf" ? "Extracting text from PDF…" : "Running OCR on image…";

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
      const response = await fetch(`${API_BASE_URL}/api/analyze`, {
        method: "POST",
        body: formData,
      });

      let data;
      try {
        data = await response.json();
      } catch {
        throw new Error("Server returned an unexpected response. Is the backend running?");
      }

      if (!response.ok) {
        throw new Error(data.error || `Request failed with status ${response.status}`);
      }

      renderResults(data);
    } catch (err) {
      const msg =
        err instanceof TypeError
          ? "Could not reach the backend. Make sure the server is running and CORS/URL is configured correctly."
          : err.message;
      showError(msg);
      filePreview.classList.remove("hidden");
    } finally {
      loadingEl.classList.add("hidden");
    }
  });

  analyzeAnotherBtn.addEventListener("click", resetUI);

  // -------------------------------------------------------------------
  // Render results
  // -------------------------------------------------------------------
  function renderResults(data) {
    dropZone.classList.add("hidden");
    resultsEl.classList.remove("hidden");

    extractedMeta.textContent = `${data.file_type.toUpperCase()} · ${data.pages} page(s)${
      data.used_ocr ? " · OCR used" : ""
    }`;
    extractedTextEl.textContent = data.extracted_text || "(No text could be extracted from this file.)";

    // Stats
    statsGrid.innerHTML = "";
    const statLabels = {
      word_count: "Words",
      sentence_count: "Sentences",
      hashtag_count: "Hashtags",
      mention_count: "Mentions",
      url_count: "Links",
      emoji_count: "Emojis",
      question_marks: "Questions",
      exclamation_marks: "Exclamations",
      readability_score: "Readability",
    };
    Object.entries(data.stats || {}).forEach(([key, value]) => {
      if (!(key in statLabels)) return;
      const item = document.createElement("div");
      item.className = "stat-item";
      item.innerHTML = `<div class="stat-value">${value}</div><div class="stat-label">${statLabels[key]}</div>`;
      statsGrid.appendChild(item);
    });

    // Suggestions
    suggestionsList.innerHTML = "";
    (data.suggestions || []).forEach((s) => {
      const row = document.createElement("div");
      row.className = `suggestion ${s.severity}`;
      row.innerHTML = `
        <span class="badge">${s.severity}</span>
        <div class="suggestion-body">
          <span class="suggestion-category">${s.category}</span>
          <span>${s.message}</span>
        </div>
      `;
      suggestionsList.appendChild(row);
    });
  }
})();
