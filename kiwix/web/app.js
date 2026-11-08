"use strict";

const STRINGS = {
  en: {
    running: "Server running",
    stopped: "Server stopped – download something to get started",
    free: "free",
    open: "Open Opslag",
    direct: "Direct link (port 8080)",
    downloading: "Downloading",
    library: "Your library",
    libraryEmpty: "Nothing installed yet. Pick something from the catalog below.",
    catalog: "Catalog",
    searchPlaceholder: "Search the catalog…",
    search: "Search",
    more: "Show more",
    noResults: "No results.",
    inEnglish: "In English",
    allCategories: "All categories",
    download: "Download",
    installed: "Installed",
    queued: "Queued",
    cancel: "Cancel",
    dismiss: "Dismiss",
    remove: "Delete",
    updates: "Updates",
    updateAvailable: "Update available",
    updateBtn: "Update ({size})",
    updateAll: "Update all",
    updating: "Updating…",
    autoUpdate: "Update automatically",
    autoUpdateHint: "New versions are downloaded when there is room, and the old one is deleted afterwards. Bookmarks move along.",
    checkNow: "Check now",
    checking: "Checking…",
    lastChecked: "Last checked {time}",
    neverChecked: "Not checked yet",
    upToDate: "Everything is up to date.",
    shown: "Shown on front page",
    hiddenLabel: "Hidden from front page",
    confirmDelete: "Delete {file}?",
    articles: "articles",
    flavour: { nopic: "No images", mini: "Intro only", maxi: "Complete" },
    catalogError: "Could not reach the Kiwix catalog.",
  },
  da: {
    running: "Serveren kører",
    stopped: "Serveren er stoppet – hent noget for at komme i gang",
    free: "ledig",
    open: "Åbn Opslag",
    direct: "Direkte link (port 8080)",
    downloading: "Henter",
    library: "Dit bibliotek",
    libraryEmpty: "Intet installeret endnu. Vælg noget i kataloget nedenfor.",
    catalog: "Katalog",
    searchPlaceholder: "Søg i kataloget…",
    search: "Søg",
    more: "Vis flere",
    noResults: "Ingen resultater.",
    inEnglish: "På engelsk",
    allCategories: "Alle kategorier",
    download: "Hent",
    installed: "Installeret",
    queued: "I kø",
    cancel: "Annuller",
    dismiss: "Luk",
    remove: "Slet",
    updates: "Opdateringer",
    updateAvailable: "Opdatering tilgængelig",
    updateBtn: "Opdatér ({size})",
    updateAll: "Opdatér alle",
    updating: "Opdaterer…",
    autoUpdate: "Opdatér automatisk",
    autoUpdateHint: "Nye versioner hentes, når der er plads, og den gamle slettes bagefter. Bogmærker følger med.",
    checkNow: "Tjek nu",
    checking: "Tjekker…",
    lastChecked: "Sidst tjekket {time}",
    neverChecked: "Endnu ikke tjekket",
    upToDate: "Alt er opdateret.",
    shown: "Vises på forsiden",
    hiddenLabel: "Skjult på forsiden",
    confirmDelete: "Slet {file}?",
    articles: "artikler",
    flavour: { nopic: "Uden billeder", mini: "Kun intro", maxi: "Komplet" },
    catalogError: "Kunne ikke nå Kiwix' katalog.",
  },
};

const CATEGORIES = [
  ["", "allCategories"], ["wikipedia", "Wikipedia"], ["wiktionary", "Wiktionary"],
  ["wikibooks", "Wikibooks"], ["wikisource", "Wikisource"], ["wikiquote", "Wikiquote"],
  ["wikivoyage", "Wikivoyage"], ["wikiversity", "Wikiversity"], ["gutenberg", "Gutenberg"],
  ["stack_exchange", "Stack Exchange"], ["ted", "TED"],
];

const uiLanguage = navigator.language.toLowerCase().startsWith("da") ? "da" : "en";
const t = STRINGS[uiLanguage];
document.documentElement.lang = uiLanguage;

const $ = (id) => document.getElementById(id);
const state = { library: [], downloads: [], updates: { items: [] }, nextStart: 0, total: 0 };

// -- helpers ------------------------------------------------------------
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node[key] = value;
  }
  node.append(...children.filter((child) => child !== null && child !== false));
  return node;
}

function formatSize(bytes) {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = value >= 100 || unit === 0 ? 0 : 1;
  return `${value.toLocaleString(uiLanguage, { maximumFractionDigits: digits })} ${units[unit]}`;
}

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}

const post = (path, payload) =>
  api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

function applyStaticText() {
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t[node.dataset.i18n];
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    node.placeholder = t[node.dataset.i18nPlaceholder];
  });
  for (const [value, label] of CATEGORIES) {
    $("category").append(el("option", { value, textContent: t[label] || label }));
  }
  $("category").value = "wikipedia";
}

// -- library & downloads --------------------------------------------------
function renderState() {
  $("status").textContent =
    `${state.running ? t.running : t.stopped} · ${formatSize(state.free)} ${t.free}`;

  // The reader opens inside Home Assistant when it is available through ingress;
  // otherwise fall back to the published port.
  const direct = `${location.protocol}//${location.hostname}:${state.port}/`;
  const open = $("open");
  open.hidden = !state.running;
  open.textContent = t.open;
  open.href = state.reader ? "reader/" : direct;
  open.target = state.reader ? "" : "_blank";

  const link = $("direct");
  link.hidden = !(state.running && state.reader);
  link.textContent = t.direct;
  link.href = direct;

  $("downloads-section").hidden = state.downloads.length === 0;
  $("downloads").replaceChildren(...state.downloads.map(renderDownload));

  renderUpdates();
  $("library-empty").hidden = state.library.length > 0;
  $("library").replaceChildren(...state.library.map(renderInstalled));
}

function updateFor(file) {
  return (state.updates.items || []).find((u) => u.file === file);
}

function updatePending(update) {
  return state.downloads.some((job) => job.file === update.new_file && job.status !== "error");
}

function renderUpdates() {
  const u = state.updates;
  const items = u.items || [];
  $("auto-update").checked = !!u.auto_update;
  $("check-now").disabled = !!u.checking;
  $("check-now").textContent = u.checking ? t.checking : t.checkNow;
  $("update-all").hidden = items.filter((i) => !updatePending(i)).length < 2;
  const when = u.checked
    ? t.lastChecked.replace("{time}", new Date(u.checked * 1000).toLocaleString(uiLanguage,
        { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }))
    : t.neverChecked;
  $("update-status").textContent = `${when}${u.checked && !items.length ? ` · ${t.upToDate}` : ""}`;
}

function renderDownload(job) {
  const failed = job.status === "error";
  const percent = job.total ? Math.floor((job.done / job.total) * 100) : 0;
  const detail = failed
    ? el("span", { class: "meta error", textContent: job.error })
    : el("span", {
        class: "meta",
        textContent: job.status === "queued"
          ? t.queued
          : `${formatSize(job.done)} / ${formatSize(job.total)} (${percent}%)`,
      });
  return el(
    "li",
    { class: "item" },
    el("div", {}, el("div", { class: "title", textContent: job.file }), detail),
    el("div", { class: "actions" },
      el("button", {
        class: "button",
        textContent: failed ? t.dismiss : t.cancel,
        onclick: () => post("api/cancel", { file: job.file }).then(refresh),
      })),
    failed ? null : el("progress", { max: job.total || 1, value: job.done }),
  );
}

function renderInstalled(item) {
  const update = updateFor(item.file);
  const pending = update && updatePending(update);
  return el(
    "li",
    { class: "item" },
    el("div", {}, el("div", { class: "title", textContent: item.file }),
      el("div", { class: "meta", textContent: formatSize(item.size) }),
      update ? el("div", { class: "meta update-note" },
        el("span", { class: "badge", textContent: t.updateAvailable }),
        ` ${update.new_file}`) : null),
    el("div", { class: "actions" },
      update ? el("button", {
        class: "button primary",
        disabled: pending,
        textContent: pending ? t.updating : t.updateBtn.replace("{size}", formatSize(update.size)),
        onclick: async (event) => {
          event.target.disabled = true;
          try { await post("api/update", { file: item.file }); } catch (error) { alert(error.message); }
          refresh();
        },
      }) : null,
      el("button", {
        class: "button",
        textContent: item.hidden ? t.hiddenLabel : t.shown,
        title: item.hidden ? t.hiddenLabel : t.shown,
        onclick: async () => {
          await post("api/visibility", { file: item.file, hidden: !item.hidden });
          refresh();
        },
      }),
      el("button", {
        class: "button danger",
        textContent: t.remove,
        onclick: async () => {
          if (!confirm(t.confirmDelete.replace("{file}", item.file))) return;
          await post("api/delete", { file: item.file });
          refresh();
        },
      })),
  );
}

async function refresh() {
  try {
    Object.assign(state, await api("api/state"));
    renderState();
    renderResultStates();
  } catch (error) {
    $("status").textContent = error.message;
  }
}

function schedulePolling() {
  const delay = state.downloads.length ? 1500 : 10000;
  setTimeout(async () => {
    await refresh();
    schedulePolling();
  }, delay);
}

// -- catalog --------------------------------------------------------------
function resultState(entry) {
  if (state.library.some((item) => item.file === entry.file)) return "installed";
  if (state.downloads.some((job) => job.file === entry.file && job.status !== "error")) {
    return "downloading";
  }
  return "available";
}

function renderResult(entry) {
  const flavour = t.flavour[entry.flavour] || entry.flavour;
  const meta = [
    entry.language,
    formatSize(entry.size),
    entry.articles ? `${entry.articles.toLocaleString(uiLanguage)} ${t.articles}` : "",
    entry.updated,
  ].filter(Boolean).join(" · ");

  const button = el("button", {
    class: "button primary",
    onclick: async () => {
      button.disabled = true;
      try {
        await post("api/download", { url: entry.url, size: entry.size });
      } catch (error) {
        alert(error.message);
      }
      refresh();
    },
  });
  const item = el(
    "li",
    { class: "item" },
    el("div", {},
      el("div", { class: "title" }, entry.title,
        flavour ? el("span", { class: "badge", textContent: flavour }) : null),
      el("div", { class: "meta", textContent: meta })),
    el("div", { class: "actions" }, button),
    entry.description ? el("div", { class: "desc", textContent: entry.description }) : null,
  );
  item.dataset.file = entry.file;
  item.dataset.url = entry.url;
  item._button = button;
  return item;
}

function renderResultStates() {
  for (const item of [...$("results").children, ...$("results-en").children]) {
    const current = resultState({ file: item.dataset.file });
    item._button.disabled = current !== "available";
    item._button.textContent = current === "installed" ? t.installed
      : current === "downloading" ? t.downloading : t.download;
  }
}

// Results come in your own language first, with English below it.
const GROUPS = [
  { lang: uiLanguage === "da" ? "dan" : "eng", list: "results", more: "more", message: "results-message", next: 0 },
  ...(uiLanguage === "da"
    ? [{ lang: "eng", list: "results-en", more: "more-en", message: "results-en-message", next: 0 }]
    : []),
];

async function loadGroup(group, append) {
  const start = append ? group.next : 0;
  const params = new URLSearchParams({
    q: $("q").value.trim(),
    lang: group.lang,
    category: $("category").value,
    start,
  });
  $(group.message).textContent = "";
  try {
    const result = await api(`api/catalog?${params}`);
    const items = result.entries.map(renderResult);
    if (append) $(group.list).append(...items);
    else $(group.list).replaceChildren(...items);
    group.next = start + result.entries.length;
    $(group.more).hidden = group.next >= result.total || result.entries.length === 0;
    $(group.message).textContent = $(group.list).children.length ? "" : t.noResults;
  } catch (error) {
    $(group.message).textContent = t.catalogError;
    $(group.more).hidden = true;
  }
}

async function loadCatalog() {
  await Promise.all(GROUPS.map((group) => loadGroup(group, false)));
  renderResultStates();
}

// -- start ----------------------------------------------------------------
applyStaticText();
$("search").addEventListener("submit", (event) => {
  event.preventDefault();
  loadCatalog();
});
for (const group of GROUPS) {
  $(group.more).addEventListener("click", async () => {
    await loadGroup(group, true);
    renderResultStates();
  });
}
$("results-en-title").hidden = GROUPS.length < 2;
$("results-en-title").textContent = t.inEnglish;
$("auto-update").addEventListener("change", async (event) => {
  await post("api/auto-update", { enabled: event.target.checked });
  refresh();
});
$("check-now").addEventListener("click", async () => {
  $("check-now").disabled = true;
  await post("api/update-check", {});
  // The check runs in the background; poll until it has finished.
  for (let i = 0; i < 40; i++) {
    await new Promise((r) => setTimeout(r, 1500));
    await refresh();
    if (!state.updates.checking) break;
  }
});
$("update-all").addEventListener("click", async () => {
  await post("api/update-all", {});
  refresh();
});

refresh().then(() => {
  schedulePolling();
  loadCatalog();
});
