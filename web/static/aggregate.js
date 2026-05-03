const qs = (id) => document.getElementById(id);

let aggregateBaseUrl = "";
let aggregateUrls = { raw: "", base64: "", yaml: "" };
let aggregateFormat = "raw";

function redirectToLogin() {
  window.location.href = "/admin/login";
}

async function authFetch(path, options = {}) {
  const resp = await fetch(path, { credentials: "include", ...options });
  if (resp.status === 401) {
    redirectToLogin();
    return null;
  }
  return resp;
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

function numberText(value, digits = 0) {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return "0";
  return digits > 0 ? num.toFixed(digits) : String(Math.trunc(num));
}

function signedNumberText(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return "0";
  if (num > 0) return `+${Math.trunc(num)}`;
  return String(Math.trunc(num));
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
    btn.classList.toggle("btn-brand", aggregateFormat === value);
  });
  const input = qs("aggregateUrlInput");
  if (input) input.value = buildAggregateUrlWithFormat(aggregateBaseUrl, aggregateFormat);
}

function fillStats(data) {
  const buildStats = data.build_stats || {};
  const snapshot = data.pool_snapshot || {};
  qs("statNodeCount").textContent = numberText(data.node_count);
  qs("statTotalSubs").textContent = numberText(buildStats.total_subscriptions);
  qs("statEligibleSubs").textContent = numberText(buildStats.eligible_subscriptions);
  qs("statParsedOk").textContent = numberText(buildStats.parsed_ok);
  qs("statParsedFailed").textContent = numberText(buildStats.parsed_failed);
  qs("statTimedOut").textContent = numberText(buildStats.timed_out);
  qs("statStablePool").textContent = numberText(snapshot.stable_pool_nodes);
  qs("statVerifyAlive").textContent = numberText(snapshot.verify_alive);
  qs("statCacheHits").textContent = numberText(snapshot.cache_hits);
  qs("statPromoted").textContent = numberText(snapshot.promoted_stable_nodes);
  qs("statEvicted").textContent = numberText(snapshot.evicted_nodes);
  qs("statHealthScore").textContent = numberText(snapshot.average_health_score, 1);
}

function fillMeta(data) {
  const snapshot = data.pool_snapshot || {};
  qs("generatedAt").textContent = data.generated_at ? formatLocalDateTime(new Date(Number(data.generated_at) * 1000).toISOString()) : "-";
  qs("versionTag").textContent = String(data.version || "-");
  qs("lastError").textContent = String(data.last_error || "-");
  qs("lastErrorAt").textContent = data.last_error_at ? formatLocalDateTime(new Date(Number(data.last_error_at) * 1000).toISOString()) : "-";
  qs("verifyMode").textContent = String(snapshot.verify_mode || "-");
  qs("cachedNodes").textContent = numberText(snapshot.cached_nodes);
  qs("cacheAge").textContent = `${numberText(data.cache_age_seconds)} s`;
}

function fillSummary(data) {
  const buildStats = data.build_stats || {};
  const snapshot = data.pool_snapshot || {};
  const summary = [
    `当前发布 ${numberText(data.node_count)} 条`,
    `稳定池 ${numberText(snapshot.stable_pool_nodes)} 条`,
    `验证通过 ${numberText(snapshot.verify_alive)} 条`,
    `缓存命中 ${numberText(snapshot.cache_hits)} / 测试 ${numberText(snapshot.tested_nodes)}`,
    `合格订阅 ${numberText(buildStats.eligible_subscriptions)} / ${numberText(buildStats.total_subscriptions)}`,
  ].join(" | ");
  qs("heroSummary").textContent = summary;
}

function fillUrlCards() {
  qs("rawUrlPreview").textContent = aggregateUrls.raw || "-";
  qs("base64UrlPreview").textContent = aggregateUrls.base64 || "-";
  qs("yamlUrlPreview").textContent = aggregateUrls.yaml || "-";
  syncFormatButtons();
}

function fillPoolMetrics(data) {
  const snapshot = data.pool_snapshot || {};
  const layers = snapshot.layer_counts || {};
  const rows = [
    ["缓存节点", numberText(snapshot.cached_nodes)],
    ["缓存存活", numberText(snapshot.cached_alive_nodes)],
    ["缓存稳定", numberText(snapshot.stable_cached_nodes)],
    ["已淘汰缓存", numberText(snapshot.evicted_cached_nodes)],
    ["Quick 测试", numberText(snapshot.tested_nodes)],
    ["Mihomo 验证", `${numberText(snapshot.verify_alive)} / ${numberText(snapshot.verify_attempted)}`],
    ["Stable 层", numberText(layers.stable)],
    ["Warm 层", numberText(layers.warm)],
    ["Fresh 层", numberText(layers.fresh)],
  ];
  const box = qs("poolMetrics");
  box.innerHTML = rows.map(([label, value]) => `
    <div class="metric-item">
      <span>${label}</span>
      <strong>${value}</strong>
    </div>
  `).join("");
}

function fillDiagnostics(data) {
  const timings = ((data.pool_snapshot || {}).timings_ms) || {};
  const delta = ((data.pool_snapshot || {}).delta) || {};
  const rows = [
    ["解析", `${numberText(timings.parse)} ms`],
    ["Quick", `${numberText(timings.quick_filter)} ms`],
    ["Verify", `${numberText(timings.verify_filter)} ms`],
    ["渲染", `${numberText(timings.render)} ms`],
    ["写缓存", `${numberText(timings.write_cache)} ms`],
    ["总耗时", `${numberText(timings.prewarm_total || timings.refresh_total || timings.build_total || timings.collect_total)} ms`],
    ["发布变化", signedNumberText(delta.published_nodes)],
    ["稳定变化", signedNumberText(delta.stable_pool_nodes)],
    ["验证变化", signedNumberText(delta.verify_alive)],
    ["缓存变化", signedNumberText(delta.cached_nodes)],
  ];
  const box = qs("timingMetrics");
  box.innerHTML = rows.map(([label, value]) => `
    <div class="metric-item">
      <span>${label}</span>
      <strong>${value}</strong>
    </div>
  `).join("");
}

function fillSources(data) {
  const rows = Array.isArray((data.pool_snapshot || {}).top_sources) ? data.pool_snapshot.top_sources : [];
  const box = qs("sourceList");
  if (!rows.length) {
    box.innerHTML = '<div class="source-item"><strong>暂无数据</strong><p>当前还没有可展示的订阅源质量快照。</p></div>';
    return;
  }
  box.innerHTML = rows.map((row) => `
    <article class="source-item">
      <div class="source-head">
        <strong>${String(row.source || "unknown")}</strong>
        <span>${numberText(row.reputation_score)} 分</span>
      </div>
      <p>订阅 ${numberText(row.eligible_subscriptions)} / ${numberText(row.subscriptions)} | 解析 ${numberText(row.parsed_ok)} 成功, ${numberText(row.parsed_failed)} 失败, ${numberText(row.timed_out)} 超时</p>
      <p>节点 ${numberText(row.parsed_nodes)} 收集 | 候选 ${numberText(row.candidate_nodes)} | Quick ${numberText(row.quick_alive)} | Verify ${numberText(row.verified_alive)} | Stable ${numberText(row.stable_nodes)} | Publish ${numberText(row.published_nodes)}</p>
    </article>
  `).join("");
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
        <p>订阅 ${numberText(row.eligible_subscriptions)} / ${numberText(row.total_subscriptions)} | 解析成功 ${numberText(row.parsed_ok)} | 失败 ${numberText(row.parsed_failed)} | 超时 ${numberText(row.timed_out)}</p>
        <p>发布 ${numberText(row.published_nodes)} | 稳定池 ${numberText(row.stable_pool_nodes)} | 验证 ${numberText(row.verify_alive)} / ${numberText(row.verify_attempted)} | 命中 ${numberText(row.cache_hits)}</p>
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
  fillPoolMetrics(data);
  fillDiagnostics(data);
  fillSources(data);
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
  qs("backDashboardBtn").onclick = () => { window.location.href = "/admin"; };
  qs("logoutBtn").onclick = async () => {
    await apiRequest("/admin/logout", { method: "POST" });
    redirectToLogin();
  };
  qs("refreshAggregateBtn").onclick = () => refreshAggregate();
  qs("rotateAggregateBtn").onclick = () => rotateAggregate();
  qs("copyUrlBtn").onclick = () => copyCurrentUrl();
  qs("fmtRawBtn").onclick = () => { aggregateFormat = "raw"; syncFormatButtons(); };
  qs("fmtBase64Btn").onclick = () => { aggregateFormat = "base64"; syncFormatButtons(); };
  qs("fmtYamlBtn").onclick = () => { aggregateFormat = "yaml"; syncFormatButtons(); };
}

async function init() {
  bindEvents();
  await loadAggregateInfo();
}

init().catch((error) => {
  const message = String(error?.message || error || "加载失败");
  const box = qs("historyTimeline");
  if (box) {
    box.innerHTML = `<div class="timeline-item"><strong>加载失败</strong><p>${message}</p></div>`;
  }
});
