"""
system_theme.py — generates the Windows theme assets from scratch (nothing is copied from Apple):
Mac-style mouse pointers, system sounds, file-type icons and desktop folder icons.
"""
import math
import os
import struct
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

THEME_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "MacUI"
FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


# ───────────────────────────── مؤشر الماوس ─────────────────────────────

def _dib(im):
    w, h = im.size
    bih = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = im.transpose(Image.FLIP_TOP_BOTTOM).tobytes("raw", "BGRA")
    return bih + pixels + bytes(((w + 31) // 32) * 4 * h)


def cur_bytes(images, hotspot):
    """ملف .cur بعدة أحجام (ويندوز يختار حسب حجم المؤشر في الإعدادات)."""
    head = struct.pack("<HHH", 0, 2, len(images))
    offset = 6 + 16 * len(images)
    entries, data = b"", b""
    for im in images:
        w, h = im.size
        bmp = _dib(im)
        hx, hy = round(hotspot[0] * w), round(hotspot[1] * h)
        entries += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, hx, hy, len(bmp), offset)
        data += bmp
        offset += len(bmp)
    return head + entries + data


def ani_bytes(frames, rate=5):
    """مؤشر متحرك .ani (مثل كرة الانتظار الملونة)."""
    def chunk(tag, body):
        return tag + struct.pack("<I", len(body)) + body + (b"\0" if len(body) % 2 else b"")
    anih = struct.pack("<9I", 36, len(frames), len(frames), 0, 0, 0, 0, rate, 1)
    fram = b"fram" + b"".join(chunk(b"icon", f) for f in frames)
    body = b"ACON" + chunk(b"anih", anih) + chunk(b"LIST", fram)
    return b"RIFF" + struct.pack("<I", len(body)) + body


SS = 8  # رسم بدقة عالية ثم تصغير = حواف ناعمة


def _canvas(size):
    return Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))


def _finish(big, size, shadow=True):
    if shadow:
        a = big.getchannel("A").filter(ImageFilter.GaussianBlur(SS * size / 32 * 1.2))
        sh = Image.new("RGBA", big.size, (0, 0, 0, 0))
        sh.putalpha(a.point(lambda v: int(v * 0.35)))
        out = Image.new("RGBA", big.size, (0, 0, 0, 0))
        out.alpha_composite(sh, (0, int(SS * size / 32 * 1.2)))
        out.alpha_composite(big)
        big = out
    return big.resize((size, size), Image.LANCZOS)


def _outlined(poly, size, fill=(0, 0, 0, 255), outline=(255, 255, 255, 255), width=1.6):
    """شكل أسود بحد أبيض (ستايل مؤشرات الماك)."""
    big = _canvas(size)
    d = ImageDraw.Draw(big)
    s = SS * size / 32
    pts = [(x * s, y * s) for x, y in poly]
    w = max(1, int(width * s * 2))
    d.polygon(pts, fill=outline)
    d.line(pts + [pts[0]], fill=outline, width=w, joint="curve")
    d.polygon(pts, fill=fill)
    return big


ARROW = [(2, 2), (2, 23), (7.2, 18.2), (11, 26.5), (14.2, 25.2), (10.6, 17), (17.5, 17)]


def arrow(size):
    return _finish(_outlined(ARROW, size), size)


def double_arrow(size, angle, four=False):
    """أسهم تغيير الحجم مثل الماك: سهم برأسين أسود بحد أبيض."""
    big = _canvas(size)
    d = ImageDraw.Draw(big)
    s = SS * size / 32
    c = 16 * s
    L, hl, hw, sw = 12, 6, 5.2, 1.5
    local = [(-L, 0), (-L + hl, -hw), (-L + hl, -sw), (L - hl, -sw), (L - hl, -hw), (L, 0),
             (L - hl, hw), (L - hl, sw), (-L + hl, sw), (-L + hl, hw)]

    def poly(a):
        ca, sa = math.cos(a), math.sin(a)
        return [(c + (x * ca - y * sa) * s, c + (x * sa + y * ca) * s) for x, y in local]

    angles = [angle, angle + math.pi / 2] if four else [angle]
    for a in angles:
        pts = poly(a)
        d.polygon(pts, fill=(255, 255, 255, 255))
        d.line(pts + [pts[0]], fill=(255, 255, 255, 255), width=int(3.4 * s), joint="curve")
    for a in angles:
        d.polygon(poly(a), fill=(0, 0, 0, 255))
    return _finish(big, size)


def ibeam(size):
    big = _canvas(size)
    d = ImageDraw.Draw(big)
    s = SS * size / 32
    x = 16 * s
    for col, w in (((255, 255, 255, 255), 4.2), ((0, 0, 0, 255), 1.6)):
        d.line([(x, 6 * s), (x, 26 * s)], fill=col, width=int(w * s))
        for y in (6 * s, 26 * s):
            d.line([(x - 4 * s, y), (x + 4 * s, y)], fill=col, width=int(w * s))
    return _finish(big, size, shadow=False)


def beachball(size, phase=0.0):
    """كرة الانتظار الملونة (مرسومة بألوان طيف بسيطة)."""
    big = _canvas(size)
    s = SS * size / 32
    c, r = 16 * s, 11 * s
    d = ImageDraw.Draw(big)
    d.ellipse((c - r - 1.2 * s, c - r - 1.2 * s, c + r + 1.2 * s, c + r + 1.2 * s), fill=(255, 255, 255, 255))
    cols = [(255, 59, 48), (255, 149, 0), (255, 204, 0), (52, 199, 89), (0, 122, 255), (175, 82, 222)]
    n = len(cols)
    for i, col in enumerate(cols):
        a0 = phase * 360 + i * 360 / n
        d.pieslice((c - r, c - r, c + r, c + r), a0, a0 + 360 / n + 1, fill=col + (255,))
    glow = Image.new("RGBA", big.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((c - r * 0.7, c - r * 0.95, c + r * 0.4, c - r * 0.05), fill=(255, 255, 255, 90))
    big.alpha_composite(glow.filter(ImageFilter.GaussianBlur(2 * s)))
    return _finish(big, size)


def badge_arrow(size, badge):
    """سهم الماك مع شارة صغيرة (انتظار، ممنوع، مساعدة)."""
    base = _outlined(ARROW, size)
    s = SS * size / 32
    if badge == "busy":
        ball = beachball(size).resize((int(14 * s), int(14 * s)), Image.LANCZOS)
        base.alpha_composite(ball, (int(15 * s), int(15 * s)))
    else:
        d = ImageDraw.Draw(base)
        cx, cy, r = 22 * s, 22 * s, 6.5 * s
        d.ellipse((cx - r - s, cy - r - s, cx + r + s, cy + r + s), fill=(255, 255, 255, 255))
        if badge == "no":
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(0, 0, 0, 255))
            d.ellipse((cx - r * 0.62, cy - r * 0.62, cx + r * 0.62, cy + r * 0.62), fill=(255, 255, 255, 255))
            d.line([(cx - r * 0.6, cy + r * 0.6), (cx + r * 0.6, cy - r * 0.6)], fill=(0, 0, 0, 255), width=int(2.2 * s))
        else:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(0, 0, 0, 255))
            from PIL import ImageFont
            f = ImageFont.truetype(str(FONTS / "segoeuib.ttf"), int(11 * s))
            d.text((cx, cy + 0.5 * s), "?", font=f, fill=(255, 255, 255, 255), anchor="mm")
    return _finish(base, size)


def hand(size):
    """يد التأشير (للروابط)."""
    big = _canvas(size)
    d = ImageDraw.Draw(big)
    s = SS * size / 32

    def shape(fill, grow):
        g = grow * s
        r = lambda x0, y0, x1, y1, rad: d.rounded_rectangle((x0 * s - g, y0 * s - g, x1 * s + g, y1 * s + g),
                                                             rad * s + g, fill=fill)
        r(11, 2, 15, 18, 2)       # السبابة
        r(15, 10, 19, 19, 2)      # الأصابع
        r(19, 11, 23, 19.5, 2)
        r(23, 12.5, 26.5, 20, 1.8)
        r(10, 15, 26.5, 28, 4.5)  # الكف
        d.polygon([(11 * s - g, 18 * s), (5 * s - g, 14 * s - g), (3.5 * s - g, 16 * s), (10 * s - g, 25 * s + g)], fill=fill)

    shape((0, 0, 0, 255), 1.4)
    shape((255, 255, 255, 255), 0)
    for x in (15, 19, 23):
        d.line([(x * s, 13 * s), (x * s, 18 * s)], fill=(0, 0, 0, 255), width=int(0.9 * s))
    return _finish(big, size)


def crosshair(size):
    big = _canvas(size)
    d = ImageDraw.Draw(big)
    s = SS * size / 32
    for col, w in (((255, 255, 255, 255), 3.4), ((0, 0, 0, 255), 1.4)):
        d.line([(16 * s, 3 * s), (16 * s, 29 * s)], fill=col, width=int(w * s))
        d.line([(3 * s, 16 * s), (29 * s, 16 * s)], fill=col, width=int(w * s))
    return _finish(big, size, shadow=False)


def make_cursors(folder):
    """يرجع {اسم ويندوز: مسار الملف}."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    sizes = (32, 48, 64)
    plan = {
        "Arrow": (lambda n: arrow(n), (2 / 32, 2 / 32)),
        "Help": (lambda n: badge_arrow(n, "help"), (2 / 32, 2 / 32)),
        "No": (lambda n: badge_arrow(n, "no"), (2 / 32, 2 / 32)),
        "Hand": (lambda n: hand(n), (13 / 32, 2 / 32)),
        "IBeam": (lambda n: ibeam(n), (0.5, 0.5)),
        "Crosshair": (lambda n: crosshair(n), (0.5, 0.5)),
        "SizeWE": (lambda n: double_arrow(n, 0), (0.5, 0.5)),
        "SizeNS": (lambda n: double_arrow(n, math.pi / 2), (0.5, 0.5)),
        "SizeNWSE": (lambda n: double_arrow(n, math.pi / 4), (0.5, 0.5)),
        "SizeNESW": (lambda n: double_arrow(n, -math.pi / 4), (0.5, 0.5)),
        "SizeAll": (lambda n: double_arrow(n, 0, four=True), (0.5, 0.5)),
    }
    out = {}
    for name, (fn, hot) in plan.items():
        path = folder / f"mac_{name.lower()}.cur"
        path.write_bytes(cur_bytes([fn(n) for n in sizes], hot))
        out[name] = str(path)
    for name, fn in (("Wait", lambda n, p: beachball(n, p)), ("AppStarting", None)):
        frames = []
        for i in range(8):
            p = i / 8
            imgs = [beachball(n, p) if name == "Wait" else _busy_arrow(n, p) for n in sizes]
            frames.append(cur_bytes(imgs, (0.5, 0.5) if name == "Wait" else (2 / 32, 2 / 32)))
        path = folder / f"mac_{name.lower()}.ani"
        path.write_bytes(ani_bytes(frames, rate=4))
        out[name] = str(path)
    return out


def _busy_arrow(size, phase):
    base = _outlined(ARROW, size)
    s = SS * size / 32
    ball = beachball(size, phase).resize((int(14 * s), int(14 * s)), Image.LANCZOS)
    base.alpha_composite(ball, (int(15 * s), int(15 * s)))
    return _finish(base, size)


# ───────────────────────────── الأصوات ─────────────────────────────

RATE = 44100


def _write_wav(path, samples):
    import array
    data = array.array("h", (max(-32767, min(32767, int(v * 32767))) for v in samples))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data.tobytes())


def _tone(partials, dur, decay, attack=0.004, vol=0.5, pitch_drop=0.0):
    n = int(RATE * dur)
    out = []
    for i in range(n):
        t = i / RATE
        env = min(1.0, t / attack) * math.exp(-t * decay)
        f_mult = 1 - pitch_drop * min(1.0, t / dur)
        v = sum(a * math.sin(2 * math.pi * f * f_mult * t) for f, a in partials)
        out.append(v * env * vol)
    return out


def _noise_crumple(dur):
    import random
    rnd = random.Random(4)
    n = int(RATE * dur)
    out, prev = [], 0.0
    for i in range(n):
        t = i / RATE
        burst = 1.0 if (int(t * 38) % 3 == 0) else 0.25
        prev = prev * 0.55 + rnd.uniform(-1, 1) * 0.45
        out.append(prev * burst * math.exp(-t * 4) * 0.5)
    return out


SOUNDS = {  # أصوات قصيرة ناعمة بروح أصوات الماك (مركبة رياضياً)
    "tink": lambda: _tone([(2637, 0.7), (5274, 0.2), (7040, 0.1)], 0.35, 22),
    "glass": lambda: _tone([(1568, 0.6), (3136, 0.25), (4704, 0.1), (2093, 0.3)], 1.1, 5),
    "pop": lambda: _tone([(880, 0.8), (1760, 0.2)], 0.12, 40, pitch_drop=0.35),
    "funk": lambda: _tone([(196, 0.7), (392, 0.3), (588, 0.15)], 0.45, 9, pitch_drop=0.12),
    "purr_up": lambda: _tone([(659, 0.6), (1318, 0.2)], 0.14, 18) + _tone([(988, 0.6), (1976, 0.2)], 0.3, 12),
    "purr_down": lambda: _tone([(988, 0.6), (1976, 0.2)], 0.14, 18) + _tone([(659, 0.6), (1318, 0.2)], 0.3, 12),
    "trash": lambda: _noise_crumple(0.7),
}

# حدث ويندوز ← صوت (الماك هادي، فنحط أصوات خفيفة)
SOUND_EVENTS = {
    r".Default\.Default": "tink", r".Default\SystemAsterisk": "pop", r".Default\SystemExclamation": "funk",
    r".Default\SystemHand": "funk", r".Default\SystemNotification": "glass", r".Default\Notification.Default": "glass",
    r".Default\Notification.IM": "glass", r".Default\Notification.Mail": "glass", r".Default\MailBeep": "glass",
    r".Default\DeviceConnect": "purr_up", r".Default\DeviceDisconnect": "purr_down", r".Default\DeviceFail": "funk",
    r".Default\WindowsUAC": "pop", r"Explorer\EmptyRecycleBin": "trash",
}


def make_sounds(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, fn in SOUNDS.items():
        path = folder / f"mac_{name}.wav"
        if not path.exists():
            _write_wav(path, fn())
        out[name] = str(path)
    return out


# ───────────────────────────── أيقونات أنواع الملفات ─────────────────────────────

FILE_TYPES = {  # امتداد ← (نص الشارة، لون، رمز)
    ".txt": ("TXT", (142, 142, 147), "lines"), ".log": ("LOG", (142, 142, 147), "lines"),
    ".md": ("MD", (88, 86, 214), "lines"), ".pdf": ("PDF", (255, 59, 48), "lines"),
    ".zip": ("ZIP", (142, 142, 147), "zip"), ".rar": ("RAR", (142, 142, 147), "zip"), ".7z": ("7Z", (142, 142, 147), "zip"),
    ".mp3": ("MP3", (255, 45, 85), "music"), ".wav": ("WAV", (255, 45, 85), "music"), ".m4a": ("M4A", (255, 45, 85), "music"),
    ".flac": ("FLAC", (255, 45, 85), "music"),
    ".mp4": ("MP4", (88, 86, 214), "film"), ".mkv": ("MKV", (88, 86, 214), "film"), ".mov": ("MOV", (88, 86, 214), "film"),
    ".avi": ("AVI", (88, 86, 214), "film"),
    ".png": ("PNG", (52, 199, 89), "photo"), ".jpg": ("JPG", (52, 199, 89), "photo"), ".jpeg": ("JPEG", (52, 199, 89), "photo"),
    ".gif": ("GIF", (52, 199, 89), "photo"), ".webp": ("WEBP", (52, 199, 89), "photo"), ".bmp": ("BMP", (52, 199, 89), "photo"),
    ".docx": ("DOCX", (0, 122, 255), "lines"), ".doc": ("DOC", (0, 122, 255), "lines"),
    ".xlsx": ("XLSX", (52, 199, 89), "grid"), ".csv": ("CSV", (52, 199, 89), "grid"),
    ".pptx": ("PPTX", (255, 149, 0), "slides"),
    ".py": ("PY", (48, 115, 194), "code"), ".js": ("JS", (230, 180, 0), "code"), ".json": ("JSON", (142, 142, 147), "code"),
    ".html": ("HTML", (255, 149, 0), "code"), ".css": ("CSS", (0, 122, 255), "code"), ".ts": ("TS", (48, 115, 194), "code"),
    ".c": ("C", (88, 86, 214), "code"), ".cpp": ("C++", (88, 86, 214), "code"), ".java": ("JAVA", (255, 59, 48), "code"),
}


def document_icon(label, color, glyph, size=256):
    """أيقونة مستند بستايل الماك: ورقة بيضاء زاويتها مطوية وشارة ملونة باسم النوع."""
    S = size * 2
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = S * 0.18, S * 0.06, S * 0.82, S * 0.94
    fold = S * 0.17
    page = [(x0, y0 + 8), (x1 - fold, y0), (x1, y0 + fold), (x1, y1), (x0, y1)]
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).polygon([(x, y + S * 0.012) for x, y in page], fill=(0, 0, 0, 110))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(S * 0.012)))
    d.rounded_rectangle((x0, y0, x1, y1), S * 0.03, fill=(250, 250, 252, 255))
    d.polygon([(x1 - fold, y0 - 1), (x1 + 1, y0 - 1), (x1 + 1, y0 + fold)], fill=(0, 0, 0, 0))
    d.polygon([(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)], fill=(214, 214, 220, 255))
    d.line([(x1 - fold, y0), (x1, y0 + fold)], fill=(196, 196, 204, 255), width=max(1, int(S * 0.004)))
    gx0, gy0, gx1, gy1 = x0 + S * 0.09, y0 + S * 0.2, x1 - S * 0.09, y1 - S * 0.3
    c = color + (255,)
    if glyph == "lines":
        y = gy0
        while y < gy1:
            d.rounded_rectangle((gx0, y, gx1 - (S * 0.08 if int(y) % 3 else 0), y + S * 0.018), S * 0.009,
                                fill=(205, 205, 212, 255))
            y += S * 0.05
    elif glyph == "grid":
        for i in range(5):
            for j in range(4):
                cx0 = gx0 + j * (gx1 - gx0) / 4
                cy0 = gy0 + i * (gy1 - gy0) / 5
                d.rectangle((cx0 + 2, cy0 + 2, cx0 + (gx1 - gx0) / 4 - 2, cy0 + (gy1 - gy0) / 5 - 2),
                            fill=(214, 236, 218, 255) if i else c)
    elif glyph == "slides":
        d.rounded_rectangle((gx0, gy0 + S * 0.04, gx1, gy1 - S * 0.04), S * 0.02, fill=c)
        d.rounded_rectangle((gx0 + S * 0.05, gy0 + S * 0.09, gx1 - S * 0.2, gy0 + S * 0.13), S * 0.01, fill=(255, 255, 255, 230))
    elif glyph == "photo":
        d.rounded_rectangle((gx0, gy0, gx1, gy1), S * 0.02, fill=(120, 190, 250, 255))
        d.polygon([(gx0, gy1), (gx0 + (gx1 - gx0) * 0.4, gy0 + (gy1 - gy0) * 0.45), (gx1 - (gx1 - gx0) * 0.25, gy1)],
                  fill=(52, 160, 80, 255))
        d.polygon([(gx0 + (gx1 - gx0) * 0.45, gy1), (gx1 - (gx1 - gx0) * 0.2, gy0 + (gy1 - gy0) * 0.55), (gx1, gy1)],
                  fill=(40, 130, 70, 255))
        r = S * 0.035
        d.ellipse((gx1 - S * 0.1 - r, gy0 + S * 0.06 - r, gx1 - S * 0.1 + r, gy0 + S * 0.06 + r), fill=(255, 214, 10, 255))
    else:
        from PIL import ImageFont
        sym = {"music": "\uE8D6", "film": "\uE8B2", "zip": "\uF012", "code": "\uE943"}.get(glyph, "\uE8A5")
        f = ImageFont.truetype(str(FONTS / "SegoeIcons.ttf"), int(S * 0.26))
        d.text(((gx0 + gx1) / 2, (gy0 + gy1) / 2), sym, font=f, fill=c, anchor="mm")
    from PIL import ImageFont
    fb = ImageFont.truetype(str(FONTS / "segoeuib.ttf"), int(S * (0.1 if len(label) <= 4 else 0.08)))
    tw = fb.getlength(label) + S * 0.08
    bx0, by0 = (S - tw) / 2, y1 - S * 0.2
    d.rounded_rectangle((bx0, by0, bx0 + tw, by0 + S * 0.13), S * 0.03, fill=c)
    d.text((S / 2, by0 + S * 0.065), label, font=fb, fill=(255, 255, 255, 255), anchor="mm")
    return img.resize((size, size), Image.LANCZOS)


def make_file_icons(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    for ext, (label, color, glyph) in FILE_TYPES.items():
        path = folder / f"doc_{ext[1:]}.ico"
        if not path.exists():
            document_icon(label, color, glyph).save(path, format="ICO", sizes=sizes)
        out[ext] = str(path)
    return out


CATEGORY = {"photo": "IMAGE", "music": "AUDIO", "film": "VIDEO", "zip": "ZIP", "lines": "TEXT", "code": "CODE",
            "grid": "SHEET", "slides": "SLIDES"}


def category_icon(exts, folder):
    """أيقونة فئة لبرنامج يفتح كذا نوع؛ لو الأنواع مختلفة (صوت + فيديو) تصير «MEDIA»."""
    _, color, glyph = FILE_TYPES[exts[0]]
    label = CATEGORY.get(glyph, "FILE")
    if len({FILE_TYPES[e][2] for e in exts}) > 1:
        label, glyph, color = "MEDIA", "film", (88, 86, 214)
    path = Path(folder) / f"cat_{label.lower()}.ico"
    if not path.exists():
        document_icon(label, color, glyph).save(
            path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return str(path)
