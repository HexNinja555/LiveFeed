const API = "http://127.0.0.1:17865";
const WS_URL = "ws://127.0.0.1:17865/ws";
const CHAT_URLS = [
  "https://chatgpt.com/*",
  "https://*.chatgpt.com/*",
  "https://chat.openai.com/*",
  "https://*.openai.com/*",
  "https://chat.deepseek.com/*",
  "https://*.deepseek.com/*",
];

let lastState = {
  online: false,
  running: false,
  starting: false,
  error: "",
  live: "",
  committed: "",
  provisional: "",
  full: "",
  extension_connected: false,
};
let socket = null;
let reconnectTimer = 0;

function mergeState(partial) {
  lastState = {
    ...lastState,
    ...partial,
    online: partial.online ?? lastState.online,
  };
  return lastState;
}

async function request(path, method = "GET") {
  const response = await fetch(`${API}${path}`, {
    method,
    cache: "no-store",
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error || `LiveFeed returned ${response.status}.`);
  }
  return body;
}

async function pollStatus() {
  try {
    const status = await request("/status");
    return mergeState({ online: true, error: status.error || "", ...status });
  } catch {
    return mergeState({
      online: false,
      running: false,
      starting: false,
      extension_connected: false,
      error: "",
    });
  }
}

async function relayInject(text) {
  const tabs = await chrome.tabs.query({ url: CHAT_URLS });
  if (!tabs.length) {
    mergeState({ error: "Open ChatGPT or DeepSeek, then select a caption and right-click." });
    return false;
  }
  let sent = false;
  for (const tab of tabs) {
    if (!tab.id) continue;
    try {
      const result = await chrome.tabs.sendMessage(tab.id, { type: "inject-prompt", text });
      if (result?.ok === false) {
        mergeState({ error: result.error || "Could not send to the chat box." });
        continue;
      }
      sent = true;
    } catch {
      try {
        await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["chat.js"] });
        const result = await chrome.tabs.sendMessage(tab.id, { type: "inject-prompt", text });
        if (result?.ok === false) {
          mergeState({ error: result.error || "Could not send to the chat box." });
          continue;
        }
        sent = true;
      } catch (error) {
        console.warn("LiveFeed could not reach the chat tab", error);
      }
    }
  }
  if (sent) mergeState({ error: "" });
  return sent;
}

function connectSocket() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  try {
    socket = new WebSocket(WS_URL);
  } catch {
    mergeState({ online: false });
    scheduleReconnect();
    return;
  }
  socket.addEventListener("open", () => {
    mergeState({ online: true, error: "" });
  });
  socket.addEventListener("message", async (event) => {
    try {
      const payload = JSON.parse(event.data);
      mergeState({ online: true, error: payload.error || lastState.error, ...payload });
      if (payload.type === "inject" && payload.text) {
        await relayInject(payload.text);
      }
    } catch {
      /* ignore malformed frames */
    }
  });
  socket.addEventListener("close", () => {
    socket = null;
    mergeState({ online: false, extension_connected: false });
    scheduleReconnect();
  });
  socket.addEventListener("error", () => {
    try {
      socket?.close();
    } catch {
      socket = null;
    }
  });
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connectSocket, 1500);
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const work = (async () => {
    if (message?.type === "connect") {
      connectSocket();
      return pollStatus();
    }
    if (message?.type === "get-state") {
      return lastState.online ? lastState : pollStatus();
    }
    return lastState;
  })();
  work.then(sendResponse).catch((error) => {
    sendResponse(mergeState({ error: error.message || String(error) }));
  });
  return true;
});

connectSocket();
pollStatus();
setInterval(pollStatus, 2000);
