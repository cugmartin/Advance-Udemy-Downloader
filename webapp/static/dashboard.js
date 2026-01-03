const qs = (selector) => document.querySelector(selector);
const TOKEN_KEY = "udemy_web_token";
const BEARER_OVERRIDE_KEY = "udemy_bearer_override";

const state = {
  token: localStorage.getItem(TOKEN_KEY),
  activeTask: null,
  eventSource: null,
  defaultBearer: document.body?.dataset?.defaultBearer || "",
};

function ensureAuth() {
  if (!state.token) {
    window.location.href = "/";
    return false;
  }
  return true;
}

function authHeaders() {
  if (!state.token) return {};
  return {
    Authorization: `Bearer ${state.token}`,
  };
}

async function request(url, options = {}) {
  const shouldJson = typeof options.body === "string";
  const res = await fetch(url, {
    ...options,
    headers: {
      ...(shouldJson ? { "Content-Type": "application/json" } : {}),
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    let detail = err.detail;
    if (Array.isArray(detail)) {
      detail = detail.map((item) => item.msg || JSON.stringify(item)).join("；");
    } else if (detail && typeof detail === "object") {
      detail = detail.msg || JSON.stringify(detail);
    }
    throw new Error(detail || "请求失败");
  }
  return res.json();
}

function logout() {
  localStorage.removeItem(TOKEN_KEY);
  state.token = null;
  stopLogStream();
  window.location.href = "/";
}

function collectPayload() {
  const drmPair = qs("#drm-pair").value.trim();
  let keyEntries = [];
  if (drmPair) {
    const [kid, key] = drmPair.split(":").map((val) => val.trim());
    if (kid && key) {
      keyEntries = [{ kid, key }];
    }
  }
  return {
    course_url: qs("#course-url").value.trim(),
    bearer_token: qs("#bearer-token").value.trim(),
    chapter_filter: qs("#chapter-filter").value.trim() || null,
    download_assets: qs("#download-assets").checked,
    auto_zip: qs("#auto-zip").checked,
    download_captions: false,
    download_quizzes: false,
    skip_lectures: false,
    keep_vtt: false,
    skip_hls: false,
    use_h265: false,
    use_nvenc: false,
    use_continuous_lecture_numbers: false,
    key_entries: keyEntries,
  };
}

function getCurrentBearer() {
  const saved = localStorage.getItem(BEARER_OVERRIDE_KEY);
  return saved ?? state.defaultBearer ?? "";
}

async function handlePrecheck() {
  const badge = qs("#precheck-result");
  badge.textContent = "预检中...";
  try {
    const payload = {
      course_url: qs("#course-url").value.trim(),
      bearer_token: qs("#bearer-token").value.trim(),
    };
    const data = await request("/api/precheck", { method: "POST", body: JSON.stringify(payload) });
    badge.textContent = data.is_drm ? "⚠ 检测到 DRM，需提供密钥" : "✔ 非 DRM 课程，可直接下载";
  } catch (err) {
    badge.textContent = err.message;
  }
}

function stopLogStream() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

function formatTaskId(taskId) {
  if (!taskId) return "-";
  return taskId.slice(-6).toUpperCase();
}

function parseUtcDate(value) {
  if (!value) return null;
  const iso = value.endsWith("Z") ? value : `${value}Z`;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatStartTime(startedAt) {
  const date = parseUtcDate(startedAt);
  if (!date) return "-";
  const pad = (n) => String(n).padStart(2, "0");
  const monthDay = `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
  return `${monthDay} ${time}`;
}

async function refreshHistory() {
  const tbody = qs("#history-body");
  tbody.innerHTML = "<tr><td colspan='4'>加载中...</td></tr>";
  try {
    const items = await request("/api/history");
    if (!items.length) {
      tbody.innerHTML = "<tr><td colspan='4'>暂无历史记录</td></tr>";
      return;
    }
    tbody.innerHTML = items
      .map((item) => {
        const isDrm =
          typeof item.is_drm === "boolean" ? (item.is_drm ? "是" : "否") : "-";
        const timeLabel = formatStartTime(item.started_at);
        const taskSuffix = formatTaskId(item.task_id);
        return `
        <tr>
          <td title="${item.course_url}">${item.course_url}</td>
          <td>${item.status}</td>
          <td>${isDrm}</td>
          <td>${timeLabel}${taskSuffix !== "-" ? ` (*${taskSuffix})` : ""}</td>
        </tr>`;
      })
      .join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4">${err.message}</td></tr>`;
  }
}

function appendLog(line) {
  const pre = qs("#log-output");
  pre.textContent += `${line}\n`;
  pre.scrollTop = pre.scrollHeight;
}

function clearLogPanel() {
  const pre = qs("#log-output");
  if (pre) {
    pre.textContent = "";
  }
  const info = qs("#active-task-info");
  if (info) {
    info.textContent = "";
  }
}

function startLogStream(taskId) {
  stopLogStream();
  clearLogPanel();
  qs("#active-task-info").textContent = `监听任务：${taskId}`;
  state.eventSource = new EventSource(`/api/tasks/${taskId}/logs?token=${state.token}`);
  state.eventSource.onmessage = (event) => {
    appendLog(event.data);
  };
  state.eventSource.addEventListener("end", () => {
    stopLogStream();
    clearLogPanel();
    refreshHistory();
  });
  state.eventSource.onerror = () => {
    appendLog("[system] 连接中断");
    stopLogStream();
  };
}

async function startDownload() {
  const payload = collectPayload();
  if (!payload.course_url || !payload.bearer_token) {
    alert("请填写课程 URL 和 Bearer Token");
    return;
  }
  qs("#start-download-btn").disabled = true;
  try {
    const res = await request("/api/download", { method: "POST", body: JSON.stringify(payload) });
    state.activeTask = res.task_id;
    startLogStream(res.task_id);
    await refreshHistory();
    qs("#precheck-result").textContent = "任务已启动";
    localStorage.setItem(BEARER_OVERRIDE_KEY, payload.bearer_token);
  } catch (err) {
    alert(err.message);
  } finally {
    qs("#start-download-btn").disabled = false;
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

function initializeForm() {
  const bearerInput = qs("#bearer-token");
  if (!bearerInput) return;
  bearerInput.value = getCurrentBearer();
}

document.addEventListener("DOMContentLoaded", () => {
  if (!ensureAuth()) return;
  initializeForm();
  qs("#logout-btn").addEventListener("click", logout);
  qs("#precheck-btn").addEventListener("click", handlePrecheck);
  qs("#start-download-btn").addEventListener("click", startDownload);
  document.querySelectorAll(".toggle-visibility").forEach((btn) => btn.addEventListener("click", toggleVisibility));
  refreshHistory();
});
