(() => {
  "use strict";

  const $ = (selector, root = document) =>
    root.querySelector(selector);

  const $$ = (selector, root = document) =>
    [...root.querySelectorAll(selector)];

  /* =========================================================
     ELEMENTS
  ========================================================= */

  const urlInput = $("#urlInput");
  const clearBtn = $("#clearBtn");
  const downloadBtn = $("#downloadBtn");
  const kind = $("#kind");

  const statusBox = $("#status");

  const homeSection = $("#homeSection");
  const downloadsSection = $("#downloadsSection");
  const historySection = $("#historySection");
  const favoritesSection = $("#favoritesSection");

  const downloadsList = $("#downloadsList");
  const historyList = $("#historyList");
  const favoritesList = $("#favoritesList");

  const historyCount = $("#historyCount");

  const previewCard = $("#previewCard");
  const previewTitle = $("#previewTitle");
  const videoPreview = $("#videoPreview");
  const previewActions = $("#previewActions");

  const playerModal = $("#playerModal");
  const modalVideo = $("#modalVideo");
  const modalTitle = $("#modalTitle");
  const closeModal = $("#closeModal");

  const clearHistoryBtn = $("#clearHistory");
  const downloadsRefresh = $("#downloadsRefresh");

  /* Install */
  const installBanner = $("#installBanner");
  const installNow = $("#installNow");
  const installClose = $("#installClose");

  /* =========================================================
     STORAGE
  ========================================================= */

  const FAVORITES_KEY = "vexdou_favorites_v3";
  const INSTALL_DISMISSED_KEY = "vexdou_install_dismissed_at";

  let historyItems = [];
  let deferredInstallPrompt = null;
  let installTimer = null;

  /* =========================================================
     HELPERS
  ========================================================= */

  function isStandalone() {
    return (
      window.matchMedia &&
      window.matchMedia("(display-mode: standalone)").matches
    ) ||
    window.navigator.standalone === true;
  }

  function setStatus(message = "", type = "") {
    if (!statusBox) return;

    statusBox.textContent = message;
    statusBox.className =
      `status ${type}`.trim();
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/[&<>"']/g, char => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;"
      }[char]));
  }

  function escapeAttr(value) {
    return escapeHtml(value)
      .replace(/`/g, "&#096;");
  }

  function formatTime(value) {
    if (!value) return "";

    let iso = String(value);

    if (
      !iso.endsWith("Z") &&
      !/[+-]\d\d:\d\d$/.test(iso)
    ) {
      iso += "Z";
    }

    const date = new Date(iso);

    if (Number.isNaN(date.getTime())) {
      return "";
    }

    const diff = Math.max(
      0,
      Math.floor(
        (Date.now() - date.getTime()) / 1000
      )
    );

    if (diff < 60) {
      return "Just now";
    }

    if (diff < 3600) {
      return `${Math.floor(diff / 60)}m ago`;
    }

    if (diff < 86400) {
      return date.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit"
      });
    }

    if (diff < 604800) {
      const days = Math.floor(diff / 86400);

      return `${days} day${days === 1 ? "" : "s"} ago`;
    }

    return date.toLocaleDateString([], {
      day: "2-digit",
      month: "short",
      year: "numeric"
    });
  }

  /* =========================================================
     FAVORITES
  ========================================================= */

  function getFavorites() {
    try {
      const data = JSON.parse(
        localStorage.getItem(FAVORITES_KEY) || "[]"
      );

      return Array.isArray(data) ? data : [];
    } catch {
      return [];
    }
  }

  function saveFavorites(items) {
    localStorage.setItem(
      FAVORITES_KEY,
      JSON.stringify(items)
    );
  }

  function isFavorite(jobId) {
    return getFavorites()
      .some(item => item?.job_id === jobId);
  }

  function toggleFavorite(jobId) {
    const item = historyItems.find(
      x => x.job_id === jobId
    );

    if (!item) return;

    const favorites = getFavorites();

    const index = favorites.findIndex(
      x => x.job_id === jobId
    );

    if (index >= 0) {
      favorites.splice(index, 1);

      setStatus(
        "Removed from Favorites.",
        "success"
      );
    } else {
      favorites.unshift(item);

      setStatus(
        "Added to Favorites.",
        "success"
      );
    }

    saveFavorites(favorites);

    renderAll();
  }

  /* =========================================================
     INSTALL APP
  ========================================================= */

  function hideInstallBanner() {
    installBanner?.classList.remove("show");
  }

  function showInstallBanner() {
    if (!installBanner) return;

    /*
      NEVER show install UI when the site is already
      running as an installed PWA.
    */
    if (isStandalone()) {
      hideInstallBanner();
      return;
    }

    installBanner.classList.add("show");
  }

  function scheduleInstallBanner() {
    clearTimeout(installTimer);

    if (isStandalone()) {
      hideInstallBanner();
      return;
    }

    installTimer = setTimeout(() => {
      showInstallBanner();
    }, 180000);
  }

  function dismissInstallForThreeMinutes() {
    hideInstallBanner();

    localStorage.setItem(
      INSTALL_DISMISSED_KEY,
      String(Date.now())
    );

    scheduleInstallBanner();
  }

  function setupInstall() {

    /*
      Android Chrome sends this event when the browser
      decides the PWA can be installed.
    */
    window.addEventListener(
      "beforeinstallprompt",
      event => {

        event.preventDefault();

        deferredInstallPrompt = event;

        if (!isStandalone()) {
          showInstallBanner();
        }
      }
    );

    /*
      Installation completed.
    */
    window.addEventListener(
      "appinstalled",
      () => {

        deferredInstallPrompt = null;

        hideInstallBanner();

        clearTimeout(installTimer);

        localStorage.removeItem(
          INSTALL_DISMISSED_KEY
        );

        setStatus(
          "VEXDOU has been installed successfully.",
          "success"
        );
      }
    );

    /*
      Install button
    */
    installNow?.addEventListener(
      "click",
      async () => {

        if (isStandalone()) {
          hideInstallBanner();
          return;
        }

        /*
          Chrome native installation prompt
        */
        if (deferredInstallPrompt) {

          const prompt =
            deferredInstallPrompt;

          deferredInstallPrompt = null;

          try {

            await prompt.prompt();

            const result =
              await prompt.userChoice;

            if (
              result &&
              result.outcome === "accepted"
            ) {
              hideInstallBanner();

              clearTimeout(installTimer);
            } else {
              /*
                User cancelled Chrome's prompt.
                Show again after 3 minutes.
              */
              hideInstallBanner();
              scheduleInstallBanner();
            }

          } catch (error) {

            console.error(
              "Install prompt:",
              error
            );

            hideInstallBanner();
            scheduleInstallBanner();
          }

          return;
        }

        /*
          beforeinstallprompt is not available.

          This can happen because Chrome controls when
          the native prompt is available.
        */
        hideInstallBanner();

        alert(
          "Chrome ma diyaarin install popup-ka hadda. " +
          "Fur Chrome menu (⋮) kadib dooro " +
          "\"Install app\" haddii uu kuu muuqdo."
        );

        scheduleInstallBanner();
      }
    );

    /*
      X button
    */
    installClose?.addEventListener(
      "click",
      dismissInstallForThreeMinutes
    );

    /*
      If already installed, NEVER show banner.
    */
    if (isStandalone()) {
      hideInstallBanner();
      return;
    }

    /*
      If Chrome has already provided the prompt,
      show banner immediately.

      Otherwise wait for beforeinstallprompt.
    */
    const dismissedAt = Number(
      localStorage.getItem(
        INSTALL_DISMISSED_KEY
      ) || 0
    );

    if (
      dismissedAt &&
      Date.now() - dismissedAt < 180000
    ) {
      scheduleInstallBanner();
    }
  }

  /* =========================================================
     NAVIGATION
  ========================================================= */

  function showSection(name) {

    homeSection.style.display =
      name === "home"
        ? "block"
        : "none";

    [downloadsSection, historySection, favoritesSection]
      .forEach(section => {
        section?.classList.remove("active");
      });

    if (name === "downloads") {
      downloadsSection?.classList.add("active");
      renderDownloads();
    }

    if (name === "history") {
      historySection?.classList.add("active");
      renderHistory();
    }

    if (name === "favorites") {
      favoritesSection?.classList.add("active");
      renderFavorites();
    }

    window.scrollTo({
      top: 0,
      behavior: "smooth"
    });
  }

  $$("[data-view]").forEach(button => {

    button.addEventListener(
      "click",
      () => {
        showSection(
          button.dataset.view
        );
      }
    );

  });

  $("#homeBrand")?.addEventListener(
    "click",
    event => {
      event.preventDefault();
      showSection("home");
    }
  );

  $("#mobileHome")?.addEventListener(
    "click",
    () => showSection("home")
  );

  /* =========================================================
     INPUT
  ========================================================= */

  clearBtn?.addEventListener(
    "click",
    () => {

      urlInput.value = "";

      clearBtn.hidden = true;

      urlInput.focus();
    }
  );

  urlInput?.addEventListener(
    "input",
    () => {
      clearBtn.hidden =
        !urlInput.value.trim();
    }
  );

  urlInput?.addEventListener(
    "keydown",
    event => {

      if (event.key === "Enter") {
        startDownload();
      }

    }
  );

  /* =========================================================
     DOWNLOAD
  ========================================================= */

  downloadBtn?.addEventListener(
    "click",
    startDownload
  );

  async function startDownload() {

    const url =
      urlInput?.value.trim();

    const selectedKind =
      kind?.value || "video";

    if (!url) {

      setStatus(
        "Paste a public media link first.",
        "error"
      );

      urlInput?.focus();

      return;
    }

    /*
      Basic client-side validation.
    */
    let parsed;

    try {
      parsed = new URL(url);
    } catch {
      setStatus(
        "Please enter a valid URL.",
        "error"
      );
      return;
    }

    if (
      parsed.protocol !== "http:" &&
      parsed.protocol !== "https:"
    ) {
      setStatus(
        "Only HTTP/HTTPS links are supported.",
        "error"
      );
      return;
    }

    downloadBtn.disabled = true;

    downloadBtn.textContent =
      "Preparing…";

    setStatus(
      "Checking your link…"
    );

    if (previewCard) {
      previewCard.hidden = true;
    }

    try {

      const response =
        await fetch(
          "/api/download",
          {
            method: "POST",
            credentials: "same-origin",
            headers: {
              "Content-Type":
                "application/json"
            },
            body: JSON.stringify({
              url,
              kind: selectedKind
            })
          }
        );

      const data =
        await response
          .json()
          .catch(() => ({}));

      if (!response.ok) {

        throw new Error(
          data.detail ||
          "Could not start download."
        );
      }

      if (!data.job_id) {

        throw new Error(
          "Server did not create a download job."
        );
      }

      await pollDownload(
        data.job_id
      );

    } catch (error) {

      console.error(
        "Download:",
        error
      );

      setStatus(
        error.message ||
        "Download failed.",
        "error"
      );

    } finally {

      downloadBtn.disabled = false;

      downloadBtn.textContent =
        "Download →";
    }
  }

  /* =========================================================
     POLL DOWNLOAD
  ========================================================= */

  async function pollDownload(jobId) {

    for (
      let attempt = 0;
      attempt < 240;
      attempt++
    ) {

      await new Promise(
        resolve =>
          setTimeout(resolve, 1500)
      );

      const response =
        await fetch(
          `/api/download/${encodeURIComponent(jobId)}`,
          {
            credentials: "same-origin",
            cache: "no-store"
          }
        );

      const data =
        await response
          .json()
          .catch(() => ({}));

      if (!response.ok) {

        throw new Error(
          data.detail ||
          "Download job was lost."
        );
      }

      if (data.status === "completed") {

        showCompletedDownload(data);

        await loadHistory();

        return;
      }

      if (data.status === "failed") {

        throw new Error(
          data.error ||
          "The server could not download this media."
        );
      }

      if (data.status === "downloading") {

        setStatus(
          "Downloading your media…"
        );

      } else {

        setStatus(
          "Preparing your download…"
        );
      }
    }

    throw new Error(
      "The download took too long. Please try again."
    );
  }

  /* =========================================================
     COMPLETED DOWNLOAD
  ========================================================= */

  function showCompletedDownload(data) {

    setStatus(
      `Ready — ${data.title || "Media"}`,
      "success"
    );

    if (!previewCard) return;

    previewCard.hidden = false;

    if (previewTitle) {
      previewTitle.textContent =
        data.title || "Your media";
    }

    /*
      Video preview only.
    */
    if (
      videoPreview &&
      data.kind === "video" &&
      data.download_url
    ) {

      videoPreview.src =
        data.download_url;

      videoPreview.load();
    }

    if (previewActions) {

      const favorite =
        isFavorite(data.job_id);

      previewActions.innerHTML = `
        <a
          class="save-btn"
          href="${escapeAttr(data.download_url || "#")}"
          download
        >
          Save file
        </a>

        <button
          class="fav-btn ${favorite ? "active" : ""}"
          type="button"
          data-preview-favorite="${escapeAttr(data.job_id)}"
        >
          ${favorite ? "♥ Saved" : "♡ Favorite"}
        </button>
      `;

      const favoriteBtn =
        previewActions.querySelector(
          "[data-preview-favorite]"
        );

      favoriteBtn?.addEventListener(
        "click",
        () => {
          toggleFavorite(
            favoriteBtn.dataset
              .previewFavorite
          );
        }
      );
    }

    /*
      Automatically show completed video
      in the preview area.
    */
    if (
      data.kind === "video" &&
      data.download_url
    ) {
      videoPreview?.scrollIntoView({
        behavior: "smooth",
        block: "center"
      });
    }
  }

  /* =========================================================
     HISTORY
  ========================================================= */

  async function loadHistory() {

    try {

      const response =
        await fetch(
          "/api/history",
          {
            credentials: "same-origin",
            cache: "no-store"
          }
        );

      if (!response.ok) {
        throw new Error(
          "History request failed."
        );
      }

      const data =
        await response.json();

      historyItems =
        Array.isArray(data.items)
          ? data.items
          : [];

      if (historyCount) {
        historyCount.textContent =
          String(historyItems.length);
      }

      renderAll();

    } catch (error) {

      console.error(
        "History:",
        error
      );

      historyItems = [];

      if (historyCount) {
        historyCount.textContent = "0";
      }

      renderAll();
    }
  }

  function renderHistory() {

    if (!historyList) return;

    if (!historyItems.length) {

      historyList.innerHTML = `
        <div class="empty">
          <div class="empty-icon">◷</div>
          <p>Your downloads will appear here.</p>
        </div>
      `;

      return;
    }

    historyList.innerHTML =
      historyItems.map(item => {

        const playable =
          item.status === "completed" &&
          item.download_url;

        const favorite =
          isFavorite(item.job_id);

        const thumb =
          item.thumbnail
            ? `
              <img
                src="${escapeAttr(item.thumbnail)}"
                alt=""
                loading="lazy"
              >
            `
            : `
              <div class="thumb-placeholder">
                ${item.kind === "audio" ? "♫" : "▶"}
              </div>
            `;

        return `
          <article class="history-card">

            <button
              class="history-thumb"
              type="button"
              data-play="${escapeAttr(item.job_id)}"
              ${playable ? "" : "disabled"}
            >

              ${thumb}

              ${
                playable
                  ? `<span class="play">▶</span>`
                  : ""
              }

            </button>

            <button
              class="history-info"
              type="button"
              data-play="${escapeAttr(item.job_id)}"
              ${playable ? "" : "disabled"}
            >

              <strong>
                ${escapeHtml(
                  item.title || "Media"
                )}
              </strong>

              <span>
                ${escapeHtml(
                  item.kind || "video"
                )}
                ·
                ${formatTime(item.created_at)}
              </span>

              <small>
                ${escapeHtml(item.url || "")}
              </small>

            </button>

            <div class="history-actions">

              ${
                playable
                  ? `
                    <a
                      class="save-btn"
                      href="${escapeAttr(item.download_url)}"
                      download
                    >
                      Save
                    </a>
                  `
                  : `
                    <span class="media-meta">
                      ${escapeHtml(
                        item.status ||
                        "processing"
                      )}…
                    </span>
                  `
              }

              ${
                item.status === "completed"
                  ? `
                    <button
                      class="fav-btn ${favorite ? "active" : ""}"
                      type="button"
                      data-favorite="${escapeAttr(item.job_id)}"
                    >
                      ${favorite ? "♥" : "♡"}
                    </button>
                  `
                  : ""
              }

            </div>

          </article>
        `;

      }).join("");

    bindHistoryActions();
  }

  function bindHistoryActions() {

    historyList
      ?.querySelectorAll("[data-play]")
      .forEach(button => {

        button.addEventListener(
          "click",
          () => {

            const item =
              historyItems.find(
                x =>
                  x.job_id ===
                  button.dataset.play
              );

            if (
              item?.download_url &&
              item.kind === "video"
            ) {

              openPlayer(
                item.download_url,
                item.title
              );
            }

          }
        );

      });

    historyList
      ?.querySelectorAll("[data-favorite]")
      .forEach(button => {

        button.addEventListener(
          "click",
          event => {

            event.stopPropagation();

            toggleFavorite(
              button.dataset.favorite
            );
          }
        );

      });
  }

  /* =========================================================
     DOWNLOADS
  ========================================================= */

  function renderDownloads() {

    if (!downloadsList) return;

    const items =
      historyItems.filter(
        item =>
          item.status === "completed" &&
          item.download_url
      );

    if (!items.length) {

      downloadsList.innerHTML = `
        <div class="empty">
          <div class="empty-icon">↓</div>
          <p>No completed downloads yet.</p>
        </div>
      `;

      return;
    }

    downloadsList.innerHTML =
      items.map(mediaCard).join("");

    bindMediaCards(downloadsList);
  }

  /* =========================================================
     FAVORITES
  ========================================================= */

  function renderFavorites() {

    if (!favoritesList) return;

    const favorites =
      getFavorites().filter(
        item =>
          item &&
          item.download_url
      );

    if (!favorites.length) {

      favoritesList.innerHTML = `
        <div class="empty">
          <div class="empty-icon">♡</div>
          <p>No favorites yet.</p>
        </div>
      `;

      return;
    }

    favoritesList.innerHTML =
      favorites.map(mediaCard).join("");

    bindMediaCards(favoritesList);
  }

  /* =========================================================
     MEDIA CARD
  ========================================================= */

  function mediaCard(item) {

    const favorite =
      isFavorite(item.job_id);

    const thumbnail =
      item.thumbnail
        ? `
          <img
            src="${escapeAttr(item.thumbnail)}"
            alt=""
            loading="lazy"
          >
        `
        : `
          <div class="thumb-placeholder">
            ${item.kind === "audio" ? "♫" : "▶"}
          </div>
        `;

    return `
      <article class="media-card">

        <button
          class="media-thumb"
          type="button"
          data-card-play="${escapeAttr(item.job_id)}"
        >

          ${thumbnail}

          <span class="play">▶</span>

        </button>

        <div class="media-body">

          <div
            class="media-title"
            title="${escapeAttr(item.title || "Media")}"
          >
            ${escapeHtml(
              item.title || "Media"
            )}
          </div>

          <div class="media-meta">
            ${escapeHtml(
              item.kind || "video"
            )}
            ·
            ${formatTime(item.created_at)}
          </div>

          <div class="media-actions">

            <a
              class="save-btn"
              href="${escapeAttr(item.download_url)}"
              download
            >
              Save
            </a>

            <button
              class="fav-btn ${favorite ? "active" : ""}"
              type="button"
              data-card-favorite="${escapeAttr(item.job_id)}"
            >
              ${favorite ? "♥ Saved" : "♡ Favorite"}
            </button>

          </div>

        </div>

      </article>
    `;
  }

  function bindMediaCards(container) {

    container
      .querySelectorAll("[data-card-play]")
      .forEach(button => {

        button.addEventListener(
          "click",
          () => {

            const item =
              historyItems.find(
                x =>
                  x.job_id ===
                  button.dataset.cardPlay
              );

            if (
              item?.download_url &&
              item.kind === "video"
            ) {

              openPlayer(
                item.download_url,
                item.title
              );
            }

          }
        );

      });

    container
      .querySelectorAll("[data-card-favorite]")
      .forEach(button => {

        button.addEventListener(
          "click",
          () => {

            toggleFavorite(
              button.dataset.cardFavorite
            );
          }
        );

      });
  }

  /* =========================================================
     PLAYER
  ========================================================= */

  function openPlayer(url, title = "Media") {

    if (!playerModal || !modalVideo) {
      return;
    }

    modalVideo.src = url;

    modalTitle.textContent =
      title || "Media";

    playerModal.classList.add("show");

    modalVideo.load();

    /*
      Browser may allow playback after user click,
      so attempt it.
    */
    const promise =
      modalVideo.play();

    if (promise?.catch) {
      promise.catch(() => {});
    }
  }

  function closePlayer() {

    if (!playerModal) return;

    modalVideo?.pause();

    if (modalVideo) {
      modalVideo.removeAttribute("src");
      modalVideo.load();
    }

    playerModal.classList.remove("show");
  }

  closeModal?.addEventListener(
    "click",
    closePlayer
  );

  playerModal?.addEventListener(
    "click",
    event => {

      if (event.target === playerModal) {
        closePlayer();
      }

    }
  );

  document.addEventListener(
    "keydown",
    event => {

      if (event.key === "Escape") {
        closePlayer();
      }

    }
  );

  /* =========================================================
     CLEAR HISTORY
  ========================================================= */

  clearHistoryBtn?.addEventListener(
    "click",
    async () => {

      const confirmed =
        window.confirm(
          "Clear your download history?"
        );

      if (!confirmed) return;

      try {

        const response =
          await fetch(
            "/api/history",
            {
              method: "DELETE",
              credentials: "same-origin"
            }
          );

        if (!response.ok) {
          throw new Error(
            "Could not clear history."
          );
        }

        historyItems = [];

        if (historyCount) {
          historyCount.textContent = "0";
        }

        renderAll();

        setStatus(
          "History cleared.",
          "success"
        );

      } catch (error) {

        setStatus(
          error.message ||
          "Could not clear history.",
          "error"
        );
      }

    }
  );

  downloadsRefresh?.addEventListener(
    "click",
    loadHistory
  );

  /* =========================================================
     RENDER ALL
  ========================================================= */

  function renderAll() {
    renderHistory();
    renderDownloads();
    renderFavorites();
  }

  /* =========================================================
     SERVICE WORKER
  ========================================================= */

  async function registerServiceWorker() {

    if (!("serviceWorker" in navigator)) {
      return;
    }

    try {

      const registration =
        await navigator.serviceWorker.register(
          "/sw.js",
          {
            scope: "/"
          }
        );

      console.log(
        "VEXDOU Service Worker:",
        registration.scope
      );

    } catch (error) {

      console.error(
        "Service Worker registration failed:",
        error
      );
    }
  }

  /* =========================================================
     INIT
  ========================================================= */

  async function init() {

    setupInstall();

    registerServiceWorker();

    await loadHistory();

    /*
      If the browser changes between standalone/browser
      mode, update install UI.
    */
    if (window.matchMedia) {

      const media =
        window.matchMedia(
          "(display-mode: standalone)"
        );

      media.addEventListener?.(
        "change",
        event => {

          if (event.matches) {
            hideInstallBanner();
            clearTimeout(installTimer);
          }

        }
      );
    }
  }

  init();

})();
