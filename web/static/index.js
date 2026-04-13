const qs = (id) => document.getElementById(id);
const statusText = qs("statusText");

const state = {
  usersPage: 1,
  auditPage: 1,
  exportsPage: 1,
  limit: 10,
  exportsLimit: 10,
  auditSnapshot: null,
};

let usersRequestToken = 0;
let auditRequestToken = 0;
let exportsRequestToken = 0;
let detailRequestToken = 0;
let statusTimer = null;

async function apiRequest(path, options = {}) {
  try {
    const resp = await fetch(path, {
      credentials: "include",
      ...options,
    });
    if (resp.status === 401) {
      window.location.href = "/admin/login";
      return null;
    }
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      throw new Error(data.error || "Request failed");
    }
    return data.data;
  } catch (e) {
    setStatus(e.message || String(e), "warn", { autoHideMs: 4500 });
    throw e;
  }
}

function setStatus(text, cls = "", options = {}) {
  const autoHideMs = Number(options.autoHideMs ?? 2600);
  const sticky = !!options.sticky;

  if (statusTimer) {
    clearTimeout(statusTimer);
    statusTimer = null;
  }

  statusText.className = "status " + cls;
  statusText.textContent = text || "";

  if (!sticky && text) {
    statusTimer = setTimeout(() => {
      statusText.className = "status";
      statusText.textContent = "";
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

function normalizeIdentity(value) {
  return (
    String(value ?? "")
      .replace(/<[^>]+>/g, " ")
      .replace(/&nbsp;/gi, " ")
      .replace(/&amp;/gi, "&")
      .replace(/&lt;/gi, "<")
      .replace(/&gt;/gi, ">")
      .replace(/&#39;/gi, "'")
      .replace(/&quot;/gi, '"')
      .replace(/\s+/g, " ")
      .trim() || "-"
  );
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
      return `<li class="audit-url-item"><div class="audit-url-main"><a href="${href}" target="_blank" rel="noopener noreferrer" class="audit-url-link mono" title="${href}">${full}</a></div><div class="audit-url-actions"><span class="audit-url-tag">#${idx + 1}</span><button type="button" class="audit-copy-btn" data-copy="${copyValue}">Copy</button></div></li>`;
    })
    .join("");

  return `<ul class="${className}" id="audit-url-${rowIndex}">${items}</ul>`;
}

function renderPagination(containerId, current, total, onPageChange, totalItems = 0) {
  const container = qs(containerId);
  if (!container) return;

  if (total <= 1) {
    container.innerHTML = "";
    return;
  }

  const safeCurrent = clampPage(current, total);
  let html = `<button class="page-btn" ${safeCurrent === 1 ? "disabled" : ""} onclick="${onPageChange}(1)">«</button>`;
  html += `<button class="page-btn" ${safeCurrent === 1 ? "disabled" : ""} onclick="${onPageChange}(${safeCurrent - 1})">←</button>`;
  html += `<span class="page-info">Page ${safeCurrent}/${total}${totalItems ? ` (Total ${totalItems})` : ""}</span>`;
  html += '<span class="page-jump">';
  html += `<input id="${containerId}JumpInput" class="page-jump-input" type="number" min="1" max="${total}" value="${safeCurrent}" aria-label="Jump page">`;
  html += `<button class="page-btn page-jump-btn" type="button" onclick="(function(){const el=document.getElementById('${containerId}JumpInput');const p=Math.max(1,Math.min(${total},Number(el && el.value || ${safeCurrent})));${onPageChange}(p);})();">Go</button>`;
  html += "</span>";
  html += `<button class="page-btn" ${safeCurrent === total ? "disabled" : ""} onclick="${onPageChange}(${safeCurrent + 1})">→</button>`;
  html += `<button class="page-btn" ${safeCurrent === total ? "disabled" : ""} onclick="${onPageChange}(${total})">»</button>`;

  container.innerHTML = html;
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
      <div class="mono u-text-muted">ID: ${escapeHtml(r.uid || "-")}</div>
    </td>
    <td>
      ${r.is_owner ? '<span class="badge badge-primary">OWNER</span>' : '<span class="badge">USER</span>'}
      ${r.is_authorized ? '<span class="badge badge-success">Authorized</span>' : '<span class="badge badge-danger">Unauthorized</span>'}
    </td>
    <td class="mono">${escapeHtml(r.last_seen || "-")}</td>
    <td class="mono">${escapeHtml(r.source || "-")}</td>
    <td>
      <div class="u-flex-gap-6">
        <button class="u-btn-compact" onclick="openUserDetail('${escapeHtml(String(r.uid || ""))}')">Details</button>
        ${!r.is_owner ? `<button class="btn-danger u-btn-compact" onclick="setUserAccess('${escapeHtml(String(r.uid || ""))}', false)">Revoke</button>` : ""}
      </div>
    </td>`;
}

function renderAuthorizedUsersTable(users) {
  const body = qs("authorizedUsersBody");
  if (!body) return;

  if (!users.length) {
    body.innerHTML = '<tr data-key="__empty"><td colspan="5" class="table-empty-cell">No matching authorized users</td></tr>';
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
      tr.innerHTML = '<td colspan="5" class="table-empty-cell">No matching authorized users</td>';
      return tr;
    }
  );
}

function renderAuthorizedUsersCards(users) {
  const cardRoot = qs("authorizedUsersCards");
  if (!cardRoot) return;

  if (!users.length) {
    cardRoot.innerHTML = '<div class="mobile-empty-card">No matching authorized users</div>';
    return;
  }

  cardRoot.innerHTML = users.map((r) => `
    <article class="mobile-card" data-key="${escapeHtml(r.uid || "")}">
      <div class="mobile-card-head">
        <div>
          <div class="u-fw-700">${escapeHtml(normalizeIdentity(r.identity || "-"))}</div>
          <div class="mono u-text-muted">ID: ${escapeHtml(r.uid || "-")}</div>
        </div>
      </div>
      <div class="mobile-card-meta">
        <div class="mobile-meta-row">${r.is_owner ? '<span class="badge badge-primary">OWNER</span>' : '<span class="badge">USER</span>'} ${r.is_authorized ? '<span class="badge badge-success">Authorized</span>' : '<span class="badge badge-danger">Unauthorized</span>'}</div>
        <div class="mobile-meta-row mono">Active: ${escapeHtml(r.last_seen || "-")}</div>
        <div class="mobile-meta-row mono">Source: ${escapeHtml(r.source || "-")}</div>
      </div>
      <div class="mobile-card-actions">
        <button class="u-btn-compact" onclick="openUserDetail('${escapeHtml(String(r.uid || ""))}')">Details</button>
        ${!r.is_owner ? `<button class="btn-danger u-btn-compact" onclick="setUserAccess('${escapeHtml(String(r.uid || ""))}', false)">Revoke</button>` : ""}
      </div>
    </article>
  `).join("");
}

function auditRowKey(r, idx) {
  return String(r.id || `${r.uid || "unknown"}-${r.ts || "0"}-${r.source || "s"}-${idx}`);
}

function patchAuditRow(tr, r, rowKey) {
  const auditCell = buildAuditUrlCell(r.urls || [], rowKey);
  tr.innerHTML = `
    <td><div class="u-fw-700">${escapeHtml(normalizeIdentity(r.identity || "-"))}</div></td>
    <td class="mono">${escapeHtml(r.ts || "-")}</td>
    <td><span class="badge badge-primary audit-source-badge">${escapeHtml(r.source || "-")}</span></td>
    <td class="audit-url-col">${auditCell}</td>`;
}

function renderRecentChecksTable(rows) {
  const body = qs("recentChecksBody");
  if (!body) return;

  if (!rows.length) {
    body.innerHTML = '<tr data-key="__empty"><td colspan="4" class="table-empty-cell">No matching checks</td></tr>';
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
      tr.innerHTML = '<td colspan="4" class="table-empty-cell">No matching checks</td>';
      return tr;
    }
  );
}

function renderRecentChecksCards(rows) {
  const cardRoot = qs("recentChecksCards");
  if (!cardRoot) return;

  if (!rows.length) {
    cardRoot.innerHTML = '<div class="mobile-empty-card">No matching checks</div>';
    return;
  }

  cardRoot.innerHTML = rows.map((r, idx) => `
    <article class="mobile-card" data-key="${escapeHtml(auditRowKey(r, idx))}">
      <div class="mobile-card-head">
        <div class="u-fw-700">${escapeHtml(normalizeIdentity(r.identity || "-"))}</div>
      </div>
      <div class="mobile-card-meta">
        <div class="mobile-meta-row mono">Time: ${escapeHtml(r.ts || "-")}</div>
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

async function loadOverview() {
  const data = await apiRequest("/api/v1/system/overview");
  if (!data) return;
  qs("mTotalSubs").textContent = data.total_subs ?? "-";
  qs("mUsers").textContent = data.authorized_users ?? "-";
  qs("mActive").textContent = data.active_24h ?? "-";
  qs("mExports").textContent = data.exports_24h ?? "-";
}

async function loadAuthorizedUsers(page = 1, options = {}) {
  const token = ++usersRequestToken;
  const data = await apiRequest(`/api/v1/users/authorized?page=${page}&limit=${state.limit}`);
  if (!data || token !== usersRequestToken) return;

  state.usersPage = clampPage(data.page || page, data.total_pages || 1);
  const users = Array.isArray(data.users) ? data.users : [];

  if (options.adjustOnEmpty && state.usersPage > 1 && users.length === 0) {
    await loadAuthorizedUsers(state.usersPage - 1, options);
    return;
  }

  renderAuthorizedUsersTable(users);
  renderAuthorizedUsersCards(users);
  renderPagination("usersPagination", state.usersPage, data.total_pages || 1, "window._goUsersPage", Number(data.total || 0));

  qs("publicAccessDesc").innerHTML = `Current: ${data.allow_all_users ? '<span class="public-access-open">OPEN</span>' : '<span class="public-access-closed">RESTRICTED</span>'}`;
  window.__allowAllUsers = !!data.allow_all_users;
}

window._goUsersPage = (p) => loadAuthorizedUsers(p);
window._goAuditPage = (p) => loadRecentChecks(p, { syncUrl: true });
window._goExportsPage = (p) => loadRecentExports(p);

async function loadRecentChecks(page = 1, options = {}) {
  const snapshot = options.snapshot || state.auditSnapshot || collectAuditFilters();
  state.auditSnapshot = snapshot;
  if (options.syncUrl !== false) writeAuditStateToUrl(snapshot, page);

  const token = ++auditRequestToken;
  const params = buildAuditParams(snapshot, page);
  const data = await apiRequest(`/api/v1/audit/recent-checks?${params.toString()}`);
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
  renderPagination("auditPagination", state.auditPage, totalPages, "window._goAuditPage", Number(data.total || rows.length));
}

function fmtUptime(seconds) {
  const s = Math.max(0, Number(seconds || 0));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  return d > 0 ? `${d}d ${h}h ${m}m` : `${h}h ${m}m`;
}

async function loadRuntime() {
  const data = await apiRequest("/api/v1/system/runtime");
  if (!data) return;
  qs("runtimeBody").innerHTML = [
    { k: "Run mode", v: data.run_mode },
    { k: "Uptime", v: fmtUptime(data.uptime_seconds) },
    { k: "Auth backend", v: data.auth_backend },
    { k: "Public mode", v: data.allow_all_users ? "ON" : "OFF" },
    { k: "Parser", v: data.parser_ready ? "Ready" : "Error" },
    { k: "Storage", v: data.storage_ready ? "Ready" : "Error" },
  ]
    .map((i) => `<div class="runtime-item"><div class="k">${i.k}</div><div class="v">${i.v}</div></div>`)
    .join("");
}

async function loadAlerts() {
  const data = await apiRequest("/api/v1/audit/alerts");
  if (!data) return;
  const el = qs("alertsBody");
  const alerts = Array.isArray(data.alerts) ? data.alerts : [];

  if (!alerts.length) {
    el.innerHTML = '<div class="panel-empty-hint">No alerts.</div>';
    return;
  }

  const capped = alerts.slice(0, 50);
  const note = alerts.length > capped.length ? `<div class="alert-limit-note">Showing first ${capped.length} alerts of ${alerts.length}.</div>` : "";
  el.innerHTML =
    note +
    capped
      .map(
        (a) => `
      <div class="alert ${escapeHtml(String(a.severity || "low"))}">
        <div class="alert-content">
          <div class="alert-title">[${escapeHtml(String(a.severity || "").toUpperCase())}] ${escapeHtml(a.title || "")}</div>
          <div class="alert-desc">${escapeHtml(a.detail || "")}</div>
        </div>
      </div>`
      )
      .join("");
}

async function loadAuditSummary() {
  const mode = qs("auditMode")?.value || "others";
  const data = await apiRequest(`/api/v1/audit/summary?mode=${encodeURIComponent(mode)}`);
  if (!data) return;
  qs("auditSummaryBody").innerHTML = [
    { l: "Mode", v: data.title },
    { l: "24h checks", v: data.check_count },
    { l: "24h users", v: data.user_count },
    { l: "24h urls", v: data.url_count },
  ]
    .map((i) => `<div class="audit-summary-item"><span class="audit-summary-label">${i.l}</span><span class="audit-summary-value">${i.v}</span></div>`)
    .join("");
}

async function loadRecentExports(page = 1) {
  const token = ++exportsRequestToken;
  const data = await apiRequest(`/api/v1/exports/recent?scope=others&limit=${state.exportsLimit}&page=${page}`);
  if (!data || token !== exportsRequestToken) return;

  const rows = Array.isArray(data.rows) ? data.rows : [];
  const totalPages = data.total_pages || Math.max(1, Math.ceil(Number(data.total || rows.length) / state.exportsLimit));
  state.exportsPage = clampPage(page, totalPages);

  const el = qs("recentExportsBody");
  if (!rows.length) {
    el.innerHTML = '<div class="panel-empty-hint panel-empty-tight">No export records</div>';
  } else {
    el.innerHTML = rows
      .map(
        (r) => `
      <div class="recent-export-item">
        <div class="recent-export-identity">${escapeHtml(normalizeIdentity(r.identity || "-"))}</div>
        <div class="recent-export-meta">
          <span class="badge badge-primary">${escapeHtml(r.fmt || "-")}</span>
          <span class="mono recent-export-ts">${escapeHtml(r.ts || "-")}</span>
        </div>
        <div class="mono recent-export-target">${escapeHtml(r.target || "-")}</div>
      </div>`
      )
      .join("");
  }

  renderPagination("exportsPagination", state.exportsPage, totalPages, "window._goExportsPage", Number(data.total || rows.length));
}

async function confirmAction(message, title = "Confirm Action", dangerLabel = "Confirm") {
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
  setStatus(`Public access ${data.enabled ? "enabled" : "disabled"}`, "ok");
  await loadAuthorizedUsers(state.usersPage);
}

async function revokeAllSessions() {
  const ok = await confirmAction("This will revoke all active admin sessions, including yours.", "Revoke Sessions", "Revoke");
  if (!ok) return;
  const data = await apiRequest("/api/v1/system/sessions/revoke-all", { method: "POST" });
  if (!data) return;
  setStatus(`Revoked ${data.revoked} sessions`, "ok");
  setTimeout(() => {
    window.location.href = "/admin/login";
  }, 1200);
}

async function setUserAccess(uid, enabled) {
  const safeUid = String(uid || "").trim();
  if (!safeUid) {
    setStatus("Please input UID", "warn");
    return;
  }

  await apiRequest("/api/v1/users/access", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ uid: safeUid, enabled }),
  });

  setStatus(enabled ? "Granted" : "Revoked", "ok");
  await Promise.all([loadAuthorizedUsers(state.usersPage, { adjustOnEmpty: !enabled }), loadOverview()]);
}

async function openUserDetail(uid) {
  const safeUid = String(uid || "").trim();
  if (!safeUid) {
    setStatus("Please input UID", "warn");
    return;
  }

  const modal = qs("userDetailModal");
  const body = qs("userDetailBody");
  const title = qs("userDetailTitle");
  if (!modal || !body || !title) return;

  const token = ++detailRequestToken;
  title.textContent = `User detail: ${safeUid}`;
  body.innerHTML = '<div class="modal-skeleton">Loading...</div>';
  modal.showModal();

  try {
    const data = await apiRequest(`/api/v1/users/detail?uid=${encodeURIComponent(safeUid)}`);
    if (!data || token !== detailRequestToken) return;

    title.textContent = `User detail: ${escapeHtml(data.identity || safeUid)}`;
    const subs = Array.isArray(data.subscriptions) ? data.subscriptions : [];
    const truncated = Number(data.subscription_count || subs.length) > subs.length;
    const truncatedBlock = truncated
      ? `<div class="modal-warning">Only ${subs.length} subscriptions are shown (server-side limited).</div>`
      : "";

    const subHtml = subs.length
      ? subs
          .map(
            (s) => `
          <div class="subscription-item">
            <div class="subscription-name">${escapeHtml(s.name || "-")}</div>
            <div class="mono subscription-url">${escapeHtml(s.url || "-")}</div>
            <div class="subscription-meta">Updated: ${escapeHtml(s.updated_at || "-")} | Expire: ${escapeHtml(s.expire_time || "-")}</div>
          </div>`
          )
          .join("")
      : '<div class="panel-empty-hint panel-empty-tight">No subscription data</div>';

    body.innerHTML = `
      ${truncatedBlock}
      <div class="user-detail-grid">
        <div class="runtime-item"><div class="k">UID</div><div class="v">${escapeHtml(data.uid || "-")}</div></div>
        <div class="runtime-item"><div class="k">Role</div><div class="v">${data.is_owner ? "Owner" : "User"}</div></div>
        <div class="runtime-item"><div class="k">Subscriptions</div><div class="v">${escapeHtml(String(data.subscription_count || 0))}</div></div>
        <div class="runtime-item"><div class="k">Last Seen</div><div class="v">${escapeHtml(data.last_seen || "-")}</div></div>
      </div>
      <h4>Subscriptions</h4>
      ${subHtml}
    `;
  } catch (e) {
    body.innerHTML = `<div class="panel-empty-hint">${escapeHtml(e.message || "Load failed")}</div>`;
  }
}

async function uploadOwnerFile(path, file) {
  const form = new FormData();
  form.append("file", file, file.name || "upload.bin");
  const resp = await fetch(path, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (resp.status === 401) {
    window.location.href = "/admin/login";
    return null;
  }
  const data = await resp.json();
  if (!resp.ok || !data.ok) throw new Error(data.error || "Request failed");
  return data.data;
}

async function runOwnerImport(file) {
  const data = await uploadOwnerFile("/api/v1/owner/import-json", file);
  if (!data) return;
  setStatus(`Import done: ${data.imported}`, "ok");
  await refreshAll();
}

async function runOwnerRestore(file) {
  const ok = await confirmAction("Restore may overwrite current data. Continue?", "Restore Backup", "Restore");
  if (!ok) return;
  const data = await uploadOwnerFile("/api/v1/owner/restore", file);
  if (!data) return;
  setStatus(`Restore done: ${data.restored_files}`, "ok");
  await refreshAll();
}

async function runOwnerCheckAll() {
  const ok = await confirmAction("Run full check now? This may take a while.", "Full Check", "Run");
  if (!ok) return;
  setStatus("Running full check...", "", { sticky: true });
  const data = await apiRequest("/api/v1/owner/check-all", { method: "POST" });
  if (!data) return;
  setStatus(`Full check finished: success ${data.success} / failed ${data.failed}`, "ok");
  await refreshAll();
}

async function refreshAll() {
  setStatus("Refreshing...", "", { sticky: true });
  try {
    await Promise.all([
      loadOverview(),
      loadRuntime(),
      loadAuthorizedUsers(state.usersPage || 1),
      loadRecentChecks(state.auditPage || 1, { syncUrl: false }),
      loadAlerts(),
      loadAuditSummary(),
      loadRecentExports(state.exportsPage || 1),
    ]);
    setStatus("Synced", "ok");
  } catch (_) {
    // handled in apiRequest
  }
}

function bindEvents() {
  qs("refreshBtn").onclick = refreshAll;
  qs("logoutBtn").onclick = () => apiRequest("/admin/logout", { method: "POST" }).then(() => (window.location.href = "/admin/login"));

  qs("openQuickAuthBtn").onclick = () => toggleQuickAuthPanel();
  qs("loadUsersTableBtn").onclick = () => loadAuthorizedUsers(state.usersPage || 1);

  qs("quickGrantBtn").onclick = () => {
    const uid = getQuickUid();
    if (!uid) return setStatus("Please input UID", "warn");
    setUserAccess(uid, true);
    toggleQuickAuthPanel(false);
  };
  qs("quickRevokeBtn").onclick = () => {
    const uid = getQuickUid();
    if (!uid) return setStatus("Please input UID", "warn");
    setUserAccess(uid, false);
    toggleQuickAuthPanel(false);
  };
  qs("quickDetailBtn").onclick = () => {
    const uid = getQuickUid();
    if (!uid) return setStatus("Please input UID", "warn");
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

  qs("exportCsvBtn").onclick = () => {
    const snapshot = state.auditSnapshot || collectAuditFilters();
    window.location.href = `/api/v1/audit/export?format=csv&${buildAuditExportQuery(snapshot)}`;
  };
  qs("exportJsonBtn").onclick = () => {
    const snapshot = state.auditSnapshot || collectAuditFilters();
    window.location.href = `/api/v1/audit/export?format=json&${buildAuditExportQuery(snapshot)}`;
  };

  qs("togglePublicBtn").onclick = togglePublicAccess;
  qs("revokeSessionsBtn").onclick = revokeAllSessions;

  qs("ownerExportJsonBtn").onclick = () => {
    setStatus("Downloading JSON export...", "", { autoHideMs: 1800 });
    window.location.href = "/api/v1/owner/export-json";
  };
  qs("ownerBackupBtn").onclick = () => {
    setStatus("Preparing ZIP backup...", "", { autoHideMs: 1800 });
    window.location.href = "/api/v1/owner/backup";
  };
  qs("ownerImportJsonBtn").onclick = () => qs("ownerImportFile").click();
  qs("ownerRestoreBtn").onclick = () => qs("ownerRestoreFile").click();
  qs("ownerCheckAllBtn").onclick = runOwnerCheckAll;

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

  document.addEventListener("click", async (event) => {
    const btn = event.target.closest(".audit-copy-btn");
    if (btn) {
      const encoded = btn.getAttribute("data-copy") || "";
      let textToCopy = "";
      try { textToCopy = decodeURIComponent(encoded); } catch { textToCopy = encoded; }
      if (!textToCopy) return;
      try { await navigator.clipboard.writeText(textToCopy); setStatus("Copied", "ok"); }
      catch { setStatus("Copy failed", "warn"); }
      return;
    }

    const panel = qs("quickAuthPanel");
    const trigger = qs("openQuickAuthBtn");
    if (panel && !panel.hidden && !panel.contains(event.target) && trigger && !trigger.contains(event.target)) {
      panel.hidden = true;
    }
  });
}

function init() {
  const restored = readAuditStateFromUrl();
  state.auditSnapshot = restored.snapshot;
  state.auditPage = restored.page;
  applyAuditFilters(restored.snapshot);
  bindEvents();
  refreshAll();
}

init();
