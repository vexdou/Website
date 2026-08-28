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

function formatDateTime(iso) {
  if (!iso) return "";
  let isoFormatted = iso;
  if (isoFormatted && !isoFormatted.endsWith('Z') && !isoFormatted.includes('+') && !isoFormatted.includes('-', 10)) {
    isoFormatted += 'Z';
  }
  const date = new Date(isoFormatted);
  const now = new Date();
  const diffSeconds = Math.max(0, Math.floor((now - date) / 1000));

  if (diffSeconds < 60) return "Just now";
  if (diffSeconds < 3600) return `${Math.floor(diffSeconds/60)}m ago`;
  if (diffSeconds < 86400) {
    // Tus saacadda sida 02:58 PM
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  const diffDays = Math.floor(diffSeconds / 86400);
  if (diffDays <= 7) return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;
  
  const day = date.getDate();
  const month = date.getMonth() + 1;
  const year = date.getFullYear();
  return `${day}/${month}/${year}`;
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
      <div class="history-card" style="display: flex; align-items: center; gap: 12px; background: #161b22; padding: 12px; border-radius: 12px; margin-bottom: 10px; border: 1px solid #30363d;">
        ${x.thumbnail ? `<img src="${escapeHtml(x.thumbnail)}" style="width: 60px; height: 80px; object-fit: cover; border-radius: 8px;" alt="thumb">` : `<div style="width: 60px; height: 80px; background: #21262d; border-radius: 8px; display: flex; align-items: center; justify-content: center;">▶</div>`}
        <div style="flex-grow: 1; overflow: hidden;">
          <a href="${escapeHtml(x.url)}" target="_blank" style="color: #58a6ff; font-size: 12px; text-decoration: none; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(x.url)}</a>
          <div style="color: #f0f6fc; font-size: 14px; font-weight: 500; margin: 4px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(x.title)}</div>
          <div style="color: #8b949e; font-size: 12px;">${formatDateTime(x.created_at)}</div>
        </div>
        ${x.download_url ? `<a class="history-action" href="${x.download_url}" style="background: #238636; color: white; padding: 6px 12px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: bold;">Save →</a>` : ""}
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
    status(data.status === "downloading" ? "Downloading your media…" : "Downloading…");
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

  downloadBtn.disabled = false;
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
