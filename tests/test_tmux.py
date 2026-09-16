import re
import unittest
from unittest.mock import patch

from PIL import Image

from caf_app.diacritics import DIACRITICS
from caf_app.terminal import Terminal


class TmuxTests(unittest.TestCase):
    def test_detection_and_escaping(self):
        with patch.dict("os.environ", {"TMUX": "/tmp/tmux-test,1,0"}):
            terminal = Terminal()
        command = b"\x1b_Ga=q,i=31;\x1b\\"
        self.assertEqual(
            terminal.passthrough(command),
            b"\x1bPtmux;\x1b\x1b_Ga=q,i=31;\x1b\x1b\\\x1b\\",
        )
        self.assertEqual(Terminal(tmux=False).passthrough(command), command)

    def test_placeholders_encode_full_id_and_explicit_coordinates(self):
        terminal = Terminal(tmux=True)
        output = terminal.placeholders(0x12345678, 7, 4, 3, 2).decode()
        self.assertTrue(output.startswith("\x1b[38;2;52;86;120m\x1b[59m"))
        for row in range(2):
            expected = f"\x1b[{5 + row};8H" + "".join(
                "\U0010eeee" + DIACRITICS[row] + DIACRITICS[col] + DIACRITICS[0x12]
                for col in range(3)
            )
            self.assertIn(expected, output)

    def test_virtual_tiles_refresh_and_clean_up_both_buffers(self):
        terminal = Terminal(tmux=True)
        terminal.dimensions = lambda: (80, 24)
        terminal.cell = (10, 20)
        output = []
        terminal.write = output.append
        frame = Image.new("RGB", (768, 480), "#654321")
        with patch("caf_app.terminal.time.monotonic", return_value=10):
            terminal.draw(frame)
        first_ids = set(terminal.image_ids)
        stream = b"".join(output)
        commands = re.findall(rb"\x1bPtmux;(.*?)\x1b\\", stream, re.DOTALL)
        self.assertTrue(commands)
        self.assertIn(b"U=1", stream)
        self.assertIn("\U0010eeee".encode(), stream)
        output.clear()
        with patch("caf_app.terminal.time.monotonic", return_value=10.1):
            terminal.draw(frame)
        self.assertNotIn(b"a=T", b"".join(output))
        output.clear()
        with patch("caf_app.terminal.time.monotonic", return_value=11.1):
            terminal.draw(frame)
        self.assertIn(b"a=T", b"".join(output))
        self.assertNotIn(b"a=d", b"".join(output))
        self.assertEqual(len(terminal.image_ids), 2 * len(first_ids))
        cleanup = terminal.delete_images()
        for ident in terminal.image_ids:
            self.assertIn(f"d=I,i={ident},".encode(), cleanup)

    def test_instances_use_separate_image_ids(self):
        with patch("caf_app.terminal.secrets.randbits", side_effect=[100000, 200000]):
            first, second = Terminal(tmux=True), Terminal(tmux=True)
        self.assertNotEqual(first.image_id_base, second.image_id_base)
