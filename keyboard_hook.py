"""
keyboard_hook.py — a low-level keyboard hook that makes a few keys behave like a Mac:

- Windows key alone  -> Apps (instead of the Start menu)
- Alt+Tab            -> the Mac app switcher
- volume keys        -> the Mac volume HUD
- Space in Explorer  -> Quick Look

It runs on its own thread and only makes quick decisions; every other key passes through untouched.
"""
import ctypes
import queue
import threading
from ctypes import wintypes as W

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32")


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", W.DWORD), ("scanCode", W.DWORD), ("flags", W.DWORD), ("time", W.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("flags", W.DWORD), ("hwndActive", W.HWND), ("hwndFocus", W.HWND),
                ("hwndCapture", W.HWND), ("hwndMenuOwner", W.HWND), ("hwndMoveSize", W.HWND),
                ("hwndCaret", W.HWND), ("rcCaret", W.RECT)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, W.WPARAM, W.LPARAM)
user32.SetWindowsHookExW.restype = W.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, W.HINSTANCE, W.DWORD]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = [W.HHOOK, ctypes.c_int, W.WPARAM, W.LPARAM]
user32.UnhookWindowsHookEx.argtypes = [W.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(W.MSG), W.HWND, W.UINT, W.UINT]
user32.PostThreadMessageW.argtypes = [W.DWORD, W.UINT, W.WPARAM, W.LPARAM]
user32.GetForegroundWindow.restype = W.HWND
user32.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
user32.GetWindowThreadProcessId.restype = W.DWORD
user32.GetGUIThreadInfo.argtypes = [W.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.keybd_event.argtypes = [W.BYTE, W.BYTE, W.DWORD, ctypes.c_size_t]
kernel32.GetModuleHandleW.restype = W.HMODULE
kernel32.GetCurrentThreadId.restype = W.DWORD

LWIN, RWIN, TAB, ESC, SPACE, SHIFT, CTRL = 0x5B, 0x5C, 0x09, 0x1B, 0x20, 0x10, 0x11
ALTS = (0x12, 0xA4, 0xA5)
VOLUME = (0xAD, 0xAE, 0xAF)  # كتم، خفض، رفع
MASK = 0xE8  # مفتاح ما له وظيفة: نضغطه عشان ويندوز ما يفتح قائمة ابدأ/قائمة البرنامج
MAGIC = 0x4D414355  # علامة على المفاتيح اللي تضغطها الواجهة نفسها (عشان ما تلتقطها)


def _class(hwnd):
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, buf, 64)
    return buf.value


def _mask():
    user32.keybd_event(MASK, 0, 0, MAGIC)
    user32.keybd_event(MASK, 0, 2, MAGIC)


class KeyLogic:
    """القرارات بس (بدون نظام) عشان تنفحص بسهولة. ترجع True = لا توصل المفتاح لويندوز."""

    def __init__(self, events, options):
        self.events, self.options = events, options
        self.win_down = self.win_combo = False
        self.alt_down = self.switching = False
        self.ql_swallow = False

    def handle(self, vk, down, ctx=None):
        opt = self.options
        if vk in (LWIN, RWIN):
            if down:
                if not self.win_down:
                    self.win_down, self.win_combo = True, False
            else:
                if self.win_down and not self.win_combo and opt.get("win_key_apps", True):
                    _mask()  # ويندوز يشوفها «Win+مفتاح» فما يفتح قائمة ابدأ
                    self.events.put(("apps",))
                self.win_down = False
            return False
        if down and self.win_down:
            self.win_combo = True  # Win+E و Win+D… تبقى زي ما هي
        if vk in ALTS:
            if down:
                self.alt_down = True
            else:
                self.alt_down = False
                if self.switching:
                    self.switching = False
                    _mask()  # عشان البرنامج ما يفتح قائمته من لمسة Alt
                    self.events.put(("switch_commit",))
            return False
        if vk == TAB and self.alt_down and opt.get("mac_switcher", True):
            if down:
                shift = bool(user32.GetAsyncKeyState(SHIFT) & 0x8000) if ctx is None else ctx.get("shift", False)
                self.events.put(("switch_prev" if shift else "switch_next", self.switching))
                self.switching = True
            return True
        if vk == ESC and self.switching:
            if down:
                self.switching = False
                self.events.put(("switch_cancel",))
            return True
        if vk in VOLUME and opt.get("volume_hud", True):
            if down:
                self.events.put(("volume", vk))
            return True
        if vk == SPACE and opt.get("quick_look", True):
            if down:
                fg = self.quicklook_target() if ctx is None else ctx.get("ql")
                if fg:
                    self.ql_swallow = True
                    self.events.put(("quicklook", fg))
                    return True
            elif self.ql_swallow:
                self.ql_swallow = False
                return True
        return False

    @staticmethod
    def quicklook_target():
        """مسافة تفتح Quick Look بس لما التركيز على قائمة الملفات في مستكشف الملفات (مو وقت الكتابة)."""
        if user32.GetAsyncKeyState(CTRL) & 0x8000 or user32.GetAsyncKeyState(SHIFT) & 0x8000:
            return None
        fg = user32.GetForegroundWindow()
        if not fg or _class(fg) != "CabinetWClass":
            return None
        info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
        tid = user32.GetWindowThreadProcessId(fg, None)
        if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)) or not info.hwndFocus:
            return None
        return fg if _class(info.hwndFocus) == "DirectUIHWND" else None


class KeyHook:
    def __init__(self, options):
        self.events = queue.Queue()
        self.logic = KeyLogic(self.events, options)
        self.thread_id = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        self.ready.wait(2)

    def run(self):
        self.thread_id = kernel32.GetCurrentThreadId()
        self.proc = HOOKPROC(self.callback)
        self.hook = user32.SetWindowsHookExW(13, self.proc, kernel32.GetModuleHandleW(None), 0)  # WH_KEYBOARD_LL
        self.ready.set()
        if not self.hook:
            return
        msg = W.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(self.hook)

    def callback(self, code, wparam, lparam):
        try:
            if code == 0:
                kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if kb.dwExtraInfo != MAGIC:  # نتجاهل بس المفاتيح اللي ضغطتها الواجهة نفسها
                    if self.logic.handle(kb.vkCode, wparam in (0x100, 0x104)):
                        return 1
        except Exception:
            pass  # أي خطأ هنا ما يوقف الكيبورد أبداً
        return user32.CallNextHookEx(None, code, wparam, lparam)

    @property
    def active(self):
        return bool(getattr(self, "hook", None))

    def stop(self):
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, 0x12, 0, 0)  # WM_QUIT
