"""
Logic tests that need no screen: Arabic shaping, Spotlight math, keyboard decisions, wallpapers.

Run:  python tests/test_logic.py
"""
import queue
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

passed = failed = 0


def check(name, ok):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print("FAIL", name)


# ── Arabic shaping and right-to-left order ──
from arabic import ar, has_arabic, shape, visual

check("english untouched", ar("Finder") == "Finder")
check("arabic detected", has_arabic("مرحبا") and not has_arabic("hello"))
shaped = shape("سلام")
check("letters are joined (presentation forms)", all("ﹰ" <= c <= "﻿" for c in shaped))
check("lam-alef ligature", "ﻻ" in shape("لا") or "ﻼ" in shape("لا"))
check("rtl reversed", visual("ab") == "ab" and visual(shape("بت"))[0] == shape("بت")[-1])
check("numbers keep LTR order", "2026" in ar("سنة 2026"))
check("harakat removed", ar("جارٍ") == ar("جار"))

# ── Spotlight calculator (safe evaluation) ──
from controlcenter import calc

check("calc basic", calc("12*3+4") == "40")
check("calc division", calc("1/4") == "0.25")
check("calc rejects code", calc("__import__('os')") is None)
check("calc ignores plain numbers", calc("2026") is None)
check("calc divide by zero", calc("1/0") is None)

# ── Keyboard decisions (no real keys are pressed) ──
import keyboard_hook as kh

kh._mask = lambda: None


def run(seq, opts=None):
    q = queue.Queue()
    logic = kh.KeyLogic(q, opts or {})
    swallowed = [logic.handle(vk, down, ctx) for vk, down, ctx in seq]
    events = []
    while not q.empty():
        events.append(q.get()[0])
    return swallowed, events


check("win alone opens Apps", run([(0x5B, True, {}), (0x5B, False, {})])[1] == ["apps"])
check("win+E untouched", run([(0x5B, True, {}), (0x45, True, {}), (0x45, False, {}), (0x5B, False, {})]) ==
      ([False] * 4, []))
s, e = run([(0xA4, True, {}), (0x09, True, {"shift": False}), (0x09, False, {}), (0xA4, False, {})])
check("alt+tab swallowed and committed", s == [False, True, True, False] and e == ["switch_next", "switch_commit"])
check("tab alone untouched", run([(0x09, True, {}), (0x09, False, {})]) == ([False, False], []))
check("space only in file list", run([(0x20, True, {"ql": None})])[1] == [] and
      run([(0x20, True, {"ql": 123})])[1] == ["quicklook"])
check("features can be turned off", run([(0x5B, True, {}), (0x5B, False, {}), (0xAF, True, {})],
                                        {"win_key_apps": False, "volume_hud": False})[1] == [])

# ── Wallpapers render ──
import wallpapers

for name, fn in wallpapers.CATALOG:
    img = fn(160, 90)
    check(f"wallpaper {name}", img.size == (160, 90))

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
