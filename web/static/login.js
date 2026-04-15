const form = document.getElementById("loginForm");
const errorText = document.getElementById("errorText");
const username = document.getElementById("username");
const password = document.getElementById("password");
const submitBtn = form.querySelector('button[type="submit"]');

let isSubmitting = false;

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
  const host = document.querySelector(".page-container");
  if (!(host instanceof HTMLElement)) return;
  ensureCyberBackdropLayers(host);

  const canvas = document.createElement("canvas");
  canvas.className = "matrix-rain-canvas";
  canvas.setAttribute("aria-hidden", "true");
  host.appendChild(canvas);

  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const isMobile = window.matchMedia("(max-width: 700px)").matches;
  const fontSize = isMobile ? 14 : 15;
  const step = isMobile ? 18 : 19;
  const frameInterval = prefersReduced ? 150 : (isMobile ? 75 : 50);
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
    drops = Array.from({ length: columns }, () => -Math.floor(Math.random() * 20));
  };

  const render = (ts) => {
    rafId = window.requestAnimationFrame(render);
    if (ts - lastTs < frameInterval) return;
    lastTs = ts;
    const width = host.clientWidth;
    const height = host.clientHeight;
    ctx.fillStyle = "rgba(2, 9, 14, 0.2)";
    ctx.fillRect(0, 0, width, height);

    for (let i = 0; i < drops.length; i += 1) {
      const char = glyphs[(Math.random() * glyphs.length) | 0];
      const x = i * step;
      const y = drops[i] * step;
      ctx.fillStyle = Math.random() > 0.85 ? "rgba(128, 255, 194, 0.9)" : "rgba(36, 224, 142, 0.72)";
      ctx.fillText(char, x, y);
      if (y > height + step && Math.random() > 0.978) drops[i] = -2;
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

function clearError() {
  errorText.textContent = "";
  errorText.className = "toast error";
}

function showError(message) {
  errorText.textContent = message;
  errorText.className = "toast error show";
}

function setSubmitting(loading) {
  isSubmitting = !!loading;
  submitBtn.disabled = isSubmitting;
  submitBtn.textContent = isSubmitting ? "Authenticating..." : "Enter Console";
}

async function probeSessionAndRedirect() {
  try {
    const resp = await fetch("/api/v1/system/overview", {
      method: "GET",
      credentials: "include"
    });
    if (!resp.ok) return;
    const data = await resp.json();
    if (data && data.ok) {
      window.location.replace("/admin");
    }
  } catch (_) {
    // ignore probe errors
  }
}

username.focus();
initMatrixRain();
probeSessionAndRedirect();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (isSubmitting) return;

  clearError();
  setSubmitting(true);
  try {
    const resp = await fetch("/admin/login", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: username.value.trim(),
        password: password.value
      })
    });
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      showError("Login failed: " + (data.error || "unknown"));
      return;
    }
    window.location.href = data.redirect || "/admin";
  } catch (err) {
    showError("Login failed: " + String(err));
  } finally {
    setSubmitting(false);
  }
});
