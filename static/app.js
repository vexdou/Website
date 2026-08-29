(() => {
  "use strict";

  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];

  const urlInput = $("#urlInput");
  const clearBtn = $("#clearBtn");
  const downloadBtn = $("#downloadBtn");
  const kind = $("#kind");
  const statusBox = $("#status");
  const historyList = $("#historyList");
  const historyCount = $("#historyCount");
  const historySection = $("#historySection");
  const downloadsSection = $("#downloadsSection");
  const favoritesSection = $("#favoritesSection");
  const downloadsList = $("#downloadsList");
  const favoritesList = $("#favoritesList");
  const previewCard = $("#previewCard");
  const videoPreview = $("#videoPreview");
  const previewMeta = $("#previewMeta");
  const playerModal = $("#playerModal");
  const modalVideo = $("#modalVideo");
  const modalTitle = $("#modalTitle");
  const modalActions = $("#modalActions");
  const closeModal = $("#closeModal");
  const installBtn = $("#installAppBtn");
  const sideInstallBtn = $("#sideInstallBtn");
  const installHelp = $("#installHelp");
  const closeInstallHelp = $("#closeInstallHelp");
  const installRetryBtn = $("#installRetryBtn");
  const historyBtn = $("#historyBtn");
  const mobileMenuBtn = $("#mobileMenuBtn");
  const sidebar = $("#sidebar");

  const FAVORITES_KEY = "vexdou_favorites_v2";
  let historyItems = [];
  let currentView = "home";
  let deferredPrompt = null;

  function setStatus(message = "", type = "") {
    if (!statusBox) return;
    statusBox.textContent = message;
    statusBox.className = `status ${type}`.trim();
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;"
    }[char]));
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/`/g, "&#096;");
  }

  function formatTime(value) {
    if (!value) return "";
    let iso = String(value);
    if (!iso.endsWith("Z") && !/[+-]\d\d:\d\d$/.test(iso)) iso += "Z";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    const diff = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
    if (diff < 60) return "Just now";
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return date.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
    if (diff < 604800) {
      const days = Math.floor(diff / 86400);
      return `${days} day${days === 1 ? "" : "s"} ago`;
    }
    return date.toLocaleDateString([], {day: "2-digit", month: "short", year: "numeric"});
  }

  function getFavorites() {
    try {
      const value = JSON.parse(localStorage.getItem(FAVORITES_KEY) || "[]");
      return Array.isArray(value) ? value : [];
    } catch {
      return [];
    }
  }

  function saveFavorites(items) {
    localStorage.setItem(FAVORITES_KEY, JSON.stringify(items));
  }

  function isFavorite(jobId) {
    return getFavorites().some(item => item && item.job_id === jobId);
  }

  function toggleFavorite(jobId) {
    const item = historyItems.find(x => x.job_id === jobId);
    if (!item) return;

    const favorites = getFavorites();
    const index = favorites.findIndex(x => x.job_id === jobId);

    if (index >= 0) {
      favorites.splice(index, 1);
      setStatus("Removed from Favorites.", "success");
    } else {
      favorites.unshift(item);
      setStatus("Added to Favorites.", "success");
    }

    saveFavorites(favorites);
    renderAll();
  }

  function emptyState(message, icon = "◷") {
    return `<div class="empty-state"><div>${icon}</div><p>${message}</p></div>`;
  }

  function mediaCard(item) {
    const jobId = escapeAttr(item.job_id);
    const title = escapeHtml(item.title || "Media");
    const fav = isFavorite(item.job_id);
    const playable = item.status === "completed" && item.download_url;
    const thumb = item.thumbnail
      ? `<img src="${escapeAttr(item.thumbnail)}" alt="" loading="lazy">`
      : `<div class="thumb-placeholder">${item.kind === "audio" ? "♫" : "▶"}</div>`;

    return `
      <article class="media-card">
        <button class="media-thumb" type="button" data-play="${jobId}" ${playable ? "" : "disabled"}>
          ${thumb}
          ${playable ? '<span class="play-badge">▶</span>' : ""}
        </button>
        <div class="media-body">
          <div class="media-title" title="${title}">${title}</div>
          <div class="media-meta">${escapeHtml(item.kind || "video")} · ${formatTime(item.created_at)}</div>
          <div class="media-actions">
            ${playable ? `<a class="save-btn" href="${escapeAttr(item.download_url)}" download>Save</a>` : ""}
            ${item.status !== "completed" ? `<span class="processing">${escapeHtml(item.status || "processing")}…</span>` : ""}
            <button class="favorite-btn ${fav ? "fav-active" : ""}" type="button" data-favorite="${jobId}">
              ${fav ? "♥ Saved" : "♡ Favorite"}
            </button>
          </div>
        </div>
      </article>
    `;
  }

  function renderDownloads() {
    if (!downloadsList) return;
    const items = historyItems.filter(x => x.status === "completed" && x.download_url);
    downloadsList.innerHTML = items.length
      ? items.map(mediaCard).join("")
      : emptyState("No completed downloads yet. Download something from Home.", "↓");
    bindMediaActions(downloadsList);
  }

  function renderFavorites() {
    if (!favoritesList) return;
    const items = getFavorites().filter(x => x && x.download_url);
    favoritesList.innerHTML = items.length
      ? items.map(mediaCard).join("")
      : emptyState("No favorites yet. Tap ♡ Favorite on a completed download.", "♡");
    bindMediaActions(favoritesList);
  }

  function renderHistory() {
    if (!historyList) return;
    if (!historyItems.length) {
      historyList.innerHTML = emptyState("Your downloads will appear here.", "◷");
      return;
    }

    historyList.innerHTML = historyItems.map(item => {
      const playable = item.status === "completed" && item.download_url;
      const fav = isFavorite(item.job_id);
      const thumb = item.thumbnail
        ? `<img src="${escapeAttr(item.thumbnail)}" alt="" loading="lazy">`
        : `<span>${item.kind === "audio" ? "♫" : "▶"}</span>`;

      return `
        <article class="history-item">
          <button class="history-thumb" type="button" data-history-play="${escapeAttr(item.job_id)}" ${playable ? "" : "disabled"}>
            ${thumb}${playable ? '<span class="play-badge">▶</span>' : ""}
          </button>
          <button class="history-info" type="button" data-history-play="${escapeAttr(item.job_id)}" ${playable ? "" : "disabled"}>
            <strong>${escapeHtml(item.title || "Media")}</strong>
            <span>${escapeHtml(item.kind || "video")} · ${formatTime(item.created_at)}</span>
            <small>${escapeHtml(item.url || "")}</small>
          </button>
          <div class="history-actions">
            ${playable ? `<a class="save-btn" href="${escapeAttr(item.download_url)}" download>Save</a>` : `<span class="processing">${escapeHtml(item.status || "processing")}…</span>`}
            ${item.status === "completed" ? `<button class="favorite-btn ${fav ? "fav-active" : ""}" type="button" data-history-fav="${escapeAttr(item.job_id)}">${fav ? "♥" : "♡"}</button>` : ""}
          </div>
        </article>
      `;
    }).join("");

    historyList.querySelectorAll("[data-history-play]").forEach(el => {
      el.addEventListener("click", () => {
        const item = historyItems.find(x => x.job_id === el.dataset.historyPlay);
        if (item?.download_url) playMedia(item.download_url, item.title);
      });
    });

    historyList.querySelectorAll("[data-history-fav]").forEach(btn => {
      btn.addEventListener("click", e => {
        e.stopPropagation();
        toggleFavorite(btn.dataset.historyFav);
      });
    });
  }

  function bindMediaActions(container) {
    if (!container) return;

    container.querySelectorAll("[data-play]").forEach(btn => {
      btn.addEventListener("click", () => {
        const item = historyItems.find(x => x.job_id === btn.dataset.play);
        if (item?.download_url) playMedia(item.download_url, item.title);
      });
    });

    container.querySelectorAll("[data-favorite]").forEach(btn => {
      btn.addEventListener("click", e => {
        e.stopPropagation();
        toggleFavorite(btn.dataset.favorite);
      });
    });
  }

  function renderAll() {
    renderHistory();
    renderDownloads();
    renderFavorites();
  }

  function setView(view) {
    currentView = view;

    $$(".view-home").forEach(el => el.classList.toggle("hidden-view", view !== "home"));
    [historySection, downloadsSection, favoritesSection].forEach(section => {
      if (!section) return;
      section.classList.toggle("is-active", section.id.replace("Section", "") === view);
    });

    $$(".side-link").forEach(link => link.classList.toggle("active", link.dataset.view === view));

    if (view === "history") renderHistory();
    if (view === "downloads") renderDownloads();
    if (view === "favorites") renderFavorites();

    window.scrollTo({top: 0, behavior: "smooth"});
    sidebar?.classList.remove("open");
  }

  $$(".side-link").forEach(link => {
    link.addEventListener("click", () => setView(link.dataset.view));
  });

  historyBtn?.addEventListener("click", () => setView("history"));
  mobileMenuBtn?.addEventListener("click", () => sidebar?.classList.toggle("open"));

  $("#downloadsRefresh")?.addEventListener("click", loadHistory);

  clearBtn?.addEventListener("click", () => {
    urlInput.value = "";
    clearBtn.hidden = true;
    urlInput.focus();
  });

  urlInput?.addEventListener("input", () => {
    clearBtn.hidden = !urlInput.value;
  });

  downloadBtn?.addEventListener("click", startDownload);
  urlInput?.addEventListener("keydown", e => {
    if (e.key === "Enter") startDownload();
  });

  async function startDownload() {
    const url = urlInput?.value.trim();
    const selectedKind = kind?.value || "video";

    if (!url) {
      setStatus("Paste a public media link first.", "error");
      urlInput?.focus();
      return;
    }

    downloadBtn.disabled = true;
    downloadBtn.innerHTML = "<span>Starting…</span><b>•</b>";
    setStatus("Checking the link…");
    if (previewCard) previewCard.hidden = true;

    try {
      const response = await fetch("/api/download", {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({url, kind: selectedKind})
      });

      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Could not start download.");

      await pollDownload(data.job_id);
    } catch (error) {
      console.error(error);
      setStatus(error.message || "Download failed.", "error");
    } finally {
      downloadBtn.disabled = false;
      downloadBtn.innerHTML = "<span>Download</span><b>→</b>";
    }
  }

  async function pollDownload(jobId) {
    if (!jobId) throw new Error("No download job was created.");

    for (let attempt = 0; attempt < 240; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 1500));

      const response = await fetch(`/api/download/${encodeURIComponent(jobId)}`, {
        credentials: "same-origin",
        cache: "no-store"
      });

      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Download job was lost.");

      if (data.status === "completed") {
        setStatus(`Ready — ${data.title || "Media"}`, "success");

        if (previewCard) previewCard.hidden = false;
        if ($("#previewTitle")) $("#previewTitle").textContent = data.title || "Your media";

        if (videoPreview && data.kind === "video" && data.download_url) {
          videoPreview.src = data.download_url;
          videoPreview.load();
        }

        if (previewMeta) {
          previewMeta.innerHTML = `
            <div class="ready-actions">
              <a class="save-btn large" href="${escapeAttr(data.download_url || "#")}" download>Save file</a>
              <button class="favorite-btn large ${isFavorite(data.job_id) ? "fav-active" : ""}" type="button" data-favorite="${escapeAttr(data.job_id)}">
                ${isFavorite(data.job_id) ? "♥ Saved" : "♡ Favorite"}
              </button>
            </div>
          `;
          bindMediaActions(previewMeta);
        }

        await loadHistory();
        return;
      }

      if (data.status === "failed") {
        throw new Error(data.error || "Download failed.");
      }

      setStatus(data.status === "downloading" ? "Downloading your media…" : "Preparing your download…");
    }

    throw new Error("The download took too long. Please try again.");
  }

  async function loadHistory() {
    try {
      const response = await fetch("/api/history", {
        credentials: "same-origin",
        cache: "no-store"
      });

      if (!response.ok) throw new Error("History request failed.");

      const data = await response.json();
      historyItems = Array.isArray(data.items) ? data.items : [];
      if (historyCount) historyCount.textContent = String(historyItems.length);
      renderAll();
    } catch (error) {
      console.error("History:", error);
      historyItems = [];
      if (historyCount) historyCount.textContent = "0";
      renderAll();
    }
  }

  async function clearHistory() {
    if (!confirm("Clear your download history?")) return;

    try {
      const response = await fetch("/api/history", {
        method: "DELETE",
        credentials: "same-origin"
      });
      if (!response.ok) throw new Error("Could not clear history.");

      historyItems = [];
      saveFavorites([]);
      if (historyCount) historyCount.textContent = "0";
      renderAll();
      setStatus("History cleared.", "success");
    } catch (error) {
      setStatus(error.message || "Could not clear history.", "error");
    }
  }

  $("#clearHistory")?.addEventListener("click", clearHistory);

  function playMedia(url, title = "Media") {
    if (!url || !modalVideo || !playerModal) return;

    modalVideo.src = url;
    modalVideo.load();
    modalTitle.textContent = title;
    if (modalActions) {
      modalActions.innerHTML = `<a class="save-btn large" href="${escapeAttr(url)}" download>Save file</a>`;
    }

    playerModal.hidden = false;
    requestAnimationFrame(() => modalVideo.play().catch(() => {}));
  }

  function closePlayer() {
    if (!playerModal) return;
    modalVideo?.pause();
    if (modalVideo) {
      modalVideo.removeAttribute("src");
      modalVideo.load();
    }
    playerModal.hidden = true;
  }

  closeModal?.addEventListener("click", closePlayer);
  playerModal?.addEventListener("click", e => {
    if (e.target === playerModal) closePlayer();
  });

  document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
      closePlayer();
      closeInstallHelpBox();
    }
  });

  // ---------- PWA install ----------
  function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true;
  }

  function setInstallVisibility(show) {
    if (isStandalone()) {
      if (installBtn) installBtn.style.display = "none";
      if (sideInstallBtn) sideInstallBtn.style.display = "none";
      return;
    }
    if (installBtn) installBtn.style.display = show ? "inline-flex" : "none";
    if (sideInstallBtn) sideInstallBtn.style.display = show ? "block" : "block";
  }

  window.addEventListener("beforeinstallprompt", e => {
    e.preventDefault();
    deferredPrompt = e;
    setInstallVisibility(true);
  });

  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    setInstallVisibility(false);
    closeInstallHelpBox();
    setStatus("VEXDOU installed successfully.", "success");
  });

  async function installApp() {
    if (isStandalone()) return;

    if (deferredPrompt) {
      deferredPrompt.prompt();
      const choice = await deferredPrompt.userChoice;
      deferredPrompt = null;
      if (choice?.outcome === "accepted") {
        setInstallVisibility(false);
      }
      return;
    }

    // Chrome/Samsung can hide beforeinstallprompt until browser criteria are met.
    // Give the user the native browser-menu fallback instead of a dead button.
    openInstallHelp();
  }

  function openInstallHelp() {
    if (!installHelp) return;
    installHelp.hidden = false;
  }

  function closeInstallHelpBox() {
    if (installHelp) installHelp.hidden = true;
  }

  installBtn?.addEventListener("click", installApp);
  sideInstallBtn?.addEventListener("click", installApp);
  installRetryBtn?.addEventListener("click", async () => {
    if (deferredPrompt) {
      await installApp();
    } else {
      closeInstallHelpBox();
      setStatus("Open Chrome ⋮ menu → Install app / Add to Home screen.", "success");
    }
  });
  closeInstallHelp?.addEventListener("click", closeInstallHelpBox);
  installHelp?.addEventListener("click", e => {
    if (e.target === installHelp) closeInstallHelpBox();
  });

  // Register service worker only after page load.
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", async () => {
      try {
        const registration = await navigator.serviceWorker.register("/sw.js", {scope: "/"});
        await registration.update();
        console.log("VEXDOU Service Worker ready:", registration.scope);
      } catch (error) {
        console.error("Service Worker registration failed:", error);
      }
    });
  }

  // Keep the install control available as a visible fallback on Android/Chrome.
  setInstallVisibility(!isStandalone());

  setView("home");
  loadHistory();
})();
