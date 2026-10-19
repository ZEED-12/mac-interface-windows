"""
overlays.py — things that appear above everything: the app switcher (Alt+Tab like Cmd+Tab),
the volume HUD, and Quick Look (press Space on a file in File Explorer).
"""
import ctypes
import os
import subprocess
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw

from arabic import ar
from settings import app_name, rtl, tr
from macui import (LANCZOS, Backdrop, Surface, activate, blit, draw_text, exe_spec, font, glass_card, glass_inset,
                   icon_body, soft_shadow, aa_round)
from macapps import AppWindow, monitor_at_cursor

WHITE = (255, 255, 255, 255)
DIM = (165, 165, 172, 255)


class GlassOverlay:
    """لوح زجاج حي فوق كل شي، بدون ما ياخذ التركيز."""

    def __init__(self, ui, mon, x, y, w, h, r):
        self.ui, self.mon, self.k = ui, mon, mon.k
        self.x, self.y, self.w, self.h, self.r = int(x), int(y), int(w), int(h), int(r)
        self.m = round(24 * self.k)
        self.backdrop = Backdrop(ui.root)
        self.surface = Surface(ui.root, self.x - self.m, self.y - self.m, self.w + 2 * self.m, self.h + 2 * self.m)
        self.backdrop.own(self.surface)
        d = glass_inset(self.r, self.k)
        self.backdrop.place(self.x + d, self.y + d, self.w - 2 * d, self.h - 2 * d)
        self.shadow = soft_shadow(self.w, self.h, self.r, round(18 * self.k), 0.45)
        self.alive = True

    def frame(self):
        img = Image.new("RGBA", (self.w + 2 * self.m, self.h + 2 * self.m), (0, 0, 0, 0))
        sh, pad = self.shadow
        blit(img, sh, self.m - pad, self.m - pad + round(6 * self.k))
        return img, glass_card(self.w, self.h, self.r, self.k, (34, 34, 40), rim=210).copy()

    def present(self, img, card):
        blit(img, card, self.m, self.m)
        self.surface.show(img)

    def close(self):
        if self.alive:
            self.alive = False
            self.surface.destroy()
            self.backdrop.destroy()


# ───────────────────────────── مبدّل التطبيقات ─────────────────────────────

OWN_ICONS = {"mac:calculator": {"name": "Calculator", "icon": "calculator"},
             "mac:about": {"name": "System Information", "icon": "finder"},
             "mac:settings": {"name": "System Settings", "icon": "settings"}}


def spec_for_group(ui, g):
    """أيقونة التطبيق مثل ما تطلع في الـ Dock (Finder، الحاسبة…)."""
    if g["key"] in OWN_ICONS:
        return OWN_ICONS[g["key"]]
    for dock in ui.docks[:1]:
        for it in dock.pinned + list(dock.extras.values()) + dock.tail:
            if any(h in it["windows"] for h in g["hwnds"]):
                return it["spec"]
    if g.get("exe") and g["stem"] != "applicationframehost":
        return exe_spec(g["exe"])
    return {"name": g.get("title", "?"), "icon": "", "color": "#5e5ce6"}


class AppSwitcher:
    """مثل Cmd+Tab: أيقونات التطبيقات المفتوحة بالترتيب (الأحدث أول)، و Alt تفلت = تنتقل."""

    def __init__(self, ui, step):
        self.ui = ui
        groups = [g for g in ui.tracker.scan() + ui.app_groups() if g.get("hwnds")]
        self.items = [(spec_for_group(ui, g), g) for g in groups]
        self.alive = bool(self.items)
        if not self.alive:
            return
        n = len(self.items)
        self.idx = (1 if step > 0 else n - 1) % n
        mon = monitor_at_cursor(ui)
        k = mon.k
        self.icon = round(min(96 * k, (mon.w * 0.8 - 40 * k) / n - 18 * k))
        self.cell = self.icon + round(18 * k)
        w = self.cell * n + round(28 * k)
        h = self.cell + round(46 * k)
        self.glass = GlassOverlay(ui, mon, mon.x + (mon.w - w) / 2, mon.y + (mon.h - h) / 2, w, h, round(30 * k))
        self.render()

    def render(self):
        g = self.glass
        k = g.k
        img, card = g.frame()
        order = list(enumerate(self.items))
        if rtl():
            order = list(reversed(order))
        for pos, (i, (spec, grp)) in enumerate(order):
            x = round(14 * k) + pos * self.cell
            y = round(14 * k)
            if i == self.idx:
                blit(card, aa_round(self.cell, self.cell, round(18 * k), (255, 255, 255, 46)), x, y)
            icon = self.ui.icons.get(spec, round(self.icon * 512 / 432))
            blit(card, icon, x + (self.cell - icon.width) / 2, y + (self.cell - icon.height) / 2)
            if i == self.idx:
                draw_text(card, (x + self.cell / 2, y + self.cell + round(17 * k)), app_name(spec)[:28],
                          font("segoeui.ttf", round(13 * k)), WHITE, "mm")
        g.present(img, card)

    def step(self, d):
        self.idx = (self.idx + d) % len(self.items)
        self.render()

    def commit(self):
        _, grp = self.items[self.idx]
        own = self.ui.apps_open.get(grp["key"][4:]) if grp["key"].startswith("mac:") else None
        self.close()
        if own:
            own.focus()
        else:
            activate(grp["hwnds"][0])

    def close(self):
        if self.alive:
            self.alive = False
            self.glass.close()


# ───────────────────────────── مؤشر الصوت ─────────────────────────────

class VolumeHUD:
    """مثل macOS 27: لوح زجاج صغير فوق تحت الشريط، فيه مستوى الصوت، ويختفي لحاله."""

    def __init__(self, ui):
        self.ui, self.glass, self.hide_job = ui, None, None

    def change(self, vk):
        audio = self.ui.audio
        audio.reset()  # السماعة الافتراضية ممكن تكون تغيرت
        vol, muted = audio.get()
        if vol is None:
            return
        if vk == 0xAD:
            audio.toggle_mute()
        else:
            vol = max(0.0, min(1.0, round((vol + (1 / 16 if vk == 0xAF else -1 / 16)) * 16) / 16))
            audio.set(vol)
        vol, muted = audio.get()
        self.show(vol, muted)

    def show(self, vol, muted):
        mon = monitor_at_cursor(self.ui)
        k = mon.k
        w, h = round(250 * k), round(52 * k)
        x = mon.x + round(12 * k) if rtl() else mon.x + mon.w - w - round(12 * k)
        y = mon.y + round(36 * k)
        if not (self.glass and self.glass.alive and self.glass.mon is mon):
            if self.glass:
                self.glass.close()
            self.glass = GlassOverlay(self.ui, mon, x, y, w, h, h // 2)
        g = self.glass
        img, card = g.frame()
        glyph = "" if muted or vol == 0 else ("" if vol < 0.34 else "" if vol < 0.67 else "")
        gx = w - round(28 * k) if rtl() else round(28 * k)
        draw_text(card, (gx, h / 2), glyph, font("SegoeIcons.ttf", round(18 * k)), WHITE, "mm")
        tw, th = w - round(76 * k), round(8 * k)
        tx = round(22 * k) if rtl() else round(54 * k)
        blit(card, aa_round(tw, th, th / 2, (255, 255, 255, 60)), tx, (h - th) / 2)
        fw = max(th, tw * (0 if muted else vol))
        blit(card, aa_round(fw, th, th / 2, WHITE), tx + (tw - fw if rtl() else 0), (h - th) / 2)
        g.present(img, card)
        if self.hide_job:
            self.ui.root.after_cancel(self.hide_job)
        self.hide_job = self.ui.root.after(1600, self.hide)

    def hide(self):
        self.hide_job = None
        if self.glass:
            self.glass.close()
            self.glass = None


# ───────────────────────────── Quick Look ─────────────────────────────

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tif", ".tiff"}
TEXT_EXT = {".txt", ".md", ".py", ".js", ".ts", ".json", ".html", ".htm", ".css", ".log", ".csv", ".xml", ".ini",
            ".cfg", ".bat", ".cmd", ".ps1", ".c", ".cpp", ".h", ".cs", ".java", ".go", ".rs", ".yml", ".yaml",
            ".sql", ".sh", ".toml", ".srt"}


def explorer_selection(hwnd):
    """الملفات المحددة في نافذة مستكشف الملفات (عن طريق واجهة الشل الرسمية)."""
    ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
          f"$s=New-Object -ComObject Shell.Application; foreach($w in $s.Windows()){{ if($w.HWND -eq {int(hwnd)})"
          "{ $w.Document.SelectedItems() | ForEach-Object { $_.Path } } }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=8,
                           creationflags=0x08000000)
        return [l.strip() for l in r.stdout.decode("utf-8", "replace").splitlines() if l.strip()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def read_text(path, max_lines=400):
    raw = Path(path).read_bytes()[:200_000]
    for enc in ("utf-8-sig", "cp1256", "latin-1"):
        try:
            return raw.decode(enc).splitlines()[:max_lines]
        except UnicodeDecodeError:
            continue
    return []


class QuickLook(AppWindow):
    key, title = "quicklook", "Quick Look"
    listed = False
    glass_center = 215

    def __init__(self, ui, path):
        self.path = Path(path)
        mon = monitor_at_cursor(ui)
        k = mon.k
        self.kind = ("folder" if self.path.is_dir() else "image" if self.path.suffix.lower() in IMAGE_EXT else
                     "text" if self.path.suffix.lower() in TEXT_EXT else "info")
        self.top = round(46 * k)
        self.content = None
        self.lines = []
        if self.kind == "image":
            try:
                im = Image.open(self.path)
                im.draft("RGB", (int(mon.w * 0.7), int(mon.h * 0.7)))
                im = im.convert("RGBA")
                im.thumbnail((int(mon.w * 0.62), int(mon.h * 0.62)), LANCZOS)
                self.content = im
                w, h = max(im.width + round(24 * k), round(360 * k)), im.height + self.top + round(16 * k)
            except Exception:
                self.kind = "info"
        if self.kind == "text":
            try:
                self.lines = read_text(self.path)
                w, h = int(mon.w * 0.5), int(mon.h * 0.66)
            except OSError:
                self.kind = "info"  # ما ينقرى: نعرض معلوماته بدل صفحة فاضية
        if self.kind in ("info", "folder"):
            w, h = round(460 * k), round(300 * k)
        self.btn = None
        super().__init__(ui, w, h)
        self.surface.win.title(f"Quick Look — {self.path.name}")
        self.render()

    def icon(self, size):
        if self.kind == "folder":
            return icon_body({"icon": "folder"}, size)
        import system_theme as st
        ext = self.path.suffix.lower()
        if ext in st.FILE_TYPES:
            return st.document_icon(*st.FILE_TYPES[ext], size=size)
        if ext == ".exe":
            from macui import exe_icon, mac_plate
            src = exe_icon(str(self.path))
            if src:
                return mac_plate(src, size)
        return st.document_icon((ext[1:5] or "FILE").upper(), (142, 142, 147), "lines", size=size)

    def render(self):
        if not self.alive:
            return
        k = self.k
        img, card = self.frame()
        name = ar(self.path.name if len(self.path.name) <= 48 else self.path.name[:46] + "…")
        draw_text(card, (self.w / 2, round(20 * k)), name, font("seguisb.ttf", round(13 * k)), WHITE, "mm")
        # زر «فتح» مثل «Open with Preview» في الماك
        bw, bh = round(64 * k), round(24 * k)
        bx = round(14 * k) if rtl() else self.w - bw - round(14 * k)
        b = aa_round(bw, bh, bh / 2, (255, 255, 255, 40))
        draw_text(b, (bw / 2, bh / 2), tr("open"), font("segoeui.ttf", round(12 * k)), WHITE, "mm")
        blit(card, b, bx, round(8 * k))
        self.btn = (bx, round(8 * k), bx + bw, round(8 * k) + bh)
        area_y, area_h = self.top, self.h - self.top - round(12 * k)
        if self.kind == "image" and self.content:
            im = self.content
            blit(card, im, (self.w - im.width) / 2, area_y + (area_h - im.height) / 2)
        elif self.kind == "text":
            page = aa_round(self.w - round(24 * k), area_h, round(10 * k), (24, 24, 28, 255))
            blit(card, page, round(12 * k), area_y)
            f = font("CascadiaCode.ttf", round(12.5 * k))
            fa = font("segoeui.ttf", round(13 * k))  # خط الأكواد ما فيه عربي
            lh = round(18 * k)
            from arabic import has_arabic
            for i, line in enumerate(self.lines[: int((area_h - 16 * k) / lh)]):
                line = line.replace("\t", "    ")[:220]
                y = area_y + round(12 * k) + i * lh
                arabic_line = has_arabic(line)
                draw_text(card, (self.w - round(26 * k) if arabic_line else round(26 * k), y + lh / 2),
                          ar(line) if line.strip() else " ", fa if arabic_line else f, (225, 225, 230, 255),
                          "rm" if arabic_line else "lm")
        else:
            size = round(128 * k)
            blit(card, self.icon(size), round(28 * k) if not rtl() else self.w - size - round(28 * k),
                 area_y + round(20 * k))
            try:
                st = self.path.stat()
                info = [(ar("النوع") if rtl() else "Kind", ar("مجلد") if self.kind == "folder" and rtl() else
                         "Folder" if self.kind == "folder" else (self.path.suffix[1:].upper() or "File")),
                        (ar("الحجم") if rtl() else "Size", human_size(st.st_size) if self.kind != "folder" else "—"),
                        (ar("التعديل") if rtl() else "Modified", time.strftime("%Y-%m-%d  %H:%M", time.localtime(st.st_mtime)))]
            except OSError:
                info = []
            tx = round(28 * k) + size + round(24 * k)
            y = area_y + round(34 * k)
            draw_text(card, (self.w - tx if rtl() else tx, y), name, font("segoeuib.ttf", round(15 * k)), WHITE,
                      "rm" if rtl() else "lm")
            for label, value in info:
                y += round(26 * k)
                draw_text(card, (self.w - tx if rtl() else tx, y), f"{label}:  {value}" if not rtl() else
                          ar(f"{label}:") + "  " + value, font("segoeui.ttf", round(12.5 * k)), DIM, "rm" if rtl() else "lm")
        self.present(img, card)

    def on_press(self, x, y):
        if self.btn and self.btn[0] <= x <= self.btn[2] and self.btn[1] <= y <= self.btn[3]:
            return True
        return False

    def on_release(self, x, y):
        if self.btn and self.btn[0] <= x <= self.btn[2] and self.btn[1] <= y <= self.btn[3]:
            os.startfile(str(self.path))
            self.close()

    def on_key(self, e):
        super().on_key(e)
        if e.keysym in ("space", "Escape"):
            self.close()
        elif e.keysym == "Return":
            os.startfile(str(self.path))
            self.close()


def open_quicklook(ui, explorer_hwnd):
    """نجيب الملف المحدد بالخلفية (ما نعلق الواجهة) وبعدين نفتح المعاينة."""
    box = {}

    def work():
        box["paths"] = explorer_selection(explorer_hwnd)

    def show():
        if "paths" not in box:
            ui.root.after(50, show)
            return
        if box["paths"]:
            old = ui.apps_open.get("quicklook")
            if old and old.alive:
                old.close()
            ui.apps_open["quicklook"] = QuickLook(ui, box["paths"][0])

    threading.Thread(target=work, daemon=True).start()
    show()
