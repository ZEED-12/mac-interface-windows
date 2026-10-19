# Contributing to Mac Interface for Windows

Thanks for helping! Bug reports, design feedback, translations and code are all welcome.

## Ground rules

These three rules keep the project trustworthy. Every change must respect them:

1. **Never modify Windows system files** (no patching DLLs, themes, `imageres`, etc.).
2. **Everything must be reversible.** Any registry value you change goes through the plan in `mac.py`
   (`apply()` → `remember()` stores the original first) and must come back with `restore()`.
3. **Stay light.** Idle CPU should stay around 0.2%. No busy loops; cache rendered images; only
   animate while something is moving.

## Getting started

```powershell
git clone https://github.com/ZEED-12/mac-interface-windows.git
cd mac-interface-windows
pip install -r requirements.txt
python tests/test_logic.py          # logic tests, no screen needed
python mac.py desktop               # run the interface without touching Windows settings
```

`python mac.py desktop` only starts the interface (it hides the taskbar while running and shows it again
when you quit). `python mac.py apply` is what changes Windows settings — use **Restore everything**
(`python mac.py restore`) to undo.

## How the UI works

- Everything is drawn with **Pillow** into RGBA images and shown in layered windows
  (`macui.Surface` → `UpdateLayeredWindow`). There is no widget toolkit; hit-testing is done by us.
- **Liquid Glass** = a `macui.Backdrop` (a DWM acrylic window that blurs whatever is behind it) +
  `glass_card()` drawn on top (tint, rim highlight). The content window is *owned* by its backdrop so
  they always stay together.
- All text that users see goes through `settings.tr()` (or `arabic.ar()` for dynamic text) so it works
  in English and Arabic. Layouts mirror when `settings.rtl()` is true.
- The interface runs on Tk's main thread. Slow work (Wi‑Fi scans, weather, icon extraction,
  PowerShell) runs on background threads and hands results back via `root.after`.
- `keyboard_hook.py` runs on its own thread and must only make quick decisions.

## Testing without disturbing your desktop

Most visual work can be checked off-screen: replace `macui.Surface.show` with a function that stores
the image, replace `macui.Backdrop` with a dummy, then render a window and save the image.
`tools/make_screenshots.py` does exactly that and is a good template.

Before opening a pull request:

- `python tests/test_logic.py` passes
- `python -m py_compile *.py` passes
- If you changed visuals, attach a screenshot (English **and** Arabic if text changed)

## Code style

- Match the surrounding code: small functions, no unnecessary abstractions.
- Many inline comments are in Arabic (the project started in Arabic). New comments can be in English;
  translating existing comments is a great first contribution.
- Keep new dependencies to a minimum (currently only Pillow and NumPy).

## Ideas

Look for issues labelled **good first issue** and **help wanted**. Bigger ideas we'd love help with:
Notification Center, Stage Manager / window tiling, file search in Spotlight, a single Dock that follows
the mouse between monitors, and GPU refraction for Liquid Glass.
