(() => {
  if (window.__livefeedConnectButton) return;
  window.__livefeedConnectButton = true;

  const STATE_COLORS = {
    offline: "#ff8a80",
    starting: "#d7e08a",
    running: "#3dd6c6",
    connected: "#9ec5ff",
  };

  function stateKey(state) {
    const online = state?.online !== false;
    if (!online) return "offline";
    if (state?.starting) return "starting";
    if (state?.running) return "running";
    return "connected";
  }

  function titleFor(state) {
    const online = state?.online !== false;
    if (!online) return "LiveFeed: Offline — click to connect";
    if (state?.starting) return "LiveFeed: Starting…";
    if (state?.running) return "LiveFeed: Capturing";
    return "LiveFeed: Connected";
  }

  function createButton() {
    const button = document.createElement("button");
    button.id = "livefeed-connect-button";
    button.type = "button";
    Object.assign(button.style, {
      position: "fixed",
      right: "20px",
      bottom: "20px",
      width: "48px",
      height: "48px",
      borderRadius: "50%",
      border: "none",
      background: STATE_COLORS.offline,
      boxShadow: "0 6px 18px rgba(0,0,0,.35)",
      cursor: "pointer",
      zIndex: 2147483647,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "0",
      transition: "background 160ms ease, transform 120ms ease",
    });
    button.innerHTML = `
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style="pointer-events:none">
        <path d="M7 12a5 5 0 0 1 5-5h1" stroke="#08221f" stroke-width="2" stroke-linecap="round"/>
        <path d="M17 12a5 5 0 0 1-5 5h-1" stroke="#08221f" stroke-width="2" stroke-linecap="round"/>
        <circle cx="7" cy="12" r="2" fill="#08221f"/>
        <circle cx="17" cy="12" r="2" fill="#08221f"/>
      </svg>
    `;
    button.addEventListener("mouseenter", () => {
      button.style.transform = "scale(1.06)";
    });
    button.addEventListener("mouseleave", () => {
      button.style.transform = "scale(1)";
    });
    document.documentElement.appendChild(button);
    return button;
  }

  function paint(button, state) {
    button.style.background = STATE_COLORS[stateKey(state)];
    button.title = titleFor(state);
  }

  async function refresh(button) {
    try {
      const state = await chrome.runtime.sendMessage({ type: "get-state" });
      paint(button, state);
    } catch {
      /* extension context may be reloading */
    }
  }

  function init() {
    const button = createButton();
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      button.disabled = true;
      try {
        const state = await chrome.runtime.sendMessage({ type: "connect" });
        paint(button, state);
      } finally {
        button.disabled = false;
      }
    });
    refresh(button);
    setInterval(() => refresh(button), 2000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
