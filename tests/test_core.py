import json
import subprocess
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from caf_app.app import Awake, handle, main
from caf_app.radio import Radio, RadioState
from caf_app.scene import Scene, hit
from caf_app.state import World
from caf_app.terminal import Event, Input, Terminal


class WorldTests(unittest.TestCase):
    def test_clock_is_always_real_even_with_preview_override(self):
        for world in [World(), World(hour_override=23), World(demo=True)]:
            self.assertLess(
                abs((world.clock(800) - datetime.now().astimezone()).total_seconds()), 1
            )

    def test_day_night_and_gradual_weather(self):
        self.assertEqual(World(hour_override=12).lighting()[0:2], ("day", "day"))
        self.assertEqual(World(hour_override=1).lighting()[0:2], ("night", "night"))
        world = World()
        self.assertEqual(world.weather(10)[1], 0)
        self.assertGreater(world.weather(350)[1], 0.8)
        self.assertEqual(world.weather(580)[1], 0)
        self.assertGreater(world.weather(580)[2], 0)
        for t in [*range(720), 719.999]:
            for a, b in zip(world.weather(t)[:3], world.weather(t + 0.01)[:3]):
                self.assertLess(abs(a - b), 0.01)

    def test_lighting_wrap_is_continuous(self):
        a = World(hour_override=23.999).lighting()
        b = World(hour_override=0.001).lighting()
        self.assertEqual(a[-1], b[-1])


class TerminalTests(unittest.TestCase):
    def test_fragmented_mouse_packets_and_keys(self):
        parser = Input()
        self.assertEqual(parser.feed(b"\x1b[<0;"), [])
        result = parser.feed(b"30;17M\x1b[<0;30;17m\x1b[Cw")
        self.assertEqual(
            [(e.kind, e.value, e.x, e.y) for e in result],
            [
                ("click", 0, 29, 16),
                ("release", 0, 29, 16),
                ("key", "right", 0, 0),
                ("key", "w", 0, 0),
            ],
        )

    def test_query_reply_wheel_and_motion(self):
        result = Input().feed(
            b"\x1b[6;20;10t\x1b_Gi=31;OK\x1b\\\x1b[<64;25;10M\x1b[<35;4;5M"
        )
        self.assertEqual(
            [e.kind for e in result], ["cell", "graphics", "scroll", "move"]
        )
        self.assertEqual(result[0].value, (10, 20))

    def test_hit_mapping_accounts_for_letterboxing(self):
        terminal = Terminal()
        terminal.bounds = (10, 4, 100, 40)
        x, y = terminal.point(96, 32)
        self.assertEqual(hit(x, y), "power")
        self.assertEqual(terminal.point(0, 0), (-1, -1))

    def test_mouse_controls_do_not_trigger_on_release(self):
        class Player:
            def __init__(self):
                self.actions = []

            def command(self, *args):
                self.actions.append(args)

        radio = Player()
        world = World()
        terminal = Terminal()
        terminal.bounds = (0, 0, 768, 480)
        handle(Event("release", 0, 667, 341), world, radio, terminal)
        handle(Event("click", 0, 667, 341), world, radio, terminal)
        self.assertEqual(radio.actions, [("toggle",)])
        handle(Event("scroll", 64, 670, 368), world, radio, terminal)
        self.assertEqual(radio.actions[-1], ("volume", 5))


class ProcessTests(unittest.TestCase):
    def test_caffeinate_assertions_and_cleanup(self):
        with Awake() as awake:
            time.sleep(0.2)
            self.assertTrue(awake.alive)
            pid = awake.process.pid
            output = subprocess.check_output(["pmset", "-g", "assertions"], text=True)
            lines = [x for x in output.splitlines() if f"pid {pid}(" in x]
            self.assertTrue(
                any("PreventUserIdleDisplaySleep" in x for x in lines), lines
            )
            self.assertTrue(
                any("PreventUserIdleSystemSleep" in x for x in lines), lines
            )
        self.assertIsNotNone(awake.process.poll())

    def test_radio_starts_off_and_persists_preferences(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "radio.json"
            radio = Radio(config=path, silent=True)
            try:
                self.assertFalse(radio.snapshot().enabled)
                self.assertIsNone(radio.process)
                radio.command("station", 2)
                radio.command("volume", 10)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    if (
                        path.exists()
                        and json.loads(path.read_text()).get("volume") == 45
                    ):
                        break
                    time.sleep(0.03)
                self.assertEqual(
                    json.loads(path.read_text()), {"station": 2, "volume": 45}
                )
            finally:
                radio.close()
            other = Radio(config=path, silent=True)
            try:
                self.assertEqual(other.snapshot().station, 2)
                self.assertEqual(other.snapshot().volume, 45)
                self.assertFalse(other.snapshot().enabled)
            finally:
                other.close()


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = Scene()

    def test_modes_and_motion(self):
        renders = [
            self.scene.render(World(hour_override=h, weather_mode=w), t=17)
            for h, w in [(12, "clear"), (18, "cloudy"), (0, "rain")]
        ]
        self.assertEqual(len({im.tobytes() for im in renders}), 3)
        world = World(hour_override=12, weather_mode="rain")
        a = self.scene.render(world, t=20)
        b = self.scene.render(world, t=20.4)
        self.assertNotEqual(
            a.crop((235, 37, 576, 279)).tobytes(), b.crop((235, 37, 576, 279)).tobytes()
        )
        self.assertNotEqual(
            a.crop((142, 279, 311, 402)).tobytes(),
            b.crop((142, 279, 311, 402)).tobytes(),
        )
        self.assertEqual(a.size, (768, 480))


class GraphicsTests(unittest.TestCase):
    def test_tiled_updates_reconstruct_exact_pixels_and_skip_unchanged_tiles(self):
        import base64
        import re
        import zlib

        from PIL import Image

        terminal = Terminal(tmux=False)
        terminal.dimensions = lambda: (100, 32)
        terminal.cell = (10, 20)
        chunks = []
        terminal.write = chunks.append
        image = Image.new("RGB", (768, 480), "#281d2f")
        from PIL import ImageDraw

        ImageDraw.Draw(image).rectangle((210, 180, 460, 320), fill="#e9bb7a")
        terminal.draw(image)
        stream = b"".join(chunks)
        canvas = Image.new("RGB", (1000, 640))
        pos = (0, 0)
        payload = b""
        meta = {}
        count = 0
        tokens = re.finditer(
            rb"\x1b\[(\d+);(\d+)H|\x1b_G(.*?)\x1b\\", stream, re.DOTALL
        )
        for token in tokens:
            if token[1]:
                pos = (int(token[2]) - 1, int(token[1]) - 1)
                continue
            header, _, body = token[3].partition(b";")
            fields = dict(x.split(b"=", 1) for x in header.split(b",") if b"=" in x)
            if fields.get(b"a") == b"T":
                meta = fields
                payload = b""
            if b"m" in fields:
                payload += body
                if fields[b"m"] == b"0":
                    tile = Image.frombytes(
                        "RGB",
                        (int(meta[b"s"]), int(meta[b"v"])),
                        zlib.decompress(base64.b64decode(payload)),
                    )
                    self.assertEqual(
                        tile.size, (int(meta[b"c"]) * 10, int(meta[b"r"]) * 20)
                    )
                    canvas.paste(tile, (pos[0] * 10, pos[1] * 20))
                    count += 1
        self.assertEqual(count, 24)
        x, y, c, r = terminal.bounds
        expected = image.resize((c * 10, r * 20), Image.Resampling.NEAREST)
        self.assertEqual(
            canvas.crop((x * 10, y * 20, (x + c) * 10, (y + r) * 20)).tobytes(),
            expected.tobytes(),
        )
        chunks.clear()
        terminal.draw(image)
        self.assertNotIn(b"a=T", b"".join(chunks))
        ImageDraw.Draw(image).point((400, 230), fill="red")
        chunks.clear()
        terminal.draw(image)
        self.assertEqual(b"".join(chunks).count(b"a=T"), 1)


class FrameRateTests(unittest.TestCase):
    def test_continuous_mouse_input_keeps_frame_cap_and_processes_events(self):
        for focused, limit in [(True, 12), (False, 6)]:
            with self.subTest(focused=focused):
                now = [0.0]
                world = World(started=0.0, focused=focused)

                class BusyTerminal:
                    supported = False
                    cell = (10, 20)
                    frames = 0
                    inputs = 0

                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        pass

                    def read(self, timeout=0):
                        self.clock[0] += min(timeout, 0.001) if timeout else 0.001
                        self.inputs += 1
                        if not self.supported:
                            return [Event("graphics", "i=31;OK")]
                        return [Event("move", 35, 5, 5)]

                    def point(self, x, y):
                        return x, y

                    def draw(self, image):
                        self.clock[0] += 0.002
                        self.frames += 1

                terminal = BusyTerminal()
                terminal.clock = now
                with (
                    patch("caf_app.app.Terminal", return_value=terminal),
                    patch("caf_app.app.World", return_value=world),
                    patch("caf_app.app.Scene"),
                    patch("caf_app.app.Radio") as radio,
                    patch("caf_app.app.Awake") as awake,
                    patch(
                        "caf_app.app.time.monotonic", side_effect=lambda now=now: now[0]
                    ),
                    patch("sys.stdin.isatty", return_value=True),
                    patch("sys.stdout.isatty", return_value=True),
                    patch("builtins.print"),
                ):
                    radio.return_value.snapshot.return_value = RadioState()
                    awake.return_value.__enter__.return_value.alive = True
                    self.assertEqual(main(["--seconds", "1"]), 0)
                self.assertLessEqual(terminal.frames, limit + 2)
                self.assertGreater(terminal.inputs, 100)


if __name__ == "__main__":
    unittest.main()
