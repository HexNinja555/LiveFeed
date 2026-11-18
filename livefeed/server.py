"""Local HTTP + WebSocket bridge for the LiveFeed extension."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import WSMsgType, web

from livefeed.errors import LiveFeedError
from livefeed.hub import CaptionHub

PREVIEW_HTML = """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>LiveFeed preview</title>
    <style>
      :root { color-scheme: dark; }
      * { box-sizing: border-box; }
      body {
        margin: 0; min-height: 100vh; background: #0c1117; color: #eef3f8;
        font: 16px/1.5 "Segoe UI", system-ui, sans-serif;
      }
      .bar { display: flex; gap: 8px; padding: 12px 16px; }
      button {
        appearance: none; border: 0; border-radius: 8px; padding: 8px 14px;
        background: #3dd6c6; color: #08221f; font: inherit; font-weight: 650; cursor: pointer;
      }
      button.ghost { background: #1a222c; color: #eef3f8; border: 1px solid #2a3542; }
      button:disabled { opacity: .45; cursor: default; }
      .modal {
        position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%);
        width: min(720px, calc(100vw - 32px)); max-height: 38vh;
        display: flex; flex-direction: column; background: #111820;
        border: 1px solid #2b3846; border-radius: 14px;
        box-shadow: 0 18px 50px rgba(0,0,0,.45);
      }
      .modal[hidden] { display: none; }
      header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 10px 12px 8px 16px; border-bottom: 1px solid #243040;
      }
      h1 { margin: 0; font-size: 14px; }
      .close {
        width: 32px; height: 32px; border: 0; border-radius: 8px;
        background: transparent; color: #d5dee8; font-size: 22px; cursor: pointer;
      }
      .scroll { overflow: auto; padding: 12px 16px 16px; }
      #empty { color: #8ea0b3; }
      #provisional { color: #7de3d4; }
    </style>
  </head>
  <body>
    <div class="bar">
      <button id="start" type="button">Start</button>
      <button id="stop" type="button" class="ghost" disabled>Stop</button>
    </div>
    <section id="modal" class="modal" hidden>
      <header>
        <h1>Live captions</h1>
        <button id="close" class="close" type="button" aria-label="Close">×</button>
      </header>
      <div class="scroll">
        <div id="empty">Waiting for Windows Live Captions…</div>
        <div><span id="body"></span><span id="provisional"></span></div>
      </div>
    </section>
    <script>
      const startBtn = document.getElementById("start");
      const stopBtn = document.getElementById("stop");
      const modal = document.getElementById("modal");
      const emptyEl = document.getElementById("empty");
      const bodyEl = document.getElementById("body");
      const provisionalEl = document.getElementById("provisional");
      let socket = null;
      function paint(state) {
        const committed = (state?.committed || "").trim();
        const next = (state?.provisional || "").trim();
        const full = (state?.full || state?.live || "").trim();
        if (!full) {
          emptyEl.hidden = false; bodyEl.textContent = ""; provisionalEl.textContent = "";
          return;
        }
        emptyEl.hidden = true;
        bodyEl.textContent = committed ? committed + " " : "";
        provisionalEl.textContent = next || (!committed ? full : "");
      }
      function connect() {
        if (socket) return;
        socket = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
        socket.onmessage = (event) => paint(JSON.parse(event.data));
        socket.onclose = () => { socket = null; };
      }
      startBtn.onclick = async () => {
        startBtn.disabled = true;
        const response = await fetch("/start", { method: "POST" });
        const state = await response.json();
        if (!response.ok) { startBtn.disabled = false; alert(state.error || "Start failed"); return; }
        modal.hidden = false; stopBtn.disabled = false; connect(); paint(state);
      };
      stopBtn.onclick = async () => {
        await fetch("/stop", { method: "POST" });
        modal.hidden = true; startBtn.disabled = false; stopBtn.disabled = true;
      };
      document.getElementById("close").onclick = () => { modal.hidden = true; };
    </script>
  </body>
</html>
"""

log = logging.getLogger("livefeed.server")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17865


def _cors_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Cache-Control": "no-store",
    }


def _json(payload: dict[str, Any], *, status: int = 200) -> web.Response:
    return web.json_response(payload, status=status, headers=_cors_headers())


async def _options(_request: web.Request) -> web.Response:
    return web.Response(status=204, headers=_cors_headers())


def build_app(hub: CaptionHub | None = None) -> web.Application:
    hub = hub or CaptionHub()
    app = web.Application()
    app["hub"] = hub
    app.router.add_route("OPTIONS", "/{path:.*}", _options)
    app.router.add_get("/", preview)
    app.router.add_get("/health", health)
    app.router.add_get("/status", status)
    app.router.add_post("/start", start)
    app.router.add_post("/stop", stop)
    app.router.add_get("/ws", websocket)
    return app


async def preview(_request: web.Request) -> web.Response:
    return web.Response(text=PREVIEW_HTML, content_type="text/html", headers=_cors_headers())


async def health(_request: web.Request) -> web.Response:
    return _json({"ok": True, "service": "livefeed"})


async def status(request: web.Request) -> web.Response:
    hub: CaptionHub = request.app["hub"]
    return _json(hub.snapshot())


async def start(request: web.Request) -> web.Response:
    hub: CaptionHub = request.app["hub"]
    try:
        payload = await hub.start()
    except LiveFeedError as exc:
        return _json({**hub.snapshot(), "ok": False, "error": exc.display()}, status=409)
    except Exception as exc:
        return _json({**hub.snapshot(), "ok": False, "error": str(exc)}, status=500)
    payload = dict(payload)
    payload["ok"] = True
    return _json(payload)


async def stop(request: web.Request) -> web.Response:
    hub: CaptionHub = request.app["hub"]
    payload = dict(await hub.stop())
    payload["ok"] = True
    return _json(payload)


async def websocket(request: web.Request) -> web.WebSocketResponse:
    hub: CaptionHub = request.app["hub"]
    socket = web.WebSocketResponse(heartbeat=20.0)
    await socket.prepare(request)
    queue: asyncio.Queue[dict] = asyncio.Queue()

    def push(event: dict) -> None:
        queue.put_nowait(event)

    unsubscribe = hub.subscribe(push)
    hub.add_extension_client()
    await socket.send_json(hub.snapshot())

    async def pump() -> None:
        while True:
            event = await queue.get()
            await socket.send_json(event)

    sender = asyncio.create_task(pump(), name="livefeed-ws-send")
    try:
        async for message in socket:
            if message.type == WSMsgType.TEXT:
                await _handle_socket_command(hub, socket, message.data)
            elif message.type in {WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.ERROR}:
                break
    finally:
        sender.cancel()
        unsubscribe()
        hub.remove_extension_client()
        try:
            await sender
        except asyncio.CancelledError:
            pass
    return socket


async def _handle_socket_command(
    hub: CaptionHub, socket: web.WebSocketResponse, raw: str
) -> None:
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        await socket.send_json({"type": "error", "error": "Invalid JSON command."})
        return
    action = str(body.get("action") or "").strip().lower()
    try:
        if action == "start":
            await socket.send_json(await hub.start())
        elif action == "stop":
            await socket.send_json(await hub.stop())
        elif action == "status":
            await socket.send_json(hub.snapshot())
    except LiveFeedError as exc:
        await socket.send_json({**hub.snapshot(), "type": "error", "error": exc.display()})
    except Exception as exc:
        await socket.send_json({**hub.snapshot(), "type": "error", "error": str(exc)})


async def start_http(
    hub: CaptionHub | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> web.AppRunner:
    app = build_app(hub)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("LiveFeed listening on http://%s:%s", host, port)
    return runner


async def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    hub = CaptionHub()
    hub.bind_loop(asyncio.get_running_loop())
    runner = await start_http(hub, host, port)
    try:
        await asyncio.Event().wait()
    finally:
        await hub.stop()
        await runner.cleanup()
