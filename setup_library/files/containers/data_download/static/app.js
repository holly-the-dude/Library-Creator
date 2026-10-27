"use strict";
/**
 * Library downloader UI. DOM IDs are defined in index.html.
 * poll() fetches backend state; render functions turn that state into the UI.
 * Event handlers submit actions, and subsequent polls reconcile their results.
 * Downloads and clones run on the Pi; uploads stream from this browser and
 * require the page to stay open until the batch finishes.
 */
const $ = id => document.getElementById(id);
const activeStates = new Set(["queued", "downloading", "verifying", "extracting"]);
// Backend snapshot plus local navigation. State-only polls omit the catalog,
// so poll() merges responses to preserve the most recent catalog listing.
let state = {catalog: [], jobs: [], sources: {}, storage: {}, internet: {status: "checking"}}, source = "maps", page = 0;
// Selection spans pages and tabs; visible contains only the current page.
// These choices are local to this page and reset when it is reloaded.
let selected = new Set(), visible = [], pollNumber = 0;
// Local busy flags cover requests/batches in this browser. Backend flags such
// as state.upload_active also reflect work started by other browser sessions.
let restartBusy = false, restartError = "";
let uploadFiles = [], uploadBusy = false;
let uploadRestartPending = false;
// Scan results contain short-lived destination tokens, separate from the
// ongoing clone job in state.clone. Changing the source discards these results.
let cloneScan = null, cloneBusy = false, cloneError = "";
// Unknown host status also blocks conflicting actions until it is resolved.
function cloning() { return cloneBusy || ["running", "unknown"].includes(state.clone?.status); }
const uploadDestinations = {music: "/Library/music", data: "/Library/library", ebooks: "/Library/calibre/put_new_books_here"};
const remindedDownloads = new Set();
const pageSize = 40;
const destinations = {routing: "/Library/maps/osm", maps: "/Library/maps/pmtiles", wiki: "/Library/wiki", streetzim: "/Library/wiki", survivor: "/Library/library"};
const hints = {
  routing: "US regional OpenStreetMap extracts from Geofabrik. MD5 and OSM headers are checked. Download first, then choose Use after restart below. Import needs additional disk space and RAM; start with a small region.",
  maps: "Regional PMTiles files. Git LFS map checksums are verified after download.",
  streetzim: "Regional OpenStreetMap archives from StreetZim, hosted on Internet Archive. Exact size and MD5 are checked before publishing. After restarting the Library, open Maps → StreetZim. Included search, routing, terrain and imagery vary by region.",
  wiki: "Offline websites, encyclopedias, books, videos, and maps from Kiwix. ZIM files open in the Library's Wikipedia / Kiwix reader after restart. For StreetZim's regional maps, use the StreetZim maps tab.",
  survivor: "Category ZIPs only. PDFs are extracted into a category folder; the ZIP is then removed. Space is needed for both the ZIP and its PDFs."
};
// Binary units; a missing size means it is not known yet, rather than zero.
function bytes(value) {
  if (value === null || value === undefined) return "Size checked on download";
  if (!value) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"], exponent = Math.min(4, Math.floor(Math.log(value) / Math.log(1024)));
  return (value / 1024 ** exponent).toFixed(exponent ? 1 : 0) + " " + units[exponent];
}
// Use textContent for catalog titles, device names, and errors, never HTML.
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function notice(message = "") { $("notice").textContent = message; $("notice").hidden = !message; }
/**
 * GET when body is omitted; otherwise POST JSON with the latest server token.
 * Callers handle errors in the relevant panel. The token protects mutation
 * requests against cross-site requests; it is not a user login credential.
 */
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
// Preliminary selection check. Unknown sizes remain selectable; the backend
// performs the authoritative size, destination, and available-space checks.
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
  $("refresh").disabled = cloning() || state.refreshing || state.internet.status !== "online";
  $("refresh").textContent = state.refreshing ? "Checking sources…" : "Refresh sources";
}
function renderStorage() {
  const disk = state.storage;
  $("storage-text").textContent = disk.ready ? `${bytes(disk.free)} free of ${bytes(disk.total)}` : disk.error || "Checking drive…";
  $("storage-meter").value = disk.ready ? disk.used / disk.total * 100 : 0;
  $("storage-detail").textContent = disk.ready ? `${bytes(disk.used)} used · ${bytes(disk.reserve)} ` : "Uploads and downloads need a writable, mounted drive.";
}
const languageNames = typeof Intl.DisplayNames === "function" ? new Intl.DisplayNames(["en"], {type: "language"}) : null;
function languageName(code) {
  if (code === "mul") return "Multiple languages";
  if (code === "und") return "Unspecified language";
  try { return languageNames?.of(code) || code; } catch { return code; }
}
function rowLanguages(row) {
  // Old cached Wikipedia directory rows remain searchable until refreshed.
  return row.languages?.length ? row.languages : [row.filename.match(/^wikipedia_([a-z-]+)_/)?.[1] || "und"];
}
const collectionNames = {maps: "Maps (ZIM)", wikipedia: "Wikipedia", wikivoyage: "Travel guides (Wikivoyage)",
  wiktionary: "Dictionaries (Wiktionary)", gutenberg: "Books (Project Gutenberg)", stack_exchange: "Questions & answers (Stack Exchange)",
  videos: "Video collections", ted: "TED talks", devdocs: "Developer documentation", other: "Other collections",
  wikibooks: "Textbooks (Wikibooks)", wikisource: "Source texts (Wikisource)", wikiquote: "Quotations (Wikiquote)",
  wikiversity: "Learning resources (Wikiversity)", vikidia: "Children's encyclopedia (Vikidia)",
  phet: "Science simulations (PhET)", ifixit: "Repair guides (iFixit)", libretexts: "Textbooks (LibreTexts)",
  freecodecamp: "Coding lessons (freeCodeCamp)", mooc: "Online courses", zimit: "Archived websites"};
function collectionName(code) {
  return collectionNames[code] || code.replace(/[_-]/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}
function rowCategory(row) { return row.category || (row.filename.startsWith("wikipedia_") ? "wikipedia" : "other"); }
function renderZimFilters() {
  $("zim-filters").hidden = source !== "wiki";
  if (source !== "wiki") return;
  const rows = state.catalog.filter(row => row.source === "wiki");
  for (const [id, values, label, all] of [
    ["zim-language", new Set(["eng", ...rows.flatMap(rowLanguages)]), languageName, "All languages"],
    ["zim-category", new Set(rows.map(rowCategory)), collectionName, "All collections"]
  ]) {
    const select = $(id), current = select.value;
    // Keep the current choice while progressive catalog pages are arriving.
    if (current) values.add(current);
    const options = [["", all], ...[...values].map(value => [value, label(value)]).sort((a, b) => a[1].localeCompare(b[1]))];
    const signature = JSON.stringify(options);
    if (select.dataset.options === signature) continue;
    select.replaceChildren(...options.map(([value, text]) => {
      const option = element("option", text); option.value = value; return option;
    }));
    select.value = current; select.dataset.options = signature;
  }
}
function zimDetails(row) {
  const edition = {maxi: "Full articles with pictures", nopic: "Articles without pictures", mini: "Short introductory articles"}[row.flavour] || row.flavour;
  return [rowLanguages(row).map(languageName).join(", "), collectionName(rowCategory(row)), edition, row.date].filter(Boolean).join(" · ");
}
// Filter the current source before pagination. Wikipedia adds edition,
// language, and collection filters; search and available-space filters are shared.
function filteredRows() {
  let rows = state.catalog.filter(row => row.source === source);
  if (source === "wiki" && $("latest").checked) {
    const latest = new Map();
    for (const row of rows) {
      // Strip only the dated suffix so editions such as maxi/nopic stay distinct.
      const key = row.filename.replace(/_\d{4}-\d{2}\.zim$/, ".zim");
      if (!latest.has(key) || row.filename > latest.get(key).filename) latest.set(key, row);
    }
    rows = [...latest.values()];
  }
  const query = $("search").value.toLowerCase();
  return rows.filter(row => (source !== "wiki" || ((!$("zim-language").value || rowLanguages(row).some(code =>
      code === $("zim-language").value || languageName(code) === languageName($("zim-language").value)))
      && (!$("zim-category").value || rowCategory(row) === $("zim-category").value)))
    && [row.title, row.filename, row.description || "", row.features || "", ...(row.tags || []),
      ...(source === "wiki" ? [zimDetails(row)] : [])].join(" ").toLowerCase().includes(query)
    && (!$("fits").checked || (state.storage.ready && row.size != null && row.size <= state.storage.available)));
}
// Switch between catalog, upload, and clone panels, then render the current
// catalog page. Local uploads and cloning do not require an online catalog.
function renderFiles() {
  const uploading = source === "upload";
  const cloneTab = source === "clone";
  $("clone-panel").hidden = !cloneTab;
  $("download-panel").hidden = uploading || cloneTab;
  $("upload-panel").hidden = !uploading;
  $("catalog-title").textContent = uploading ? "Upload files" : "Available downloads";
  $("count").hidden = uploading || cloneTab;
  if (cloneTab) {
    $("catalog-title").textContent = "Clone";
    $("destination").textContent = "Copy the SD card or Library_USB to another drive";
    renderClone();
    return;
  }
  if (uploading) {
    $("destination").textContent = "Add files from your device to the Library USB drive";
    return;
  }
  renderZimFilters();
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
    if (row.source === "wiki") {
      if (row.description) name.append(element("p", row.description, "zim-description"));
      name.append(element("small", zimDetails(row)));
      const details = element("details"), summary = element("summary", "File details");
      details.append(summary, element("small", row.filename + " → /Library/" + row.destination));
      if (row.tags?.includes("_sw:yes")) details.append(element("small", "This archive uses a service worker and may need a compatible Kiwix reader."));
      name.append(details);
    }
    if (row.source === "survivor") name.append(element("small", row.filename + " → " + row.destination));
    if (row.source === "streetzim") {
      if (row.description) name.append(element("p", row.description, "zim-description"));
      name.append(element("small", [row.features, row.date].filter(Boolean).join(" · ")));
      const details = element("details"), summary = element("summary", "File details");
      details.append(summary, element("small", row.filename + " → /Library/" + row.destination));
      name.append(details);
    }
    const job = jobFor(row);
    const status = installed(row) ? "Already present" : activeStates.has(job?.status) ? job.status : row.size > state.storage.available ? "Too large" : "Ready";
    tr.append(checkCell, name, element("td", (row.size_is_approximate ? "≈ " : "") + bytes(row.size)), element("td", status));
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
// Totals include all selected pages; the header checkbox affects only visible
// eligible rows. Unknown sizes and ZIP expansion still need backend checks.
function renderSelection() {
  const rows = state.catalog.filter(row => selected.has(row.id));
  const known = rows.reduce((sum, row) => sum + (row.size || 0), 0), unknown = rows.some(row => row.size == null);
  $("selected").textContent = rows.length ? `${rows.length} selected · ${bytes(known)}${unknown ? " + unknown sizes" : ""}` : "No files selected";
  $("download").disabled = cloning() || !rows.length || state.internet.status !== "online" || !state.storage.ready || known > state.storage.available;
  const choices = visible.filter(eligible), checked = choices.filter(row => selected.has(row.id));
  $("select-page").checked = !!choices.length && checked.length === choices.length;
  $("select-page").indeterminate = checked.length > 0 && checked.length < choices.length;
  $("select-page").disabled = !choices.length;
}
// Newest jobs first. Download and extraction stages use separate byte totals;
// verification and stages without a known total show indeterminate progress.
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
// Choosing a routing region schedules its import for the next restart.
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
    button.disabled = cloning() || !state.storage.ready || info.pending?.filename === row.filename;
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
    cancel.disabled = cloning();
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
  $("restart-now").disabled = cloning() || restartBusy || active.length > 0 || uploadBusy || state.upload_active || !state.restart?.available || state.restart?.requested;
  $("restart-status").textContent = restartError || (state.restart?.requested
    ? "Restart requested. Keep power connected and reload this page when the Library is back online."
    : restartBusy ? "Requesting a graceful restart…"
    : state.restart?.available ? "" : "Automatic restart is not installed. Use the Library's Shutdown option, then turn it back on after shutdown finishes.");
  for (const job of active) remindedDownloads.delete(job.id);
  if (cloning() || active.length || uploadBusy || state.upload_active) {
    if (dialog.open) dialog.close();
    return;
  }
  const completed = state.jobs.filter(job => job.status === "complete" && !remindedDownloads.has(job.id));
  if ((!completed.length && !uploadRestartPending) || dialog.open || $("music-reminder").open) return;
  dialog.showModal();
  uploadRestartPending = false;
  for (const job of completed) remindedDownloads.add(job.id);
}
/**
 * Refresh status every 2.5 seconds after the previous request finishes, avoiding
 * overlapping polling requests. Fetch the larger catalog every fifth poll, or
 * on every poll while sources are refreshing. Prune selections that are no
 * longer eligible, then repaint. Stop polling after an accepted restart request.
 */
async function poll() {
  if (state.restart?.requested) return;
  try {
    const includeCatalog = pollNumber++ % 5 === 0 || state.refreshing;
    const fresh = await api(includeCatalog ? "/api/catalog" : "/api/state");
    if (state.restart?.requested) return;
    state = {...state, ...fresh};
    selected = new Set([...selected].filter(id => state.catalog.some(row => row.id === id && eligible(row))));
    renderInternet(); renderStorage(); renderSources(); renderFiles(); renderJobs(); renderRouting(); renderUpload(); renderClone();
    showRestartReminder();
  } catch (error) { if (!state.restart?.requested) notice("Cannot reach the downloader: " + error.message); }
  setTimeout(poll, 2500);
}
// Submit catalog IDs; the backend owns the download queue and source URLs.
async function download(ids) {
  try { await api("/api/download", {ids}); selected.clear(); notice(); pollNumber = 0; renderSelection(); }
  catch (error) { notice(error.message); }
}
function uploadCategory() { return document.querySelector('[name="upload-category"]:checked').value; }
/**
 * Show progress for the current host-reported stage, not an overall ETA.
 * Container stages count containers; copying stages estimate bytes per
 * filesystem (SD root and boot are separate). Only host completion means 100%.
 * Older helpers without phase/total fields can still show copied-byte text.
 */
function renderCloneProgress(info) {
  const panel = $("clone-progress-panel"), bar = $("clone-progress"), label = $("clone-progress-text");
  panel.hidden = !["running", "complete"].includes(info.status);
  bar.max = 100;
  bar.removeAttribute("value"); // Indeterminate while preparing, formatting or flushing.
  label.textContent = "Working…";
  bar.setAttribute("aria-label", info.message || "Clone progress");
  if (panel.hidden) return;
  if (info.status === "complete") {
    bar.value = 100;
    label.textContent = "Clone complete · 100%";
  } else if (["stopping", "restarting"].includes(info.phase)) {
    const done = info.containers_done || 0, total = info.containers_total;
    if (total != null) {
      bar.value = total > 0 ? Math.min(100, done / total * 100) : 100;
      label.textContent = `${done} of ${total} containers ${info.phase === "stopping" ? "stopped" : "restarted"}`;
    } else label.textContent = "Finding Library containers…";
  } else if (info.phase?.startsWith("copying_") || (!info.phase && info.copied != null)) {
    const copied = info.copied || 0, total = info.copy_total;
    // Used space includes allocation/metadata and may differ from rsync bytes.
    // Show an estimate per filesystem; completion waits for flush and cleanup.
    if (total > 0) {
      const percent = Math.min(99, Math.max(0, Math.floor(copied / total * 100)));
      bar.value = percent;
      label.textContent = `Copied ${bytes(copied)} of about ${bytes(total)} · ≈${percent}% of this stage`;
    } else label.textContent = `Copied ${bytes(copied)} in this stage`;
  } else if (info.phase === "finalizing") label.textContent = "Finishing writes and safely unmounting…";
  else if (info.phase === "formatting") label.textContent = "Preparing the destination…";
}
// Browser prompt() cannot style text. A modal dialog highlights the exact device
// while retaining typed confirmation; Cancel and Escape resolve without approval.
function confirmCloneDestination(target, sdClone) {
  const dialog = $("clone-confirm"), input = $("clone-confirm-input"), submit = $("clone-confirm-submit");
  $("clone-confirm-message").replaceChildren("Erase ALL data on ",
    element("strong", target.device, "clone-device"),
    ` (${target.model}, ${bytes(target.size)}) and clone the ${sdClone ? "SD card" : "Library_USB"}?`);
  $("clone-confirm-device").textContent = target.device;
  input.value = ""; submit.disabled = true; dialog.returnValue = "";
  return new Promise(resolve => {
    input.oninput = () => { submit.disabled = input.value !== target.device; };
    $("clone-confirm-form").onsubmit = event => {
      event.preventDefault();
      if (input.value === target.device) dialog.close("confirmed");
    };
    $("clone-confirm-cancel").onclick = () => dialog.close();
    dialog.addEventListener("close", () => {
      const confirmation = dialog.returnValue === "confirmed" && input.value === target.device ? input.value : null;
      input.oninput = null;
      $("clone-confirm-form").onsubmit = null;
      $("clone-confirm-cancel").onclick = null;
      resolve(confirmation);
    }, {once: true});
    dialog.showModal();
  });
}
// Combine the latest scan with host job status. Media eligibility and capacity
// are separate checks; the host revalidates the destination before erasing it.
function renderClone() {
  const info = state.clone || {};
  const transfers = uploadBusy || state.upload_active || state.refreshing || state.jobs.some(job => activeStates.has(job.status));
  $("clone-scan").disabled = cloning() || !info.available || state.restart?.requested;
  $("clone-source").disabled = cloning();
  $("clone-status").textContent = cloneError || (cloning() ? info.message || "Contacting clone service…" : transfers ? "Wait for transfers and source refresh to finish before cloning." : info.message || "Checking host clone service…");
  renderCloneProgress(info);
  $("clone-capacity").textContent = cloneScan ? `Source: ${cloneScan.source.device} · Used: ${bytes(cloneScan.source.used)} · Destination needs at least ${bytes(cloneScan.source.required)} including filesystem overhead.` : "";
  $("clone-targets").replaceChildren();
  if (!cloneScan) return;
  if (!cloneScan.targets.length) $("clone-targets").append(element("p", cloneScan.source.kind === "sd"
    ? "No unused SD destination found. Insert an SD card in a USB reader and scan again. Mounted or in-use drives are not offered."
    : "No unused USB destination found. Insert a spare drive into the Pi and scan again. Mounted or in-use drives are not offered."));
  for (const target of cloneScan.targets) {
    const row = element("div", undefined, "clone-target");
    row.append(element("p", `${target.device} · ${target.model} · ${bytes(target.size)}${target.serial ? " · Serial: " + target.serial : ""}`));
    const sdClone = cloneScan.source.kind === "sd";
    // Unknown media is allowed only when the host explicitly supports user
    // verification. Missing fields from older helpers must not allow OS cloning.
    const needsVerification = sdClone && target.media === "unknown" && target.requires_sd_confirmation === true;
    const allowed = target.eligible !== false && (!sdClone || (target.eligible === true && (target.media === "sd" || needsVerification)));
    row.append(element("p", target.media === "sd" ? "SD card detected" : target.media === "other" ? "Other storage media" : "Media type unidentified"));
    if (needsVerification) row.append(element("p", "Cannot identify the media type. Before copying the operating system, you must verify that this destination is an SD card in a reader.", "warning"));
    if (!allowed) row.append(element("p", target.blocked_reason || "This destination has not been approved for OS cloning. Update the host clone service and scan again.", "warning"));
    const button = element("button", !allowed ? "SD card required" : target.fits ? "Erase and clone…" : "Too small");
    button.disabled = !allowed || !target.fits || cloning() || transfers || !info.available || state.restart?.requested;
    button.addEventListener("click", async () => {
      if (!allowed) return;
      // Confirm physical SD media and OS-copy intent first, then separately
      // require the device path to acknowledge erasing this exact destination.
      if (needsVerification && !confirm(`The Library cannot tell whether ${target.device} (${target.model}, ${bytes(target.size)}) is an SD card.

Verify that this destination is an SD card in a reader, not a USB stick, and that you intend to copy the Library OPERATING SYSTEM to it. All existing data on this destination will be erased.

Have you verified the SD card and want to continue with the OS copy?`)) return;
      // Keep scans and other actions disabled while the asynchronous dialog is open.
      cloneBusy = true; cloneError = ""; renderClone();
      try {
        const confirmation = await confirmCloneDestination(target, sdClone);
        if (confirmation !== target.device) return;
        const result = await api("/api/clone/start", {token: target.token, confirmation,
          ...(needsVerification ? {sd_confirmed: true} : {})});
        // The job was accepted, not completed. Discard the consumed scan token;
        // subsequent polls track the host's background work.
        state.clone = {available: true, ...result}; cloneScan = null;
      } catch (error) { cloneError = error.message; }
      finally { cloneBusy = false; renderClone(); showRestartReminder(); }
    });
    row.append(button); $("clone-targets").append(row);
  }
}
$("clone-source").addEventListener("change", () => { cloneScan = null; cloneError = ""; renderClone(); });
$("clone-scan").addEventListener("click", async () => {
  cloneBusy = true; cloneError = ""; cloneScan = null; renderClone();
  try { cloneScan = await api("/api/clone/scan", {source: $("clone-source").value}); }
  catch (error) { cloneError = error.message; }
  finally { cloneBusy = false; renderClone(); }
});

// Selected bytes exclude ZIP expansion; the server also checks space while
// saving/extracting. Controls account for both local and other-client uploads.
function renderUpload() {
  const total = uploadFiles.reduce((sum, file) => sum + file.size, 0);
  $("upload-destination").textContent = `Saves to ${uploadDestinations[uploadCategory()]}`;
  $("upload-selected").textContent = uploadFiles.length ? `${uploadFiles.length} files selected · ${bytes(total)}` : "No files selected";
  $("upload-controls").disabled = uploadBusy;
  $("upload-start").disabled = cloning() || uploadBusy || state.upload_active || !uploadFiles.length || !state.storage.ready || state.restart?.requested || total > state.storage.available;
  $("upload-start").textContent = uploadBusy ? "Uploading…" : "Upload selected";
  $("upload-readiness").textContent = uploadBusy ? ""
    : state.restart?.requested ? "The Library is restarting. Wait for it to come back online."
    : !state.storage.ready ? state.storage.error || "Checking the USB drive…"
    : state.upload_active ? "Another upload is running. Wait for it to finish."
    : total > state.storage.available ? "The selected files exceed the available drive space. Choose fewer files."
    : "";
}
// File and folder pickers replace each other. Folder uploads preserve relative
// paths; preview only the first 100 entries to keep large selections manageable.
function selectUploads(input) {
  uploadFiles = [...input.files];
  $(input.id === "upload-files" ? "upload-folder" : "upload-files").value = "";
  $("upload-list").replaceChildren(...uploadFiles.slice(0, 100).map(file => element("li", `${file.webkitRelativePath || file.name} · ${bytes(file.size)}`)));
  if (uploadFiles.length > 100) $("upload-list").append(element("li", `And ${uploadFiles.length - 100} more files`));
  $("upload-status").textContent = "";
  $("upload-progress").hidden = true;
  renderUpload();
}
/**
 * Use XHR for upload progress events. completed/total are batch byte counts;
 * index/count identify this file within the batch.
 * Sending all bytes is not completion: wait for the server to save/extract the
 * file and return its response before resolving and starting the next file.
 */
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
// Capture a fixed batch/category and upload sequentially. Stop on the first
// failure; successful files stay saved and still trigger the relevant reminder.
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
// Only uploads depend on this tab staying open; downloads/clones run on the Pi.
window.addEventListener("beforeunload", event => {
  if (uploadBusy) { event.preventDefault(); event.returnValue = ""; }
});
// Return to the Library on this host's default web port, including IPv6 hosts.
$("home").href = `${location.protocol}//${location.hostname.includes(":") ? "[" + location.hostname.replace(/[\[\]]/g, "") + "]" : location.hostname}/`;
// Navigation and filter changes reset pagination but preserve eligible selections.
document.querySelectorAll("[data-source]").forEach(button => button.addEventListener("click", () => {
  source = button.dataset.source; page = 0;
  document.querySelectorAll("[data-source]").forEach(tab => tab.setAttribute("aria-pressed", String(tab === button)));
  renderFiles(); renderRouting();
}));
for (const id of ["search", "fits", "latest", "zim-language", "zim-category"]) $(id).addEventListener("input", () => { page = 0; renderFiles(); });
$("previous").addEventListener("click", () => { page--; renderFiles(); });
$("next").addEventListener("click", () => { page++; renderFiles(); });
$("select-page").addEventListener("change", () => {
  visible.filter(eligible).forEach(row => $("select-page").checked ? selected.add(row.id) : selected.delete(row.id)); renderFiles();
});
// Mark restart requested only after the API accepts it. A rejected request
// leaves polling active and displays an error so the user can try again.
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
// Start polling after all event handlers are registered.

poll();
