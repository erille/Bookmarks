"use strict";

const feed = document.getElementById("feed");
const loadMoreButton = document.getElementById("loadMoreButton");
const searchInput = document.getElementById("searchInput");
const sourceUrlInput = document.getElementById("sourceUrlInput");
const savePanel = document.getElementById("savePanel");

let activeCard = null;
let isLoading = false;
let hasMore = Boolean(loadMoreButton);

const videoObserver = new IntersectionObserver(handleVideoIntersection, {
  threshold: [0, 0.65],
});

const cardObserver = new IntersectionObserver(handleCardIntersection, {
  rootMargin: "-20% 0px -45% 0px",
  threshold: [0, 0.35, 0.7],
});

const loadObserver = new IntersectionObserver((entries) => {
  if (entries.some((entry) => entry.isIntersecting)) {
    loadMoreBookmarks();
  }
}, {
  rootMargin: "700px 0px",
});

initPage();

function initPage() {
  initSavePanel();
  initShareButtons();
  initSelectAll();

  if (feed) {
    observeFeedItems(feed);

    if (loadMoreButton) {
      loadMoreButton.addEventListener("click", loadMoreBookmarks);
      loadObserver.observe(loadMoreButton);
    }

    document.addEventListener("keydown", handleKeyboard);
  }
}

function initSavePanel() {
  document.querySelectorAll("[data-toggle-save-panel]").forEach((button) => {
    button.addEventListener("click", () => {
      setSavePanelOpen(savePanel?.hidden ?? true);
    });
  });
  updateSaveToggleState();
}

function setSavePanelOpen(open) {
  if (!savePanel) {
    window.location.href = "/bookmarks";
    return;
  }
  savePanel.hidden = !open;
  updateSaveToggleState();
  if (open) {
    sourceUrlInput?.focus();
  }
}

function updateSaveToggleState() {
  document.querySelectorAll("[data-toggle-save-panel]").forEach((button) => {
    button.setAttribute("aria-expanded", savePanel && !savePanel.hidden ? "true" : "false");
  });
}

function initShareButtons() {
  document.querySelectorAll("[data-share-url]").forEach((button) => {
    button.addEventListener("click", async () => {
      const shareUrl = button.dataset.shareUrl;
      if (!shareUrl) {
        return;
      }
      const originalText = button.textContent;
      try {
        if (navigator.share) {
          await navigator.share({ url: shareUrl });
        } else {
          await copyToClipboard(shareUrl);
        }
        button.textContent = "Copied";
      } catch (_error) {
        button.textContent = "Copy failed";
      } finally {
        window.setTimeout(() => {
          button.textContent = originalText;
        }, 1400);
      }
    });
  });
}

async function copyToClipboard(value) {
  if (navigator.clipboard) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.append(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

function initSelectAll() {
  document.querySelectorAll("[data-select-all]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const form = checkbox.closest("form");
      form?.querySelectorAll('input[name="bookmark_ids"]').forEach((item) => {
        item.checked = checkbox.checked;
      });
    });
  });
}

async function loadMoreBookmarks() {
  if (!feed || !hasMore || isLoading) {
    return;
  }

  isLoading = true;
  if (loadMoreButton) {
    loadMoreButton.disabled = true;
    loadMoreButton.textContent = "Loading...";
  }

  const offset = Number.parseInt(feed.dataset.offset || "0", 10);
  const limit = Number.parseInt(feed.dataset.limit || "20", 10);
  const params = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  });

  if (feed.dataset.q) {
    params.set("q", feed.dataset.q);
  }
  if (feed.dataset.category) {
    params.set("category", feed.dataset.category);
  }
  if (feed.dataset.tag) {
    params.set("tag", feed.dataset.tag);
  }

  try {
    const response = await fetch(`${feed.dataset.feedUrl}?${params.toString()}`, {
      credentials: "same-origin",
      headers: {
        "X-Requested-With": "fetch",
      },
    });

    if (!response.ok) {
      throw new Error("Could not load more bookmarks.");
    }

    const html = await response.text();
    const template = document.createElement("template");
    template.innerHTML = html.trim();
    const cards = Array.from(template.content.querySelectorAll(".bookmark"));

    if (cards.length === 0) {
      stopLoadingMore();
      return;
    }

    const empty = feed.querySelector(".empty");
    if (empty) {
      empty.remove();
    }

    feed.append(template.content);
    feed.dataset.offset = String(offset + cards.length);
    observeFeedItems(feed);

    if (cards.length < limit) {
      stopLoadingMore();
    }
  } catch (_error) {
    if (loadMoreButton) {
      loadMoreButton.textContent = "Load more";
    }
  } finally {
    isLoading = false;
    if (loadMoreButton && hasMore) {
      loadMoreButton.disabled = false;
      loadMoreButton.textContent = "Load more";
    }
  }
}

function observeFeedItems(root) {
  root.querySelectorAll("video[data-autoplay]:not([data-observed])").forEach((video) => {
    video.dataset.observed = "true";
    video.muted = true;
    video.playsInline = true;
    videoObserver.observe(video);
  });

  root.querySelectorAll(".bookmark:not([data-card-observed])").forEach((card) => {
    card.dataset.cardObserved = "true";
    cardObserver.observe(card);
  });
}

function handleVideoIntersection(entries) {
  for (const entry of entries) {
    const video = entry.target;
    if (entry.intersectionRatio >= 0.65) {
      pauseOtherVideos(video);
      video.muted = true;
      video.play().catch(() => {});
    } else if (!entry.isIntersecting || entry.intersectionRatio < 0.2) {
      video.pause();
    }
  }
}

function handleCardIntersection(entries) {
  const visibleCards = entries
    .filter((entry) => entry.isIntersecting)
    .sort((left, right) => right.intersectionRatio - left.intersectionRatio);

  if (visibleCards.length === 0) {
    return;
  }

  setActiveCard(visibleCards[0].target);
}

function setActiveCard(card) {
  if (activeCard === card) {
    return;
  }
  if (activeCard) {
    activeCard.classList.remove("is-active");
  }
  activeCard = card;
  activeCard.classList.add("is-active");
}

function pauseOtherVideos(currentVideo) {
  document.querySelectorAll("video[data-autoplay]").forEach((video) => {
    if (video !== currentVideo) {
      video.pause();
    }
  });
}

function handleKeyboard(event) {
  if (event.altKey || event.ctrlKey || event.metaKey || isTypingTarget(event.target)) {
    return;
  }

  if (event.key === "/") {
    event.preventDefault();
    searchInput?.focus();
    searchInput?.select();
  } else if (event.key.toLowerCase() === "n") {
    event.preventDefault();
    setSavePanelOpen(true);
    sourceUrlInput?.focus();
  } else if (event.key.toLowerCase() === "j") {
    event.preventDefault();
    scrollToRelativeCard(1);
  } else if (event.key.toLowerCase() === "k") {
    event.preventDefault();
    scrollToRelativeCard(-1);
  } else if (event.key.toLowerCase() === "o") {
    event.preventDefault();
    openActiveSource();
  }
}

function scrollToRelativeCard(direction) {
  const cards = Array.from(document.querySelectorAll(".bookmark"));
  if (cards.length === 0) {
    return;
  }

  const currentIndex = activeCard ? cards.indexOf(activeCard) : 0;
  const nextIndex = Math.min(Math.max(currentIndex + direction, 0), cards.length - 1);
  cards[nextIndex].scrollIntoView({ behavior: "smooth", block: "center" });
  setActiveCard(cards[nextIndex]);
}

function openActiveSource() {
  const card = activeCard || document.querySelector(".bookmark");
  const sourceUrl = card?.dataset.sourceUrl;
  if (sourceUrl) {
    window.open(sourceUrl, "_blank", "noopener");
  }
}

function isTypingTarget(target) {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  return (
    target.matches("input, textarea, select") ||
    target.isContentEditable
  );
}

function stopLoadingMore() {
  hasMore = false;
  if (loadMoreButton) {
    loadObserver.unobserve(loadMoreButton);
    loadMoreButton.remove();
  }
}
