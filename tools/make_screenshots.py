"""
Regenerates docs/screenshots (English UI, fake data, nothing appears on screen).

Run after `python mac.py apply` (it needs the generated wallpapers):  python tools/make_screenshots.py
"""
import ctypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
sys.stdout.reconfigure(encoding="utf-8")
ctypes.windll.shcore.SetProcessDpiAwareness(2)
import settings
settings.S["language"] = "en"
import macui
import tkinter as tk
from PIL import Image

shots = {}


def fake_show(self, img=None):
    img = img or self.last
    if img is not None:
        self.last = img
        shots[id(self)] = img


macui.Surface.show = fake_show


class NoBackdrop:
    def __init__(self, *a, **k): self.hwnd = None
    def place(self, *a): pass
    def own(self, *a): pass
    def show(self, *a): pass
    def set_tint(self, *a): pass
    def set_top(self, *a): pass
    def destroy(self): pass


macui.Backdrop = NoBackdrop
import controlcenter as cc
import macapps
import overlays
import widgets
for mod in (cc, macapps, overlays, widgets):
    mod.Backdrop = NoBackdrop

root = tk.Tk()
root.withdraw()
WALL = Image.open(ROOT / "wallpapers" / "Golden Gate Day.jpg").convert("RGB")


class FakeAudio:
    def reset(self): pass
    def get(self): return 0.6, False
    def set(self, v): pass
    def toggle_mute(self): pass


class FakeUI:
    def __init__(self):
        self.root = root
        self.mons = macui.monitors()[:1]
        m = self.mons[0]
        m.screen = WALL.resize((m.w // 2, m.h // 2))
        self.icons = macui.Icons()
        self.apps = []
        self.popup = self.widgets = None
        self.groups, self.docks, self.apps_open = [], [], {}
        self.audio = FakeAudio()
        self.wifi_cache = {"present": True, "connected": True, "ssid": "Home Wi-Fi"}
        self.bright_cache = 0.7
        self.tray_now, self.app, self.lang, self.menu_titles, self.target = [], "Finder", "EN", None, None
        self.tracker = macui.Tracker()

    def __getattr__(self, name):
        return lambda *a, **k: None


ui = FakeUI()
mon = ui.mons[0]


def on_wall(img, name, pad=40):
    bbox = img.getchannel("A").getbbox()
    img = img.crop(bbox)
    bg = WALL.resize((img.width + 2 * pad, img.height + 2 * pad)).convert("RGBA")
    bg.alpha_composite(img, (pad, pad))
    bg.convert("RGB").save(OUT / name, optimize=True)
    print("saved", name)


# الشريط العلوي
mb = macui.MenuBar(ui, mon)
mb.render(force=True)
bar = shots[id(mb.surface)]
mb.bar.remove()
canvas = WALL.resize((mon.w, int(mon.w * WALL.height / WALL.width))).crop((0, 0, mon.w, bar.height)).convert("RGBA")
canvas.alpha_composite(bar)
canvas.convert("RGB").save(OUT / "menubar.png", optimize=True)

# التطبيقات
calc = macapps.Calculator(ui)
for x in "12×3+4":
    calc.input(x)
calc.render()
on_wall(shots[id(calc.surface)], "calculator.png")
st = macapps.Settings(ui)
on_wall(shots[id(st.surface)], "settings.png")
st.section = "corners"
st.render()
on_wall(shots[id(st.surface)], "hot_corners.png")
c = cc.ControlCenter(ui, mon, mon.x + mon.w - 20, mon.y + 32)
c.loaded, c.wifi_new, c.bright_new = True, ui.wifi_cache, 0.7
c.wait_load()
on_wall(shots[id(c.surface)], "control_center.png")
ql = overlays.QuickLook(ui, ROOT / "arabic.py")
on_wall(shots[id(ql.surface)], "quick_look.png")
hud = overlays.VolumeHUD(ui)
hud.show(0.6, False)
on_wall(shots[id(hud.glass.surface)], "volume_hud.png")

# الأدوات (بيانات طقس وهمية، بدون أداة الصور الشخصية)
host = widgets.Widgets.__new__(widgets.Widgets)
host.ui, host.mon, host.top, host.bottom = ui, mon, 28, 80
host.u, host.gap = round(164 * mon.k), round(16 * mon.k)
host.editing, host.items, host.weather_error = False, [], None
host.weather = {"name": "Cupertino", "temp": 22, "code": 1, "day": True, "hi": 25, "lo": 14,
                "hours": [{"h": (13 + i) % 24, "t": 22 - i % 3, "c": [1, 2, 0, 3, 2, 1][i], "d": True} for i in range(6)],
                "days": [{"date": f"2026-10-{19 + i}", "hi": 25 - i % 2, "lo": 14 + i % 3, "c": [1, 0, 2, 61, 3][i]}
                         for i in range(5)]}
widgets.NOTES_FILE = OUT / ".notes_demo.txt"
widgets.NOTES_FILE.write_text("Groceries\nCall mom at 6\nFinish the Dock drag & drop PR", encoding="utf-8")
tiles = []
for kind, size in (("clock", "small"), ("clock", "medium"), ("calendar", "medium"), ("weather", "medium"),
                   ("battery", "small"), ("system", "small"), ("notes", "small"), ("countdown", "small")):
    w = widgets.TYPES[kind](host, {"type": kind, "size": size, "dx": 200, "dy": 200,
                                   "config": {"file": str(widgets.NOTES_FILE)} if kind == "notes" else {}}, preview=True)
    card = w.compose()
    card.putalpha(macui.ImageChops.multiply(card.getchannel("A"), macui.aa_round(w.w, w.h, w.r, (255,) * 4).getchannel("A")))
    tiles.append(card)
widgets.NOTES_FILE.unlink()
gap = 24
rows = [tiles[:4], tiles[4:]]
W = max(sum(t.width for t in r) + gap * (len(r) + 1) for r in rows)
H = sum(max(t.height for t in r) for r in rows) + gap * 3
sheet = WALL.resize((W, int(W * WALL.height / WALL.width))).crop((0, 0, W, H)).convert("RGBA")
y = gap
for r in rows:
    x = gap
    for t in r:
        sheet.alpha_composite(t, (x, y))
        x += t.width + gap
    y += max(t.height for t in r) + gap
sheet.convert("RGB").save(OUT / "widgets.png", optimize=True)

# الأيقونات والخلفيات والمؤشرات
specs = [a for a in macui.DEFAULT_APPS if a != "sep" and a["icon"] != "browser"]
row = Image.new("RGBA", (len(specs) * 120 + 20, 140), (0, 0, 0, 0))
for i, s in enumerate(specs):
    row.alpha_composite(macui.render_icon(s).resize((112, 112), Image.LANCZOS), (10 + i * 120, 14))
on_wall(row, "icons.png", 20)
import wallpapers
names = [n for n, _ in wallpapers.CATALOG]
sheet = Image.new("RGB", (4 * 330 + 10, ((len(names) + 3) // 4) * 190 + 10), (20, 20, 22))
for i, n in enumerate(names):
    im = Image.open(ROOT / "wallpapers" / f"{n}.jpg")
    im.draft("RGB", (640, 360))
    sheet.paste(im.convert("RGB").resize((320, 180)), (10 + (i % 4) * 330, 10 + (i // 4) * 190))
sheet.save(OUT / "wallpapers.jpg", quality=88)
import system_theme as stt
cur = [stt.arrow(64), stt.hand(64), stt.ibeam(64), stt.double_arrow(64, 0), stt.beachball(64)]
docs = [stt.document_icon(*stt.FILE_TYPES[e], size=96) for e in (".txt", ".pdf", ".zip", ".mp3", ".png", ".py")]
strip = Image.new("RGBA", (len(cur) * 76 + len(docs) * 104 + 30, 112), (210, 210, 215, 255))
for i, im in enumerate(cur):
    strip.alpha_composite(im, (10 + i * 76, 24))
for i, im in enumerate(docs):
    strip.alpha_composite(im, (len(cur) * 76 + 20 + i * 104, 8))
strip.convert("RGB").save(OUT / "system_theme.png", optimize=True)
root.destroy()
print("done")
