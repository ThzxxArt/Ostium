#!/usr/bin/env python3
"""Generate deterministic Ostium PNG icons using only the Python stdlib.

Outputs: web/public/icons/{icon-192,icon-512,maskable-512,apple-touch-icon}.png
The mark is a dark rounded square with an aurora ring and an abstract door.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

SIZE = 1024
OUT = Path(__file__).resolve().parent.parent / "web" / "public" / "icons"


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def gradient(t: float) -> tuple[float, float, float]:
    # #5EEAD4 -> #60A5FA
    return (lerp(94, 96, t), lerp(234, 165, t), lerp(212, 250, t))


def rounded_rect(
    x: float, y: float, x0: float, y0: float, x1: float, y1: float, radius: float
) -> bool:
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + radius), x1 - radius)
    cy = min(max(y, y0 + radius), y1 - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius**2


def coverage(x: float, y: float) -> tuple[float, float, float, float]:
    """Return straight-alpha RGBA at a supersampled point (0..1 coords)."""
    cx = cy = 0.5
    dx, dy = x - cx, y - cy
    distance = math.hypot(dx, dy)

    # rounded-square background
    if not rounded_rect(x, y, 0.0, 0.0, 1.0, 1.0, 0.22):
        return (0.0, 0.0, 0.0, 0.0)

    # background gradient
    shade = 0.05 + 0.06 * (1.0 - y)
    r, g, b = 6 + shade * 40, 9 + shade * 46, 17 + shade * 58

    # outer ring
    if 0.345 <= distance <= 0.358:
        t = (math.atan2(dy, dx) + math.pi) / (2 * math.pi)
        gr, gg, gb = gradient(t)
        return (gr / 255, gg / 255, gb / 255, 0.55)

    # door: two rounded L strokes
    lw = 0.055
    if rounded_rect(x, y, 0.32, 0.27, 0.32 + lw, 0.68, 0.02) or rounded_rect(
        x, y, 0.32, 0.27, 0.61, 0.27 + lw, 0.02
    ):
        t = (y + x) / 2
        gr, gg, gb = gradient(t)
        return (gr / 255, gg / 255, gb / 255, 1.0)
    if rounded_rect(x, y, 0.68 - lw, 0.32, 0.68, 0.73, 0.02) or rounded_rect(
        x, y, 0.39, 0.73 - lw, 0.68, 0.73, 0.02
    ):
        t = (y + x) / 2
        gr, gg, gb = gradient(t)
        return (gr / 255, gg / 255, gb / 255, 0.58)

    # core
    if distance <= 0.085:
        return (0.043, 0.071, 0.125, 1.0)
    if 0.085 < distance <= 0.094:
        t = (math.atan2(dy, dx) + math.pi) / (2 * math.pi)
        gr, gg, gb = gradient(t)
        return (gr / 255, gg / 255, gb / 255, 1.0)
    if distance <= 0.032:
        return (0.369, 0.918, 0.831, 1.0)
    return (r / 255, g / 255, b / 255, 1.0)


def render(size: int, maskable: bool = False) -> bytes:
    ss = 2
    rows = bytearray()
    scale = 1.0 / (size * ss)
    for py in range(size):
        rows.append(0)
        for px in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sy in range(ss):
                for sx in range(ss):
                    x = (px * ss + sx + 0.5) * scale
                    y = (py * ss + sy + 0.5) * scale
                    if maskable:
                        # keep the mark inside the 80% safe zone
                        x = 0.5 + (x - 0.5) * 0.78
                        y = 0.5 + (y - 0.5) * 0.78
                    r, g, b, a = coverage(x, y)
                    acc[0] += r * a
                    acc[1] += g * a
                    acc[2] += b * a
                    acc[3] += a
            samples = ss * ss
            alpha = acc[3] / samples
            if alpha <= 0:
                rows.extend((0, 0, 0, 0))
            else:
                rows.extend(
                    (
                        round(acc[0] / acc[3] * 255),
                        round(acc[1] / acc[3] * 255),
                        round(acc[2] / acc[3] * 255),
                        round(alpha * 255),
                    )
                )
    return png(size, size, bytes(rows))


def png(width: int, height: int, raw: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size, maskable in (
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("maskable-512.png", 512, True),
        ("apple-touch-icon.png", 180, False),
    ):
        (OUT / name).write_bytes(render(size, maskable=maskable))
        print(f"wrote {OUT / name}")


if __name__ == "__main__":
    main()
