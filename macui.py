"""
macui.py — the core of the interface: menu bar, Dock, popups and the drawing toolkit.

Everything is rendered with Pillow and shown in per-pixel-alpha layered windows
(UpdateLayeredWindow). Real Liquid Glass blur comes from DWM acrylic "backdrop" windows that
sit right behind our content. The Windows taskbar is hidden while the interface runs and
everything it offered moves to the menu bar and the Dock.
"""
import ctypes
import io
import json
import math
import os
import subprocess
import threading
import time
import winreg
from ctypes import wintypes as W
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from arabic import ar
from settings import S as SETTINGS, app_name, clock_text, rtl, tr

HERE = Path(__file__).resolve().parent
APPS_FILE = HERE / "dock_apps.json"
WALLPAPER = HERE / "mac_wallpaper_27.png"
FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
LANCZOS = Image.LANCZOS
HKCU = winreg.HKEY_CURRENT_USER

# ───────────────────────────── Win32 ─────────────────────────────

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32")
kernel32 = ctypes.WinDLL("kernel32")
shell32 = ctypes.WinDLL("shell32")
shcore = ctypes.WinDLL("shcore")
ole32 = ctypes.WinDLL("ole32")
dwmapi = ctypes.WinDLL("dwmapi")
version = ctypes.WinDLL("version")
P = ctypes.POINTER


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", W.WORD), ("biBitCount", W.WORD), ("biCompression", W.DWORD),
                ("biSizeImage", W.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("op", ctypes.c_ubyte), ("flags", ctypes.c_ubyte),
                ("alpha", ctypes.c_ubyte), ("fmt", ctypes.c_ubyte)]


class APPBARDATA(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("hWnd", W.HWND), ("uCallbackMessage", W.UINT),
                ("uEdge", W.UINT), ("rc", RECT), ("lParam", W.LPARAM)]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", W.DWORD), ("BatteryFullLifeTime", W.DWORD)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", W.DWORD)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", W.DWORD), ("cntThreads", W.DWORD),
                ("th32ParentProcessID", W.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", W.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", W.DWORD), ("Data2", W.WORD), ("Data3", W.WORD), ("Data4", ctypes.c_ubyte * 8)]


WNDENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HMONITOR, W.HDC, P(RECT), W.LPARAM)


def _sig(fn, res, *args):
    fn.restype = res
    fn.argtypes = list(args)


_sig(user32.GetParent, W.HWND, W.HWND)
_sig(user32.GetForegroundWindow, W.HWND)
_sig(user32.GetWindowLongPtrW, ctypes.c_ssize_t, W.HWND, ctypes.c_int)
_sig(user32.SetWindowLongPtrW, ctypes.c_ssize_t, W.HWND, ctypes.c_int, ctypes.c_ssize_t)
_sig(user32.GetDC, W.HDC, W.HWND)
_sig(user32.ReleaseDC, ctypes.c_int, W.HWND, W.HDC)
_sig(user32.UpdateLayeredWindow, W.BOOL, W.HWND, W.HDC, P(W.POINT), P(W.SIZE), W.HDC,
     P(W.POINT), W.DWORD, P(BLENDFUNCTION), W.DWORD)
_sig(user32.SetWindowPos, W.BOOL, W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.UINT)
_sig(user32.IsWindowVisible, W.BOOL, W.HWND)
_sig(user32.IsWindow, W.BOOL, W.HWND)
_sig(user32.IsIconic, W.BOOL, W.HWND)
_sig(user32.GetWindow, W.HWND, W.HWND, W.UINT)
_sig(user32.GetWindowTextLengthW, ctypes.c_int, W.HWND)
_sig(user32.GetWindowTextW, ctypes.c_int, W.HWND, W.LPWSTR, ctypes.c_int)
_sig(user32.GetClassNameW, ctypes.c_int, W.HWND, W.LPWSTR, ctypes.c_int)
_sig(user32.GetWindowThreadProcessId, W.DWORD, W.HWND, P(W.DWORD))
_sig(user32.GetWindowRect, W.BOOL, W.HWND, P(RECT))
_sig(user32.ShowWindow, W.BOOL, W.HWND, ctypes.c_int)
_sig(user32.SetForegroundWindow, W.BOOL, W.HWND)
_sig(user32.PostMessageW, W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
_sig(user32.FindWindowW, W.HWND, W.LPCWSTR, W.LPCWSTR)
_sig(user32.GetCursorPos, W.BOOL, P(W.POINT))
_sig(user32.GetAsyncKeyState, ctypes.c_short, ctypes.c_int)
_sig(user32.keybd_event, None, W.BYTE, W.BYTE, W.DWORD, ctypes.c_size_t)
_sig(user32.GetSystemMetrics, ctypes.c_int, ctypes.c_int)
_sig(user32.EnumWindows, W.BOOL, WNDENUMPROC, W.LPARAM)
_sig(user32.EnumChildWindows, W.BOOL, W.HWND, WNDENUMPROC, W.LPARAM)
_sig(user32.EnumDisplayMonitors, W.BOOL, W.HDC, P(RECT), MONITORENUMPROC, W.LPARAM)
_sig(user32.GetMonitorInfoW, W.BOOL, W.HMONITOR, P(MONITORINFO))
_sig(user32.GetKeyboardLayout, ctypes.c_void_p, W.DWORD)
_sig(user32.PrivateExtractIconsW, W.UINT, W.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
     P(W.HICON), P(W.UINT), W.UINT, W.UINT)
_sig(user32.DrawIconEx, W.BOOL, W.HDC, ctypes.c_int, ctypes.c_int, W.HICON, ctypes.c_int, ctypes.c_int,
     W.UINT, W.HBRUSH, W.UINT)
_sig(user32.DestroyIcon, W.BOOL, W.HICON)
_sig(user32.LockWorkStation, W.BOOL)
_sig(user32.SystemParametersInfoW, W.BOOL, W.UINT, W.UINT, ctypes.c_void_p, W.UINT)
_sig(gdi32.CreateCompatibleDC, W.HDC, W.HDC)
_sig(gdi32.CreateDIBSection, W.HBITMAP, W.HDC, ctypes.c_void_p, W.UINT, P(ctypes.c_void_p), W.HANDLE, W.DWORD)
_sig(gdi32.SelectObject, W.HGDIOBJ, W.HDC, W.HGDIOBJ)
_sig(gdi32.DeleteObject, W.BOOL, W.HGDIOBJ)
_sig(gdi32.DeleteDC, W.BOOL, W.HDC)
_sig(kernel32.OpenProcess, W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
_sig(kernel32.QueryFullProcessImageNameW, W.BOOL, W.HANDLE, W.DWORD, W.LPWSTR, P(W.DWORD))
_sig(kernel32.CloseHandle, W.BOOL, W.HANDLE)
_sig(kernel32.GetSystemPowerStatus, W.BOOL, P(SYSTEM_POWER_STATUS))
_sig(kernel32.CreateToolhelp32Snapshot, W.HANDLE, W.DWORD, W.DWORD)
_sig(kernel32.Process32FirstW, W.BOOL, W.HANDLE, P(PROCESSENTRY32W))
_sig(kernel32.Process32NextW, W.BOOL, W.HANDLE, P(PROCESSENTRY32W))
_sig(kernel32.LCIDToLocaleName, ctypes.c_int, W.DWORD, W.LPWSTR, ctypes.c_int, W.DWORD)
_sig(shell32.SHAppBarMessage, ctypes.c_size_t, W.UINT, P(APPBARDATA))
_sig(shell32.SHGetKnownFolderPath, ctypes.c_long, P(GUID), W.DWORD, W.HANDLE, P(W.LPWSTR))
_sig(shcore.GetDpiForMonitor, ctypes.c_long, W.HMONITOR, ctypes.c_int, P(W.UINT), P(W.UINT))
_sig(ole32.CLSIDFromString, ctypes.c_long, W.LPCWSTR, P(GUID))
_sig(ole32.CoTaskMemFree, None, ctypes.c_void_p)
_sig(dwmapi.DwmGetWindowAttribute, ctypes.c_long, W.HWND, W.DWORD, ctypes.c_void_p, W.DWORD)
_sig(version.GetFileVersionInfoSizeW, W.DWORD, W.LPCWSTR, P(W.DWORD))
_sig(version.GetFileVersionInfoW, W.BOOL, W.LPCWSTR, W.DWORD, W.DWORD, ctypes.c_void_p)
_sig(version.VerQueryValueW, W.BOOL, ctypes.c_void_p, W.LPCWSTR, P(ctypes.c_void_p), P(W.UINT))

GWL_EXSTYLE, GWLP_HWNDPARENT = -20, -8
WS_EX_LAYERED, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80000, 0x80, 0x08000000
ABM_NEW, ABM_REMOVE, ABM_QUERYPOS, ABM_SETPOS = 0, 1, 2, 3
ABE_TOP, ABE_BOTTOM = 1, 3
VK_LWIN, VK_MENU = 0x5B, 0x12
MY_PID = os.getpid()


def cursor():
    pt = W.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def mouse_down():
    # 0x8001: مضغوط الحين أو انضغط من آخر مرة (عشان الضغطات السريعة ما تفوت)
    return bool(user32.GetAsyncKeyState(0x01) & 0x8001 or user32.GetAsyncKeyState(0x02) & 0x8001)


KEY_MAGIC = 0x4D414355  # نفس علامة keyboard_hook: ضغطاتنا ما تلتقطها الواجهة


def press(*vks):
    for vk in vks:
        user32.keybd_event(vk, 0, 0, KEY_MAGIC)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, 2, KEY_MAGIC)


def window_text(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def class_name(hwnd):
    buf = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, buf, 128)
    return buf.value


def window_pid(hwnd):
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_rect(hwnd):
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def process_path(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    buf = ctypes.create_unicode_buffer(1024)
    size = W.DWORD(1024)
    ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
    kernel32.CloseHandle(h)
    return buf.value if ok else ""


def running_exes():
    """أسماء كل البرامج الشغالة (بأحرف صغيرة)."""
    snap = kernel32.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == ctypes.c_void_p(-1).value:
        return set()
    out = set()
    e = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
    ok = kernel32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        out.add(e.szExeFile.lower())
        ok = kernel32.Process32NextW(snap, ctypes.byref(e))
    kernel32.CloseHandle(snap)
    return out


def known_folder(guid):
    g = GUID()
    if ole32.CLSIDFromString(guid, ctypes.byref(g)) != 0:
        return None
    p = W.LPWSTR()
    if shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) != 0:
        return None
    path = p.value
    ole32.CoTaskMemFree(p)
    return path


def file_description(path):
    try:
        size = version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path, 0, size, buf):
            return ""
        p, n = ctypes.c_void_p(), W.UINT()
        if not version.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(p), ctypes.byref(n)) or n.value < 4:
            return ""
        words = ctypes.cast(p, P(W.WORD))
        sub = f"\\StringFileInfo\\{words[0]:04x}{words[1]:04x}\\FileDescription"
        if version.VerQueryValueW(buf, sub, ctypes.byref(p), ctypes.byref(n)) and n.value:
            return ctypes.wstring_at(p, n.value).rstrip("\0").strip()
    except OSError:
        pass
    return ""


def activate(hwnd):
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    if not user32.SetForegroundWindow(hwnd):
        press(VK_MENU)  # لمسة Alt تسمح لويندوز يقدم النافذة
        user32.SetForegroundWindow(hwnd)


def battery():
    st = SYSTEM_POWER_STATUS()
    if not kernel32.GetSystemPowerStatus(ctypes.byref(st)):
        return None
    if st.BatteryFlag & 128 or st.BatteryLifePercent == 255:
        return None
    return st.BatteryLifePercent, st.ACLineStatus == 1


def input_language():
    hwnd = user32.GetForegroundWindow()
    tid = user32.GetWindowThreadProcessId(hwnd, None) if hwnd else 0
    lang = (user32.GetKeyboardLayout(tid) or 0) & 0xFFFF
    if lang & 0x3FF == 0x01:
        return "ع"
    buf = ctypes.create_unicode_buffer(85)
    kernel32.LCIDToLocaleName(lang, buf, 85, 0)
    return (buf.value[:2] or "EN").upper()


APP_HANDLER = None  # الواجهة تسجل دالة تفتح تطبيقاتنا الداخلية (الحاسبة، التطبيقات…)


def open_target(targets):
    for t in targets:
        try:
            if t.startswith("app:") and APP_HANDLER:
                APP_HANDLER(t[4:])
            elif t == "key:win":
                press(VK_LWIN)
            elif t.startswith("shell:"):
                subprocess.Popen(["explorer.exe", t])
            else:
                os.startfile(t)
            return True
        except OSError:
            continue
    return False


def default_browser():
    try:
        with winreg.OpenKey(HKCU, r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as k:
            progid = winreg.QueryValueEx(k, "ProgId")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + r"\shell\open\command") as k:
            cmd = winreg.QueryValueEx(k, "")[0].strip()
    except OSError:
        return None
    exe = cmd.split('"')[1] if cmd.startswith('"') else cmd.split(" ")[0]
    return exe if os.path.exists(exe) else None


def lnk_target(path):
    """يقرأ مسار البرنامج من اختصار .lnk (بدون COM)."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    u32 = lambda o: int.from_bytes(data[o:o + 4], "little")
    if len(data) < 0x4C or u32(0) != 0x4C:
        return None
    flags, pos = u32(0x14), 0x4C
    if flags & 0x01:
        pos += 2 + int.from_bytes(data[pos:pos + 2], "little")
    if not flags & 0x02:
        return None
    li = pos
    if not u32(li + 8) & 1:
        return None
    try:
        if u32(li + 4) >= 0x24 and u32(li + 0x1C):
            start = li + u32(li + 0x1C)
            end = start
            while data[end:end + 2] != b"\0\0":
                end += 2
            base = data[start:end].decode("utf-16-le")
        else:
            start = li + u32(li + 0x10)
            base = data[start:data.index(b"\0", start)].decode("mbcs")
    except (ValueError, UnicodeDecodeError):
        return None
    return base if os.path.exists(base) else None


# ───────────────────────────── الشاشات ─────────────────────────────

class Monitor:
    def __init__(self, rc, primary, dpi):
        self.x, self.y = rc.left, rc.top
        self.w, self.h = rc.right - rc.left, rc.bottom - rc.top
        self.primary = primary
        self.k = dpi / 96
        self.wp_sig, self.screen = None, None

    @property
    def rect(self):
        return self.x, self.y, self.x + self.w, self.y + self.h

    def load_wallpaper(self):
        # نص الدقة تكفي لأن الزجاج مغبش أصلاً، وتوفر ذاكرة
        self.wp_sig, self.screen = wallpaper_on_screen(max(1, self.w // 2), max(1, self.h // 2))

    def frost(self, box, tint, amount, blur):
        s = self.screen.width / self.w
        x0, y0, x1, y1 = [int(v) for v in box]
        reg = frost(self.screen, (x0 * s, y0 * s, x1 * s, y1 * s), tint, amount, max(2, int(blur * s)))
        return reg.resize((max(1, x1 - x0), max(1, y1 - y0)), Image.BICUBIC)


def monitors():
    out = []

    def cb(hmon, hdc, prc, lp):
        mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        dx, dy = W.UINT(96), W.UINT(96)
        if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)) != 0:
            dx.value = 96
        out.append(Monitor(mi.rcMonitor, bool(mi.dwFlags & 1), dx.value))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    out.sort(key=lambda m: not m.primary)
    return out


def taskbar_windows():
    out = []

    def cb(hwnd, _):
        if class_name(hwnd) in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            out.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def show_taskbar(visible):
    for hwnd in taskbar_windows():
        if bool(user32.IsWindowVisible(hwnd)) != visible:
            user32.ShowWindow(hwnd, 8 if visible else 0)  # SW_SHOWNA / SW_HIDE


# ───────────────────────────── أدوات الرسم ─────────────────────────────

_fonts = {}


def font(name, px):
    key = (name, int(px))
    if key not in _fonts:
        try:
            _fonts[key] = ImageFont.truetype(str(FONT_DIR / name), int(px))
        except OSError:
            _fonts[key] = ImageFont.truetype(str(FONT_DIR / "segoeui.ttf"), int(px))
    return _fonts[key]


def rgb(h, a=255):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a


def shade(c, f):
    """f > 0 يفتّح، f < 0 يغمّق."""
    r, g, b = c[:3]
    if f >= 0:
        return tuple(round(v + (255 - v) * f) for v in (r, g, b)) + (255,)
    return tuple(round(v * (1 + f)) for v in (r, g, b)) + (255,)


def vgrad(w, h, top, bottom):
    mask = Image.linear_gradient("L").resize((max(1, int(w)), max(1, int(h))))
    return Image.composite(Image.new("RGBA", mask.size, bottom), Image.new("RGBA", mask.size, top), mask)


def stroke(d, p0, p1, w, fill):
    d.line([p0, p1], fill=fill, width=int(w))
    for x, y in (p0, p1):
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=fill)


def aa_round(w, h, r, fill, outline=None, ss=3):
    w, h = max(1, int(w)), max(1, int(h))
    big = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), int(r * ss), fill=fill,
                                          outline=outline, width=ss if outline else 0)
    return big.resize((w, h), LANCZOS)


_glass = {}


def glass_overlay(w, h, r, top=170, bottom=40, sheen=30):
    """لمعة الزجاج السائل (Liquid Glass): حافة مضيئة من فوق تخف لتحت + لمعة خفيفة أعلى السطح."""
    key = (int(w), int(h), int(r), top, bottom, sheen)
    if key not in _glass:
        if len(_glass) > 300:
            _glass.clear()
        w, h = max(1, int(w)), max(1, int(h))
        ring = aa_round(w, h, r, None, (255, 255, 255, 255)).getchannel("A")
        grad = Image.linear_gradient("L").resize((w, h))
        rim = ImageChops.multiply(ring, grad.point(lambda v: int(top + (bottom - top) * v / 255)))
        fill = aa_round(w, h, r, (255, 255, 255, 255)).getchannel("A")
        shine = ImageChops.multiply(fill, grad.point(lambda v: max(0, int(sheen * (1 - v / 110)))))
        over = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        over.putalpha(ImageChops.lighter(rim, shine))
        _glass[key] = over
    return _glass[key]


def glass_panel(w, h, r, tint=(40, 40, 46, 205)):
    """لوح زجاجي للقوائم والتلميحات."""
    panel = aa_round(w, h, r, tint)
    panel.alpha_composite(glass_overlay(w, h, r))
    return panel


def soft_shadow(w, h, r, blur, alpha):
    pad = blur * 2
    m = Image.new("L", (int(w) + 2 * pad, int(h) + 2 * pad), 0)
    ImageDraw.Draw(m).rounded_rectangle((pad, pad, pad + w, pad + h), int(r), fill=int(255 * alpha))
    s = Image.new("RGBA", m.size, (0, 0, 0, 0))
    s.putalpha(m.filter(ImageFilter.GaussianBlur(blur)))
    return s, pad


def blit(dst, src, x, y):
    x, y = int(round(x)), int(round(y))
    sx0, sy0 = max(0, -x), max(0, -y)
    sx1, sy1 = min(src.width, dst.width - x), min(src.height, dst.height - y)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    if (sx0, sy0, sx1, sy1) != (0, 0, src.width, src.height):
        src = src.crop((sx0, sy0, sx1, sy1))
    dst.alpha_composite(src, (x + sx0, y + sy0))


def draw_text(img, xy, text, fnt, color, anchor="lm"):
    """نص ناعم فوق صورة شفافة بدون ما يخرب الشفافية."""
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).text(xy, text, font=fnt, fill=color[3] if len(color) > 3 else 255, anchor=anchor)
    layer = Image.new("RGBA", img.size, tuple(color[:3]) + (0,))
    layer.putalpha(mask)
    img.alpha_composite(layer)


# ───────────────────────────── الأيقونات ─────────────────────────────

RES, BODY = 512, 432
OFF = (RES - BODY) // 2
_squircle = {}


def squircle(size, n=5.0):
    if size not in _squircle:
        ss = size * 2
        pts = []
        for i in range(720):
            t = 2 * math.pi * i / 720
            c, s = math.cos(t), math.sin(t)
            x = math.copysign(abs(c) ** (2 / n), c)
            y = math.copysign(abs(s) ** (2 / n), s)
            pts.append(((x + 1) / 2 * (ss - 1), (y + 1) / 2 * (ss - 1)))
        m = Image.new("L", (ss, ss), 0)
        ImageDraw.Draw(m).polygon(pts, fill=255)
        _squircle[size] = m.resize((size, size), LANCZOS)
    return _squircle[size]


_rims = {}


def icon_rim(S):
    """حافة زجاجية مضيئة حول الأيقونة، مثل أيقونات macOS الجديدة."""
    if S not in _rims:
        sq = squircle(S)
        inner = sq.filter(ImageFilter.MinFilter(max(3, int(S * 0.012) * 2 + 1)))
        band = ImageChops.subtract(sq, inner)
        grad = Image.linear_gradient("L").resize((S, S)).point(lambda v: int(190 - 150 * v / 255))
        top = Image.linear_gradient("L").resize((S, S)).point(lambda v: max(0, int(38 * (1 - v / 120))))
        over = Image.new("RGBA", (S, S), (255, 255, 255, 0))
        over.putalpha(ImageChops.lighter(ImageChops.multiply(band, grad), ImageChops.multiply(sq, top)))
        _rims[S] = over
    return _rims[S]


def _rgbcanvas(S, top, bottom):
    return vgrad(S, S, rgb(top), rgb(bottom)).convert("RGB")


def _finder(S):
    img = _rgbcanvas(S, "#62cdfc", "#1673e8")
    right = _rgbcanvas(S, "#f6f9fd", "#c6ddf3")
    m = Image.new("L", (S, S), 0)
    f = lambda a: a * S
    ImageDraw.Draw(m).polygon([(S, 0), (S, S), (f(.62), S), (f(.6), f(.8)), (f(.585), f(.67)), (f(.47), f(.615)),
                               (f(.52), f(.53)), (f(.545), f(.35)), (f(.56), 0)], fill=255)
    img.paste(right, (0, 0), m)
    d = ImageDraw.Draw(img)
    eye = rgb("#1b2c4c")
    stroke(d, (f(.33), f(.27)), (f(.33), f(.41)), f(.068), eye)
    stroke(d, (f(.72), f(.27)), (f(.72), f(.41)), f(.068), eye)
    d.arc((f(.19), f(.36), f(.83), f(.78)), start=32, end=148, fill=eye, width=int(f(.045)))
    return img


def _launchpad(S):
    img = _rgbcanvas(S, "#a2a2ac", "#4b4b55")
    cols = ["#ff453a", "#ff9f0a", "#ffd60a", "#32d74b", "#64d2ff", "#0a84ff", "#5e5ce6", "#bf5af2", "#ff375f"]
    t, g = S * 0.19, S * 0.07
    start = (S - (3 * t + 2 * g)) / 2
    for i, c in enumerate(cols):
        r, cn = divmod(i, 3)
        x, y = start + cn * (t + g), start + r * (t + g)
        tile = vgrad(t, t, shade(rgb(c), 0.18), shade(rgb(c), -0.12))
        mask = Image.new("L", tile.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, tile.width - 1, tile.height - 1), int(t * 0.28), fill=255)
        img.paste(tile.convert("RGB"), (int(x), int(y)), mask)
    return img


def _safari(S):
    img = _rgbcanvas(S, "#ffffff", "#dcdce2")
    c, R = S / 2, S * 0.41
    disc = _rgbcanvas(S, "#52d6ff", "#1260f2")
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).ellipse((c - R, c - R, c + R, c + R), fill=255)
    img.paste(disc, (0, 0), m)
    d = ImageDraw.Draw(img)
    for i in range(72):
        a = math.radians(i * 5)
        big = i % 9 == 0
        r0, r1 = R * (0.78 if big else 0.86), R * 0.94
        d.line([(c + r0 * math.cos(a), c + r0 * math.sin(a)), (c + r1 * math.cos(a), c + r1 * math.sin(a))],
               fill=(235, 245, 255), width=max(2, int(S * (0.013 if big else 0.007))))
    a = math.radians(-45)
    L, Wd = R * 0.74, R * 0.14
    ca, sa = math.cos(a), math.sin(a)
    tip, tail = (c + L * ca, c + L * sa), (c - L * ca, c - L * sa)
    s1, s2 = (c - Wd * sa, c + Wd * ca), (c + Wd * sa, c - Wd * ca)
    d.polygon([tip, s1, s2], fill=rgb("#ff3b30"))
    d.polygon([tail, s1, s2], fill=(245, 245, 247))
    d.ellipse((c - R * .05, c - R * .05, c + R * .05, c + R * .05), fill=(200, 200, 205))
    return img


def _terminal(S):
    img = _rgbcanvas(S, "#e2e2e6", "#9a9aa2")
    d = ImageDraw.Draw(img)
    i = S * 0.075
    d.rounded_rectangle((i, i, S - i, S - i), int(S * 0.07), fill=rgb("#1c1c1e"))
    d.text((S * 0.17, S * 0.2), ">_", font=font("consolab.ttf", S * 0.25), fill=(242, 242, 242))
    return img


def _photos(S):
    img = Image.new("RGBA", (S, S), (255, 255, 255, 255))
    cols = ["#ff9500", "#ffcc00", "#a2d94a", "#34c759", "#5ac8fa", "#007aff", "#af52de", "#ff2d55"]
    c, pw = S / 2, S * 0.19
    for i, col in enumerate(cols):
        layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle((c - pw / 2, c - S * 0.37, c + pw / 2, c - S * 0.02),
                                                int(pw / 2), fill=rgb(col, 205))
        img.alpha_composite(layer.rotate(-45 * i, center=(c, c), resample=Image.BICUBIC))
    return img.convert("RGB")


def _notes(S):
    img = Image.new("RGB", (S, S), (251, 251, 248))
    img.paste(vgrad(S, S * 0.29, rgb("#ffe36e"), rgb("#ffc61f")).convert("RGB"), (0, 0))
    d = ImageDraw.Draw(img)
    step = S * 0.055
    for n in range(int(S / step) + 1):
        x = n * step + step / 2
        d.ellipse((x - S * .012, S * .325 - S * .012, x + S * .012, S * .325 + S * .012), fill=(205, 205, 210))
    y = S * 0.46
    while y < S * 0.97:
        d.line([(0, y), (S, y)], fill=(216, 216, 222), width=max(2, int(S * 0.008)))
        y += S * 0.105
    return img


def _calculator(S):
    img = _rgbcanvas(S, "#4c4c52", "#1d1d20")
    d = ImageDraw.Draw(img)
    r, w, white = S * 0.165, S * 0.038, (255, 255, 255)
    for cx, cy, col, sym in ((.31, .31, "#8e8e93", "-"), (.69, .31, "#ff9f0a", "+"),
                             (.31, .69, "#636366", "x"), (.69, .69, "#ff9f0a", "=")):
        cx, cy = cx * S, cy * S
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=rgb(col))
        q = r * 0.48
        if sym in "-+":
            stroke(d, (cx - q, cy), (cx + q, cy), w, white)
        if sym == "+":
            stroke(d, (cx, cy - q), (cx, cy + q), w, white)
        if sym == "x":
            q *= 0.8
            stroke(d, (cx - q, cy - q), (cx + q, cy + q), w, white)
            stroke(d, (cx - q, cy + q), (cx + q, cy - q), w, white)
        if sym == "=":
            stroke(d, (cx - q, cy - q * .4), (cx + q, cy - q * .4), w, white)
            stroke(d, (cx - q, cy + q * .4), (cx + q, cy + q * .4), w, white)
    return img


def _appstore(S):
    img = _rgbcanvas(S, "#22d0ff", "#0a5ff0")
    d = ImageDraw.Draw(img)
    w, white, f = S * 0.072, (255, 255, 255), lambda a: a * S
    stroke(d, (f(.29), f(.73)), (f(.55), f(.27)), w, white)
    stroke(d, (f(.71), f(.73)), (f(.45), f(.27)), w, white)
    stroke(d, (f(.23), f(.6)), (f(.77), f(.6)), w, white)
    return img


def _settings(S):
    img = _rgbcanvas(S, "#dadadf", "#8b8b93")
    d = ImageDraw.Draw(img)
    c = S / 2
    d.ellipse((c - S * .4, c - S * .4, c + S * .4, c + S * .4), fill=rgb("#4a4a50"))
    d.text((c, c), "\uE713", font=font("SegoeIcons.ttf", S * 0.62), fill=(205, 205, 212), anchor="mm")
    d.ellipse((c - S * .08, c - S * .08, c + S * .08, c + S * .08), fill=rgb("#4a4a50"))
    return img


def _folder(S, glyph=None):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = lambda a: a * S
    back = rgb("#3a98ec")
    d.rounded_rectangle((f(.06), f(.15), f(.46), f(.32)), int(f(.05)), fill=back)
    d.rounded_rectangle((f(.06), f(.21), f(.94), f(.86)), int(f(.06)), fill=back)
    front = vgrad(f(.88), f(.55), rgb("#93d6ff"), rgb("#4aa7f3"))
    m = Image.new("L", front.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, front.width - 1, front.height - 1), int(f(.06)), fill=255)
    front.putalpha(m)
    img.alpha_composite(front, (int(f(.06)), int(f(.31))))
    if glyph:
        draw_text(img, (S / 2, f(.585)), glyph, font("SegoeIcons.ttf", f(.3)), (30, 105, 185, 220), "mm")
    return img


def _downloads(S):
    return _folder(S, "\uE896")


def _trash(S, full=False):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    f = lambda a: a * S
    if full:
        papers = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        pd = ImageDraw.Draw(papers)
        for x0, y0, x1, y1, ang in ((.3, .08, .55, .4, -14), (.45, .06, .7, .38, 12), (.36, .12, .64, .42, 3)):
            sheet = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            ImageDraw.Draw(sheet).rectangle((f(x0), f(y0), f(x1), f(y1)), fill=(250, 250, 252, 255),
                                            outline=(200, 200, 208, 255), width=int(f(.008)))
            papers.alpha_composite(sheet.rotate(ang, center=(S / 2, f(.25)), resample=Image.BICUBIC))
        img.alpha_composite(papers)
    body = vgrad(S, S, (246, 246, 250, 240), (196, 196, 206, 240))
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).polygon([(f(.24), f(.22)), (f(.76), f(.22)), (f(.72), f(.9)), (f(.28), f(.9))], fill=255)
    body.putalpha(ImageChops.multiply(body.getchannel("A"), m))
    img.alpha_composite(body)
    d = ImageDraw.Draw(img)
    for x0, x1 in ((.36, .38), (.5, .5), (.64, .62)):
        d.line([(f(x0), f(.3)), (f(x1), f(.83))], fill=(160, 160, 172, 255), width=int(f(.018)))
    if not full:
        d.rounded_rectangle((f(.41), f(.07), f(.59), f(.14)), int(f(.02)), outline=(220, 220, 228, 255), width=int(f(.025)))
        d.rounded_rectangle((f(.18), f(.12), f(.82), f(.21)), int(f(.03)), fill=(232, 232, 238, 255))
    return img


def _trash_full(S):
    return _trash(S, True)


def _drive(S):
    """قرص بستايل Macintosh HD."""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    f = lambda a: a * S
    body = vgrad(f(.84), f(.5), rgb("#f2f2f5"), rgb("#a9a9b2"))
    m = Image.new("L", body.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, body.width - 1, body.height - 1), int(f(.07)), fill=255)
    body.putalpha(m)
    img.alpha_composite(body, (int(f(.08)), int(f(.25))))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((f(.08), f(.6), f(.92), f(.75)), int(f(.05)), fill=(120, 120, 130, 255))
    d.ellipse((f(.78), f(.645), f(.84), f(.705)), fill=(80, 255, 140, 255))
    for i in range(6):
        x = f(.18) + i * f(.07)
        d.line([(x, f(.32)), (x, f(.52))], fill=(170, 170, 180, 255), width=max(2, int(f(.012))))
    return img


def _generic(S, spec):
    base = rgb(spec.get("color", "#636366"))
    img = vgrad(S, S, shade(base, 0.25), shade(base, -0.18)).convert("RGB")
    d = ImageDraw.Draw(img)
    if spec.get("glyph"):
        d.text((S / 2, S / 2), chr(int(spec["glyph"], 16)), font=font("SegoeIcons.ttf", S * 0.5),
               fill=(255, 255, 255), anchor="mm")
    else:
        name = spec.get("name") or "?"
        letter = name[:1].upper() if name[:1].isascii() else "•"
        d.text((S / 2, S / 2), letter, font=font("seguisb.ttf", S * 0.5), fill=(255, 255, 255), anchor="mm")
    return img


DRAWERS = {"finder": _finder, "launchpad": _launchpad, "safari": _safari, "terminal": _terminal,
           "photos": _photos, "notes": _notes, "calculator": _calculator, "appstore": _appstore,
           "settings": _settings}
SHAPED = {"downloads": _downloads, "trash": _trash, "trash_full": _trash_full, "folder": _folder, "drive": _drive}


def exe_icon(path, size=256):
    hicon, iid = W.HICON(), W.UINT()
    if not user32.PrivateExtractIconsW(path, 0, size, size, ctypes.byref(hicon), ctypes.byref(iid), 1, 0) or not hicon:
        return None
    sdc = user32.GetDC(None)
    mdc = gdi32.CreateCompatibleDC(sdc)
    bih = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), size, -size, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    bmp = gdi32.CreateDIBSection(mdc, ctypes.byref(bih), 0, ctypes.byref(bits), None, 0)
    old = gdi32.SelectObject(mdc, bmp)
    user32.DrawIconEx(mdc, 0, 0, hicon, size, size, 0, None, 3)
    raw = ctypes.string_at(bits, size * size * 4)
    gdi32.SelectObject(mdc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(None, sdc)
    user32.DestroyIcon(hicon)
    img = Image.frombuffer("RGBA", (size, size), raw, "raw", "BGRA", 0, 1)
    if img.getchannel("A").getextrema()[1] == 0:
        img = img.copy()
        img.putalpha(255)
        return img
    return Image.frombuffer("RGBa", (size, size), raw, "raw", "BGRa", 0, 1).convert("RGBA")


def mac_plate(src, S):
    """يحط أيقونة برنامج ويندوز الحقيقية بإطار الماك المربع الناعم."""
    bbox = src.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    if bbox:
        src = src.crop(bbox)
    a = src.getchannel("A")
    w, h = src.size
    corners = [a.getpixel((int(w * fx), int(h * fy))) for fx in (0.04, 0.96) for fy in (0.04, 0.96)]
    if min(w, h) > 0 and abs(w - h) < max(w, h) * 0.08 and min(corners) > 200:
        # الأيقونة أصلاً مربعة كاملة: نقص زواياها بشكل الماك
        body = src.resize((S, S), LANCZOS)
        body.putalpha(ImageChops.multiply(body.getchannel("A"), squircle(S)))
        body.alpha_composite(icon_rim(S))
        return body
    plate = vgrad(S, S, (252, 252, 254, 255), (222, 222, 229, 255))
    plate.putalpha(squircle(S))
    fit = S * 0.66 / max(w, h)
    icon = src.resize((max(1, int(w * fit)), max(1, int(h * fit))), LANCZOS)
    sh = Image.new("RGBA", plate.size, (0, 0, 0, 0))
    sa = Image.new("L", plate.size, 0)
    sa.paste(icon.getchannel("A"), ((S - icon.width) // 2, (S - icon.height) // 2 + int(S * 0.015)))
    sh.putalpha(sa.filter(ImageFilter.GaussianBlur(S * 0.015)).point(lambda v: int(v * 0.3)))
    plate.alpha_composite(sh)
    plate.alpha_composite(icon, ((S - icon.width) // 2, (S - icon.height) // 2))
    plate.alpha_composite(icon_rim(S))
    return plate


def icon_body(spec, S=BODY):
    kind = spec.get("icon", "")
    if kind == "exe" and spec.get("exe"):
        src = exe_icon(spec["exe"])
        if src:
            return mac_plate(src, S)
        kind = ""
    if kind == "png" and spec.get("png"):
        return mac_plate(Image.open(io.BytesIO(spec["png"])).convert("RGBA"), S)
    if kind in SHAPED:
        return SHAPED[kind](S)
    body = (DRAWERS[kind](S) if kind in DRAWERS else _generic(S, spec)).convert("RGBA")
    body.putalpha(squircle(S))
    body.alpha_composite(icon_rim(S))
    return body


def render_icon(spec):
    """أيقونة 512×512 بظل ناعم، مثل أيقونات الماك."""
    body = icon_body(spec)
    canvas = Image.new("RGBA", (RES, RES), (0, 0, 0, 0))
    a = Image.new("L", (RES, RES), 0)
    a.paste(body.getchannel("A"), (OFF, OFF + 9))
    shadow = Image.new("RGBA", (RES, RES), (0, 0, 0, 0))
    shadow.putalpha(a.filter(ImageFilter.GaussianBlur(9)).point(lambda v: int(v * 0.42)))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(body, (OFF, OFF))
    return canvas


def save_ico(spec, path):
    body = icon_body(spec, 512)
    bbox = body.getchannel("A").getbbox() or (0, 0, 512, 512)
    side = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.alpha_composite(body.crop(bbox), ((side - (bbox[2] - bbox[0])) // 2, (side - (bbox[3] - bbox[1])) // 2))
    sq.resize((256, 256), LANCZOS).save(path, format="ICO",
                                         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return path


class Icons:
    def __init__(self):
        self.base, self.sized = {}, {}

    @staticmethod
    def key(spec):
        return "|".join(str(spec.get(k, "")) for k in ("icon", "exe", "color", "glyph", "name"))

    def get(self, spec, px):
        k = self.key(spec)
        if k not in self.base:
            try:
                icon = render_icon(spec)
            except Exception:
                icon = render_icon({"name": spec.get("name", "?")})
            self.base[k] = icon.resize((256, 256), LANCZOS)  # 256 تكفي لأكبر حجم بالـ Dock وتوفر ذاكرة
        px = max(2, int(px) // 2 * 2)  # أحجام زوجية بس = كاش أصغر
        sk = (k, px)
        if sk not in self.sized:
            if len(self.sized) > 160:
                self.sized.clear()
            self.sized[sk] = self.base[k].resize((px, px), LANCZOS)
        return self.sized[sk]


# ───────────────────────────── الخلفية ─────────────────────────────

def make_wallpaper(path, w, h):
    """خلفية حرير ذهبي متموج، بروح خلفية macOS 27 (مرسومة من الصفر)."""
    import numpy as np
    sw, sh = max(320, w // 2), max(180, h // 2)
    y, x = np.mgrid[0:sh, 0:sw].astype(np.float32)
    X, Y = x / sw, y / sh * (sh / sw)
    u = X * 2.6 + 0.55 * np.sin(Y * 3.2 + X * 1.7) + 0.25 * np.sin(X * 5.3 - Y * 2.1 + 1.3)
    hgt = np.sin(u * 2 * np.pi * 0.85 + Y * 4.2) * (0.6 + 0.4 * np.sin(Y * 2.0 + X * 1.1))
    hgt += 0.35 * np.sin(u * 2 * np.pi * 1.9 - Y * 3.0 + 0.7)
    gy, gx = np.gradient(hgt)
    nx, ny = -gx * 55.0, -gy * 55.0
    n = np.sqrt(nx ** 2 + ny ** 2 + 1)
    lx, ly, lz = -0.55, -0.6, 0.58
    diffuse = np.clip((nx * lx + ny * ly + lz) / n, 0, 1)
    hn = math.sqrt(lx * lx + ly * ly + (lz + 1) ** 2)
    spec = np.clip((nx * lx + ny * ly + (lz + 1)) / (n * hn), 0, 1) ** 40
    depth = 0.6 + 0.4 * (hgt - hgt.min()) / (np.ptp(hgt) + 1e-6)
    t = np.clip(diffuse * 0.88 * depth + 0.13, 0, 1)
    stops = np.array([[20, 11, 5], [66, 36, 10], [138, 84, 26], [208, 150, 60], [245, 210, 140], [255, 242, 214]],
                     np.float32)
    pos = np.linspace(0, 1, len(stops))
    col = np.stack([np.interp(t, pos, stops[:, c]) for c in range(3)], -1)
    col += spec[..., None] * np.array([255, 236, 200], np.float32) * 0.55
    vign = (1 - 0.42 * np.clip(1 - y / (sh * 0.22), 0, 1) ** 2
            - 0.32 * np.clip((y - sh * 0.8) / (sh * 0.2), 0, 1) ** 2)
    col *= vign[..., None]
    img = Image.fromarray(np.clip(col, 0, 255).astype(np.uint8), "RGB")
    img = img.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(0.8))
    noise = np.random.default_rng(7).normal(0, 2.2, (h, w, 1)).astype(np.float32)
    Image.fromarray(np.clip(np.asarray(img, np.float32) + noise, 0, 255).astype(np.uint8), "RGB").save(path)
    return path


def screen_size():
    try:
        shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def user_wallpaper():
    """خلفية حطها المستخدم بنفسه في المجلد (مثل خلفية macOS 27 الرسمية)."""
    for name in ("mac_wallpaper.jpg", "mac_wallpaper.jpeg", "mac_wallpaper.png", "mac_wallpaper.webp"):
        if (HERE / name).exists():
            return HERE / name
    return None


def upscale_wallpaper(src_path, path, w, h):
    """يكبّر الخلفية لحجم الشاشة بنعومة (تنعيم بسيط، تكبير، توضيح، حبيبات خفيفة تخفي التكبير)."""
    import numpy as np
    src = Image.open(src_path).convert("RGB")
    s = max(w / src.width, h / src.height)
    if s > 1.2:
        src = src.filter(ImageFilter.GaussianBlur(0.6))
    big = src.resize((max(w, int(src.width * s + 1)), max(h, int(src.height * s + 1))), LANCZOS)
    x, y = (big.width - w) // 2, (big.height - h) // 2
    big = big.crop((x, y, x + w, y + h))
    if s > 1.2:
        big = big.filter(ImageFilter.UnsharpMask(radius=2.2, percent=70, threshold=2))
        arr = np.asarray(big, np.float32) + np.random.default_rng(3).normal(0, 1.6, (h, w, 1))
        big = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    big.save(path)
    return path


def ensure_wallpaper():
    src = user_wallpaper()
    if src and (not WALLPAPER.exists() or WALLPAPER.stat().st_mtime < src.stat().st_mtime):
        upscale_wallpaper(src, WALLPAPER, *screen_size())
    elif not WALLPAPER.exists():
        make_wallpaper(WALLPAPER, *screen_size())
    return WALLPAPER


def set_wallpaper(path):
    buf = ctypes.create_unicode_buffer(str(path))
    user32.SystemParametersInfoW(20, 0, buf, 3)  # SPI_SETDESKWALLPAPER، حفظ + إبلاغ


def wallpaper_info():
    try:
        with winreg.OpenKey(HKCU, r"Control Panel\Desktop") as k:
            path = winreg.QueryValueEx(k, "WallPaper")[0]
            style = winreg.QueryValueEx(k, "WallpaperStyle")[0]
    except OSError:
        path, style = "", "10"
    if not path or not os.path.exists(path):
        path = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Themes\TranscodedWallpaper")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0
    return path, str(style), mtime


def wallpaper_on_screen(sw, sh):
    path, style, mtime = wallpaper_info()
    try:
        src = Image.open(path).convert("RGB")
    except Exception:
        return (path, style, mtime), vgrad(sw, sh, rgb("#1a1a2e"), rgb("#16213e")).convert("RGB")
    if style == "2":
        img = src.resize((sw, sh), Image.BILINEAR)
    elif style == "6":
        s = min(sw / src.width, sh / src.height)
        img = Image.new("RGB", (sw, sh), (0, 0, 0))
        fit = src.resize((max(1, int(src.width * s)), max(1, int(src.height * s))), Image.BILINEAR)
        img.paste(fit, ((sw - fit.width) // 2, (sh - fit.height) // 2))
    else:
        s = max(sw / src.width, sh / src.height)
        big = src.resize((max(sw, int(src.width * s + 1)), max(sh, int(src.height * s + 1))), Image.BILINEAR)
        x, y = (big.width - sw) // 2, (big.height - sh) // 2
        img = big.crop((x, y, x + sw, y + sh))
    return (path, style, mtime), img


def frost(screen, box, tint, amount, blur):
    """زجاج مغبش: جزء من الخلفية مغبش ومشبع ومصبوغ."""
    x0, y0, x1, y1 = [int(v) for v in box]
    m = blur * 2
    bx0, by0 = max(0, x0 - m), max(0, y0 - m)
    bx1, by1 = min(screen.width, x1 + m), min(screen.height, y1 + m)
    reg = screen.crop((bx0, by0, bx1, by1))
    w, h = reg.size
    small = reg.resize((max(1, w // 4), max(1, h // 4)), Image.BILINEAR).filter(ImageFilter.GaussianBlur(blur / 4))
    reg = small.resize((w, h), Image.BICUBIC).crop((x0 - bx0, y0 - by0, x1 - bx0, y1 - by0))
    reg = ImageEnhance.Color(reg).enhance(1.6)
    return Image.blend(reg, Image.new("RGB", reg.size, tint), amount)


# ───────────────────────────── النوافذ الشفافة ─────────────────────────────

class Surface:
    """نافذة Tk نرسم محتواها بأنفسنا بشفافية كاملة (ألفا لكل بكسل)."""

    def __init__(self, root, x, y, w, h, topmost=True, activate=False, app=False):
        import tkinter as tk
        self.x, self.y, self.w, self.h = int(x), int(y), int(w), int(h)
        prev = None if (activate or app) else user32.GetForegroundWindow()
        win = self.win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-alpha", 0.0)
        win.geometry(f"{self.w}x{self.h}+{self.x}+{self.y}")
        if topmost:
            win.attributes("-topmost", True)
        win.update_idletasks()
        self.hwnd = user32.GetParent(win.winfo_id())
        ex = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex & ~WS_EX_LAYERED)
        if app:  # نافذة تطبيق عادية: تطلع في Alt+Tab وتاخذ الكيبورد
            ex = (ex | WS_EX_LAYERED | 0x40000) & ~(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        else:
            ex |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | (0 if activate else WS_EX_NOACTIVATE)
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex)
        # Tk يفعّل النافذة أول ما تظهر؛ نرجع التركيز للبرنامج اللي كان شغال
        if prev and user32.GetForegroundWindow() != prev and window_pid(prev) != MY_PID:
            user32.SetForegroundWindow(prev)
        self.mdc = self.bmp = self.old = None
        self.dib_size = None
        self.last = None

    def _alloc(self, w, h):
        self._free()
        sdc = user32.GetDC(None)
        self.mdc = gdi32.CreateCompatibleDC(sdc)
        user32.ReleaseDC(None, sdc)
        bih = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        self.bits = ctypes.c_void_p()
        self.bmp = gdi32.CreateDIBSection(self.mdc, ctypes.byref(bih), 0, ctypes.byref(self.bits), None, 0)
        self.old = gdi32.SelectObject(self.mdc, self.bmp)
        self.dib_size = (w, h)

    def _free(self):
        if self.mdc:
            gdi32.SelectObject(self.mdc, self.old)
            gdi32.DeleteObject(self.bmp)
            gdi32.DeleteDC(self.mdc)
            self.mdc = None

    def show(self, img=None):
        img = img or self.last
        if img is None:
            return
        self.last = img
        if img.size != self.dib_size:
            self._alloc(*img.size)
            data = img.convert("RGBa").tobytes("raw", "BGRa")
            ctypes.memmove(self.bits, data, len(data))
        else:
            data = img.convert("RGBa").tobytes("raw", "BGRa")
            ctypes.memmove(self.bits, data, len(data))
        user32.UpdateLayeredWindow(self.hwnd, None, ctypes.byref(W.POINT(self.x, self.y)),
                                   ctypes.byref(W.SIZE(*img.size)), self.mdc, ctypes.byref(W.POINT(0, 0)),
                                   0, ctypes.byref(BLENDFUNCTION(0, 0, 255, 1)), 2)

    def move(self, x, y):
        self.x, self.y = int(x), int(y)
        self.win.geometry(f"+{self.x}+{self.y}")
        self.show()

    def set_top(self, on):
        flags = 0x1 | 0x2 | 0x10  # NOSIZE | NOMOVE | NOACTIVATE
        if on:
            user32.SetWindowPos(self.hwnd, W.HWND(-1), 0, 0, 0, 0, flags)
        else:
            user32.SetWindowPos(self.hwnd, W.HWND(-2), 0, 0, 0, 0, flags)
            user32.SetWindowPos(self.hwnd, W.HWND(1), 0, 0, 0, 0, flags)

    def destroy(self):
        self._free()
        try:
            self.win.destroy()
        except Exception:
            pass


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
_sig(user32.CallWindowProcW, ctypes.c_ssize_t, ctypes.c_void_p, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
_sig(shell32.DragAcceptFiles, None, W.HWND, W.BOOL)
_sig(shell32.DragQueryFileW, W.UINT, W.HANDLE, W.UINT, W.LPWSTR, W.UINT)
_sig(shell32.DragFinish, None, W.HANDLE)
_sig(user32.ChangeWindowMessageFilterEx, W.BOOL, W.HWND, W.UINT, W.DWORD, ctypes.c_void_p)


class WndHook:
    """يلتقط رسائل ويندوز معيّنة لنافذة Tk (ملفات مسحوبة، اختصارات عامة…) ويمرر الباقي لـ Tk."""

    def __init__(self, hwnd, handlers):
        self.hwnd, self.handlers = hwnd, handlers
        self.proc = WNDPROC(self.wndproc)
        self.old = user32.SetWindowLongPtrW(hwnd, -4, ctypes.cast(self.proc, ctypes.c_void_p).value)

    def wndproc(self, hwnd, msg, wp, lp):
        handler = self.handlers.get(msg)
        if handler is not None:
            result = handler(wp, lp)
            if result is not None:
                return result
        return user32.CallWindowProcW(self.old, hwnd, msg, wp, lp)


class DropTarget(WndHook):
    """يخلي النافذة تستقبل ملفات/تطبيقات مسحوبة من سطح المكتب أو مستكشف الملفات."""

    def __init__(self, hwnd, callback):
        self.callback = callback
        shell32.DragAcceptFiles(hwnd, True)
        for msg in (0x233, 0x4A, 0x49):
            user32.ChangeWindowMessageFilterEx(hwnd, msg, 1, None)
        super().__init__(hwnd, {0x233: self.on_drop})

    def on_drop(self, wp, lp):  # WM_DROPFILES
        n = shell32.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)
        files = []
        for i in range(n):
            buf = ctypes.create_unicode_buffer(1024)
            shell32.DragQueryFileW(wp, i, buf, 1024)
            files.append(buf.value)
        shell32.DragFinish(wp)
        self.callback(files)
        return 0


# ── قوائم البرنامج الحقيقية (للبرامج اللي عندها قوائم ويندوز تقليدية) ──
_sig(user32.GetMenu, W.HMENU, W.HWND)
_sig(user32.GetMenuItemCount, ctypes.c_int, W.HMENU)
_sig(user32.GetMenuStringW, ctypes.c_int, W.HMENU, W.UINT, W.LPWSTR, ctypes.c_int, W.UINT)
_sig(user32.GetSubMenu, W.HMENU, W.HMENU, ctypes.c_int)
_sig(user32.GetMenuItemID, W.UINT, W.HMENU, ctypes.c_int)
_sig(user32.GetMenuState, W.UINT, W.HMENU, W.UINT, W.UINT)
_sig(user32.SendMessageTimeoutW, ctypes.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT,
     P(ctypes.c_size_t))
_sig(user32.RegisterHotKey, W.BOOL, W.HWND, ctypes.c_int, W.UINT, W.UINT)
_sig(user32.UnregisterHotKey, W.BOOL, W.HWND, ctypes.c_int)
MF_BYPOSITION, MF_GRAYED, MF_DISABLED, MF_POPUP, MF_SEPARATOR = 0x400, 0x1, 0x2, 0x10, 0x800


def menu_text(hmenu, i):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetMenuStringW(hmenu, i, buf, 256, MF_BYPOSITION)
    return buf.value.replace("&&", "\0").replace("&", "").replace("\0", "&").strip()


def app_menu_titles(hwnd):
    """عناوين قوائم البرنامج الأمامي (ملف، تحرير…) لو عنده قوائم ويندوز تقليدية."""
    if not hwnd:
        return None
    hm = user32.GetMenu(hwnd)
    if not hm:
        return None
    n = user32.GetMenuItemCount(hm)
    if n <= 0 or n > 16:
        return None
    titles = [menu_text(hm, i) for i in range(n)]
    return [(t, i) for i, t in enumerate(titles) if t] or None


def app_menu_entries(hwnd, index):
    """أوامر قائمة وحدة من البرنامج؛ الضغط ينفذ نفس الأمر داخل البرنامج (WM_COMMAND)."""
    hm = user32.GetMenu(hwnd)
    sub = user32.GetSubMenu(hm, index) if hm else None
    if not sub:
        return []
    res = ctypes.c_size_t()
    user32.SendMessageTimeoutW(hwnd, 0x117, sub, index, 0x2, 300, ctypes.byref(res))  # WM_INITMENUPOPUP
    entries = []
    for j in range(max(0, user32.GetMenuItemCount(sub))):
        state = user32.GetMenuState(sub, j, MF_BYPOSITION)
        if state & MF_SEPARATOR:
            if entries and entries[-1] is not None:
                entries.append(None)
            continue
        label, _, shortcut = menu_text(sub, j).partition("\t")
        text = ar(label) + ("\t" + shortcut if shortcut else "")
        if state & MF_POPUP:
            entries.append((text + ("  ◂" if rtl() else "  ▸"), None))
            continue
        cid = user32.GetMenuItemID(sub, j)
        if state & (MF_GRAYED | MF_DISABLED) or cid in (0, 0xFFFFFFFF):
            entries.append((text, None))
        else:
            entries.append((text, lambda cid=cid: (activate(hwnd), user32.PostMessageW(hwnd, 0x111, cid, 0))))
    while entries and entries[-1] is None:
        entries.pop()
    if not any(e and e[0].split("	")[0].strip() for e in entries):
        return []  # قائمة يرسمها البرنامج بنفسه (بدون نصوص): نرجع لطريقة Alt+حرف
    return entries


class SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]


_sig(shell32.SHQueryRecycleBinW, ctypes.c_long, W.LPCWSTR, P(SHQUERYRBINFO))
_sig(shell32.SHEmptyRecycleBinW, ctypes.c_long, W.HWND, W.LPCWSTR, W.DWORD)


def trash_items():
    info = SHQUERYRBINFO(cbSize=ctypes.sizeof(SHQUERYRBINFO))
    return info.i64NumItems if shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0 else 0


def empty_trash():
    """مثل الماك: يسأل أول، وبعدين يفرغ السلة بصوت الورق."""
    from tkinter import messagebox
    n = trash_items()
    if not n:
        return
    msg = (f"متأكد تبي تحذف {n} عنصر من سلة المهملات نهائياً؟ ما تقدر ترجعها بعدين." if rtl() else
           f"Are you sure you want to permanently erase the {n} item(s) in the Trash? You can’t undo this action.")
    if messagebox.askyesno("Trash", msg):
        shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
        from controlcenter import play
        play("trash")


def is_trash(spec):
    return spec.get("open") == ["shell:RecycleBinFolder"]


class ACCENTPOLICY(ctypes.Structure):
    _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int), ("color", ctypes.c_uint), ("anim", ctypes.c_int)]


class WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [("attr", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]


_sig(user32.SetWindowCompositionAttribute, W.BOOL, W.HWND, P(WINCOMPATTRDATA))


def glass_level():
    return max(0.0, min(1.0, float(SETTINGS.get("glass", 0.45))))


def glass_inset(r, k):
    """ويندوز يدور زوايا التغبيش 8 بكسل بس؛ ندخله شوي داخل الشكل عشان ما يطلع من زوايانا الكبيرة."""
    return int(math.ceil(0.293 * max(0, r - 8 * k))) + 1


class Backdrop:
    """زجاج حقيقي: تغبيش حي من ويندوز (DWM Acrylic) لكل اللي وراه حتى البرامج المفتوحة.
    يشتغل على كرت الشاشة، فما يثقل المعالج. نافذة المحتوى تكون «تابعة» له فتبقى فوقه دائماً."""

    def __init__(self, root, topmost=True, rgb=(18, 18, 22)):
        import tkinter as tk
        win = self.win = tk.Toplevel(root, bg="black")
        win.overrideredirect(True)
        win.geometry("1x1+-32000+-32000")
        if topmost:
            win.attributes("-topmost", True)
        win.update_idletasks()
        self.hwnd = user32.GetParent(win.winfo_id())
        ex = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        corner = ctypes.c_int(2)  # DWMWCP_ROUND
        dwmapi.DwmSetWindowAttribute(self.hwnd, 33, ctypes.byref(corner), 4)
        self.rgb, self.rect, self.visible = rgb, None, True
        self.set_tint()

    def set_tint(self, alpha=None):
        a = int(16 + 112 * glass_level()) if alpha is None else int(alpha)
        r, g, b = self.rgb
        policy = ACCENTPOLICY(4, 2, (a << 24) | (b << 16) | (g << 8) | r, 0)
        data = WINCOMPATTRDATA(19, ctypes.cast(ctypes.pointer(policy), ctypes.c_void_p), ctypes.sizeof(policy))
        user32.SetWindowCompositionAttribute(self.hwnd, ctypes.byref(data))

    def place(self, x, y, w, h):
        rect = (int(x), int(y), max(1, int(w)), max(1, int(h)))
        if rect != self.rect:
            self.rect = rect
            user32.SetWindowPos(self.hwnd, None, *rect, 0x10 | 0x4)  # NOACTIVATE | NOZORDER

    def own(self, surface):
        """نافذة المحتوى تتبع الزجاج (تبقى فوقه وتنزل وتطلع معه)."""
        user32.SetWindowLongPtrW(surface.hwnd, GWLP_HWNDPARENT, self.hwnd)

    def show(self, on):
        if on != self.visible:
            self.visible = on
            user32.ShowWindow(self.hwnd, 8 if on else 0)

    def set_top(self, on):
        flags = 0x1 | 0x2 | 0x10
        user32.SetWindowPos(self.hwnd, W.HWND(-1 if on else -2), 0, 0, 0, 0, flags)
        if not on:
            user32.SetWindowPos(self.hwnd, W.HWND(1), 0, 0, 0, 0, flags)

    def destroy(self):
        try:
            self.win.destroy()
        except Exception:
            pass


_cards = {}


def glass_card(w, h, r, k, rgb=(30, 30, 36), rim=170, center=None, overlay=True):
    """وجه الزجاج فوق التغبيش الحي: الوسط شبه شفاف عشان يبان اللي وراه، والحافة لامعة مثل Liquid Glass."""
    center = int(14 + 70 * glass_level()) if center is None else center
    key = (int(w), int(h), int(r), rgb, rim, center, overlay)
    if key not in _cards:
        if len(_cards) > 60:
            _cards.clear()
        w, h = max(2, int(w)), max(2, int(h))
        d = glass_inset(r, k)
        outer = aa_round(w, h, r, (255, 255, 255, 255)).getchannel("A")
        inner = Image.new("L", (w, h), 0)
        if w > 2 * d and h > 2 * d:
            inner.paste(aa_round(w - 2 * d, h - 2 * d, max(1, r - d), (255, 255, 255, 255)).getchannel("A"), (d, d))
        alpha = ImageChops.subtract(outer.point(lambda v: v * rim // 255), inner.point(lambda v: v * (rim - center) // 255))
        card = Image.new("RGBA", (w, h), rgb + (0,))
        card.putalpha(alpha)
        if overlay:
            card.alpha_composite(glass_overlay(w, h, r, top=200, bottom=60, sheen=36))
        _cards[key] = card
    return _cards[key]


class AppBar:
    """يحجز مكان على حافة الشاشة عشان النوافذ المكبرة ما تغطي الشريط."""

    def __init__(self, hwnd, edge, thickness, mon):
        self.hwnd, self.edge, self.thickness, self.mon = hwnd, edge, thickness, mon
        self.register()

    def register(self):
        m = self.mon
        abd = APPBARDATA(cbSize=ctypes.sizeof(APPBARDATA), hWnd=self.hwnd, uCallbackMessage=0x0400 + 77)
        shell32.SHAppBarMessage(ABM_NEW, ctypes.byref(abd))
        abd.uEdge = self.edge
        if self.edge == ABE_TOP:
            abd.rc = RECT(m.x, m.y, m.x + m.w, m.y + self.thickness)
        else:
            abd.rc = RECT(m.x, m.y + m.h - self.thickness, m.x + m.w, m.y + m.h)
        shell32.SHAppBarMessage(ABM_QUERYPOS, ctypes.byref(abd))
        if self.edge == ABE_TOP:
            abd.rc.bottom = abd.rc.top + self.thickness
        else:
            abd.rc.top = abd.rc.bottom - self.thickness
        shell32.SHAppBarMessage(ABM_SETPOS, ctypes.byref(abd))

    def remove(self):
        abd = APPBARDATA(cbSize=ctypes.sizeof(APPBARDATA), hWnd=self.hwnd)
        shell32.SHAppBarMessage(ABM_REMOVE, ctypes.byref(abd))


# ───────────────────────────── تتبع البرامج المفتوحة ─────────────────────────────

FRIENDLY = {"explorer": "Finder", "msedge": "Microsoft Edge", "chrome": "Google Chrome", "firefox": "Firefox",
            "brave": "Brave", "windowsterminal": "Terminal", "cmd": "Terminal", "powershell": "PowerShell",
            "code": "Code", "notepad": "Notes", "calculatorapp": "Calculator", "systemsettings": "System Settings",
            "taskmgr": "Task Manager", "winword": "Word", "excel": "Excel", "powerpnt": "PowerPoint",
            "pythonw": "Python", "python": "Python", "winstore.app": "App Store", "photos": "Photos",
            "microsoft.photos": "Photos"}
SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow"}


class Tracker:
    def __init__(self):
        self.paths, self.names, self.uwp, self.stamp = {}, {}, {}, time.time()

    def exe(self, pid):
        if time.time() - self.stamp > 60:
            self.paths.clear()
            self.stamp = time.time()
        if pid not in self.paths:
            self.paths[pid] = process_path(pid)
        return self.paths[pid]

    def real_exe(self, hwnd, exe):
        """تطبيقات المتجر (الآلة الحاسبة، الإعدادات…) نافذتها تابعة لـ ApplicationFrameHost؛
        البرنامج الحقيقي نافذة داخلها."""
        if Path(exe).stem.lower() != "applicationframehost":
            return exe
        if hwnd in self.uwp:  # لما تتصغر النافذة الداخلية تختفي، فنتذكرها
            return self.uwp[hwnd]
        frame_pid, found = window_pid(hwnd), []

        def cb(child, _):
            pid = window_pid(child)
            if pid != frame_pid:
                found.append(pid)
                return False
            return True

        user32.EnumChildWindows(hwnd, WNDENUMPROC(cb), 0)
        real = self.exe(found[0]) if found else ""
        if not real:
            return exe
        if len(self.uwp) > 200:
            self.uwp.clear()
        self.uwp[hwnd] = real
        return real

    def app_name(self, exe, title=""):
        stem = Path(exe).stem.lower()
        if stem == "applicationframehost":
            return title
        if stem in FRIENDLY:
            return FRIENDLY[stem]
        if exe not in self.names:
            desc = file_description(exe)
            self.names[exe] = desc or Path(exe).stem.capitalize()
        return self.names[exe]

    def scan(self):
        """البرامج اللي لها نوافذ ظاهرة، مجمعة حسب البرنامج وبترتيب الأحدث."""
        hwnds = []

        def cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):  # GW_OWNER
                return True
            if user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
                return True
            if user32.GetWindowTextLengthW(hwnd) == 0:
                return True
            cloaked = W.DWORD()
            dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)
            if cloaked.value:
                return True
            hwnds.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(cb), 0)
        groups = {}
        for hwnd in hwnds:
            pid = window_pid(hwnd)
            if pid == MY_PID or class_name(hwnd) in SKIP_CLASSES:
                continue
            exe = self.exe(pid)
            if not exe:
                continue
            exe = self.real_exe(hwnd, exe)
            stem = Path(exe).stem.lower()
            title = window_text(hwnd)
            key = f"uwp:{title.lower()}" if stem == "applicationframehost" else exe.lower()
            g = groups.setdefault(key, {"key": key, "exe": exe, "stem": stem, "title": title, "hwnds": []})
            g["hwnds"].append(hwnd)
        return list(groups.values())


def foreground_info(tracker):
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = window_pid(hwnd)
    if pid == MY_PID:
        return None
    if class_name(hwnd) in ("Progman", "WorkerW", "Shell_TrayWnd"):
        return "Finder"
    exe = tracker.exe(pid)
    return tracker.app_name(tracker.real_exe(hwnd, exe), window_text(hwnd)) if exe else None


def fullscreen_rect():
    """إذا البرنامج الأمامي بملء الشاشة (فيلم/لعبة) يرجع مستطيله."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd or window_pid(hwnd) == MY_PID or class_name(hwnd) in SKIP_CLASSES:
        return None
    return window_rect(hwnd)


# ───────────────────────────── أيقونات منطقة الإشعارات ─────────────────────────────

TRAY_SKIP = {"explorer.exe", "securityhealthsystray.exe", "monotificationux.exe", "vsngenrunner.exe",
             "nvcontainer.exe", "nvdisplay.container.exe", "taskmgr.exe", "vcam.broker.exe", "pythonw.exe"}


class TrayIcons:
    """أيقونات البرامج اللي كانت جنب ساعة ويندوز، بصورها الحقيقية."""
    KEY = r"Control Panel\NotifyIconSettings"

    def __init__(self):
        self.entries, self.stamp = [], 0.0

    @staticmethod
    def resolve(path):
        if path.startswith("{") and "}" in path:
            guid, rest = path[1:].split("}", 1)
            base = known_folder("{" + guid + "}")
            if base:
                return base + rest
        return path

    def read(self):
        out, seen = [], set()
        try:
            with winreg.OpenKey(HKCU, self.KEY) as root:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(root, sub) as k:
                            path = winreg.QueryValueEx(k, "ExecutablePath")[0]
                            png = winreg.QueryValueEx(k, "IconSnapShot")[0]
                    except OSError:
                        continue
                    exe = self.resolve(path)
                    base = os.path.basename(exe).lower()
                    if not png or base in TRAY_SKIP or exe.lower() in seen:
                        continue
                    seen.add(exe.lower())
                    try:
                        img = Image.open(io.BytesIO(png)).convert("RGBA")
                    except Exception:
                        continue
                    out.append({"exe": exe, "base": base, "img": img})
        except OSError:
            pass
        return out

    def current(self, running):
        if time.time() - self.stamp > 15:
            self.entries = self.read()
            self.stamp = time.time()
        return [e for e in self.entries if e["base"] in running][:10]


# ───────────────────────────── تطبيقات الـ Dock ─────────────────────────────

APPS_VERSION = 4
APPS_SPEC = {"name": "Apps", "icon": "launchpad", "open": ["app:apps"], "match": ["mac:apps"]}
CALC_SPEC = {"name": "Calculator", "icon": "calculator", "open": ["app:calculator"],
             "match": ["mac:calculator", "calculatorapp"]}
DEFAULT_APPS = [
    {"name": "Finder", "icon": "finder", "open": ["explorer.exe"], "match": ["explorer"]},
    APPS_SPEC,
    {"name": "Browser", "icon": "browser", "open": ["https://www.google.com"],
     "match": ["msedge", "chrome", "firefox", "brave", "opera"]},
    {"name": "Terminal", "icon": "terminal", "open": ["wt.exe", "cmd.exe"],
     "match": ["windowsterminal", "cmd", "powershell", "pwsh"]},
    {"name": "Photos", "icon": "photos", "open": ["ms-photos:"], "match": ["photos", "microsoft.photos"]},
    {"name": "Notes", "icon": "notes", "open": ["notepad.exe"], "match": ["notepad"]},
    CALC_SPEC,
    {"name": "App Store", "icon": "appstore", "open": ["ms-windows-store:"], "match": ["winstore.app"]},
    {"name": "System Settings", "icon": "settings", "open": ["ms-settings:"], "match": ["systemsettings", "settings"]},
    "sep",
    {"name": "Downloads", "icon": "downloads", "open": ["shell:Downloads"]},
    {"name": "Trash", "icon": "trash", "open": ["shell:RecycleBinFolder"]},
]


def taskbar_pins():
    """البرامج المثبتة في شريط مهام ويندوز، عشان ما تضيع لما نخفيه."""
    folder = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"
    pins = []
    for lnk in sorted(folder.glob("*.lnk")) if folder.is_dir() else []:
        exe = lnk_target(lnk)
        if exe and exe.lower().endswith(".exe"):
            pins.append(exe)
    return pins


def exe_spec(exe):
    stem = Path(exe).stem.lower()
    name = FRIENDLY.get(stem) or file_description(exe) or Path(exe).stem.capitalize()
    return {"name": name, "icon": "exe", "exe": exe, "open": [exe], "match": [stem]}


def build_default_apps(keep=()):
    pinned = [dict(a) for a in DEFAULT_APPS[:DEFAULT_APPS.index("sep")]]
    tail = [dict(a) for a in DEFAULT_APPS[DEFAULT_APPS.index("sep") + 1:]]
    known = {t for a in pinned for t in a.get("match", [])}
    for exe in taskbar_pins() + [a["exe"] for a in keep if a.get("exe")]:
        stem = Path(exe).stem.lower()
        if stem not in known and stem != "explorer":
            pinned.append(exe_spec(exe))
            known.add(stem)
    return pinned + ["sep"] + tail


def load_apps():
    try:
        data = json.loads(APPS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if isinstance(data, dict) and data.get("version") == APPS_VERSION:
        apps = data["apps"]
    elif isinstance(data, dict) and data.get("version") == 3:
        # ترقية بدون ما نضيع ترتيب المستخدم
        apps = [dict(APPS_SPEC) if isinstance(a, dict) and a.get("icon") == "launchpad" else
                dict(CALC_SPEC) if isinstance(a, dict) and a.get("icon") == "calculator" else a
                for a in data["apps"]]
        save_apps(apps)
    else:
        old = data.get("apps", []) if isinstance(data, dict) else []
        apps = build_default_apps(keep=[a for a in old if isinstance(a, dict) and a.get("icon") == "exe"])
        save_apps(apps)
    cut = apps.index("sep") if "sep" in apps else len(apps)
    pinned, tail = [], []
    for i, a in enumerate(apps):
        if not isinstance(a, dict):
            continue
        if a.get("icon") == "browser":
            exe = default_browser()
            if exe:
                spec = exe_spec(exe)
                spec["match"] = a.get("match", []) + spec["match"]
                a = dict(a, **spec)
            else:
                a = dict(a, icon="safari")
        (pinned if i < cut else tail).append(dict(a, _i=i))  # _i: مكانه في الملف عشان الحذف
    return pinned, tail


def spec_for_path(path):
    """تطبيق أو ملف أو مجلد انسحب على الـ Dock. يرجع (المواصفات، هل مكانه بعد الفاصل)."""
    path = str(path)
    low = path.lower()
    if os.path.isdir(path):
        return {"name": Path(path).name or path, "icon": "folder", "open": [path]}, True
    if low.endswith(".lnk"):
        exe = lnk_target(path)
        if exe and exe.lower().endswith(".exe"):
            return dict(exe_spec(exe), open=[path]), False
        return {"name": Path(path).stem, "icon": "", "color": "#5e5ce6", "open": [path]}, False
    if low.endswith(".exe"):
        return exe_spec(path), False
    if low.endswith(".url"):
        return {"name": Path(path).stem, "icon": "", "glyph": "E774", "color": "#0a84ff", "open": [path]}, False
    return {"name": Path(path).name, "icon": "", "glyph": "E8A5", "color": "#8e8e93", "open": [path]}, True


def save_apps(apps):
    APPS_FILE.write_text(json.dumps({"version": APPS_VERSION, "apps": apps}, ensure_ascii=False, indent=1),
                         encoding="utf-8")


def matches(spec, g):
    tokens = [t.lower() for t in spec.get("match", [])]
    if spec.get("exe"):
        tokens.append(Path(spec["exe"]).stem.lower())
    if g["stem"] == "applicationframehost":
        return g["title"].lower() in tokens
    return g["stem"] in tokens


# ───────────────────────────── القوائم المنبثقة ─────────────────────────────

class Popup:
    def __init__(self, ui, mon, x, y, entries, on_close=None, above=False, kind="menu"):
        k = mon.k
        self.kind = kind
        self.ui, self.entries, self.on_close = ui, entries, on_close
        self.f = font("segoeui.ttf", round(13.5 * k))
        self.row, self.sep, self.pad = round(25 * k), round(9 * k), round(5 * k)
        tw = max([self.f.getlength(e[0].split("\t")[0]) + (self.f.getlength(e[0].split("\t")[1]) + round(36 * k)
                                                             if "\t" in e[0] else 0) for e in entries if e] + [0])
        self.w = max(round(210 * k), int(tw) + round(44 * k))
        self.h = sum(self.row if e else self.sep for e in entries) + 2 * self.pad
        self.m = round(16 * k)
        self.k = k
        if above:
            y -= self.h
        x = min(max(x, mon.x + 4), mon.x + mon.w - self.w - 4)
        self.sx, self.sy = x - self.m, y - self.m
        self.radius = round(13 * k)
        self.backdrop = Backdrop(ui.root)
        self.surface = Surface(ui.root, self.sx, self.sy, self.w + 2 * self.m, self.h + 2 * self.m)
        self.backdrop.own(self.surface)
        d = glass_inset(self.radius, k)
        self.backdrop.place(self.sx + self.m + d, self.sy + self.m + d, self.w - 2 * d, self.h - 2 * d)
        self.shadow, self.spad = soft_shadow(self.w, self.h, self.radius, round(12 * k), 0.4)
        self.bg = glass_card(self.w, self.h, self.radius, k, (34, 34, 40), rim=200)
        self.hover = -2
        self.born = time.time()
        self.alive = True
        self.surface.win.bind("<ButtonRelease-1>", self.on_click)
        self.render(-1)
        self.poll()

    def rows(self):
        y = self.pad
        for i, e in enumerate(self.entries):
            h = self.row if e else self.sep
            yield i, e, y, h
            y += h

    def index_at(self, x, y):
        if not (0 <= x < self.w and 0 <= y < self.h):
            return -1
        for i, e, ry, h in self.rows():
            if e and e[1] is not None and ry <= y < ry + h:  # بدون فعل = عنوان أو معلومة
                return i
        return -1

    def render(self, hover):
        if hover == self.hover:
            return
        self.hover = hover
        k = self.k
        img = Image.new("RGBA", (self.w + 2 * self.m, self.h + 2 * self.m), (0, 0, 0, 0))
        blit(img, self.shadow, self.m - self.spad, self.m - self.spad + round(4 * k))
        blit(img, self.bg, self.m, self.m)
        for i, e, ry, h in self.rows():
            y = self.m + ry
            if not e:
                ImageDraw.Draw(img).line([(self.m + round(10 * k), y + h // 2), (self.m + self.w - round(10 * k), y + h // 2)],
                                         fill=(255, 255, 255, 34), width=1)
                continue
            if i == hover:
                blit(img, aa_round(self.w - 2 * self.pad, h, round(8 * k), (10, 132, 255, 255)), self.m + self.pad, y)
            color = (245, 245, 247, 255) if e[1] is not None else (165, 165, 172, 255)
            label, _, shortcut = e[0].partition("\t")
            start, end = (self.m + self.w - round(16 * k), "rm"), (self.m + round(16 * k), "lm")
            if not rtl():
                start, end = (self.m + round(16 * k), "lm"), (self.m + self.w - round(16 * k), "rm")
            draw_text(img, (start[0], y + h / 2), label, self.f, color, start[1])
            if shortcut:
                draw_text(img, (end[0], y + h / 2), shortcut, self.f,
                          (255, 255, 255, 200) if i == hover else (150, 150, 158, 255), end[1])
        self.surface.show(img)

    def poll(self):
        if not self.alive:
            return
        cx, cy = cursor()
        lx, ly = cx - self.sx - self.m, cy - self.sy - self.m
        self.render(self.index_at(lx, ly))
        if mouse_down() and time.time() - self.born > 0.15 and not (0 <= lx < self.w and 0 <= ly < self.h):
            self.close()
            return
        self.surface.win.after(25, self.poll)

    def on_click(self, e):
        i = self.index_at(e.x - self.m, e.y - self.m)
        if i >= 0 and self.entries[i] and self.entries[i][1] is not None:
            fn = self.entries[i][1]
            self.close()
            self.ui.root.after(10, fn)

    def close(self):
        if not self.alive:
            return
        self.alive = False
        self.surface.destroy()
        self.backdrop.destroy()
        self.ui.closed(self)
        if self.on_close:
            self.on_close()


# ───────────────────────────── الشريط العلوي ─────────────────────────────

class MenuBar:
    def __init__(self, ui, mon):
        self.ui, self.mon = ui, mon
        k = mon.k
        self.h = round(28 * k)
        self.surface = Surface(ui.root, mon.x, mon.y, mon.w, self.h)
        self.surface.win.bind("<ButtonRelease-1>", self.on_click)
        self.surface.win.bind("<ButtonRelease-3>", self.on_right)
        self.f = font("segoeui.ttf", round(13.5 * k))
        self.fb = font("segoeuib.ttf", round(13.5 * k))
        self.fi = font("SegoeIcons.ttf", round(15 * k))
        self.tray_px = round(16 * k)
        self.tray_imgs = {}
        self.open_item = None
        self.regions = []
        self.state = None
        self.refresh_bg()
        self.bar = AppBar(self.surface.hwnd, ABE_TOP, self.h, mon)

    def refresh_bg(self):
        # شريط شفاف مثل macOS الجديد؛ تظليل خفيف جداً عشان الكتابة تنقرى (وألفا > 0 عشان يستقبل الضغط)
        strip = self.mon.screen.crop((0, 0, self.mon.screen.width, max(1, self.h // 2))).convert("L")
        lum = sum(strip.resize((64, 1)).getdata()) / 64
        top = int(min(150, 60 + max(0, lum - 90) * 0.9))  # خلفية فاتحة = تظليل أكثر عشان الكتابة البيضاء تنقرى
        grad = Image.linear_gradient("L").resize((self.mon.w, self.h)).point(lambda v: int(top - (top - 12) * v / 255))
        self.bg = Image.new("RGBA", (self.mon.w, self.h), (0, 0, 0, 0))
        self.bg.putalpha(grad)
        self.state = None

    def battery_icon(self, pct, charging):
        """بطارية macOS 27 (مثل iOS): كبسولة والنسبة محفورة داخلها."""
        k, ss = self.mon.k, 4
        w, h = round(27 * k), round(13 * k)
        W2, H2 = w * ss, h * ss
        body = W2 - 3 * ss
        img = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, body, H2 - 1), H2 * 0.32, fill=(255, 255, 255, 95))
        d.rounded_rectangle((body + ss, H2 * .34, W2 - 1, H2 * .66), ss, fill=(255, 255, 255, 120))
        col = (52, 199, 89, 255) if charging else ((255, 69, 58, 255) if pct <= 20 else (255, 255, 255, 255))
        shape_ = Image.new("L", (W2, H2), 0)
        ImageDraw.Draw(shape_).rounded_rectangle((0, 0, body, H2 - 1), H2 * 0.32, fill=255)
        level = Image.new("L", (W2, H2), 0)
        ImageDraw.Draw(level).rectangle((0, 0, body * pct / 100, H2), fill=255)
        layer = Image.new("RGBA", (W2, H2), col)
        layer.putalpha(ImageChops.multiply(shape_, level))
        img.alpha_composite(layer)
        num = Image.new("L", (W2, H2), 0)
        ImageDraw.Draw(num).text((body / 2, H2 / 2), str(pct), font=font("segoeuib.ttf", H2 * 0.72), fill=255, anchor="mm")
        img.putalpha(ImageChops.subtract(img.getchannel("A"), num))
        return img.resize((w, h), LANCZOS)

    def cc_icon(self):
        k, ss = self.mon.k, 4
        w, h = round(16 * k), round(14 * k)
        img = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        ph = h * ss * 0.42
        for i, knob_left in ((0, False), (1, True)):
            y0 = i * (h * ss - ph)
            d.rounded_rectangle((ss, y0, w * ss - ss, y0 + ph), ph / 2, outline=(255, 255, 255, 235), width=int(1.5 * ss))
            kx = ss + ph / 2 if knob_left else w * ss - ss - ph / 2
            d.ellipse((kx - ph / 2 + ss, y0 + ss, kx + ph / 2 - ss, y0 + ph - ss), fill=(255, 255, 255, 235))
        return img.resize((w, h), LANCZOS)

    def tray_img(self, e):
        key = (e["exe"], id(e["img"]))
        if key not in self.tray_imgs:
            self.tray_imgs[key] = e["img"].resize((self.tray_px, self.tray_px), LANCZOS)
        return self.tray_imgs[key]

    def render(self, force=False):
        ui = self.ui
        R = rtl()
        clock = clock_text()
        bat = battery()
        tray = ui.tray_now
        state = (ui.app, clock, bat, self.open_item, ui.lang, R, tuple(e["exe"] for e in tray),
                 tuple(ui.menu_titles or ()))
        if state == self.state and not force:
            return
        self.state = state
        k, H, W = self.mon.k, self.h, self.mon.w
        final = self.bg.copy()
        img = Image.new("RGBA", final.size, (0, 0, 0, 0))  # طبقة المحتوى (لها ظل ناعم)
        d = ImageDraw.Draw(img)
        cy = H / 2
        white = (255, 255, 255, 250)
        regions = []
        gap = round(18 * k)

        def X(x0, w):  # مكان منطقي ← فعلي (بالعربي الشريط ينعكس مثل الماك العربي)
            return W - x0 - w if R else x0

        def text(x0, s, fnt, fill=white, dy=0):
            w = fnt.getlength(s)
            d.text((X(x0, w), cy + dy), s, font=fnt, fill=fill, anchor="lm")
            return w

        def region(x0, w, action, pad):
            ax = X(x0, w)
            regions.append((ax - pad, ax + w + pad, action))

        # الشعار (قائمة النظام) واسم البرنامج والقوائم
        x, L = round(18 * k), round(13 * k)
        lx = X(x, L)
        if self.open_item == "logo":
            pill = round(9 * k)
            final.alpha_composite(glass_panel(L + 2 * pill, H - round(6 * k), (H - round(6 * k)) // 2,
                                              (255, 255, 255, 40)), (int(lx - pill), round(3 * k)))
        q, g2 = (L - round(2 * k)) / 2, round(2 * k)
        for i in range(4):
            r, c = divmod(i, 2)
            sx, sy = lx + c * (q + g2), cy - L / 2 + r * (q + g2)
            d.rectangle((sx, sy, sx + q - 1, sy + q - 1), fill=white)
        region(x, L, "logo", round(9 * k))
        x += L + round(20 * k)
        x += text(x, ar(ui.app), self.fb) + round(22 * k)
        if ui.menu_titles:
            for title, idx in ui.menu_titles[:10]:
                w = text(x, ar(title), self.f, (255, 255, 255, 235))
                region(x, w, ("menu", idx), round(9 * k))
                x += w + round(20 * k)
        else:
            for key in ("File", "Edit", "View", "Window", "Help"):
                w = text(x, tr(key), self.f, (255, 255, 255, 235))
                region(x, w, ("alt", key[0]), round(9 * k))
                x += w + round(20 * k)

        # الجهة الثانية: الساعة، مركز التحكم، البحث، اللغة، الواي فاي، البطارية، أيقونات البرامج
        xr = W - round(16 * k)

        def right_text(s, action, fnt, dy=0):
            nonlocal xr
            w = fnt.getlength(s)
            text(xr - w, s, fnt, white, dy)
            region(xr - w, w, action, round(8 * k))
            xr -= w + gap

        def right_img(im, action):
            nonlocal xr
            img.alpha_composite(im, (int(X(xr - im.width, im.width)), int(cy - im.height / 2)))
            region(xr - im.width, im.width, action, round(7 * k))
            xr -= im.width + gap

        right_text(clock, "clock", self.f)
        right_img(self.cc_icon(), "cc")
        right_text("\uE721", "search", font("SegoeIcons.ttf", round(14 * k)))
        right_text(ui.lang, "lang", font("seguisb.ttf", round(12.5 * k)))
        right_text("\uE701", "wifi", self.fi, round(1 * k))
        if bat:
            right_img(self.battery_icon(*bat), "battery")
        for e in tray:
            right_img(self.tray_img(e), ("tray", e))
        self.regions = regions
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        shadow.putalpha(img.getchannel("A").filter(ImageFilter.GaussianBlur(max(1, 1.3 * k))).point(lambda v: int(v * 0.6)))
        final.alpha_composite(shadow)
        final.alpha_composite(img)
        self.surface.show(final)

    def region_at(self, x):
        for x0, x1, action in self.regions:
            if x0 <= x <= x1:
                return x0, x1, action
        return None, None, None

    def on_click(self, e):
        x0, x1, action = self.region_at(e.x)
        if action is None:
            return
        ui, mon, below = self.ui, self.mon, self.mon.y + self.h + round(4 * self.mon.k)
        if isinstance(action, tuple):
            if action[0] == "alt":
                press(VK_MENU, ord(action[1]))
            elif action[0] == "menu":
                if ui.just_closed(f"appmenu{action[1]}"):
                    return
                entries = app_menu_entries(ui.target, action[1])
                if entries:
                    ui.show_popup(mon, mon.x + int(x0), below, entries, kind=f"appmenu{action[1]}")
                else:
                    title = dict((i, t) for t, i in ui.menu_titles or []).get(action[1], "")
                    if title[:1].isascii() and title[:1].isalpha():
                        press(VK_MENU, ord(title[0].upper()))
            else:
                ui.open_tray(action[1])
        elif action == "logo":
            self.open_logo_menu(x0)
        elif action == "clock":
            press(VK_LWIN, ord("N"))
        elif action == "search":
            ui.open_spotlight(mon)
        elif action == "lang":
            press(VK_LWIN, 0x20)
        elif action == "cc":
            ui.open_cc(mon, mon.x + int(x1), below)
        elif action == "wifi":
            ui.open_wifi(mon, mon.x + int(x1))
        elif action == "battery":
            ui.open_battery(mon, mon.x + int(x0), below)

    def on_right(self, e):
        x0, _, action = self.region_at(e.x)
        if isinstance(action, tuple) and action[0] == "tray":
            entry = action[1]
            name = Path(entry["exe"]).stem
            self.ui.show_popup(self.mon, self.mon.x + int(x0), self.mon.y + self.h + round(3 * self.mon.k), [
                (f"{tr('open')} {name}", lambda: self.ui.open_tray(entry)),
                (tr("taskbar"), self.ui.peek_taskbar),
            ])

    def open_logo_menu(self, x):
        ui = self.ui
        if ui.popup:
            ui.popup.close()
            return
        if ui.just_closed("logo"):
            return
        widgets_on = ui.widgets is not None and ui.widgets.visible
        entries = [
            (tr("about_mac"), lambda: ui.open_app("about")),
            None,
            (tr("sys_settings"), lambda: os.startfile("ms-settings:")),
            (tr("mac_settings"), lambda: ui.open_app("settings")),
            (tr("app_store"), lambda: os.startfile("ms-windows-store:")),
            None,
            (tr("start"), lambda: press(VK_LWIN)),
            (tr("mission"), lambda: press(VK_LWIN, 0x09)),
            (tr("show_desktop"), lambda: press(VK_LWIN, ord("D"))),
            (tr("edit_widgets"), ui.open_widget_gallery),
            (tr("hide_widgets") if widgets_on else tr("show_widgets"), ui.toggle_widgets),
            (tr("win_widgets"), lambda: press(VK_LWIN, ord("W"))),
            (tr("taskbar"), ui.peek_taskbar),
            None,
            (tr("force_quit"), lambda: ui.open_app("forcequit")),
            None,
            (tr("lock"), lambda: user32.LockWorkStation()),
            (tr("restart"), lambda: ui.power("/r", ("restart", "إعادة التشغيل"))),
            (tr("shutdown"), lambda: ui.power("/s", ("shut down", "إيقاف التشغيل"))),
            None,
            (tr("quit_ui"), ui.quit),
        ]
        self.open_item = "logo"
        self.render()

        def closed():
            self.open_item = None
            self.render()

        ui.show_popup(self.mon, self.mon.x + int(x), self.mon.y + self.h + round(3 * self.mon.k), entries,
                      on_close=closed, kind="logo")


# ───────────────────────────── الـ Dock ─────────────────────────────

class Dock:
    def __init__(self, ui, mon):
        self.ui, self.mon = ui, mon
        k = mon.k
        self.u = round(int(SETTINGS.get("dock_size", 54)) * k)
        self.gap = round(6 * k)
        self.padv, self.padh = round(7 * k), round(8 * k)
        self.sepw = round(17 * k)
        self.margin = round(5 * k)
        self.mag = 1.6 if SETTINGS.get("magnify", True) else 1.0
        self.panel_h = self.u + 2 * self.padv
        self.H = self.margin + self.panel_h + round(self.u * 0.8) + round(46 * k)
        self.pb = self.H - self.margin
        self.y = mon.y + mon.h - self.H
        self.icons = ui.icons
        self.f = font("segoeui.ttf", round(13 * k))
        self.dot = aa_round(round(4 * k), round(4 * k), round(2 * k), (255, 255, 255, 215))
        self.extras = {}
        self.mx = None
        self.layout = []
        self.panel = (0, 0)
        self.surface = None
        self.W, self.offx = mon.w, 0
        self.reload()
        # النافذة بعرض الـ Dock بس (مو عرض الشاشة كلها) عشان الرسم يكون أخف
        self.backdrop = Backdrop(ui.root, rgb=(28, 28, 34))
        self.surface = Surface(ui.root, mon.x + self.offx, self.y, self.W, self.H)
        self.backdrop.own(self.surface)
        win = self.surface.win
        win.bind("<ButtonPress-1>", self.on_press)
        win.bind("<B1-Motion>", self.on_motion)
        win.bind("<ButtonRelease-1>", self.on_release)
        win.bind("<ButtonRelease-3>", self.on_right)
        self.press = None
        self.drop = DropTarget(win.winfo_id(), lambda files: ui.root.after(0, self.on_drop, files))
        self.refresh_bg()
        self.bar = AppBar(self.surface.hwnd, ABE_BOTTOM, self.panel_h + self.margin, mon)
        self.alive = True
        self.loop()

    # ── بيانات ──
    def reload(self):
        pinned, tail = load_apps()
        self.pinned = [self._item(s, True) for s in pinned]
        self.tail = [self._item(s, True, tail=True) for s in tail]
        self.extras = {}
        self.rebuild()
        if self.ui.groups is not None:
            self.update_running(self.ui.groups)

    @staticmethod
    def _item(spec, pinned, tail=False):
        return {"spec": spec, "pinned": pinned, "tail": tail, "windows": [], "scale": 1.0, "bounce": 0.0}

    def rebuild(self):
        items = list(self.pinned)
        if self.extras:
            items += ["sep"] + list(self.extras.values())
        if self.tail:
            items += ["sep"] + self.tail
        if rtl():
            items.reverse()  # بالعربي: Finder على اليمين وسلة المهملات على اليسار مثل الماك العربي
        self.items = items
        self.dirty = True
        self.fit()

    def fit(self):
        k = self.mon.k
        base = sum(self.width_of(i) for i in self.items) + self.gap * (len(self.items) - 1)
        W = min(self.mon.w, int(base + self.u * (self.mag - 1) * 2.6 + 2 * self.padh + round(140 * k)))
        offx = (self.mon.w - W) // 2
        if (W, offx) == (self.W, self.offx):
            return
        self.W, self.offx = W, offx
        if self.surface:
            s = self.surface
            s.x, s.w = self.mon.x + offx, W
            s.win.geometry(f"{W}x{self.H}+{s.x}+{self.y}")

    def update_running(self, groups):
        used = set()
        changed = False
        for it in self.pinned:
            wins = []
            for g in groups:
                if g["key"] not in used and matches(it["spec"], g):
                    wins += g["hwnds"]
                    used.add(g["key"])
            if wins != it["windows"]:
                it["windows"] = wins
                changed = True
        live = {}
        for g in groups:
            if g["key"] in used:
                continue
            it = self.extras.get(g["key"])
            if it is None:
                if g["stem"] == "applicationframehost":
                    spec = {"name": self.ui.tracker.app_name(g["exe"], g["title"]), "icon": "", "color": "#5e5ce6"}
                else:
                    spec = exe_spec(g["exe"])
                it = self._item(spec, False)
                changed = True
            if it["windows"] != g["hwnds"]:
                it["windows"] = g["hwnds"]
                changed = True
            live[g["key"]] = it
        if list(live) != list(self.extras):
            changed = True
        self.extras = live
        if changed:
            self.rebuild()

    # ── رسم ──
    def refresh_bg(self):
        self.backdrop.set_tint()
        self.dirty = True

    def width_of(self, it):
        return self.sepw if it == "sep" else self.u

    def panel_parts(self):
        """وجه الزجاج ينرسم مرة وحدة بعرض صغير، وبعدين ينمط لأي عرض."""
        if not hasattr(self, "_parts"):
            k = self.mon.k
            r = round(26 * k)
            ref = 4 * r
            body = glass_card(ref, self.panel_h, r, k, (40, 40, 46), rim=150)
            shadow, pad = soft_shadow(ref, self.panel_h, r, round(14 * k), 0.3)
            self._parts = (r, ref, body, shadow, pad)
        return self._parts

    @staticmethod
    def stretch(ref, w, cap):
        """يمد صورة: الطرفين ثابتين والوسط ينمط."""
        h = ref.height
        out = Image.new(ref.mode, (w, h))
        out.paste(ref.crop((0, 0, cap, h)), (0, 0))
        out.paste(ref.crop((ref.width - cap, 0, ref.width, h)), (w - cap, 0))
        if w > 2 * cap:
            out.paste(ref.crop((cap, 0, cap + 1, h)).resize((w - 2 * cap, h)), (cap, 0))
        return out

    def panel_image(self, px0, w):
        r, ref, body, shadow, pad = self.panel_parts()
        w = max(w, 2 * r + 2)
        k = self.mon.k
        d = glass_inset(r, k)
        self.backdrop.place(self.surface.x + px0 + d, self.y + self.pb - self.panel_h + d, w - 2 * d,
                            self.panel_h - 2 * d)
        return self.stretch(body, w, r + 1), self.stretch(shadow, w + 2 * pad, r + pad + 1), pad

    def targets(self):
        base = [self.width_of(i) for i in self.items]
        total = sum(base) + self.gap * (len(base) - 1)
        x = (self.W - total) / 2
        out = []
        for it, w in zip(self.items, base):
            if it == "sep" or self.mx is None:
                out.append(1.0)
            else:
                d = abs(self.mx - (x + w / 2)) / (self.u * 2.4)
                out.append(1 + (self.mag - 1) * ((math.cos(math.pi * d) + 1) / 2 if d < 1 else 0))
            x += w + self.gap
        return out

    def step(self):
        """يحرك التكبير بنعومة. يرجع True إذا فيه حركة."""
        moving = False
        now = time.time()
        for it, t in zip(self.items, self.targets()):
            if it == "sep":
                continue
            diff = t - it["scale"]
            if abs(diff) > 0.003:
                it["scale"] += diff * 0.38
                moving = True
            elif diff:
                it["scale"] = t
                moving = True
            if it["bounce"]:
                moving = True
                if now - it["bounce"] > 1.0:
                    it["bounce"] = 0.0
        return moving

    def render(self):
        k, sw = self.mon.k, self.W
        now = time.time()
        widths = [self.sepw if it == "sep" else self.u * it["scale"] for it in self.items]
        total = sum(widths) + self.gap * (len(widths) - 1)
        x = (sw - total) / 2
        px0 = int(x - self.padh)
        pw = int(total + 2 * self.padh + 1) // 2 * 2
        self.panel = (px0, px0 + pw)
        body, shadow, pad = self.panel_image(px0, pw)
        img = Image.new("RGBA", (sw, self.H), (0, 0, 0, 0))
        blit(img, shadow, px0 - pad, self.pb - self.panel_h - pad + round(3 * k))
        blit(img, body, px0, self.pb - self.panel_h)
        d = ImageDraw.Draw(img)
        layout, hovered = [], None
        drag = self.press["it"] if self.press and self.press.get("drag") else None
        for it, w in zip(self.items, widths):
            if it is drag:
                layout.append((x, x + w, self.pb - self.padv - w, it))
                x += w + self.gap
                continue
            if it == "sep":
                cx = int(x + w / 2)
                d.line([(cx, self.pb - self.panel_h + self.padv + round(4 * k)), (cx, self.pb - self.padv - round(4 * k))],
                       fill=(255, 255, 255, 70), width=max(1, round(k)))
            else:
                bounce = 0.0
                if it["bounce"]:
                    t = now - it["bounce"]
                    bounce = self.u * 0.5 * abs(math.sin(math.pi * t / 0.5)) if t < 1.0 else 0.0
                px = round(w * RES / BODY)
                icon = self.icons.get(it["spec"], px)
                cy = self.pb - self.padv - bounce - w / 2
                blit(img, icon, x + w / 2 - px / 2, cy - px / 2)
                if it["windows"]:
                    blit(img, self.dot, x + w / 2 - self.dot.width / 2, self.pb - round(4 * k) - self.dot.height / 2)
                layout.append((x, x + w, cy - w / 2, it))
                if self.mx is not None and x <= self.mx <= x + w + self.gap:
                    hovered = (x + w / 2, cy - w / 2, it)
            x += w + self.gap
        if drag:
            px = round(self.u * RES / BODY)
            icon = self.icons.get(drag["spec"], px)
            dx, dy = self.press["cx"], min(self.press["cy"], self.pb - self.padv - self.u / 2)
            blit(img, icon, dx - px / 2, max(-px * 0.3, dy - px / 2))
            if self.press.get("out"):
                hovered = (dx, max(round(30 * k), dy - self.u / 2), {"spec": {"name": tr("remove_dock")}})
            else:
                hovered = None
        if hovered and not (self.ui.popup and self.ui.popup.alive):
            cx, top, it = hovered
            name = app_name(it["spec"])
            tw = int(self.f.getlength(name)) + round(22 * k)
            th = round(25 * k)
            pill = glass_panel(tw, th, th // 2, (34, 34, 40, 215)).copy()
            draw_text(pill, (tw / 2, th / 2), name, self.f, (245, 245, 247, 255), "mm")
            blit(img, pill, min(max(cx - tw / 2, 0), self.W - tw), max(0, top - th - round(10 * k)))
        self.layout = layout
        self.surface.show(img)

    def loop(self):
        if not self.alive:
            return
        mon = self.mon
        fast = False
        if not self.ui.hidden.get(id(mon)):
            cx, cy = cursor()
            if mon.x <= cx < mon.x + mon.w and mon.y <= cy < mon.y + mon.h:
                self.ui.hot_corner(mon, cx, cy)
            lx = cx - self.surface.x
            top = mon.y + mon.h - self.margin - self.panel_h
            if any(it != "sep" and it["scale"] > 1.05 for it in self.items):
                top -= self.u * (self.mag - 1)
            px0, px1 = self.panel
            inside = px0 <= lx <= px1 and top <= cy < mon.y + mon.h
            mx = lx if inside else None
            if mx != self.mx:
                self.mx = mx
                self.dirty = True
            if self.step() or self.dirty:
                self.dirty = False
                self.render()
                fast = True
            else:
                fast = self.mx is not None
        self.surface.win.after(16 if fast else 120, self.loop)

    # ── تفاعل ──
    def item_at(self, x, y):
        for x0, x1, top, it in self.layout:
            if x0 - self.gap / 2 <= x <= x1 + self.gap / 2 and y >= top - 4:
                return it
        return None

    # ضغط/سحب: الضغط العادي يفتح، والسحب يرتب، والسحب لفوق يشيل التطبيق (مثل الماك)
    def on_press(self, e):
        it = self.item_at(e.x, e.y)
        self.press = {"it": it, "x": e.x, "y": e.y, "drag": False} if it else None

    def on_motion(self, e):
        p = self.press
        if not p:
            return
        it = p["it"]
        if not p["drag"]:
            if abs(e.x - p["x"]) + abs(e.y - p["y"]) < round(8 * self.mon.k) or not it["pinned"] or it["tail"]:
                return
            p["drag"] = True
        p["cx"], p["cy"] = e.x, e.y
        p["out"] = e.y < self.pb - self.panel_h - self.u * 0.9
        centers = {id(i): (x0 + x1) / 2 for x0, x1, _, i in self.layout}
        shown = [i for i in self.items if i != "sep" and i["pinned"] and not i["tail"]]
        others = [i for i in shown if i is not it]
        idx = sum(1 for i in others if centers.get(id(i), 0) < e.x)
        new = others[:idx] + [it] + others[idx:]
        if new != shown:
            self.pinned = list(reversed(new)) if rtl() else new
            self.rebuild()
        self.dirty = True

    def on_release(self, e):
        p, self.press = self.press, None
        if not p:
            return
        if not p["drag"]:
            self.on_click(e)
            return
        if p.get("out") and p["it"] in self.pinned:
            self.pinned.remove(p["it"])
        self.save_pinned()

    def on_drop(self, files):
        """ملفات/تطبيقات انسحبت على الـ Dock: التطبيقات قبل الفاصل، والمجلدات والملفات بعده."""
        cx, _ = cursor()
        lx = cx - self.surface.x
        centers = sorted((x0 + x1) / 2 for x0, x1, _, i in self.layout if i["pinned"] and not i["tail"])
        idx = sum(1 for c in centers if c < lx)
        if rtl():
            idx = len(centers) - idx
        raw = self._raw()
        cut = raw.index("sep") if "sep" in raw else len(raw)
        pinned_raw, tail_raw = self.pinned_raw(raw, cut), raw[cut + 1:]
        for f in files:
            spec, after_sep = spec_for_path(f)
            if after_sep:
                tail_raw.insert(max(0, len(tail_raw) - 1), spec)  # قبل سلة المهملات
            else:
                pinned_raw.insert(min(idx, len(pinned_raw)), spec)
                idx += 1
        save_apps(pinned_raw + ["sep"] + tail_raw)
        self.ui.reload_docks()

    def pinned_raw(self, raw, cut):
        out = []
        for it in self.pinned:
            i = it["spec"].get("_i")
            out.append(raw[i] if isinstance(i, int) and 0 <= i < cut else
                       {k: v for k, v in it["spec"].items() if k != "_i"})
        return out

    def save_pinned(self):
        raw = self._raw()
        cut = raw.index("sep") if "sep" in raw else len(raw)
        save_apps(self.pinned_raw(raw, cut) + ["sep"] + raw[cut + 1:])
        self.ui.reload_docks()

    def on_click(self, e):
        it = self.item_at(e.x, e.y)
        if not it:
            return
        wins = [h for h in it["windows"] if user32.IsWindowVisible(h)]
        if wins:
            fg = user32.GetForegroundWindow()
            if fg in wins:
                if len(wins) > 1:
                    activate(wins[(wins.index(fg) + 1) % len(wins)])
                else:
                    user32.ShowWindow(fg, 6)  # SW_MINIMIZE
            else:
                activate(wins[0])
            return
        spec = it["spec"]
        targets = spec.get("open") or ([spec["exe"]] if spec.get("exe") else [])
        if open_target(targets):
            if not it["tail"]:
                it["bounce"] = time.time()
                self.dirty = True
        else:
            from tkinter import messagebox
            messagebox.showwarning("Dock", (f"ما قدرت أفتح {spec.get('name', '')}" if rtl() else
                                            f"Couldn’t open {spec.get('name', '')}"))
            return
        if targets and targets[0].startswith("app:"):
            it["bounce"] = time.time()

    def on_right(self, e):
        ui = self.ui
        it = self.item_at(e.x, e.y)
        entries = []
        if it:
            spec = it["spec"]
            if it["windows"]:
                entries.append((tr("show"), lambda: activate(it["windows"][0])))
                entries.append((tr("quit"), lambda: [user32.PostMessageW(h, 0x0010, 0, 0) for h in it["windows"]]))
            else:
                entries.append((tr("open"), lambda: open_target(spec.get("open") or [spec.get("exe", "")])))
            if it["pinned"]:
                entries += [None, (tr("remove_dock"), lambda: self.unpin(it))]
            elif spec.get("exe"):
                entries += [None, (tr("keep_dock"), lambda: self.pin(it))]
            entries.append(None)
        if it and is_trash(it["spec"]) and trash_items():
            entries = [entries[0], (ar("إفراغ سلة المهملات…") if rtl() else "Empty Trash…", empty_trash), None]
        entries += [(tr("add_app"), lambda: ui.open_app("apps_add")),
                    (tr("mac_settings"), lambda: ui.open_app("settings")), None, (tr("quit_ui"), ui.quit)]
        ui.show_popup(self.mon, self.surface.x + e.x - round(20 * self.mon.k),
                      self.y + self.pb - self.panel_h - round(10 * self.mon.k), entries, above=True)

    @staticmethod
    def _raw():
        try:
            return json.loads(APPS_FILE.read_text(encoding="utf-8"))["apps"]
        except (OSError, ValueError, KeyError):
            return build_default_apps()

    def pin(self, it):
        raw = self._raw()
        raw.insert(raw.index("sep") if "sep" in raw else len(raw), exe_spec(it["spec"]["exe"]))
        save_apps(raw)
        self.ui.reload_docks()

    def unpin(self, it):
        raw = self._raw()
        i = it["spec"].get("_i")
        if isinstance(i, int) and 0 <= i < len(raw) and raw[i] != "sep":
            del raw[i]
            save_apps(raw)
        self.ui.reload_docks()

    def destroy(self):
        self.alive = False
        self.bar.remove()
        self.surface.destroy()
        self.backdrop.destroy()


# ───────────────────────────── التشغيل ─────────────────────────────

class Desktop:
    def __init__(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.popup = None
        self.tracker = Tracker()
        self.tray = TrayIcons()
        self.icons = Icons()
        self.groups = None
        self.app, self.lang, self.tray_now = "Finder", input_language(), []
        self.running = running_exes()
        self.hidden = {}
        self.peek = None
        self.widgets = None
        self.menubars, self.docks = [], []
        self.tray_hwnd = user32.FindWindowW("Shell_TrayWnd", None)
        self.slow_count = 0
        from controlcenter import Audio
        self.audio = Audio()
        self.wifi_cache, self.bright_cache, self.apps = None, None, None
        self.apps_open = {}
        self.target, self.menu_titles = None, None
        self.hotkeys = WndHook(self.root.winfo_id(), {0x312: self.on_hotkey})
        hk = self.root.winfo_id()
        user32.RegisterHotKey(hk, 1, 0x1 | 0x4000, 0x20)        # Alt+Space ← Spotlight (مثل Cmd+Space)
        user32.RegisterHotKey(hk, 2, 0x2 | 0x1 | 0x4000, 0x1B)  # Ctrl+Alt+Esc ← إنهاء إجباري (مثل Cmd+Opt+Esc)
        global APP_HANDLER
        APP_HANDLER = self.open_app
        self.switcher, self.hud = None, None
        try:
            from keyboard_hook import KeyHook
            self.keys = KeyHook(SETTINGS)
        except Exception:
            self.keys = None
        self.root.after(30, self.poll_keys)
        threading.Thread(target=self.preload, daemon=True).start()
        self.build()
        self.tick_fast()
        self.tick_slow()

    def preload(self):
        """أشياء بطيئة نجهزها بالخلفية: فهرس التطبيقات لـ Spotlight، الواي فاي، السطوع."""
        import controlcenter as cc
        self.apps = cc.app_index()
        self.wifi_cache = cc.wifi_status()
        self.bright_cache = cc.get_brightness()

    # ── بناء الواجهة لكل شاشة ──
    def build(self):
        self.mons = monitors()
        self.mon_sig = [m.rect for m in self.mons]
        for m in self.mons:
            m.load_wallpaper()
        self.menubars = [MenuBar(self, m) for m in self.mons]
        self.docks = [Dock(self, m) for m in self.mons]
        for mb in self.menubars:
            mb.render(force=True)
        from widgets import Widgets
        dock = self.docks[0]
        self.widgets = Widgets(self, self.mons[0], self.menubars[0].h, dock.panel_h + dock.margin)
        show_taskbar(False)

    def teardown(self):
        if self.popup:
            self.popup.close()
        for mb in self.menubars:
            mb.bar.remove()
            mb.surface.destroy()
        for d in self.docks:
            d.destroy()
        if self.widgets:
            self.widgets.shutdown()
        self.menubars, self.docks, self.widgets = [], [], None

    def show_popup(self, mon, x, y, entries, on_close=None, above=False, kind="menu"):
        if self.popup:
            self.popup.close()
        self.popup = Popup(self, mon, x, y, entries, on_close=on_close, above=above, kind=kind)

    def closed(self, obj):
        if self.popup is obj:
            self.popup = None
        self.last_close = (getattr(obj, "kind", type(obj).__name__), time.time())

    def just_closed(self, kind):
        """ضغطة على نفس الزر وهو مفتوح = تسكير (مو فتح من جديد)."""
        k, t = getattr(self, "last_close", (None, 0))
        return k == kind and time.time() - t < 0.45

    def reload_docks(self):
        for d in self.docks:
            d.reload()

    # ── تطبيقاتنا (الحاسبة، حول هذا الماك، الإعدادات، التطبيقات) ──
    APP_NAMES = {"calculator": "Calculator", "about": ("System Information", "معلومات النظام"),
                 "forcequit": ("Force Quit", "إنهاء إجباري"),
                 "settings": ("Mac Settings", "إعدادات واجهة ماك")}

    def open_app(self, key):
        from macapps import APPS, AppsLauncher
        add = key == "apps_add"
        key = "apps" if add else key
        w = self.apps_open.get(key)
        if w and w.alive:
            if isinstance(w, AppsLauncher):
                w.close()
            else:
                w.focus()
                return
        try:
            self.apps_open[key] = AppsLauncher(self, add_mode=add) if key == "apps" else APPS[key](self)
        except Exception:
            import traceback
            (HERE / "mac_error.log").write_text(traceback.format_exc(), encoding="utf-8")

    def app_closed(self, key):
        self.apps_open.pop(key, None)

    def app_groups(self):
        return [{"key": "mac:" + k, "stem": "mac:" + k, "exe": "", "title": w.title, "hwnds": [w.hwnd]}
                for k, w in self.apps_open.items() if w.alive and w.listed]

    def app_title(self, hwnd):
        for k, w in self.apps_open.items():
            if w.alive and w.listed and w.hwnd == hwnd:
                name = self.APP_NAMES.get(k, k)
                if isinstance(name, tuple):
                    return ar(name[1]) if rtl() else name[0]
                return app_name({"name": name})
        return None

    def hot_corner(self, mon, cx, cy):
        """الزوايا النشطة مثل الماك: الماوس في زاوية الشاشة لثلث ثانية = إجراء."""
        e = 2
        key = None
        if cy <= mon.y + e:
            key = "tl" if cx <= mon.x + e else "tr" if cx >= mon.x + mon.w - 1 - e else None
        elif cy >= mon.y + mon.h - 1 - e:
            key = "bl" if cx <= mon.x + e else "br" if cx >= mon.x + mon.w - 1 - e else None
        state = getattr(self, "_corner", (None, 0, False))
        if key is None or mouse_down():
            if key is None:
                self._corner = (None, 0, False)
            return
        if state[0] != key:
            self._corner = (key, time.time(), False)
            return
        if state[2] or time.time() - state[1] < 0.3:
            return
        self._corner = (key, state[1], True)
        action = (SETTINGS.get("hot_corners") or {}).get(key, "")
        if action == "mission":
            press(VK_LWIN, 0x09)
        elif action == "desktop":
            press(VK_LWIN, ord("D"))
        elif action == "spotlight":
            self.open_spotlight(mon)
        elif action == "apps":
            self.open_app("apps")
        elif action == "lock":
            user32.LockWorkStation()

    def poll_keys(self):
        """أحداث الكيبورد من خيط الالتقاط (نتعامل معها هنا لأن الرسم لازم يكون في خيط الواجهة)."""
        import queue
        if self.keys:
            try:
                while True:
                    self.on_key_event(self.keys.events.get_nowait())
            except queue.Empty:
                pass
            except Exception:
                pass
        self.root.after(30, self.poll_keys)

    def on_key_event(self, ev):
        import overlays
        kind = ev[0]
        if kind == "apps":
            self.open_app("apps")
        elif kind in ("switch_next", "switch_prev"):
            step = 1 if kind == "switch_next" else -1
            if self.switcher and self.switcher.alive:
                self.switcher.step(step)
            else:
                self.switcher = overlays.AppSwitcher(self, step)
        elif kind == "switch_commit" and self.switcher and self.switcher.alive:
            self.switcher.commit()
        elif kind == "switch_cancel" and self.switcher:
            self.switcher.close()
        elif kind == "volume":
            if not self.hud:
                self.hud = overlays.VolumeHUD(self)
            self.hud.change(ev[1])
        elif kind == "quicklook":
            old = self.apps_open.get("quicklook")
            if old and old.alive:
                old.close()
            else:
                overlays.open_quicklook(self, ev[1])

    def on_hotkey(self, wp, lp):  # WM_HOTKEY
        if wp == 1:
            from macapps import monitor_at_cursor
            self.root.after(0, lambda: self.open_spotlight(monitor_at_cursor(self)))
        elif wp == 2:
            self.root.after(0, lambda: self.open_app("forcequit"))
        return 0

    def check_dynamic_wallpaper(self, force=False):
        """مثل خلفيات الماك الديناميكية: نسخة النهار من 6 الصبح لين 6 المغرب، والليل بعدها."""
        now = time.time()
        if not force and now - getattr(self, "_dyn_check", 0) < 60:
            return
        self._dyn_check = now
        if not SETTINGS.get("dynamic_wp", False):
            return
        import wallpapers
        current = wallpaper_info()[0]
        pair = wallpapers.dynamic_pair(SETTINGS.get("wallpaper") or current)
        if not pair:
            return
        want = pair[0] if 6 <= time.localtime().tm_hour < 18 else pair[1]
        if Path(current).stem != want.stem:
            set_wallpaper(want)

    def open_widget_gallery(self):
        if self.widgets:
            self.widgets.open_gallery()

    def apply_settings(self):
        """إعدادات تغيرت (لغة، حجم Dock، زجاج…): نعيد بناء الواجهة بسرعة."""
        self.teardown()
        self.build()
        for w in list(self.apps_open.values()):
            if w.alive:
                w.render()

    def check_ipc(self):
        """أوامر جاية من قائمة الزر الأيمن على سطح المكتب (mac.py ipc …)."""
        f = HERE / "ipc.txt"
        if not f.exists():
            return
        try:
            cmd = f.read_text(encoding="utf-8").strip()
            f.unlink()
        except OSError:
            return
        if cmd == "edit_widgets":
            self.open_widget_gallery()
        elif cmd in ("settings", "about", "calculator", "apps", "forcequit"):
            self.open_app(cmd)
        elif cmd == "dump":
            self.dump_state()
        elif cmd == "close_all":
            if self.popup:
                self.popup.close()
            if self.widgets and self.widgets.gallery:
                self.widgets.gallery.close()
            for w in list(self.apps_open.values()):
                if w.alive:
                    w.close()

    def dump_state(self):
        """للاختبار: أماكن أزرار الشريط والـ Dock والنوافذ المفتوحة (debug_state.json)."""
        data = {"popup": type(self.popup).__name__ if self.popup else None,
                "apps_open": [k for k, w in self.apps_open.items() if w.alive],
                "switcher": bool(self.switcher and self.switcher.alive),
                "hud": bool(self.hud and self.hud.glass and self.hud.glass.alive),
                "gallery": bool(self.widgets and self.widgets.gallery and self.widgets.gallery.alive),
                "widgets": len(self.widgets.items) if self.widgets else 0,
                "app": self.app, "menu_titles": self.menu_titles, "menubars": [], "docks": []}
        for mb in self.menubars:
            data["menubars"].append({"rect": mb.mon.rect, "h": mb.h, "regions": [
                [mb.mon.x + x0, mb.mon.x + x1, a if isinstance(a, str) else f"{a[0]}:{a[1] if a[0] != 'tray' else ''}"]
                for x0, x1, a in mb.regions]})
        for d in self.docks:
            data["docks"].append({"rect": d.mon.rect, "items": [
                [round(d.surface.x + (x0 + x1) / 2), round(d.y + d.pb - d.padv - d.u / 2), it["spec"].get("name", "")]
                for x0, x1, top, it in d.layout]})
        (HERE / "debug_state.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── متابعة ──
    def tick_fast(self):
        """كل ثانية: اسم البرنامج الأمامي، اللغة، الساعة، ملء الشاشة."""
        self.check_dynamic_wallpaper()
        fg = user32.GetForegroundWindow()
        if fg and window_pid(fg) != MY_PID and class_name(fg) not in SKIP_CLASSES:
            self.target = fg  # البرنامج اللي قوائمه تطلع في الشريط
            self.menu_titles = app_menu_titles(fg)
        elif fg and window_pid(fg) != MY_PID:
            self.target, self.menu_titles = None, None
        name = self.app_title(fg) or foreground_info(self.tracker)
        if name:
            self.app = name
        self.check_ipc()
        self.lang = input_language()
        full = fullscreen_rect()
        for m, mb, d in zip(self.mons, self.menubars, self.docks):
            covers = bool(full and full[0] <= m.x and full[1] <= m.y and full[2] >= m.x + m.w and full[3] >= m.y + m.h)
            if covers != self.hidden.get(id(m), False):
                self.hidden[id(m)] = covers
                mb.surface.set_top(not covers)
                d.backdrop.set_top(not covers)
                d.backdrop.show(not covers)
            mb.render()
        self.watch_peek()
        self.root.after(1000, self.tick_fast)

    def tick_slow(self):
        """كل ثانيتين: البرامج المفتوحة، الإشعارات، تغيّر الشاشات أو الخلفية."""
        try:
            self.groups = self.tracker.scan() + self.app_groups()
            for d in self.docks:
                d.update_running(self.groups)
            self.slow_count += 1
            if self.slow_count % 2 == 0:  # قائمة البرامج كلها كل 4 ثواني تكفي
                self.running = running_exes()
                self.tray_now = self.tray.current(self.running)
        except Exception:
            pass
        rare = self.slow_count % 3 == 0  # الشاشات والخلفية كل 6 ثواني
        if rare and [m.rect for m in monitors()] != self.mon_sig:
            self.teardown()
            self.build()
        else:
            tray = user32.FindWindowW("Shell_TrayWnd", None)
            if tray and tray != self.tray_hwnd:  # مستكشف الملفات انعاد تشغيله
                self.tray_hwnd = tray
                for s in self.menubars + self.docks:
                    s.bar.register()
                if self.widgets:
                    self.widgets.reattach()
            if not self.peek:
                show_taskbar(False)
            if rare:
                full = trash_items() > 0
                for d in self.docks:
                    for it in d.tail:
                        if is_trash(it["spec"]) and (it["spec"].get("icon") == "trash_full") != full:
                            it["spec"]["icon"] = "trash_full" if full else "trash"
                            d.dirty = True
            sig = wallpaper_info() if rare else self.mons[0].wp_sig
            if sig != self.mons[0].wp_sig:
                for m, mb, d in zip(self.mons, self.menubars, self.docks):
                    m.load_wallpaper()
                    mb.refresh_bg()
                    d.refresh_bg()
                if self.widgets:
                    self.widgets.refresh_bg()
        self.root.after(2000, self.tick_slow)

    # ── أفعال ──
    def open_tray(self, entry):
        for g in self.groups or []:
            if g["exe"].lower() == entry["exe"].lower():
                activate(g["hwnds"][0])
                return
        open_target([entry["exe"]])

    def peek_taskbar(self):
        """يظهر شريط ويندوز الحقيقي مؤقتاً (لقوائم أيقونات الإشعارات)."""
        show_taskbar(True)
        press(VK_LWIN, ord("B"))
        self.peek = {"start": time.time(), "away": None}

    def watch_peek(self):
        if not self.peek:
            return
        now = time.time()
        cx, cy = cursor()
        inside = any(l <= cx < r and t <= cy < b for l, t, r, b in (window_rect(h) for h in taskbar_windows()))
        if inside or mouse_down() or now - self.peek["start"] < 3:
            self.peek["away"] = None
        elif self.peek["away"] is None:
            self.peek["away"] = now
        elif now - self.peek["away"] > 2:
            self.peek = None
            show_taskbar(False)

    def toggle_widgets(self):
        if self.widgets:
            self.widgets.toggle()

    def _replace_popup(self, obj_factory):
        if self.popup:
            self.popup.close()
        self.popup = obj_factory()

    def open_cc(self, mon, right_x, y):
        from controlcenter import ControlCenter
        if isinstance(self.popup, ControlCenter) and self.popup.alive:
            self.popup.close()
            return
        if self.just_closed("ControlCenter"):
            return
        self._replace_popup(lambda: ControlCenter(self, mon, right_x, y))

    def open_spotlight(self, mon):
        from controlcenter import Spotlight
        if isinstance(self.popup, Spotlight) and self.popup.alive:
            self.popup.close()
            return
        if self.just_closed("Spotlight"):
            return
        self._replace_popup(lambda: Spotlight(self, mon))

    def open_battery(self, mon, x, y):
        from controlcenter import battery_entries
        if self.just_closed("battery"):
            return
        self.show_popup(mon, x, y, battery_entries(), kind="battery")

    def open_wifi(self, mon, right_x):
        """قائمة الواي فاي تنزل من الشريط (نجيب الشبكات بالخلفية عشان ما يعلق)."""
        import controlcenter as cc
        if self.popup:
            self.popup.close()
        if self.just_closed("wifi"):
            return
        box = {}

        def work():
            box["status"] = cc.wifi_status()
            box["nets"] = cc.wifi_networks()

        def show():
            if "nets" not in box:
                self.root.after(60, show)
                return
            self.wifi_cache = box["status"]
            entries = cc.wifi_entries(box["status"], box["nets"], self)
            w = round(260 * mon.k)
            self.show_popup(mon, right_x - w, mon.y + round(32 * mon.k), entries, kind="wifi")

        threading.Thread(target=work, daemon=True).start()
        show()

    def power(self, flag, label):
        from tkinter import messagebox
        msg = (f"متأكد تبي {label[1]}؟ احفظ شغلك أول." if rtl() else
               f"Are you sure you want to {label[0]} now? Save your work first.")
        if messagebox.askyesno("Mac Interface", msg):
            subprocess.Popen(["shutdown", flag, "/t", "0"])

    def quit(self):
        if self.keys:
            self.keys.stop()
        for i in (1, 2):
            user32.UnregisterHotKey(self.root.winfo_id(), i)
        self.teardown()
        show_taskbar(True)
        self.root.destroy()

    def run(self):
        try:
            self.root.mainloop()
        finally:
            show_taskbar(True)
            for s in self.menubars + self.docks:
                try:
                    s.bar.remove()
                except Exception:
                    pass


def run():
    try:
        shcore.SetProcessDpiAwareness(2)
    except Exception:
        user32.SetProcessDPIAware()
    import atexit
    atexit.register(show_taskbar, True)
    Desktop().run()
