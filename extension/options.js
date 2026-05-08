"use strict";

const DEFAULT_BASE_URL = "http://localhost:8010";

const elements = {
  form: document.getElementById("optionsForm"),
  baseUrl: document.getElementById("baseUrl"),
  apiToken: document.getElementById("apiToken"),
  testConnection: document.getElementById("testConnection"),
  status: document.getElementById("status"),
};

document.addEventListener("DOMContentLoaded", loadOptions);
elements.form.addEventListener("submit", saveOptions);
elements.testConnection.addEventListener("click", testConnection);

async function loadOptions() {
  const settings = await storageGet({
    baseUrl: DEFAULT_BASE_URL,
    apiToken: "",
  });
  elements.baseUrl.value = settings.baseUrl || DEFAULT_BASE_URL;
  elements.apiToken.value = settings.apiToken || "";
}

async function saveOptions(event) {
  event.preventDefault();
  await storageSet(readSettings());
  setStatus("Options saved.", "success");
}

async function testConnection() {
  const settings = readSettings();
  if (!settings.apiToken) {
    setStatus("Missing API token.", "error");
    return;
  }

  elements.testConnection.disabled = true;
  setStatus("Testing...");

  try {
    const response = await fetch(`${settings.baseUrl}/api/categories`, {
      headers: {
        Authorization: `Bearer ${settings.apiToken}`,
      },
    });

    const data = await readJson(response);
    if (!response.ok) {
      if (response.status === 401) {
        throw new Error("Login token rejected.");
      }
      throw new Error(responseMessage(data, response.status));
    }

    await storageSet(settings);
    setStatus("Connection works. Options saved.", "success");
  } catch (error) {
    setStatus(error.message || "Cannot reach Bookmarks API.", "error");
  } finally {
    elements.testConnection.disabled = false;
  }
}

function readSettings() {
  return {
    baseUrl: normalizeBaseUrl(elements.baseUrl.value || DEFAULT_BASE_URL),
    apiToken: elements.apiToken.value.trim(),
  };
}

function storageGet(defaults) {
  return new Promise((resolve) => {
    chrome.storage.sync.get(defaults, resolve);
  });
}

function storageSet(values) {
  return new Promise((resolve) => {
    chrome.storage.sync.set(values, resolve);
  });
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

function normalizeBaseUrl(value) {
  return value.trim().replace(/\/+$/, "");
}

function setStatus(message, type = "") {
  elements.status.textContent = message;
  elements.status.className = type ? `status ${type}` : "status";
}
