const form = document.getElementById("loginForm");
    const errorText = document.getElementById("errorText");
    const username = document.getElementById("username");
    const password = document.getElementById("password");

    function clearError() {
      errorText.textContent = "";
      errorText.className = "toast error";
    }

    function showError(message) {
      errorText.textContent = message;
      errorText.className = "toast error show";
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      clearError();
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
          showError("登录失败: " + (data.error || "unknown"));
          return;
        }
        window.location.href = data.redirect || "/admin";
      } catch (err) {
        showError("登录失败: " + String(err));
      }
    });
