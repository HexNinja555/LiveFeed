"""CLI: python -m livefeed"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from livefeed.app import run_app
from livefeed.captions import captions_are_running, captions_exe
from livefeed.server import DEFAULT_HOST, DEFAULT_PORT, serve
from livefeed.window import force_restore_all


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def _check() -> int:
    print(f"Python {sys.version}")
    print(f"Platform {sys.platform}")
    exe = captions_exe()
    print(f"Live Captions: {'OK' if exe.is_file() else 'missing'}  {exe}")
    print(f"Live Captions running: {captions_are_running()}")
    for name in ("comtypes", "psutil", "aiohttp"):
        try:
            __import__(name)
            print(f"import {name}: OK")
        except Exception as exc:
            print(f"import {name}: FAIL ({exc})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture Windows 11 Live Captions for LiveFeed.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--check", action="store_true", help="Print environment info and exit.")
    parser.add_argument(
        "--restore-captions",
        action="store_true",
        help="Move the Windows Live Captions bar back on screen and exit.",
    )
    parser.add_argument(
        "--server",
        action="store_true",
        help="Run the local service without the desktop app window.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    if args.check:
        return _check()
    if args.restore_captions:
        print(f"Restored {force_restore_all()} Live Captions window(s).")
        return 0
    if args.server:
        try:
            asyncio.run(serve(args.host, args.port))
        except KeyboardInterrupt:
            force_restore_all()
            return 0
        return 0
    return run_app(host=args.host, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
