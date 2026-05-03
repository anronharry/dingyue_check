const qs = (id) => document.getElementById(id);

let aggregateBaseUrl = "";
let aggregateUrls = { raw: "", base64: "", yaml: "" };
let aggregateFormat = "raw";

function redirectToLogin() {
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
      return data.error || data.message || `请求失败（${resp.status}）`;
    }
    return (await resp.text()) || `请求失败（${resp.status}）`;
  } catch (_) {
    return `请求失败（${resp.status}）`;
  }
}

async function apiRequest(path, options = {}) {
  const resp = await authFetch(path, options);
  if (!resp) return null;
  const data = await resp.json();
  if (!resp.ok || !data.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data.data;
}

function formatLocalDateTime(value) {
  const raw = String(value ?? "").trim();
  if (!raw || raw === "-") return "-";
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

function buildAggregateUrlWithFormat(baseUrl, format) {
  const fmt = format || "raw";
  const direct = aggregateUrls[fmt];
  if (direct) return direct;
  const safeBase = String(baseUrl || "").split("?")[0];
  if (!safeBase) return "";
  if (fmt === "raw") return `${safeBase}/nodes`;
  if (fmt === "base64") return `${safeBase}/base64`;
  return `${safeBase}/clash`;
}

function syncFormatButtons() {
  [
    ["fmtRawBtn", "raw"],
    ["fmtBase64Btn", "base64"],
    ["fmtYamlBtn", "yaml"],
  ].forEach(([id, value]) => {
    const btn = qs(id);
    if (!btn) return;
    if (aggregateFormat === value) btn.classList.add("btn-brand");
    else btn.classList.remove("btn-brand");
  });
  const input = qs("aggregateUrlInput");
  if (input) input.value = buildAggregateUrlWithFormat(aggregateBaseUrl, aggregateFormat);
}

function fillStats(data) {
  const buildStats = data.build_stats || {};
  qs("statNodeCount").textContent = String(Number(data.node_count || 0));
  qs("statTotalSubs").textContent = String(Number(buildStats.total_subscriptions || 0));
  qs("statEligibleSubs").textContent = String(Number(buildStats.eligible_subscriptions || 0));
  qs("statParsedOk").textContent = String(Number(buildStats.parsed_ok || 0));
  qs("statParsedFailed").textContent = String(Number(buildStats.parsed_failed || 0));
  qs("statTimedOut").textContent = String(Number(buildStats.timed_out || 0));
}

function fillMeta(data) {
  qs("generatedAt").textContent = data.generated_at ? formatLocalDateTime(new Date(Number(data.generated_at) * 1000).toISOString()) : "-";
  qs("versionTag").textContent = String(data.version || "-");
  qs("lastError").textContent = String(data.last_error || "-");
  qs("lastErrorAt").textContent = data.last_error_at ? formatLocalDateTime(new Date(Number(data.last_error_at) * 1000).toISOString()) : "-";
}

function fillSummary(data) {
  const buildStats = data.build_stats || {};
  const summary = [
    `当前节点 ${Number(data.node_count || 0)} 条`,
    `合格订阅 ${Number(buildStats.eligible_subscriptions || 0)} / ${Number(buildStats.total_subscriptions || 0)}`,
    `解析成功 ${Number(buildStats.parsed_ok || 0)}`,
    `超时 ${Number(buildStats.timed_out || 0)}`,
  ].join(" | ");
  qs("heroSummary").textContent = summary;
}

function fillUrlCards() {
  qs("rawUrlPreview").textContent = aggregateUrls.raw || "-";
  qs("base64UrlPreview").textContent = aggregateUrls.base64 || "-";
  qs("yamlUrlPreview").textContent = aggregateUrls.yaml || "-";
  syncFormatButtons();
}

function fillHistory(data) {
  const box = qs("historyTimeline");
  const rows = Array.isArray(data.build_history) ? data.build_history.slice().reverse() : [];
  if (!rows.length) {
    box.innerHTML = '<div class="timeline-item"><strong>暂无记录</strong><p>当前还没有可展示的聚合构建历史。</p></div>';
    return;
  }
  box.innerHTML = rows.map((row) => {
    const ts = row.ts ? formatLocalDateTime(new Date(Number(row.ts) * 1000).toISOString()) : "-";
    return `
      <article class="timeline-item">
        <strong>${ts}</strong>
        <p>总订阅 ${Number(row.total_subscriptions || 0)} / 合格 ${Number(row.eligible_subscriptions || 0)} / 成功 ${Number(row.parsed_ok || 0)} / 失败 ${Number(row.parsed_failed || 0)} / 超时 ${Number(row.timed_out || 0)}</p>
      </article>
    `;
  }).join("");
}

async function loadAggregateInfo() {
  const data = await apiRequest("/api/v1/owner/aggregate-subscription");
  if (!data) return;
  aggregateBaseUrl = String(data.url || "").split("?")[0];
  aggregateUrls = {
    raw: String((data.urls && data.urls.nodes) || ""),
    base64: String((data.urls && data.urls.base64) || ""),
    yaml: String((data.urls && data.urls.clash) || ""),
  };
  fillSummary(data);
  fillStats(data);
  fillMeta(data);
  fillUrlCards();
  fillHistory(data);
}

async function refreshAggregate() {
  await apiRequest("/api/v1/owner/aggregate-subscription/refresh", { method: "POST" });
  await loadAggregateInfo();
}

async function rotateAggregate() {
  await apiRequest("/api/v1/owner/aggregate-subscription/rotate", { method: "POST" });
  await loadAggregateInfo();
}

async function copyCurrentUrl() {
  const input = qs("aggregateUrlInput");
  const text = String(input?.value || "");
  if (!text) return;
  await navigator.clipboard.writeText(text);
}

function bindEvents() {
  qs("backDashboardBtn").onclick = () => {
    window.location.href = "/admin";
  };
  qs("logoutBtn").onclick = async () => {
    await apiRequest("/admin/logout", { method: "POST" });
    redirectToLogin();
  };
  qs("refreshAggregateBtn").onclick = () => refreshAggregate();
  qs("rotateAggregateBtn").onclick = () => rotateAggregate();
  qs("copyUrlBtn").onclick = () => copyCurrentUrl();
  qs("fmtRawBtn").onclick = () => {
    aggregateFormat = "raw";
    syncFormatButtons();
  };
  qs("fmtBase64Btn").onclick = () => {
    aggregateFormat = "base64";
    syncFormatButtons();
  };
  qs("fmtYamlBtn").onclick = () => {
    aggregateFormat = "yaml";
    syncFormatButtons();
  };
}

async function init() {
  bindEvents();
  await loadAggregateInfo();
}

init().catch(async (error) => {
  const message = String(error?.message || error || "加载失败");
  const box = qs("historyTimeline");
  if (box) {
    box.innerHTML = `<div class="timeline-item"><strong>加载失败</strong><p>${message}</p></div>`;
  }
});
