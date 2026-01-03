const qs = (selector) => document.querySelector(selector);
const TOKEN_KEY = "udemy_web_token";
const CREDENTIAL_KEY = "udemy_login_remember";
const REMEMBER_DURATION_MS = 7 * 24 * 60 * 60 * 1000; // 7 days

async function request(url, payload) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    let detail = err.detail;
    if (Array.isArray(detail)) {
      detail = detail.map((item) => item.msg || JSON.stringify(item)).join("；");
    } else if (detail && typeof detail === "object") {
      detail = detail.msg || JSON.stringify(detail);
    }
    throw new Error(detail || "登录失败，请重试");
  }
  return res.json();
}

function saveCredentialsIfNeeded(username, password, shouldRemember) {
  if (!shouldRemember) {
    localStorage.removeItem(CREDENTIAL_KEY);
    return;
  }
  const payload = {
    username,
    password,
    expiresAt: Date.now() + REMEMBER_DURATION_MS,
  };
  localStorage.setItem(CREDENTIAL_KEY, JSON.stringify(payload));
}

function loadRememberedCredentials() {
  const raw = localStorage.getItem(CREDENTIAL_KEY);
  if (!raw) return;
  try {
    const data = JSON.parse(raw);
    if (!data.expiresAt || Date.now() > data.expiresAt) {
      localStorage.removeItem(CREDENTIAL_KEY);
      return;
    }
    if (data.username) {
      qs("#login-username").value = data.username;
    }
    if (data.password) {
      qs("#login-password").value = data.password;
    }
    const checkbox = qs("#remember-login");
    if (checkbox) checkbox.checked = true;
  } catch {
    localStorage.removeItem(CREDENTIAL_KEY);
  }
}

async function handleLogin(event) {
  event.preventDefault();
  const errorEl = qs("#login-error");
  errorEl.textContent = "";

  const payload = {
    username: qs("#login-username").value.trim(),
    password: qs("#login-password").value.trim(),
  };
  const shouldRemember = qs("#remember-login")?.checked;

  try {
    const data = await request("/api/login", payload);
    localStorage.setItem(TOKEN_KEY, data.token);
    saveCredentialsIfNeeded(payload.username, payload.password, shouldRemember);
    window.location.href = "/dashboard";
  } catch (err) {
    errorEl.textContent = err.message;
  }
}

function toggleVisibility(e) {
  const targetId = e.currentTarget.dataset.target;
  const input = qs(`#${targetId}`);
  if (!input) return;
  const showing = input.type === "text";
  input.type = showing ? "password" : "text";
  e.currentTarget.textContent = showing ? "👁" : "🙈";
}

document.addEventListener("DOMContentLoaded", () => {
  loadRememberedCredentials();
  qs("#login-form").addEventListener("submit", handleLogin);
  document.querySelectorAll(".toggle-visibility").forEach((btn) => btn.addEventListener("click", toggleVisibility));
});
