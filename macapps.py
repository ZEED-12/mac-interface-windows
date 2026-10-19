"""
macapps.py — Mac-style apps that run inside the interface process (no extra processes):
Calculator, About This Mac, Mac Interface Settings, the full-screen Apps launcher and Force Quit.
"""
import ctypes
import os
import sys
import threading
import time
import winreg
from ctypes import wintypes as W
from pathlib import Path

from PIL import Image, ImageDraw

from arabic import ar
from settings import S as SETTINGS, app_name, rtl, tr
from macui import (Backdrop, dwmapi, glass_card, glass_inset, HERE, LANCZOS, WALLPAPER, Surface, _generic, aa_round, activate, blit, cursor, draw_text,
                   exe_icon, exe_spec, font, glass_overlay, glass_panel, lnk_target, mac_plate, monitors, open_target,
                   save_apps, set_wallpaper, soft_shadow, squircle, stroke, user32, wallpaper_on_screen)

WHITE = (255, 255, 255, 255)
DIM = (160, 160, 168, 255)
BLUE = (10, 132, 255, 255)


def monitor_at_cursor(ui):
    cx, cy = cursor()
    for m in ui.mons:
        if m.x <= cx < m.x + m.w and m.y <= cy < m.y + m.h:
            return m
    return ui.mons[0]


# ───────────────────────────── نافذة تطبيق بستايل الماك ─────────────────────────────

class AppWindow:
    key = ""
    title = ""
    listed = True  # يطلع في الـ Dock كبرنامج مفتوح

    def __init__(self, ui, w, h):
        self.ui = ui
        self.mon = mon = monitor_at_cursor(ui)
        self.k = k = mon.k
        self.w, self.h = int(w), int(h)
        self.m = round(34 * k)
        self.r = round(18 * k)  # macOS 27: نفس الانحناء لكل النوافذ
        x = mon.x + (mon.w - self.w) // 2
        y = mon.y + max(round(60 * k), (mon.h - self.h) // 2 - round(30 * k))
        self.backdrop = Backdrop(ui.root, topmost=False)
        self.surface = Surface(ui.root, x - self.m, y - self.m, self.w + 2 * self.m, self.h + 2 * self.m,
                               topmost=False, app=True)
        self.backdrop.own(self.surface)
        self.hwnd = self.surface.hwnd
        win = self.surface.win
        win.title(self.title)
        self.alive = True
        self.active = True
        self.hover_lights = False
        self.drag = None
        self.press_light = None
        self.shadow = soft_shadow(self.w, self.h, self.r, round(22 * k), 0.55)
        win.bind("<ButtonPress-1>", self._press)
        win.bind("<B1-Motion>", self._motion)
        win.bind("<ButtonRelease-1>", self._release)
        win.bind("<Motion>", self._hover)
        win.bind("<Leave>", lambda e: self._set_hover(False))
        win.bind("<Key>", self.on_key)
        win.bind("<FocusIn>", lambda e: self._set_active(True))
        win.bind("<FocusOut>", lambda e: self._set_active(False))
        self.focus()

    def focus(self):
        activate(self.hwnd)
        self.surface.win.focus_force()

    def X(self, x, w=0):
        return self.w - x - w if rtl() else x

    # ── الإشارات الثلاث (إغلاق، تصغير، تكبير) ──
    def lights(self):
        k = self.k
        r, step, y = round(6.5 * k), round(20 * k), round(20 * k)
        out = []
        for i, kind in enumerate(("close", "min", "zoom")):
            cx = round(20 * k) + i * step
            out.append((self.w - cx if rtl() else cx, y, r, kind))
        return out

    def draw_lights(self, card):
        colors = {"close": (255, 95, 87), "min": (254, 188, 46), "zoom": (40, 200, 64)}
        ss = 4
        for cx, cy, r, kind in self.lights():
            S = r * 2 * ss + 2 * ss
            dot = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            d = ImageDraw.Draw(dot)
            col = colors[kind] if self.active or self.hover_lights else (78, 78, 84)
            if kind == "zoom" and not self.zoomable():
                col = (78, 78, 84)
            d.ellipse((ss, ss, S - ss, S - ss), fill=col + (255,))
            d.ellipse((ss * 2, ss * 2, S - ss * 2, S * 0.55), fill=(255, 255, 255, 60))  # لمعة زجاج
            if self.hover_lights:
                c, q, w = S / 2, S * 0.2, max(ss, int(S * 0.09))
                ink = (90, 20, 20, 255) if kind == "close" else (110, 70, 0, 255) if kind == "min" else (0, 90, 20, 255)
                if kind == "close":
                    d.line([(c - q, c - q), (c + q, c + q)], fill=ink, width=w)
                    d.line([(c - q, c + q), (c + q, c - q)], fill=ink, width=w)
                elif kind == "min":
                    d.line([(c - q, c), (c + q, c)], fill=ink, width=w)
                elif self.zoomable():
                    d.line([(c - q, c), (c + q, c)], fill=ink, width=w)
                    d.line([(c, c - q), (c, c + q)], fill=ink, width=w)
            small = dot.resize((S // ss, S // ss), LANCZOS)
            blit(card, small, cx - small.width / 2, cy - small.height / 2)

    def light_at(self, x, y):
        for cx, cy, r, kind in self.lights():
            if (x - cx) ** 2 + (y - cy) ** 2 <= (r + 3) ** 2:
                return kind
        return None

    def zoomable(self):
        return False

    # ── الرسم ──
    def frame(self, tint=(32, 32, 36, 246)):
        img = Image.new("RGBA", (self.w + 2 * self.m, self.h + 2 * self.m), (0, 0, 0, 0))
        sh, pad = self.shadow
        blit(img, sh, self.m - pad, self.m - pad + round(10 * self.k))
        self.place_backdrop()
        card = glass_card(self.w, self.h, self.r, self.k, tint[:3], rim=235, center=self.glass_center).copy()
        return img, card

    glass_center = 175  # نوافذ التطبيقات: زجاج ملوّن أكثر عشان المحتوى ينقرى

    def place_backdrop(self):
        d = glass_inset(self.r, self.k)
        self.backdrop.place(self.surface.x + self.m + d, self.surface.y + self.m + d, self.w - 2 * d, self.h - 2 * d)

    def present(self, img, card):
        self.draw_lights(card)
        blit(img, card, self.m, self.m)
        self.surface.show(img)

    def render(self):
        pass

    # ── الأحداث ──
    def local(self, e):
        return e.x - self.m, e.y - self.m

    def _set_active(self, on):
        if self.alive and on:
            self.backdrop.show(True)
        if self.alive and on != self.active:
            self.active = on
            self.render()

    def _set_hover(self, on):
        if self.alive and on != self.hover_lights:
            self.hover_lights = on
            self.render()

    def _hover(self, e):
        x, y = self.local(e)
        lights = self.lights()
        x0 = min(c[0] for c in lights) - 12
        x1 = max(c[0] for c in lights) + 12
        self._set_hover(x0 <= x <= x1 and y < round(34 * self.k))
        self.on_hover(x, y)

    def _press(self, e):
        x, y = self.local(e)
        self.press_light = self.light_at(x, y)
        if self.press_light:
            return
        if self.on_press(x, y):
            return
        self.drag = (e.x_root - self.surface.x, e.y_root - self.surface.y)

    def _motion(self, e):
        if self.drag:
            self.surface.move(e.x_root - self.drag[0], e.y_root - self.drag[1])
            self.place_backdrop()

    def _release(self, e):
        x, y = self.local(e)
        if self.press_light:
            kind, self.press_light = self.press_light, None
            if kind == self.light_at(x, y):
                if kind == "close":
                    self.close()
                elif kind == "min":
                    self.backdrop.show(False)
                    user32.ShowWindow(self.hwnd, 6)
            return
        if self.drag:
            self.drag = None
            return
        self.on_release(x, y)

    def on_hover(self, x, y):
        pass

    def on_press(self, x, y):
        return False

    def on_release(self, x, y):
        pass

    def on_key(self, e):
        if e.keysym == "w" and e.state & 0x4:
            self.close()

    def close(self):
        if not self.alive:
            return
        self.alive = False
        self.surface.destroy()
        self.backdrop.destroy()
        self.ui.app_closed(self.key)


# ───────────────────────────── الآلة الحاسبة ─────────────────────────────

OPS = {"÷": "/", "×": "*", "−": "-", "+": "+"}


class Calculator(AppWindow):
    key, title = "calculator", "Calculator"

    def __init__(self, ui):
        k = monitor_at_cursor(ui).k
        self.btn, self.gap, self.side = round(54 * k), round(12 * k), round(16 * k)
        self.top_h, self.disp_h = round(38 * k), round(100 * k)
        w = 4 * self.btn + 3 * self.gap + 2 * self.side
        h = self.top_h + self.disp_h + 5 * self.btn + 4 * self.gap + self.side
        self.tokens, self.history, self.just = [], "", False
        self.pressed = None
        super().__init__(ui, w, h)
        self.render()

    # ── المنطق ──
    @staticmethod
    def is_num(t):
        return t not in OPS

    def current(self):
        nums = [t for t in self.tokens if self.is_num(t)]
        return nums[-1] if nums else "0"

    def input(self, key):
        tk = self.tokens
        if key in "0123456789.":
            if self.just:
                tk.clear()
                self.history, self.just = "", False
            if tk and self.is_num(tk[-1]):
                cur = tk[-1]
                if key == "." and "." in cur:
                    return
                if len(cur.replace("-", "").replace(".", "")) >= 15:
                    return
                tk[-1] = ("0." if key == "." and cur in ("", "-") else
                          key if cur == "0" and key != "." else
                          ("-" + key if cur == "-0" and key != "." else cur + key))
            else:
                tk.append("0." if key == "." else key)
        elif key in OPS:
            if not tk:
                tk.append("0")
            self.just = False
            if not self.is_num(tk[-1]):
                tk[-1] = key
            else:
                tk.append(key)
        elif key == "=":
            self.evaluate()
        elif key == "AC":
            tk.clear()
            self.history, self.just = "", False
        elif key == "⌫":
            if self.just:
                return
            if tk:
                last = tk[-1]
                if self.is_num(last) and len(last) > 1 and last != "-0":
                    tk[-1] = last[:-1]
                    if tk[-1] in ("-", ""):
                        tk.pop()
                else:
                    tk.pop()
        elif key in ("±", "%"):
            if not tk or not self.is_num(tk[-1]):
                tk.append("0")
            cur = tk[-1]
            if key == "±":
                tk[-1] = cur[1:] if cur.startswith("-") else "-" + cur
            else:
                tk[-1] = self.fmt(float(cur) / 100, plain=True)
            self.just = False
        self.render()

    def expression(self, tokens):
        return "".join(f"({t})" if self.is_num(t) and t.startswith("-") else OPS.get(t, t) for t in tokens)

    def evaluate(self):
        from controlcenter import calc
        tk = list(self.tokens)
        while tk and not self.is_num(tk[-1]):
            tk.pop()
        if len(tk) < 2:
            return
        expr = self.expression(tk) + "+0"
        value = calc(expr)
        self.history = "".join(tk)
        if value is None:
            self.tokens = []
            self.history = "خطأ" if rtl() else "Error"
        else:
            self.tokens = [value.replace(",", "")]
        self.just = True

    @staticmethod
    def fmt(v, plain=False):
        if abs(v) >= 1e15 or (v and abs(v) < 1e-9):
            return f"{v:.6g}"
        s = f"{v:.10f}".rstrip("0").rstrip(".")
        return s if plain else s

    def display(self):
        cur = self.current()
        neg = cur.startswith("-")
        body = cur.lstrip("-")
        whole, _, frac = body.partition(".")
        try:
            whole = f"{int(whole or 0):,}"
        except ValueError:
            pass
        return ("-" if neg else "") + whole + ("." + frac if "." in body else "")

    # ── الأزرار ──
    def buttons(self):
        top_left = "⌫" if self.tokens and not self.just else "AC"
        rows = [[top_left, "±", "%", "÷"], ["7", "8", "9", "×"], ["4", "5", "6", "−"], ["1", "2", "3", "+"],
                ["sci", "0", ".", "="]]
        y = self.top_h + self.disp_h
        for r, row in enumerate(rows):
            for c, label in enumerate(row):
                x = self.side + c * (self.btn + self.gap)
                yield label, x, y + r * (self.btn + self.gap)

    def button_at(self, x, y):
        for label, bx, by in self.buttons():
            if bx <= x <= bx + self.btn and by <= y <= by + self.btn:
                return label
        return None

    def render(self):
        if not self.alive:
            return
        k = self.k
        img, card = self.frame((22, 22, 24, 248))
        # الشاشة: العملية بالرمادي فوق، والرقم الكبير تحت
        right = self.w - self.side - round(6 * k)
        expr = "".join(self.tokens) if not self.just else self.history
        if expr:
            fe = font("segoeui.ttf", round(18 * k))
            while fe.getlength(expr) > self.w - 2 * self.side and len(expr) > 4:
                expr = expr[1:]
            draw_text(card, (right, self.top_h + round(22 * k)), expr, fe, (150, 150, 156, 255), "rm")
        text = self.display() if self.history not in ("Error", "خطأ") else ar(self.history)
        size = 56
        f = font("segoeuil.ttf", round(size * k))
        while f.getlength(text) > self.w - 2 * self.side and size > 22:
            size -= 2
            f = font("segoeuil.ttf", round(size * k))
        draw_text(card, (right, self.top_h + self.disp_h - round(26 * k)), text, f, WHITE, "rm")
        # الأزرار (دوائر بزجاج سائل)
        for label, bx, by in self.buttons():
            if label in OPS or label == "=":
                col = (255, 159, 10)
            elif label in ("AC", "⌫", "±", "%"):
                col = (92, 92, 96)
            else:
                col = (51, 51, 54)
            if label == self.pressed:
                col = tuple(min(255, int(v * 1.35 + 30)) for v in col)
            b = aa_round(self.btn, self.btn, self.btn / 2, col + (255,))
            b.alpha_composite(glass_overlay(self.btn, self.btn, self.btn // 2, top=120, bottom=20, sheen=26))
            fb = font("segoeui.ttf", round(26 * k))
            if label == "sci":
                draw_text(b, (self.btn / 2, self.btn / 2), "", font("SegoeIcons.ttf", round(19 * k)), WHITE, "mm")
            elif label == "⌫":
                draw_text(b, (self.btn / 2, self.btn / 2), "", font("SegoeIcons.ttf", round(19 * k)), WHITE, "mm")
            else:
                fnt = font("segoeui.ttf", round(30 * k)) if label in OPS or label == "=" else \
                    font("segoeui.ttf", round(20 * k)) if label in ("AC", "±", "%") else fb
                draw_text(b, (self.btn / 2, self.btn / 2 - round(1 * k)), label, fnt, WHITE, "mm")
            blit(card, b, bx, by)
        self.present(img, card)

    def on_press(self, x, y):
        label = self.button_at(x, y)
        if label:
            self.pressed = label
            self.render()
            return True
        return False

    def on_release(self, x, y):
        label, self.pressed = self.pressed, None
        if label and label == self.button_at(x, y):
            if label == "sci":
                open_target(["calc.exe"])  # الحاسبة العلمية حقت ويندوز
                self.render()
                return
            self.input(label)
        else:
            self.render()

    def on_key(self, e):
        super().on_key(e)
        ch = e.char.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789."))
        ks = e.keysym
        if e.state & 0x4 and ks.lower() == "c":
            self.ui.root.clipboard_clear()
            self.ui.root.clipboard_append(self.current())
            return
        key = {"+": "+", "-": "−", "*": "×", "x": "×", "/": "÷", "=": "=", "%": "%", ",": "."}.get(ch, ch)
        if ks in ("Return", "KP_Enter"):
            key = "="
        elif ks == "BackSpace":
            key = "⌫"
        elif ks in ("Escape", "Delete"):
            key = "AC"
        if key and (key in "0123456789." or key in OPS or key in ("=", "⌫", "AC", "%")):
            self.input(key)


# ───────────────────────────── حول هذا الماك ─────────────────────────────

class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", W.DWORD), ("DeviceName", ctypes.c_wchar * 32), ("DeviceString", ctypes.c_wchar * 128),
                ("StateFlags", W.DWORD), ("DeviceID", ctypes.c_wchar * 128), ("DeviceKey", ctypes.c_wchar * 128)]


def reg_str(root, path, name):
    try:
        with winreg.OpenKey(root, path) as k:
            return str(winreg.QueryValueEx(k, name)[0]).strip()
    except OSError:
        return ""


def system_info():
    hklm = winreg.HKEY_LOCAL_MACHINE
    cpu = reg_str(hklm, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString")
    maker = reg_str(hklm, r"HARDWARE\DESCRIPTION\System\BIOS", "SystemManufacturer")
    model = reg_str(hklm, r"HARDWARE\DESCRIPTION\System\BIOS", "SystemProductName")
    nt = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    build = reg_str(hklm, nt, "CurrentBuild")
    product = reg_str(hklm, nt, "ProductName")
    if build.isdigit() and int(build) >= 22000:
        product = product.replace("Windows 10", "Windows 11")
    version = f"{product} {reg_str(hklm, nt, 'DisplayVersion')} ({build})"
    from widgets import MEMORYSTATUSEX, kernel32
    m = MEMORYSTATUSEX(dwLength=ctypes.sizeof(MEMORYSTATUSEX))
    kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    gpus = []
    dd = DISPLAY_DEVICEW(cb=ctypes.sizeof(DISPLAY_DEVICEW))
    i = 0
    while ctypes.windll.user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
        if dd.DeviceString and dd.DeviceString not in gpus:
            gpus.append(dd.DeviceString)
        i += 1
    return {"name": model or "PC", "maker": maker, "cpu": " ".join(cpu.split()), "memory": f"{round(m.ullTotalPhys / 1024 ** 3)} GB",
            "gpu": ", ".join(gpus[:2]), "os": version}


class About(AppWindow):
    key, title = "about", "About This Mac"

    def __init__(self, ui):
        k = monitor_at_cursor(ui).k
        self.info = system_info()
        self.btn_rect = None
        super().__init__(ui, round(300 * k), round(470 * k))
        self.render()

    def device(self, w):
        """رسمة لابتوب وشاشتها عليها خلفية الجهاز."""
        k = self.k
        h = int(w * 0.68)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sw, sh = int(w * 0.84), int(h * 0.82)
        sx = (w - sw) // 2
        bezel = aa_round(sw, sh, round(10 * k), (20, 20, 22, 255), (120, 120, 128, 255))
        img.alpha_composite(bezel, (sx, 0))
        try:
            _, wp = wallpaper_on_screen(sw - round(12 * k), sh - round(14 * k))
            scr = wp.convert("RGBA")
            scr.putalpha(aa_round(scr.width, scr.height, round(5 * k), WHITE).getchannel("A"))
            img.alpha_composite(scr, (sx + round(6 * k), round(6 * k)))
        except Exception:
            pass
        base = aa_round(w, h - sh, round(6 * k), (190, 190, 198, 255))
        ImageDraw.Draw(base).rectangle((w * 0.42, 0, w * 0.58, round(3 * k)), fill=(150, 150, 158, 255))
        img.alpha_composite(base, (0, sh))
        return img

    def render(self):
        if not self.alive:
            return
        k = self.k
        img, card = self.frame()
        dev = self.device(round(190 * k))
        blit(card, dev, (self.w - dev.width) / 2, round(46 * k))
        y = round(46 * k) + dev.height + round(26 * k)
        info = self.info
        draw_text(card, (self.w / 2, y), ar(info["name"]), font("segoeuib.ttf", round(21 * k)), WHITE, "mm")
        draw_text(card, (self.w / 2, y + round(24 * k)), ar(info["maker"]), font("segoeui.ttf", round(12 * k)), DIM, "mm")
        y += round(56 * k)
        rows = [(tr("processor"), info["cpu"]), (tr("memory"), info["memory"]), (tr("graphics"), info["gpu"]),
                (tr("serial"), info["os"])]
        fl, fv = font("seguisb.ttf", round(11.5 * k)), font("segoeui.ttf", round(11.5 * k))
        mid = self.w * 0.36
        room = self.w - mid - round(22 * k)
        for label, value in rows:
            value = ar(value)
            while fv.getlength(value) > room and len(value) > 4:
                value = value[:-2].rstrip() + "…"
            if rtl():
                draw_text(card, (self.w - mid + round(8 * k), y), label, fl, WHITE, "lm")
                draw_text(card, (self.w - mid - round(4 * k), y), value, fv, DIM, "rm")
            else:
                draw_text(card, (mid - round(8 * k), y), label, fl, WHITE, "rm")
                draw_text(card, (mid + round(4 * k), y), value, fv, DIM, "lm")
            y += round(21 * k)
        bw, bh = round(120 * k), round(28 * k)
        bx, by = (self.w - bw) / 2, self.h - bh - round(22 * k)
        b = aa_round(bw, bh, bh / 2, (255, 255, 255, 40))
        draw_text(b, (bw / 2, bh / 2), tr("more_info"), font("segoeui.ttf", round(12.5 * k)), WHITE, "mm")
        blit(card, b, bx, by)
        self.btn_rect = (bx, by, bx + bw, by + bh)
        self.present(img, card)

    def on_press(self, x, y):
        x0, y0, x1, y1 = self.btn_rect or (0, 0, -1, -1)
        return x0 <= x <= x1 and y0 <= y <= y1

    def on_release(self, x, y):
        x0, y0, x1, y1 = self.btn_rect or (0, 0, -1, -1)
        if x0 <= x <= x1 and y0 <= y <= y1:
            os.startfile("ms-settings:about")


# ───────────────────────────── إعدادات الواجهة (بستايل إعدادات النظام) ─────────────────────────────

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "MacDesktop")
            return True
    except OSError:
        return False


def set_startup(on):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            exe = Path(sys.executable)
            w = exe.with_name("pythonw.exe")
            winreg.SetValueEx(k, "MacDesktop", 0, winreg.REG_SZ,
                              f'"{w if w.exists() else exe}" "{HERE / "mac.py"}" desktop')
        else:
            try:
                winreg.DeleteValue(k, "MacDesktop")
            except FileNotFoundError:
                pass


SECTIONS = [("general", "E713", (142, 142, 147)), ("appearance", "E790", (40, 40, 44)),
            ("desktop_dock", "E8A1", (10, 132, 255)), ("corners", "E7C4", (175, 82, 222)),
            ("wallpaper", "E91B", (50, 173, 230))]


class Settings(AppWindow):
    key, title = "settings", "Mac Settings"

    def __init__(self, ui):
        k = monitor_at_cursor(ui).k
        self.section = "general"
        self.regions = []
        self.drag_slider = None
        super().__init__(ui, round(760 * k), round(600 * k))
        self.render()

    def zoomable(self):
        return False

    def label(self, key):
        names = {"general": ("General", "عام"), "appearance": ("Appearance", "المظهر"),
                 "desktop_dock": ("Desktop & Dock", "سطح المكتب و Dock"), "wallpaper": ("Wallpaper", "الخلفية"),
                 "corners": ("Hot Corners", "الزوايا النشطة")}
        en, a = names.get(key, (key, key))
        return ar(a) if rtl() else en

    def rows(self):
        S = SETTINGS
        if self.section == "general":
            S = SETTINGS
            return [("seg", tr("language"), "language", [("ar", ar("العربية")), ("en", "English")]),
                    ("toggle", tr("start_with_windows"), "startup", startup_enabled()),
                    ("toggle", tr("opt_win_key"), "win_key_apps", S.get("win_key_apps", True)),
                    ("toggle", tr("opt_switcher"), "mac_switcher", S.get("mac_switcher", True)),
                    ("toggle", tr("opt_volume"), "volume_hud", S.get("volume_hud", True)),
                    ("toggle", tr("opt_quicklook"), "quick_look", S.get("quick_look", True))]
        if self.section == "appearance":
            return [("slider", tr("glass"), "glass", S.get("glass", 0.45), (tr("clear"), tr("tinted")))]
        if self.section == "corners":
            from settings import CORNER_LABELS, CORNER_NAMES
            corners = SETTINGS.get("hot_corners") or {}
            i = 1 if rtl() else 0
            return [("cycle", ar(CORNER_LABELS[c][i]), c, ar(CORNER_NAMES.get(corners.get(c, ""), ("—", "—"))[i]))
                    for c in ("tl", "tr", "bl", "br")]
        if self.section == "desktop_dock":
            return [("slider", tr("dock_size"), "dock_size", (S.get("dock_size", 54) - 40) / 32, ("", "")),
                    ("toggle", tr("magnification"), "magnify", S.get("magnify", True)),
                    ("toggle", tr("show_widgets"), "widgets", self.ui.widgets is not None and self.ui.widgets.visible),
                    ("button", tr("edit_widgets"), "edit_widgets", None)]
        return [("wallpaper", "", "", None),
                ("toggle", ar("خلفية متغيرة (نهار وليل)") if rtl() else "Dynamic (Day & Night)", "dynamic_wp",
                 SETTINGS.get("dynamic_wp", False)),
                ("button", ar("إضافة خلفياتك…") if rtl() else "Add Your Own…", "open_wp_folder", None),
                ("button", ar("اختيار صورة…") if rtl() else "Choose Image…", "choose_wp", None)]

    def render(self):
        if not self.alive:
            return
        k = self.k
        R = rtl()
        img, card = self.frame((30, 30, 34, 248))
        self.regions = []
        side = round(210 * k)
        sb = aa_round(side - round(16 * k), self.h - round(16 * k), round(14 * k), (255, 255, 255, 14))
        blit(card, sb, self.X(round(8 * k), sb.width), round(8 * k))
        y = round(56 * k)
        fl = font("segoeui.ttf", round(13 * k))
        for key, glyph, color in SECTIONS:
            rh = round(32 * k)
            if key == self.section:
                blit(card, aa_round(side - round(32 * k), rh, round(8 * k), BLUE), self.X(round(16 * k), side - round(32 * k)), y)
            ic = round(22 * k)
            badge = aa_round(ic, ic, round(6 * k), color + (255,))
            draw_text(badge, (ic / 2, ic / 2), chr(int(glyph, 16)), font("SegoeIcons.ttf", round(12 * k)), WHITE, "mm")
            blit(card, badge, self.X(round(26 * k), ic), y + (rh - ic) / 2)
            draw_text(card, (self.X(round(56 * k)), y + rh / 2), self.label(key), fl, WHITE, "rm" if R else "lm")
            self.regions.append((self.X(round(16 * k), side - round(32 * k)), y,
                                 self.X(round(16 * k), side - round(32 * k)) + side - round(32 * k), y + rh, "section", key))
            y += rh + round(4 * k)
        # المحتوى
        cx = side + round(24 * k)
        cw = self.w - cx - round(24 * k)
        draw_text(card, (self.X(cx), round(30 * k)), self.label(self.section), font("segoeuib.ttf", round(19 * k)),
                  WHITE, "rm" if R else "lm")
        y = round(66 * k)
        rows = self.rows()
        box_h = sum(self.grid_height() if r[0] == "wallpaper" else round(48 * k) for r in rows)
        box = aa_round(cw, box_h, round(12 * k), (255, 255, 255, 16))
        blit(card, box, self.X(cx, cw), y)
        for i, row in enumerate(rows):
            kind, label, key, value = row[0], row[1], row[2], row[3]
            rh = self.grid_height() if kind == "wallpaper" else round(48 * k)
            mid = y + rh / 2
            if i:
                ImageDraw.Draw(card).line([(self.X(cx + round(14 * k), cw - round(28 * k)), y),
                                           (self.X(cx + round(14 * k), cw - round(28 * k)) + cw - round(28 * k), y)],
                                          fill=(255, 255, 255, 22))
            if label and kind != "button":
                draw_text(card, (self.X(cx + round(16 * k)), mid), label, fl, WHITE, "rm" if R else "lm")
            right = cx + cw - round(16 * k)  # طرف التحكم (منطقي)
            if kind == "toggle":
                tw, th = round(40 * k), round(24 * k)
                tg = aa_round(tw, th, th / 2, (48, 209, 88, 255) if value else (80, 80, 86, 255))
                kn = round(20 * k)
                knob = aa_round(kn, kn, kn / 2, WHITE)
                on_side = (tw - kn - round(2 * k)) if value != R else round(2 * k)
                blit(tg, knob, on_side, round(2 * k))
                tx = self.X(right - tw, tw)
                blit(card, tg, tx, mid - th / 2)
                self.regions.append((tx, mid - th / 2, tx + tw, mid + th / 2, "toggle", key))
            elif kind == "seg":
                opts = value
                sw = round(92 * k) * len(opts)
                sx = self.X(right - sw, sw)
                seg = aa_round(sw, round(26 * k), round(8 * k), (255, 255, 255, 26))
                cur = SETTINGS.get(key)
                ow = sw / len(opts)
                for j, (val, text) in enumerate(opts):
                    jj = len(opts) - 1 - j if R else j
                    if val == cur:
                        seg.alpha_composite(aa_round(ow - round(4 * k), round(22 * k), round(6 * k), (99, 99, 106, 255)),
                                            (int(jj * ow + round(2 * k)), round(2 * k)))
                    draw_text(seg, (jj * ow + ow / 2, round(13 * k)), text, font("segoeui.ttf", round(12 * k)), WHITE, "mm")
                    self.regions.append((sx + jj * ow, mid - round(13 * k), sx + (jj + 1) * ow, mid + round(13 * k),
                                         "seg", (key, val)))
                blit(card, seg, sx, mid - round(13 * k))
            elif kind == "slider":
                sw = round(220 * k)
                sx = self.X(right - sw, sw)
                track = aa_round(sw, round(6 * k), round(3 * k), (255, 255, 255, 40))
                fill_w = max(round(6 * k), sw * value)
                blit(card, track, sx, mid - round(3 * k))
                blit(card, aa_round(fill_w, round(6 * k), round(3 * k), BLUE), sx + (sw - fill_w if R else 0), mid - round(3 * k))
                kn = round(20 * k)
                kx = sx + (sw * (1 - value) if R else sw * value) - kn / 2
                knob = aa_round(kn, kn, kn / 2, WHITE)
                blit(card, knob, kx, mid - kn / 2)
                lo, hi = row[4]
                fs = font("segoeui.ttf", round(10.5 * k))
                if lo:
                    draw_text(card, (sx if not R else sx + sw, mid + round(18 * k)), lo, fs, DIM, "lm" if not R else "rm")
                    draw_text(card, (sx + sw if not R else sx, mid + round(18 * k)), hi, fs, DIM, "rm" if not R else "lm")
                self.regions.append((sx - kn / 2, mid - round(16 * k), sx + sw + kn / 2, mid + round(16 * k), "slider",
                                     (key, sx, sw)))
            elif kind == "cycle":
                bw = round(170 * k)
                bx = self.X(right - bw, bw)
                b = aa_round(bw, round(28 * k), round(8 * k), (255, 255, 255, 30))
                draw_text(b, (bw / 2, round(14 * k)), value, font("segoeui.ttf", round(12 * k)), WHITE, "mm")
                draw_text(b, (round(14 * k) if R else bw - round(14 * k), round(14 * k)), "",
                          font("SegoeIcons.ttf", round(9 * k)), DIM, "mm")
                blit(card, b, bx, mid - round(14 * k))
                self.regions.append((bx, mid - round(14 * k), bx + bw, mid + round(14 * k), "cycle", key))
            elif kind == "button":
                bw = cw - round(32 * k)  # زر بعرض الصف (بدون عنوان مكرر)
                bx = self.X(cx + round(16 * k), bw)
                b = aa_round(bw, round(28 * k), round(14 * k), (255, 255, 255, 34))
                draw_text(b, (bw / 2, round(14 * k)), label, font("segoeui.ttf", round(12 * k)), WHITE, "mm")
                blit(card, b, bx, mid - round(14 * k))
                draw_text(card, (self.X(cx + round(16 * k)), mid), "", fl, WHITE)
                self.regions.append((bx, mid - round(14 * k), bx + bw, mid + round(14 * k), "button", key))
            elif kind == "wallpaper":
                self.draw_grid(card, cx, y, cw)
            y += rh
        self.present(img, card)

    GRID_COLS = 4

    def grid_height(self):
        import wallpapers
        k = self.k
        n = len(wallpapers.available())
        rows = max(1, (n + self.GRID_COLS - 1) // self.GRID_COLS)
        return rows * round(84 * k) + round(16 * k)

    def draw_grid(self, card, cx, y, cw):
        """شبكة الخلفيات (المولّدة + خلفياتك). الحالية عليها إطار أزرق."""
        import wallpapers
        from macui import wallpaper_info
        k = self.k
        current = str(Path(wallpaper_info()[0])).lower().replace("mac_wallpaper_27.png", "mac_wallpaper.jpg")
        gap = round(12 * k)
        tw = int((cw - round(32 * k) - gap * (self.GRID_COLS - 1)) / self.GRID_COLS)
        th = int(tw * 9 / 16)
        for i, path in enumerate(wallpapers.available()):
            r, c = divmod(i, self.GRID_COLS)
            x = cx + round(16 * k) + c * (tw + gap)
            ty = y + round(10 * k) + r * round(84 * k)
            try:
                thumb = wallpapers.thumbnail(path, (tw, th)).copy()
            except Exception:
                continue
            thumb.putalpha(aa_round(tw, th, round(7 * k), WHITE).getchannel("A"))
            ax = self.X(x, tw)
            if str(path).lower() == current or Path(current).stem.lower() == path.stem.lower():
                ring = aa_round(tw + round(6 * k), th + round(6 * k), round(9 * k), BLUE)
                blit(card, ring, ax - round(3 * k), ty - round(3 * k))
            blit(card, thumb, ax, ty)
            name = path.stem if len(path.stem) <= 18 else path.stem[:17] + "…"
            draw_text(card, (ax + tw / 2, ty + th + round(10 * k)), ar(name), font("segoeui.ttf", round(10 * k)), DIM, "mm")
            self.regions.append((ax, ty, ax + tw, ty + th, "wp", str(path)))

    def hit(self, x, y):
        for r in self.regions:
            if r[0] <= x <= r[2] and r[1] <= y <= r[3]:
                return r
        return None

    def on_press(self, x, y):
        r = self.hit(x, y)
        if r and r[4] == "slider":
            self.drag_slider = r[5]
            self.slide(x, False)
            self.surface.win.bind("<B1-Motion>", lambda e: self.slide(e.x - self.m, False))
            return True
        return bool(r)

    def slide(self, x, done):
        key, sx, sw = self.drag_slider
        v = max(0.0, min(1.0, (x - sx) / sw))
        if rtl():
            v = 1 - v
        if key == "dock_size":
            SETTINGS["dock_size"] = int(40 + 32 * v)
        else:
            SETTINGS[key] = round(v, 2)
        self.render()
        if done:
            SETTINGS.save()
            self.ui.apply_settings()

    def on_release(self, x, y):
        if self.drag_slider:
            self.slide(x, True)
            self.drag_slider = None
            self.surface.win.bind("<B1-Motion>", self._motion)
            return
        r = self.hit(x, y)
        if not r:
            return
        what, val = r[4], r[5]
        if what == "section":
            self.section = val
        elif what == "toggle":
            if val == "startup":
                set_startup(not startup_enabled())
            elif val == "widgets":
                self.ui.toggle_widgets()
            elif val == "dynamic_wp":
                SETTINGS["dynamic_wp"] = not SETTINGS.get("dynamic_wp", False)
                SETTINGS.save()
                self.ui.check_dynamic_wallpaper(force=True)
            elif val in ("win_key_apps", "mac_switcher", "volume_hud", "quick_look"):
                SETTINGS[val] = not SETTINGS.get(val, True)  # تطبق فوراً بدون إعادة بناء الواجهة
                SETTINGS.save()
            else:
                SETTINGS[val] = not SETTINGS.get(val, True)
                SETTINGS.save()
                self.ui.apply_settings()
        elif what == "seg":
            key, v = val
            if SETTINGS.get(key) != v:
                SETTINGS[key] = v
                SETTINGS.save()
                self.ui.apply_settings()
        elif what == "cycle":
            from settings import CORNER_ACTIONS
            corners = dict(SETTINGS.get("hot_corners") or {})
            cur = corners.get(val, "")
            corners[val] = CORNER_ACTIONS[(CORNER_ACTIONS.index(cur) + 1) % len(CORNER_ACTIONS)]
            SETTINGS["hot_corners"] = corners
            SETTINGS.save()
        elif what == "wp":
            set_wallpaper(val)
            SETTINGS["wallpaper"] = val
            SETTINGS.save()
            self.ui.root.after(1200, self.render)
        elif what == "button":
            if val == "open_wp_folder":
                import wallpapers
                wallpapers.FOLDER.mkdir(exist_ok=True)
                os.startfile(str(wallpapers.FOLDER))
            if val == "edit_widgets":
                self.ui.open_widget_gallery()
            elif val == "choose_wp":
                from tkinter import filedialog
                path = filedialog.askopenfilename(filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.webp")])
                if path:
                    set_wallpaper(path)
            elif val == "default_wp":
                if WALLPAPER.exists():
                    set_wallpaper(WALLPAPER)
            self.ui.root.after(1500, self.render)
        self.render()


# ───────────────────────────── «التطبيقات» (بدل Launchpad) ─────────────────────────────

class AppsLauncher:
    """شاشة كاملة مغبشة فيها كل التطبيقات مع بحث، مثل Apps في macOS Tahoe."""
    key = "apps"
    listed = False

    def __init__(self, ui, add_mode=False):
        self.ui = ui
        self.mon = mon = monitor_at_cursor(ui)
        self.k = k = mon.k
        self.add_mode = add_mode
        self.query, self.page = "", 0
        self.alive = True
        self.icon_px = round(76 * k)
        self.cols, self.rows = 7, 4
        # تغبيش حي حقيقي لكل الشاشة (البرامج اللي وراها تبان مغبشة)
        self.backdrop = Backdrop(ui.root, rgb=(14, 14, 18))
        self.backdrop.set_tint(70)
        square = ctypes.c_int(1)  # شاشة كاملة: بدون زوايا دائرية
        dwmapi.DwmSetWindowAttribute(self.backdrop.hwnd, 33, ctypes.byref(square), 4)
        self.backdrop.place(mon.x, mon.y, mon.w, mon.h)
        self.bg = Image.new("RGBA", (mon.w, mon.h), (8, 8, 12, 40))
        self.surface = Surface(ui.root, mon.x, mon.y, mon.w, mon.h, activate=True)
        self.backdrop.own(self.surface)
        self.hwnd = self.surface.hwnd
        if not hasattr(ui, "app_icons"):
            ui.app_icons = {}
        self.cells = []
        win = self.surface.win
        win.bind("<Key>", self.on_key)
        win.bind("<ButtonRelease-1>", self.on_click)
        win.bind("<ButtonRelease-3>", self.on_right)
        win.bind("<MouseWheel>", self.on_wheel)
        win.focus_force()
        activate(self.hwnd)
        self.pending = True
        threading.Thread(target=self.load_icons, daemon=True).start()
        self.render()
        self.poll()

    def focus(self):
        activate(self.hwnd)

    def apps(self):
        apps = self.ui.apps or []
        q = self.query.strip().lower()
        if q:
            apps = [a for a in apps if q in a["name"].lower()]
        return sorted(apps, key=lambda a: a["name"].lower())

    def load_icons(self):
        for a in sorted(self.ui.apps or [], key=lambda a: a["name"].lower()):
            if not self.alive:
                return
            self.icon(a)
        self.pending = False

    def icon(self, a, make=True):
        cache = self.ui.app_icons
        if a["path"] in cache:
            return cache[a["path"]]
        if not make:
            return None
        p = a["path"]
        exe = lnk_target(p) if p.lower().endswith(".lnk") else (p if p.lower().endswith(".exe") else None)
        src = exe_icon(exe, 128) if exe else None
        S = self.icon_px * 2
        if src:
            body = mac_plate(src, S)
        else:
            body = _generic(S, {"name": a["name"], "color": "#5e5ce6"}).convert("RGBA")
            body.putalpha(squircle(S))
        cache[p] = body.resize((self.icon_px, self.icon_px), LANCZOS)
        return cache[p]

    def poll(self):
        if not self.alive:
            return
        if self.pending:
            self.render()
            self.surface.win.after(400, self.poll)

    def render(self):
        if not self.alive:
            return
        k, mon = self.k, self.mon
        img = self.bg.copy()
        # البحث
        bw, bh = round(260 * k), round(34 * k)
        bx, by = (mon.w - bw) / 2, round(60 * k)
        box = glass_panel(bw, bh, bh / 2, (255, 255, 255, 40)).copy()
        q = ar(self.query) if self.query else tr("search")
        draw_text(box, (round(30 * k), bh / 2), "", font("SegoeIcons.ttf", round(13 * k)), DIM, "mm")
        draw_text(box, (bw / 2 + round(8 * k), bh / 2), q, font("segoeui.ttf", round(14 * k)),
                  WHITE if self.query else DIM, "mm")
        blit(img, box, bx, by)
        if self.add_mode:
            draw_text(img, (mon.w / 2, by - round(24 * k)),
                      ar("اختر تطبيقًا لإضافته إلى Dock") if rtl() else "Choose an app to add to the Dock",
                      font("seguisb.ttf", round(15 * k)), WHITE, "mm")
        # الشبكة
        apps = self.apps()
        per = self.cols * self.rows
        pages = max(1, (len(apps) + per - 1) // per)
        self.page = min(self.page, pages - 1)
        cw, ch = round(150 * k), round(140 * k)
        gx = (mon.w - cw * self.cols) / 2
        gy = by + bh + round(50 * k)
        fn = font("segoeui.ttf", round(12.5 * k))
        self.cells = []
        for i, a in enumerate(apps[self.page * per:(self.page + 1) * per]):
            r, c = divmod(i, self.cols)
            if rtl():
                c = self.cols - 1 - c
            x, y = gx + c * cw, gy + r * ch
            ic = self.icon(a, make=False)
            if ic is None:
                ph = _generic(self.icon_px, {"name": a["name"], "color": "#48484a"}).convert("RGBA")
                ph.putalpha(squircle(self.icon_px))
                ic = ph
            blit(img, ic, x + (cw - self.icon_px) / 2, y)
            name = a["name"] if len(a["name"]) <= 20 else a["name"][:19] + "…"
            draw_text(img, (x + cw / 2, y + self.icon_px + round(16 * k)), ar(name), fn, WHITE, "mm")
            self.cells.append((x, y, x + cw, y + ch, a))
        # نقاط الصفحات
        if pages > 1:
            dot = round(7 * k)
            total = pages * dot * 2
            for p in range(pages):
                d = aa_round(dot, dot, dot / 2, (255, 255, 255, 230 if p == self.page else 90))
                blit(img, d, (mon.w - total) / 2 + p * dot * 2, mon.h - round(140 * k))
        self.surface.show(img)

    def cell_at(self, x, y):
        for x0, y0, x1, y1, a in self.cells:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return a
        return None

    def add_to_dock(self, a):
        from macui import APPS_FILE, build_default_apps
        import json
        try:
            raw = json.loads(APPS_FILE.read_text(encoding="utf-8"))["apps"]
        except (OSError, ValueError, KeyError):
            raw = build_default_apps()
        p = a["path"]
        exe = lnk_target(p) if p.lower().endswith(".lnk") else None
        spec = dict(exe_spec(exe), open=[p]) if exe else {"name": a["name"], "icon": "", "color": "#5e5ce6", "open": [p]}
        raw.insert(raw.index("sep") if "sep" in raw else len(raw), spec)
        save_apps(raw)
        self.ui.reload_docks()

    def on_click(self, e):
        a = self.cell_at(e.x, e.y)
        if not a:
            self.close()
            return
        if self.add_mode:
            self.add_to_dock(a)
        else:
            open_target([a["path"]])
        self.close()

    def on_right(self, e):
        a = self.cell_at(e.x, e.y)
        if a:
            self.ui.show_popup(self.mon, e.x_root, e.y_root, [
                (tr("open"), lambda: (open_target([a["path"]]), self.close())),
                (tr("keep_dock"), lambda: self.add_to_dock(a))])

    def on_wheel(self, e):
        self.page = max(0, self.page + (1 if e.delta < 0 else -1))
        self.render()

    def on_key(self, e):
        ks = e.keysym
        if ks == "Escape":
            self.close()
        elif ks == "Return":
            apps = self.apps()
            if apps:
                (self.add_to_dock if self.add_mode else lambda a: open_target([a["path"]]))(apps[0])
                self.close()
        elif ks == "BackSpace":
            self.query = self.query[:-1]
            self.page = 0
            self.render()
        elif ks in ("Right", "Next"):
            self.page += 1
            self.render()
        elif ks in ("Left", "Prior"):
            self.page = max(0, self.page - 1)
            self.render()
        elif e.char and e.char.isprintable():
            self.query += e.char
            self.page = 0
            self.render()

    def close(self):
        if not self.alive:
            return
        self.alive = False
        self.surface.destroy()
        self.backdrop.destroy()
        self.ui.app_closed(self.key)


# ───────────────────────────── إنهاء التطبيقات إجبارياً (مثل Cmd+Option+Esc) ─────────────────────────────

kernel32 = ctypes.windll.kernel32
kernel32.OpenProcess.restype = W.HANDLE
kernel32.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
kernel32.CloseHandle.argtypes = [W.HANDLE]


class ForceQuit(AppWindow):
    key, title = "forcequit", "Force Quit Applications"
    listed = False

    def __init__(self, ui):
        k = monitor_at_cursor(ui).k
        self.sel, self.scroll, self.rows_cache = 0, 0, []
        self.row_h = round(34 * k)
        super().__init__(ui, round(440 * k), round(470 * k))
        self.surface.win.bind("<MouseWheel>", self.on_wheel)
        self.refresh()

    def apps(self):
        out = []
        for g in self.ui.groups or []:
            if g["stem"].startswith("mac:") or not g.get("exe"):
                continue
            from macui import exe_spec
            spec = exe_spec(g["exe"])
            if g["stem"] == "explorer":
                spec = {"name": "Finder", "icon": "finder"}
            elif g["stem"] == "applicationframehost":
                spec = {"name": g["title"], "icon": "", "color": "#5e5ce6"}
            out.append((spec, g))
        return out

    def refresh(self):
        if not self.alive:
            return
        self.rows_cache = self.apps()
        self.sel = min(self.sel, max(0, len(self.rows_cache) - 1))
        self.render()
        self.surface.win.after(2000, self.refresh)

    def layout(self):
        k = self.k
        top = round(96 * k)
        bottom = self.h - round(66 * k)
        return top, bottom, max(1, (bottom - top) // self.row_h)

    def render(self):
        if not self.alive:
            return
        k = self.k
        R = rtl()
        img, card = self.frame()
        draw_text(card, (self.w / 2, round(22 * k)), tr("fq_title"), font("seguisb.ttf", round(13 * k)), WHITE, "mm")
        hint = tr("fq_hint")
        draw_text(card, (self.X(round(22 * k)), round(56 * k)), hint, font("segoeui.ttf", round(11.5 * k)), DIM,
                  "rm" if R else "lm")
        top, bottom, visible = self.layout()
        box = aa_round(self.w - round(40 * k), bottom - top + round(8 * k), round(10 * k), (0, 0, 0, 70))
        blit(card, box, round(20 * k), top - round(4 * k))
        from settings import app_name
        rows = self.rows_cache[self.scroll:self.scroll + visible]
        for i, (spec, g) in enumerate(rows):
            idx = self.scroll + i
            y = top + i * self.row_h
            if idx == self.sel:
                blit(card, aa_round(self.w - round(52 * k), self.row_h - round(4 * k), round(7 * k), BLUE),
                     round(26 * k), y + round(2 * k))
            isz = round(22 * k)
            icon = self.ui.icons.get(spec, round(isz * 512 / 432))
            blit(card, icon.resize((isz, isz), LANCZOS), self.X(round(36 * k), isz), y + (self.row_h - isz) / 2)
            draw_text(card, (self.X(round(68 * k)), y + self.row_h / 2), app_name(spec)[:40],
                      font("segoeui.ttf", round(13 * k)), WHITE, "rm" if R else "lm")
        bw, bh = round(130 * k), round(30 * k)
        label = tr("relaunch") if self.selected_is_finder() else tr("fq_button")
        b = aa_round(bw, bh, bh / 2, BLUE if self.rows_cache else (80, 80, 86, 255))
        draw_text(b, (bw / 2, bh / 2), label, font("seguisb.ttf", round(12.5 * k)), WHITE, "mm")
        self.btn = (self.X(self.w - round(20 * k) - bw, bw), self.h - bh - round(20 * k))
        blit(card, b, *self.btn)
        self.btn_size = (bw, bh)
        self.present(img, card)

    def selected_is_finder(self):
        return bool(self.rows_cache) and self.rows_cache[self.sel][1]["stem"] == "explorer"

    def on_press(self, x, y):
        top, bottom, visible = self.layout()
        bx, by = self.btn
        bw, bh = self.btn_size
        if bx <= x <= bx + bw and by <= y <= by + bh:
            return True
        if top <= y < bottom and round(20 * self.k) <= x <= self.w - round(20 * self.k):
            idx = self.scroll + int((y - top) // self.row_h)
            if idx < len(self.rows_cache):
                self.sel = idx
                self.render()
            return True
        return False

    def on_release(self, x, y):
        bx, by = self.btn
        bw, bh = self.btn_size
        if bx <= x <= bx + bw and by <= y <= by + bh and self.rows_cache:
            self.force_quit()

    def on_wheel(self, e):
        _, _, visible = self.layout()
        self.scroll = max(0, min(max(0, len(self.rows_cache) - visible), self.scroll + (1 if e.delta < 0 else -1)))
        self.render()

    def on_key(self, e):
        super().on_key(e)
        if e.keysym in ("Down", "Up") and self.rows_cache:
            self.sel = (self.sel + (1 if e.keysym == "Down" else -1)) % len(self.rows_cache)
            self.render()
        elif e.keysym == "Return" and self.rows_cache:
            self.force_quit()
        elif e.keysym == "Escape":
            self.close()

    def force_quit(self):
        from tkinter import messagebox
        from settings import STRINGS, app_name
        spec, g = self.rows_cache[self.sel]
        if g["stem"] == "explorer":  # مثل الماك: Finder ما ينقفل، يعاد تشغيله
            import subprocess
            subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], capture_output=True, creationflags=0x08000000)
            subprocess.Popen(["explorer.exe"], creationflags=0x00000008)
            return
        name = spec.get("name", "")
        text = STRINGS["fq_confirm"][1 if rtl() else 0].format(name)
        if not messagebox.askyesno(tr("fq_button") if not rtl() else "إنهاء إجباري", text, parent=self.surface.win):
            return
        from macui import window_pid
        for pid in {window_pid(h) for h in g["hwnds"]}:
            h = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
            if h:
                kernel32.TerminateProcess(h, 1)
                kernel32.CloseHandle(h)
        self.ui.root.after(800, self.refresh)


APPS = {"calculator": Calculator, "about": About, "settings": Settings, "apps": AppsLauncher, "forcequit": ForceQuit}
