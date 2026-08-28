const $ = (s) => document.querySelector(s);
const urlInput = $("#urlInput");
const clearBtn = $("#clearBtn");
const downloadBtn = $("#downloadBtn");
const kind = $("#kind");
const statusBox = $("#status");
const historyList = $("#historyList");
const historyCount = $("#historyCount");

urlInput.addEventListener("input", () => {
  clearBtn.hidden = !urlInput.value;
});

clearBtn.addEventListener("click", () => {
  urlInput.value = "";
  clearBtn.hidden = true;
  urlInput.focus();
});

function status(text, type="") {
  statusBox.textContent = text;
  statusBox.className = `status ${type}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
  }[c]));
}

function timeAgo(iso) {
  if (!iso) return "";
  const d = new Date(iso), s = Math.max(0, (Date.now() - d.getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s/60)}m ago`;
  if (s < 86400) return `${Math.floor(s/3600)}h ago`;
  return `${Math.floor(s/86400)}d ago`;
}

async function loadHistory() {
  try {
    const res = await fetch("/api/history");
    const data = await res.json();
    historyCount.textContent = data.items.length;
    if (!data.items.length) {
      historyList.innerHTML = '<div class="empty">Your downloads will appear here.</div>';
      return;
    }
    historyList.innerHTML = data.items.map(x => `
      <div class="history-item">
        <div class="history-icon">${x.kind === "audio" ? "♫" : "▶"}</div>
        <div class="history-info">
          <div class="history-title">${escapeHtml(x.title)}</div>
          <div class="history-meta">${escapeHtml(x.status)} · ${timeAgo(x.created_at)}</div>
        </div>
        ${x.download_url ? `<a class="history-action" href="${x.download_url}">Save →</a>` : ""}
      </div>
    `).join("");
  } catch {
    historyList.innerHTML = '<div class="empty">History is temporarily unavailable.</div>';
  }
}

async function poll(jobId) {
  for (let i = 0; i < 180; i++) {
    await new Promise(r => setTimeout(r, 1500));
    const res = await fetch(`/api/download/${jobId}`);
    if (!res.ok) throw new Error("Download job was lost.");
    const data = await res.json();

    if (data.status === "completed") {
      status(`Ready — ${data.title}`, "success");
      window.location.href = data.download_url;
      downloadBtn.disabled = false;
      downloadBtn.innerHTML = "<span>Download</span><b>→</b>";
      loadHistory();
      return;
    }
    if (data.status === "failed") {
      throw new Error(data.error || "Download failed.");
    }
    status(data.status === "downloading" ? "Downloading your media…" : "Preparing download…");
  }
  throw new Error("The download took too long. Please try again.");
}

downloadBtn.addEventListener("click", async () => {
  const url = urlInput.value.trim();
  if (!url) {
    status("Paste a public media link first.", "error");
    urlInput.focus();
    return;
  }

  downloadBtn.disabled = true;
  downloadBtn.innerHTML = "<span>Starting…</span><b>•</b>";
  status("Checking the link…");

  try {
    const res = await fetch("/api/download", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({url, kind: kind.value})
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not start download.");
    await poll(data.job_id);
  } catch (err) {
    status(err.message, "error");
    downloadBtn.disabled = false;
    downloadBtn.innerHTML = "<span>Download</span><b>→</b>";
  }
});

$("#historyBtn").addEventListener("click", () => {
  $("#historySection").scrollIntoView({behavior:"smooth"});
});

$("#clearHistory").addEventListener("click", async () => {
  if (!confirm("Clear your browser history?")) return;
  await fetch("/api/history", {method:"DELETE"});
  loadHistory();
});

loadHistory();
