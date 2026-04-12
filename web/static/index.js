const qs = (id) => document.getElementById(id);
    const statusText = qs("statusText");

    let state = {
        usersPage: 1,
        auditPage: 1,
        limit: 10
    };

    async function apiRequest(path, options = {}) {
      try {
        const resp = await fetch(path, {
            credentials: "include",
            ...options
        });
        if (resp.status === 401) {
            window.location.href = "/admin/login";
            return null;
        }
        const data = await resp.json();
        if (!resp.ok || !data.ok) throw new Error(data.error || "请求失败");
        return data.data;
      } catch (e) {
        setStatus(e.message, "warn");
        throw e;
      }
    }

    function setStatus(text, cls) {
      statusText.className = "status " + (cls || "");
      statusText.textContent = text;
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
      return String(value ?? "")
        .replace(/<[^>]+>/g, " ")
        .replace(/&nbsp;/gi, " ")
        .replace(/&amp;/gi, "&")
        .replace(/&lt;/gi, "<")
        .replace(/&gt;/gi, ">")
        .replace(/&#39;/gi, "'")
        .replace(/&quot;/gi, '"')
        .replace(/\s+/g, " ")
        .trim() || "-";
    }

    function compactUrlLabel(rawUrl) {
      try {
        const u = new URL(String(rawUrl));
        const path = `${u.pathname || "/"}${u.search || ""}`;
        const compactPath = path.length > 86 ? `${path.slice(0, 86)}...` : path;
        return `${u.hostname}${compactPath}`;
      } catch (e) {
        const fallback = String(rawUrl ?? "");
        return fallback.length > 120 ? `${fallback.slice(0, 120)}...` : fallback;
      }
    }

    function buildAuditUrlCell(urls, rowIndex) {
      const list = Array.isArray(urls) ? urls.filter(Boolean) : [];
      if (!list.length) return `<span class="audit-empty">-</span>`;

      const firstRaw = String(list[0]);
      const firstLabel = escapeHtml(compactUrlLabel(firstRaw));
      const summaryText = list.length === 1 ? "1 条链接" : `共 ${list.length} 条链接`;

      const items = list.map((u, idx) => {
        const raw = String(u);
        const href = escapeHtml(raw);
        const full = escapeHtml(raw);
        const copyValue = encodeURIComponent(raw);
        return `<li class="audit-url-item"><div class="audit-url-main"><a href="${href}" target="_blank" rel="noopener noreferrer" class="audit-url-link mono" title="${href}">${full}</a></div><div class="audit-url-actions"><span class="audit-url-tag">#${idx + 1}</span><button type="button" class="audit-copy-btn" data-copy="${copyValue}">复制</button></div></li>`;
      }).join("");

      return `<details class="audit-url-details" id="audit-url-${rowIndex}"><summary class="audit-url-summary"><span>${summaryText}</span><span class="audit-url-hint">点击展开完整链接</span></summary><div class="audit-url-preview mono">${firstLabel}</div><ul class="audit-url-list">${items}</ul></details>`;
    }

    function renderPagination(containerId, current, total, onPageChange) {
        const container = qs(containerId);
        if (total <= 1) {
            container.innerHTML = "";
            return;
        }
        
        let html = `<button class="page-btn" ${current === 1 ? 'disabled' : ''} onclick="${onPageChange}(${current - 1})">←</button>`;
        html += `<span class="page-info">第 ${current} / ${total} 页</span>`;
        html += `<button class="page-btn" ${current === total ? 'disabled' : ''} onclick="${onPageChange}(${current + 1})">→</button>`;
        
        container.innerHTML = html;
    }

    async function loadOverview() {
      const data = await apiRequest("/api/v1/system/overview");
      if (!data) return;
      qs("mTotalSubs").textContent = data.total_subs;
      qs("mUsers").textContent = data.authorized_users;
      qs("mActive").textContent = data.active_24h;
      qs("mExports").textContent = data.exports_24h;
    }

    async function loadAuthorizedUsers(page = 1) {
      const data = await apiRequest(`/api/v1/users/authorized?page=${page}&limit=${state.limit}`);
      if (!data) return;
      state.usersPage = data.page;
      
      const body = qs("authorizedUsersBody");
      if (!data.users.length) {
        body.innerHTML = `<tr><td colspan="5" class="table-empty-cell">暂无满足条件的授权用户</td></tr>`;
      } else {
        body.innerHTML = data.users.map(r => `
          <tr>
            <td>
                <div class="u-fw-700">${escapeHtml(normalizeIdentity(r.identity || "-"))}</div>
                <div class="mono u-text-muted">ID: ${r.uid}</div>
            </td>
            <td>
                ${r.is_owner ? '<span class="badge badge-primary">OWNER</span>' : '<span class="badge">USER</span>'}
                ${r.is_authorized ? '<span class="badge badge-success">已授权</span>' : '<span class="badge badge-danger">未授权</span>'}
            </td>
            <td class="mono">${r.last_seen}</td>
            <td class="mono">${r.source}</td>
            <td>
                <div class="u-flex-gap-6">
                    <button class="u-btn-compact" onclick="openUserDetail('${r.uid}')">详情</button>
                    ${!r.is_owner ? `<button class="btn-danger u-btn-compact" onclick="setUserAccess('${r.uid}', false)">撤销</button>` : ''}
                </div>
            </td>
          </tr>
        `).join("");
      }
      renderPagination("usersPagination", data.page, data.total_pages, "window._goUsersPage");
      
      // Update Public Access Desc
      qs("publicAccessDesc").innerHTML = `当前：${data.allow_all_users ? '<span class="public-access-open">🟢 全员开放</span>' : '<span class="public-access-closed">🔴 限制访问</span>'}`;
      window.__allowAllUsers = data.allow_all_users;
    }

    // Global page handlers for onclick
    window._goUsersPage = (p) => loadAuthorizedUsers(p);
    window._goAuditPage = (p) => loadRecentChecks(p);

    async function loadRecentChecks(page = 1) {
      const q = currentAuditQuery();
      const data = await apiRequest(`/api/v1/audit/recent-checks?page=${page}&limit=${state.limit}&${q}`);
      if (!data) return;
      state.auditPage = page;

      const body = qs("recentChecksBody");
      if (!data.rows.length) {
        body.innerHTML = `<tr><td colspan="4" class="table-empty-cell">找不到相关的检测记录</td></tr>`;
      } else {
        body.innerHTML = data.rows.map((r, rowIndex) => {
          const auditCell = buildAuditUrlCell(r.urls || [], rowIndex);
          return `
            <tr>
              <td><div class="u-fw-700">${escapeHtml(normalizeIdentity(r.identity || "-"))}</div></td>
              <td class="mono">${escapeHtml(r.ts || "-")}</td>
              <td><span class="badge badge-primary audit-source-badge">${escapeHtml(r.source || "-")}</span></td>
              <td class="audit-url-col">${auditCell}</td>
            </tr>
          `;
        }).join("");
      }
      // Calculate total pages for audit
      const totalPages = Math.ceil(data.total / state.limit) || 1;
      renderPagination("auditPagination", page, totalPages, "window._goAuditPage");
    }

    async function loadRuntime() {
      const data = await apiRequest("/api/v1/system/runtime");
      if (!data) return;
      window.__runtimeState = data;
      qs("runtimeBody").innerHTML = [
        {k: '运行模式', v: data.run_mode},
        {k: '运行时长', v: fmtUptime(data.uptime_seconds)},
        {k: '认证后端', v: data.auth_backend},
        {k: '全员模式', v: data.allow_all_users ? '已开启' : '已关闭'},
        {k: '解析引擎', v: data.parser_ready ? '就绪' : '异常'},
        {k: '存储引擎', v: data.storage_ready ? '就绪' : '异常'}
      ].map(i => `<div class="runtime-item"><div class="k">${i.k}</div><div class="v">${i.v}</div></div>`).join("");
    }

    async function loadAlerts() {
      const data = await apiRequest("/api/v1/audit/alerts");
      if (!data) return;
      const el = qs("alertsBody");
      if (!data.alerts.length) {
        el.innerHTML = `<div class="panel-empty-hint">系统运行平稳，无异常告警</div>`;
        return;
      }
      el.innerHTML = data.alerts.map(a => `
        <div class="alert ${a.severity}">
          <div class="alert-content">
            <div class="alert-title">[${a.severity.toUpperCase()}] ${a.title}</div>
            <div class="alert-desc">${a.detail}</div>
          </div>
        </div>
      `).join("");
    }

    async function loadAuditSummary() {
      const mode = qs("auditMode").value;
      const data = await apiRequest(`/api/v1/audit/summary?mode=${encodeURIComponent(mode)}`);
      if (!data) return;
      qs("auditSummaryBody").innerHTML = [
          {l: '当前模式', v: data.title},
          {l: '24h 检测量', v: data.check_count},
          {l: '24h 用户数', v: data.user_count},
          {l: '24h URL 总数', v: data.url_count}
      ].map(i => `<div class="audit-summary-item">
        <span class="audit-summary-label">${i.l}</span><span class="audit-summary-value">${i.v}</span></div>`).join("");
    }

    async function loadRecentExports() {
      const data = await apiRequest("/api/v1/exports/recent?scope=others&limit=10");
      if (!data) return;
      const el = qs("recentExportsBody");
      if (!data.rows.length) {
        el.innerHTML = `<div class="panel-empty-hint panel-empty-tight">无导出记录</div>`;
        return;
      }
      el.innerHTML = data.rows.map(r => `
        <div class="recent-export-item">
            <div class="recent-export-identity">${escapeHtml(normalizeIdentity(r.identity || "-"))}</div>
            <div class="recent-export-meta">
                <span class="badge badge-primary">${r.fmt}</span>
                <span class="mono recent-export-ts">${r.ts}</span>
            </div>
            <div class="mono recent-export-target">${r.target}</div>
        </div>
      `).join("");
    }

    async function togglePublicAccess() {
      const current = window.__allowAllUsers;
      const data = await apiRequest("/api/v1/system/public-access", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ enabled: !current })
      });
      setStatus(`成功：${data.enabled ? "开启" : "关闭"}全员访问`, "ok");
      loadAuthorizedUsers(state.usersPage);
    }

    async function revokeAllSessions() {
      if (!confirm("确定要强制注销所有管理员在线会话吗？您自己也会被踢出。")) return;
      const data = await apiRequest("/api/v1/system/sessions/revoke-all", { method: "POST" });
      setStatus(`已撤消 ${data.revoked} 个活跃会话`, "ok");
      setTimeout(() => window.location.href = "/admin/login", 1500);
    }

    async function setUserAccess(uid, enabled) {
      await apiRequest("/api/v1/users/access", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ uid, enabled })
      });
      setStatus(enabled ? "已授权" : "已撤销授权", "ok");
      loadAuthorizedUsers(state.usersPage);
      loadOverview();
    }

    async function openUserDetail(uid) {
      const data = await apiRequest(`/api/v1/users/detail?uid=${encodeURIComponent(uid)}`);
      if (!data) return;
      qs("userDetailTitle").textContent = `资源画像：${data.identity}`;
      
      const subs = (data.subscriptions || []).map(s => `
        <div class="subscription-item">
            <div class="subscription-name">${s.name}</div>
            <div class="mono subscription-url">${s.url}</div>
            <div class="subscription-meta">更新: ${s.updated_at} | 到期: ${s.expire_time}</div>
        </div>
      `).join("") || "暂无订阅库数据";

      qs("userDetailBody").innerHTML = `
        <div class="user-detail-grid">
            <div class="runtime-item"><div class="k">UID</div><div class="v">${data.uid}</div></div>
            <div class="runtime-item"><div class="k">身份状态</div><div class="v">${data.is_owner ? '管理员' : '普通用户'}</div></div>
            <div class="runtime-item"><div class="k">订阅总数</div><div class="v">${data.subscription_count}</div></div>
            <div class="runtime-item"><div class="k">最近活跃</div><div class="v">${data.last_seen}</div></div>
        </div>
        <h4>订阅库列表</h4>
        ${subs}
      `;
      qs("userDetailModal").showModal();
    }

    function currentAuditQuery() {
      const q = new URLSearchParams();
      q.set("mode", qs("auditMode").value);
      const uid = qs("filterUserId").value.trim();
      const src = qs("filterSource").value.trim();
      const kw = qs("filterQ").value.trim();
      const f = qs("filterFrom").value;
      const t = qs("filterTo").value;
      if (uid) q.set("user_id", uid);
      if (src) q.set("source", src);
      if (kw) q.set("q", kw);
      if (f) q.set("from", f);
      if (t) q.set("to", t);
      return q.toString();
    }

    function fmtUptime(seconds) {
      const s = Math.max(0, Number(seconds || 0));
      const d = Math.floor(s / 86400);
      const h = Math.floor((s % 86400) / 3600);
      const m = Math.floor((s % 3600) / 60);
      return d > 0 ? `${d}天 ${h}时 ${m}分` : `${h}时 ${m}分`;
    }

    async function uploadOwnerFile(path, file) {
      const form = new FormData();
      form.append("file", file, file.name || "upload.bin");
      const resp = await fetch(path, {
        method: "POST",
        credentials: "include",
        body: form
      });
      if (resp.status === 401) {
        window.location.href = "/admin/login";
        return null;
      }
      const data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error(data.error || "请求失败");
      return data.data;
    }

    async function runOwnerImport(file) {
      const data = await uploadOwnerFile("/api/v1/owner/import-json", file);
      if (!data) return;
      setStatus(`导入完成：${data.imported} 条`, "ok");
      await refreshAll();
    }

    async function runOwnerRestore(file) {
      if (!confirm("恢复备份可能覆盖当前数据，确定继续吗？")) return;
      const data = await uploadOwnerFile("/api/v1/owner/restore", file);
      if (!data) return;
      setStatus(`恢复完成：${data.restored_files} 个文件`, "ok");
      await refreshAll();
    }

    async function runOwnerCheckAll() {
      if (!confirm("确定要执行全量体检吗？这可能需要一段时间。")) return;
      setStatus("正在执行全量体检...");
      const data = await apiRequest("/api/v1/owner/check-all", { method: "POST" });
      if (!data) return;
      setStatus(`全量体检完成：成功 ${data.success} / 失败 ${data.failed}`, "ok");
      await refreshAll();
    }
    async function refreshAll() {
      setStatus("数据刷新中...");
      try {
        await Promise.all([
          loadOverview(),
          loadRuntime(),
          loadAuthorizedUsers(1),
          loadRecentChecks(1),
          loadAlerts(),
          loadAuditSummary(),
          loadRecentExports()
        ]);
        setStatus("实时数据已同步", "ok");
      } catch (e) {}
    }

    // Events
    qs("refreshBtn").onclick = refreshAll;
    qs("logoutBtn").onclick = () => apiRequest("/admin/logout", {method:"POST"}).then(()=>window.location.href="/admin/login");
    qs("loadUsersTableBtn").onclick = () => loadAuthorizedUsers(state.usersPage);
    qs("loadChecksBtn").onclick = () => loadRecentChecks(1);
    qs("exportCsvBtn").onclick = () => window.location.href = `/api/v1/audit/export?format=csv&${currentAuditQuery()}`;
    qs("exportJsonBtn").onclick = () => window.location.href = `/api/v1/audit/export?format=json&${currentAuditQuery()}`;
    qs("togglePublicBtn").onclick = togglePublicAccess;
    qs("revokeSessionsBtn").onclick = revokeAllSessions;
    qs("quickGrantBtn").onclick = () => setUserAccess(qs("quickUidInput").value, true);
    qs("quickRevokeBtn").onclick = () => setUserAccess(qs("quickUidInput").value, false);
    qs("quickDetailBtn").onclick = () => openUserDetail(qs("quickUidInput").value);
    qs("closeUserDetailBtn").onclick = () => qs("userDetailModal").close();
    
    qs("ownerExportJsonBtn").onclick = () => {
      setStatus("正在下载 JSON 导出...");
      window.location.href = "/api/v1/owner/export-json";
    };
    qs("ownerBackupBtn").onclick = () => {
      setStatus("正在生成并下载 ZIP 备份...");
      window.location.href = "/api/v1/owner/backup";
    };
    qs("ownerImportJsonBtn").onclick = () => qs("ownerImportFile").click();
    qs("ownerRestoreBtn").onclick = () => qs("ownerRestoreFile").click();
    qs("ownerCheckAllBtn").onclick = runOwnerCheckAll;

    qs("ownerImportFile").onchange = async (event) => {
      const file = event.target.files && event.target.files[0];
      event.target.value = "";
      if (!file) return;
      try {
        await runOwnerImport(file);
      } catch (e) {
        setStatus(e.message || String(e), "warn");
      }
    };

    qs("ownerRestoreFile").onchange = async (event) => {
      const file = event.target.files && event.target.files[0];
      event.target.value = "";
      if (!file) return;
      try {
        await runOwnerRestore(file);
      } catch (e) {
        setStatus(e.message || String(e), "warn");
      }
    };
    document.addEventListener("click", async (event) => {
      const btn = event.target.closest(".audit-copy-btn");
      if (!btn) return;
      const encoded = btn.getAttribute("data-copy") || "";
      let textToCopy = "";
      try {
        textToCopy = decodeURIComponent(encoded);
      } catch (e) {
        textToCopy = encoded;
      }
      if (!textToCopy) return;
      try {
        await navigator.clipboard.writeText(textToCopy);
        setStatus("链接已复制", "ok");
      } catch (e) {
        setStatus("复制失败，请手动复制", "warn");
      }
    });
    // Auto Refresh
    refreshAll();
