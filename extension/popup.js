"use strict";

const DEFAULT_BASE_URL = "http://localhost:8010";

const state = {
  baseUrl: DEFAULT_BASE_URL,
  apiToken: "",
  categories: [],
  selectedCategories: new Set(),
};

const elements = {
  form: document.getElementById("bookmarkForm"),
  sourceUrl: document.getElementById("sourceUrl"),
  title: document.getElementById("title"),
  categoryList: document.getElementById("categoryList"),
  selectedCategories: document.getElementById("selectedCategories"),
  newCategory: document.getElementById("newCategory"),
  addCategory: document.getElementById("addCategory"),
  tags: document.getElementById("tags"),
  mode: document.getElementById("mode"),
  visibility: document.getElementById("visibility"),
  saveButton: document.getElementById("saveButton"),
  openOptions: document.getElementById("openOptions"),
  status: document.getElementById("status"),
};

document.addEventListener("DOMContentLoaded", init);
elements.form.addEventListener("submit", saveBookmark);
elements.addCategory.addEventListener("click", createCategory);
elements.openOptions.addEventListener("click", openOptions);

async function init() {
  setBusy(true);
  setStatus("Loading...");

  try {
    await loadSettings();
    await loadCurrentTab();

    if (!state.apiToken) {
      setStatus("Missing API token. Open options.", "error");
      return;
    }

    await loadCategories();
    setStatus("");
  } catch (error) {
    setStatus(error.message || "Cannot initialize popup.", "error");
  } finally {
    setBusy(false);
  }
}

async function loadSettings() {
  const settings = await storageGet({
    baseUrl: DEFAULT_BASE_URL,
    apiToken: "",
  });
  state.baseUrl = normalizeBaseUrl(settings.baseUrl || DEFAULT_BASE_URL);
  state.apiToken = settings.apiToken || "";
}

async function loadCurrentTab() {
  const tabs = await tabsQuery({ active: true, currentWindow: true });
  const tab = tabs[0];
  if (!tab) {
    throw new Error("Could not read the active tab.");
  }

  elements.sourceUrl.value = tab.url || "";
  elements.title.value = tab.title || "";
}

async function loadCategories() {
  const data = await apiFetch("/api/categories");
  state.categories = (data.items || []).slice().sort(compareByName);
  renderCategories();
}

async function createCategory() {
  const name = cleanCategoryName(elements.newCategory.value);
  if (!name) {
    return;
  }

  elements.addCategory.disabled = true;
  try {
    const category = await apiFetch("/api/categories", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    upsertCategory(category);
    state.selectedCategories.add(category.name);
    elements.newCategory.value = "";
    renderCategories();
    setStatus("Category added.", "success");
  } catch (error) {
    setStatus(error.message || "Could not create category.", "error");
  } finally {
    elements.addCategory.disabled = false;
  }
}

async function saveBookmark(event) {
  event.preventDefault();

  const sourceUrl = elements.sourceUrl.value.trim();
  if (!isHttpUrl(sourceUrl)) {
    setStatus("Only http and https URLs can be saved.", "error");
    return;
  }

  const categories = Array.from(state.selectedCategories);
  const pendingCategory = cleanCategoryName(elements.newCategory.value);
  if (pendingCategory && !categories.includes(pendingCategory)) {
    categories.push(pendingCategory);
  }

  setBusy(true);
  setStatus("Saving...");

  try {
    const data = await apiFetch("/api/bookmarks", {
      method: "POST",
      body: JSON.stringify({
        source_url: sourceUrl,
        title: cleanTitle(elements.title.value),
        categories,
        tags: splitCommaList(elements.tags.value),
        create_missing_categories: true,
        mode: elements.mode.value,
        visibility: elements.visibility.value,
      }),
    });

    if (data.duplicate) {
      setStatus("Already saved.", "success");
    } else if (elements.mode.value === "bookmark_only") {
      setStatus("Saved as bookmark only.", "success");
    } else {
      setStatus("Saved. Download started.", "success");
    }
  } catch (error) {
    setStatus(error.message || "Cannot reach Bookmarks API.", "error");
  } finally {
    setBusy(false);
  }
}

async function apiFetch(path, options = {}) {
  if (!state.apiToken) {
    throw new Error("Missing API token. Open options.");
  }

  let response;
  try {
    response = await fetch(`${state.baseUrl}${path}`, {
      method: options.method || "GET",
      headers: {
        Authorization: `Bearer ${state.apiToken}`,
        "Content-Type": "application/json",
      },
      body: options.body,
    });
  } catch (error) {
    throw new Error("Cannot reach Bookmarks API.");
  }

  const data = await readJson(response);
  if (!response.ok) {
    if (response.status === 401) {
      throw new Error("Login token rejected.");
    }
    throw new Error(responseMessage(data, response.status));
  }
  return data || {};
}

function renderCategories() {
  elements.categoryList.replaceChildren();

  if (state.categories.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No categories yet.";
    elements.categoryList.append(empty);
  }

  for (const category of state.categories) {
    const label = document.createElement("label");
    label.className = "checkbox-row";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selectedCategories.has(category.name);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        state.selectedCategories.add(category.name);
      } else {
        state.selectedCategories.delete(category.name);
      }
      renderSelectedCategories();
    });

    const text = document.createElement("span");
    text.textContent = category.name;

    label.append(checkbox, text);
    elements.categoryList.append(label);
  }

  renderSelectedCategories();
}

function renderSelectedCategories() {
  elements.selectedCategories.replaceChildren();

  for (const name of state.selectedCategories) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = `${name} x`;
    chip.addEventListener("click", () => {
      state.selectedCategories.delete(name);
      renderCategories();
    });
    elements.selectedCategories.append(chip);
  }
}

function upsertCategory(category) {
  const existingIndex = state.categories.findIndex((item) => item.id === category.id);
  if (existingIndex >= 0) {
    state.categories[existingIndex] = category;
  } else {
    state.categories.push(category);
  }
  state.categories.sort(compareByName);
}

function storageGet(defaults) {
  return new Promise((resolve) => {
    chrome.storage.sync.get(defaults, resolve);
  });
}

function tabsQuery(queryInfo) {
  return new Promise((resolve) => {
    chrome.tabs.query(queryInfo, resolve);
  });
}

function openOptions() {
  chrome.runtime.openOptionsPage();
}

async function readJson(response) {
  try {
    return await response.json();
  } catch (_error) {
    return null;
  }
}

function responseMessage(data, status) {
  if (data && typeof data.detail === "string") {
    return data.detail;
  }
  if (data && typeof data.message === "string") {
    return data.message;
  }
  return `Request failed with HTTP ${status}.`;
}

function cleanCategoryName(value) {
  return value.trim().replace(/\s+/g, " ");
}

function splitCommaList(value) {
  const names = [];
  const seen = new Set();
  for (const item of value.split(",")) {
    const name = cleanCategoryName(item);
    const key = name.toLowerCase();
    if (name && !seen.has(key)) {
      names.push(name);
      seen.add(key);
    }
  }
  return names;
}

function cleanTitle(value) {
  const title = value.trim().replace(/\s+/g, " ");
  return title || null;
}

function compareByName(left, right) {
  return left.name.localeCompare(right.name);
}

function normalizeBaseUrl(value) {
  return value.trim().replace(/\/+$/, "");
}

function isHttpUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch (_error) {
    return false;
  }
}

function setBusy(isBusy) {
  elements.saveButton.disabled = isBusy;
}

function setStatus(message, type = "") {
  elements.status.textContent = message;
  elements.status.className = type ? `status ${type}` : "status";
}
