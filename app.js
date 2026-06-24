const DEFAULTS = {
  owner: "Pauldw666",
  repo: "codex-agenthub",
  branch: "main",
  path: "MOBILE_INBOX.md",
  language: "zh-CN",
  target: "auto",
};

const STORAGE_KEY = "agenthubVoiceSettings";
const TOKEN_KEY = "agenthubVoiceToken";

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
  refreshInbox: document.querySelector("#refreshInbox"),
  quickCommands: document.querySelector("#quickCommands"),
  targetButtons: Array.from(document.querySelectorAll(".target-button")),
};

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let listening = false;
let target = DEFAULTS.target;

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

function apiUrl(settings) {
  return `https://api.github.com/repos/${encodeURIComponent(settings.owner)}/${encodeURIComponent(settings.repo)}/contents/${encodeURIComponent(settings.path)}`;
}

function githubHeaders(token) {
  return {
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${token}`,
    "X-GitHub-Api-Version": "2022-11-28",
  };
}

async function fetchInbox(settings, token) {
  const url = `${apiUrl(settings)}?ref=${encodeURIComponent(settings.branch)}`;
  const response = await fetch(url, { headers: githubHeaders(token) });
  if (!response.ok) {
    throw new Error(`GitHub 读取失败：${response.status}`);
  }
  const payload = await response.json();
  return {
    sha: payload.sha,
    text: base64ToUtf8(payload.content || ""),
    htmlUrl: payload.html_url,
  };
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
    await loadQuickCommands();
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

function extractQuickCommands(inboxText) {
  const lines = inboxText.replace(/\r\n/g, "\n").split("\n");
  const start = lines.findIndex((line) => line.trim() === "## Quick Commands");
  if (start === -1) return "没有找到 Quick Commands。";
  const commands = [];
  for (let index = start + 1; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.startsWith("## ")) break;
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("<!--")) continue;
    commands.push(trimmed);
  }
  return commands.length ? commands.slice(0, 12).join("\n") : "暂无快速命令。";
}

async function loadQuickCommands() {
  const token = els.tokenInput.value.trim() || localStorage.getItem(TOKEN_KEY);
  if (!token) {
    els.quickCommands.textContent = "保存 token 后可以读取最近手机命令。";
    return;
  }
  try {
    const inbox = await fetchInbox(currentSettings(), token);
    els.quickCommands.textContent = extractQuickCommands(inbox.text);
  } catch (error) {
    els.quickCommands.textContent = error instanceof Error ? error.message : String(error);
  }
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
els.refreshInbox.addEventListener("click", loadQuickCommands);

els.saveSettings.addEventListener("click", async () => {
  const settings = currentSettings();
  saveSettings(settings);
  if (els.tokenInput.value.trim()) {
    localStorage.setItem(TOKEN_KEY, els.tokenInput.value.trim());
  }
  setConnectionState();
  setStatus("设置已保存。", "ok");
  await loadQuickCommands();
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
loadQuickCommands();
