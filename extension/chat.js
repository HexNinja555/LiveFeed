(() => {
  if (window.__livefeedChat) return;
  window.__livefeedChat = true;

  const INPUTS = [
    'form[data-chatgpt-composer] div.ProseMirror[contenteditable="true"]',
    'form[data-chatgpt-composer] [contenteditable="true"][role="textbox"]',
    'div.ProseMirror[contenteditable="true"][aria-label*="ChatGPT"]',
    "#prompt-textarea",
    '[data-testid="prompt-textarea"]',
    "div.ProseMirror#prompt-textarea",
    "#chat-input",
    "textarea#chat-input",
    'textarea[placeholder*="Send a message"]',
    'textarea[placeholder*="Message"]',
    'textarea[placeholder*="message"]',
    'div[contenteditable="true"][data-lexical-editor]',
    'div[contenteditable="true"][role="textbox"]',
    'div[contenteditable="true"]#prompt-textarea',
    "textarea",
  ];
  const SEND = [
    '[data-testid="send-button"]',
    "#composer-submit-button",
    'button[data-testid="composer-send"]',
    'button[aria-label="Send prompt"]',
    'button[aria-label="Send"]',
    'button[aria-label*="Send message"]',
    'button[aria-label*="Send"]',
    'button[type="submit"]',
    '[class*="send-button"]',
    'button[class*="send"]',
  ];
  const STOP = [
    '[data-testid="stop-button"]',
    'button[data-testid="stop-button"]',
    'button[aria-label="Stop streaming"]',
    'button[aria-label*="Stop generating"]',
    'button[aria-label*="Stop"]',
    'button[aria-label*="stop"]',
    '[class*="stop-button"]',
  ];

  function visible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
      return false;
    }
    const box = el.getBoundingClientRect();
    return box.width > 8 && box.height > 8;
  }

  function enabled(el) {
    if (!el || el.disabled) return false;
    if (el.getAttribute("aria-disabled") === "true") return false;
    if (el.getAttribute("data-disabled") === "true") return false;
    return true;
  }

  function first(selectors, requireEnabled = true, root = document) {
    for (const selector of selectors) {
      const nodes = root.querySelectorAll(selector);
      for (const node of nodes) {
        if (!visible(node)) continue;
        if (requireEnabled && !enabled(node)) continue;
        return node;
      }
    }
    return null;
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function fill(el, text) {
    el.focus();
    if (el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement) {
      const proto = Object.getOwnPropertyDescriptor(
        el instanceof HTMLTextAreaElement
          ? HTMLTextAreaElement.prototype
          : HTMLInputElement.prototype,
        "value"
      );
      if (proto?.set) proto.set.call(el, text);
      else el.value = text;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return;
    }
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(el);
    selection.removeAllRanges();
    selection.addRange(range);
    const inserted = document.execCommand("insertText", false, text);
    if (!inserted || !el.textContent.includes(text.slice(0, 20))) {
      // ProseMirror fallback: a synthetic paste goes through its clipboard handler.
      const data = new DataTransfer();
      data.setData("text/plain", text);
      el.dispatchEvent(
        new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true })
      );
    }
  }

  async function stopCurrent() {
    const button = first(STOP);
    if (!button) return false;
    button.click();
    await sleep(320);
    return true;
  }

  async function clickSend(input) {
    const form = input.closest("form");
    for (let attempt = 0; attempt < 10; attempt += 1) {
      const send = (form && first(SEND, true, form)) || first(SEND);
      if (send && send.id !== "livefeed-connect-button") {
        send.click();
        return true;
      }
      await sleep(80);
    }
    input.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        code: "Enter",
        keyCode: 13,
        which: 13,
        bubbles: true,
        cancelable: true,
      })
    );
    return true;
  }

  async function inject(text) {
    const value = (text || "").trim();
    if (!value) return { ok: false, error: "Caption slice was empty." };
    await stopCurrent();
    const input = first(INPUTS, false);
    if (!input) return { ok: false, error: "Chat input not found." };
    fill(input, value);
    await sleep(120);
    await clickSend(input);
    return { ok: true };
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "ping") {
      sendResponse({ ok: true, chat: true });
      return;
    }
    if (message?.type === "inject-prompt") {
      inject(message.text).then(sendResponse).catch((error) => {
        sendResponse({ ok: false, error: error.message || String(error) });
      });
      return true;
    }
  });
})();
