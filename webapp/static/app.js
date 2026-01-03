const qs = (selector) => document.querySelector(selector);
const qsa = (selector) => Array.from(document.querySelectorAll(selector));

const state = {
  token: null,
  activeTask: null,
  eventSource: null,
};

const endpoints = {
  login: "/api/login",
  history: "/api/history",
  precheck: "/api/precheck",
  download: "/api/download",
  tasks: "/api/tasks",
  task: (id) => `/api/tasks/${id}`,
  logs: (id) => `/api/tasks/${id}/logs`,
};

function setSectionVisible(isLoggedIn) {
  qs("#login-panel").classList.toggle("hidden", isLoggedIn);
  qs("#dashboard").classList.toggle("hidden", !isLoggedIn);
}

function authHeaders() {
  if (!state.token) return {};
  return {
    Authorization: `Bearer ${state.token}`,
    "Content-Type": "application/json",
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

async function login(e) {
  e.preventDefault();
  qs("#login-error").textContent = "";
  const payload = {
    username: qs("#login-username").value.trim(),
    password: qs("#login-password").value.trim(),
  };
  try {
    const data = await request(endpoints.login, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.token = data.token;
    setSectionVisible(true);
    await refreshHistory();
  } catch (err) {
    qs("#login-error").textContent = err.message || "登录失败，请重试";
  }
}

function logout() {
  state.token = null;
  stopLogStream();
  setSectionVisible(false);
}

function collectKeyEntries() {
  return qsa("#key-body tr")
    .map((row) => {
      const [kidInput, keyInput] = row.querySelectorAll("input");
      return { kid: kidInput.value.trim(), key: keyInput.value.trim() };
    })
    .filter((entry) => entry.kid && entry.key);
}

function collectPayload() {
  return {
    course_url: qs("#course-url").value.trim(),
    bearer_token: qs("#bearer-token").value.trim(),
    output_dir: qs("#output-dir").value.trim() || undefined,
    lang: qs("#lang").value.trim() || undefined,
    quality: qs("#quality").value ? parseInt(qs("#quality").value, 10) : undefined,
    concurrent_downloads: qs("#concurrent-downloads").value
      ? parseInt(qs("#concurrent-downloads").value, 10)
      : undefined,
    chapter_filter: qs("#chapter-filter").value.trim() || undefined,
    download_assets: qs("#download-assets").checked,
    download_captions: qs("#download-captions").checked,
    download_quizzes: qs("#download-quizzes").checked,
    skip_lectures: qs("#skip-lectures").checked,
    keep_vtt: qs("#keep-vtt").checked,
    skip_hls: qs("#skip-hls").checked,
    use_h265: qs("#use-h265").checked,
    use_nvenc: qs("#use-nvenc").checked,
    use_continuous_lecture_numbers: qs("#continuous-lectures").checked,
    key_entries: collectKeyEntries(),
  };
}

async function handlePrecheck() {
  const payload = {
    course_url: qs("#course-url").value.trim(),
    bearer_token: qs("#bearer-token").value.trim(),
  };
  const badge = qs("#precheck-result");
  badge.textContent = "预检中...";
  try {
    const data = await request(endpoints.precheck, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    badge.textContent = data.is_drm
      ? `⚠ 检测到 DRM：${data.encrypted_lectures}/${data.total_lectures}`
      : `✔ 非 DRM 课程，讲座总数：${data.total_lectures}`;
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

async function refreshHistory() {
  const tbody = qs("#history-body");
  tbody.innerHTML = "<tr><td colspan='6'>加载中...</td></tr>";
  try {
    const items = await request(endpoints.history);
    tbody.innerHTML = items
      .map(
        (item) => `
      <tr>
        <td>${item.task_id}</td>
        <td>${item.course_url}</td>
        <td>${item.status}</td>
        <td>${item.started_at || "-"}</td>
        <td>${item.finished_at || "-"}</td>
        <td>${item.message || "-"}</td>
      </tr>`
      )
      .join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6">${err.message}</td></tr>`;
  }
}

function appendLog(line) {
  const pre = qs("#log-output");
  pre.textContent += `${line}\n`;
  pre.scrollTop = pre.scrollHeight;
}

function startLogStream(taskId) {
  stopLogStream();
  qs("#log-output").textContent = "";
  qs("#active-task-info").textContent = `监听任务：${taskId}`;
  state.eventSource = new EventSource(`${endpoints.logs(taskId)}?token=${state.token}`);
  state.eventSource.onmessage = (event) => {
    appendLog(event.data);
  };
  state.eventSource.addEventListener("end", () => {
    appendLog("[system] 日志结束");
    stopLogStream();
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
    const res = await request(endpoints.download, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.activeTask = res.task_id;
    startLogStream(res.task_id);
    await refreshHistory();
    qs("#precheck-result").textContent = "任务已启动";
  } catch (err) {
    alert(err.message);
  } finally {
    qs("#start-download-btn").disabled = false;
  }
}

function addKeyRow() {
  const row = document.createElement("tr");
  row.innerHTML = `
    <td><input type="text" placeholder="e.g. 1234abcd..." /></td>
    <td><input type="text" placeholder="e.g. abcd1234..." /></td>
    <td><button class="remove-row">删除</button></td>
  `;
  qs("#key-body").appendChild(row);
}

function handleKeyTableClick(e) {
  if (e.target.classList.contains("remove-row")) {
    const row = e.target.closest("tr");
    row.remove();
  }
}

function toggleVisibility(e) {
  const targetId = e.currentTarget.dataset.target;
  const input = qs(`#${targetId}`);
  if (!input) return;
  const isPassword = input.type === "password";
  input.type = isPassword ? "text" : "password";
  e.currentTarget.textContent = isPassword ? "🙈" : "👁";
}

document.addEventListener("DOMContentLoaded", () => {
  qs("#login-form").addEventListener("submit", login);
  qs("#logout-btn").addEventListener("click", logout);
  qs("#precheck-btn").addEventListener("click", handlePrecheck);
  qs("#start-download-btn").addEventListener("click", startDownload);
  qs("#add-key-row").addEventListener("click", addKeyRow);
  qs("#key-body").addEventListener("click", handleKeyTableClick);
  qsa(".toggle-visibility").forEach((btn) => btn.addEventListener("click", toggleVisibility));
});
