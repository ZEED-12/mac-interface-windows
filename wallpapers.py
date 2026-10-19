"""
wallpapers.py — original 4K wallpapers in the spirit of macOS, generated procedurally.

Apple's official wallpapers belong to Apple and are not included. Any image you drop into
the wallpapers/ folder also appears in Mac Interface Settings > Wallpaper.
"""
import math
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
FOLDER = HERE / "wallpapers"


def _grid(w, h):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    return x / w, y / w  # نفس المقياس للمحورين


def _palette(t, stops):
    stops = np.asarray(stops, np.float32)
    pos = np.linspace(0, 1, len(stops))
    return np.stack([np.interp(t, pos, stops[:, c]) for c in range(3)], -1)


def _finish(rgb, seed=1):
    rgb = rgb + np.random.default_rng(seed).normal(0, 1.4, rgb.shape[:2] + (1,)).astype(np.float32)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")


def vgradient(h, w, top, bottom):
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    return np.asarray(top, np.float32) * (1 - t) + np.asarray(bottom, np.float32) * t + np.zeros((1, w, 1), np.float32)


# ── حرير متموج (مثل خلفية Golden Gate الذهبية) ──
def silk(w, h, stops, light=(-0.55, -0.6, 0.58), freq=0.85, shine=0.55, seed=1):
    X, Y = _grid(w, h)
    u = X * 2.6 + 0.55 * np.sin(Y * 3.2 + X * 1.7) + 0.25 * np.sin(X * 5.3 - Y * 2.1 + 1.3)
    hgt = np.sin(u * 2 * np.pi * freq + Y * 4.2) * (0.6 + 0.4 * np.sin(Y * 2.0 + X * 1.1))
    hgt += 0.35 * np.sin(u * 2 * np.pi * freq * 2.2 - Y * 3.0 + 0.7)
    gy, gx = np.gradient(hgt)
    s = w / 1920 * 55
    nx, ny = -gx * s * (1920 / w) * w / 1920, -gy * s * (1920 / w) * w / 1920
    n = np.sqrt(nx ** 2 + ny ** 2 + 1)
    lx, ly, lz = light
    diffuse = np.clip((nx * lx + ny * ly + lz) / n, 0, 1)
    hn = math.sqrt(lx * lx + ly * ly + (lz + 1) ** 2)
    spec = np.clip((nx * lx + ny * ly + (lz + 1)) / (n * hn), 0, 1) ** 40
    depth = 0.6 + 0.4 * (hgt - hgt.min()) / (np.ptp(hgt) + 1e-6)
    t = np.clip(diffuse * 0.88 * depth + 0.13, 0, 1)
    rgb = _palette(t, stops) + spec[..., None] * np.array([255, 240, 214], np.float32) * shine
    return _finish(rgb, seed)


# ── طيات ورق/صفائح (مثل Tahoe و Golden Gate) وتلال (مثل Sonoma) ──
def sheets(w, h, back_top, back_bottom, layers, shadow=0.45, rim=0.35, seed=2):
    """layers: (ارتفاع الحافة، سعة، تردد، طور، لون فوق، لون تحت، ميل)"""
    X, Y = _grid(w, h)
    rgb = vgradient(h, w, back_top, back_bottom)
    px = 1.0 / w
    for y0, amp, f, ph, top, bottom, tilt in layers:
        c = (y0 + amp * np.sin(2 * np.pi * f * X + ph) + amp * 0.35 * np.sin(2 * np.pi * f * 2.3 * X + ph * 1.7)
             + tilt * (X - 0.5)) * (h / w)
        dc = np.gradient(c[0])[None, :] / px
        s = (Y - c) / np.sqrt(1 + dc ** 2)  # مسافة تقريبية عن الحافة (موجب = داخل الصفيحة)
        sw = 0.05 * h / w
        # ظل ناعم على اللي وراها
        rgb *= (1 - shadow * np.exp(-np.clip(-s, 0, None) / sw * 3) * (s < 0))[..., None]
        t = np.clip(s / (0.35 * h / w), 0, 1)[..., None]
        sheet = np.asarray(top, np.float32) * (1 - t) + np.asarray(bottom, np.float32) * t
        sheet += rim * 255 * np.exp(-np.clip(s, 0, None) / (0.004 * h / w))[..., None] * (s > 0)[..., None] * 0.5
        a = np.clip(s / px + 0.5, 0, 1)[..., None]
        rgb = rgb * (1 - a) + sheet * a
    return _finish(rgb, seed)


# ── شفق ألوان ناعم ──
def aurora(w, h, base, blobs, seed=3):
    X, Y = _grid(w, h)
    rgb = vgradient(h, w, base[0], base[1])
    for cx, cy, rx, ry, color, strength in blobs:
        g = np.exp(-(((X - cx) / rx) ** 2 + ((Y - cy * h / w) / (ry * h / w)) ** 2))
        rgb = rgb + (np.asarray(color, np.float32) - rgb * 0.4) * (g * strength)[..., None]
    return _finish(rgb, seed)


CATALOG = [
    ("Golden Gate Silk", lambda w, h: silk(w, h, [[20, 11, 5], [66, 36, 10], [138, 84, 26], [208, 150, 60],
                                                   [245, 210, 140], [255, 242, 214]])),
    ("Golden Gate Day", lambda w, h: sheets(w, h, (238, 232, 222), (205, 198, 190), [
        (0.08, 0.10, 0.55, 0.4, (250, 246, 238), (214, 204, 190), 0.55),
        (0.28, 0.09, 0.6, 1.9, (246, 240, 230), (190, 182, 174), 0.5),
        (0.48, 0.08, 0.5, 3.1, (238, 234, 228), (150, 150, 170), 0.45),
        (0.66, 0.07, 0.65, 4.4, (226, 226, 232), (120, 124, 150), 0.4)], shadow=0.35, rim=0.25)),
    ("Golden Gate Night", lambda w, h: sheets(w, h, (40, 38, 46), (18, 18, 26), [
        (0.08, 0.10, 0.55, 0.4, (120, 104, 84), (52, 46, 44), 0.55),
        (0.28, 0.09, 0.6, 1.9, (104, 96, 92), (40, 38, 46), 0.5),
        (0.48, 0.08, 0.5, 3.1, (86, 86, 108), (30, 30, 46), 0.45),
        (0.66, 0.07, 0.65, 4.4, (70, 76, 108), (20, 22, 40), 0.4)], shadow=0.5, rim=0.18)),
    ("Tahoe Day", lambda w, h: sheets(w, h, (150, 205, 245), (70, 150, 220), [
        (0.20, 0.09, 0.45, 0.2, (190, 230, 250), (90, 170, 230), 0.4),
        (0.38, 0.08, 0.55, 1.4, (120, 200, 240), (30, 120, 200), 0.35),
        (0.55, 0.07, 0.5, 2.6, (60, 160, 225), (10, 80, 170), 0.3),
        (0.72, 0.06, 0.6, 3.8, (20, 110, 200), (5, 50, 130), 0.25)])),
    ("Tahoe Night", lambda w, h: sheets(w, h, (14, 26, 56), (6, 10, 28), [
        (0.20, 0.09, 0.45, 0.2, (40, 80, 150), (14, 30, 70), 0.4),
        (0.38, 0.08, 0.55, 1.4, (30, 70, 140), (10, 22, 60), 0.35),
        (0.55, 0.07, 0.5, 2.6, (20, 56, 120), (6, 16, 48), 0.3),
        (0.72, 0.06, 0.6, 3.8, (14, 40, 100), (4, 10, 34), 0.25)], shadow=0.55)),
    ("Sonoma Day", lambda w, h: sheets(w, h, (172, 214, 238), (232, 222, 200), [
        (0.30, 0.05, 0.9, 0.5, (150, 196, 140), (110, 160, 110), -0.1),
        (0.40, 0.06, 0.7, 2.0, (120, 180, 110), (70, 130, 80), 0.15),
        (0.50, 0.05, 1.1, 3.4, (90, 160, 90), (40, 100, 60), -0.12),
        (0.62, 0.05, 0.8, 1.1, (60, 130, 70), (20, 70, 40), 0.1)], shadow=0.3, rim=0.2)),
    ("Sonoma Night", lambda w, h: sheets(w, h, (16, 24, 52), (40, 34, 60), [
        (0.30, 0.05, 0.9, 0.5, (40, 60, 80), (24, 40, 56), -0.1),
        (0.40, 0.06, 0.7, 2.0, (30, 54, 70), (16, 30, 44), 0.15),
        (0.50, 0.05, 1.1, 3.4, (22, 44, 58), (10, 22, 34), -0.12),
        (0.62, 0.05, 0.8, 1.1, (14, 32, 44), (6, 14, 24), 0.1)], shadow=0.5, rim=0.12)),
    ("Big Sur Dusk", lambda w, h: sheets(w, h, (60, 40, 120), (250, 140, 120), [
        (0.32, 0.07, 0.5, 0.8, (180, 90, 150), (90, 40, 110), 0.3),
        (0.44, 0.06, 0.7, 2.2, (120, 60, 140), (60, 26, 90), -0.2),
        (0.56, 0.06, 0.6, 3.7, (70, 40, 110), (30, 16, 60), 0.25),
        (0.70, 0.05, 0.9, 5.0, (40, 26, 80), (14, 8, 36), -0.15)], shadow=0.4, rim=0.3)),
    ("Sequoia", lambda w, h: sheets(w, h, (10, 30, 34), (4, 14, 18), [
        (0.18, 0.10, 0.5, 0.6, (40, 150, 130), (10, 60, 60), 0.6),
        (0.36, 0.09, 0.55, 2.0, (30, 120, 120), (6, 44, 50), 0.5),
        (0.54, 0.08, 0.5, 3.3, (20, 90, 110), (4, 30, 44), 0.45),
        (0.70, 0.07, 0.6, 4.6, (16, 70, 100), (2, 20, 36), 0.4)], shadow=0.55, rim=0.3)),
    ("Monterey", lambda w, h: sheets(w, h, (40, 30, 110), (130, 60, 170), [
        (0.25, 0.10, 0.45, 0.3, (120, 80, 230), (60, 40, 160), -0.4),
        (0.42, 0.09, 0.5, 1.7, (170, 90, 220), (90, 40, 170), -0.35),
        (0.58, 0.08, 0.55, 3.0, (220, 110, 200), (130, 50, 160), -0.3),
        (0.74, 0.07, 0.6, 4.2, (90, 120, 240), (40, 50, 170), -0.25)], shadow=0.4, rim=0.35)),
    ("Ventura", lambda w, h: silk(w, h, [[18, 6, 2], [90, 30, 4], [200, 80, 10], [250, 150, 40], [255, 210, 120],
                                         [255, 240, 200]], freq=0.6, shine=0.4, seed=5)),
    ("Graphite", lambda w, h: silk(w, h, [[10, 10, 12], [30, 30, 34], [60, 60, 66], [110, 110, 118], [170, 170, 178],
                                          [220, 220, 226]], shine=0.35, seed=6)),
    ("Rose Silk", lambda w, h: silk(w, h, [[30, 10, 16], [90, 34, 50], [170, 80, 100], [230, 150, 160],
                                           [250, 210, 210], [255, 240, 240]], freq=0.75, seed=7)),
    ("Aurora", lambda w, h: aurora(w, h, ((6, 8, 24), (10, 6, 30)), [
        (0.25, 0.35, 0.35, 0.35, (60, 220, 170), 0.85), (0.6, 0.25, 0.4, 0.3, (60, 120, 255), 0.8),
        (0.85, 0.6, 0.35, 0.4, (200, 70, 230), 0.75), (0.4, 0.8, 0.45, 0.3, (255, 90, 140), 0.55)])),
    ("Hello", lambda w, h: aurora(w, h, ((250, 180, 80), (230, 70, 140)), [
        (0.2, 0.3, 0.45, 0.45, (255, 220, 120), 0.7), (0.8, 0.3, 0.4, 0.5, (120, 120, 255), 0.6),
        (0.5, 0.9, 0.5, 0.35, (255, 80, 160), 0.6)], seed=9)),
]


def generate(w=3840, h=2160, progress=print):
    """يولّد كل الخلفيات (مرة وحدة) ويرجع قائمة مساراتها."""
    FOLDER.mkdir(exist_ok=True)
    out = []
    for name, fn in CATALOG:
        path = FOLDER / f"{name}.jpg"
        if not path.exists():
            fn(w, h).save(path, quality=94, subsampling=0)
            progress(f"  ✓ خلفية {name}")
        out.append(path)
    return out


def available():
    """كل الخلفيات: المولدة + أي صور حطها المستخدم في المجلد أو mac_wallpaper.jpg."""
    files = []
    for folder in (FOLDER,):
        if folder.is_dir():
            files += sorted(p for p in folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".bmp"))
    for name in ("mac_wallpaper.jpg", "mac_wallpaper.png"):
        if (HERE / name).exists():
            files.insert(0, HERE / name)
    return files


def thumbnail(path, size=(208, 117)):
    thumbs = FOLDER / ".thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    t = thumbs / (Path(path).stem + f"_{size[0]}.png")
    if not t.exists() or t.stat().st_mtime < Path(path).stat().st_mtime:
        from PIL import ImageOps
        im = Image.open(path)
        im.draft("RGB", (size[0] * 2, size[1] * 2))
        ImageOps.fit(im.convert("RGB"), size, Image.LANCZOS).save(t)
    return Image.open(t).convert("RGBA")


def dynamic_pair(path):
    """خلفية لها نسخة نهار وليل: يرجع (نهار، ليل) أو None."""
    stem = Path(path).stem
    for a, b in ((" Day", " Night"), (" Night", " Day")):
        if stem.endswith(a):
            other = Path(path).with_name(stem[: -len(a)] + b + Path(path).suffix)
            if other.exists():
                return (Path(path), other) if a == " Day" else (other, Path(path))
    return None
