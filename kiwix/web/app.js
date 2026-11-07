"use strict";

const STRINGS = {
  en: {
    running: "Server running",
    stopped: "Server stopped – download something to get started",
    free: "free",
    open: "Open Kiwix",
    direct: "Direct link (port 8080)",
    downloading: "Downloading",
    library: "Your library",
    libraryEmpty: "Nothing installed yet. Pick something from the catalog below.",
    catalog: "Catalog",
    searchPlaceholder: "Search the catalog…",
    search: "Search",
    more: "Show more",
    noResults: "No results.",
    allLanguages: "All languages",
    allCategories: "All categories",
    download: "Download",
    installed: "Installed",
    queued: "Queued",
    cancel: "Cancel",
    dismiss: "Dismiss",
    remove: "Delete",
    confirmDelete: "Delete {file}?",
    articles: "articles",
    flavour: { nopic: "No images", mini: "Intro only", maxi: "Complete" },
    catalogError: "Could not reach the Kiwix catalog.",
  },
  da: {
    running: "Serveren kører",
    stopped: "Serveren er stoppet – hent noget for at komme i gang",
    free: "ledig",
    open: "Åbn Kiwix",
    direct: "Direkte link (port 8080)",
    downloading: "Henter",
    library: "Dit bibliotek",
    libraryEmpty: "Intet installeret endnu. Vælg noget i kataloget nedenfor.",
    catalog: "Katalog",
    searchPlaceholder: "Søg i kataloget…",
    search: "Søg",
    more: "Vis flere",
    noResults: "Ingen resultater.",
    allLanguages: "Alle sprog",
    allCategories: "Alle kategorier",
    download: "Hent",
    installed: "Installeret",
    queued: "I kø",
    cancel: "Annuller",
    dismiss: "Luk",
    remove: "Slet",
    confirmDelete: "Slet {file}?",
    articles: "artikler",
    flavour: { nopic: "Uden billeder", mini: "Kun intro", maxi: "Komplet" },
    catalogError: "Kunne ikke nå Kiwix' katalog.",
  },
};

const LANGUAGES = [
  ["", "allLanguages"], ["dan", "Dansk"], ["eng", "English"], ["swe", "Svenska"],
  ["nob", "Norsk bokmål"], ["deu", "Deutsch"], ["fra", "Français"], ["spa", "Español"],
  ["nld", "Nederlands"], ["ita", "Italiano"],
];
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
const state = { library: [], downloads: [], nextStart: 0, total: 0 };

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
  for (const [select, options] of [[$("lang"), LANGUAGES], [$("category"), CATEGORIES]]) {
    for (const [value, label] of options) {
      select.append(el("option", { value, textContent: t[label] || label }));
    }
  }
  $("lang").value = uiLanguage === "da" ? "dan" : "eng";
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

  $("library-empty").hidden = state.library.length > 0;
  $("library").replaceChildren(...state.library.map(renderInstalled));
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
  return el(
    "li",
    { class: "item" },
    el("div", {}, el("div", { class: "title", textContent: item.file }),
      el("div", { class: "meta", textContent: formatSize(item.size) })),
    el("div", { class: "actions" },
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
  for (const item of $("results").children) {
    const current = resultState({ file: item.dataset.file });
    item._button.disabled = current !== "available";
    item._button.textContent = current === "installed" ? t.installed
      : current === "downloading" ? t.downloading : t.download;
  }
}

async function loadCatalog(append = false) {
  const start = append ? state.nextStart : 0;
  const params = new URLSearchParams({
    q: $("q").value.trim(),
    lang: $("lang").value,
    category: $("category").value,
    start,
  });
  $("results-message").textContent = "";
  try {
    const result = await api(`api/catalog?${params}`);
    const items = result.entries.map(renderResult);
    if (append) $("results").append(...items);
    else $("results").replaceChildren(...items);
    state.nextStart = start + result.entries.length;
    state.total = result.total;
    $("more").hidden = state.nextStart >= result.total || result.entries.length === 0;
    $("results-message").textContent = $("results").children.length ? "" : t.noResults;
    renderResultStates();
  } catch (error) {
    $("results-message").textContent = t.catalogError;
    $("more").hidden = true;
  }
}

// -- start ----------------------------------------------------------------
applyStaticText();
$("search").addEventListener("submit", (event) => {
  event.preventDefault();
  loadCatalog(false);
});
$("more").addEventListener("click", () => loadCatalog(true));

refresh().then(() => {
  schedulePolling();
  loadCatalog(false);
});
