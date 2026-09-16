import base64
import fcntl
import math
import os
import re
import select
import shutil
import struct
import sys
import termios
import tty
import zlib
from dataclasses import dataclass

ESC = "\x1b"
MOUSE = re.compile(rb"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
CELL = re.compile(rb"\x1b\[6;(\d+);(\d+)t")


@dataclass
class Event:
    kind: str
    value: object = None
    x: int = 0
    y: int = 0


class Input:
    def __init__(self):
        self.buffer = b""

    def feed(self, data):
        self.buffer += data
        events = []
        while self.buffer:
            b = self.buffer
            match = MOUSE.match(b)
            if match:
                button, x, y = map(int, match.groups()[:3])
                release = match[4] == b"m"
                kind = (
                    "move"
                    if button & 32
                    else "scroll"
                    if button & 64
                    else "release"
                    if release
                    else "click"
                )
                events.append(Event(kind, button, x - 1, y - 1))
                self.buffer = b[match.end() :]
                continue
            match = CELL.match(b)
            if match:
                events.append(Event("cell", (int(match[2]), int(match[1]))))
                self.buffer = b[match.end() :]
                continue
            sequences = {
                b"\x1b[A": "up",
                b"\x1b[B": "down",
                b"\x1b[C": "right",
                b"\x1b[D": "left",
                b"\x1b[I": "focus",
                b"\x1b[O": "blur",
            }
            found = False
            for seq, key in sequences.items():
                if b.startswith(seq):
                    events.append(Event("key", key))
                    self.buffer = b[len(seq) :]
                    found = True
                    break
            if found:
                continue
            if b.startswith(b"\x1b_G"):
                end = b.find(b"\x1b\\")
                if end < 0:
                    break
                events.append(Event("graphics", b[3:end].decode(errors="replace")))
                self.buffer = b[end + 2 :]
                continue
            if b[0] == 27:
                if (
                    len(b) < 3
                    or (b.startswith(b"\x1b[<") and len(b) < 40)
                    or (b.startswith(b"\x1b[6;") and len(b) < 30)
                ):
                    break
                end = re.match(rb"\x1b\[[0-9;?]*[A-Za-z~]", b)
                self.buffer = b[end.end() :] if end else b[1:]
                continue
            value = chr(b[0])
            events.append(Event("key", value))
            self.buffer = b[1:]
        if len(self.buffer) > 4096:
            self.buffer = b""
        return events


class Terminal:
    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.saved = None
        self.parser = Input()
        self.cell = (9, 18)
        self.tiles = {}
        self.geometry = None
        self.bounds = (0, 0, 80, 24)
        self.size = (0, 0)
        self.supported = False

    def write(self, value):
        sys.stdout.buffer.write(value.encode() if isinstance(value, str) else value)
        sys.stdout.buffer.flush()

    def __enter__(self):
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise RuntimeError(
                "caf needs an interactive terminal. Run ./caf in Ghostty."
            )
        self.saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        self.write(
            ESC
            + "[?1049h"
            + ESC
            + "[?25l"
            + ESC
            + "[?1003h"
            + ESC
            + "[?1006h"
            + ESC
            + "[?1004h"
            + ESC
            + "[22;0t"
            + ESC
            + "]0;caf · stay a little longer\a"
            + ESC
            + "[48;2;18;16;26m"
            + ESC
            + "[2J"
            + ESC
            + "[16t"
        )
        self.write(ESC + "_Gi=31,a=q,t=d,f=24,s=1,v=1;AAAA" + ESC + "\\")
        return self

    def read(self, timeout=0):
        if select.select([self.fd], [], [], timeout)[0]:
            block = os.read(self.fd, 65536)
            if not block:
                return [Event("key", "q")]
            return self.parser.feed(block)
        return []

    def dimensions(self):
        cols, rows = shutil.get_terminal_size((80, 24))
        try:
            h, w, px, py = struct.unpack(
                "HHHH", fcntl.ioctl(self.fd, termios.TIOCGWINSZ, b"\0" * 8)
            )
            if px and py and w and h:
                self.cell = (px / w, py / h)
        except OSError:
            pass
        return cols, rows

    def layout(self):
        cols, rows = self.dimensions()
        cw, ch = self.cell
        width = max(1, cols)
        height = max(1, int(width * cw / ch * 480 / 768))
        if height > rows:
            height = max(1, rows)
            width = max(1, min(cols, int(height * ch / cw * 768 / 480)))
        x, y = (cols - width) // 2, (rows - height) // 2
        self.bounds = x, y, width, height
        return max(1, round(width * cw)), max(1, round(height * ch))

    def point(self, x, y):
        left, top, width, height = self.bounds
        if not (left <= x < left + width and top <= y < top + height):
            return -1, -1
        return (x - left + 0.5) / width * 768, (y - top + 0.5) / height * 480

    def draw(self, image):
        from PIL import Image

        pixels = self.layout()
        x, y, cols, rows = self.bounds
        geometry = self.bounds, pixels
        pieces = [(ESC + "[?2026h").encode()]
        if self.geometry != geometry:
            for _, ident in self.tiles.values():
                pieces.append(f"{ESC}_Ga=d,d=I,i={ident},q=2;{ESC}\\".encode())
            self.tiles.clear()
            self.geometry = geometry
            pieces.append((ESC + "[2J").encode())
        image = image.resize(pixels, Image.Resampling.NEAREST)
        step_x, step_y = max(1, math.ceil(cols / 6)), max(1, math.ceil(rows / 4))
        tile_index = 0
        for top in range(0, rows, step_y):
            for left in range(0, cols, step_x):
                width, height = min(step_x, cols - left), min(step_y, rows - top)
                crop = (
                    round(left / cols * pixels[0]),
                    round(top / rows * pixels[1]),
                    round((left + width) / cols * pixels[0]),
                    round((top + height) / rows * pixels[1]),
                )
                tile = image.crop(crop)
                raw = tile.tobytes()
                previous = self.tiles.get(tile_index)
                if previous and previous[0] == raw:
                    tile_index += 1
                    continue
                first_id = 1000 + tile_index * 2
                ident = (
                    first_id + 1 if previous and previous[1] == first_id else first_id
                )
                payload = base64.b64encode(zlib.compress(raw, 1))
                pieces.append(f"{ESC}[{y + top + 1};{x + left + 1}H".encode())
                chunks = [payload[i : i + 4096] for i in range(0, len(payload), 4096)]
                for index, block in enumerate(chunks):
                    prefix = (
                        f"a=T,f=24,o=z,s={tile.width},v={tile.height},i={ident},q=2,C=1,c={width},r={height},"
                        if index == 0
                        else ""
                    )
                    pieces.append(
                        f"{ESC}_G{prefix}m={int(index < len(chunks) - 1)};".encode()
                        + block
                        + f"{ESC}\\".encode()
                    )
                if previous:
                    pieces.append(
                        f"{ESC}_Ga=d,d=I,i={previous[1]},q=2;{ESC}\\".encode()
                    )
                self.tiles[tile_index] = raw, ident
                tile_index += 1
        pieces.append((ESC + "[?2026l").encode())
        self.write(b"".join(pieces))

    def __exit__(self, *args):
        try:
            remove = "".join(
                f"{ESC}_Ga=d,d=I,i={ident},q=2;{ESC}\\"
                for _, ident in self.tiles.values()
            )
            self.write(
                ESC
                + "[?2026l"
                + remove
                + ESC
                + "[?1003l"
                + ESC
                + "[?1006l"
                + ESC
                + "[?1004l"
                + ESC
                + "[0m"
                + ESC
                + "[?25h"
                + ESC
                + "[?1049l"
                + ESC
                + "[23;0t"
            )
        finally:
            if self.saved:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
