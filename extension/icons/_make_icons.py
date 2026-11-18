"""Generate simple PNG icons without extra dependencies."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png(path: Path, size: int) -> None:
    pixels = bytearray()
    cx = cy = (size - 1) / 2
    radius = size * 0.36
    for y in range(size):
        pixels.append(0)
        for x in range(size):
            dx = x - cx
            dy = y - cy
            inside = dx * dx + dy * dy <= radius * radius
            if inside:
                pixels.extend((61, 214, 198, 255))
            else:
                pixels.extend((17, 22, 28, 255))
    raw = bytes(pixels)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def main() -> None:
    folder = Path(__file__).resolve().parent
    for size in (16, 48, 128):
        write_png(folder / f"icon{size}.png", size)


if __name__ == "__main__":
    main()
