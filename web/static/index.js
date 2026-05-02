const qs = (id) => document.getElementById(id);
const statusText = qs("statusText");
const liveClock = qs("liveClock");
const terminalFeed = qs("systemTerminalFeed");
const AUTH_HEARTBEAT_MS = 10000;
const AUTH_HEARTBEAT_MOBILE_MS = 20000;
const MOBILE_MEDIA_QUERY = "(max-width: 700px)";
const COARSE_POINTER_QUERY = "(pointer: coarse)";
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
const DASHBOARD_VIEWS = ["overview", "users", "subscriptions", "audit", "ops"];

const state = {
  usersPage: 1,
  subscriptionsPage: 1,
  auditPage: 1,
  exportsPage: 1,
  limit: 10,
  subscriptionsLimit: 20,
  exportsLimit: 10,
  auditSnapshot: null,
  view: "overview",
};

let usersRequestToken = 0;
let subscriptionsRequestToken = 0;
let auditRequestToken = 0;
let exportsRequestToken = 0;
let detailRequestToken = 0;
let statusTimer = null;
let statusHistory = [];
let authHeartbeatTimer = null;
let liveClockTimer = null;
let loginRedirecting = false;
let ownerCheckAllRunning = false;
let heartbeatInFlight = false;
let perfMode = "full";
const loadedViews = new Set();
const viewLoadPromises = new Map();
let fullRefreshController = null;
const viewRefreshControllers = new Map();

function isMobileLikeDevice() {
  return window.matchMedia(MOBILE_MEDIA_QUERY).matches || window.matchMedia(COARSE_POINTER_QUERY).matches;
}

function detectPerfMode() {
  if (window.matchMedia(REDUCED_MOTION_QUERY).matches) return "lite";
  if (isMobileLikeDevice()) return "lite";
  return "full";
}

function applyPerfMode(mode) {
  const safeMode = mode === "lite" ? "lite" : "full";
  perfMode = safeMode;
  document.body.dataset.perfMode = safeMode;
}

function ensureCyberBackdropLayers(host) {
  const classNames = ["drift-grid-layer", "matrix-ghost-layer", "scan-beam-layer"];
  classNames.forEach((className) => {
    if (host.querySelector(`.${className}`)) return;
    const layer = document.createElement("div");
    layer.className = className;
    layer.setAttribute("aria-hidden", "true");
    host.appendChild(layer);
  });
}

function initMatrixRain() {
  if (perfMode !== "full") return;
  const host = document.querySelector(".page-container");
  if (!(host instanceof HTMLElement)) return;
  ensureCyberBackdropLayers(host);

  const canvas = document.createElement("canvas");
  canvas.className = "matrix-rain-canvas";
  canvas.setAttribute("aria-hidden", "true");
  host.appendChild(canvas);

  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const prefersReduced = window.matchMedia(REDUCED_MOTION_QUERY).matches;
  const isMobile = window.matchMedia(MOBILE_MEDIA_QUERY).matches;
  const fontSize = isMobile ? 14 : 16;
  const step = isMobile ? 18 : 20;
  const frameInterval = prefersReduced ? 140 : (isMobile ? 70 : 45);
  const glyphs = "01ABCDEFGHIJKLMNOPQRSTUVWXYZ#$%*+-<>[]{}";
  let drops = [];
  let rafId = 0;
  let lastTs = 0;

  const resize = () => {
    const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    const w = host.clientWidth;
    const h = host.clientHeight;
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.font = `${fontSize}px "JetBrains Mono", monospace`;
    ctx.textBaseline = "top";
    const columns = Math.max(1, Math.floor(w / step));
    drops = Array.from({ length: columns }, () => -Math.floor(Math.random() * 24));
  };

  const render = (ts) => {
    rafId = window.requestAnimationFrame(render);
    if (ts - lastTs < frameInterval) return;
    lastTs = ts;

    const width = host.clientWidth;
    const height = host.clientHeight;
    ctx.fillStyle = "rgba(2, 10, 15, 0.18)";
    ctx.fillRect(0, 0, width, height);

    for (let i = 0; i < drops.length; i += 1) {
      const char = glyphs[(Math.random() * glyphs.length) | 0];
      const x = i * step;
      const y = drops[i] * step;
      const headGlow = Math.random() > 0.86;
      ctx.fillStyle = headGlow ? "rgba(124, 255, 190, 0.92)" : "rgba(40, 233, 148, 0.75)";
      ctx.fillText(char, x, y);
      if (y > height + step && Math.random() > 0.975) drops[i] = -2;
      else drops[i] += 1;
    }
  };

  resize();
  rafId = window.requestAnimationFrame(render);
  window.addEventListener("resize", resize);
  window.addEventListener("beforeunload", () => {
    window.removeEventListener("resize", resize);
    if (rafId) window.cancelAnimationFrame(rafId);
  });
}

function pushTerminalLine(text, tag = "INFO") {
  if (!terminalFeed || !text) return;
  const ts = new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date());
  const li = document.createElement("li");
  li.textContent = `[${ts}] [${tag}] ${String(text).replace(/\s+/g, " ").trim()}`;
  terminalFeed.insertBefore(li, terminalFeed.firstChild);
  while (terminalFeed.children.length > 12) {
    terminalFeed.removeChild(terminalFeed.lastChild);
  }
}

function startLiveClock() {
  if (!liveClock) return;
  const tickMs = perfMode === "lite" ? 5000 : 1000;
  const tick = () => {
    liveClock.textContent = new Intl.DateTimeFormat(undefined, {
      year: "2-digit",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(new Date());
  };
  tick();
  if (liveClockTimer) clearInterval(liveClockTimer);
  liveClockTimer = setInterval(tick, tickMs);
}

function setSignalWidth(id, value) {
  const node = qs(id);
  if (!node) return;
  const n = Math.max(8, Math.min(96, Number(value || 8)));
  node.style.width = `${n}%`;
}

function syncSignalBars(runtime = null) {
  const uptime = Number(runtime?.uptime_seconds || 0);
  const parserReady = !!runtime?.parser_ready;
  const storageReady = !!runtime?.storage_ready;
  const allowAll = !!runtime?.allow_all_users;

  const cpu = (uptime % 63) + (parserReady ? 22 : 10);
  const mem = (Math.floor(uptime / 3) % 58) + (storageReady ? 28 : 16);
  const io = (Math.floor(uptime / 7) % 46) + (allowAll ? 34 : 18);
  const net = (Math.floor(uptime / 5) % 52) + (parserReady && storageReady ? 36 : 20);

  setSignalWidth("cpuBar", cpu);
  setSignalWidth("memBar", mem);
  setSignalWidth("ioBar", io);
  setSignalWidth("netBar", net);
}

function redirectToLogin() {
  if (loginRedirecting) return;
  loginRedirecting = true;
  window.location.href = "/admin/login";
}

async function authFetch(path, options = {}) {
  const resp = await fetch(path, {
    credentials: "include",
    ...options,
  });
  if (resp.status === 401) {
    redirectToLogin();
    return null;
  }
  return resp;
}

async function readErrorMessage(resp) {
  if (!resp) return "请求失败";
  try {
    const contentType = (resp.headers.get("content-type") || "").toLowerCase();
    if (contentType.includes("application/json")) {
      const data = await resp.json();
      if (data && typeof data === "object") {
        return data.error || data.message || `请求失败（${resp.status}）`;
      }
    }
    const text = await resp.text();
    return text || `请求失败（${resp.status}）`;
  } catch (_) {
    return `请求失败（${resp.status}）`;
  }
}

function extractFilename(disposition, fallback = "download.bin") {
  const text = String(disposition || "");
  const utf8Match = text.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match && utf8Match[1]) {
    try {
      return decodeURIComponent(utf8Match[1].replace(/["']/g, ""));
    } catch (_) {
      return utf8Match[1].replace(/["']/g, "");
    }
  }
  const plainMatch = text.match(/filename="?([^";]+)"?/i);
  if (plainMatch && plainMatch[1]) return plainMatch[1];
  return fallback;
}

async function downloadWithBlob(path, fallbackName) {
  const resp = await authFetch(path, { method: "GET" });
  if (!resp) return false;
  if (!resp.ok) {
    throw new Error(await readErrorMessage(resp));
  }

  const blob = await resp.blob();
  if (!blob || blob.size <= 0) {
    throw new Error("下载内容为空");
  }

  const filename = extractFilename(resp.headers.get("content-disposition"), fallbackName);
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = filename || fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
  return true;
}

function formatLocalDateTime(value) {
  const raw = String(value ?? "").trim();
  if (!raw || raw === "-") return "-";
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;

  const normalized = raw.includes("T") ? raw : raw.replace(" ", "T");
  const dt = new Date(normalized);
  if (Number.isNaN(dt.getTime())) return raw;

  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(dt);
}

async function apiRequest(path, options = {}) {
  try {
    const resp = await authFetch(path, options);
    if (!resp) return null;
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      throw new Error(data.error || "请求失败");
    }
    return data.data;
  } catch (e) {
    if (e && e.name === "AbortError") {
      throw e;
    }
    setStatus(e.message || String(e), "warn", { autoHideMs: 4500, merge: true });
    throw e;
  }
}

function setStatus(text, cls = "", options = {}) {
  const autoHideMs = Number(options.autoHideMs ?? 2600);
  const sticky = !!options.sticky;
  const merge = !!options.merge;
  const cleanText = String(text || "").trim();
  if (merge && cleanText) {
    statusHistory = [cleanText, ...statusHistory.filter((line) => line !== cleanText)].slice(0, 3);
  } else if (cleanText) {
    statusHistory = [cleanText];
  }

  if (statusTimer) {
    clearTimeout(statusTimer);
    statusTimer = null;
  }

  statusText.className = "status " + cls;
  statusText.textContent = statusHistory.join(" | ");
  if (cleanText) pushTerminalLine(cleanText, cls === "warn" ? "WARN" : cls === "ok" ? "OK" : "INFO");

  if (!sticky && cleanText) {
    statusTimer = setTimeout(() => {
      statusText.className = "status";
      statusText.textContent = "";
      statusHistory = [];
      statusTimer = null;
    }, autoHideMs);
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function decodeHtmlEntities(value) {
  let text = String(value ?? "");
  for (let i = 0; i < 3; i += 1) {
    const prev = text;
    const holder = document.createElement("textarea");
    holder.innerHTML = text.replace(/&nbsp;/gi, " ");
    text = holder.value;
    if (text === prev) break;
  }
  return text;
}

function normalizeIdentity(value) {
  const decoded = decodeHtmlEntities(value);
  const clean = decoded
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return clean || "-";
}

function clampPage(value, total) {
  const n = Number(value || 1);
  return Math.max(1, Math.min(Math.max(1, Number(total || 1)), Number.isFinite(n) ? n : 1));
}

function buildAuditUrlCell(urls, rowIndex, extraClass = "") {
  const list = Array.isArray(urls) ? urls.filter(Boolean) : [];
  if (!list.length) return '<span class="audit-empty">-</span>';

  const className = extraClass ? `audit-url-list ${extraClass}` : "audit-url-list";
  const items = list
    .map((u, idx) => {
      const raw = String(u);
      const href = escapeHtml(raw);
      const full = escapeHtml(raw);
      const copyValue = encodeURIComponent(raw);
      return `<li class="audit-url-item"><div class="audit-url-main"><a href="${href}" target="_blank" rel="noopener noreferrer" class="audit-url-link mono" title="${href}">${full}</a></div><div class="audit-url-actions"><span class="audit-url-tag">#${idx + 1}</span><button type="button" class="audit-copy-btn" data-copy="${copyValue}">复制</button></div></li>`;
    })
    .join("");

  return `<ul class="${className}" id="audit-url-${rowIndex}">${items}</ul>`;
}

function goPage(pageType, page) {
  const safePage = Math.max(1, Number(page || 1));
  if (pageType === "users") return loadAuthorizedUsers(safePage);
  if (pageType === "subscriptions") return loadAvailableSubscriptions(safePage);
  if (pageType === "audit") return loadRecentChecks(safePage, { syncUrl: true });
  if (pageType === "exports") return loadRecentExports(safePage);
}

function renderPagination(containerId, current, total, pageType, totalItems = 0) {
  const container = qs(containerId);
  if (!container) return;

  if (total <= 1) {
    container.innerHTML = "";
    return;
  }

  const safeCurrent = clampPage(current, total);
  container.dataset.pageType = pageType;
  let html = `<button class="page-btn" ${safeCurrent === 1 ? "disabled" : ""} data-page-target="1">&laquo;</button>`;
  html += `<button class="page-btn" ${safeCurrent === 1 ? "disabled" : ""} data-page-target="${safeCurrent - 1}">&larr;</button>`;
  html += `<span class="page-info">第 ${safeCurrent}/${total} 页${totalItems ? `（共 ${totalItems} 条）` : ""}</span>`;
  html += '<span class="page-jump">';
  html += `<input id="${containerId}JumpInput" class="page-jump-input" type="number" min="1" max="${total}" value="${safeCurrent}" data-page-total="${total}" aria-label="跳转页码">`;
  html += `<button class="page-btn page-jump-btn" type="button" data-page-go="${containerId}">跳转</button>`;
  html += "</span>";
  html += `<button class="page-btn" ${safeCurrent === total ? "disabled" : ""} data-page-target="${safeCurrent + 1}">&rarr;</button>`;
  html += `<button class="page-btn" ${safeCurrent === total ? "disabled" : ""} data-page-target="${total}">&raquo;</button>`;

  container.innerHTML = html;
}

function ensureAvailableSubscriptionsView() {
  const tabs = document.querySelector(".view-tabs");
  if (tabs && !tabs.querySelector('[data-view-target="subscriptions"]')) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "view-tab";
    btn.dataset.viewTarget = "subscriptions";
    btn.textContent = "订阅池";
    const auditBtn = tabs.querySelector('[data-view-target="audit"]');
    if (auditBtn) tabs.insertBefore(btn, auditBtn);
    else tabs.appendChild(btn);
  }

  const stack = document.querySelector(".dashboard-layout .stack");
  if (!(stack instanceof HTMLElement) || stack.querySelector('[data-page="subscriptions"]')) return;
  const card = document.createElement("article");
  card.className = "card";
  card.dataset.page = "subscriptions";
  card.innerHTML = `
    <div class="head">
      <h2>可用订阅池</h2>
      <div class="head-actions">
        <button id="loadAvailableSubsBtn" type="button">刷新</button>
      </div>
    </div>
    <div class="body">
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>用户</th><th>订阅</th><th>剩余流量</th><th>到期时间</th><th>最近更新</th></tr>
          </thead>
          <tbody id="availableSubsBody"></tbody>
        </table>
      </div>
      <div id="availableSubsCards" class="mobile-card-list"></div>
      <div id="availableSubsPagination" class="pagination"></div>
    </div>`;
  const auditCard = stack.querySelector('[data-page="audit"]');
  if (auditCard) stack.insertBefore(card, auditCard);
  else stack.appendChild(card);
}

function syncList(container, items, keyFn, createFn, updateFn, emptyFactory) {
  if (!container) return;

  const existing = new Map();
  Array.from(container.children).forEach((node) => {
    if (!(node instanceof HTMLElement)) return;
    const key = node.dataset.key;
    if (key) existing.set(key, node);
  });

  let anchor = container.firstElementChild;
  const liveKeys = new Set();

  for (let i = 0; i < items.length; i += 1) {
    const item = items[i];
    const key = String(keyFn(item, i));
    liveKeys.add(key);
    let node = existing.get(key);
    if (!node) {
      node = createFn(item, key, i);
    } else {
      updateFn(node, item, key, i);
    }

    if (anchor !== node) {
      container.insertBefore(node, anchor);
    } else {
      anchor = anchor.nextElementSibling;
    }
  }

  Array.from(container.children).forEach((node) => {
    if (!(node instanceof HTMLElement)) return;
    const key = node.dataset.key;
    if (!key || !liveKeys.has(key)) node.remove();
  });

  if (!items.length) {
    const emptyNode = emptyFactory();
    container.innerHTML = "";
    container.appendChild(emptyNode);
  }
}

function patchAuthorizedUserRow(tr, r) {
  tr.innerHTML = `
    <td>
      <div class="u-fw-700">${escapeHtml(normalizeIdentity(r.identity || "-"))}</div>
    </td>
    <td>
      ${r.is_owner ? '<span class="badge badge-primary">管理员</span>' : '<span class="badge">用户</span>'}
      ${r.is_authorized ? '<span class="badge badge-success">已授权</span>' : '<span class="badge badge-danger">未授权</span>'}
    </td>
    <td class="mono">${escapeHtml(formatLocalDateTime(r.last_seen || "-"))}</td>
    <td class="mono">${escapeHtml(r.source || "-")}</td>
    <td>
      <div class="u-flex-gap-6">
        <button class="u-btn-compact" data-action="open-detail" data-uid="${escapeHtml(String(r.uid || ""))}">详情</button>
        ${!r.is_owner ? `<button class="btn-danger u-btn-compact" data-action="set-access" data-enabled="0" data-uid="${escapeHtml(String(r.uid || ""))}">撤销</button>` : ""}
      </div>
    </td>`;
}

function renderAuthorizedUsersTable(users) {
  const body = qs("authorizedUsersBody");
  if (!body) return;

  if (!users.length) {
    body.innerHTML = '<tr data-key="__empty"><td colspan="5" class="table-empty-cell">没有匹配的授权用户</td></tr>';
    return;
  }

  syncList(
    body,
    users,
    (u) => u.uid,
    (u, key) => {
      const tr = document.createElement("tr");
      tr.dataset.key = key;
      patchAuthorizedUserRow(tr, u);
      return tr;
    },
    (node, u) => patchAuthorizedUserRow(node, u),
    () => {
      const tr = document.createElement("tr");
      tr.dataset.key = "__empty";
      tr.innerHTML = '<td colspan="5" class="table-empty-cell">没有匹配的授权用户</td>';
      return tr;
    }
  );
}

function renderAuthorizedUsersCards(users) {
  const cardRoot = qs("authorizedUsersCards");
  if (!cardRoot) return;

  if (!users.length) {
    cardRoot.innerHTML = '<div class="mobile-empty-card">没有匹配的授权用户</div>';
    return;
  }

  cardRoot.innerHTML = users.map((r) => `
    <article class="mobile-card" data-key="${escapeHtml(r.uid || "")}">
      <div class="mobile-card-head">
        <div>
          <div class="u-fw-700">${escapeHtml(normalizeIdentity(r.identity || "-"))}</div>
        </div>
      </div>
      <div class="mobile-card-meta">
        <div class="mobile-meta-row">${r.is_owner ? '<span class="badge badge-primary">管理员</span>' : '<span class="badge">用户</span>'} ${r.is_authorized ? '<span class="badge badge-success">已授权</span>' : '<span class="badge badge-danger">未授权</span>'}</div>
        <div class="mobile-meta-row mono">最近活跃：${escapeHtml(formatLocalDateTime(r.last_seen || "-"))}</div>
        <div class="mobile-meta-row mono">访问来源：${escapeHtml(r.source || "-")}</div>
      </div>
      <div class="mobile-card-actions">
        <button class="u-btn-compact" data-action="open-detail" data-uid="${escapeHtml(String(r.uid || ""))}">详情</button>
        ${!r.is_owner ? `<button class="btn-danger u-btn-compact" data-action="set-access" data-enabled="0" data-uid="${escapeHtml(String(r.uid || ""))}">撤销</button>` : ""}
      </div>
    </article>
  `).join("");
}

function renderAvailableSubscriptionsTable(rows) {
  const body = qs("availableSubsBody");
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="5" class="table-empty-cell">暂无可用订阅</td></tr>';
    return;
  }
  body.innerHTML = rows
    .map(
      (r) => `
    <tr>
      <td><div class="u-fw-700">${escapeHtml(normalizeIdentity(r.identity || "-"))}</div></td>
      <td>
        <div class="u-fw-700">${escapeHtml(r.name || "-")}</div>
        <a class="audit-url-link mono" href="${escapeHtml(r.url || "#")}" target="_blank" rel="noopener noreferrer">${escapeHtml(r.url || "-")}</a>
      </td>
      <td class="mono">${escapeHtml(r.remaining || "-")}</td>
      <td class="mono">${escapeHtml(formatLocalDateTime(r.expire_time || "-"))}</td>
      <td class="mono">${escapeHtml(formatLocalDateTime(r.updated_at || "-"))}</td>
    </tr>`
    )
    .join("");
}

function renderAvailableSubscriptionsCards(rows) {
  const root = qs("availableSubsCards");
  if (!root) return;
  if (!rows.length) {
    root.innerHTML = '<div class="mobile-empty-card">暂无可用订阅</div>';
    return;
  }
  root.innerHTML = rows
    .map(
      (r) => `
    <article class="mobile-card">
      <div class="mobile-card-head">
        <div>
          <div class="u-fw-700">${escapeHtml(r.name || "-")}</div>
          <div class="mono u-text-muted">${escapeHtml(normalizeIdentity(r.identity || "-"))}</div>
        </div>
      </div>
      <div class="mobile-card-meta">
        <div class="mobile-meta-row mono">剩余流量：${escapeHtml(r.remaining || "-")}</div>
        <div class="mobile-meta-row mono">到期时间：${escapeHtml(formatLocalDateTime(r.expire_time || "-"))}</div>
        <div class="mobile-meta-row mono">最近更新：${escapeHtml(formatLocalDateTime(r.updated_at || "-"))}</div>
        <div class="mobile-meta-row"><a class="audit-url-link mono" href="${escapeHtml(r.url || "#")}" target="_blank" rel="noopener noreferrer">${escapeHtml(r.url || "-")}</a></div>
      </div>
    </article>`
    )
    .join("");
}

function auditRowKey(r, idx) {
  return String(r.id || `${r.uid || "unknown"}-${r.ts || "0"}-${r.source || "s"}-${idx}`);
}

function patchAuditRow(tr, r, rowKey) {
  const auditCell = buildAuditUrlCell(r.urls || [], rowKey);
  tr.innerHTML = `
    <td><div class="u-fw-700">${escapeHtml(normalizeIdentity(r.identity || "-"))}</div></td>
    <td class="mono">${escapeHtml(formatLocalDateTime(r.ts || "-"))}</td>
    <td><span class="badge badge-primary audit-source-badge">${escapeHtml(r.source || "-")}</span></td>
    <td class="audit-url-col">${auditCell}</td>`;
}

function renderRecentChecksTable(rows) {
  const body = qs("recentChecksBody");
  if (!body) return;

  if (!rows.length) {
    body.innerHTML = '<tr data-key="__empty"><td colspan="4" class="table-empty-cell">没有匹配的审计记录</td></tr>';
    return;
  }

  syncList(
    body,
    rows,
    (r, i) => auditRowKey(r, i),
    (r, key, i) => {
      const tr = document.createElement("tr");
      tr.dataset.key = key;
      patchAuditRow(tr, r, key || i);
      return tr;
    },
    (node, r, key) => patchAuditRow(node, r, key),
    () => {
      const tr = document.createElement("tr");
      tr.dataset.key = "__empty";
      tr.innerHTML = '<td colspan="4" class="table-empty-cell">没有匹配的审计记录</td>';
      return tr;
    }
  );
}

function renderRecentChecksCards(rows) {
  const cardRoot = qs("recentChecksCards");
  if (!cardRoot) return;

  if (!rows.length) {
    cardRoot.innerHTML = '<div class="mobile-empty-card">没有匹配的审计记录</div>';
    return;
  }

  cardRoot.innerHTML = rows.map((r, idx) => `
    <article class="mobile-card" data-key="${escapeHtml(auditRowKey(r, idx))}">
      <div class="mobile-card-head">
        <div class="u-fw-700">${escapeHtml(normalizeIdentity(r.identity || "-"))}</div>
      </div>
      <div class="mobile-card-meta">
        <div class="mobile-meta-row mono">时间：${escapeHtml(formatLocalDateTime(r.ts || "-"))}</div>
        <div class="mobile-meta-row">${r.source ? `<span class="badge badge-primary audit-source-badge">${escapeHtml(r.source || "-")}</span>` : '<span class="audit-empty">-</span>'}</div>
      </div>
      <div class="mobile-card-urls">${buildAuditUrlCell(r.urls || [], `${auditRowKey(r, idx)}-mobile`, "audit-url-list-mobile")}</div>
    </article>
  `).join("");
}

function collectAuditFilters() {
  return {
    mode: qs("auditMode")?.value || "others",
    user_id: (qs("filterUserId")?.value || "").trim(),
    source: (qs("filterSource")?.value || "").trim(),
    q: (qs("filterQ")?.value || "").trim(),
    from: qs("filterFrom")?.value || "",
    to: qs("filterTo")?.value || "",
  };
}

function applyAuditFilters(snapshot) {
  if (!snapshot) return;
  if (qs("auditMode")) qs("auditMode").value = snapshot.mode || "others";
  if (qs("filterUserId")) qs("filterUserId").value = snapshot.user_id || "";
  if (qs("filterSource")) qs("filterSource").value = snapshot.source || "";
  if (qs("filterQ")) qs("filterQ").value = snapshot.q || "";
  if (qs("filterFrom")) qs("filterFrom").value = snapshot.from || "";
  if (qs("filterTo")) qs("filterTo").value = snapshot.to || "";
}

function readAuditStateFromUrl() {
  const sp = new URLSearchParams(window.location.search);
  return {
    snapshot: {
      mode: sp.get("mode") || "others",
      user_id: sp.get("user_id") || "",
      source: sp.get("source") || "",
      q: sp.get("q") || "",
      from: sp.get("from") || "",
      to: sp.get("to") || "",
    },
    page: clampPage(sp.get("audit_page") || 1, 999999),
  };
}

function writeAuditStateToUrl(snapshot, page) {
  const url = new URL(window.location.href);
  const sp = url.searchParams;
  const setOrDelete = (key, value) => {
    if (value) sp.set(key, value); else sp.delete(key);
  };

  setOrDelete("mode", snapshot.mode);
  setOrDelete("user_id", snapshot.user_id);
  setOrDelete("source", snapshot.source);
  setOrDelete("q", snapshot.q);
  setOrDelete("from", snapshot.from);
  setOrDelete("to", snapshot.to);

  if (Number(page || 1) > 1) sp.set("audit_page", String(page));
  else sp.delete("audit_page");

  history.replaceState(null, "", `${url.pathname}?${sp.toString()}`);
}

function resolveView(value) {
  const candidate = String(value || "").trim().toLowerCase();
  return DASHBOARD_VIEWS.includes(candidate) ? candidate : "overview";
}

function readViewFromHash() {
  return resolveView((window.location.hash || "").replace(/^#/, ""));
}

function applyView(view, options = {}) {
  const safeView = resolveView(view);
  state.view = safeView;

  const syncHash = options.syncHash !== false;
  if (syncHash && window.location.hash !== `#${safeView}`) {
    history.replaceState(null, "", `#${safeView}`);
  }

  document.querySelectorAll("[data-page]").forEach((node) => {
    if (!(node instanceof HTMLElement)) return;
    const page = resolveView(node.dataset.page || "overview");
    node.classList.toggle("is-hidden", page !== safeView);
  });

  document.querySelectorAll("[data-view-target]").forEach((node) => {
    if (!(node instanceof HTMLElement)) return;
    const target = resolveView(node.dataset.viewTarget || "overview");
    node.classList.toggle("active", target === safeView);
  });

  let visibleStackCount = 0;
  document.querySelectorAll(".dashboard-layout .stack").forEach((stack) => {
    if (!(stack instanceof HTMLElement)) return;
    const hasVisibleCard = Array.from(stack.querySelectorAll("[data-page]")).some((card) => {
      return card instanceof HTMLElement && !card.classList.contains("is-hidden");
    });
    stack.classList.toggle("is-hidden-stack", !hasVisibleCard);
    if (hasVisibleCard) visibleStackCount += 1;
  });

  const layout = document.querySelector(".dashboard-layout");
  if (layout instanceof HTMLElement) {
    const forceSingleColumn = safeView !== "overview" || visibleStackCount <= 1;
    layout.classList.toggle("single-column", forceSingleColumn);
    layout.classList.toggle("single-stack", visibleStackCount <= 1);
  }

  if (options.loadData !== false) {
    void refreshByView(safeView);
  }
}

function updateAuditFilterMobileLabel() {
  const btn = qs("toggleAuditFiltersBtn");
  const form = qs("auditFilterForm");
  if (!btn || !form) return;
  btn.textContent = form.classList.contains("collapsed") ? "展开筛选" : "收起筛选";
}

function syncResponsiveState() {
  const form = qs("auditFilterForm");
  if (!(form instanceof HTMLFormElement)) return;
  const isMobile = window.matchMedia("(max-width: 700px)").matches;
  if (isMobile) {
    form.classList.add("collapsed");
  } else {
    form.classList.remove("collapsed");
  }
  updateAuditFilterMobileLabel();
}

function buildAuditParams(snapshot, page) {
  const q = new URLSearchParams();
  q.set("mode", snapshot.mode || "others");
  q.set("page", String(page));
  q.set("limit", String(state.limit));
  if (snapshot.user_id) q.set("user_id", snapshot.user_id);
  if (snapshot.source) q.set("source", snapshot.source);
  if (snapshot.q) q.set("q", snapshot.q);
  if (snapshot.from) q.set("from", snapshot.from);
  if (snapshot.to) q.set("to", snapshot.to);
  return q;
}

function buildAuditExportQuery(snapshot) {
  const q = buildAuditParams(snapshot, 1);
  q.delete("page");
  q.delete("limit");
  return q.toString();
}

function skeletonLines(count = 3) {
  return Array.from({ length: count }).map(() => '<div class="skeleton-line"></div>').join("");
}

async function loadOverview(requestOptions = {}) {
  ["mTotalSubs", "mUsers", "mActive", "mExports"].forEach((id) => {
    const el = qs(id);
    if (el) el.textContent = "...";
  });
  const data = await apiRequest("/api/v1/system/overview", requestOptions);
  if (!data) return;
  qs("mTotalSubs").textContent = data.total_subs ?? "-";
  qs("mUsers").textContent = data.authorized_users ?? "-";
  qs("mActive").textContent = data.active_24h ?? "-";
  qs("mExports").textContent = data.exports_24h ?? "-";
}

async function loadAuthorizedUsers(page = 1, options = {}) {
  const requestOptions = options.requestOptions || {};
  const usersBody = qs("authorizedUsersBody");
  const usersCards = qs("authorizedUsersCards");
  if (usersBody) {
    usersBody.innerHTML = '<tr><td colspan="5"><div class="skeleton-line"></div><div class="skeleton-line"></div></td></tr>';
  }
  if (usersCards) {
    usersCards.innerHTML = '<div class="mobile-empty-card"><div class="skeleton-line"></div></div>';
  }
  const token = ++usersRequestToken;
  const data = await apiRequest(`/api/v1/users/authorized?page=${page}&limit=${state.limit}`, requestOptions);
  if (!data || token !== usersRequestToken) return;

  state.usersPage = clampPage(data.page || page, data.total_pages || 1);
  const users = Array.isArray(data.users) ? data.users : [];

  if (options.adjustOnEmpty && state.usersPage > 1 && users.length === 0) {
    await loadAuthorizedUsers(state.usersPage - 1, options);
    return;
  }

  renderAuthorizedUsersTable(users);
  renderAuthorizedUsersCards(users);
  renderPagination("usersPagination", state.usersPage, data.total_pages || 1, "users", Number(data.total || 0));

  qs("publicAccessDesc").innerHTML = `当前：${data.allow_all_users ? '<span class="public-access-open">开启</span>' : '<span class="public-access-closed">受限</span>'}`;
  window.__allowAllUsers = !!data.allow_all_users;
}

async function loadAvailableSubscriptions(page = 1, options = {}) {
  const requestOptions = options.requestOptions || {};
  const body = qs("availableSubsBody");
  const cards = qs("availableSubsCards");
  if (body) body.innerHTML = '<tr><td colspan="5"><div class="skeleton-line"></div><div class="skeleton-line"></div></td></tr>';
  if (cards) cards.innerHTML = '<div class="mobile-empty-card"><div class="skeleton-line"></div></div>';
  const token = ++subscriptionsRequestToken;
  const data = await apiRequest(`/api/v1/subscriptions/available?page=${page}&limit=${state.subscriptionsLimit}`, requestOptions);
  if (!data || token !== subscriptionsRequestToken) return;
  const rows = Array.isArray(data.rows) ? data.rows : [];
  const totalPages = data.total_pages || Math.max(1, Math.ceil(Number(data.total || rows.length) / state.subscriptionsLimit));
  state.subscriptionsPage = clampPage(data.page || page, totalPages);
  if (state.subscriptionsPage !== page) {
    await loadAvailableSubscriptions(state.subscriptionsPage, options);
    return;
  }
  renderAvailableSubscriptionsTable(rows);
  renderAvailableSubscriptionsCards(rows);
  renderPagination("availableSubsPagination", state.subscriptionsPage, totalPages, "subscriptions", Number(data.total || rows.length));
}


async function loadRecentChecks(page = 1, options = {}) {
  const requestOptions = options.requestOptions || {};
  const checksBody = qs("recentChecksBody");
  const checksCards = qs("recentChecksCards");
  if (checksBody) {
    checksBody.innerHTML = '<tr><td colspan="4"><div class="skeleton-line"></div><div class="skeleton-line"></div></td></tr>';
  }
  if (checksCards) {
    checksCards.innerHTML = '<div class="mobile-empty-card"><div class="skeleton-line"></div></div>';
  }
  const snapshot = options.snapshot || state.auditSnapshot || collectAuditFilters();
  state.auditSnapshot = snapshot;
  if (options.syncUrl !== false) writeAuditStateToUrl(snapshot, page);

  const token = ++auditRequestToken;
  const params = buildAuditParams(snapshot, page);
  const data = await apiRequest(`/api/v1/audit/recent-checks?${params.toString()}`, requestOptions);
  if (!data || token !== auditRequestToken) return;

  const rows = Array.isArray(data.rows) ? data.rows : [];
  const totalPages = data.total_pages || Math.max(1, Math.ceil(Number(data.total || rows.length) / state.limit));
  state.auditPage = clampPage(page, totalPages);

  if (state.auditPage !== page) {
    await loadRecentChecks(state.auditPage, { snapshot, syncUrl: true });
    return;
  }

  renderRecentChecksTable(rows);
  renderRecentChecksCards(rows);
  renderPagination("auditPagination", state.auditPage, totalPages, "audit", Number(data.total || rows.length));
}

function fmtUptime(seconds) {
  const s = Math.max(0, Number(seconds || 0));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  return d > 0 ? `${d}天 ${h}小时 ${m}分` : `${h}小时 ${m}分`;
}

async function loadRuntime(requestOptions = {}) {
  qs("runtimeBody").innerHTML = '<div class="skeleton-block"></div><div class="skeleton-block"></div><div class="skeleton-block"></div><div class="skeleton-block"></div>';
  const data = await apiRequest("/api/v1/system/runtime", requestOptions);
  if (!data) return;
  qs("runtimeBody").innerHTML = [
    { k: "运行模式", v: data.run_mode },
    { k: "运行时长", v: fmtUptime(data.uptime_seconds) },
    { k: "认证后端", v: data.auth_backend === "memory" ? "内存" : data.auth_backend },
    { k: "公开模式", v: data.allow_all_users ? "开启" : "关闭" },
    { k: "解析器", v: data.parser_ready ? "就绪" : "异常" },
    { k: "存储", v: data.storage_ready ? "就绪" : "异常" },
  ]
    .map((i) => `<div class="runtime-item"><div class="k">${i.k}</div><div class="v">${i.v}</div></div>`)
    .join("");
  syncSignalBars(data);
}

async function loadAlerts(requestOptions = {}) {
  qs("alertsBody").innerHTML = `<div class="skeleton-block">${skeletonLines(2)}</div><div class="skeleton-block">${skeletonLines(2)}</div>`;
  const data = await apiRequest("/api/v1/audit/alerts", requestOptions);
  if (!data) return;
  const el = qs("alertsBody");
  const alerts = Array.isArray(data.alerts) ? data.alerts : [];

  if (!alerts.length) {
    el.innerHTML = '<div class="panel-empty-hint">暂无告警。</div>';
    return;
  }

  const capped = alerts.slice(0, 50);
  const note = alerts.length > capped.length ? `<div class="alert-limit-note">仅显示前 ${capped.length} 条，共 ${alerts.length} 条告警。</div>` : "";
  el.innerHTML =
    note +
    capped
      .map(
        (a) => `
      <div class="alert ${escapeHtml(String(a.severity || "low"))}">
        <div class="alert-content">
          <div class="alert-title">[${escapeHtml(String(a.severity || "").toUpperCase())}] ${escapeHtml(a.title || "")}</div>
          <div class="alert-desc">${escapeHtml(normalizeIdentity(a.detail || ""))}</div>
        </div>
      </div>`
      )
      .join("");
}

async function loadAuditSummary(requestOptions = {}) {
  qs("auditSummaryBody").innerHTML = '<div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line"></div>';
  const mode = qs("auditMode")?.value || "others";
  const data = await apiRequest(`/api/v1/audit/summary?mode=${encodeURIComponent(mode)}`, requestOptions);
  if (!data) return;
  qs("auditSummaryBody").innerHTML = [
    { l: "范围", v: data.title },
    { l: "24h 检测", v: data.check_count },
    { l: "24h 用户", v: data.user_count },
    { l: "24h 链接", v: data.url_count },
  ]
    .map((i) => `<div class="audit-summary-item"><span class="audit-summary-label">${i.l}</span><span class="audit-summary-value">${i.v}</span></div>`)
    .join("");
}

async function loadRecentExports(page = 1, options = {}) {
  const requestOptions = options.requestOptions || {};
  qs("recentExportsBody").innerHTML = `<div class="skeleton-block">${skeletonLines(2)}</div><div class="skeleton-block">${skeletonLines(2)}</div>`;
  const token = ++exportsRequestToken;
  const data = await apiRequest(`/api/v1/exports/recent?scope=others&limit=${state.exportsLimit}&page=${page}`, requestOptions);
  if (!data || token !== exportsRequestToken) return;

  const rows = Array.isArray(data.rows) ? data.rows : [];
  const totalPages = data.total_pages || Math.max(1, Math.ceil(Number(data.total || rows.length) / state.exportsLimit));
  state.exportsPage = clampPage(page, totalPages);

  const el = qs("recentExportsBody");
  if (!rows.length) {
    el.innerHTML = '<div class="panel-empty-hint panel-empty-tight">暂无导出记录</div>';
  } else {
    el.innerHTML = rows
      .map(
        (r) => `
      <div class="recent-export-item">
        <div class="recent-export-identity">${escapeHtml(normalizeIdentity(r.identity || "-"))}</div>
        <div class="recent-export-meta">
          <span class="badge badge-primary">${escapeHtml(r.fmt || "-")}</span>
          <span class="mono recent-export-ts">${escapeHtml(formatLocalDateTime(r.ts || "-"))}</span>
        </div>
        <div class="mono recent-export-target">${escapeHtml(r.target || "-")}</div>
      </div>`
      )
      .join("");
  }

  renderPagination("exportsPagination", state.exportsPage, totalPages, "exports", Number(data.total || rows.length));
}

async function confirmAction(message, title = "确认操作", dangerLabel = "确认") {
  const modal = qs("confirmActionModal");
  const titleEl = qs("confirmActionTitle");
  const msgEl = qs("confirmActionMessage");
  const okBtn = qs("confirmActionBtn");
  const cancelBtn = qs("cancelConfirmBtn");

  if (!modal || !titleEl || !msgEl || !okBtn || !cancelBtn) {
    return window.confirm(message);
  }

  titleEl.textContent = title;
  msgEl.textContent = message;
  okBtn.textContent = dangerLabel;

  return await new Promise((resolve) => {
    let done = false;
    const finish = (val) => {
      if (done) return;
      done = true;
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      modal.removeEventListener("cancel", onCancel);
      modal.close();
      resolve(val);
    };
    const onOk = () => finish(true);
    const onCancel = (e) => {
      if (e && typeof e.preventDefault === "function") e.preventDefault();
      finish(false);
    };

    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    modal.addEventListener("cancel", onCancel);
    modal.showModal();
  });
}

function getQuickUid() {
  return (qs("quickUidInput")?.value || "").trim();
}

function toggleQuickAuthPanel(forceOpen = null) {
  const panel = qs("quickAuthPanel");
  if (!panel) return;
  const shouldOpen = forceOpen === null ? !!panel.hidden : !!forceOpen;
  panel.hidden = !shouldOpen;
  if (shouldOpen) qs("quickUidInput")?.focus();
}

async function togglePublicAccess() {
  const current = !!window.__allowAllUsers;
  const data = await apiRequest("/api/v1/system/public-access", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled: !current }),
  });
  if (!data) return;
  setStatus(`公开访问已${data.enabled ? "开启" : "关闭"}`, "ok");
  await loadAuthorizedUsers(state.usersPage);
}

async function revokeAllSessions() {
  const ok = await confirmAction("该操作会让所有已登录管理会话下线（包含当前会话）。", "强制下线", "确认下线");
  if (!ok) return;
  const data = await apiRequest("/api/v1/system/sessions/revoke-all", { method: "POST" });
  if (!data) return;
  setStatus(`已下线 ${data.revoked} 个会话`, "ok");
  setTimeout(() => {
    window.location.href = "/admin/login";
  }, 1200);
}

async function setUserAccess(uid, enabled) {
  const safeUid = String(uid || "").trim();
  if (!safeUid) {
    setStatus("请输入 UID", "warn");
    return;
  }

  await apiRequest("/api/v1/users/access", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ uid: safeUid, enabled }),
  });

  setStatus(enabled ? "授权成功" : "撤销成功", "ok");
  await Promise.all([loadAuthorizedUsers(state.usersPage, { adjustOnEmpty: !enabled }), loadOverview()]);
}

async function openUserDetail(uid) {
  const safeUid = String(uid || "").trim();
  if (!safeUid) {
    setStatus("请输入 UID", "warn");
    return;
  }

  const modal = qs("userDetailModal");
  const body = qs("userDetailBody");
  const title = qs("userDetailTitle");
  if (!modal || !body || !title) return;

  const token = ++detailRequestToken;
  title.textContent = `用户详情：${safeUid}`;
  body.innerHTML = '<div class="modal-skeleton">加载中...</div>';
  modal.showModal();

  try {
    const data = await apiRequest(`/api/v1/users/detail?uid=${encodeURIComponent(safeUid)}`);
    if (!data || token !== detailRequestToken) return;

    title.textContent = `用户详情：${normalizeIdentity(data.identity || safeUid)}`;
    const subs = Array.isArray(data.subscriptions) ? data.subscriptions : [];
    const truncated = Number(data.subscription_count || subs.length) > subs.length;
    const truncatedBlock = truncated
      ? `<div class="modal-warning">当前仅展示 ${subs.length} 条订阅（服务端有数量限制）。</div>`
      : "";

    const subHtml = subs.length
      ? subs
          .map(
            (s) => `
          <div class="subscription-item">
            <div class="subscription-name">${escapeHtml(s.name || "-")}</div>
            <div class="mono subscription-url">${escapeHtml(s.url || "-")}</div>
            <div class="subscription-meta">更新时间：${escapeHtml(formatLocalDateTime(s.updated_at || "-"))} | 到期：${escapeHtml(formatLocalDateTime(s.expire_time || "-"))}</div>
          </div>`
          )
          .join("")
      : '<div class="panel-empty-hint panel-empty-tight">暂无订阅数据</div>';

    const safeDetailUid = escapeHtml(String(data.uid || safeUid));
    body.innerHTML = `
      ${truncatedBlock}
      <div class="user-detail-actions">
          <button type="button" class="btn-brand" data-action="set-access" data-enabled="1" data-uid="${safeDetailUid}">授权</button>
          ${data.is_owner ? '<button type="button" class="btn-danger" disabled>管理员不可撤销</button>' : `<button type="button" class="btn-danger" data-action="set-access" data-enabled="0" data-uid="${safeDetailUid}">撤销</button>`}
      </div>
      <div class="user-detail-grid">
        <div class="runtime-item"><div class="k">角色</div><div class="v">${data.is_owner ? "管理员" : "用户"}</div></div>
        <div class="runtime-item"><div class="k">订阅数</div><div class="v">${escapeHtml(String(data.subscription_count || 0))}</div></div>
        <div class="runtime-item"><div class="k">最近活跃</div><div class="v">${escapeHtml(formatLocalDateTime(data.last_seen || "-"))}</div></div>
      </div>
      <h4>订阅列表</h4>
      ${subHtml}
    `;
  } catch (e) {
    body.innerHTML = `<div class="panel-empty-hint">${escapeHtml(e.message || "加载失败")}</div>`;
  }
}

async function uploadOwnerFile(path, file) {
  const form = new FormData();
  form.append("file", file, file.name || "upload.bin");
  const resp = await authFetch(path, {
    method: "POST",
    body: form,
  });
  if (!resp) return null;
  const data = await resp.json();
  if (!resp.ok || !data.ok) throw new Error(data.error || "请求失败");
  return data.data;
}

function startAuthHeartbeat() {
  if (authHeartbeatTimer) clearInterval(authHeartbeatTimer);
  const heartbeatMs = perfMode === "lite" ? AUTH_HEARTBEAT_MOBILE_MS : AUTH_HEARTBEAT_MS;
  authHeartbeatTimer = setInterval(async () => {
    if (document.visibilityState !== "visible" || heartbeatInFlight) return;
    heartbeatInFlight = true;
    try {
      const probeUrl = `/healthz?probe_ts=${Date.now()}`;
      const resp = await authFetch(probeUrl, { method: "GET", cache: "no-store" });
      if (!resp) return;
    } catch (_) {
      // Ignore transient network errors and keep heartbeat alive.
    } finally {
      heartbeatInFlight = false;
    }
  }, heartbeatMs);
}

async function runOwnerImport(file) {
  const data = await uploadOwnerFile("/api/v1/owner/import-json", file);
  if (!data) return;
  setStatus(`导入完成：${data.imported}`, "ok");
  await refreshAll();
}

async function runOwnerRestore(file) {
  const ok = await confirmAction("恢复备份会覆盖当前数据，是否继续？", "恢复备份", "确认恢复");
  if (!ok) return;
  const data = await uploadOwnerFile("/api/v1/owner/restore", file);
  if (!data) return;
  setStatus(`恢复完成：${data.restored_files}`, "ok");
  await refreshAll();
}

async function runOwnerCheckAll() {
  if (ownerCheckAllRunning) {
    setStatus("全量体检正在进行中", "warn", { autoHideMs: 2200 });
    return;
  }
  const ok = await confirmAction("现在执行全量体检吗？这可能需要一段时间。", "全量体检", "开始体检");
  if (!ok) return;
  const btn = qs("ownerCheckAllBtn");
  ownerCheckAllRunning = true;
  if (btn) btn.disabled = true;
  setStatus("全量体检执行中...", "", { sticky: true });
  try {
    const data = await apiRequest("/api/v1/owner/check-all", { method: "POST" });
    if (!data) return;
    setStatus(`全量体检完成：成功 ${data.success} / 失败 ${data.failed}`, "ok");
    await refreshAll();
  } finally {
    ownerCheckAllRunning = false;
    if (btn) btn.disabled = false;
  }
}

async function loadOwnerAggregateInfo() {
  const data = await apiRequest("/api/v1/owner/aggregate-subscription");
  if (!data) return null;
  const urlInput = qs("ownerAggregateUrl");
  const meta = qs("ownerAggregateMeta");
  const historyBox = qs("ownerAggregateHistory");
  if (urlInput) urlInput.value = data.url || "";
  if (meta) {
    const ts = data.generated_at ? formatLocalDateTime(new Date(Number(data.generated_at) * 1000).toISOString().slice(0, 19).replace("T", " ")) : "-";
    const ver = data.version || "-";
    let text = `节点数: ${Number(data.node_count || 0)} | 最近生成: ${ts} | 版本: ${ver}`;
    if (data.last_error) {
      const errTs = data.last_error_at
        ? formatLocalDateTime(new Date(Number(data.last_error_at) * 1000).toISOString().slice(0, 19).replace("T", " "))
        : "-";
      text += ` | 最近失败: ${data.last_error} (${errTs})`;
    }
    if (data.build_stats) {
      const s = data.build_stats;
      text += ` | 构建: 总${Number(s.total_subscriptions || 0)} 合格${Number(s.eligible_subscriptions || 0)} 成功${Number(s.parsed_ok || 0)} 超时${Number(s.timed_out || 0)}`;
    }
    meta.textContent = text;
  }
  if (historyBox) {
    const rows = Array.isArray(data.build_history) ? data.build_history.slice(-8).reverse() : [];
    if (!rows.length) {
      historyBox.textContent = "最近构建：暂无";
    } else {
      historyBox.innerHTML = rows
        .map((r) => {
          const ts = r.ts
            ? formatLocalDateTime(new Date(Number(r.ts) * 1000).toISOString().slice(0, 19).replace("T", " "))
            : "-";
          return `• ${ts} | 总${Number(r.total_subscriptions || 0)} 合格${Number(r.eligible_subscriptions || 0)} 成功${Number(r.parsed_ok || 0)} 失败${Number(r.parsed_failed || 0)} 超时${Number(r.timed_out || 0)}`;
        })
        .join("<br>");
    }
  }
  return data;
}

async function refreshOwnerAggregate() {
  const data = await apiRequest("/api/v1/owner/aggregate-subscription/refresh", { method: "POST" });
  if (!data) return;
  setStatus(`聚合订阅已刷新，节点 ${Number(data.node_count || 0)} 条`, "ok");
  await loadOwnerAggregateInfo();
}

async function rotateOwnerAggregateUrl() {
  const ok = await confirmAction("刷新URL后，旧URL会立即作废，是否继续？", "刷新聚合URL", "确认刷新");
  if (!ok) return;
  let data = null;
  try {
    data = await apiRequest("/api/v1/owner/aggregate-subscription/rotate", { method: "POST" });
  } catch (e) {
    const msg = String((e && e.message) || "");
    if (msg.includes("rotate_cooldown")) {
      setStatus("操作过快，请稍后再刷新URL", "warn");
      return;
    }
    throw e;
  }
  if (!data) return;
  const urlInput = qs("ownerAggregateUrl");
  if (urlInput) urlInput.value = data.url || "";
  setStatus("聚合URL已刷新，旧URL已作废", "ok");
  await refreshOwnerAggregate();
}

function resetViewRefreshControllers() {
  viewRefreshControllers.forEach((controller) => controller.abort());
  viewRefreshControllers.clear();
}

function nextViewRefreshSignal(view) {
  const prev = viewRefreshControllers.get(view);
  if (prev) prev.abort();
  const controller = new AbortController();
  viewRefreshControllers.set(view, controller);
  return { signal: controller.signal, controller };
}

function nextFullRefreshSignal() {
  if (fullRefreshController) fullRefreshController.abort();
  fullRefreshController = new AbortController();
  return { signal: fullRefreshController.signal, controller: fullRefreshController };
}

function getViewLoaders(view, requestOptions = {}) {
  const safeView = resolveView(view);
  if (safeView === "users") {
    return [() => loadAuthorizedUsers(state.usersPage || 1, { requestOptions })];
  }
  if (safeView === "subscriptions") {
    return [() => loadAvailableSubscriptions(state.subscriptionsPage || 1, { requestOptions })];
  }
  if (safeView === "audit") {
    return [
      () => loadRecentChecks(state.auditPage || 1, { syncUrl: false, requestOptions }),
      () => loadRecentExports(state.exportsPage || 1, { requestOptions }),
      () => loadAuditSummary(requestOptions),
    ];
  }
  if (safeView === "ops") {
    return [() => loadAuthorizedUsers(state.usersPage || 1, { requestOptions }), () => loadRuntime(requestOptions)];
  }
  return [() => loadOverview(requestOptions), () => loadRuntime(requestOptions), () => loadAlerts(requestOptions), () => loadAuditSummary(requestOptions)];
}

async function refreshByView(view, options = {}) {
  const safeView = resolveView(view);
  const force = !!options.force;
  if (!force && loadedViews.has(safeView)) return;
  if (!force && viewLoadPromises.has(safeView)) {
    await viewLoadPromises.get(safeView);
    return;
  }

  const refreshContext = nextViewRefreshSignal(safeView);
  const run = (async () => {
    if (options.showStatus !== false) {
      setStatus("刷新中...", "", { sticky: true });
    }
    try {
      const requestOptions = { signal: refreshContext.signal };
      await Promise.all(getViewLoaders(safeView, requestOptions).map((loader) => loader()));
      loadedViews.add(safeView);
      if (options.showStatus !== false) {
        setStatus("已同步", "ok");
      }
    } catch (e) {
      if (!(e && e.name === "AbortError")) {
        // handled in apiRequest
      }
    } finally {
      const latest = viewRefreshControllers.get(safeView);
      if (latest === refreshContext.controller) {
        viewRefreshControllers.delete(safeView);
      }
      viewLoadPromises.delete(safeView);
    }
  })();

  viewLoadPromises.set(safeView, run);
  await run;
}

async function refreshAll() {
  resetViewRefreshControllers();
  loadedViews.clear();
  setStatus("刷新中...", "", { sticky: true });
  const refreshContext = nextFullRefreshSignal();
  try {
    await Promise.all([
      loadOverview({ signal: refreshContext.signal }),
      loadRuntime({ signal: refreshContext.signal }),
      loadAuthorizedUsers(state.usersPage || 1, { requestOptions: { signal: refreshContext.signal } }),
      loadAvailableSubscriptions(state.subscriptionsPage || 1, { requestOptions: { signal: refreshContext.signal } }),
      loadRecentChecks(state.auditPage || 1, { syncUrl: false, requestOptions: { signal: refreshContext.signal } }),
      loadAlerts({ signal: refreshContext.signal }),
      loadAuditSummary({ signal: refreshContext.signal }),
      loadRecentExports(state.exportsPage || 1, { requestOptions: { signal: refreshContext.signal } }),
    ]);
    DASHBOARD_VIEWS.forEach((view) => loadedViews.add(view));
    setStatus("已同步", "ok");
  } catch (e) {
    if (!(e && e.name === "AbortError")) {
      // handled in apiRequest
    }
  }
}
function bindEvents() {
  qs("refreshBtn").onclick = refreshAll;
  qs("logoutBtn").onclick = () => apiRequest("/admin/logout", { method: "POST" }).then(() => (window.location.href = "/admin/login"));

  qs("openQuickAuthBtn").onclick = () => toggleQuickAuthPanel();
  qs("loadUsersTableBtn").onclick = () => loadAuthorizedUsers(state.usersPage || 1);
  qs("loadAvailableSubsBtn").onclick = () => loadAvailableSubscriptions(state.subscriptionsPage || 1);

  qs("quickGrantBtn").onclick = () => {
    const uid = getQuickUid();
    if (!uid) return setStatus("请输入 UID", "warn");
    setUserAccess(uid, true);
    toggleQuickAuthPanel(false);
  };
  qs("quickRevokeBtn").onclick = () => {
    const uid = getQuickUid();
    if (!uid) return setStatus("请输入 UID", "warn");
    setUserAccess(uid, false);
    toggleQuickAuthPanel(false);
  };
  qs("quickDetailBtn").onclick = () => {
    const uid = getQuickUid();
    if (!uid) return setStatus("请输入 UID", "warn");
    openUserDetail(uid);
    toggleQuickAuthPanel(false);
  };
  qs("closeUserDetailBtn").onclick = () => qs("userDetailModal")?.close();

  const auditForm = qs("auditFilterForm");
  if (auditForm) {
    auditForm.addEventListener("submit", (e) => {
      e.preventDefault();
      state.auditSnapshot = collectAuditFilters();
      state.auditPage = 1;
      loadRecentChecks(1, { snapshot: state.auditSnapshot, syncUrl: true });
    });
  }

  qs("loadChecksBtn").onclick = () => {
    state.auditSnapshot = collectAuditFilters();
    state.auditPage = 1;
    loadRecentChecks(1, { snapshot: state.auditSnapshot, syncUrl: true });
  };
  qs("auditMode").onchange = () => {
    state.auditSnapshot = collectAuditFilters();
    state.auditPage = 1;
    loadRecentChecks(1, { snapshot: state.auditSnapshot, syncUrl: true });
    loadAuditSummary();
  };
  qs("toggleAuditFiltersBtn").onclick = () => {
    const form = qs("auditFilterForm");
    if (!(form instanceof HTMLFormElement)) return;
    form.classList.toggle("collapsed");
    updateAuditFilterMobileLabel();
  };

  qs("exportCsvBtn").onclick = async () => {
    const snapshot = state.auditSnapshot || collectAuditFilters();
    try {
      setStatus("正在准备 CSV 导出...", "", { autoHideMs: 2000 });
      await downloadWithBlob(`/api/v1/audit/export?format=csv&${buildAuditExportQuery(snapshot)}`, "audit_checks.csv");
      setStatus("CSV 已下载", "ok");
    } catch (e) {
      setStatus(e.message || "CSV 导出失败", "warn");
    }
  };
  qs("exportJsonBtn").onclick = async () => {
    const snapshot = state.auditSnapshot || collectAuditFilters();
    try {
      setStatus("正在准备 JSON 导出...", "", { autoHideMs: 2000 });
      await downloadWithBlob(`/api/v1/audit/export?format=json&${buildAuditExportQuery(snapshot)}`, "audit_checks.json");
      setStatus("JSON 已下载", "ok");
    } catch (e) {
      setStatus(e.message || "JSON 导出失败", "warn");
    }
  };

  qs("togglePublicBtn").onclick = togglePublicAccess;
  qs("revokeSessionsBtn").onclick = revokeAllSessions;

  qs("ownerExportJsonBtn").onclick = async () => {
    try {
      setStatus("正在下载 JSON 备份...", "", { autoHideMs: 2000 });
      await downloadWithBlob("/api/v1/owner/export-json", "subscriptions_export.json");
      setStatus("JSON 备份已下载", "ok");
    } catch (e) {
      setStatus(e.message || "JSON 导出失败", "warn");
    }
  };
  qs("ownerBackupBtn").onclick = async () => {
    try {
      setStatus("正在准备 ZIP 备份...", "", { autoHideMs: 2000 });
      await downloadWithBlob("/api/v1/owner/backup", "backup.zip");
      setStatus("ZIP 备份已下载", "ok");
    } catch (e) {
      setStatus(e.message || "ZIP 备份失败", "warn");
    }
  };
  qs("ownerImportJsonBtn").onclick = () => qs("ownerImportFile").click();
  qs("ownerRestoreBtn").onclick = () => qs("ownerRestoreFile").click();
  qs("ownerCheckAllBtn").onclick = runOwnerCheckAll;
  qs("ownerAggregateRefreshBtn").onclick = () => refreshOwnerAggregate();
  qs("ownerAggregateRotateBtn").onclick = () => rotateOwnerAggregateUrl();
  qs("ownerAggregateCopyBtn").onclick = async () => {
    const urlInput = qs("ownerAggregateUrl");
    const text = (urlInput && urlInput.value) || "";
    if (!text) return setStatus("聚合URL为空", "warn");
    try {
      await navigator.clipboard.writeText(text);
      setStatus("聚合URL已复制", "ok");
    } catch (_e) {
      setStatus("复制失败", "warn");
    }
  };

  qs("ownerImportFile").onchange = async (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = "";
    if (!file) return;
    try { await runOwnerImport(file); } catch (e) { setStatus(e.message || String(e), "warn"); }
  };

  qs("ownerRestoreFile").onchange = async (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = "";
    if (!file) return;
    try { await runOwnerRestore(file); } catch (e) { setStatus(e.message || String(e), "warn"); }
  };

  qs("loadRuntimeBtn").onclick = () => loadRuntime();
  qs("loadAlertsBtn").onclick = () => loadAlerts();
  qs("loadAuditBtn").onclick = () => loadAuditSummary();
  qs("loadExportsBtn").onclick = () => loadRecentExports(state.exportsPage || 1);

  document.addEventListener("keydown", (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement) || !input.classList.contains("page-jump-input")) return;
    if (event.key !== "Enter") return;
    const container = input.closest(".pagination");
    if (!container) return;
    const total = Number(input.dataset.pageTotal || 1);
    const page = Math.max(1, Math.min(total, Number(input.value || 1)));
    goPage(container.dataset.pageType || "", page);
  });

  document.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    const copyBtn = target.closest(".audit-copy-btn");
    if (copyBtn) {
      const encoded = copyBtn.getAttribute("data-copy") || "";
      let textToCopy = "";
      try { textToCopy = decodeURIComponent(encoded); } catch { textToCopy = encoded; }
      if (!textToCopy) return;
      try { await navigator.clipboard.writeText(textToCopy); setStatus("已复制", "ok"); }
      catch { setStatus("复制失败", "warn"); }
      return;
    }

    const actionBtn = target.closest("[data-action]");
    if (actionBtn) {
      const action = actionBtn.getAttribute("data-action") || "";
      const uid = actionBtn.getAttribute("data-uid") || "";
      if (action === "open-detail") {
        await openUserDetail(uid);
        return;
      }
      if (action === "set-access") {
        const enabled = actionBtn.getAttribute("data-enabled") === "1";
        await setUserAccess(uid, enabled);
        return;
      }
    }

    const pageBtn = target.closest("[data-page-target]");
    if (pageBtn) {
      const container = pageBtn.closest(".pagination");
      if (!container) return;
      const page = Number(pageBtn.getAttribute("data-page-target") || 1);
      goPage(container.dataset.pageType || "", page);
      return;
    }

    const pageGo = target.closest("[data-page-go]");
    if (pageGo) {
      const containerId = pageGo.getAttribute("data-page-go");
      const container = qs(containerId);
      const input = qs(`${containerId}JumpInput`);
      if (!container || !(input instanceof HTMLInputElement)) return;
      const total = Number(input.dataset.pageTotal || 1);
      const page = Math.max(1, Math.min(total, Number(input.value || 1)));
      goPage(container.dataset.pageType || "", page);
      return;
    }

    const viewBtn = target.closest("[data-view-target]");
    if (viewBtn) {
      const view = viewBtn.getAttribute("data-view-target") || "overview";
      applyView(view, { syncHash: true });
      return;
    }

    const panel = qs("quickAuthPanel");
    const trigger = qs("openQuickAuthBtn");
    if (panel && !panel.hidden && !panel.contains(target) && trigger && !trigger.contains(target)) {
      panel.hidden = true;
    }
  });
}

function init() {
  applyPerfMode(detectPerfMode());
  ensureAvailableSubscriptionsView();
  const restored = readAuditStateFromUrl();
  state.auditSnapshot = restored.snapshot;
  state.auditPage = restored.page;
  applyAuditFilters(restored.snapshot);
  applyView(readViewFromHash(), { syncHash: false, loadData: false });
  initMatrixRain();
  window.addEventListener("hashchange", () => applyView(readViewFromHash(), { syncHash: false }));
  syncResponsiveState();
  window.addEventListener("resize", () => syncResponsiveState());
  bindEvents();
  startLiveClock();
  syncSignalBars();
  pushTerminalLine("console bootstrap complete", "BOOT");
  startAuthHeartbeat();
  window.addEventListener("beforeunload", () => {
    if (fullRefreshController) {
      fullRefreshController.abort();
      fullRefreshController = null;
    }
    resetViewRefreshControllers();
    if (authHeartbeatTimer) {
      clearInterval(authHeartbeatTimer);
      authHeartbeatTimer = null;
    }
    if (liveClockTimer) {
      clearInterval(liveClockTimer);
      liveClockTimer = null;
    }
  });
  refreshByView(state.view, { force: true, showStatus: true });
  loadOwnerAggregateInfo();
}

init();









