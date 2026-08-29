const $ = (s) => document.querySelector(s);

const urlInput = $("#urlInput");
const clearBtn = $("#clearBtn");
const downloadBtn = $("#downloadBtn");
const kind = $("#kind");
const statusBox = $("#status");

const historyList = $("#historyList");
const historyCount = $("#historyCount");
const historySection = $("#historySection");

const previewCard = $("#previewCard");
const videoPreview = $("#videoPreview");
const previewMeta = $("#previewMeta");

const playerModal = $("#playerModal");
const modalVideo = $("#modalVideo");
const modalTitle = $("#modalTitle");
const closeModal = $("#closeModal");

const FAVORITES_KEY = "vexdou_favorites_v1";

let historyItems = [];
let currentView = "home";

/* =========================================================
BASIC HELPERS
========================================================= */

function status(text, type = "") {
if (!statusBox) return;

statusBox.textContent = text;
statusBox.className = "status ${type}";
}

function escapeHtml(value) {
return String(value ?? "").replace(/[&<>"']/g, c => ({
"&": "&",
"<": "<",
">": ">",
'"': """,
"'": "'"
}[c]));
}

function escapeAttr(value) {
return escapeHtml(value).replace(/`/g, "`");
}

function formatTime(iso) {
if (!iso) return "";

let value = iso;

if (
!value.endsWith("Z") &&
!value.includes("+") &&
!value.includes("-", 10)
) {
value += "Z";
}

const date = new Date(value);

if (Number.isNaN(date.getTime())) {
return "";
}

const diff = Math.max(
0,
Math.floor((Date.now() - date.getTime()) / 1000)
);

if (diff < 60) return "Just now";

if (diff < 3600) {
return "${Math.floor(diff / 60)}m ago";
}

if (diff < 86400) {
return date.toLocaleTimeString([], {
hour: "2-digit",
minute: "2-digit"
});
}

const days = Math.floor(diff / 86400);

if (days <= 7) {
return "${days} day${days > 1 ? "s" : ""} ago";
}

return "${date.getDate()}/${date.getMonth() + 1}/${date.getFullYear()}";
}

/* =========================================================
FAVORITES
========================================================= */

function getFavorites() {
try {
const value = JSON.parse(
localStorage.getItem(FAVORITES_KEY) || "[]"
);

return Array.isArray(value) ? value : [];

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
return getFavorites().some(
item => item.job_id === jobId
);
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

status(
  "Removed from Favorites.",
  "success"
);

} else {

favorites.unshift(item);

status(
  "Added to Favorites.",
  "success"
);

}

saveFavorites(favorites);

renderFavorites();
renderHistory();
renderDownloads();
}

/* =========================================================
CREATE APP SECTIONS
========================================================= */

function createSections() {

const main = document.querySelector(".main");

if (!main) return;

/* ---------------- DOWNLOADS ---------------- */

let downloadsSection =
document.getElementById("downloadsSection");

if (!downloadsSection) {

downloadsSection =
  document.createElement("section");

downloadsSection.id =
  "downloadsSection";

downloadsSection.className =
  "recent-section app-view-section";


downloadsSection.innerHTML = `

  <div class="section-header">

    <div>

      <div class="section-kicker">
        YOUR MEDIA
      </div>

      <h2>
        Downloads
      </h2>

    </div>

    <button
      type="button"
      class="view-history"
      id="downloadsRefresh"
    >
      Refresh
    </button>

  </div>


  <div class="history-wrap">

    <div
      id="downloadsList"
      class="downloads-grid"
    ></div>

  </div>

`;


const recentSection =
  document.querySelector(
    ".recent-section"
  );

if (recentSection) {

  recentSection.after(
    downloadsSection
  );

} else {

  main.appendChild(
    downloadsSection
  );
}

}

/* ---------------- FAVORITES ---------------- */

let favoritesSection =
document.getElementById(
"favoritesSection"
);

if (!favoritesSection) {

favoritesSection =
  document.createElement("section");

favoritesSection.id =
  "favoritesSection";

favoritesSection.className =
  "recent-section app-view-section";


favoritesSection.innerHTML = `

  <div class="section-header">

    <div>

      <div class="section-kicker">
        SAVED MEDIA
      </div>

      <h2>
        Favorites
      </h2>

    </div>

    <span class="view-history">
      Saved on this device
    </span>

  </div>


  <div class="history-wrap">

    <div
      id="favoritesList"
      class="downloads-grid"
    ></div>

  </div>

`;


downloadsSection.after(
  favoritesSection
);

}

/* =======================================================
FIX HISTORY
======================================================= */

if (
historySection &&
historyList &&
historyList.parentElement !== historySection
) {

historySection.appendChild(
  historyList
);

}

/* =======================================================
EXTRA STYLES
======================================================= */

if (
!document.getElementById(
"vexdou-navigation-style"
)
) {

const style =
  document.createElement("style");

style.id =
  "vexdou-navigation-style";


style.textContent = `

  .app-view-section {
    display: none;
  }

  .app-view-section.is-active {
    display: block;
  }

  #historySection.is-active {
    display: block !important;
  }

  .downloads-grid {
    display: grid;
    grid-template-columns:
      repeat(3, minmax(0, 1fr));
    gap: 12px;
  }

  .media-card {
    overflow: hidden;
    border:
      1px solid
      rgba(255,255,255,.07);
    border-radius: 15px;
    background:
      rgba(255,255,255,.025);
  }

  .media-card-thumb {
    aspect-ratio: 16 / 10;
    overflow: hidden;
    background: #030607;
    cursor: pointer;
  }

  .media-card-thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .media-card-placeholder {
    width: 100%;
    height: 100%;
    display: grid;
    place-items: center;
    color: #00f5a0;
    font-size: 30px;
  }

  .media-card-body {
    padding: 12px;
  }

  .media-card-title {
    color: #eef5f2;
    font-size: 11px;
    font-weight: 800;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .media-card-meta {
    margin-top: 5px;
    color: #65716c;
    font-size: 9px;
  }

  .media-card-actions {
    display: flex;
    gap: 6px;
    margin-top: 10px;
  }

  .media-card-actions a,
  .media-card-actions button {
    flex: 1;
    border:
      1px solid
      rgba(255,255,255,.07);
    border-radius: 8px;
    padding: 7px 6px;
    text-align: center;
    background:
      rgba(255,255,255,.035);
    color: #aab4b0;
    font-size: 9px;
    text-decoration: none;
    cursor: pointer;
  }

  .media-card-actions .fav-active {
    color: #ff68d7;
    border-color:
      rgba(255,62,200,.25);
  }

  .view-empty {
    grid-column: 1 / -1;
    min-height: 150px;
    display: grid;
    place-items: center;
    color: #56615e;
    border:
      1px dashed
      rgba(255,255,255,.06);
    border-radius: 14px;
    font-size: 11px;
    text-align: center;
    padding: 20px;
  }

  @media(max-width:760px) {

    .downloads-grid {
      grid-template-columns: 1fr;
    }

  }

`;

document.head.appendChild(
  style
);

}
}

/* =========================================================
NAVIGATION
========================================================= */

function setActiveNav(view) {

document
.querySelectorAll(
".side-link[data-view]"
)
.forEach(link => {

  link.classList.toggle(
    "active",
    link.dataset.view === view
  );

});

}

function setView(view) {

createSections();

currentView = view;

const hero =
document.querySelector(".hero");

const downloadSection =
document.querySelector(
".download-section"
);

const recentSection =
document.querySelector(
".recent-section:not(#downloadsSection):not(#favoritesSection)"
);

const featureStrip =
document.querySelector(
".feature-strip"
);

const footer =
document.querySelector(".footer");

const downloadsSection =
document.getElementById(
"downloadsSection"
);

const favoritesSection =
document.getElementById(
"favoritesSection"
);

const isHome =
view === "home";

if (hero) {
hero.style.display =
isHome ? "grid" : "none";
}

if (downloadSection) {
downloadSection.style.display =
isHome ? "block" : "none";
}

if (recentSection) {
recentSection.style.display =
isHome ? "block" : "none";
}

if (featureStrip) {
featureStrip.style.display =
isHome ? "block" : "none";
}

if (footer) {
footer.style.display = "flex";
}

if (downloadsSection) {

downloadsSection.classList.toggle(
  "is-active",
  view === "downloads"
);

}

if (favoritesSection) {

favoritesSection.classList.toggle(
  "is-active",
  view === "favorites"
);

}

if (historySection) {

historySection.classList.toggle(
  "is-active",
  view === "history"
);

}

setActiveNav(view);

if (view === "downloads") {
renderDownloads();
}

if (view === "favorites") {
renderFavorites();
}

if (view === "history") {
renderHistory();
}

window.scrollTo({
top: 0,
behavior: "smooth"
});
}

/* =========================================================
CONNECT SIDEBAR BUTTONS
========================================================= */

function bindNavigation() {

createSections();

document
.querySelectorAll(".side-link")
.forEach(link => {

  if (
    link.dataset.vexdouBound === "1"
  ) {
    return;
  }


  link.dataset.vexdouBound =
    "1";


  const text =
    (
      link.textContent || ""
    )
      .trim()
      .toLowerCase();


  if (text.includes("home")) {

    link.dataset.view =
      "home";

  } else if (
    text.includes("downloads")
  ) {

    link.dataset.view =
      "downloads";

  } else if (
    text.includes("history")
  ) {

    link.dataset.view =
      "history";

  } else if (
    text.includes("favorites")
  ) {

    link.dataset.view =
      "favorites";

  }


  if (!link.dataset.view) {
    return;
  }


  link.addEventListener(
    "click",
    event => {

      event.preventDefault();

      setView(
        link.dataset.view
      );

    }
  );

});

document
.getElementById(
"downloadsRefresh"
)
?.addEventListener(
"click",
loadHistory
);
}

/* =========================================================
MEDIA CARD
========================================================= */

function renderMediaCard(item) {

const favorite =
isFavorite(item.job_id);

const title =
escapeHtml(
item.title || "Media"
);

const jobId =
escapeAttr(
item.job_id || ""
);

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
    <div class="media-card-placeholder">
      ${
        item.kind === "audio"
          ? "♫"
          : "▶"
      }
    </div>
  `;

return `

<article class="media-card">

  <div
    class="media-card-thumb"
    data-play="${jobId}"
  >

    ${thumbnail}

  </div>


  <div class="media-card-body">

    <div
      class="media-card-title"
      title="${title}"
    >
      ${title}
    </div>


    <div class="media-card-meta">

      ${escapeHtml(
        item.kind || "video"
      )}

      ·

      ${formatTime(
        item.created_at
      )}

    </div>


    <div class="media-card-actions">

      ${
        item.download_url

          ? `
            <a
              href="${escapeAttr(item.download_url)}"
              download
            >
              Save
            </a>
          `

          : ""
      }


      <button
        type="button"
        class="${
          favorite
            ? "fav-active"
            : ""
        }"
        data-favorite="${jobId}"
      >

        ${
          favorite
            ? "♥ Saved"
            : "♡ Favorite"
        }

      </button>

    </div>

  </div>

</article>

`;
}

/* =========================================================
MEDIA ACTIONS
========================================================= */

function bindMediaActions(
container
) {

if (!container) return;

container
.querySelectorAll(
"[data-play]"
)
.forEach(element => {

  element.addEventListener(
    "click",
    () => {

      const item =
        historyItems.find(
          x =>
            x.job_id ===
            element.dataset.play
        );


      if (
        item &&
        item.download_url
      ) {

        playMedia(
          item.download_url,
          item.title
        );

      }

    }
  );

});

container
.querySelectorAll(
"[data-favorite]"
)
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
DOWNLOADS PAGE
========================================================= */

function renderDownloads() {

const list =
document.getElementById(
"downloadsList"
);

if (!list) return;

const items =
historyItems.filter(
item =>
item.status ===
"completed" &&
item.download_url
);

if (!items.length) {

list.innerHTML = `

  <div class="view-empty">

    No downloads yet.

    <br>

    Download a video or MP3
    from Home and it will
    appear here.

  </div>

`;

return;

}

list.innerHTML =
items
.map(renderMediaCard)
.join("");

bindMediaActions(list);
}

/* =========================================================
FAVORITES PAGE
========================================================= */

function renderFavorites() {

const list =
document.getElementById(
"favoritesList"
);

if (!list) return;

const favorites =
getFavorites().filter(
item =>
item &&
item.download_url
);

if (!favorites.length) {

list.innerHTML = `

  <div class="view-empty">

    No favorites yet.

    <br>

    Tap ♡ Favorite on
    any completed download.

  </div>

`;

return;

}

list.innerHTML =
favorites
.map(renderMediaCard)
.join("");

bindMediaActions(list);
}

/* =========================================================
HISTORY PAGE
========================================================= */

function renderHistory() {

if (!historyList) return;

if (!historyItems.length) {

historyList.innerHTML = `

  <div class="empty">

    Your downloads
    will appear here.

  </div>

`;

return;

}

historyList.innerHTML =
historyItems
.map(item => `

    <div
      class="history-item"
      style="
        display:flex;
        align-items:center;
        gap:12px;
        background:rgba(22,27,34,.6);
        padding:12px;
        border-radius:12px;
        margin-bottom:10px;
        border:1px solid rgba(255,255,255,.08);
      "
    >

      ${
        item.thumbnail

          ? `
            <img
              src="${escapeAttr(item.thumbnail)}"
              alt=""
              style="
                width:50px;
                height:70px;
                object-fit:cover;
                border-radius:8px;
                cursor:pointer;
              "
              data-history-play="${escapeAttr(item.job_id)}"
            >
          `

          : `
            <div
              style="
                width:50px;
                height:70px;
                background:#21262d;
                border-radius:8px;
                display:flex;
                align-items:center;
                justify-content:center;
                font-size:18px;
                cursor:pointer;
              "
              data-history-play="${escapeAttr(item.job_id)}"
            >
              ${
                item.kind === "audio"
                  ? "♫"
                  : "▶"
              }
            </div>
          `
      }


      <div
        style="
          flex-grow:1;
          overflow:hidden;
        "
      >

        <a
          href="${escapeAttr(item.url)}"
          target="_blank"
          rel="noopener noreferrer"
          style="
            color:#58a6ff;
            font-size:11px;
            text-decoration:none;
            display:block;
            white-space:nowrap;
            overflow:hidden;
            text-overflow:ellipsis;
          "
        >
          ${escapeHtml(item.url)}
        </a>


        <div
          data-history-play="${escapeAttr(item.job_id)}"
          style="
            color:#f0f6fc;
            font-size:13px;
            font-weight:500;
            margin:4px 0;
            white-space:nowrap;
            overflow:hidden;
            text-overflow:ellipsis;
            cursor:pointer;
          "
        >
          ${escapeHtml(item.title)}
        </div>


        <div
          style="
            color:#8b949e;
            font-size:11px;
          "
        >
          ${formatTime(item.created_at)}
          ·
          ${escapeHtml(item.status)}
        </div>

      </div>


      <div
        style="
          display:flex;
          gap:5px;
          flex-wrap:wrap;
          justify-content:flex-end;
        "
      >

        ${
          item.download_url

            ? `
              <a
                href="${escapeAttr(item.download_url)}"
                download
                style="
                  background:#238636;
                  color:white;
                  padding:6px 12px;
                  border-radius:6px;
                  text-decoration:none;
                  font-size:12px;
                  font-weight:bold;
                "
              >
                Save
              </a>
            `

            : ""
        }


        ${
          item.status ===
          "completed"

            ? `
              <button
                type="button"
                data-history-fav="${escapeAttr(item.job_id)}"
                style="
                  background:rgba(255,255,255,.06);
                  color:${
                    isFavorite(item.job_id)
                      ? "#ff68d7"
                      : "#aaa"
                  };
                  border:0;
                  padding:6px 10px;
                  border-radius:6px;
                  cursor:pointer;
                "
              >
                ${
                  isFavorite(
                    item.job_id
                  )
                    ? "♥"
                    : "♡"
                }
              </button>
            `

            : ""
        }

      </div>

    </div>

  `)
  .join("");

historyList
.querySelectorAll(
"[data-history-play]"
)
.forEach(element => {

  element.addEventListener(
    "click",
    () => {

      const item =
        historyItems.find(
          x =>
            x.job_id ===
            element.dataset.historyPlay
        );


      if (
        item &&
        item.download_url
      ) {

        playMedia(
          item.download_url,
          item.title
        );

      }

    }
  );

});

historyList
.querySelectorAll(
"[data-history-fav]"
)
.forEach(button => {

  button.addEventListener(
    "click",
    event => {

      event.stopPropagation();

      toggleFavorite(
        button.dataset.historyFav
      );

    }
  );

});

}

/* =========================================================
LOAD HISTORY FROM BACKEND
========================================================= */

async function loadHistory() {

try {

const response =
  await fetch(
    "/api/history",
    {
      credentials:
        "same-origin"
    }
  );


if (!response.ok) {
  throw new Error(
    "History request failed"
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
    historyItems.length;

}


renderHistory();
renderDownloads();
renderFavorites();

} catch {

historyItems = [];


if (historyCount) {
  historyCount.textContent = "0";
}


if (historyList) {

  historyList.innerHTML = `
    <div class="empty">
      History is temporarily unavailable.
    </div>
  `;

}


renderDownloads();
renderFavorites();

}
}

/* =========================================================
VIDEO PLAYER
========================================================= */

window.playMedia =
function(url, title) {

if (
  !url ||
  !modalVideo ||
  !playerModal
) {
  return;
}


modalVideo.src = url;


if (modalTitle) {
  modalTitle.textContent =
    title || "Media";
}


playerModal.style.display =
  "flex";


modalVideo
  .play()
  .catch(() => {});

};

closeModal?.addEventListener(
"click",
() => {

modalVideo.pause();

modalVideo.removeAttribute(
  "src"
);

modalVideo.load();

playerModal.style.display =
  "none";

}
);

playerModal?.addEventListener(
"click",
event => {

if (
  event.target ===
  playerModal
) {

  closeModal?.click();

}

}
);

document.addEventListener(
"keydown",
event => {

if (
  event.key === "Escape" &&
  playerModal?.style.display ===
    "flex"
) {

  closeModal?.click();

}

}
);

/* =========================================================
INPUT
========================================================= */

urlInput?.addEventListener(
"input",
() => {

if (clearBtn) {

  clearBtn.hidden =
    !urlInput.value;

}

}
);

clearBtn?.addEventListener(
"click",
() => {

urlInput.value = "";

clearBtn.hidden = true;

urlInput.focus();

}
);

/* =========================================================
DOWNLOAD
========================================================= */

downloadBtn?.addEventListener(
"click",
async () => {

const url =
  urlInput.value.trim();


if (!url) {

  status(
    "Paste a public media link first.",
    "error"
  );

  urlInput.focus();

  return;
}


downloadBtn.disabled = true;

downloadBtn.innerHTML =
  "<span>Starting…</span><b>•</b>";


status(
  "Checking the link…"
);


if (previewCard) {

  previewCard.style.display =
    "none";

}


try {

  const response =
    await fetch(
      "/api/download",
      {
        method: "POST",
        credentials:
          "same-origin",
        headers: {
          "Content-Type":
            "application/json"
        },
        body: JSON.stringify({
          url,
          kind:
            kind.value
        })
      }
    );


  const data =
    await response.json();


  if (!response.ok) {

    throw new Error(
      data.detail ||
      "Could not start download."
    );

  }


  await poll(
    data.job_id
  );

} catch (error) {

  status(
    error.message,
    "error"
  );


  downloadBtn.disabled =
    false;


  downloadBtn.innerHTML =
    "<span>Download</span><b>→</b>";
}

}
);

/* =========================================================
POLL DOWNLOAD
========================================================= */

async function poll(jobId) {

for (
let i = 0;
i < 180;
i++
) {

await new Promise(
  resolve =>
    setTimeout(
      resolve,
      1500
    )
);


const response =
  await fetch(
    `/api/download/${encodeURIComponent(jobId)}`,
    {
      credentials:
        "same-origin"
    }
  );


if (!response.ok) {

  throw new Error(
    "Download job was lost."
  );

}


const data =
  await response.json();


if (
  data.status ===
  "completed"
) {

  status(
    `Ready — ${data.title}`,
    "success"
  );


  if (data.download_url) {

    if (
      videoPreview &&
      data.kind ===
        "video"
    ) {

      videoPreview.src =
        data.download_url;

    }


    if (previewMeta) {

      previewMeta.innerHTML = `

        <div
          style="
            color:#fff;
            font-weight:600;
            margin-bottom:8px;
            font-size:14px;
          "
        >
          ${escapeHtml(
            data.title
          )}
        </div>


        <div
          style="
            display:flex;
            gap:8px;
          "
        >

          <a
            href="${escapeAttr(
              data.download_url
            )}"
            download
            style="
              display:block;
              flex:1;
              text-align:center;
              text-decoration:none;
              background:#238636;
              color:#fff;
              padding:10px;
              border-radius:8px;
              font-weight:bold;
            "
          >
            Save
          </a>


          <button
            type="button"
            id="newFavoriteBtn"
            style="
              background:rgba(255,255,255,.07);
              color:#fff;
              border:0;
              padding:10px 14px;
              border-radius:8px;
              cursor:pointer;
            "
          >
            ♡ Favorite
          </button>

        </div>

      `;


      document
        .getElementById(
          "newFavoriteBtn"
        )
        ?.addEventListener(
          "click",
          () => {

            const item =
              historyItems.find(
                x =>
                  x.job_id ===
                  data.job_id
              );


            if (item) {

              toggleFavorite(
                item.job_id
              );

            } else {

              status(
                "Open History and save this download to Favorites.",
                "error"
              );

            }

          }
        );

    }


    if (previewCard) {

      previewCard.style.display =
        "block";

    }


    if (
      data.kind ===
      "video"
    ) {

      videoPreview
        ?.play()
        .catch(() => {});

    }


    const link =
      document.createElement(
        "a"
      );


    link.href =
      data.download_url;

    link.download = "";

    document.body.appendChild(
      link
    );

    link.click();

    link.remove();

  }


  downloadBtn.disabled =
    false;


  downloadBtn.innerHTML =
    "<span>Download</span><b>→</b>";


  await loadHistory();

  return;
}


if (
  data.status ===
  "failed"
) {

  throw new Error(
    data.error ||
    "Download failed."
  );

}


status(
  data.status ===
    "downloading"

    ? "Downloading your media…"

    : "Preparing your download…"
);

}

throw new Error(
"The download took too long. Please try again."
);
}

/* =========================================================
CLEAR HISTORY
========================================================= */

function bindClearHistory() {

const button =
document.getElementById(
"clearHistory"
);

if (
!button ||
button.dataset.bound === "1"
) {
return;
}

button.dataset.bound =
"1";

button.addEventListener(
"click",
async () => {

  if (
    !confirm(
      "Clear your download history?"
    )
  ) {
    return;
  }


  try {

    const response =
      await fetch(
        "/api/history",
        {
          method: "DELETE",
          credentials:
            "same-origin"
        }
      );


    if (!response.ok) {

      throw new Error(
        "Could not clear history."
      );

    }


    historyItems = [];


    saveFavorites([]);


    if (historyCount) {

      historyCount.textContent =
        "0";

    }


    renderHistory();
    renderDownloads();
    renderFavorites();


    status(
      "History cleared.",
      "success"
    );

  } catch (error) {

    status(
      error.message,
      "error"
    );

  }

}

);
}

/* =========================================================
START APP
========================================================= */

createSections();

bindNavigation();

bindClearHistory();

setView("home");

loadHistory();
