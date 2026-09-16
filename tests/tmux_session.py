"""Exercise real tmux with a simulated outer Kitty terminal, never a user's session."""

import base64
import fcntl
import json
import os
import pty
import re
import select
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import zlib
from pathlib import Path

from PIL import Image, ImageDraw

from caf_app.diacritics import DIACRITICS


def fixture():
    image = Image.new("RGB", (768, 480), "#291d35")
    draw = ImageDraw.Draw(image)
    for i in range(30):
        draw.rectangle(
            (i * 25, i * 13, i * 25 + 18, 479), fill=(i * 8, 255 - i * 7, i * 5)
        )
    return image


class OuterTerminal:
    def __init__(self, config, root, directory):
        self.root = root
        self.directory = directory
        self.label = "caf-test-" + str(os.getpid())
        self.images = {}
        self.buffer = b""
        self.payload = b""
        self.meta = {}
        self.queries = 0
        self.transfers = 0
        self.master, self.slave = pty.openpty()
        fcntl.ioctl(
            self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 100, 1000, 640)
        )
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in ("TMUX", "TMUX_PANE")
        }
        env.update(
            TERM="xterm-256color",
            LC_ALL="en_US.UTF-8",
            XDG_CONFIG_HOME=str(directory / "config"),
        )
        self.client = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import os, sys; os.login_tty(0); os.execvp(sys.argv[1], sys.argv[1:])",
                "tmux",
                "-L",
                self.label,
                "-f",
                str(config),
                "new-session",
                "-s",
                "test",
                "-c",
                str(root),
                "sleep 60",
            ],
            stdin=self.slave,
            stdout=self.slave,
            stderr=self.slave,
            env=env,
        )

    def tmux(self, *args):
        return subprocess.check_output(
            ["tmux", "-L", self.label, *args], text=True
        ).strip()

    def command(self, name):
        return shlex.join(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--child",
                str(self.directory / (name + ".json")),
            ]
        )

    def pump(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if not select.select(
                [self.master], [], [], min(0.02, max(0, deadline - time.monotonic()))
            )[0]:
                continue
            self.buffer += os.read(self.master, 1048576)
            consumed = 0
            for token in re.finditer(
                rb"\x1b_G(.*?)\x1b\\|\x1b\[(16t|c|>c)", self.buffer, re.DOTALL
            ):
                consumed = token.end()
                if token[2]:
                    response = {
                        b"16t": b"\x1b[6;20;10t",
                        b"c": b"\x1b[?1;2c",
                        b">c": b"\x1b[>0;4000;0c",
                    }[token[2]]
                    os.write(self.master, response)
                    continue
                header, _, body = token[1].partition(b";")
                fields = dict(
                    value.split(b"=", 1)
                    for value in header.split(b",")
                    if b"=" in value
                )
                if fields.get(b"a") == b"q":
                    self.queries += 1
                    os.write(self.master, b"\x1b_Gi=" + fields[b"i"] + b";OK\x1b\\")
                elif fields.get(b"a") == b"d":
                    self.images.pop(int(fields[b"i"]), None)
                if fields.get(b"a") == b"T":
                    assert fields[b"U"] == b"1", "tmux must use virtual placements"
                    assert fields[b"q"] == b"2"
                    self.meta, self.payload = fields, b""
                if b"m" in fields:
                    self.payload += body
                    if fields[b"m"] == b"0" and self.meta:
                        meta = self.meta
                        image = Image.frombytes(
                            "RGB",
                            (int(meta[b"s"]), int(meta[b"v"])),
                            zlib.decompress(base64.b64decode(self.payload)),
                        )
                        self.images[int(meta[b"i"])] = (
                            image,
                            int(meta[b"c"]),
                            int(meta[b"r"]),
                        )
                        self.transfers += 1
                        self.meta, self.payload = {}, b""
            self.buffer = self.buffer[consumed:]
            start = self.buffer.find(b"\x1b_G")
            self.buffer = self.buffer[start:] if start >= 0 else self.buffer[-32:]

    def until(self, condition, seconds=5):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.pump(0.05)
            if condition():
                return
        raise AssertionError("tmux condition timed out")

    def report(self, name):
        path = self.directory / (name + ".json")
        return json.loads(path.read_text()) if path.exists() else None

    def check_pixels(self, pane, name):
        frames = self.report(name)["frames"]
        # Stop after a completed frame, not halfway through a resize upload.
        self.until(lambda: self.report(name)["frames"] > frames)
        info = self.report(name)
        os.kill(info["pid"], signal.SIGSTOP)
        try:
            self.pump(0.15)
            capture = self.tmux("capture-pane", "-e", "-p", "-t", pane)
            cells = {}
            color = (255, 255, 255)
            for row, line in enumerate(capture.splitlines()):
                col = 0
                for token in re.finditer(
                    r"\x1b\[([0-9;:]*)m|\U0010eeee(.)(.)(.)|([^\x1b])", line
                ):
                    if token[1] is not None:
                        values = [int(v) if v else 0 for v in token[1].split(";")]
                        if values[:2] == [38, 2]:
                            color = tuple(values[2:5])
                    elif token[2]:
                        ident = (
                            (DIACRITICS.index(token[4]) << 24)
                            | (color[0] << 16)
                            | (color[1] << 8)
                            | color[2]
                        )
                        assert ident in self.images, (
                            "Placeholder references a missing image",
                            ident,
                        )
                        cells[(col, row)] = (
                            ident,
                            DIACRITICS.index(token[2]),
                            DIACRITICS.index(token[3]),
                        )
                        col += 1
                    elif token[5]:
                        col += 1
            left, top, cols, rows = info["bounds"]
            expected_cells = {
                (x, y) for y in range(top, top + rows) for x in range(left, left + cols)
            }
            assert set(cells) == expected_cells, (
                len(cells),
                len(expected_cells),
                info["bounds"],
            )
            cw, ch = map(round, info["cell"])
            canvas = Image.new("RGB", (cols * cw, rows * ch))
            for (x, y), (ident, row, col) in cells.items():
                image, width, height = self.images[ident]
                assert image.size == (width * cw, height * ch)
                cell = image.crop((col * cw, row * ch, (col + 1) * cw, (row + 1) * ch))
                canvas.paste(cell, ((x - left) * cw, (y - top) * ch))
            assert (
                canvas.tobytes()
                == fixture().resize(canvas.size, Image.Resampling.NEAREST).tobytes()
            )
            return {ident for ident, _, _ in cells.values()}
        finally:
            os.kill(info["pid"], signal.SIGCONT)

    def close(self):
        subprocess.run(
            ["tmux", "-L", self.label, "kill-server"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        os.close(self.master)
        os.close(self.slave)
        if self.client.poll() is None:
            self.client.kill()
        self.client.wait(timeout=5)


def run():
    assert shutil.which("tmux"), "Install tmux to run this integration test"
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="caf-tmux-") as temporary:
        directory = Path(temporary)
        config = directory / "tmux.conf"
        config.write_text(
            "set -g default-shell /bin/sh\nset -g default-terminal tmux-256color\n"
            'set -as terminal-features ",xterm-256color:RGB"\n'
            "set -g allow-passthrough on\nset -g mouse on\nset -g focus-events on\n"
            "set -g remain-on-exit on\nset -g status off\nset -s escape-time 0\n"
        )
        terminal = OuterTerminal(config, root, directory)
        pids = []
        try:
            terminal.pump(0.2)
            first = terminal.tmux("display-message", "-p", "#{pane_id}")
            terminal.tmux("respawn-pane", "-k", "-t", first, terminal.command("first"))
            terminal.until(lambda: terminal.report("first") is not None)
            terminal.pump(1.2)
            first_ids = terminal.check_pixels(first, "first")
            print(
                "Negotiation and exact pixel reconstruction through tmux passed.",
                flush=True,
            )

            terminal.tmux("new-window", "-n", "away", "sleep 60")
            terminal.pump(1.2)
            terminal.images.clear()  # A newly attached outer terminal starts with no images.
            terminal.tmux("select-window", "-t", "test:0")
            terminal.pump(1.4)
            terminal.check_pixels(first, "first")
            print(
                "Hidden-window return restores every tile, including static regions.",
                flush=True,
            )

            second = terminal.tmux(
                "split-window",
                "-h",
                "-P",
                "-F",
                "#{pane_id}",
                "-t",
                first,
                terminal.command("second"),
            )
            terminal.until(lambda: terminal.report("second") is not None)
            terminal.pump(1.4)
            first_ids = terminal.check_pixels(first, "first")
            second_ids = terminal.check_pixels(second, "second")
            assert first_ids.isdisjoint(second_ids)
            print(
                "Two split cafes reconstruct correctly with independent image IDs.",
                flush=True,
            )

            terminal.tmux("resize-pane", "-Z", "-t", first)
            terminal.pump(1.4)
            terminal.check_pixels(first, "first")
            terminal.tmux("resize-pane", "-Z", "-t", first)
            terminal.pump(1.4)
            terminal.check_pixels(first, "first")
            print("Zoom and unzoom preserve pane-relative image placement.", flush=True)

            info = terminal.report("first")
            offset = terminal.tmux(
                "display-message", "-p", "-t", first, "#{pane_left},#{pane_top}"
            )
            ox, oy = map(int, offset.split(","))
            x, y, cols, rows = info["bounds"]
            cx, cy = (
                ox + x + int(620 / 768 * cols) + 1,
                oy + y + int(65 / 480 * rows) + 1,
            )
            os.write(terminal.master, f"\x1b[<0;{cx};{cy}M\x1b[<0;{cx};{cy}m".encode())
            terminal.until(lambda: terminal.report("first")["lamp"] == 2)
            terminal.tmux("send-keys", "-t", second, "ww")
            terminal.until(
                lambda: (
                    terminal.report("second")["weather"] == "OVERCAST"
                    and terminal.report("second")["frames"] > 3
                )
            )

            for pane, name in [(first, "first"), (second, "second")]:
                pids.append(terminal.report(name)["caffeinate_pid"])
                terminal.tmux("send-keys", "-t", pane, "q")
                terminal.until(
                    lambda pane=pane: (
                        terminal.tmux(
                            "display-message", "-p", "-t", pane, "#{pane_dead}"
                        )
                        == "1"
                    )
                )
                assert (
                    terminal.tmux(
                        "display-message", "-p", "-t", pane, "#{pane_dead_status}"
                    )
                    == "0"
                )
                assert "\U0010eeee" not in terminal.tmux(
                    "capture-pane", "-p", "-t", pane
                )
            for pid in pids:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    continue
                raise AssertionError("Leaked keep-awake process")
            print(
                "Mouse, keyboard, clean exit, and keep-awake cleanup passed.",
                flush=True,
            )

            terminal.tmux("select-pane", "-t", first)
            terminal.tmux("set-option", "-p", "-t", first, "allow-passthrough", "off")
            terminal.tmux(
                "respawn-pane", "-k", "-t", first, terminal.command("blocked")
            )
            terminal.until(
                lambda: (
                    terminal.tmux("display-message", "-p", "-t", first, "#{pane_dead}")
                    == "1"
                )
            )
            assert (
                terminal.tmux(
                    "display-message", "-p", "-t", first, "#{pane_dead_status}"
                )
                == "1"
            )
            output = terminal.tmux("capture-pane", "-p", "-J", "-t", first)
            assert "tmux set -g allow-passthrough on" in output
            assert terminal.report("blocked") is None
            print("Disabled passthrough exits with an actionable error.", flush=True)
        finally:
            terminal.close()


if __name__ == "__main__":
    if "--child" in sys.argv:
        from caf_app import app

        class StaticScene:
            def __init__(self):
                self.frame = fixture()

            def render(self, *args):
                return self.frame

        app.Scene = StaticScene
        raise SystemExit(
            app.main(["--diagnostics", sys.argv[2], "--seconds", "45", "--fps", "8"])
        )
    run()
