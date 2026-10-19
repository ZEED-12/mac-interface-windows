"""
widgets.py — macOS-style desktop widgets: three sizes, the "Edit Widgets" gallery, and user widgets.

Widgets sit above the wallpaper and below every app, can be dragged anywhere and snap to each other.
Users add their own widgets with a small JSON file in widgets_custom/ (see the README there).
"""
import calendar
import ctypes
import importlib.util
import json
import math
import os
import random
import shutil
import struct
import subprocess
import threading
import time
import urllib.request
import winreg
from ctypes import wintypes as W
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps

from arabic import ar
from settings import DAYS, MONTHS, S as SETTINGS, STRINGS, lang, rtl, tr
from macui import (Backdrop, glass_card, glass_inset, GWLP_HWNDPARENT, HERE, LANCZOS, P, Surface, aa_round, battery, blit, cursor, draw_text, font,
                   glass_overlay, glass_panel, kernel32, load_apps, mouse_down, open_target, soft_shadow, stroke,
                   user32, vgrad)

WIDGETS_FILE = HERE / "widgets.json"
CUSTOM_DIR = HERE / "widgets_custom"
NOTES_FILE = HERE / "widget_notes.txt"
WHITE = (255, 255, 255, 255)
DIM = (160, 160, 168, 255)
RED = (255, 69, 58, 255)
ORANGE = (255, 159, 10, 255)
SIZES = {"small": (1, 1), "medium": (2, 1), "large": (2, 2)}
NO_WINDOW = 0x08000000


def glass_amount():
    return max(0.0, min(1.0, float(SETTINGS.get("glass", 0.45))))


# ───────────────────────────── قياسات الجهاز ─────────────────────────────

class FILETIME(ctypes.Structure):
    _fields_ = [("lo", W.DWORD), ("hi", W.DWORD)]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", W.DWORD), ("dwMemoryLoad", W.DWORD), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class SYSTEMTIME(ctypes.Structure):
    _fields_ = [(n, W.WORD) for n in ("wYear", "wMonth", "wDayOfWeek", "wDay", "wHour", "wMinute", "wSecond",
                                      "wMilliseconds")]


class TIME_ZONE_INFORMATION(ctypes.Structure):
    _fields_ = [("Bias", ctypes.c_long), ("StandardName", ctypes.c_wchar * 32), ("StandardDate", SYSTEMTIME),
                ("StandardBias", ctypes.c_long), ("DaylightName", ctypes.c_wchar * 32), ("DaylightDate", SYSTEMTIME),
                ("DaylightBias", ctypes.c_long)]


kernel32.GetSystemTimes.argtypes = [P(FILETIME)] * 3
kernel32.GetSystemTimes.restype = W.BOOL
kernel32.GlobalMemoryStatusEx.argtypes = [P(MEMORYSTATUSEX)]
kernel32.GlobalMemoryStatusEx.restype = W.BOOL
kernel32.GetSystemTime.argtypes = [P(SYSTEMTIME)]
kernel32.SystemTimeToTzSpecificLocalTime.argtypes = [P(TIME_ZONE_INFORMATION), P(SYSTEMTIME), P(SYSTEMTIME)]
kernel32.SystemTimeToTzSpecificLocalTime.restype = W.BOOL


class CPU:
    def __init__(self):
        self.prev = self.times()

    @staticmethod
    def times():
        i, k, u = FILETIME(), FILETIME(), FILETIME()
        kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
        return [(t.hi << 32) | t.lo for t in (i, k, u)]

    def percent(self):
        cur = self.times()
        di, dk, du = (c - p for c, p in zip(cur, self.prev))
        self.prev = cur
        total = dk + du  # وقت النواة يشمل الخمول
        return 0 if total <= 0 else max(0, min(100, round(100 * (total - di) / total)))


def memory_percent():
    m = MEMORYSTATUSEX(dwLength=ctypes.sizeof(MEMORYSTATUSEX))
    kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.dwMemoryLoad


_TZ = {}


def tz_time(key):
    """الوقت في منطقة زمنية حسب بيانات ويندوز نفسها (التوقيت الصيفي محسوب)."""
    if key not in _TZ:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                rf"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Time Zones\{key}") as k:
                raw = winreg.QueryValueEx(k, "TZI")[0]
            bias, sbias, dbias, *rest = struct.unpack("<lll8H8H", raw)
            tzi = TIME_ZONE_INFORMATION(Bias=bias, StandardBias=sbias, DaylightBias=dbias)
            tzi.StandardDate = SYSTEMTIME(*rest[:8])
            tzi.DaylightDate = SYSTEMTIME(*rest[8:])
            _TZ[key] = tzi
        except OSError:
            _TZ[key] = None
    utc, out = SYSTEMTIME(), SYSTEMTIME()
    kernel32.GetSystemTime(ctypes.byref(utc))
    tzi = _TZ[key]
    if tzi is None or not kernel32.SystemTimeToTzSpecificLocalTime(ctypes.byref(tzi), ctypes.byref(utc), ctypes.byref(out)):
        t = time.localtime()
        return t.tm_hour, t.tm_min, t.tm_sec, 0
    local = time.localtime()
    day_diff = (out.wDay != local.tm_mday) * (1 if (out.wYear, out.wMonth, out.wDay) >
                                              (local.tm_year, local.tm_mon, local.tm_mday) else -1)
    return out.wHour, out.wMinute, out.wSecond, day_diff


# ───────────────────────────── الطقس ─────────────────────────────

WMO = {0: "clear", 1: "mostly", 2: "partly", 3: "cloudy", 45: "fog", 48: "fog", 51: "drizzle", 53: "drizzle",
       55: "drizzle", 56: "drizzle", 57: "drizzle", 61: "rain", 63: "rain", 65: "heavy", 66: "rain", 67: "rain",
       71: "snow", 73: "snow", 75: "snow", 77: "snow", 80: "showers", 81: "showers", 82: "showers",
       85: "snowshowers", 86: "snowshowers", 95: "storm", 96: "storm", 99: "storm"}
WMO_TEXT = {"clear": ("Clear", "صافٍ"), "sunny": ("Sunny", "مشمس"), "mostly": ("Mostly Clear", "صافٍ غالبًا"),
            "partly": ("Partly Cloudy", "غائم جزئيًا"), "cloudy": ("Cloudy", "غائم"), "fog": ("Fog", "ضباب"),
            "drizzle": ("Drizzle", "رذاذ"), "rain": ("Rain", "مطر"), "heavy": ("Heavy Rain", "مطر غزير"),
            "snow": ("Snow", "ثلج"), "showers": ("Showers", "زخات مطر"), "snowshowers": ("Snow Showers", "زخات ثلج"),
            "storm": ("Thunderstorm", "عاصفة رعدية")}
ICON_KIND = {"clear": "clear", "mostly": "partly", "partly": "partly", "cloudy": "cloudy", "fog": "fog",
             "drizzle": "rain", "rain": "rain", "heavy": "rain", "showers": "rain", "snow": "snow",
             "snowshowers": "snow", "storm": "storm"}


def condition(code, day):
    key = WMO.get(code, "cloudy")
    if key == "clear" and day:
        key = "sunny"
    en, a = WMO_TEXT[key]
    return (a if rtl() else en), ICON_KIND.get(WMO.get(code, "cloudy"), "cloudy")


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "MacDesktopWidgets/2.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def locate():
    """الموقع التقريبي من الإنترنت (المدينة) عشان الطقس."""
    for url in ("https://ipapi.co/json/", "http://ip-api.com/json/?fields=city,lat,lon"):
        try:
            j = _get_json(url)
            lat, lon = j.get("latitude", j.get("lat")), j.get("longitude", j.get("lon"))
            if lat is not None and lon is not None:
                return {"name": j.get("city") or "", "lat": lat, "lon": lon}
        except Exception:
            continue
    return None


def fetch_weather(loc):
    j = _get_json("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                  "&current=temperature_2m,weather_code,is_day"
                  "&hourly=temperature_2m,weather_code,is_day"
                  "&daily=temperature_2m_max,temperature_2m_min,weather_code"
                  "&timezone=auto&forecast_days=6".format(**loc))
    cur, daily, hourly = j["current"], j["daily"], j["hourly"]
    now = cur["time"][:13]
    start = next((i for i, t in enumerate(hourly["time"]) if t[:13] >= now), 0)
    hours = [{"h": int(hourly["time"][i][11:13]), "t": round(hourly["temperature_2m"][i]),
              "c": int(hourly["weather_code"][i]), "d": bool(hourly["is_day"][i])}
             for i in range(start, min(start + 6, len(hourly["time"])))]
    days = [{"date": daily["time"][i], "hi": round(daily["temperature_2m_max"][i]),
             "lo": round(daily["temperature_2m_min"][i]), "c": int(daily["weather_code"][i])}
            for i in range(len(daily["time"]))]
    return {"name": loc.get("name", ""), "temp": round(cur["temperature_2m"]), "code": int(cur["weather_code"]),
            "day": bool(cur.get("is_day", 1)), "hi": days[0]["hi"], "lo": days[0]["lo"], "hours": hours, "days": days}


_wicons = {}


def weather_icon(kind, day, size):
    key = (kind, day, size)
    if key in _wicons:
        return _wicons[key]
    ss = 4
    S = size * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = lambda a: a * S

    def sun(cx, cy, r):
        for i in range(8):
            a = math.radians(i * 45)
            stroke(d, (cx + r * 1.35 * math.cos(a), cy + r * 1.35 * math.sin(a)),
                   (cx + r * 1.75 * math.cos(a), cy + r * 1.75 * math.sin(a)), r * 0.22, (255, 214, 10, 255))
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 214, 10, 255))

    def moon(cx, cy, r):
        m = Image.new("L", (S, S), 0)
        md = ImageDraw.Draw(m)
        md.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
        md.ellipse((cx - r * 0.35, cy - r * 1.15, cx + r * 1.45, cy + r * 0.6), fill=0)
        img.paste((240, 240, 250, 255), (0, 0), m)

    def cloud(cx, cy, w, col=(255, 255, 255, 255)):
        h = w * 0.36
        d.rounded_rectangle((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), int(h / 2), fill=col)
        d.ellipse((cx - w * 0.3, cy - h * 1.15, cx + w * 0.12, cy + h * 0.25), fill=col)
        d.ellipse((cx - w * 0.02, cy - h * 1.45, cx + w * 0.38, cy + h * 0.1), fill=col)

    if kind == "clear":
        (sun if day else moon)(f(.5), f(.5), f(.24 if day else .3))
    elif kind == "partly":
        (sun if day else moon)(f(.62), f(.38), f(.17 if day else .2))
        cloud(f(.45), f(.62), f(.68))
    elif kind == "cloudy":
        cloud(f(.6), f(.42), f(.52), (200, 205, 215, 255))
        cloud(f(.45), f(.62), f(.68))
    elif kind == "fog":
        for i, y in enumerate((.35, .5, .65)):
            stroke(d, (f(.18 + .06 * (i % 2)), f(y)), (f(.82 - .06 * (i % 2)), f(y)), f(.07), (230, 230, 238, 255))
    else:
        cloud(f(.5), f(.42), f(.72))
        if kind == "rain":
            for x in (.32, .5, .68):
                stroke(d, (f(x), f(.68)), (f(x - .06), f(.86)), f(.05), (100, 190, 255, 255))
        elif kind == "snow":
            for x, y in ((.32, .72), (.5, .82), (.68, .72), (.41, .9), (.59, .9)):
                d.ellipse((f(x - .035), f(y - .035), f(x + .035), f(y + .035)), fill=WHITE)
        elif kind == "storm":
            d.polygon([(f(.52), f(.6)), (f(.38), f(.8)), (f(.5), f(.8)), (f(.44), f(.97)),
                       (f(.64), f(.72)), (f(.52), f(.72)), (f(.6), f(.6))], fill=(255, 214, 10, 255))
    _wicons[key] = img.resize((size, size), LANCZOS)
    return _wicons[key]


def wrap(text, fnt, width, max_lines=99):
    """يقسم النص لأسطر تناسب العرض (يدعم العربي)."""
    lines = []
    for para in str(text).splitlines() or [""]:
        cur = ""
        for word in para.split(" "):
            test = (cur + " " + word).strip()
            if fnt.getlength(ar(test)) <= width or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines[:max_lines]


# ───────────────────────────── الأداة الأساسية ─────────────────────────────

class Widget:
    kind = ""
    title_key = ""
    glyph = "E10F"
    sizes = ("small",)
    every = 60
    link = None

    def __init__(self, host, item, preview=False):
        self.host, self.item = host, item
        self.size = item.get("size") if item.get("size") in self.sizes else self.sizes[0]
        item["size"] = self.size
        self.k = k = host.mon.k
        cols, rows = SIZES[self.size]
        self.w = host.u * cols + host.gap * (cols - 1)
        self.h = host.u * rows + host.gap * (rows - 1)
        self.r = round(22 * k)
        self.m = round(20 * k)
        self.pad = round(16 * k)
        self.dx, self.dy = item.get("dx", 0), item.get("dy", 0)
        self.bg = None
        self.alive = not preview
        self.setup()
        if preview:
            return
        mon = host.mon
        self.surface = Surface(host.ui.root, mon.x + self.dx - self.m, mon.y + self.dy - self.m,
                               self.w + 2 * self.m, self.h + 2 * self.m, topmost=False)
        host.attach(self.surface)
        self.shadow, self.spad = soft_shadow(self.w, self.h, self.r, round(14 * k), 0.4)
        self.drag = None
        win = self.surface.win
        win.bind("<ButtonPress-1>", self.on_press)
        win.bind("<B1-Motion>", self.on_motion)
        win.bind("<ButtonRelease-1>", self.on_release)
        win.bind("<ButtonRelease-3>", self.on_right)
        self.render()
        self.schedule()

    @property
    def config(self):
        return self.item.setdefault("config", {})

    def setup(self):
        pass

    # ── مساعدات الاتجاه: x منطقي من «بداية» السطر (يسار بالإنجليزي، يمين بالعربي) ──
    def tx(self, x):
        return self.w - x if rtl() else x

    def bx(self, x, w):
        return self.w - x - w if rtl() else x

    def text(self, card, x, y, s, fnt, color=WHITE, align="start", v="m"):
        if align == "center":
            h = "m"
        elif (align == "start") != rtl():
            h = "l"
        else:
            h = "r"
        draw_text(card, (self.tx(x) if align != "center" else x, y), ar(str(s)), fnt, color, h + v)

    # ── الخلفية والرسم ──
    def card(self):
        g = glass_amount()
        return self.host.mon.frost((self.dx, self.dy, self.dx + self.w, self.dy + self.h),
                                   (26, 26, 32), 0.42 + 0.35 * g, round(24 * self.k)).convert("RGBA")

    def background(self):
        if self.bg is None:
            body = self.card()
            body.putalpha(aa_round(self.w, self.h, self.r, WHITE).getchannel("A"))
            body.alpha_composite(glass_overlay(self.w, self.h, self.r, top=175, bottom=45, sheen=32))
            self.bg = body
        return self.bg

    def draw(self, card):
        pass

    def compose(self):
        card = self.background().copy()
        try:
            self.draw(card)
        except Exception as e:  # أداة خربانة ما توقف الباقي
            draw_text(card, (self.w / 2, self.h / 2), f"⚠ {type(e).__name__}", font("segoeui.ttf", round(12 * self.k)),
                      DIM, "mm")
        return card

    def render(self):
        if not self.alive:
            return
        img = Image.new("RGBA", (self.w + 2 * self.m, self.h + 2 * self.m), (0, 0, 0, 0))
        blit(img, self.shadow, self.m - self.spad, self.m - self.spad + round(5 * self.k))
        blit(img, self.compose(), self.m, self.m)
        if self.host.editing:  # زر الحذف (−) فوق الزاوية مثل الماك
            b = round(22 * self.k)
            badge = glass_panel(b, b, b / 2, (88, 88, 94, 245)).copy()
            ImageDraw.Draw(badge).line([(b * .3, b / 2), (b * .7, b / 2)], fill=WHITE, width=max(2, round(2 * self.k)))
            bxp = self.m + self.w - b * 0.6 if rtl() else self.m - b * 0.4
            blit(img, badge, bxp, self.m - b * 0.4)
        self.surface.show(img)

    def schedule(self):
        if self.alive:
            self.surface.win.after(int(self.every * 1000), self.tick)

    def tick(self):
        if self.alive:
            self.render()
            self.schedule()

    # ── سحب وإفلات وضغط ──
    def on_press(self, e):
        self.drag = [e.x_root, e.y_root, self.dx, self.dy, False]

    def on_motion(self, e):
        if not self.drag:
            return
        sx, sy, dx0, dy0, moved = self.drag
        ddx, ddy = e.x_root - sx, e.y_root - sy
        if not moved and abs(ddx) + abs(ddy) < 5:
            return
        self.drag[4] = True
        self.move_to(dx0 + ddx, dy0 + ddy)

    def move_to(self, dx, dy, snap=False):
        mon, host = self.host.mon, self.host
        dx = min(max(dx, 0), mon.w - self.w)
        dy = min(max(dy, host.top), mon.h - host.bottom - self.h)
        if snap:
            dx, dy = host.snap(self, dx, dy)
        self.dx, self.dy = int(dx), int(dy)
        self.item["dx"], self.item["dy"] = self.dx, self.dy
        self.bg = None
        self.surface.x, self.surface.y = mon.x + self.dx - self.m, mon.y + self.dy - self.m
        self.render()
        self.surface.win.geometry(f"+{self.surface.x}+{self.surface.y}")

    def on_release(self, e):
        drag, self.drag = self.drag, None
        if not drag:
            return
        if drag[4]:
            self.move_to(self.dx, self.dy, snap=True)
            self.host.save()
            return
        lx, ly = e.x - self.m, e.y - self.m
        b = round(22 * self.k)
        on_badge = ly < b * 0.7 and ((lx > self.w - b * 0.7) if rtl() else (lx < b * 0.7))
        if self.host.editing and on_badge:
            self.host.remove(self)
        else:
            self.click(lx, ly)

    def click(self, x, y):
        if self.link:
            open_target(self.link)

    def menu_entries(self):
        return []

    def on_right(self, e):
        host = self.host
        entries = []
        if len(self.sizes) > 1:
            for sz in self.sizes:
                mark = "✓  " if sz == self.size else "     "
                entries.append((ar(mark) + tr(sz), lambda sz=sz: host.resize(self, sz)))
            entries.append(None)
        entries += self.menu_entries()
        entries += [(tr("edit_widgets"), host.ui.open_widget_gallery), None,
                    (tr("remove_widget"), lambda: host.remove(self))]
        host.ui.show_popup(host.mon, e.x_root, e.y_root, entries)

    def destroy(self):
        self.alive = False
        if hasattr(self, "surface"):
            self.surface.destroy()


# ───────────────────────────── الأدوات ─────────────────────────────

CITIES = [("Cupertino", "كوبرتينو", "Pacific Standard Time"), ("London", "لندن", "GMT Standard Time"),
          ("Tokyo", "طوكيو", "Tokyo Standard Time"), ("Sydney", "سيدني", "AUS Eastern Standard Time")]


class Clock(Widget):
    kind, title_key, glyph = "clock", "clock", "E121"
    sizes = ("small", "medium")
    every = 1
    link = ["ms-clock:"]

    def setup(self):
        self.faces = {}

    def face(self, S):
        if S not in self.faces:
            ss = 3
            big = Image.new("RGBA", (S * ss, S * ss), (0, 0, 0, 0))
            c, R = S * ss / 2, S * ss * 0.46
            ImageDraw.Draw(big).ellipse((c - R, c - R, c + R, c + R), fill=(28, 28, 31, 255),
                                        outline=(255, 255, 255, 30), width=ss)
            for n in range(1, 13):
                a = math.radians(n * 30)
                draw_text(big, (c + R * 0.78 * math.sin(a), c - R * 0.78 * math.cos(a)), str(n),
                          font("seguisb.ttf", R * 0.2), (242, 242, 247, 255), "mm")
            self.faces[S] = big.resize((S, S), LANCZOS)
        return self.faces[S]

    def dial(self, card, x, y, S, hms, seconds=True):
        blit(card, self.face(S), x, y)
        ss = 2
        hands = Image.new("RGBA", (S * ss, S * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(hands)
        c, R = S * ss / 2, S * ss * 0.46
        h, m, s = hms
        point = lambda deg, r: (c + r * math.sin(math.radians(deg)), c - r * math.cos(math.radians(deg)))
        stroke(d, (c, c), point(((h % 12) + m / 60) * 30, R * 0.48), R * 0.065, WHITE)
        stroke(d, (c, c), point((m + s / 60) * 6, R * 0.72), R * 0.045, WHITE)
        if seconds:
            stroke(d, point(s * 6 + 180, R * 0.16), point(s * 6, R * 0.84), R * 0.02, ORANGE)
        d.ellipse((c - R * .055, c - R * .055, c + R * .055, c + R * .055), fill=ORANGE)
        blit(card, hands.resize((S, S), LANCZOS), x, y)

    def draw(self, card):
        if self.size == "small":
            t = time.localtime()
            S = self.h - round(18 * self.k)
            self.dial(card, (self.w - S) / 2, round(9 * self.k), S, (t.tm_hour, t.tm_min, t.tm_sec))
            return
        # الساعة العالمية: أربع مدن
        k = self.k
        n = len(CITIES)
        cw = (self.w - 2 * self.pad) / n
        S = round(min(cw - 10 * k, self.h * 0.55))
        fs, fd = font("seguisb.ttf", round(12 * k)), font("segoeui.ttf", round(11 * k))
        order = list(reversed(CITIES)) if rtl() else CITIES
        for i, (en, a, tz) in enumerate(order):
            h, m, s, dd = tz_time(tz)
            cx = self.pad + cw * (i + 0.5)
            self.dial(card, cx - S / 2, round(16 * k), S, (h, m, s), seconds=False)
            draw_text(card, (cx, round(28 * k) + S), ar(a if rtl() else en), fs, WHITE, "mm")
            rel = {0: ("Today", "اليوم"), 1: ("Tomorrow", "غدًا"), -1: ("Yesterday", "أمس")}[dd]
            draw_text(card, (cx, round(44 * k) + S), ar(rel[1] if rtl() else rel[0]), fd, DIM, "mm")


class Calendar(Widget):
    kind, title_key, glyph = "calendar", "calendar", "E787"
    sizes = ("small", "medium", "large")
    every = 30
    link = ["outlookcal:", "ms-settings:dateandtime"]

    def grid(self, card, x0, top, gw, gh, t, big=False):
        k = self.k
        weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(t.tm_year, t.tm_mon)
        cw, ch = gw / 7, gh / (len(weeks) + 1)
        fh = font("seguisb.ttf", round((12 if big else 10) * k))
        fday = font("segoeui.ttf", round((14 if big else 11) * k))
        fbold = font("segoeuib.ttf", round((14 if big else 11) * k))
        heads = ["ح", "ن", "ث", "ر", "خ", "ج", "س"] if rtl() else list("SMTWTFS")
        for i, name in enumerate(heads):
            draw_text(card, (self.tx(x0 + cw * (i + 0.5)), top + ch / 2), ar(name), fh, DIM, "mm")
        for r, week in enumerate(weeks):
            for i, day in enumerate(week):
                if not day:
                    continue
                cx, cy = self.tx(x0 + cw * (i + 0.5)), top + ch * (r + 1.5)
                if day == t.tm_mday:
                    dot = aa_round(ch * 0.95, ch * 0.95, ch * 0.475, RED)
                    blit(card, dot, cx - dot.width / 2, cy - dot.height / 2)
                    draw_text(card, (cx, cy), str(day), fbold, WHITE, "mm")
                else:
                    draw_text(card, (cx, cy), str(day), fday, DIM if i in (5, 6) else (235, 235, 240, 255), "mm")

    def draw(self, card):
        k, pad = self.k, self.pad
        t = time.localtime()
        day = DAYS[lang()][t.tm_wday]
        month = MONTHS[lang()][t.tm_mon - 1]
        if self.size == "large":
            self.text(card, pad, pad + round(8 * k), f"{month} {t.tm_year}", font("segoeuib.ttf", round(16 * k)), RED)
            self.grid(card, pad, pad + round(26 * k), self.w - 2 * pad, self.h - 2 * pad - round(56 * k), t, big=True)
            self.text(card, pad, self.h - pad - round(8 * k), tr("no_events"), font("segoeui.ttf", round(12 * k)), DIM)
            return
        self.text(card, pad, pad + round(6 * k), day if rtl() else day.upper(), font("segoeuib.ttf", round(12 * k)), RED)
        self.text(card, pad - round(3 * k), pad + round(16 * k), t.tm_mday, font("segoeuil.ttf", round(64 * k)), WHITE,
                  v="a")
        self.text(card, pad, self.h - pad - round(26 * k), f"{month} {t.tm_year}", font("seguisb.ttf", round(13 * k)),
                  (235, 235, 240, 255))
        self.text(card, pad, self.h - pad - round(8 * k), tr("no_events"), font("segoeui.ttf", round(11 * k)), DIM)
        if self.size == "medium":
            x0 = self.w * 0.47
            self.text(card, x0, pad + round(6 * k), month if rtl() else month.upper(), font("segoeuib.ttf", round(11 * k)),
                      RED)
            self.grid(card, x0, pad + round(24 * k), self.w - x0 - pad, self.h - 2 * pad - round(20 * k), t)


class Weather(Widget):
    kind, title_key, glyph = "weather", "weather", "E706"
    sizes = ("small", "medium", "large")
    every = 2
    link = ["msnweather://forecast", "https://www.msn.com/weather"]

    def setup(self):
        self.state = None

    def card(self):
        w = self.host.weather
        day = w["day"] if w else True
        top, bottom = ((74, 158, 245, 255), (35, 104, 206, 255)) if day else ((34, 48, 96, 255), (12, 20, 48, 255))
        return vgrad(self.w, self.h, top, bottom)

    def tick(self):
        w = self.host.weather
        state = (id(w), self.host.weather_error)
        if state != self.state:
            self.state = state
            self.bg = None
            self.render()
        self.schedule()

    def draw(self, card):
        k, pad = self.k, self.pad
        w = self.host.weather
        name = (w or {}).get("name") or tr("weather")
        self.text(card, pad, pad + round(7 * k), name, font("seguisb.ttf", round(13.5 * k)))
        if not w:
            msg = tr("loading") if self.host.weather_error is None else tr("no_connection")
            self.text(card, pad, pad + round(40 * k), msg, font("segoeui.ttf", round(13 * k)), (230, 236, 255, 255))
            return
        cond, kind = condition(w["code"], w["day"])
        hl = (f"↑{w['hi']}°  ↓{w['lo']}°" if rtl() else f"H:{w['hi']}°  L:{w['lo']}°")
        if self.size == "small":
            self.text(card, pad - round(2 * k), pad + round(16 * k), f"{w['temp']}°", font("segoeuil.ttf", round(46 * k)),
                      v="a")
            blit(card, weather_icon(kind, w["day"], round(20 * k)), self.bx(pad, round(20 * k)),
                 self.h - pad - round(50 * k))
            self.text(card, pad, self.h - pad - round(22 * k), cond, font("seguisb.ttf", round(12 * k)))
            self.text(card, pad, self.h - pad - round(6 * k), hl, font("seguisb.ttf", round(12 * k)))
            return
        # متوسط/كبير: الحالي فوق + الساعات الجاية
        self.text(card, pad - round(2 * k), pad + round(16 * k), f"{w['temp']}°", font("segoeuil.ttf", round(40 * k)),
                  v="a")
        blit(card, weather_icon(kind, w["day"], round(22 * k)), self.bx(self.w - pad - round(22 * k), round(22 * k)),
             pad)
        self.text(card, self.w - pad, pad + round(38 * k), cond, font("seguisb.ttf", round(12 * k)), align="end")
        self.text(card, self.w - pad, pad + round(55 * k), hl, font("seguisb.ttf", round(12 * k)), align="end")
        row_y = round(self.host.u * 0.62)
        hours = w.get("hours", [])[:6]
        if hours:
            cw = (self.w - 2 * pad) / len(hours)
            fs = font("segoeui.ttf", round(11 * k))
            for i, hr in enumerate(hours):
                cx = self.tx(pad + cw * (i + 0.5))
                h12 = hr["h"] % 12 or 12
                label = (f"{h12}{'ص' if hr['h'] < 12 else 'م'}" if rtl() else f"{h12}{'AM' if hr['h'] < 12 else 'PM'}")
                if i == 0:
                    label = "الآن" if rtl() else "Now"
                draw_text(card, (cx, row_y), ar(label), fs, (225, 235, 255, 255), "mm")
                _, hk = condition(hr["c"], hr["d"])
                ic = weather_icon(hk, hr["d"], round(20 * k))
                blit(card, ic, cx - ic.width / 2, row_y + round(10 * k))
                draw_text(card, (cx, row_y + round(44 * k)), f"{hr['t']}°", font("seguisb.ttf", round(12 * k)), WHITE, "mm")
        if self.size == "large":
            y = self.host.u + self.host.gap + round(8 * k)
            ImageDraw.Draw(card).line([(pad, y - round(6 * k)), (self.w - pad, y - round(6 * k))], fill=(255, 255, 255, 50))
            rows = w.get("days", [])[:5]
            rh = (self.h - y - pad) / max(1, len(rows))
            for i, dd in enumerate(rows):
                cy = y + rh * (i + 0.5)
                yy, mm, dday = map(int, dd["date"].split("-"))
                wd = time.struct_time((yy, mm, dday, 0, 0, 0, calendar.weekday(yy, mm, dday), 0, -1)).tm_wday
                name = ("اليوم" if rtl() else "Today") if i == 0 else DAYS[lang()][wd][:3 if not rtl() else None]
                self.text(card, pad, cy, name, font("seguisb.ttf", round(12.5 * k)))
                _, dk = condition(dd["c"], True)
                ic = weather_icon(dk, True, round(18 * k))
                blit(card, ic, self.bx(self.w * 0.36, ic.width), cy - ic.height / 2)
                self.text(card, self.w * 0.55, cy, f"{dd['lo']}°", font("segoeui.ttf", round(12 * k)), DIM)
                bar_x, bar_w = self.w * 0.64, self.w * 0.22
                bar = aa_round(bar_w, round(4 * k), round(2 * k), (255, 255, 255, 70))
                blit(card, bar, self.bx(bar_x, bar_w), cy - bar.height / 2)
                self.text(card, self.w - pad, cy, f"{dd['hi']}°", font("seguisb.ttf", round(12 * k)), align="end")


class Battery(Widget):
    kind, title_key, glyph = "battery", "battery", "E83F"
    every = 20
    link = ["ms-settings:batterysaver"]

    def draw(self, card):
        k, ss = self.k, 3
        bat = battery()
        pct, charging = bat if bat else (100, True)
        size = round(self.h * 0.56)
        big = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(big)
        lw = round(8 * k) * ss
        box = (lw / 2, lw / 2, size * ss - lw / 2, size * ss - lw / 2)
        d.ellipse(box, outline=(72, 72, 78, 255), width=lw)
        col = (48, 209, 88, 255) if (charging or pct > 20) else RED
        if pct > 0:
            d.arc(box, start=-90, end=-90 + 360 * pct / 100, fill=col, width=lw)
            c, r = size * ss / 2, (size * ss - lw) / 2
            for deg in (-90, -90 + 360 * pct / 100):
                a = math.radians(deg)
                x, y = c + r * math.cos(a), c + r * math.sin(a)
                d.ellipse((x - lw / 2, y - lw / 2, x + lw / 2, y + lw / 2), fill=col)
        draw_text(big, (size * ss / 2, size * ss / 2), "\uEA93" if charging else "\uE7F8",
                  font("SegoeIcons.ttf", size * ss * 0.3), WHITE, "mm")
        blit(card, big.resize((size, size), LANCZOS), (self.w - size) / 2, round(14 * k))
        label = f"{pct}%" if bat else tr("adapter")
        draw_text(card, (self.w / 2, self.h - round(30 * k)), ar(label), font("seguisb.ttf", round(17 * k)), WHITE, "mm")
        sub = (tr("charging") if charging else tr("on_battery")) if bat else tr("this_pc")
        draw_text(card, (self.w / 2, self.h - round(13 * k)), sub, font("segoeui.ttf", round(11 * k)), DIM, "mm")


class System(Widget):
    kind, title_key, glyph = "system", "system", "E9D9"
    sizes = ("small", "medium")
    every = 3
    link = ["taskmgr.exe"]

    def setup(self):
        self.cpu = CPU()

    def values(self):
        try:
            du = shutil.disk_usage("C:\\")
            disk = round(100 * du.used / du.total)
        except OSError:
            disk = 0
        return [(tr("cpu"), self.cpu.percent(), (10, 132, 255, 255)),
                (tr("memory"), memory_percent(), (48, 209, 88, 255)),
                (tr("disk"), disk, ORANGE)]

    def draw(self, card):
        k, pad = self.k, self.pad
        rows = self.values()
        if self.size == "medium":
            cw = (self.w - 2 * pad) / 3
            size = round(min(cw - 12 * k, self.h * 0.58))
            for i, (label, val, col) in enumerate(reversed(rows) if rtl() else rows):
                cx = pad + cw * (i + 0.5)
                ss = 3
                big = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
                d = ImageDraw.Draw(big)
                lw = round(7 * k) * ss
                box = (lw / 2, lw / 2, size * ss - lw / 2, size * ss - lw / 2)
                d.ellipse(box, outline=(72, 72, 78, 255), width=lw)
                if val > 0:
                    d.arc(box, start=-90, end=-90 + 360 * val / 100, fill=col, width=lw)
                draw_text(big, (size * ss / 2, size * ss / 2), f"{val}%", font("seguisb.ttf", size * ss * 0.24), WHITE, "mm")
                blit(card, big.resize((size, size), LANCZOS), cx - size / 2, pad)
                draw_text(card, (cx, self.h - pad - round(4 * k)), label, font("seguisb.ttf", round(12 * k)), DIM, "mm")
            return
        step = (self.h - 2 * pad) / 3
        bw, bh = self.w - 2 * pad, round(7 * k)
        fl = font("seguisb.ttf", round(12 * k))
        for i, (label, val, col) in enumerate(rows):
            y = pad + step * i + round(9 * k)
            draw_text(card, (self.tx(pad), y), label, fl, DIM, "rm" if rtl() else "lm")
            self.text(card, self.w - pad, y, f"{val}%", fl, align="end")
            blit(card, aa_round(bw, bh, bh / 2, (72, 72, 78, 255)), pad, y + round(13 * k))
            if val > 0:
                fw = max(bh, bw * val / 100)
                blit(card, aa_round(fw, bh, bh / 2, col), self.bx(pad, fw), y + round(13 * k))


class Notes(Widget):
    kind, title_key, glyph = "notes", "notes", "E70B"
    sizes = ("small", "medium", "large")
    every = 4

    def setup(self):
        self.path = Path(self.config.get("file") or NOTES_FILE)
        if not self.path.exists():
            try:
                self.path.write_text("اكتب ملاحظاتك هنا…\nاضغط على الأداة عشان تعدلها." if rtl() else
                                     "Write your notes here…\nClick the widget to edit them.", encoding="utf-8")
            except OSError:
                pass
        self.stamp = None

    def tick(self):
        try:
            stamp = self.path.stat().st_mtime
        except OSError:
            stamp = None
        if stamp != self.stamp:
            self.stamp = stamp
            self.render()
        self.schedule()

    def card(self):
        return vgrad(self.w, self.h, (44, 42, 36, 255), (30, 29, 26, 255))

    def draw(self, card):
        k, pad = self.k, self.pad
        self.text(card, pad, pad + round(8 * k), tr("notes"), font("segoeuib.ttf", round(13 * k)), (255, 204, 0, 255))
        try:
            body = self.path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            body = ""
        f = font("segoeui.ttf", round(12.5 * k))
        lh = round(18 * k)
        max_lines = int((self.h - pad * 2 - round(26 * k)) / lh)
        for i, line in enumerate(wrap(body, f, self.w - 2 * pad, max_lines)):
            self.text(card, pad, pad + round(32 * k) + i * lh, line, f, (235, 235, 230, 255))

    def click(self, x, y):
        os.startfile(str(self.path))


IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class Photos(Widget):
    kind, title_key, glyph = "photos", "photos", "E91B"
    sizes = ("small", "medium", "large")
    every = 1800

    def setup(self):
        self.current, self.image = None, None
        self.pick()

    def folder(self):
        return Path(self.config.get("folder") or Path(os.environ.get("USERPROFILE", "")) / "Pictures")

    def pick(self):
        files = []
        root = self.folder()
        if root.is_dir():
            for p in root.rglob("*"):
                if p.suffix.lower() in IMAGE_EXT:
                    files.append(p)
                    if len(files) >= 400:
                        break
        random.shuffle(files)
        for f in files[:5]:
            try:
                im = Image.open(f)
                im.draft("RGB", (self.w * 2, self.h * 2))
                self.image = ImageOps.fit(im.convert("RGB"), (self.w, self.h), LANCZOS)
                self.current = f
                return
            except Exception:
                continue
        self.image, self.current = None, None

    def tick(self):
        self.pick()
        self.bg = None
        super().tick()

    def card(self):
        return self.image.convert("RGBA") if self.image else super().card()

    def draw(self, card):
        if not self.image:
            draw_text(card, (self.w / 2, self.h / 2 - round(10 * self.k)), "\uE91B",
                      font("SegoeIcons.ttf", round(28 * self.k)), DIM, "mm")
            self.text(card, self.w / 2, self.h / 2 + round(22 * self.k), tr("photos"),
                      font("seguisb.ttf", round(12 * self.k)), DIM, align="center")

    def click(self, x, y):
        os.startfile(str(self.current or self.folder()))

    def menu_entries(self):
        return [(ar("صورة أخرى") if rtl() else "Next Photo", lambda: (self.pick(), setattr(self, "bg", None), self.render())),
                (ar("اختيار مجلد…") if rtl() else "Choose Folder…", self.choose)]

    def choose(self):
        from tkinter import filedialog
        path = filedialog.askdirectory(initialdir=str(self.folder()))
        if path:
            self.config["folder"] = path
            self.host.save()
            self.pick()
            self.bg = None
            self.render()


class Countdown(Widget):
    kind, title_key, glyph = "countdown", "countdown", "E916"
    every = 600

    def target(self):
        t = time.localtime()
        date = self.config.get("date") or f"{t.tm_year}-12-31"
        try:
            y, m, d = map(int, date.split("-"))
            return y, m, d
        except ValueError:
            return t.tm_year, 12, 31

    def draw(self, card):
        k, pad = self.k, self.pad
        y, m, d = self.target()
        days = max(0, int((time.mktime((y, m, d, 0, 0, 0, 0, 0, -1)) - time.time()) // 86400 + 1))
        title = self.config.get("title") or ("نهاية السنة" if rtl() else "End of Year")
        self.text(card, pad, pad + round(8 * k), title, font("segoeuib.ttf", round(13 * k)), ORANGE)
        self.text(card, pad - round(2 * k), pad + round(22 * k), days, font("segoeuil.ttf", round(54 * k)), v="a")
        self.text(card, pad, self.h - pad - round(24 * k), tr("days"), font("seguisb.ttf", round(13 * k)))
        self.text(card, pad, self.h - pad - round(6 * k), f"{d} {MONTHS[lang()][m - 1]} {y}",
                  font("segoeui.ttf", round(11 * k)), DIM)

    def menu_entries(self):
        return [(tr("edit_widget"), self.edit)]

    def edit(self):
        from tkinter import simpledialog
        ask_title, ask_date = (("العنوان:", "التاريخ (YYYY-MM-DD):") if rtl() else ("Title:", "Date (YYYY-MM-DD):"))
        title = simpledialog.askstring("Countdown", ask_title, initialvalue=self.config.get("title", ""))
        date = simpledialog.askstring("Countdown", ask_date, initialvalue="-".join(map(str, self.target())))
        if title is not None:
            self.config["title"] = title
        if date:
            self.config["date"] = date
        self.host.save()
        self.render()


class AppsWidget(Widget):
    kind, title_key, glyph = "shortcuts", "shortcuts", "E71D"
    sizes = ("small", "medium")
    every = 3600

    def apps(self):
        if self.config.get("apps"):
            return self.config["apps"]
        pinned, _ = load_apps()
        return [{k: v for k, v in a.items() if k != "_i"} for a in pinned[1:9]]

    def cells(self):
        n = 4 if self.size == "small" else 8
        cols = 2 if self.size == "small" else 4
        apps = self.apps()[:n]
        cw, ch = (self.w - 2 * self.pad) / cols, (self.h - 2 * self.pad) / 2
        for i, spec in enumerate(apps):
            r, c = divmod(i, cols)
            if rtl():
                c = cols - 1 - c
            yield spec, self.pad + c * cw, self.pad + r * ch, cw, ch

    def draw(self, card):
        k = self.k
        from settings import app_name
        for spec, x, y, cw, ch in self.cells():
            px = round(min(cw, ch) * 0.78)
            icon = self.host.ui.icons.get(spec, px)
            blit(card, icon, x + (cw - px) / 2, y + (ch - px) / 2 - round(6 * k))
            if self.size == "medium":
                draw_text(card, (x + cw / 2, y + ch - round(8 * k)), app_name(spec)[:14],
                          font("segoeui.ttf", round(10.5 * k)), (230, 230, 235, 255), "mm")

    def click(self, x, y):
        for spec, cx, cy, cw, ch in self.cells():
            if cx <= x < cx + cw and cy <= y < cy + ch:
                open_target(spec.get("open") or [spec.get("exe", "")])
                return


# ── أدوات المستخدم (ملفات JSON داخل widgets_custom) ──

class CustomWidget(Widget):
    kind, title_key, glyph = "custom", "custom", "E70F"
    spec = {}

    def setup(self):
        self.output = None
        self.running = False
        self.every = max(5, int(self.spec.get("interval", 60)))
        if self.spec.get("type") == "command":
            self.run_command()

    def run_command(self):
        if self.running:
            return
        self.running = True

        def work():
            try:
                r = subprocess.run(self.spec["command"], shell=True, capture_output=True, timeout=20,
                                   creationflags=NO_WINDOW)
                raw = r.stdout or r.stderr
                for enc in ("utf-8", "cp1256", "cp437"):
                    try:
                        self.output = raw.decode(enc).strip()
                        break
                    except UnicodeDecodeError:
                        continue
            except Exception as e:
                self.output = f"⚠ {e}"
            self.running = False

        threading.Thread(target=work, daemon=True).start()

    def tick(self):
        if self.spec.get("type") == "command":
            self.run_command()
            if self.alive:
                self.surface.win.after(2500, self.render)
        super().tick()

    def card(self):
        if self.spec.get("image") and Path(self.spec["image"]).exists():
            try:
                return ImageOps.fit(Image.open(self.spec["image"]).convert("RGB"), (self.w, self.h), LANCZOS).convert("RGBA")
            except Exception:
                pass
        if self.spec.get("color"):
            c = self.spec["color"].lstrip("#")
            base = tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
            return vgrad(self.w, self.h, base + (255,), tuple(int(v * 0.7) for v in base) + (255,))
        return super().card()

    def draw(self, card):
        k, pad = self.k, self.pad
        sp = self.spec
        if sp.get("title"):
            self.text(card, pad, pad + round(8 * k), sp["title"], font("segoeuib.ttf", round(13 * k)),
                      tuple(int(sp.get("title_color", "#ffcc00").lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) + (255,))
        body = self.output if sp.get("type") == "command" else sp.get("text", "")
        if body is None:
            body = tr("loading")
        big = sp.get("big", False)
        f = font("segoeuil.ttf" if big else "segoeui.ttf", round((30 if big else 12.5) * k))
        lh = round((36 if big else 18) * k)
        top = pad + round(32 * k)
        max_lines = max(1, int((self.h - top - pad + lh * 0.5) / lh))
        for i, line in enumerate(wrap(body, f, self.w - 2 * pad, max_lines)):
            self.text(card, pad, top + i * lh, line, f, (240, 240, 244, 255))

    def click(self, x, y):
        if self.spec.get("link"):
            open_target([self.spec["link"]])


TYPES = {c.kind: c for c in (Clock, Calendar, Weather, Battery, System, Notes, Photos, Countdown, AppsWidget)}

README = """# Your own widgets

Any `.json` file in this folder shows up in **Edit Widgets…** and can be added to the desktop.

## Format
```json
{
  "title": "Widget title",
  "type": "text",
  "text": "Any text you like (Arabic works too)",
  "size": "small",
  "color": "#5e5ce6",
  "link": "https://www.example.com"
}
```

- **type**: `text` (static text) or `command` (runs a command and shows its output).
- **command**: the command to run, e.g. `powershell -NoProfile -Command "Get-Date -Format HH:mm"`.
  It refreshes every `interval` seconds.
- **size**: `small`, `medium` or `large`. You can also write `"sizes": ["small", "medium"]`.
- **color**: background color (optional). Without it the widget uses Liquid Glass.
- **image**: path to an image used as the background (optional).
- **link**: opened when the widget is clicked (a URL, file or program).
- **big**: `true` uses a large font (good for numbers).

## For developers
A `.py` file with a class that inherits from `widgets.Widget` and defines `kind` and `draw(self, card)`
is registered automatically. See `example_plugin.py.example`.
"""

EXAMPLES = {
    "reminder.json": {"title": "Reminder", "type": "text", "text": "Drink some water and take a break every hour.",
                      "size": "small", "color": "#0a84ff"},
    "ip_address.json": {"title": "IP Address", "type": "command", "big": False, "size": "small", "interval": 300,
                      "command": "powershell -NoProfile -Command \"(Get-NetIPAddress -AddressFamily IPv4 | "
                                 "Where-Object { $_.InterfaceAlias -notmatch 'Loopback' -and $_.IPAddress -notmatch '^169' } "
                                 "| Select-Object -First 1).IPAddress\""},
}

PLUGIN_EXAMPLE = '''from widgets import Widget, WHITE
from macui import font, draw_text


class Hello(Widget):
    kind = "hello"
    title_key = "مرحبا"
    sizes = ("small",)
    every = 60

    def draw(self, card):
        draw_text(card, (self.w / 2, self.h / 2), "Hello!", font("segoeuib.ttf", 28), WHITE, "mm")
'''


def load_custom():
    """يحمّل أدوات المستخدم: ملفات JSON وإضافات بايثون."""
    try:
        if not CUSTOM_DIR.exists():
            CUSTOM_DIR.mkdir()
            (CUSTOM_DIR / "README.md").write_text(README, encoding="utf-8")
            (CUSTOM_DIR / "example_plugin.py.example").write_text(PLUGIN_EXAMPLE, encoding="utf-8")
            for name, data in EXAMPLES.items():
                (CUSTOM_DIR / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        return
    for f in sorted(CUSTOM_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sizes = tuple(s for s in (data.get("sizes") or [data.get("size", "small")]) if s in SIZES) or ("small",)
        kind = "custom:" + f.stem
        TYPES[kind] = type("Custom_" + str(abs(hash(kind))), (CustomWidget,),
                           {"kind": kind, "title_key": data.get("title") or f.stem, "spec": data, "sizes": sizes})
    for f in sorted(CUSTOM_DIR.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location("widget_" + f.stem, f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for obj in vars(mod).values():
                if isinstance(obj, type) and issubclass(obj, Widget) and obj is not Widget and getattr(obj, "kind", ""):
                    TYPES[obj.kind] = obj
        except Exception:
            continue


# ───────────────────────────── معرض الأدوات ─────────────────────────────

class Gallery:
    """«تعديل الأدوات»: قائمة الأدوات يسار، ومعاينات الأحجام يمين، والضغط يضيف للسطح."""

    def __init__(self, host):
        self.host, self.ui = host, host.ui
        mon = host.mon
        self.k = k = mon.k
        self.kinds = list(TYPES)
        self.sel = 0
        self.side = round(210 * k)
        self.w = min(mon.w - round(80 * k), round(1000 * k))
        self.h = round(470 * k)
        self.m = round(24 * k)
        x = mon.x + (mon.w - self.w) // 2
        y = mon.y + mon.h - self.h - host.bottom - round(30 * k)
        self.x, self.y = x, y
        self.backdrop = Backdrop(self.ui.root)
        self.surface = Surface(self.ui.root, x - self.m, y - self.m, self.w + 2 * self.m, self.h + 2 * self.m)
        self.backdrop.own(self.surface)
        d = glass_inset(round(26 * k), k)
        self.backdrop.place(x + d, y + d, self.w - 2 * d, self.h - 2 * d)
        self.shadow, self.spad = soft_shadow(self.w, self.h, round(26 * k), round(18 * k), 0.5)
        self.previews = {}
        self.regions = []
        self.alive = True
        self.kind = "gallery"
        self.surface.win.bind("<ButtonRelease-1>", self.on_click)
        self.surface.win.bind("<MouseWheel>", self.on_wheel)
        self.scroll = 0
        self.render()

    def preview(self, kind, size):
        key = (kind, size)
        if key not in self.previews:
            try:
                w = TYPES[kind](self.host, {"type": kind, "size": size, "dx": 0, "dy": self.host.top}, preview=True)
                card = w.compose()
                card.putalpha(ImageChops.multiply(card.getchannel("A"), aa_round(w.w, w.h, w.r, WHITE).getchannel("A")))
                self.previews[key] = card
            except Exception:
                self.previews[key] = None
        return self.previews[key]

    def render(self):
        k = self.k
        img = Image.new("RGBA", (self.w + 2 * self.m, self.h + 2 * self.m), (0, 0, 0, 0))
        blit(img, self.shadow, self.m - self.spad, self.m - self.spad + round(6 * k))
        card = glass_card(self.w, self.h, round(26 * k), k, (30, 30, 36), rim=220, center=150).copy()
        self.regions = []
        R = rtl()
        X = (lambda x, w=0: self.w - x - w) if R else (lambda x, w=0: x)
        # الشريط الجانبي
        side = self.side
        sb = aa_round(side, self.h, round(26 * k), (255, 255, 255, 14))
        blit(card, sb, X(0, side), 0)
        draw_text(card, (X(round(20 * k)), round(30 * k)), tr("widget_gallery"), font("segoeuib.ttf", round(17 * k)),
                  WHITE, "rm" if R else "lm")
        row, y = round(34 * k), round(58 * k)
        fl = font("segoeui.ttf", round(13 * k))
        for i, kind in enumerate(self.kinds):
            cls = TYPES[kind]
            if i == self.sel:
                blit(card, aa_round(side - round(20 * k), row, round(8 * k), (10, 132, 255, 255)),
                     X(round(10 * k), side - round(20 * k)), y)
            ic = round(22 * k)
            badge = aa_round(ic, ic, round(6 * k), (255, 255, 255, 40))
            draw_text(badge, (ic / 2, ic / 2), chr(int(cls.glyph, 16)), font("SegoeIcons.ttf", round(12 * k)), WHITE, "mm")
            blit(card, badge, X(round(18 * k), ic), y + (row - ic) / 2)
            name = tr(cls.title_key) if cls.title_key in STRINGS else ar(cls.title_key)
            draw_text(card, (X(round(48 * k)), y + row / 2), name, fl, WHITE, "rm" if R else "lm")
            self.regions.append((X(0, side), y, X(0, side) + side, y + row, "kind", i))
            y += row
            if y > self.h - round(80 * k):
                break
        # زر «أضف أداة خاصة فيك»
        by = self.h - round(52 * k)
        add_w = side - round(20 * k)
        btn = aa_round(add_w, round(30 * k), round(15 * k), (255, 255, 255, 34))
        draw_text(btn, (add_w / 2, round(15 * k)), tr("add_your_own"), font("segoeui.ttf", round(11.5 * k)), WHITE, "mm")
        blit(card, btn, X(round(10 * k), add_w), by)
        self.regions.append((X(round(10 * k), add_w), by, X(round(10 * k), add_w) + add_w, by + round(30 * k), "custom", 0))
        # المعاينات
        kind = self.kinds[self.sel]
        cls = TYPES[kind]
        area_x = side + round(30 * k)
        title = tr(cls.title_key) if cls.title_key in STRINGS else ar(cls.title_key)
        draw_text(card, (X(area_x), round(34 * k)), title, font("segoeuib.ttf", round(20 * k)), WHITE, "rm" if R else "lm")
        hint = ar("اضغط على الحجم اللي تبيه عشان يضاف لسطح المكتب") if R else "Click a size to add it to your desktop"
        draw_text(card, (X(area_x), round(58 * k)), hint, font("segoeui.ttf", round(12 * k)), DIM, "rm" if R else "lm")
        scale = 0.78
        x, top = area_x, round(88 * k)
        for size in cls.sizes:
            pv = self.preview(kind, size)
            if pv is None:
                continue
            pw, ph = int(pv.width * scale), int(pv.height * scale)
            if x + pw > self.w - round(20 * k):
                break
            small = pv.resize((pw, ph), LANCZOS)
            blit(card, small, X(x, pw), top)
            draw_text(card, (X(x, pw) + pw / 2, top + ph + round(18 * k)), tr(size), font("segoeui.ttf", round(12 * k)),
                      DIM, "mm")
            plus = round(26 * k)
            pb = aa_round(plus, plus, plus / 2, (10, 132, 255, 255))
            draw_text(pb, (plus / 2, plus / 2), "+", font("segoeuib.ttf", round(18 * k)), WHITE, "mm")
            blit(card, pb, X(x, pw) + (pw - plus if not R else 0) + (plus * 0.3 if not R else -plus * 0.3), top - plus * 0.3)
            self.regions.append((X(x, pw), top, X(x, pw) + pw, top + ph, "add", size))
            x += pw + round(28 * k)
        # زر «تم»
        dw, dh = round(90 * k), round(32 * k)
        done = aa_round(dw, dh, dh / 2, (10, 132, 255, 255))
        draw_text(done, (dw / 2, dh / 2), tr("done"), font("seguisb.ttf", round(13 * k)), WHITE, "mm")
        dx = X(self.w - dw - round(20 * k), dw)
        blit(card, done, dx, self.h - dh - round(18 * k))
        self.regions.append((dx, self.h - dh - round(18 * k), dx + dw, self.h - round(18 * k), "done", 0))
        blit(img, card, self.m, self.m)
        self.surface.show(img)

    def on_wheel(self, e):
        self.sel = max(0, min(len(self.kinds) - 1, self.sel + (1 if e.delta < 0 else -1)))
        self.render()

    def on_click(self, e):
        x, y = e.x - self.m, e.y - self.m
        for x0, y0, x1, y1, what, val in self.regions:
            if x0 <= x <= x1 and y0 <= y <= y1:
                if what == "kind":
                    self.sel = val
                    self.render()
                elif what == "add":
                    self.host.add(self.kinds[self.sel], val)
                elif what == "custom":
                    os.startfile(str(CUSTOM_DIR))
                elif what == "done":
                    self.close()
                return

    def close(self):
        if not self.alive:
            return
        self.alive = False
        self.surface.destroy()
        self.backdrop.destroy()
        self.host.set_editing(False)
        self.ui.closed(self)


# ───────────────────────────── مدير الأدوات ─────────────────────────────

class Widgets:
    def __init__(self, ui, mon, top, bottom):
        self.ui, self.mon = ui, mon
        k = mon.k
        self.top, self.bottom = top, bottom
        self.u, self.gap = round(164 * k), round(16 * k)
        load_custom()
        self.cfg = self.load()
        self.visible = self.cfg.get("visible", True)
        self.weather, self.weather_error = None, None
        self.editing = False
        self.gallery = None
        self.items = []
        if self.visible:
            self.create()
        self.stop = threading.Event()
        threading.Thread(target=self.weather_loop, daemon=True).start()

    def defaults(self):
        k = self.mon.k
        u, g = self.u, self.gap
        order = [("clock", "small"), ("calendar", "medium"), ("weather", "small"), ("battery", "small"),
                 ("system", "small")]
        total = sum(SIZES[s][0] for _, s in order) * (u + g) - g
        x = self.mon.w - total - round(26 * k)
        y = self.mon.h - self.bottom - u - round(18 * k)
        out = []
        for kind, size in order:
            out.append({"type": kind, "size": size, "dx": x, "dy": y})
            x += SIZES[size][0] * (u + g)
        return out

    def load(self):
        try:
            cfg = json.loads(WIDGETS_FILE.read_text(encoding="utf-8"))
            if isinstance(cfg, dict) and isinstance(cfg.get("items"), list):
                return cfg
        except (OSError, ValueError):
            pass
        return {"version": 2, "visible": True, "items": self.defaults()}

    def save(self):
        self.cfg["visible"] = self.visible
        if self.visible:
            self.cfg["items"] = [w.item for w in self.items]
        try:
            WIDGETS_FILE.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def make(self, item):
        cls = TYPES.get(item.get("type"))
        return cls(self, item) if cls else None

    def create(self):
        self.items = [w for w in (self.make(i) for i in self.cfg["items"]) if w]

    def destroy(self):
        for w in self.items:
            w.destroy()
        self.items = []

    def shutdown(self):
        self.stop.set()
        if self.gallery:
            self.gallery.close()
        self.destroy()

    def toggle(self):
        self.visible = not self.visible
        if self.visible:
            self.create()
        else:
            self.destroy()
        self.save()

    def remove(self, w):
        w.destroy()
        if w in self.items:
            self.items.remove(w)
        self.save()

    def resize(self, w, size):
        item = dict(w.item, size=size)
        idx = self.items.index(w)
        w.destroy()
        cols, rows = SIZES[size]
        wd, ht = self.u * cols + self.gap * (cols - 1), self.u * rows + self.gap * (rows - 1)
        item["dx"] = min(item["dx"], self.mon.w - wd)
        item["dy"] = min(item["dy"], self.mon.h - self.bottom - ht)
        self.items[idx] = self.make(item)
        self.save()

    def reset(self):
        self.destroy()
        self.cfg["items"] = self.defaults()
        self.visible = True
        self.create()
        self.save()

    # ── أماكن ──
    def rects(self, skip=None):
        return [(w.dx, w.dy, w.dx + w.w, w.dy + w.h) for w in self.items if w is not skip]

    def free_spot(self, wd, ht):
        """أول مكان فاضي (من اليمين تحت) ما يغطي أداة ثانية."""
        step = self.u + self.gap
        taken = self.rects()
        right = self.mon.w - round(26 * self.mon.k)
        bottom = self.mon.h - self.bottom - round(18 * self.mon.k)
        for row in range(0, 8):
            y = bottom - ht - row * step
            if y < self.top:
                break
            for col in range(0, 12):
                x = right - wd - col * step
                if x < 0:
                    break
                g = self.gap // 2
                if all(x + wd + g <= a or x - g >= c or y + ht + g <= b or y - g >= d for a, b, c, d in taken):
                    return x, y
        return max(0, right - wd), self.top + round(20 * self.mon.k)

    def snap(self, w, dx, dy):
        """يلزق الأداة بحواف الأدوات الثانية (مسافة ثابتة بينها) مثل الماك."""
        thr = round(18 * self.mon.k)
        g = self.gap
        best_x, best_y = dx, dy
        for a, b, c, d in self.rects(skip=w):
            for cand in (a, c + g, a - w.w - g, c - w.w):
                if abs(cand - dx) < thr:
                    best_x = cand
            for cand in (b, d + g, b - w.h - g, d - w.h):
                if abs(cand - dy) < thr:
                    best_y = cand
        return best_x, best_y

    def add(self, kind, size):
        cols, rows = SIZES[size]
        wd, ht = self.u * cols + self.gap * (cols - 1), self.u * rows + self.gap * (rows - 1)
        x, y = self.free_spot(wd, ht)
        if not self.visible:
            self.visible = True
            self.create()
        w = self.make({"type": kind, "size": size, "dx": x, "dy": y})
        if w:
            self.items.append(w)
            if self.editing:
                w.render()
            self.save()

    def set_editing(self, on):
        self.editing = on
        for w in self.items:
            w.render()

    def open_gallery(self):
        if self.gallery and self.gallery.alive:
            return self.gallery
        if not self.visible:
            self.visible = True
            self.create()
        self.set_editing(True)
        self.gallery = Gallery(self)
        return self.gallery

    def attach(self, surface):
        """نخلي الأداة تابعة لسطح المكتب: فوق الخلفية وتحت كل البرامج."""
        progman = user32.FindWindowW("Progman", None)
        if progman:
            user32.SetWindowLongPtrW(surface.hwnd, GWLP_HWNDPARENT, progman)
        user32.SetWindowPos(surface.hwnd, W.HWND(1), 0, 0, 0, 0, 0x1 | 0x2 | 0x10)

    def reattach(self):
        for w in self.items:
            self.attach(w.surface)

    def refresh_bg(self):
        for w in self.items:
            w.bg = None
            w.render()

    def weather_loop(self):
        while not self.stop.is_set():
            try:
                loc = self.cfg.get("location") or locate()
                if not loc:
                    raise OSError("no location")
                if "location" not in self.cfg:
                    self.cfg["location"] = loc
                    self.save()
                self.weather = fetch_weather(loc)
                self.weather_error = None
                wait = 1800
            except Exception as e:
                self.weather_error = str(e) or "error"
                wait = 300
            self.stop.wait(wait)
