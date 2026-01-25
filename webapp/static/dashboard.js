const qs = (selector) => document.querySelector(selector);
const TOKEN_KEY = "udemy_web_token";
const BEARER_OVERRIDE_KEY = "udemy_bearer_override";

const state = {
  token: localStorage.getItem(TOKEN_KEY),
  activeTask: null,
  eventSource: null,
  defaultBearer: document.body?.dataset?.defaultBearer || "",
  historySignature: null,
  activeTasksSignature: null,
  logLines: [],
  logFlushScheduled: false,
};

const LOG_BUFFER_LIMIT = 500;

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

async function refreshHistory(options = {}) {
  const { showLoading = true } = options;
  const tbody = qs("#history-body");
  if (showLoading) {
    tbody.innerHTML = "<tr><td colspan='5'>加载中...</td></tr>";
  }
  try {
    const items = await request("/api/history");
    if (!items.length) {
      tbody.innerHTML = "<tr><td colspan='5'>暂无历史记录</td></tr>";
      return;
    }
    const signature = JSON.stringify(items);
    if (signature === state.historySignature && !showLoading) {
      return;
    }
    state.historySignature = signature;
    tbody.innerHTML = items
      .map((item) => {
        const isDrm =
          typeof item.is_drm === "boolean" ? (item.is_drm ? "是" : "否") : "-";
        const timeLabel = formatStartTime(item.started_at);
        const taskSuffix = formatTaskId(item.task_id);
        const courseCell = `<span class="history-url" title="${item.course_url}">${item.course_url}</span>`;
        const buttons = [];
        if (item.status === "success") {
          buttons.push(
            `<button class="primary ghost small generate-article-btn" data-task-id="${item.task_id}">生成文章</button>`
          );
          buttons.push(
            `<button class="secondary outline small view-article-log" data-task-id="${item.task_id}" data-course-url="${item.course_url}">查看日志</button>`
          );
        } else if (item.status === "生成文章中") {
          buttons.push(`<button class="primary ghost small" disabled>生成中...</button>`);
          buttons.push(
            `<button class="secondary outline small view-article-log" data-task-id="${item.task_id}" data-course-url="${item.course_url}">查看日志</button>`
          );
        } else if (item.article_status === "failed") {
          buttons.push(
            `<button class="primary ghost small generate-article-btn" data-task-id="${item.task_id}">重试生成</button>`
          );
          buttons.push(
            `<button class="secondary outline small view-article-log" data-task-id="${item.task_id}" data-course-url="${item.course_url}">查看日志</button>`
          );
        } else if (item.article_status === "success") {
          buttons.push(
            `<button class="secondary outline small view-article-log" data-task-id="${item.task_id}" data-course-url="${item.course_url}">查看日志</button>`
          );
        }
        const actionCell = buttons.length ? `<div class="history-actions">${buttons.join("")}</div>` : "-";
        return `
        <tr>
          <td>${courseCell}</td>
          <td>${item.status}</td>
          <td>${isDrm}</td>
          <td>${timeLabel}${taskSuffix !== "-" ? ` (*${taskSuffix})` : ""}</td>
          <td>${actionCell}</td>
        </tr>`;
      })
      .join("");
  } catch (err) {
    if (showLoading) {
      tbody.innerHTML = `<tr><td colspan="5">${err.message}</td></tr>`;
    }
  }
}

async function refreshActiveTasks(options = {}) {
  const { showLoading = true } = options;
  const container = qs("#active-task-list");
  if (!container) return;
  if (showLoading) {
    container.textContent = "加载中...";
  }
  try {
    const tasks = await request("/api/tasks");
    const activeTasks = tasks.filter(
      (task) => !["success", "failed", "cancelled"].includes(task.status)
    );
    const signature = JSON.stringify(activeTasks);
    if (signature === state.activeTasksSignature && !showLoading) {
      return;
    }
    state.activeTasksSignature = signature;
    if (!activeTasks.length) {
      container.textContent = "暂无运行中的任务";
      document.body.classList.remove("has-active-task");
      stopLogStream();
      clearLogPanel();
      return;
    }
    document.body.classList.add("has-active-task");
    container.innerHTML = activeTasks
      .map((task) => {
        const { id, course_url, status } = task;
        const statusLabel = status || "-";
        const actionBtn =
          status === "running"
            ? `<button class="secondary small attach-log-btn" data-task-id="${id}">查看日志</button>`
            : status === "queued"
            ? `<button class="secondary small attach-log-btn" data-task-id="${id}">等待中</button>`
            : `<button class="secondary small attach-log-btn" data-task-id="${id}">查看日志</button>`;
        return `<div class="active-task-row">
          <div class="task-info">
            <div class="task-url" title="${course_url || ""}">${course_url || "-"}</div>
            <div class="task-meta">ID: ${formatTaskId(id)} · 状态：${statusLabel}</div>
          </div>
          ${actionBtn}
        </div>`;
      })
      .join("");
  } catch (err) {
    container.textContent = err.message || "加载失败";
  }
}

async function handleHistoryClick(e) {
  const btn = e.target.closest(".generate-article-btn");
  if (!btn) return;
  const taskId = btn.dataset.taskId;
  if (!taskId) return;
  if (!btn.dataset.originalLabel) {
    btn.dataset.originalLabel = btn.textContent;
  }
  btn.disabled = true;
  btn.textContent = "生成中...";
  try {
    await request(`/api/history/${taskId}/generate-article`, {
      method: "POST",
      body: JSON.stringify({ status: "draft" }),
    });
    await refreshHistory({ showLoading: false });
  } catch (err) {
    alert(err.message);
    btn.disabled = false;
    btn.textContent = btn.dataset.originalLabel || "生成文章";
  }
}

async function handleHistoryLogClick(e) {
  const btn = e.target.closest(".view-article-log");
  if (!btn) return;
  const taskId = btn.dataset.taskId;
  const courseUrl = btn.dataset.courseUrl;
  if (!taskId) return;
  state.activeTask = `article-${taskId}`;
  startArticleLogStream(taskId, courseUrl);
}

function flushLogs() {
  const pre = qs("#log-output");
  if (!pre) {
    state.logFlushScheduled = false;
    return;
  }
  pre.textContent = state.logLines.join("\n");
  pre.scrollTop = pre.scrollHeight;
  state.logFlushScheduled = false;
}

function scheduleLogFlush() {
  if (state.logFlushScheduled) return;
  state.logFlushScheduled = true;
  requestAnimationFrame(flushLogs);
}

function appendLog(line) {
  state.logLines.push(line);
  if (state.logLines.length > LOG_BUFFER_LIMIT) {
    state.logLines = state.logLines.slice(-LOG_BUFFER_LIMIT);
  }
  scheduleLogFlush();
}

function clearLogPanel() {
  const pre = qs("#log-output");
  if (pre) {
    pre.textContent = "";
  }
  state.logLines = [];
  state.logFlushScheduled = false;
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
    refreshActiveTasks({ showLoading: false });
  });
  state.eventSource.onerror = () => {
    appendLog("[system] 连接中断");
    stopLogStream();
  };
}

function startArticleLogStream(taskId, courseUrl) {
  stopLogStream();
  clearLogPanel();
  qs("#active-task-info").textContent = `生成文章日志：${courseUrl || taskId}`;
  state.eventSource = new EventSource(`/api/history/${taskId}/article/logs?token=${state.token}`);
  state.eventSource.onmessage = (event) => {
    appendLog(event.data);
  };
  state.eventSource.addEventListener("end", () => {
    stopLogStream();
    clearLogPanel();
    refreshHistory({ showLoading: false });
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
  qs("#history-body").addEventListener("click", handleHistoryClick);
  qs("#history-body").addEventListener("click", handleHistoryLogClick);
  document.body.addEventListener("click", (event) => {
    const btn = event.target.closest(".attach-log-btn");
    if (!btn) return;
    const taskId = btn.dataset.taskId;
    if (!taskId) return;
    state.activeTask = taskId;
    startLogStream(taskId);
  });
  const refreshActiveBtn = qs("#refresh-active-tasks");
  if (refreshActiveBtn) {
    refreshActiveBtn.addEventListener("click", () => refreshActiveTasks({ showLoading: true }));
  }
  refreshHistory();
  refreshActiveTasks();

  setInterval(() => {
    if (!state.token) return;
    refreshHistory({ showLoading: false });
    refreshActiveTasks({ showLoading: false });
  }, 5000);
});
