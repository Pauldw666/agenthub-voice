const DEFAULTS = {
  owner: "Pauldw666",
  repo: "codex-agenthub",
  branch: "main",
  path: "MOBILE_INBOX.md",
  requestsPath: "REQUESTS.md",
  language: "zh-CN",
  target: "auto",
};

const STORAGE_KEY = "agenthubVoiceSettings";
const TOKEN_KEY = "agenthubVoiceToken";
const SELECTED_REQUEST_KEY = "agenthubSelectedRequest";
const REFRESH_INTERVAL_MS = 20000;

const els = {
  connectionState: document.querySelector("#connectionState"),
  languageSelect: document.querySelector("#languageSelect"),
  commandText: document.querySelector("#commandText"),
  listenButton: document.querySelector("#listenButton"),
  submitButton: document.querySelector("#submitButton"),
  speechHint: document.querySelector("#speechHint"),
  submitStatus: document.querySelector("#submitStatus"),
  tokenInput: document.querySelector("#tokenInput"),
  ownerInput: document.querySelector("#ownerInput"),
  repoInput: document.querySelector("#repoInput"),
  branchInput: document.querySelector("#branchInput"),
  saveSettings: document.querySelector("#saveSettings"),
  clearToken: document.querySelector("#clearToken"),
  toggleSettings: document.querySelector("#toggleSettings"),
  settingsBody: document.querySelector("#settingsBody"),
  refreshTasks: document.querySelector("#refreshTasks"),
  autoRefresh: document.querySelector("#autoRefresh"),
  progressStatus: document.querySelector("#progressStatus"),
  taskList: document.querySelector("#taskList"),
  taskDetail: document.querySelector("#taskDetail"),
  targetButtons: Array.from(document.querySelectorAll(".target-button")),
};

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let listening = false;
let target = DEFAULTS.target;
let refreshTimer = null;
let selectedRequestId = localStorage.getItem(SELECTED_REQUEST_KEY) || "";

function loadSettings() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") };
  } catch {
    return { ...DEFAULTS };
  }
}

function saveSettings(settings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

function currentSettings() {
  return {
    owner: els.ownerInput.value.trim() || DEFAULTS.owner,
    repo: els.repoInput.value.trim() || DEFAULTS.repo,
    branch: els.branchInput.value.trim() || DEFAULTS.branch,
    path: DEFAULTS.path,
    requestsPath: DEFAULTS.requestsPath,
    language: els.languageSelect.value || DEFAULTS.language,
    target,
  };
}

function setStatus(message, type = "") {
  els.submitStatus.textContent = message;
  els.submitStatus.classList.toggle("is-error", type === "error");
  els.submitStatus.classList.toggle("is-ok", type === "ok");
}

function setConnectionState() {
  const hasToken = Boolean(localStorage.getItem(TOKEN_KEY));
  els.connectionState.textContent = hasToken ? "已配置" : "需设置";
  els.connectionState.classList.toggle("is-ready", hasToken);
}

function applySettings(settings) {
  els.ownerInput.value = settings.owner;
  els.repoInput.value = settings.repo;
  els.branchInput.value = settings.branch;
  els.languageSelect.value = settings.language;
  target = settings.target || DEFAULTS.target;
  els.targetButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.target === target);
  });
  els.tokenInput.value = localStorage.getItem(TOKEN_KEY) || "";
  setConnectionState();
}

function utf8ToBase64(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

function base64ToUtf8(base64) {
  const binary = atob(base64.replace(/\s/g, ""));
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

function apiUrl(settings, path = settings.path) {
  const encodedPath = path.split("/").map((part) => encodeURIComponent(part)).join("/");
  return `https://api.github.com/repos/${encodeURIComponent(settings.owner)}/${encodeURIComponent(settings.repo)}/contents/${encodedPath}`;
}

function githubHeaders(token) {
  return {
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${token}`,
    "X-GitHub-Api-Version": "2022-11-28",
  };
}

async function fetchRepoFile(settings, token, path) {
  const url = `${apiUrl(settings, path)}?ref=${encodeURIComponent(settings.branch)}`;
  const response = await fetch(url, { headers: githubHeaders(token) });
  if (!response.ok) {
    throw new Error(`GitHub 读取 ${path} 失败：${response.status}`);
  }
  const payload = await response.json();
  return {
    sha: payload.sha,
    text: base64ToUtf8(payload.content || ""),
    htmlUrl: payload.html_url,
  };
}

async function fetchInbox(settings, token) {
  return fetchRepoFile(settings, token, settings.path);
}

function targetPrefix(selectedTarget) {
  if (selectedTarget === "windows") return "Win";
  if (selectedTarget === "mac") return "Mac";
  if (selectedTarget === "both") return "两边";
  return "";
}

function buildCommandLine(command, selectedTarget) {
  const clean = command.replace(/\s+/g, " ").trim();
  const prefix = targetPrefix(selectedTarget);
  if (!prefix) return `- ${clean}`;
  const alreadyPrefixed = /^(win|windows|mac|两边|双方|全部)/i.test(clean);
  return `- ${alreadyPrefixed ? clean : `${prefix}${clean}`}`;
}

function insertQuickCommand(inboxText, commandLine) {
  const normalized = inboxText.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const lines = normalized.split("\n");
  const sectionIndex = lines.findIndex((line) => line.trim() === "## Quick Commands");
  if (sectionIndex === -1) {
    return `${normalized.trimEnd()}\n\n## Quick Commands\n\n${commandLine}\n`;
  }
  let insertIndex = sectionIndex + 1;
  while (insertIndex < lines.length && lines[insertIndex].trim() === "") {
    insertIndex += 1;
  }
  lines.splice(insertIndex, 0, commandLine, "");
  return lines.join("\n");
}

function commitMessage(command) {
  const compact = command.replace(/\s+/g, " ").trim();
  const short = compact.length > 36 ? `${compact.slice(0, 34)}...` : compact;
  return `Mobile voice command: ${short}`;
}

async function submitCommand() {
  const token = els.tokenInput.value.trim() || localStorage.getItem(TOKEN_KEY);
  const command = els.commandText.value.trim();
  if (!token) {
    setStatus("先填写并保存 GitHub token。", "error");
    return;
  }
  if (!command) {
    setStatus("先说一句或输入一条任务。", "error");
    return;
  }

  const settings = currentSettings();
  localStorage.setItem(TOKEN_KEY, token);
  saveSettings(settings);
  setConnectionState();

  els.submitButton.disabled = true;
  setStatus("正在提交到 AgentHub...");
  try {
    const inbox = await fetchInbox(settings, token);
    const commandLine = buildCommandLine(command, settings.target);
    const updatedText = insertQuickCommand(inbox.text, commandLine);
    const response = await fetch(apiUrl(settings), {
      method: "PUT",
      headers: {
        ...githubHeaders(token),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message: commitMessage(command),
        content: utf8ToBase64(updatedText),
        sha: inbox.sha,
        branch: settings.branch,
      }),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`GitHub 提交失败：${response.status} ${errorText}`);
    }
    const payload = await response.json();
    els.commandText.value = "";
    setStatus(`已提交，等待 AgentHub worker 处理。${payload.commit?.sha?.slice(0, 7) || ""}`, "ok");
    await loadTaskDashboard();
    startAutoRefresh();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error), "error");
  } finally {
    els.submitButton.disabled = false;
  }
}

function setupSpeech() {
  if (!SpeechRecognition) {
    els.listenButton.disabled = true;
    els.speechHint.textContent = "当前浏览器不支持内置语音识别；可以先手动输入文字。";
    return;
  }
  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    listening = true;
    els.listenButton.textContent = "停止语音";
    els.listenButton.classList.add("is-listening");
    els.speechHint.textContent = "正在听，你可以直接说任务。";
  };

  recognition.onend = () => {
    listening = false;
    els.listenButton.textContent = "开始语音";
    els.listenButton.classList.remove("is-listening");
    if (!els.commandText.value.trim()) {
      els.speechHint.textContent = "没有听到内容，可以再试一次或手动输入。";
    }
  };

  recognition.onerror = (event) => {
    els.speechHint.textContent = `语音识别失败：${event.error || "未知错误"}`;
  };

  recognition.onresult = (event) => {
    let finalText = "";
    let interimText = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const transcript = event.results[index][0]?.transcript || "";
      if (event.results[index].isFinal) {
        finalText += transcript;
      } else {
        interimText += transcript;
      }
    }
    const nextText = `${els.commandText.value.replace(/\s+$/g, "")}${finalText}`;
    els.commandText.value = nextText || interimText;
  };
}

function toggleListening() {
  if (!recognition) return;
  recognition.lang = els.languageSelect.value;
  if (listening) {
    recognition.stop();
  } else {
    els.speechHint.textContent = "";
    recognition.start();
  }
}

function parseQuickCommandEntries(inboxText) {
  const lines = inboxText.replace(/\r\n/g, "\n").split("\n");
  const start = lines.findIndex((line) => line.trim() === "## Quick Commands");
  if (start === -1) return [];
  const entries = [];
  for (let index = start + 1; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.startsWith("## ")) break;
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("<!--")) continue;
    const withoutBullet = trimmed.replace(/^[-*]\s+/, "");
    const imported = withoutBullet.match(/\(imported as (R-\d+)\)/);
    entries.push({
      source: "quick",
      requestId: imported?.[1] || "",
      title: withoutBullet.replace(/\s*\(imported as R-\d+\)\s*$/, "").trim(),
    });
  }
  return entries;
}

function parseRequestTable(requestsText) {
  return requestsText
    .split("\n")
    .filter((line) => line.startsWith("| R-"))
    .map((line) => {
      const parts = line.split("|").map((part) => part.trim()).filter(Boolean);
      return {
        requestId: parts[0] || "",
        status: parts[1] || "",
        requestedBy: parts[2] || "",
        assignedTo: parts[3] || "",
        title: parts[4] || "",
        updated: parts[5] || "",
        source: "request",
      };
    })
    .filter((request) => request.requestId);
}

function requestNumber(requestId) {
  const number = Number(requestId.replace("R-", ""));
  return Number.isFinite(number) ? number : 0;
}

function statusLabel(status) {
  const labels = {
    pending: "待导入",
    open: "待领取",
    claimed: "处理中",
    done: "完成",
    blocked: "阻塞",
  };
  return labels[status] || status || "未知";
}

function taskSortValue(item) {
  if (item.requestId) return requestNumber(item.requestId);
  return 999999;
}

function buildTaskItems(inboxText, requestsText) {
  const quickEntries = parseQuickCommandEntries(inboxText);
  const requests = parseRequestTable(requestsText);
  const byId = new Map(requests.map((request) => [request.requestId, request]));
  const used = new Set();
  const fromQuick = quickEntries.map((entry) => {
    if (!entry.requestId) {
      return { ...entry, status: "pending", assignedTo: "等待 worker", updated: "" };
    }
    used.add(entry.requestId);
    const request = byId.get(entry.requestId);
    return request ? { ...entry, ...request, title: request.title || entry.title } : { ...entry, status: "pending", assignedTo: "等待同步", updated: "" };
  });
  const extraMobileRequests = requests
    .filter((request) => request.requestedBy === "mobile-user" && !used.has(request.requestId))
    .sort((a, b) => requestNumber(b.requestId) - requestNumber(a.requestId));
  return [...fromQuick, ...extraMobileRequests]
    .sort((a, b) => taskSortValue(b) - taskSortValue(a))
    .slice(0, 12);
}

function setProgress(message, type = "") {
  els.progressStatus.textContent = message;
  els.progressStatus.classList.toggle("is-error", type === "error");
  els.progressStatus.classList.toggle("is-ok", type === "ok");
}

function renderTaskList(items, settings, token) {
  els.taskList.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "还没有手机任务。";
    els.taskList.append(empty);
    els.taskDetail.textContent = "提交第一条任务后，这里会显示导入、领取和完成结果。";
    return;
  }
  if (!selectedRequestId || !items.some((item) => item.requestId === selectedRequestId)) {
    selectedRequestId = items.find((item) => item.requestId)?.requestId || "";
  }
  items.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `task-card ${item.requestId === selectedRequestId ? "is-active" : ""}`;

    const meta = document.createElement("span");
    meta.className = "task-meta";
    const left = document.createElement("span");
    left.textContent = item.requestId ? `${item.requestId} -> ${item.assignedTo || "未分配"}` : "等待导入 -> worker";
    const badge = document.createElement("span");
    badge.className = `status-badge is-${item.status || "pending"}`;
    badge.textContent = statusLabel(item.status);
    meta.append(left, badge);

    const title = document.createElement("span");
    title.className = "task-card-title";
    title.textContent = item.title || "未命名任务";
    button.append(meta, title);

    button.addEventListener("click", async () => {
      selectedRequestId = item.requestId || "";
      localStorage.setItem(SELECTED_REQUEST_KEY, selectedRequestId);
      renderTaskList(items, settings, token);
      if (item.requestId) {
        await loadTaskDetail(item, settings, token);
      } else {
        els.taskDetail.textContent = `这条命令还在等待 AgentHub worker 导入。\n\n${item.title}`;
      }
    });
    els.taskList.append(button);
  });
}

function readMarkdownField(text, field) {
  const line = text.split("\n").find((item) => item.startsWith(`${field}:`));
  return line ? line.slice(field.length + 1).trim() : "";
}

function readMarkdownSection(text, heading) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const start = lines.findIndex((line) => line.trim() === `### ${heading}` || line.trim() === `## ${heading}`);
  if (start === -1) return "";
  const body = [];
  for (let index = start + 1; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.startsWith("## ") || line.startsWith("### ")) break;
    body.push(line);
  }
  return body.join("\n").trim();
}

function summarizeDetail(item, detailText) {
  const goal = readMarkdownSection(detailText, "Goal");
  const result = readMarkdownSection(detailText, "Result");
  const claimBy = readMarkdownField(detailText, "Claimed by");
  const claimAt = readMarkdownField(detailText, "Claimed at");
  const completedBy = readMarkdownField(detailText, "Completed by");
  const completedAt = readMarkdownField(detailText, "Completed at");
  const lines = [
    `${item.requestId} | ${statusLabel(item.status)} | ${item.assignedTo}`,
    "",
    "任务",
    item.title || goal || "未命名任务",
  ];
  if (goal && goal !== item.title) {
    lines.push("", "目标", goal);
  }
  if (claimBy) {
    lines.push("", "领取", `${claimBy}${claimAt ? ` @ ${claimAt}` : ""}`);
  }
  if (completedBy) {
    lines.push("", "完成", `${completedBy}${completedAt ? ` @ ${completedAt}` : ""}`);
  }
  if (result) {
    lines.push("", "结果", result);
  } else if (item.status === "open") {
    lines.push("", "当前进度", "已经导入请求，等待目标机器领取。");
  } else if (item.status === "claimed") {
    lines.push("", "当前进度", "目标机器已经领取，正在处理或等待下一次 worker tick 写回结果。");
  }
  return lines.join("\n");
}

async function loadTaskDetail(item, settings, token) {
  try {
    const detail = await fetchRepoFile(settings, token, `requests/${item.requestId}.md`);
    els.taskDetail.textContent = summarizeDetail(item, detail.text);
  } catch (error) {
    els.taskDetail.textContent = error instanceof Error ? error.message : String(error);
  }
}

async function loadTaskDashboard() {
  const token = els.tokenInput.value.trim() || localStorage.getItem(TOKEN_KEY);
  if (!token) {
    setProgress("保存 token 后可以读取任务进度。");
    els.taskList.replaceChildren();
    els.taskDetail.textContent = "尚未连接。";
    return;
  }
  try {
    const settings = currentSettings();
    const [inbox, requests] = await Promise.all([
      fetchInbox(settings, token),
      fetchRepoFile(settings, token, settings.requestsPath),
    ]);
    const items = buildTaskItems(inbox.text, requests.text);
    renderTaskList(items, settings, token);
    const latest = items.find((item) => item.requestId === selectedRequestId) || items.find((item) => item.requestId);
    if (latest?.requestId) {
      selectedRequestId = latest.requestId;
      localStorage.setItem(SELECTED_REQUEST_KEY, selectedRequestId);
      await loadTaskDetail(latest, settings, token);
    } else if (items[0]) {
      els.taskDetail.textContent = `这条命令还在等待 AgentHub worker 导入。\n\n${items[0].title}`;
    }
    const active = items.filter((item) => item.status !== "done").length;
    setProgress(active ? `已刷新：${active} 条任务还在进行或等待导入。` : "已刷新：最近手机任务都已完成。", "ok");
  } catch (error) {
    setProgress(error instanceof Error ? error.message : String(error), "error");
  }
}

function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  if (!els.autoRefresh.checked) return;
  refreshTimer = window.setInterval(() => {
    loadTaskDashboard();
  }, REFRESH_INTERVAL_MS);
}

function registerServiceWorker() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./service-worker.js").catch(() => {});
  }
}

els.targetButtons.forEach((button) => {
  button.addEventListener("click", () => {
    target = button.dataset.target || DEFAULTS.target;
    els.targetButtons.forEach((item) => item.classList.toggle("is-active", item === button));
    saveSettings(currentSettings());
  });
});

els.listenButton.addEventListener("click", toggleListening);
els.submitButton.addEventListener("click", submitCommand);
els.refreshTasks.addEventListener("click", loadTaskDashboard);
els.autoRefresh.addEventListener("change", startAutoRefresh);

els.saveSettings.addEventListener("click", async () => {
  const settings = currentSettings();
  saveSettings(settings);
  if (els.tokenInput.value.trim()) {
    localStorage.setItem(TOKEN_KEY, els.tokenInput.value.trim());
  }
  setConnectionState();
  setStatus("设置已保存。", "ok");
  await loadTaskDashboard();
  startAutoRefresh();
});

els.clearToken.addEventListener("click", () => {
  localStorage.removeItem(TOKEN_KEY);
  els.tokenInput.value = "";
  setConnectionState();
  setStatus("Token 已从本机浏览器清除。", "ok");
});

els.toggleSettings.addEventListener("click", () => {
  const hidden = els.settingsBody.hidden;
  els.settingsBody.hidden = !hidden;
  els.toggleSettings.textContent = hidden ? "收起" : "展开";
});

applySettings(loadSettings());
setupSpeech();
registerServiceWorker();
loadTaskDashboard();
startAutoRefresh();
