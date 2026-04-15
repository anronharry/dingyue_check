const form = document.getElementById("loginForm");
const errorText = document.getElementById("errorText");
const username = document.getElementById("username");
const password = document.getElementById("password");
const submitBtn = form.querySelector('button[type="submit"]');

let isSubmitting = false;

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
