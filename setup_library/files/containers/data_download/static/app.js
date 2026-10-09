"use strict";
const $ = id => document.getElementById(id);
const activeStates = new Set(["queued", "downloading", "verifying", "extracting"]);
let state = {catalog: [], jobs: [], sources: {}, storage: {}, internet: {status: "checking"}}, source = "maps", page = 0;
let selected = new Set(), visible = [], pollNumber = 0;
let restartBusy = false, restartError = "";
let uploadFiles = [], uploadBusy = false;
let uploadRestartPending = false;
const uploadDestinations = {music: "/Library/music", data: "/Library/library", ebooks: "/Library/calibre/put_new_books_here"};
const remindedDownloads = new Set();
const pageSize = 40;
const destinations = {routing: "/Library/maps/osm", maps: "/Library/maps/pmtiles", wiki: "/Library/wiki", survivor: "/Library/library"};
const hints = {
  routing: "US regional OpenStreetMap extracts from Geofabrik. MD5 and OSM headers are checked. Download first, then choose Use after restart below. Import needs additional disk space and RAM; start with a small region.",
  maps: "Regional PMTiles files. Git LFS map checksums are verified after download.",
  wiki: "Search a language code such as wikipedia_en_. Latest editions keeps the newest date for each variant.",
  survivor: "Category ZIPs only. PDFs are extracted into a category folder; the ZIP is then removed. Space is needed for both the ZIP and its PDFs."
};
function bytes(value) {
  if (value === null || value === undefined) return "Size checked on download";
  if (!value) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"], exponent = Math.min(4, Math.floor(Math.log(value) / Math.log(1024)));
  return (value / 1024 ** exponent).toFixed(exponent ? 1 : 0) + " " + units[exponent];
}
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function notice(message = "") { $("notice").textContent = message; $("notice").hidden = !message; }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-Library-Token": state.token}, body: JSON.stringify(body)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Request failed");
  return result;
}
function jobFor(row) { return state.jobs.find(job => job.id === row.id); }
function installed(row) { return row.installed || jobFor(row)?.status === "complete"; }
function renderInternet() {
  const offline = state.internet.status === "offline";
  $("internet-status").hidden = state.internet.status === "online";
  $("internet-message").textContent = state.internet.message || "Checking internet connection…";
  $("internet-message").className = offline ? "warning" : "";
  $("internet-detail").textContent = offline
    ? "Local uploads work offline. Checking again every 30 seconds; downloads will become available when the connection returns."
    : "Local uploads work without internet. Waiting for the Pi to connect before checking download sources.";
}
function eligible(row) {
  return state.internet.status === "online" && state.storage.ready && !installed(row) && !activeStates.has(jobFor(row)?.status)
    && (row.size == null || row.size <= state.storage.available);
}
function renderSources() {
  $("sources").replaceChildren();
  for (const info of Object.values(state.sources)) {
    const card = element("article", undefined, "source");
    const heading = element("h3", info.name);
    heading.append(element("span", info.status === "available" ? "●" : "◌", info.status === "available" ? "good" : "warning"));
    const status = {available: "Available", checking: "Checking…", partial: "Partially available", unavailable: "Unavailable · cached files may remain", cached: "Cached · checking on startup", waiting: "Waiting"};
    card.append(heading, element("p", `${status[info.status] || info.status} · ${info.count} files`));
    if (info.error) card.append(element("p", info.error, "warning"));
    const link = element("a", "Open source website ↗");
    link.href = info.url; link.target = "_blank"; link.rel = "noopener noreferrer";
    card.append(link); $("sources").append(card);
  }
  $("refresh").disabled = state.refreshing || state.internet.status !== "online";
  $("refresh").textContent = state.refreshing ? "Checking sources…" : "Refresh sources";
}
function renderStorage() {
  const disk = state.storage;
  $("storage-text").textContent = disk.ready ? `${bytes(disk.free)} free of ${bytes(disk.total)}` : disk.error || "Checking drive…";
  $("storage-meter").value = disk.ready ? disk.used / disk.total * 100 : 0;
  $("storage-detail").textContent = disk.ready ? `${bytes(disk.used)} used · ${bytes(disk.reserve)} kept free` : "Uploads and downloads need a writable, mounted drive.";
}
function filteredRows() {
  let rows = state.catalog.filter(row => row.source === source);
  if (source === "wiki" && $("latest").checked) {
    const latest = new Map();
    for (const row of rows) {
      const key = row.filename.replace(/_\d{4}-\d{2}\.zim$/, ".zim");
      if (!latest.has(key) || row.filename > latest.get(key).filename) latest.set(key, row);
    }
    rows = [...latest.values()];
  }
  const query = $("search").value.toLowerCase();
  return rows.filter(row => (row.title + " " + row.filename).toLowerCase().includes(query)
    && (!$("fits").checked || (state.storage.ready && row.size != null && row.size <= state.storage.available)));
}
function renderFiles() {
  const uploading = source === "upload";
  $("download-panel").hidden = uploading;
  $("upload-panel").hidden = !uploading;
  $("catalog-title").textContent = uploading ? "Upload files" : "Available downloads";
  $("count").hidden = uploading;
  if (uploading) {
    $("destination").textContent = "Add files from your device to the Library USB drive";
    return;
  }
  const rows = filteredRows(), pages = Math.max(1, Math.ceil(rows.length / pageSize));
  page = Math.min(page, pages - 1); visible = rows.slice(page * pageSize, (page + 1) * pageSize);
  $("files").replaceChildren();
  for (const row of visible) {
    const tr = element("tr"), checkCell = element("td"), check = element("input");
    check.type = "checkbox"; check.checked = selected.has(row.id); check.disabled = !eligible(row);
    check.setAttribute("aria-label", `Select ${row.title}`);
    check.addEventListener("change", () => { check.checked ? selected.add(row.id) : selected.delete(row.id); renderSelection(); });
    checkCell.append(check);
    const name = element("td", row.title);
    if (row.source === "survivor") name.append(element("small", row.filename + " → " + row.destination));
    const job = jobFor(row);
    const status = installed(row) ? "Already present" : activeStates.has(job?.status) ? job.status : row.size > state.storage.available ? "Too large" : "Ready";
    tr.append(checkCell, name, element("td", bytes(row.size)), element("td", status));
    $("files").append(tr);
  }
  if (!visible.length) {
    const tr = element("tr"), td = element("td", state.refreshing ? "Checking source listings… Files will appear as they are found." : "No matching files. Try another search or refresh the sources.", "empty");
    td.colSpan = 4; tr.append(td); $("files").append(tr);
  }
  $("count").textContent = `${rows.length} files`;
  $("page").textContent = `Page ${page + 1} of ${pages}`;
  $("previous").disabled = page === 0; $("next").disabled = page >= pages - 1;
  $("destination").textContent = `Saves to ${destinations[source]}`;
  $("source-hint").textContent = hints[source];
  $("latest-label").hidden = source !== "wiki";
  renderSelection();
}
function renderSelection() {
  const rows = state.catalog.filter(row => selected.has(row.id));
  const known = rows.reduce((sum, row) => sum + (row.size || 0), 0), unknown = rows.some(row => row.size == null);
  $("selected").textContent = rows.length ? `${rows.length} selected · ${bytes(known)}${unknown ? " + unknown sizes" : ""}` : "No files selected";
  $("download").disabled = !rows.length || state.internet.status !== "online" || !state.storage.ready || known > state.storage.available;
  const choices = visible.filter(eligible), checked = choices.filter(row => selected.has(row.id));
  $("select-page").checked = !!choices.length && checked.length === choices.length;
  $("select-page").indeterminate = checked.length > 0 && checked.length < choices.length;
  $("select-page").disabled = !choices.length;
}
function renderJobs() {
  $("jobs").replaceChildren();
  const count = state.jobs.filter(job => activeStates.has(job.status)).length;
  $("queue-count").textContent = `${count} active`;
  if (!state.jobs.length) $("jobs").append(element("p", "No downloads queued yet."));
  for (const job of [...state.jobs].reverse()) {
    const card = element("div", undefined, "job"), head = element("div", undefined, "job-head");
    head.append(element("strong", job.title));
    if (activeStates.has(job.status)) {
      const cancel = element("button", "Cancel", "secondary");
      cancel.addEventListener("click", async () => {
        try { await api("/api/cancel", {id: job.id}); cancel.disabled = true; cancel.textContent = "Cancelling…"; }
        catch (error) { notice(error.message); }
      }); head.append(cancel);
    }
    card.append(head);
    const extracting = job.status === "extracting", done = extracting ? job.extracted : job.downloaded, total = extracting ? job.extract_total : job.total;
    card.append(element("p", `${job.status} · ${bytes(done)}${total != null ? " / " + bytes(total) : ""} · /Library/${job.destination}`, job.status === "complete" ? "good" : ""));
    if (activeStates.has(job.status)) {
      const progress = element("progress"); progress.max = total || 1;
      if (total && job.status !== "verifying") progress.value = done || 0;
      progress.setAttribute("aria-label", `${job.title} ${job.status}`); card.append(progress);
    }
    if (job.error) card.append(element("p", job.error, "warning"));
    if (["failed", "cancelled"].includes(job.status)) {
      const retry = element("button", "Retry download", "secondary");
      retry.disabled = !state.storage.ready || state.internet.status !== "online";
      retry.addEventListener("click", () => download([job.id])); card.append(retry);
    }
    $("jobs").append(card);
  }
}
function renderRouting() {
  $("routing-panel").hidden = source !== "routing";
  const info = state.routing || {downloads: []};
  $("routing-status").textContent = info.error || (info.pending
    ? `Next restart: ${info.pending.title}. Shut down and restart to build directions.`
    : info.active ? `Selected region: ${info.active.title}. Directions become available after import finishes.`
    : "No region selected here yet. Existing manually installed routing is kept until you choose a replacement.");
  $("routing-downloads").replaceChildren();
  for (const row of info.downloads) {
    const line = element("div", undefined, "job-head");
    line.append(element("span", row.title));
    const button = element("button", info.pending?.filename === row.filename ? "Queued for restart" : "Use after restart", "secondary");
    button.disabled = !state.storage.ready || info.pending?.filename === row.filename;
    button.addEventListener("click", async () => {
      if (!confirm(`Use ${row.title} after the next shutdown and restart? This replaces the active routing region and rebuilds directions. The existing region continues working until restart.`)) return;
      try { await api("/api/routing", {filename: row.filename}); state.routing.pending = row; notice("Routing region selected. Shut down and restart the Library after downloads finish."); renderRouting(); }
      catch (error) { notice(error.message); }
    });
    line.append(button); $("routing-downloads").append(line);
  }
  if (!info.downloads.length) $("routing-downloads").append(element("p", "No verified routing downloads yet."));
  if (info.pending) {
    const cancel = element("button", "Cancel region change", "secondary");
    cancel.addEventListener("click", async () => {
      try { await api("/api/routing", {filename: null}); state.routing.pending = null; renderRouting(); }
      catch (error) { notice(error.message); }
    });
    $("routing-downloads").append(cancel);
  }
}
// Remind once per completed batch while this page is open, after the queue
// becomes idle. Failed/cancelled jobs alone must not trigger a restart reminder.
function showRestartReminder() {
  const dialog = $("restart-reminder");
  const active = state.jobs.filter(job => activeStates.has(job.status));
  $("restart-now").disabled = restartBusy || active.length > 0 || uploadBusy || state.upload_active || !state.restart?.available || state.restart?.requested;
  $("restart-status").textContent = restartError || (state.restart?.requested
    ? "Restart requested. Keep power connected and reload this page when the Library is back online."
    : restartBusy ? "Requesting a graceful restart…"
    : state.restart?.available ? "" : "Automatic restart is not installed. Use the Library's Shutdown option, then turn it back on after shutdown finishes.");
  for (const job of active) remindedDownloads.delete(job.id);
  if (active.length || uploadBusy || state.upload_active) {
    if (dialog.open) dialog.close();
    return;
  }
  const completed = state.jobs.filter(job => job.status === "complete" && !remindedDownloads.has(job.id));
  if ((!completed.length && !uploadRestartPending) || dialog.open || $("music-reminder").open) return;
  dialog.showModal();
  uploadRestartPending = false;
  for (const job of completed) remindedDownloads.add(job.id);
}
async function poll() {
  if (state.restart?.requested) return;
  try {
    const includeCatalog = pollNumber++ % 5 === 0 || state.refreshing;
    const fresh = await api(includeCatalog ? "/api/catalog" : "/api/state");
    if (state.restart?.requested) return;
    state = {...state, ...fresh};
    selected = new Set([...selected].filter(id => state.catalog.some(row => row.id === id && eligible(row))));
    renderInternet(); renderStorage(); renderSources(); renderFiles(); renderJobs(); renderRouting(); renderUpload();
    showRestartReminder();
  } catch (error) { if (!state.restart?.requested) notice("Cannot reach the downloader: " + error.message); }
  setTimeout(poll, 2500);
}
async function download(ids) {
  try { await api("/api/download", {ids}); selected.clear(); notice(); pollNumber = 0; renderSelection(); }
  catch (error) { notice(error.message); }
}
function uploadCategory() { return document.querySelector('[name="upload-category"]:checked').value; }
function renderUpload() {
  const total = uploadFiles.reduce((sum, file) => sum + file.size, 0);
  $("upload-destination").textContent = `Saves to ${uploadDestinations[uploadCategory()]}`;
  $("upload-selected").textContent = uploadFiles.length ? `${uploadFiles.length} files selected · ${bytes(total)}` : "No files selected";
  $("upload-controls").disabled = uploadBusy;
  $("upload-start").disabled = uploadBusy || state.upload_active || !uploadFiles.length || !state.storage.ready || state.restart?.requested || total > state.storage.available;
  $("upload-start").textContent = uploadBusy ? "Uploading…" : "Upload selected";
  $("upload-readiness").textContent = uploadBusy ? ""
    : state.restart?.requested ? "The Library is restarting. Wait for it to come back online."
    : !state.storage.ready ? state.storage.error || "Checking the USB drive…"
    : state.upload_active ? "Another upload is running. Wait for it to finish."
    : total > state.storage.available ? "The selected files exceed the available drive space. Choose fewer files."
    : "";
}
function selectUploads(input) {
  uploadFiles = [...input.files];
  $(input.id === "upload-files" ? "upload-folder" : "upload-files").value = "";
  $("upload-list").replaceChildren(...uploadFiles.slice(0, 100).map(file => element("li", `${file.webkitRelativePath || file.name} · ${bytes(file.size)}`)));
  if (uploadFiles.length > 100) $("upload-list").append(element("li", `And ${uploadFiles.length - 100} more files`));
  $("upload-status").textContent = "";
  $("upload-progress").hidden = true;
  renderUpload();
}
function sendUpload(file, category, completed, total, index, count) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    const path = file.webkitRelativePath || file.name;
    request.open("POST", "/api/upload?" + new URLSearchParams({category, path}));
    request.setRequestHeader("X-Library-Token", state.token);
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.upload.addEventListener("progress", event => {
      $("upload-progress").value = total ? (completed + event.loaded) / total * 100 : 0;
      $("upload-status").textContent = `${index + 1} of ${count}: Uploading ${path}…`;
    });
    request.upload.addEventListener("load", () => {
      $("upload-status").textContent = `${index + 1} of ${count}: Saving ${path}${/\.zip$/i.test(path) ? " and extracting ZIP" : ""}…`;
    });
    request.addEventListener("load", () => {
      let result;
      try { result = JSON.parse(request.responseText); }
      catch { reject(new Error("Unexpected server response. Check the destination before retrying.")); return; }
      if (request.status >= 200 && request.status < 300) resolve(result);
      else reject(new Error(result.error || "Upload failed"));
    });
    request.addEventListener("error", () => reject(new Error("Connection lost. Check the destination before retrying.")));
    request.send(file);
  });
}
$("upload-files").addEventListener("change", event => selectUploads(event.target));
$("upload-folder").addEventListener("change", event => selectUploads(event.target));
document.querySelectorAll('[name="upload-category"]').forEach(input => input.addEventListener("change", renderUpload));
$("upload-start").addEventListener("click", async () => {
  if (uploadBusy) return;
  const files = [...uploadFiles], category = uploadCategory();
  const total = files.reduce((sum, file) => sum + file.size, 0);
  let completed = 0, succeeded = 0;
  uploadBusy = true; renderUpload(); showRestartReminder(); notice();
  $("upload-progress").hidden = false; $("upload-progress").value = 0;
  try {
    for (let index = 0; index < files.length; index++) {
      $("upload-status").textContent = `${index + 1} of ${files.length}: Uploading ${files[index].webkitRelativePath || files[index].name}…`;
      await sendUpload(files[index], category, completed, total, index, files.length);
      completed += files[index].size; succeeded++;
    }
    $("upload-progress").value = 100;
    $("upload-status").textContent = `Uploaded ${succeeded} file${succeeded === 1 ? "" : "s"} to ${uploadDestinations[category]}.` + (files.some(file => /\.zip$/i.test(file.name)) ? " ZIP files were extracted and removed." : "");
    uploadFiles = [];
  } catch (error) {
    const failed = files[succeeded];
    $("upload-status").textContent = `${succeeded} of ${files.length} uploaded. Stopped at ${failed.webkitRelativePath || failed.name}: ${error.message} Completed files were kept. Select the remaining files to retry.`;
    uploadFiles = [];
  } finally {
    $("upload-files").value = ""; $("upload-folder").value = ""; $("upload-list").replaceChildren();
    uploadBusy = false; renderUpload(); pollNumber = 0;
    if (succeeded > 0) {
      if (category === "music") $("music-reminder").showModal();
      else uploadRestartPending = true;
      showRestartReminder();
    }
  }
});
$("music-reminder").addEventListener("close", showRestartReminder);
window.addEventListener("beforeunload", event => {
  if (uploadBusy) { event.preventDefault(); event.returnValue = ""; }
});
$("home").href = `${location.protocol}//${location.hostname.includes(":") ? "[" + location.hostname.replace(/[\[\]]/g, "") + "]" : location.hostname}/`;
document.querySelectorAll("[data-source]").forEach(button => button.addEventListener("click", () => {
  source = button.dataset.source; page = 0;
  document.querySelectorAll("[data-source]").forEach(tab => tab.setAttribute("aria-pressed", String(tab === button)));
  renderFiles(); renderRouting();
}));
for (const id of ["search", "fits", "latest"]) $(id).addEventListener("input", () => { page = 0; renderFiles(); });
$("previous").addEventListener("click", () => { page--; renderFiles(); });
$("next").addEventListener("click", () => { page++; renderFiles(); });
$("select-page").addEventListener("change", () => {
  visible.filter(eligible).forEach(row => $("select-page").checked ? selected.add(row.id) : selected.delete(row.id)); renderFiles();
});
$("restart-now").addEventListener("click", async () => {
  restartBusy = true; restartError = "";
  $("restart-now").disabled = true;
  $("restart-status").textContent = "Requesting a graceful restart…";
  try {
    await api("/api/restart", {});
    state.restart.requested = true;
    showRestartReminder();
  } catch (error) {
    restartError = error.message;
  } finally {
    restartBusy = false;
    showRestartReminder();
  }
});
$("download").addEventListener("click", () => download([...selected]));
$("refresh").addEventListener("click", async () => {
  try { await api("/api/refresh", {}); notice(); state.refreshing = true; pollNumber = 0; renderSources(); }
  catch (error) { notice(error.message); }
});
poll();
