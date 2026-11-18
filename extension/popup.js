const connectBtn = document.getElementById("connect");
const badge = document.getElementById("badge");
const serverEl = document.getElementById("server");
const previewEl = document.getElementById("preview");
const messageEl = document.getElementById("message");
const versionEl = document.getElementById("version");

const version = chrome.runtime.getManifest().version;
if (versionEl) versionEl.textContent = `v${version} · ChatGPT / DeepSeek`;

function paint(state) {
  const online = state?.online !== false;
  const running = Boolean(state?.running);
  const starting = Boolean(state?.starting);
  badge.className = `badge ${!online ? "stopped" : starting ? "starting" : running ? "running" : "connected"}`;
  badge.textContent = !online ? "Offline" : starting ? "Starting" : running ? "Capturing" : "Connected";
  serverEl.textContent = !online
    ? "Open the LiveFeed app, then click Connect."
    : running
      ? "Connected. Select text on the caption bar, then right-click to send from there to the end."
      : "Connected. Use Start in the LiveFeed app, then select a caption and right-click.";
  const text = (state?.full || state?.live || "").trim();
  if (text) {
    previewEl.hidden = false;
    previewEl.textContent = text;
  } else {
    previewEl.hidden = true;
    previewEl.textContent = "";
  }
  if (state?.error) {
    messageEl.hidden = false;
    messageEl.textContent = state.error;
  } else {
    messageEl.hidden = true;
    messageEl.textContent = "";
  }
}

async function refresh() {
  const state = await chrome.runtime.sendMessage({ type: "get-state" });
  paint(state);
}

connectBtn.addEventListener("click", async () => {
  connectBtn.disabled = true;
  const state = await chrome.runtime.sendMessage({ type: "connect" });
  paint(state);
  connectBtn.disabled = false;
});

refresh();
setInterval(refresh, 1000);
