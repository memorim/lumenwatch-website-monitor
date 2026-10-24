import { escapeHtml } from './escape.js';
const state = {
  targets: [],
  changes: [],
};

const elements = {
  form: document.querySelector("#target-form"),
  message: document.querySelector("#message"),
  heroTargetCount: document.querySelector("#hero-target-count"),
  activeTargets: document.querySelector("#active-targets"),
  totalChecks: document.querySelector("#total-checks"),
  changeCount: document.querySelector("#change-count"),
  averageResponse: document.querySelector("#average-response"),
  targetSummary: document.querySelector("#target-summary"),
  targetGrid: document.querySelector("#target-grid"),
  timeline: document.querySelector("#timeline"),
  detailTitle: document.querySelector("#detail-title"),
  detailSeverity: document.querySelector("#detail-severity"),
  detailSummary: document.querySelector("#detail-summary"),
  detailSimilarity: document.querySelector("#detail-similarity"),
  detailResponse: document.querySelector("#detail-response"),
  detailEngine: document.querySelector("#detail-engine"),
  addedWords: document.querySelector("#added-words"),
  removedWords: document.querySelector("#removed-words"),
  contentPreview: document.querySelector("#content-preview"),
};

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(payload.detail)
      ? payload.detail.map((item) => item.msg).join(", ")
      : payload.detail;
    throw new Error(detail || "Request failed.");
  }
  return payload;
}

function setMessage(text = "", type = "") {
  elements.message.textContent = text;
  elements.message.className = `message ${type}`.trim();
}

function formatTime(value) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function renderOverview(overview) {
  elements.heroTargetCount.textContent = String(overview.targets).padStart(2, "0");
  elements.activeTargets.textContent = overview.active_targets;
  elements.totalChecks.textContent = overview.checks;
  elements.changeCount.textContent = overview.changes;
  elements.averageResponse.textContent = `${Math.round(overview.average_response_ms)}ms`;
  elements.targetSummary.textContent = `${overview.active_targets} active / ${overview.targets} total`;
}

function renderTargets() {
  elements.targetGrid.innerHTML = state.targets.length
    ? state.targets
        .map((target) => {
          const latest = target.latest_snapshot;
          return `
            <article class="target-card">
              <div class="target-top">
                <div>
                  <h3>${escapeHtml(target.name)}</h3>
                  <a class="target-url" href="${escapeHtml(target.url)}" target="_blank" rel="noreferrer">
                    ${escapeHtml(target.url)}
                  </a>
                </div>
                <span class="target-dot" aria-label="Active"></span>
              </div>
              <div class="target-meta">
                <div>
                  <span>LAST STATUS</span>
                  <strong>${latest ? `HTTP ${latest.status_code}` : "Not checked"}</strong>
                </div>
                <div>
                  <span>CAPTURE MODE</span>
                  <strong>${target.render_js ? "Browser ready" : "HTTP"}</strong>
                </div>
                <div>
                  <span>INTERVAL</span>
                  <strong>${target.interval_minutes} min</strong>
                </div>
                <div>
                  <span>RESPONSE</span>
                  <strong>${latest ? `${latest.response_ms} ms` : "—"}</strong>
                </div>
              </div>
              <div class="target-actions">
                <span class="severity ${latest?.severity || "none"}">
                  ${latest?.severity || "waiting"}
                </span>
                <button type="button" data-run-target="${target.id}">Run check</button>
              </div>
            </article>
          `;
        })
        .join("")
    : '<div class="empty-state">No watch targets yet.</div>';

  elements.targetGrid.querySelectorAll("[data-run-target]").forEach((button) => {
    button.addEventListener("click", () => runTarget(button.dataset.runTarget, button));
  });
}

function renderTimeline() {
  elements.timeline.innerHTML = state.changes.length
    ? state.changes
        .map(
          (change) => `
            <button class="timeline-event" type="button" data-change-id="${change.id}">
              <span class="event-time">${formatTime(change.created_at)}</span>
              <span>
                <strong class="event-title">${escapeHtml(change.target_name)}</strong>
                <span class="event-summary">${escapeHtml(change.summary)}</span>
              </span>
              <span class="severity ${change.severity}">${change.severity}</span>
            </button>
          `,
        )
        .join("")
    : '<div class="empty-state">No meaningful changes detected yet.</div>';

  elements.timeline.querySelectorAll("[data-change-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const change = state.changes.find((item) => item.id === button.dataset.changeId);
      if (change) renderDetail(change);
    });
  });
}

function renderWords(element, words) {
  element.innerHTML = words.length
    ? words.map((word) => `<span>${escapeHtml(word)}</span>`).join("")
    : "<small>None</small>";
}

function renderDetail(change) {
  elements.detailTitle.textContent = change.target_name;
  elements.detailSeverity.textContent = change.severity;
  elements.detailSeverity.className = `severity ${change.severity}`;
  elements.detailSummary.textContent = change.summary;
  elements.detailSimilarity.textContent = `${change.similarity}%`;
  elements.detailResponse.textContent = `${change.response_ms} ms`;
  elements.detailEngine.textContent = change.engine;
  renderWords(elements.addedWords, change.added);
  renderWords(elements.removedWords, change.removed);
  elements.contentPreview.textContent = change.content_text || "No extracted content.";
}

async function refresh(preferredChange = null) {
  const [overview, targets, changes] = await Promise.all([
    request("/api/overview"),
    request("/api/targets"),
    request("/api/changes"),
  ]);
  state.targets = targets;
  state.changes = changes;
  renderOverview(overview);
  renderTargets();
  renderTimeline();
  const detail = preferredChange || state.changes[0];
  if (detail) renderDetail(detail);
}

async function runTarget(targetId, button) {
  button.disabled = true;
  setMessage("Capturing the target and comparing it with the previous snapshot…");
  try {
    const snapshot = await request(`/api/targets/${targetId}/run`, { method: "POST" });
    await refresh(snapshot.severity === "none" || snapshot.severity === "baseline" ? null : snapshot);
    setMessage(`Check completed: ${snapshot.summary}`);
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

elements.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(elements.form);
  const submitButton = elements.form.querySelector('button[type="submit"]');
  const payload = {
    name: formData.get("name"),
    url: formData.get("url"),
    interval_minutes: Number(formData.get("interval_minutes")),
    render_js: formData.get("render_js") === "on",
  };

  submitButton.disabled = true;
  setMessage("Creating watch target…");
  try {
    const target = await request("/api/targets", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    elements.form.reset();
    await refresh();
    setMessage(`${target.name} is now being watched.`);
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    submitButton.disabled = false;
  }
});

refresh().catch((error) => setMessage(error.message, "error"));

