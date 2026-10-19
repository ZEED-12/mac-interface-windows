"""
controlcenter.py — Control Center, the Wi-Fi and battery menus, and Spotlight.

The controls are real: volume through Core Audio, brightness through WMI, Wi-Fi through netsh.
"""
import ast
import ctypes
import operator
import os
import subprocess
import threading
import time
import urllib.parse
from ctypes import wintypes as W
from pathlib import Path

from PIL import Image, ImageDraw

from arabic import ar
from settings import STRINGS, rtl, tr

from macui import (Backdrop, glass_card, glass_inset, GUID, LANCZOS, P, VK_LWIN, Surface, aa_round, battery, blit, cursor, draw_text, exe_icon, font,
                   glass_overlay, glass_panel, lnk_target, mac_plate, mouse_down, ole32, open_target, press,
                   soft_shadow, user32, _generic)

NO_WINDOW = 0x08000000
WHITE = (255, 255, 255, 255)
DIM = (170, 170, 178, 255)
BLUE = (10, 132, 255, 255)


def play(name):
    """يشغل صوت من أصوات الماك اللي سويناها (بدون ما يوقف الواجهة)."""
    import winsound
    path = Path(os.environ.get("LOCALAPPDATA", "")) / "MacUI" / "icons" / "sounds" / f"mac_{name}.wav"
    if path.exists():
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)


def run_hidden(args, timeout=8):
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ───────────────────────────── الصوت (Core Audio) ─────────────────────────────

ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, W.DWORD]
ole32.CoCreateInstance.argtypes = [P(GUID), ctypes.c_void_p, W.DWORD, P(GUID), P(ctypes.c_void_p)]


def _guid(s):
    g = GUID()
    ole32.CLSIDFromString(s, ctypes.byref(g))
    return g


def _vcall(ptr, idx, argtypes, *args):
    vtbl = ctypes.cast(ptr, P(P(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtbl[idx])(ptr, *args)


class Audio:
    """مستوى صوت السماعة الافتراضية."""

    def __init__(self):
        ole32.CoInitializeEx(None, 2)
        self.ep = None

    def endpoint(self):
        if self.ep:
            return self.ep
        enum, dev, ep = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        if ole32.CoCreateInstance(ctypes.byref(_guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")), None, 0x17,
                                  ctypes.byref(_guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")), ctypes.byref(enum)):
            return None
        hr = _vcall(enum, 4, [ctypes.c_int, ctypes.c_int, P(ctypes.c_void_p)], 0, 1, ctypes.byref(dev))
        _vcall(enum, 2, [])
        if hr:
            return None
        hr = _vcall(dev, 3, [P(GUID), W.DWORD, ctypes.c_void_p, P(ctypes.c_void_p)],
                    ctypes.byref(_guid("{5CDF2C82-841E-4546-9722-0CF74078229A}")), 0x17, None, ctypes.byref(ep))
        _vcall(dev, 2, [])
        self.ep = ep if not hr else None
        return self.ep

    def reset(self):
        """السماعة الافتراضية ممكن تتغير (سماعة رأس مثلاً)."""
        if self.ep:
            _vcall(self.ep, 2, [])
            self.ep = None

    def get(self):
        ep = self.endpoint()
        if not ep:
            return None, False
        v, m = ctypes.c_float(), W.BOOL()
        _vcall(ep, 9, [P(ctypes.c_float)], ctypes.byref(v))
        _vcall(ep, 15, [P(W.BOOL)], ctypes.byref(m))
        return v.value, bool(m.value)

    def set(self, value):
        ep = self.endpoint()
        if ep:
            _vcall(ep, 7, [ctypes.c_float, ctypes.c_void_p], max(0.0, min(1.0, value)), None)
            if value > 0:
                _vcall(ep, 14, [W.BOOL, ctypes.c_void_p], 0, None)

    def toggle_mute(self):
        ep = self.endpoint()
        if ep:
            _, m = self.get()
            _vcall(ep, 14, [W.BOOL, ctypes.c_void_p], 0 if m else 1, None)


# ───────────────────────────── السطوع والواي فاي ─────────────────────────────

def get_brightness():
    out = run_hidden(["powershell", "-NoProfile", "-Command",
                      "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -EA Stop).CurrentBrightness"])
    try:
        return int(out.split()[0]) / 100
    except (ValueError, IndexError):
        return None


def set_brightness(value):
    pct = int(round(max(0.05, min(1.0, value)) * 100))
    subprocess.Popen(["powershell", "-NoProfile", "-Command",
                      "Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | "
                      f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1;Brightness={pct}}}"],
                     creationflags=NO_WINDOW)


def wifi_status():
    out = run_hidden(["netsh", "wlan", "show", "interfaces"])
    info = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            info.setdefault(k.strip().lower(), v.strip())
    if not out:
        return {"present": False}
    return {"present": True, "connected": info.get("state", "").lower() == "connected",
            "ssid": info.get("ssid", ""), "signal": info.get("signal", "")}


def wifi_networks():
    out = run_hidden(["netsh", "wlan", "show", "networks"])
    nets = []
    for line in out.splitlines():
        line = line.strip()
        if line.lower().startswith("ssid ") and ":" in line:
            name = line.split(":", 1)[1].strip()
            if name and name not in nets:
                nets.append(name)
    return nets


def wifi_profiles():
    out = run_hidden(["netsh", "wlan", "show", "profiles"])
    return {line.split(":", 1)[1].strip() for line in out.splitlines() if ":" in line and "profile" in line.lower()}


def wifi_connect(ssid):
    if ssid in wifi_profiles():
        subprocess.Popen(["netsh", "wlan", "connect", f"name={ssid}"], creationflags=NO_WINDOW)
    else:
        os.startfile("ms-settings:network-wifi")  # شبكة جديدة تحتاج كلمة مرور


# ───────────────────────────── لوحة زجاجية عامة ─────────────────────────────

class Flyout:
    """لوحة زجاجية تنزل من الشريط العلوي، تتقفل لما تضغط برا."""

    def __init__(self, ui, mon, x, y, w, h, activate=False):
        self.ui, self.mon, self.k = ui, mon, mon.k
        self.w, self.h = int(w), int(h)
        self.m = round(18 * self.k)
        self.r = round(18 * self.k)
        x = min(max(x, mon.x + 6), mon.x + mon.w - self.w - 6)
        self.x, self.y = x, y
        self.backdrop = Backdrop(ui.root)
        self.surface = Surface(ui.root, x - self.m, y - self.m, self.w + 2 * self.m, self.h + 2 * self.m,
                               activate=activate)
        self.backdrop.own(self.surface)
        self.regions = []
        self.alive = True
        self.born = time.time()
        self.drag = None
        win = self.surface.win
        win.bind("<ButtonPress-1>", self._press)
        win.bind("<B1-Motion>", self._motion)
        win.bind("<ButtonRelease-1>", self._release)

    def resize(self, h):
        if int(h) != self.h:
            self.h = int(h)
            self.surface.h = self.h + 2 * self.m
            self.surface.win.geometry(f"{self.w + 2 * self.m}x{self.surface.h}+{self.surface.x}+{self.surface.y}")

    def frame(self, tint=(30, 30, 36, 214)):
        img = Image.new("RGBA", (self.w + 2 * self.m, self.h + 2 * self.m), (0, 0, 0, 0))
        shadow, pad = soft_shadow(self.w, self.h, self.r, round(14 * self.k), 0.42)
        blit(img, shadow, self.m - pad, self.m - pad + round(5 * self.k))
        d = glass_inset(self.r, self.k)
        self.backdrop.place(self.x + d, self.y + d, self.w - 2 * d, self.h - 2 * d)
        card = glass_card(self.w, self.h, self.r, self.k, tint[:3], rim=210).copy()
        return img, card

    def present(self, img, card):
        blit(img, card, self.m, self.m)
        self.surface.show(img)

    def local(self, e):
        return e.x - self.m, e.y - self.m

    def hit(self, x, y):
        for r in self.regions:
            if r[0] <= x <= r[2] and r[1] <= y <= r[3]:
                return r
        return None

    def _press(self, e):
        r = self.hit(*self.local(e))
        if r and r[4] == "slider":
            self.drag = r
            self.slide(r, self.local(e)[0], False)

    def _motion(self, e):
        if self.drag:
            self.slide(self.drag, self.local(e)[0], False)

    def _release(self, e):
        if self.drag:
            self.slide(self.drag, self.local(e)[0], True)
            self.drag = None
            return
        r = self.hit(*self.local(e))
        if r:
            self.click(r)

    def slide(self, region, x, done):
        pass

    def click(self, region):
        pass

    def poll(self):
        if not self.alive:
            return
        cx, cy = cursor()
        inside = self.x <= cx < self.x + self.w and self.y <= cy < self.y + self.h
        if mouse_down() and not inside and not self.drag and time.time() - self.born > 0.2:
            self.close()
            return
        self.surface.win.after(40, self.poll)

    def close(self):
        if not self.alive:
            return
        self.alive = False
        self.surface.destroy()
        self.backdrop.destroy()
        self.ui.closed(self)


# ───────────────────────────── مركز التحكم ─────────────────────────────

class ControlCenter(Flyout):
    def __init__(self, ui, mon, right_x, y):
        k = mon.k
        self.pad, self.gap = round(12 * k), round(10 * k)
        self.th = round(58 * k)
        w = round(330 * k)
        h = self.pad * 2 + self.th * 2 + self.gap + (round(64 * k) + self.gap) * 2 + round(64 * k)
        super().__init__(ui, mon, right_x - w, y, w, h)
        self.audio = ui.audio
        self.wifi = ui.wifi_cache
        self.volume, self.muted = self.audio.get()
        self.bright = ui.bright_cache
        self.render()
        self.poll()
        threading.Thread(target=self.load, daemon=True).start()
        self.wait_load()

    def load(self):
        self.wifi_new = wifi_status()
        self.bright_new = get_brightness()
        self.loaded = True

    def wait_load(self):
        if not self.alive:
            return
        if getattr(self, "loaded", False):
            self.wifi = self.ui.wifi_cache = self.wifi_new
            self.bright = self.ui.bright_cache = self.bright_new
            self.render()
        else:
            self.surface.win.after(80, self.wait_load)

    def tile(self, card, x, y, w, h):
        t = aa_round(w, h, round(16 * self.k), (255, 255, 255, 30))
        t.alpha_composite(glass_overlay(w, h, round(16 * self.k), top=90, bottom=20, sheen=0))
        blit(card, t, x, y)

    def circle(self, card, cx, cy, glyph, on):
        d = round(30 * self.k)
        c = aa_round(d, d, d / 2, BLUE if on else (255, 255, 255, 46))
        draw_text(c, (d / 2, d / 2), glyph, font("SegoeIcons.ttf", round(14 * self.k)), WHITE, "mm")
        blit(card, c, cx - d / 2, cy - d / 2)

    def slider(self, card, x, y, w, value, glyph, key):
        k = self.k
        h = round(26 * k)
        track = aa_round(w, h, h / 2, (255, 255, 255, 40))
        R = rtl()
        if value is not None:
            fw = max(h, w * value)
            track.alpha_composite(aa_round(fw, h, h / 2, (255, 255, 255, 235)), (int(w - fw) if R else 0, 0))
        gx = w - h * 0.55 if R else h * 0.55
        draw_text(track, (gx, h / 2), glyph, font("SegoeIcons.ttf", round(13 * k)), (40, 40, 46, 255), "mm")
        blit(card, track, x, y)
        self.regions.append((x, y - round(6 * k), x + w, y + h + round(6 * k), "slider", key, x, w))

    def render(self):
        if not self.alive:
            return
        k, pad, gap, th = self.k, self.pad, self.gap, self.th
        R = rtl()
        X = (lambda x, w=0: self.w - x - w) if R else (lambda x, w=0: x)
        A = "rm" if R else "lm"
        img, card = self.frame()
        self.regions = []
        f13, f11 = font("seguisb.ttf", round(13 * k)), font("segoeui.ttf", round(11.5 * k))
        half = (self.w - 2 * pad - gap) / 2

        # الاتصال: واي فاي + بلوتوث
        self.tile(card, X(pad, half), pad, half, th * 2 + gap)
        wifi = self.wifi or {}
        ssid = (wifi.get("ssid") if wifi.get("connected") else tr("not_connected")) if wifi else "…"
        rows = [("\uE701", tr("wifi"), ar(ssid), bool(wifi.get("connected")), "wifi"),
                ("\uE702", tr("bt"), tr("settings"), True, "bt")]
        for i, (g, title, sub, on, key) in enumerate(rows):
            cy = pad + (th * 2 + gap) * (i + 0.5) / 2
            cx = pad + round(26 * k)
            self.circle(card, X(cx), cy, g, on)
            draw_text(card, (X(cx + round(24 * k)), cy - round(8 * k)), title, f13, WHITE, A)
            draw_text(card, (X(cx + round(24 * k)), cy + round(9 * k)), sub[:22], f11, DIM, A)
            self.regions.append((X(pad, half), cy - th / 2, X(pad, half) + half, cy + th / 2, "tap", key))

        # الجهة الثانية: انعكاس الشاشة + Mission Control
        rx = pad + half + gap
        for i, (g, skey, key) in enumerate((("\uEC15", "mirroring", "cast"), ("\uE7C4", "mission", "mc"))):
            ty = pad + i * (th + gap)
            self.tile(card, X(rx, half), ty, half, th)
            self.circle(card, X(rx + round(26 * k)), ty + th / 2, g, False)
            words = STRINGS[skey][1 if R else 0].split(" ", 1) + [""]
            for j, word in enumerate(words[:2]):
                draw_text(card, (X(rx + round(48 * k)), ty + th / 2 + (-1 if j == 0 else 1) * round(8.5 * k)),
                          ar(word), f13, WHITE, A)
            self.regions.append((X(rx, half), ty, X(rx, half) + half, ty + th, "tap", key))

        # السطوع والصوت
        y = pad + th * 2 + gap * 2
        full = self.w - 2 * pad
        sh = round(64 * k)
        for title, value, glyph, key in ((tr("display"), self.bright, "\uE706", "bright"),
                                         (tr("sound"), 0 if self.muted else self.volume,
                                          "\uE74F" if self.muted else "\uE767", "vol")):
            self.tile(card, pad, y, full, sh)
            draw_text(card, (X(pad + round(14 * k)), y + round(17 * k)), title, f13, WHITE, A)
            if value is None and key == "bright":
                draw_text(card, (X(pad + full - round(14 * k)), y + round(17 * k)), tr("display_settings"), f11, DIM,
                          "lm" if R else "rm")
                self.regions.append((pad, y, pad + full, y + sh, "tap", "display"))
            self.slider(card, pad + round(12 * k), y + round(30 * k), full - round(24 * k), value, glyph, key)
            if key == "vol":
                mx = X(pad + round(12 * k), round(26 * k))
                self.regions.insert(0, (mx, y + round(30 * k), mx + round(26 * k), y + round(56 * k), "tap", "mute"))
            y += sh + gap

        # قيد التشغيل
        self.tile(card, pad, y, full, sh)
        draw_text(card, (X(pad + round(14 * k)), y + sh / 2), tr("now_playing"), f13, WHITE, A)
        bx = pad + full - round(24 * k)
        for g, key in (("\uE893", "next"), ("\uE768", "play"), ("\uE892", "prev")):
            ax = X(bx)
            draw_text(card, (ax, y + sh / 2), g if not R else {"\uE893": "\uE892", "\uE892": "\uE893"}.get(g, g),
                      font("SegoeIcons.ttf", round(17 * k)), WHITE, "mm")
            self.regions.append((ax - round(16 * k), y, ax + round(16 * k), y + sh, "tap", key))
            bx -= round(44 * k)
        self.present(img, card)

    def slide(self, region, x, done):
        _, _, _, _, _, key, sx, sw = region
        value = max(0.0, min(1.0, (x - sx) / sw))
        if rtl():
            value = 1 - value
        if key == "vol":
            self.audio.set(value)
            self.volume, self.muted = value, False
            if done:
                play("pop")  # مثل الماك: صوت خفيف لما تغير مستوى الصوت
        elif key == "bright" and self.bright is not None:
            self.bright = value
            if done:
                self.ui.bright_cache = value
                set_brightness(value)
        self.render()

    def click(self, r):
        key = r[5]
        actions = {
            "wifi": lambda: self.ui.open_wifi(self.mon, self.x + self.w),
            "bt": lambda: os.startfile("ms-settings:bluetooth"),
            "cast": lambda: press(VK_LWIN, ord("K")),
            "mc": lambda: press(VK_LWIN, 0x09),
            "display": lambda: os.startfile("ms-settings:display"),
        }
        media = {"next": 0xB0, "prev": 0xB1, "play": 0xB3}
        if key in media:
            press(media[key])
            return
        if key == "mute":
            self.audio.toggle_mute()
            self.volume, self.muted = self.audio.get()
            self.render()
            return
        if key in actions:
            self.close()
            self.ui.root.after(30, actions[key])


# ───────────────────────────── Spotlight ─────────────────────────────

SKIP_WORDS = ("uninstall", "readme", "help", "documentation", "website", "license", "release notes", "verifier",
              "debuggable", "إلغاء التثبيت")
SKIP_DIRS = ("administrative tools", "windows tools", "system tools", "accessibility", "windows kits",
             "windows powershell", "maintenance", "startup")
BUILTIN_APPS = [("System Settings", "ms-settings:"), ("File Explorer", "explorer.exe"), ("Calculator", "app:calculator"),
                ("الآلة الحاسبة", "app:calculator"), ("Mac Settings", "app:settings"), ("About This Mac", "app:about"),
                ("Notepad", "notepad.exe"), ("Task Manager", "taskmgr.exe"), ("Terminal", "wt.exe"),
                ("Control Panel", "control.exe"), ("App Store", "ms-windows-store:"), ("Photos", "ms-photos:"),
                ("Snipping Tool", "ms-screenclip:"), ("Camera", "microsoft.windows.camera:")]


def app_index():
    roots = [Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
             Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs"]
    seen, out = set(), []
    for name, target in BUILTIN_APPS:
        seen.add(name.lower())
        out.append({"name": name, "path": target, "exe": None})
    for root in roots:
        if not root.is_dir():
            continue
        for lnk in root.rglob("*.lnk"):
            name = lnk.stem
            low = name.lower()
            folder = str(lnk.parent).lower()
            if low in seen or any(w in low for w in SKIP_WORDS) or any(d in folder for d in SKIP_DIRS):
                continue
            seen.add(low)
            out.append({"name": name, "path": str(lnk), "exe": None, "lnk": True})
    return out


_SAFE = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
         ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos}


def calc(expr):
    """حاسبة Spotlight: أرقام وعمليات بس (بدون تنفيذ أي كود)."""
    expr = expr.replace("^", "**").replace("×", "*").replace("÷", "/").replace(",", "")
    if not expr.strip() or not set(expr) <= set("0123456789.+-*/%() "):
        return None
    if not any(c.isdigit() for c in expr) or not any(c in "+-*/%" for c in expr.strip().lstrip("-")):
        return None

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _SAFE:
            left, right = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(right) > 100:
                raise ValueError
            return _SAFE[type(n.op)](left, right)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _SAFE:
            return _SAFE[type(n.op)](ev(n.operand))
        raise ValueError

    try:
        v = ev(ast.parse(expr, mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
        return None
    return f"{v:,.10g}" if isinstance(v, float) else f"{v:,}"


class Spotlight(Flyout):
    MAX = 7

    def __init__(self, ui, mon):
        k = mon.k
        w = round(660 * k)
        self.bar = round(56 * k)
        self.row = round(42 * k)
        super().__init__(ui, mon, mon.x + (mon.w - w) // 2, mon.y + int(mon.h * 0.2), w, self.bar, activate=True)
        self.r = round(24 * k)
        self.query, self.sel, self.results = "", 0, []
        self.icons = {}
        win = self.surface.win
        win.bind("<Key>", self.on_key)
        win.bind("<FocusOut>", lambda e: win.after(120, self.check_focus))
        win.focus_force()
        user32.SetForegroundWindow(self.surface.hwnd)
        self.blink()
        self.poll()

    def check_focus(self):
        if self.alive and user32.GetForegroundWindow() != self.surface.hwnd:
            self.close()

    def search(self):
        q = self.query.strip().lower()
        out = []
        if not q:
            return out
        value = calc(self.query)
        if value is not None:
            out.append({"kind": "calc", "name": value, "sub": tr("calculator"), "path": "app:calculator"})
        apps = self.ui.apps or []
        starts = [a for a in apps if a["name"].lower().startswith(q)]
        words = [a for a in apps if a not in starts and any(w.startswith(q) for w in a["name"].lower().split())]
        contains = [a for a in apps if a not in starts and a not in words and q in a["name"].lower()]
        for a in (starts + words + contains)[:self.MAX - 1 - len(out)]:
            out.append({"kind": "app", "name": a["name"], "sub": tr("application"), "path": a["path"], "app": a})
        web = (f"البحث في الويب عن «{self.query.strip()}»" if rtl() else f"Search the web for “{self.query.strip()}”")
        out.append({"kind": "web", "name": web, "sub": tr("web"),
                    "path": "https://www.google.com/search?q=" + urllib.parse.quote(self.query)})
        return out

    def icon_for(self, item, size):
        key = (item["path"], size)
        if key in self.icons:
            return self.icons[key]
        src = None
        if item["path"].startswith("app:"):
            own = {"calculator": "calculator", "settings": "settings", "about": "finder"}.get(item["path"][4:], "")
            icon = self.ui.icons.get({"icon": own, "name": item["name"]}, round(size * 512 / 432))
            self.icons[key] = icon.resize((size, size), LANCZOS)
            return self.icons[key]
        if item["kind"] == "app":
            p = item["path"]
            exe = lnk_target(p) if p.lower().endswith(".lnk") else (p if p.lower().endswith(".exe") else None)
            if exe:
                src = exe_icon(exe, 64)
        S = size * 2
        if src:
            body = mac_plate(src, S)
        else:
            glyph = {"calc": "E8EF", "web": "E774"}.get(item["kind"], "E8FC")
            body = _generic(S, {"name": item["name"], "glyph": glyph,
                                "color": {"calc": "#ff9f0a", "web": "#0a84ff"}.get(item["kind"], "#5e5ce6")}).convert("RGBA")
            from macui import squircle
            body.putalpha(squircle(S))
        self.icons[key] = body.resize((size, size), LANCZOS)
        return self.icons[key]

    def render(self):
        if not self.alive:
            return
        k = self.k
        self.results = self.search()
        self.sel = min(self.sel, max(0, len(self.results) - 1))
        rows = len(self.results)
        self.resize(self.bar + (rows * self.row + round(12 * k) if rows else 0))
        img, card = self.frame((28, 28, 34, 222))
        self.regions = []
        # شريط البحث
        R = rtl()
        X = (lambda x, w=0: self.w - x - w) if R else (lambda x, w=0: x)
        A = "rm" if R else "lm"
        draw_text(card, (X(round(22 * k)), self.bar / 2), "\uE721", font("SegoeIcons.ttf", round(19 * k)), DIM, "mm")
        fq = font("segoeui.ttf", round(22 * k))
        tx = round(46 * k)
        shown = ar(self.query) if self.query else tr("spotlight")
        draw_text(card, (X(tx), self.bar / 2), shown, fq, WHITE if self.query else (150, 150, 158, 255), A)
        cx = X(tx + (fq.getlength(shown) + round(2 * k) if self.query else 0))
        if int(time.time() * 2) % 2 == 0:
            ImageDraw.Draw(card).line([(cx, self.bar / 2 - round(12 * k)), (cx, self.bar / 2 + round(12 * k))],
                                      fill=BLUE, width=max(2, round(2 * k)))
        if rows:
            ImageDraw.Draw(card).line([(0, self.bar), (self.w, self.bar)], fill=(255, 255, 255, 30), width=1)
        f1, f2 = font("segoeui.ttf", round(14 * k)), font("segoeui.ttf", round(11.5 * k))
        isz = round(28 * k)
        for i, item in enumerate(self.results):
            y = self.bar + round(6 * k) + i * self.row
            if i == self.sel:
                blit(card, aa_round(self.w - round(16 * k), self.row, round(10 * k), BLUE), round(8 * k), y)
            blit(card, self.icon_for(item, isz), X(round(18 * k), isz), y + (self.row - isz) / 2)
            draw_text(card, (X(round(56 * k)), y + self.row / 2), ar(item["name"]), f1, WHITE, A)
            draw_text(card, (X(self.w - round(20 * k)), y + self.row / 2), item["sub"], f2,
                      WHITE if i == self.sel else DIM, "lm" if R else "rm")
            self.regions.append((0, y, self.w, y + self.row, "tap", i))
        self.present(img, card)

    def blink(self):
        if self.alive:
            self.render()
            self.surface.win.after(500, self.blink)

    def on_key(self, e):
        ks = e.keysym
        if ks == "Escape":
            self.close()
        elif ks == "Return":
            self.launch(self.sel)
        elif ks in ("Down", "Up"):
            if self.results:
                self.sel = (self.sel + (1 if ks == "Down" else -1)) % len(self.results)
            self.render()
        elif ks == "BackSpace":
            self.query = self.query[:-1]
            self.sel = 0
            self.render()
        elif e.char and e.char.isprintable() and not (e.state & 0x4):
            self.query += e.char
            self.sel = 0
            self.render()

    def click(self, r):
        self.launch(r[5])

    def launch(self, i):
        if not (0 <= i < len(self.results)):
            return
        item = self.results[i]
        self.close()
        if item["kind"] == "calc":
            self.ui.root.clipboard_clear()
            self.ui.root.clipboard_append(item["name"].replace(",", ""))
        open_target([item["path"]])


# ───────────────────────────── قوائم صغيرة ─────────────────────────────

def wifi_entries(status, networks, ui):
    entries = [(tr("wifi"), None)]
    current = status.get("ssid") if status.get("connected") else None
    if current:
        entries.append((ar("✓  " + current), None))
    others = [n for n in networks if n != current]
    if others:
        entries += [None, (tr("other_networks"), None)]
        entries += [(ar("     " + n), (lambda n=n: wifi_connect(n))) for n in others[:8]]
    entries += [None, (tr("wifi_settings"), lambda: os.startfile("ms-settings:network-wifi"))]
    return entries


def battery_entries():
    bat = battery()
    if not bat:
        i = 1 if rtl() else 0
        return [(tr("power"), None), (ar(f"{STRINGS['power_source'][i]} {STRINGS['adapter'][i]}"), None), None,
                (tr("battery_settings"), lambda: os.startfile("ms-settings:powersleep"))]
    pct, ac = bat
    src = tr("adapter") if ac else tr("on_battery")
    return [(ar(f"{STRINGS['battery'][1 if rtl() else 0]}  {pct}%"), None),
            (ar(f"{STRINGS['power_source'][1 if rtl() else 0]} {STRINGS['adapter' if ac else 'on_battery'][1 if rtl() else 0]}"), None),
            None,
            (tr("battery_settings"), lambda: os.startfile("ms-settings:batterysaver"))]
