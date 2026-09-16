import math
import random
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from .radio import STATIONS, RadioState
from .state import duration

ASSETS = Path(__file__).resolve().parent / "assets"
W, H = 768, 480
WINDOW = (235, 37, 576, 279)
HITS = {
    "power": (654, 333, 682, 354),
    "previous": (563, 382, 592, 401),
    "next": (650, 382, 681, 401),
    "volume": (651, 352, 688, 381),
    "preset0": (580, 369, 595, 381),
    "preset1": (597, 369, 612, 381),
    "preset2": (614, 369, 629, 381),
    "preset3": (631, 369, 646, 381),
    "cat": (344, 319, 462, 391),
    "coffee": (142, 279, 311, 402),
    "lamp": (583, 25, 654, 114),
    "window": WINDOW,
    "radio": (549, 318, 697, 408),
}


def hit(x, y):
    for name, (l, t, r, b) in HITS.items():
        if l <= x < r and t <= y < b:
            return name
    return ""


def mix(a, b, amount):
    return tuple(round(x * (1 - amount) + y * amount) for x, y in zip(a, b))


class Scene:
    def __init__(self):
        self.backgrounds = {}
        for name, file in [
            ("dusk", "cafe.png"),
            ("day", "day.png"),
            ("night", "night.png"),
        ]:
            path = ASSETS / file
            if not path.exists():
                path = ASSETS / "cafe.png"
            self.backgrounds[name] = (
                Image.open(path).convert("RGB").resize((W, H), Image.Resampling.NEAREST)
            )
        self.fonts = {
            n: ImageFont.truetype(str(ASSETS / "Silkscreen-Regular.ttf"), n)
            for n in (8, 10, 12, 16, 20)
        }
        rng = random.Random(1709)
        self.rain = [
            (rng.random(), rng.random(), rng.random(), rng.random()) for _ in range(100)
        ]
        self.dust = [(rng.random(), rng.random(), rng.random()) for _ in range(20)]
        self.stars = [
            (rng.randint(242, 568), rng.randint(43, 162), rng.random())
            for _ in range(28)
        ]
        self.cloud_sprites = self.atlas(
            "clouds.png",
            [
                (0, 0, 840, 500),
                (840, 0, 1536, 500),
                (0, 500, 790, 1024),
                (790, 500, 1536, 1024),
            ],
            [142, 112, 156, 145],
        )
        self.cat_sprites = self.atlas(
            "miso.png",
            [
                (0, 0, 820, 480),
                (820, 0, 1536, 480),
                (0, 480, 820, 1024),
                (820, 480, 1536, 1024),
            ],
            [128, 123, 145, 119],
        )
        self.cloud_tints = {}
        self.cache_key = None
        self.cached = None
        self.text_mask = lru_cache(maxsize=512)(self.text_mask)

    def atlas(self, name, regions, widths):
        sheet = Image.open(ASSETS / name).convert("RGBA")
        sprites = []
        for box, width in zip(regions, widths):
            sprite = sheet.crop(box)
            bounds = (
                sprite.getchannel("A").point(lambda v: 255 if v > 30 else 0).getbbox()
            )
            sprite = sprite.crop(bounds)
            sprite = sprite.resize(
                (width, round(sprite.height * width / sprite.width)),
                Image.Resampling.NEAREST,
            )
            sprites.append(sprite)
        return sprites

    def text_mask(self, text, size, anchor):
        core, offset = self.fonts[size].getmask2(text, mode="1", anchor=anchor)
        return Image.frombytes("L", core.size, bytes(core)), offset

    def text(self, draw, pos, text, color="#f3d5b3", size=10, anchor=None):
        mask, (dx, dy) = self.text_mask(str(text), size, anchor)
        draw.bitmap((pos[0] + dx, pos[1] + dy), mask, fill=color)

    def render(self, world, radio=None, t=None):
        t = world.elapsed() if t is None else t
        radio = radio or RadioState()
        a, b, blend, night = world.lighting(t)
        key = a, b, round(blend, 3)
        if key != self.cache_key:
            self.cached = Image.blend(self.backgrounds[a], self.backgrounds[b], blend)
            self.cache_key = key
        im = self.cached.copy().convert("RGBA")
        self.weather(im, world, t, night)
        self.lighting(im, world, t, night)
        self.clock(im, world.clock(t))
        self.coffee(im, t, world)
        self.cat(im, t, world)
        self.radio(im, t, radio, world)
        self.details(im, t, world)
        self.footer(im, world, radio, t)
        if world.help:
            self.help(im)
        return im.convert("RGB")

    def weather(self, im, world, t, night):
        cloud, rain, wet, _ = world.weather(t)
        layer = Image.new("RGBA", (W, H))
        d = ImageDraw.Draw(layer)
        x0, y0, x1, y1 = WINDOW
        if cloud:
            d.rectangle(WINDOW, fill=(40, 48, 70, int(cloud * 55)))
        for x, y, phase in self.stars:
            alpha = int(
                night * (1 - cloud) * max(0, 80 + 90 * math.sin(t * 0.4 + phase * 20))
            )
            if alpha:
                d.point((x, y), fill=(255, 232, 195, alpha))
                if phase > 0.9:
                    d.line((x - 1, y, x + 1, y), fill=(255, 232, 195, alpha // 2))
        # Celestial objects and weather are separate from the clean painted sky.
        hour = world.sky_clock(t).hour + world.sky_clock(t).minute / 60
        if night > 0.05:
            mx = 492 + int(math.sin((hour - 1) / 12 * math.pi) * 29)
            my = 91 + int(math.cos((hour - 1) / 12 * math.pi) * 12)
            moon = Image.new("RGBA", (28, 28))
            md = ImageDraw.Draw(moon)
            md.ellipse(
                (3, 3, 24, 24),
                fill=(251, 221, 169, int(night * (1 - cloud * 0.95) * 235)),
            )
            md.ellipse((0, 0, 20, 21), fill=(0, 0, 0, 0))
            layer.alpha_composite(moon, (mx, my))
        if 6 < hour < 18:
            angle = (hour - 6) / 12 * math.pi
            sx = int(x0 + 25 + (x1 - x0 - 50) * (hour - 6) / 12)
            sy = int(135 - math.sin(angle) * 74)
            alpha = int((1 - cloud) * 140)
            d.ellipse(
                (sx - 10, sy - 10, sx + 10, sy + 10), fill=(255, 225, 168, alpha // 5)
            )
            d.ellipse((sx - 6, sy - 6, sx + 6, sy + 6), fill=(255, 231, 180, alpha))
        clouds = Image.new("RGBA", (x1 - x0, y1 - y0))
        a, b, f, _ = world.lighting(t)
        tones = {
            "day": (249, 233, 217),
            "dusk": (222, 150, 167),
            "night": (78, 86, 131),
        }
        color = mix(tones[a], tones[b], f)
        tint_key = tuple(round(v / 8) * 8 for v in color)
        if tint_key not in self.cloud_tints:
            tinted = []
            for sprite in self.cloud_sprites:
                tone = ImageOps.colorize(
                    sprite.convert("L"),
                    tuple(max(0, v - 90) for v in tint_key),
                    tuple(min(255, v) for v in tint_key),
                ).convert("RGBA")
                tone.putalpha(sprite.getchannel("A"))
                tinted.append(tone)
            self.cloud_tints[tint_key] = tinted
        for i in range(6):
            sprite = self.cloud_tints[tint_key][i % 4]
            opacity = min(1, max(0, cloud * 2.1 - (i % 3) * 0.25))
            if opacity <= 0:
                continue
            cx = (
                int(
                    (t * (0.45 + i * 0.09) * (1 + cloud * 0.7) + i * 91)
                    % (x1 - x0 + sprite.width)
                )
                - sprite.width
            )
            cy = 17 + (i * 29) % 100
            moving = sprite.copy()
            moving.putalpha(
                sprite.getchannel("A").point(
                    lambda v, opacity=opacity: int(v * opacity)
                )
            )
            clouds.alpha_composite(moving, (cx, cy))
        layer.alpha_composite(clouds, (x0, y0))
        if night < 0.6 and rain < 0.1:
            flight = t % 67
            if flight < 14:
                for i in range(3):
                    x = int(x0 + flight * 27 - i * 12)
                    y = int(120 + i * 8 + math.sin(t * 1.5 + i) * 3)
                    if x0 + 5 < x < x1 - 5:
                        wing = int(math.sin(t * 8) * 2)
                        d.line(
                            [(x - 3, y - wing), (x, y + 1), (x + 3, y - wing)],
                            fill=(53, 51, 76, 200),
                        )
        # A tiny train crosses the distant raised railway.
        travel = t % 91
        if travel < 20:
            x = int(x0 - 50 + travel * 22)
            for n in range(4):
                l, r = max(x0, x + n * 15), min(x1, x + n * 15 + 13)
                if l < r:
                    d.rectangle((l, 247, r, 251), fill=(61, 65, 90, 220))
                    d.line(
                        (l, 248, r, 248),
                        fill=(247, 192, 118, 210 if night > 0.4 else 120),
                    )
        if rain:
            for u, v, s, phase in self.rain:
                x = int(x0 + u * (x1 - x0))
                y = int(y0 + (v * (y1 - y0) + t * (38 + s * 55)) % (y1 - y0))
                length = 3 + int(s * 6)
                d.line(
                    (x, y, max(x0, x - 2), min(y1, y + length)),
                    fill=(186, 202, 226, int(40 + rain * 70)),
                )
        if wet:
            for u, v, s, phase in self.rain[:32]:
                x = int(x0 + u * (x1 - x0))
                y = int(y0 + (v * (y1 - y0) + t * (1 + s * 3)) % (y1 - y0))
                d.line(
                    (x, y, x, min(y1, y + 3 + int(s * 7))),
                    fill=(182, 201, 224, int(wet * 95)),
                )
                d.point((x - 1, y), fill=(220, 226, 236, int(wet * 130)))
        im.alpha_composite(layer)

    def lighting(self, im, world, t, night):
        layer = Image.new("RGBA", (W, H))
        d = ImageDraw.Draw(layer)
        if world.lamp == 0:
            d.polygon(
                [(585, 78), (651, 78), (703, 392), (541, 392)], fill=(20, 24, 47, 58)
            )
        else:
            strength = 1 if world.lamp == 1 else 1.7
            for step in range(8, 0, -1):
                a = int((1 + night * 2) * strength)
                d.ellipse(
                    (590 - step * 5, 330 - step * 2, 652 + step * 5, 366 + step * 2),
                    fill=(255, 176, 69, a * 2),
                )
            d.polygon(
                [(588, 80), (651, 80), (696, 376), (541, 376)],
                fill=(255, 192, 100, int((5 + night * 6) * strength)),
            )
        hour = world.sky_clock(t).hour + world.sky_clock(t).minute / 60
        if 7 < hour < 17:
            shift = int((hour - 12) * 14)
            d.polygon(
                [(235, 222), (330, 222), (480 + shift, 389), (347 + shift, 389)],
                fill=(255, 220, 157, 13),
            )
            d.polygon(
                [(390, 239), (441, 239), (614 + shift, 389), (544 + shift, 389)],
                fill=(255, 220, 157, 10),
            )
        for u, v, phase in self.dust:
            x = int(270 + u * 330 + math.sin(t * 0.17 + phase * 20) * 7)
            y = int(110 + (v * 230 - t * (0.8 + phase)) % 230)
            alpha = int(35 + 25 * math.sin(t + phase * 30))
            d.rectangle((x, y, x + 1, y + 1), fill=(255, 218, 162, alpha))
        if night > 0.6 and t % 79 < 5:
            p = t % 79 / 5
            x = int(-100 + p * 850)
            d.polygon(
                [(x, 302), (x + 15, 302), (x + 210, 12), (x + 160, 12)],
                fill=(249, 213, 151, int(12 * math.sin(p * math.pi))),
            )
        im.alpha_composite(layer)

    def clock(self, im, now):
        d = ImageDraw.Draw(im)
        cx, cy, r = 740, 78, 29
        d.ellipse(
            (cx - r - 3, cy - r - 4, cx + r + 3, cy + r + 4),
            fill="#251f28",
            outline="#5b4140",
            width=2,
        )
        d.ellipse(
            (cx - r, cy - r, cx + r, cy + r), fill="#ceb08b", outline="#8d6c55", width=2
        )
        for n in range(60):
            a = n * math.tau / 60 - math.pi / 2
            inner = r - (6 if n % 5 == 0 else 3)
            d.line(
                (
                    cx + math.cos(a) * inner,
                    cy + math.sin(a) * inner,
                    cx + math.cos(a) * (r - 2),
                    cy + math.sin(a) * (r - 2),
                ),
                fill="#665049",
                width=2 if n % 5 == 0 else 1,
            )
        for number, (dx, dy) in {
            "12": (0, -19),
            "3": (19, 0),
            "6": (0, 18),
            "9": (-19, 0),
        }.items():
            self.text(d, (cx + dx, cy + dy), number, "#382c30", 8, "mm")
        for angle, length, width, color in [
            ((now.hour % 12 + now.minute / 60) * math.tau / 12, 14, 3, "#382c30"),
            ((now.minute + now.second / 60) * math.tau / 60, 21, 2, "#382c30"),
            (now.second * math.tau / 60, 23, 1, "#a45b47"),
        ]:
            a = angle - math.pi / 2
            d.line(
                (cx, cy, cx + math.cos(a) * length, cy + math.sin(a) * length),
                fill=color,
                width=width,
            )
        d.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill="#51382f")

    def coffee(self, im, t, world):
        layer = Image.new("RGBA", (W, H))
        d = ImageDraw.Draw(layer)
        ink = "#312536"
        dark = "#643b32"
        copper = "#b5714b"
        gold = "#e4ad6c"
        cream = "#f3dab0"
        d.ellipse((151, 380, 287, 401), fill=(25, 18, 29, 90))
        # Copper pour-over stand, with a bevel and warm highlights.
        d.rounded_rectangle((161, 388, 247, 395), 3, fill=ink)
        d.rectangle((166, 386, 244, 389), fill=copper)
        d.rectangle((169, 290, 176, 388), fill=dark)
        d.rectangle((170, 291, 172, 386), fill=gold)
        d.rectangle((170, 289, 224, 295), fill=copper)
        d.line((171, 289, 225, 289), fill=gold, width=2)
        d.ellipse((194, 294, 241, 304), fill=ink)
        d.polygon([(195, 297), (240, 297), (226, 323), (208, 323)], fill=copper)
        d.polygon([(199, 299), (235, 299), (224, 319), (211, 319)], fill=cream)
        d.polygon([(201, 299), (232, 299), (225, 308), (208, 308)], fill="#6f4436")
        for i in range(5):
            d.line((201 + i * 7, 301, 211 + i * 3, 318), fill="#cbb68e")
        d.ellipse((194, 294, 241, 301), fill=gold, outline=ink, width=2)
        d.ellipse((200, 296, 235, 299), fill="#533533")
        # Glass carafe: transparent body, layered coffee, glass glints.
        d.polygon(
            [
                (205, 345),
                (227, 345),
                (231, 356),
                (237, 380),
                (232, 385),
                (200, 385),
                (195, 380),
                (202, 356),
            ],
            fill=(135, 162, 167, 66),
            outline="#bfbbb0",
            width=2,
        )
        d.polygon(
            [(200, 368), (232, 368), (235, 379), (231, 382), (201, 382), (198, 379)],
            fill="#58342c",
        )
        d.ellipse((200, 364, 232, 371), fill="#9b6945")
        d.line((201, 358, 198, 376), fill="#e5d7ba", width=2)
        d.line((229, 356, 233, 370), fill="#a9babb")
        d.rectangle((203, 348, 228, 353), fill=dark)
        d.line((204, 348, 228, 348), fill=copper, width=2)
        d.arc((228, 353, 246, 377), 270, 90, fill=copper, width=4)
        phase = t % 1.6 / 1.6
        if phase < 0.55:
            d.ellipse((215, 322, 218, 324 + int(phase * 4)), fill="#b88051")
        elif phase < 0.92:
            drop_y = 327 + int(((phase - 0.55) / 0.37) ** 2 * 39)
            d.line((216, drop_y - 3, 216, drop_y), fill="#c29560", width=2)
        else:
            radius = 2 + int((phase - 0.92) / 0.08 * 12)
            d.arc((216 - radius, 365, 216 + radius, 369), 0, 355, fill="#d6b080")
        # Your porcelain cup and saucer.
        shift = int(42 * (1 - (t % 3600) / 4)) if 0 < t % 3600 < 4 and t > 10 else 0
        if world.brew_until > t:
            shift = int(max(0, world.brew_until - t - 3) * 12)
        x = 272 + shift
        d.ellipse((x - 29, 388, x + 27, 396), fill="#342a31")
        d.ellipse((x - 26, 386, x + 26, 392), fill="#c9b195")
        d.ellipse((x + 12, 366, x + 28, 383), fill=cream)
        d.ellipse((x + 16, 369, x + 24, 379), fill="#75503e")
        d.rounded_rectangle((x - 19, 363, x + 16, 387), 6, fill="#d5ba92")
        d.rectangle((x - 17, 366, x - 12, 380), fill="#f5dcb0")
        d.ellipse((x - 19, 359, x + 16, 368), fill=cream)
        d.ellipse((x - 15, 361, x + 12, 366), fill="#674233")
        d.arc((x - 9, 362, x + 6, 365), 0, 280, fill="#d8ab70")
        # Independent curls with rising particles; occasional heart in the steam.
        for n in range(3):
            points = []
            for j in range(21):
                yy = 357 - j * 2
                xx = (
                    x
                    - 9
                    + n * 8
                    + math.sin(j * 0.36 - t * 1.4 + n * 2) * (2 + j * 0.12)
                )
                points.append((int(xx), yy))
            d.line(points, fill=(255, 226, 195, 48 + n * 11), width=1)
        if t % 89 < 4 and t > 10:
            self.heart(d, x, 310 - int(t % 89 * 4), (246, 201, 184, 100))
        if world.brew_until > t:
            d.arc(
                (x - 12, 361, x + 10, 366),
                int(t * 190) % 360,
                int(t * 190) % 360 + 230,
                fill=gold,
            )
        if world.hover == "coffee":
            self.text(d, (216, 273), "FRESH CUP?", "#f8deb2", 10, "mm")
        im.alpha_composite(layer)

    def heart(self, d, x, y, color):
        d.polygon(
            [
                (x - 4, y),
                (x - 2, y - 2),
                (x, y),
                (x + 2, y - 2),
                (x + 4, y),
                (x + 4, y + 2),
                (x, y + 6),
                (x - 4, y + 2),
            ],
            fill=color,
        )

    def cat(self, im, t, world):
        active = world.cat_until > t
        hour = world.sky_clock(t).hour
        stretch = not active and 79 < t % 87 < 83
        alert = (
            world.cat_watch_until > t
            or (17 <= hour < 21 and t % 31 < 9)
            or 45 < t % 63 < 48
        )
        pose = 3 if active else 2 if stretch else 1 if alert and t % 5 > 0.18 else 0
        sprite = self.cat_sprites[pose]
        breath = int(math.sin(t * 1.4) > 0.35)
        sprite = sprite.resize(
            (sprite.width, sprite.height + breath), Image.Resampling.NEAREST
        )
        night = world.lighting(t)[3]
        sprite = ImageEnhance.Brightness(sprite).enhance(1 - 0.12 * night)
        if t % 19 < 4:
            # A small local displacement gives the wrapped tail a sleepy twitch.
            cut = int(sprite.width * 0.74)
            tail = sprite.crop(
                (cut, int(sprite.height * 0.65), sprite.width, sprite.height)
            )
            sprite.alpha_composite(
                tail, (cut + int(math.sin(t * 2) * 1.5), int(sprite.height * 0.65))
            )
        x = 335 if stretch else 343
        y = 389 - sprite.height
        shadow = Image.new("RGBA", (W, H))
        sd = ImageDraw.Draw(shadow)
        sd.ellipse((340, 378, 472, 397), fill=(21, 15, 23, 92))
        im.alpha_composite(shadow)
        im.alpha_composite(sprite, (x, y))
        d = ImageDraw.Draw(im)
        if active:
            self.heart(d, 375, y - 9 - int((t % 1.5) * 5), "#e9a6a0")
        elif pose == 0 and t % 27 < 5:
            self.text(d, (355, y - 9 - int(t % 27 * 3)), "z", "#c0a8b1", 10)
        if world.hover == "cat":
            self.text(d, (402, y - 13), "MISO", "#f7d9aa", 10, "mm")

    def radio(self, im, t, radio, world):
        d = ImageDraw.Draw(im)
        d.ellipse((550, 397, 704, 412), fill="#49302e")
        d.rectangle((556, 324, 696, 398), fill="#302431")
        d.rectangle((552, 328, 699, 394), fill="#302431")
        d.rectangle((555, 326, 696, 394), fill="#94603f")
        d.rectangle((558, 329, 693, 390), fill="#bb7e4e")
        d.line((559, 327, 691, 327), fill="#ddaa6b", width=2)
        for y in (332, 336, 384, 388):
            d.line((561, y, 691, y), fill="#a16b43")
        d.rectangle((560, 394, 571, 400), fill="#36272a")
        d.rectangle((681, 394, 692, 400), fill="#36272a")
        # Woven speaker grille.
        d.rectangle((563, 343, 591, 379), fill="#4c3a35")
        for y in range(345, 379, 3):
            for x in range(564, 591, 3):
                d.point((x + (1 if y % 2 else 0), y), fill="#c29666")
        # Backlit dial and a real moving station needle.
        d.rectangle((598, 337, 650, 365), fill="#45302b")
        d.rectangle(
            (600, 339, 648, 363), fill="#dca85a" if radio.enabled else "#8e7855"
        )
        for x in range(603, 648, 4):
            d.line((x, 341, x, 345 + (2 if x % 3 == 0 else 0)), fill="#805c3c")
        needle = 605 + radio.station * 12
        if radio.status in ("TUNING", "RECONNECTING"):
            needle = 623 + int(math.sin(t * 3) * 19)
        d.line((needle, 340, needle, 348), fill="#9f4336", width=2)
        self.text(
            d,
            (624, 354),
            ["LOFI", "BEATS", "GROOVE", "DRONE"][radio.station],
            "#4c352c",
            8,
            "mm",
        )
        d.ellipse((660, 335, 675, 350), fill="#382f31", outline="#d0a76f", width=1)
        d.arc(
            (663, 338, 672, 347),
            -50,
            230,
            fill="#eac180" if radio.enabled else "#8c7360",
            width=2,
        )
        d.line((667, 337, 667, 341), fill="#eac180" if radio.enabled else "#8c7360")
        led = (
            "#96bb88"
            if radio.playing
            else "#edb674"
            if radio.enabled and int(t * 3) % 2
            else "#5b4940"
        )
        d.ellipse((683, 340, 687, 344), fill=led)
        d.ellipse((658, 355, 681, 378), fill="#382d30", outline="#d3a367", width=2)
        angle = (-135 + radio.volume * 2.7) * math.pi / 180
        d.line(
            (670, 367, 670 + math.sin(angle) * 8, 367 - math.cos(angle) * 8),
            fill="#efc88d",
            width=2,
        )
        # The four tactile station presets.
        for n in range(4):
            x = 580 + n * 17
            d.rectangle((x, 373, x + 12, 381), fill="#503932")
            d.rectangle(
                (x, 370 if n != radio.station else 372, x + 12, 377),
                fill="#e0bb86" if n == radio.station else "#b39269",
            )
        self.text(d, (569, 386), "<", "#efca94", 10)
        self.text(d, (672, 386), ">", "#efca94", 10)
        self.text(d, (623, 385), "CAF FM", "#533a2e", 8, "mm")
        if world.hover in (
            "radio",
            "power",
            "volume",
            "previous",
            "next",
        ) or world.hover.startswith("preset"):
            self.text(
                d,
                (625, 314),
                f"{STATIONS[radio.station][0]} / {radio.volume}%",
                "#f7d9aa",
                10,
                "mm",
            )

    def details(self, im, t, world):
        d = ImageDraw.Draw(im)
        # A little open notebook and pencil, set back from the main objects.
        d.polygon([(481, 367), (520, 368), (528, 388), (487, 386)], fill="#4b3031")
        d.polygon([(481, 365), (519, 366), (526, 385), (487, 383)], fill="#d3b687")
        d.line((501, 367, 506, 382), fill="#937955")
        for y in range(370, 381, 3):
            d.line((486, y, 498, y + 1), fill="#aa916d")
            d.line((506, y + 1, 518, y + 2), fill="#aa916d")
        d.line((526, 368, 536, 386), fill="#b8704b", width=3)
        d.line((526, 368, 534, 382), fill="#dfb27b")
        # Small counter placard, also the honest keep-awake status.
        d.rectangle((36, 360, 132, 391), fill="#392d35")
        d.rectangle((39, 363, 129, 388), outline="#bb865c")
        self.text(d, (84, 369), "STAY AWHILE", "#e1bb87", 10, "mm")
        self.text(
            d,
            (84, 382),
            "MAC AWAKE" if world.awake else "PREVIEW",
            "#a6c79c" if world.awake else "#bb9e8d",
            8,
            "mm",
        )

    def footer(self, im, world, radio, t):
        d = ImageDraw.Draw(im)
        d.rectangle((0, 420, W, 480), fill="#191723")
        d.line((0, 420, W, 420), fill="#6b4f49")
        self.text(d, (20, 429), "CAF", "#efc69a", 20)
        self.text(d, (80, 428), world.period(t), "#d8b196", 10)
        self.text(d, (80, 444), world.weather(t)[3], "#8f889d", 8)
        self.text(
            d, (748, 426), world.clock(t).strftime("%H:%M:%S"), "#edcbae", 16, "ra"
        )
        self.text(d, (748, 445), "AWAKE FOR " + duration(t), "#9b91a6", 8, "ra")
        station = STATIONS[radio.station][0]
        title = radio.title.upper()
        # Clip long track names to a dedicated marquee region.
        strip = Image.new("RGBA", (306, 27))
        sd = ImageDraw.Draw(strip)
        self.text(
            sd,
            (0, 0),
            f"{'● ' if radio.playing else ''}{station}  /  {radio.status}",
            "#b7c09a" if radio.playing else "#b29a94",
            10,
        )
        length = sd.textlength(title, font=self.fonts[8])
        scroll = max(0, int((t * 12) % (length + 55) - 25)) if length > 306 else 0
        self.text(sd, (-scroll, 16), title, "#8f889d", 8)
        im.alpha_composite(strip, (302, 428))
        d = ImageDraw.Draw(im)
        if world.toast_until > t:
            self.text(d, (384, 466), world.toast, "#b9a4a6", 8, "mm")
        elif world.hover:
            hints = {
                "cat": "CLICK TO SAY HELLO TO MISO",
                "coffee": "CLICK FOR A FRESH CUP",
                "lamp": "CLICK TO CHANGE THE LIGHT",
                "window": "CLICK TO CHANGE THE WEATHER",
                "volume": "SCROLL TO ADJUST VOLUME",
                "power": "CLICK TO TURN THE RADIO ON / OFF",
                "previous": "PREVIOUS STATION",
                "next": "NEXT STATION",
                "radio": "SPACE: POWER  /  ARROWS: STATIONS  /  SCROLL: VOLUME",
            }
            self.text(
                d,
                (384, 466),
                hints.get(world.hover, "CLICK TO TUNE THIS PRESET"),
                "#b9a4a6",
                8,
                "mm",
            )
        else:
            self.text(
                d,
                (384, 466),
                "SPACE RADIO   < > STATION   +/- VOLUME   W WEATHER   L LAMP   ? HELP   Q LEAVE",
                "#8b8194",
                8,
                "mm",
            )

    def help(self, im):
        shade = Image.new("RGBA", (W, H), (15, 13, 26, 175))
        im.alpha_composite(shade)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle(
            (166, 102, 602, 374), 8, fill="#24202e", outline="#9e765e", width=2
        )
        self.text(d, (384, 128), "MAKE YOURSELF AT HOME", "#e9c6a2", 16, "mm")
        lines = [
            ("SPACE / RADIO POWER", "MUSIC ON / OFF"),
            ("LEFT / RIGHT / 1-4", "CHOOSE A STATION"),
            ("+ / - / SCROLL RADIO", "CHANGE VOLUME"),
            ("W / CLICK WINDOW", "AUTO, CLEAR, CLOUDY, RAIN"),
            ("L / CLICK LAMP", "LOW, WARM, EXTRA COZY"),
            ("C / CLICK MISO", "SAY HELLO TO THE CAT"),
            ("B / CLICK COFFEE", "A FRESH CUP"),
            ("Q / CTRL+C", "CLOSE UP AND RELEASE AWAKE"),
        ]
        for i, (key, value) in enumerate(lines):
            self.text(d, (188, 157 + i * 22), key, "#d7b393", 8)
            self.text(d, (391, 157 + i * 22), value, "#a79bab", 8)
        self.text(d, (384, 351), "? OR CLICK ANYWHERE TO RETURN", "#bc9d95", 10, "mm")
