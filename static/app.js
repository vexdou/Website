(() => {
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];

  const state = {
    items: [],
    favs: new Set(
      JSON.parse(localStorage.getItem("quickdl_favs") || "[]")
    ),
    polls: new Map()
  };

  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;"
    }[char]));

  const saveFavs = () => {
    localStorage.setItem(
      "quickdl_favs",
      JSON.stringify([...state.favs])
    );
  };

  function toast(message) {
    const element = $("#toast");
    if (!element) return;

    element.textContent = message;
    element.classList.add("show");

    clearTimeout(window._toast);

    window._toast = setTimeout(() => {
      element.classList.remove("show");
    }, 3800);
  }

  /*
   * History/Favorites time display
   *
   * 0 minutes       -> Now
   * 1 minute        -> 1 min ago
   * 2 minutes       -> 2 min ago
   * 1 hour          -> 1 hour ago
   * 2 hours         -> 2 hours ago
   * 1 day           -> 1 day ago
   * 5 days          -> 5 days ago
   * 7 days          -> 7 days ago
   * Older than 7d   -> DD/M/YYYY
   */
  function relative(iso) {
    const date = new Date(iso);

    if (Number.isNaN(date.getTime())) {
      return "";
    }

    const diff = Math.max(0, Date.now() - date.getTime());

    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (minutes < 1) {
      return "Now";
    }

    if (minutes < 60) {
      return `${minutes} min ago`;
    }

    if (hours < 24) {
      return `${hours} hour${hours === 1 ? "" : "s"} ago`;
    }

    if (days <= 7) {
      return `${days} day${days === 1 ? "" : "s"} ago`;
    }

    return `${date.getDate()}/${date.getMonth() + 1}/${date.getFullYear()}`;
  }

  function view(viewName) {
    $$(".view").forEach((element) => {
      element.classList.add("hidden");
    });

    const target =
      viewName === "home"
        ? $("#homeView")
        : $(`#${viewName}View`);

    if (target) {
      target.classList.remove("hidden");
    }

    $$(".nav-tab").forEach((button) => {
      button.classList.toggle(
        "active",
        button.dataset.view === viewName
      );
    });

    if (viewName === "history") {
      loadHistory();
    }

    if (viewName === "favorites") {
      loadHistory().then(renderFavorites);
    }

    window.scrollTo({
      top: 0,
      behavior: "smooth"
    });
  }

  $$(".nav-tab").forEach((button) => {
    button.addEventListener("click", () => {
      view(button.dataset.view);
    });
  });

  const brand = $(".brand");

  if (brand) {
    brand.addEventListener("click", () => {
      view("home");
    });
  }

  function row(item) {
    return `
      <article class="history-row">
        <div class="thumb">
          ${
            item.thumbnail
              ? `<img src="${esc(item.thumbnail)}" loading="lazy" alt="">`
              : "<span>▶</span>"
          }
          <button
            class="mini-play"
            data-play="${esc(item.job_id)}"
            type="button"
            aria-label="Play"
          >▶</button>
        </div>

        <div class="history-info">
          <strong>${esc(item.title || "Media")}</strong>
          <small>
            ${esc(item.platform)} ·
            ${esc(item.kind)} ·
            ${relative(item.created_at)}
          </small>
        </div>

        <div class="actions">
          <button
            class="small-btn"
            data-play="${esc(item.job_id)}"
            type="button"
          >
            Play
          </button>

          <a
            class="small-btn save"
            href="${esc(item.download_url)}"
          >
            Save
          </a>

          <button
            class="small-btn"
            data-fav="${esc(item.job_id)}"
            type="button"
            aria-label="Favorite"
          >
            ${state.favs.has(item.job_id) ? "♥" : "♡"}
          </button>
        </div>
      </article>
    `;
  }

  function card(item) {
    return `
      <article class="favorite-card">
        <div class="thumb">
          ${
            item.thumbnail
              ? `<img src="${esc(item.thumbnail)}" loading="lazy" alt="">`
              : "<span>▶</span>"
          }

          <button
            class="mini-play"
            data-play="${esc(item.job_id)}"
            type="button"
            aria-label="Play"
          >▶</button>
        </div>

        <div class="favorite-body">
          <strong>${esc(item.title || "Media")}</strong>

          <small>
            ${esc(item.platform)} ·
            ${relative(item.created_at)}
          </small>

          <div class="actions">
            <button
              class="small-btn"
              data-play="${esc(item.job_id)}"
              type="button"
            >
              Play
            </button>

            <a
              class="small-btn save"
              href="${esc(item.download_url)}"
            >
              Save
            </a>

            <button
              class="small-btn"
              data-fav="${esc(item.job_id)}"
              type="button"
              aria-label="Remove favorite"
            >
              ♥
            </button>
          </div>
        </div>
      </article>
    `;
  }

  function bind() {
    $$("[data-play]").forEach((button) => {
      button.addEventListener("click", () => {
        const item = state.items.find(
          (entry) => entry.job_id === button.dataset.play
        );

        if (item) {
          openPlayer(item);
        }
      });
    });

    $$("[data-fav]").forEach((button) => {
      button.addEventListener("click", () => {
        const id = button.dataset.fav;

        if (state.favs.has(id)) {
          state.favs.delete(id);
        } else {
          state.favs.add(id);
        }

        saveFavs();

        renderHistory();
        renderFavorites();
      });
    });
  }

  function renderHistory() {
    const historyElement = $("#history");

    if (!historyElement) return;

    const items = state.items.filter(
      (item) =>
        item.status === "completed" &&
        item.download_url
    );

    historyElement.innerHTML = items.length
      ? items.map(row).join("")
      : '<div class="empty">No successful downloads yet.</div>';

    bind();
  }

  function renderFavorites() {
    const favoritesElement = $("#favorites");

    if (!favoritesElement) return;

    const items = state.items.filter(
      (item) =>
        item.status === "completed" &&
        item.download_url &&
        state.favs.has(item.job_id)
    );

    favoritesElement.innerHTML = items.length
      ? items.map(card).join("")
      : '<div class="empty">No favorites yet.</div>';

    bind();
  }

  async function loadHistory() {
    try {
      const response = await fetch(
        `/api/history?${Date.now()}`,
        {
          cache: "no-store",
          credentials: "same-origin"
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail || "Could not load history"
        );
      }

      state.items = data.items || [];

      renderHistory();
      renderFavorites();
    } catch (error) {
      toast("Could not load history");
    }
  }

  function openPlayer(item) {
    const modal = $("#player");
    const video = $("#video");
    const audio = $("#audio");
    const saveButton = $("#saveBtn");
    const title = $("#playerTitle");

    if (!modal || !video || !audio) return;

    if (title) {
      title.textContent = item.title || "Media preview";
    }

    if (saveButton) {
      saveButton.href = item.download_url || "#";
    }

    video.pause();
    audio.pause();

    video.classList.add("hidden");
    audio.classList.add("hidden");

    video.removeAttribute("src");
    audio.removeAttribute("src");

    video.load();
    audio.load();

    if (item.kind === "audio") {
      video.style.display = "none";

      audio.style.display = "block";
      audio.classList.remove("hidden");

      if (item.preview_url) {
        audio.src = item.preview_url;
        audio.play().catch(() => {});
      }
    } else {
      audio.style.display = "none";

      video.style.display = "block";
      video.classList.remove("hidden");

      if (item.preview_url) {
        video.src = item.preview_url;
        video.play().catch(() => {});
      }
    }

    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
  }

  function closePlayer() {
    const video = $("#video");
    const audio = $("#audio");
    const modal = $("#player");

    if (video) {
      video.pause();
      video.removeAttribute("src");
      video.load();
    }

    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }

    if (modal) {
      modal.classList.add("hidden");
      modal.setAttribute("aria-hidden", "true");
    }
  }

  const closePlayerButton = $("#closePlayer");

  if (closePlayerButton) {
    closePlayerButton.addEventListener(
      "click",
      closePlayer
    );
  }

  const player = $("#player");

  if (player) {
    player.addEventListener("click", (event) => {
      if (event.target.id === "player") {
        closePlayer();
      }
    });
  }

  document.addEventListener("keydown", (event) => {
    if (
      event.key === "Escape" &&
      $("#player") &&
      !$("#player").classList.contains("hidden")
    ) {
      closePlayer();
    }
  });

  const pasteButton = $("#pasteBtn");

  if (pasteButton) {
    pasteButton.addEventListener("click", async () => {
      try {
        const text =
          await navigator.clipboard.readText();

        if (text) {
          $("#url").value = text;
          $("#url").focus();
        }
      } catch {
        toast(
          "Clipboard permission is not available; paste normally into the field."
        );
      }
    });
  }

  async function start() {
    const input = $("#url");
    const kindElement = $("#kind");
    const button = $("#downloadBtn");

    if (!input || !kindElement || !button) {
      return;
    }

    const url = input.value.trim();
    const kind = kindElement.value;

    if (!url) {
      toast("Paste a link first");
      return;
    }

    try {
      new URL(url);
    } catch {
      toast("Enter a valid URL");
      return;
    }

    button.disabled = true;

    button.innerHTML = `
      <span class="download-icon">⌛</span>
      <span>
        <b>Starting…</b>
        <small>Please wait</small>
      </span>
    `;

    const status = $("#status");
    const statusText = $("#statusText");
    const statusSub = $("#statusSub");
    const statusTime = $("#statusTime");
    const bar = $("#bar");

    if (status) {
      status.classList.remove("hidden");
    }

    if (statusText) {
      statusText.textContent = "Adding to queue…";
    }

    if (statusSub) {
      statusSub.textContent =
        "Your link is being prepared.";
    }

    if (statusTime) {
      statusTime.textContent = "";
    }

    if (bar) {
      bar.style.width = "8%";
    }

    input.value = "";

    try {
      const response = await fetch("/api/download", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          url,
          kind
        })
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail || "Could not start"
        );
      }

      if (!data.job_id) {
        throw new Error("Download job was not created");
      }

      poll(data.job_id);
    } catch (error) {
      toast(error.message);

      if (statusText) {
        statusText.textContent = "Could not start";
      }

      if (statusSub) {
        statusSub.textContent =
          "Please try another link.";
      }

      if (bar) {
        bar.style.width = "0%";
      }
    } finally {
      button.disabled = false;

      button.innerHTML = `
        <span class="download-icon">↓</span>
        <span>
          <b>Download</b>
          <small>Start download</small>
        </span>
      `;
    }
  }

  async function poll(jobId) {
    const started = Date.now();

    state.polls.set(jobId, true);

    while (state.polls.has(jobId)) {
      await new Promise((resolve) =>
        setTimeout(resolve, 900)
      );

      try {
        const response = await fetch(
          `/api/download/${encodeURIComponent(jobId)}?${Date.now()}`,
          {
            cache: "no-store",
            credentials: "same-origin"
          }
        );

        const item = await response.json();

        if (!response.ok) {
          throw new Error(
            item.detail || "Status unavailable"
          );
        }

        if (item.status === "queued") {
          $("#statusText").textContent = "Queued…";
          $("#statusSub").textContent =
            "Waiting for the downloader.";
          $("#bar").style.width = "18%";
        }

        else if (item.status === "downloading") {
          $("#statusText").textContent =
            `Downloading ${item.platform || ""}…`;

          $("#statusSub").textContent =
            "Please keep this tab open.";

          $("#bar").style.width = "58%";
        }

        else if (item.status === "completed") {
          $("#statusText").textContent =
            "✓ Download ready";

          $("#statusSub").textContent =
            "Preview it or save it to your device.";

          $("#bar").style.width = "100%";

          state.items = [
            item,
            ...state.items.filter(
              (entry) => entry.job_id !== item.job_id
            )
          ];

          state.polls.delete(jobId);

          toast("Download completed");

          renderHistory();
          renderFavorites();

          setTimeout(() => {
            openPlayer(item);
          }, 250);

          return;
        }

        else if (item.status === "failed") {
          throw new Error(
            item.error || "Download failed"
          );
        }

        else if (item.status === "expired") {
          throw new Error(
            item.error || "File expired"
          );
        }

        if (Date.now() - started > 15601000) {
          throw new Error(
            "Download timed out"
          );
        }
      } catch (error) {
        state.polls.delete(jobId);

        if ($("#statusText")) {
          $("#statusText").textContent =
            "Download failed";
        }

        if ($("#statusSub")) {
          $("#statusSub").textContent =
            error.message;
        }

        if ($("#bar")) {
          $("#bar").style.width = "0%";
        }

        toast(error.message);

        return;
      }
    }
  }

  const downloadButton = $("#downloadBtn");

  if (downloadButton) {
    downloadButton.addEventListener(
      "click",
      start
    );
  }

  const urlInput = $("#url");

  if (urlInput) {
    urlInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        start();
      }
    });
  }

  const clearButton = $("#clear");

  if (clearButton) {
    clearButton.addEventListener("click", async () => {
      if (
        !confirm(
          "Clear successful download history?"
        )
      ) {
        return;
      }

      try {
        const response = await fetch(
          "/api/history",
          {
            method: "DELETE",
            credentials: "same-origin"
          }
        );

        if (!response.ok) {
          throw new Error(
            "Could not clear history"
          );
        }

        state.items = [];
        state.favs.clear();

        saveFavs();

        renderHistory();
        renderFavorites();

        toast("History cleared");
      } catch (error) {
        toast(error.message);
      }
    });
  }

  fetch(`/api/public-config?${Date.now()}`, {
    cache: "no-store",
    credentials: "same-origin"
  })
    .then((response) => {
      if (!response.ok) {
        throw new Error("Config unavailable");
      }

      return response.json();
    })
    .then((config) => {
      if (
        config.announcement_enabled &&
        config.announcement
      ) {
        const announcement =
          $("#announcement");

        if (announcement) {
          announcement.textContent =
            config.announcement;

          announcement.classList.remove("hidden");
        }
      }
    })
    .catch(() => {});

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker
      .register("/sw.js")
      .catch(() => {});
  }

  loadHistory();

  setInterval(() => {
    const historyView = $("#historyView");

    if (
      historyView &&
      !historyView.classList.contains("hidden")
    ) {
      loadHistory();
    }
  }, 15000);
})();
