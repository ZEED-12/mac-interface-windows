"""
mac.py — entry point and Windows integration for Mac Interface.

  python mac.py              interactive menu
  python mac.py apply        apply the Mac look to Windows (everything is backed up first)
  python mac.py restore      restore every original Windows setting
  python mac.py uninstall    restore + delete our generated assets
  python mac.py desktop      start the Mac interface (menu bar, Dock, widgets…)
  python mac.py ipc <cmd>    send a command to the running interface (used by the desktop menu)

All changes are per-user (HKCU) registry values that are recorded in mac_backup.json before
they are written, so they can always be undone. No Windows system file is ever modified.
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import winreg
from ctypes import wintypes
from pathlib import Path

sys.dont_write_bytecode = True  # بدون مجلد __pycache__ جنب الملفات

HERE = Path(__file__).resolve().parent
BACKUP = HERE / "mac_backup.json"
ERROR_LOG = HERE / "mac_error.log"

HKCU = winreg.HKEY_CURRENT_USER
D, S, B = winreg.REG_DWORD, winreg.REG_SZ, winreg.REG_BINARY
ADV = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
THEME = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
CDM = r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"
STUCK = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StuckRects3"
DESKTOP = r"Control Panel\Desktop"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "MacDesktop"

# (الوصف, المسار, الاسم, النوع, القيمة)
TWEAKS = [
    ("Dark mode (apps)", THEME, "AppsUseLightTheme", D, 0),
    ("Dark mode (system)", THEME, "SystemUsesLightTheme", D, 0),
    ("Transparency effects", THEME, "EnableTransparency", D, 1),
    ("Centered taskbar", ADV, "TaskbarAl", D, 1),
    ("Hide Task View button", ADV, "ShowTaskViewButton", D, 0),
    ("Hide Widgets button", ADV, "TaskbarDa", D, 0),
    ("Hide Chat button", ADV, "TaskbarMn", D, 0),
    ("Hide Copilot button", ADV, "ShowCopilotButton", D, 0),
    ("Hide taskbar search box", r"Software\Microsoft\Windows\CurrentVersion\Search", "SearchboxTaskbarMode", D, 0),
    ("Start search without Bing", r"Software\Policies\Microsoft\Windows\Explorer", "DisableSearchBoxSuggestions", D, 1),
    ("No Start recommendations", ADV, "Start_IrisRecommendations", D, 0),
    ("No taskbar animations", ADV, "TaskbarAnimations", D, 0),
    ("Faster menus", DESKTOP, "MenuShowDelay", S, "100"),
    ("No minimize/maximize animation", r"Control Panel\Desktop\WindowMetrics", "MinAnimate", S, "0"),
    ("No ads or suggested apps", CDM, "SystemPaneSuggestionsEnabled", D, 0),
    ("No ads or suggested apps", CDM, "SilentInstalledAppsEnabled", D, 0),
    ("No ads or suggested apps", CDM, "SoftLandingEnabled", D, 0),
    ("No ads or suggested apps", CDM, "SubscribedContent-338388Enabled", D, 0),
    ("No ads or suggested apps", CDM, "SubscribedContent-338389Enabled", D, 0),
    ("No ads or suggested apps", CDM, "SubscribedContent-353694Enabled", D, 0),
]

# ميزات كانت تنطفي بنسخة قديمة؛ الحين ترجع شغالة (كل شي في ويندوز يبقى، بس شكله يتغير)
REVERT = [
    ("background apps (notifications)", r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications", "GlobalUserDisabled"),
    ("game recording", r"System\GameConfigStore", "GameDVR_Enabled"),
    ("game recording", r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled"),
]

CLSID = r"Software\Microsoft\Windows\CurrentVersion\Explorer\CLSID"
RECYCLE_ICON = CLSID + r"\{645FF040-5081-101B-9F08-00AA002F954E}\DefaultIcon"
PC_ICON = CLSID + r"\{20D04FE0-3AEA-1069-A2D8-08002B30309D}\DefaultIcon"
SHELL_ICONS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Icons"
ICON_DIR = Path(os.environ.get("LOCALAPPDATA", str(HERE))) / "MacUI" / "icons"


# ───────────────────────────── الريجستري ─────────────────────────────

def reg_read(path, name):
    try:
        with winreg.OpenKey(HKCU, path) as k:
            return winreg.QueryValueEx(k, name)
    except OSError:
        return None


def reg_write(path, name, typ, value):
    with winreg.CreateKeyEx(HKCU, path, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, typ, value)


def reg_delete(path, name):
    try:
        with winreg.OpenKey(HKCU, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except FileNotFoundError:
        pass


def encode(value, typ):
    return value.hex() if typ == B else value


def decode(value, typ):
    return bytes.fromhex(value) if typ == B else value


def load_backup():
    try:
        return json.loads(BACKUP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def remember(backup, path, name):
    """يحفظ القيمة الأصلية مرة وحدة بس، عشان التطبيق مرتين ما يمسح النسخة الأصلية."""
    key = f"{path}|{name}"
    if key in backup:
        return
    cur = reg_read(path, name)
    backup[key] = None if cur is None else {"type": cur[1], "data": encode(cur[0], cur[1])}


def taskbar_autohide_bytes():
    cur = reg_read(STUCK, "Settings")
    if not cur or len(cur[0]) < 9:
        return None
    data = bytearray(cur[0])
    data[8] |= 0x01
    return bytes(data)


def restart_explorer():
    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], capture_output=True)
    time.sleep(1.5)
    subprocess.Popen(["explorer.exe"], creationflags=0x00000008)  # DETACHED_PROCESS


def ensure_pillow():
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("Installing Pillow (one time only)...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--user", "-q", "pillow"], check=True)


def apply(dry_run=False):
    backup = load_backup()
    plan = list(TWEAKS)
    hide = taskbar_autohide_bytes()
    if hide is not None:
        plan.append(("Auto-hide the Windows taskbar (the Dock replaces it)", STUCK, "Settings", B, hide))
    wallpaper = None
    try:
        ensure_pillow()
        import macui
        wallpaper = str(macui.ensure_wallpaper())
        plan += [("Mac-style wallpaper", DESKTOP, "WallPaper", S, wallpaper),
                 ("Mac-style wallpaper", DESKTOP, "WallpaperStyle", S, "10"),
                 ("Mac-style wallpaper", DESKTOP, "TileWallpaper", S, "0")]
        icons = system_icons()
        plan += theme_plan()
        plan += [("Mac-style Recycle Bin icon", RECYCLE_ICON, "", S, f"{icons['trash']},0"),
                 ("Mac-style Recycle Bin icon", RECYCLE_ICON, "empty", S, f"{icons['trash']},0"),
                 ("Mac-style Recycle Bin icon", RECYCLE_ICON, "full", S, f"{icons['trash_full']},0"),
                 ("Mac-style This PC icon", PC_ICON, "", S, f"{icons['drive']},0")]
    except Exception as e:
        print(f"  - Skipped wallpaper/icons: {e}")

    if not dry_run:
        for desc, path, name in REVERT:
            orig = backup.pop(f"{path}|{name}", "absent")
            if orig == "absent":
                continue
            try:
                if orig is None:
                    reg_delete(path, name)
                else:
                    reg_write(path, name, orig["type"], decode(orig["data"], orig["type"]))
                print(f"  ✓ Re-enabled {desc}")
            except OSError:
                pass

    for _, path, name, _, _ in plan:
        remember(backup, path, name)
    if not dry_run:
        BACKUP.write_text(json.dumps(backup, ensure_ascii=False, indent=1), encoding="utf-8")

    done = skipped = 0
    changed_wallpaper = False
    for desc, path, name, typ, value in plan:
        cur = reg_read(path, name)
        if cur is not None and cur[0] == value:
            continue
        if dry_run:
            print(f"  [dry run] {desc}: {name}")
            done += 1
            continue
        try:
            reg_write(path, name, typ, value)
            print(f"  ✓ {desc}")
            done += 1
            changed_wallpaper |= path == DESKTOP and name.startswith(("WallPaper", "Tile"))
        except OSError:
            print(f"  - Skipped ({desc}): Windows did not allow it")
            skipped += 1

    if dry_run:
        print(f"\n{done} change(s) would be applied.")
        return
    if changed_wallpaper and wallpaper:
        import macui
        macui.set_wallpaper(wallpaper)
    ctypes.windll.user32.SystemParametersInfoW(0x57, 0, None, 0)  # SPI_SETCURSORS: يحمّل المؤشر الجديد فوراً
    broadcast_colors()
    try:
        import wallpapers
        print("Rendering 4K wallpapers (first time only, about a minute)...")
        wallpapers.generate()
    except Exception as e:
        print(f"  - Skipped wallpapers: {e}")
    desktop_folder_icons(backup)
    BACKUP.write_text(json.dumps(backup, ensure_ascii=False, indent=1), encoding="utf-8")
    refresh_icons()
    print(f"\nDone: {done} change(s)" + (f", {skipped} skipped" if skipped else "") + ".")
    print(f"Backup: {BACKUP}")
    if done:
        print("Restarting File Explorer so the changes show up...")
        restart_explorer()


CURSORS = r"Control Panel\Cursors"
SOUNDS = r"AppEvents\Schemes\Apps"
CLASSES = r"Software\Classes"
MENU = CLASSES + r"\DesktopBackground\Shell"


def progids_for(ext):
    """البرامج (ProgID) اللي تفتح هذا النوع، عشان نغير أيقونته."""
    ids = []
    uc = reg_read(rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{ext}\UserChoice", "ProgId")
    if uc and uc[0]:
        ids.append(uc[0])
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ext) as k:
            v = winreg.QueryValueEx(k, "")[0]
            if v and v not in ids:
                ids.append(v)
    except OSError:
        pass
    return ids


def theme_plan():
    """مؤشر الماوس + أصوات + أيقونات الملفات + قائمة الزر الأيمن، كلها بنسخة احتياطية."""
    import system_theme as st
    plan = []
    cursors = st.make_cursors(ICON_DIR / "cursors")
    plan.append(("Mac-style mouse pointer", CURSORS, "", S, "Mac"))
    for name, path in cursors.items():
        plan.append(("Mac-style mouse pointer", CURSORS, name, winreg.REG_EXPAND_SZ, path))
    sounds = st.make_sounds(ICON_DIR / "sounds")
    for event, sound in st.SOUND_EVENTS.items():
        plan.append(("Mac-like system sounds", rf"{SOUNDS}\{event}\.Current", "", winreg.REG_EXPAND_SZ, sounds[sound]))
    icons = st.make_file_icons(ICON_DIR / "files")
    owners = {}
    for ext in icons:
        for progid in progids_for(ext):
            owners.setdefault(progid, []).append(ext)
    for progid, exts in owners.items():
        # برنامج واحد يفتح كذا نوع (مثل الصور): أيقونة فئة وحدة بدل ما آخر نوع يغلب
        ico = icons[exts[0]] if len(exts) == 1 else st.category_icon(exts, ICON_DIR / "files")
        plan.append((f"أيقونة ملفات {exts[0]}", rf"{CLASSES}\{progid}\DefaultIcon", "", S, f"{ico},0"))
    plan += accent_plan()
    import macui
    py = f'"{pythonw()}" "{Path(__file__).resolve()}"'
    for key, label, cmd, icon in (("MacEditWidgets", "Edit Widgets…", "edit_widgets", "launchpad"),
                                  ("MacSettings", "Mac Interface Settings…", "settings", "settings")):
        ico = ICON_DIR / f"menu_{icon}.ico"
        if not ico.exists():
            macui.save_ico({"icon": icon}, ico)
        plan += [("Desktop right-click menu", rf"{MENU}\{key}", "MUIVerb", S, label),
                 ("Desktop right-click menu", rf"{MENU}\{key}", "Icon", S, str(ico)),
                 ("Desktop right-click menu", rf"{MENU}\{key}\command", "", S, f"{py} ipc {cmd}")]
    return plan


MAC_BLUE = (10, 132, 255)  # أزرق النظام في الماك (الوضع الداكن)


def _mix(c, other, t):
    return tuple(round(a + (b - a) * t) for a, b in zip(c, other))


def accent_plan():
    """لون التمييز في ويندوز يصير أزرق الماك (أزرار التفعيل، التحديد، الروابط)."""
    base = MAC_BLUE
    shades = [_mix(base, (255, 255, 255), 0.7), _mix(base, (255, 255, 255), 0.45), _mix(base, (255, 255, 255), 0.22),
              base, _mix(base, (0, 0, 0), 0.15), _mix(base, (0, 0, 0), 0.4), _mix(base, (0, 0, 0), 0.65), (247, 99, 12)]
    palette = b"".join(bytes(c) + b"\0" for c in shades)
    abgr = lambda c: 0xFF000000 | (c[2] << 16) | (c[1] << 8) | c[0]
    accent = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent"
    dwm = r"Software\Microsoft\Windows\DWM"
    return [("Mac blue accent color", accent, "AccentPalette", B, palette),
            ("Mac blue accent color", accent, "AccentColorMenu", D, abgr(base)),
            ("Mac blue accent color", accent, "StartColorMenu", D, abgr(shades[4])),
            ("Mac blue accent color", dwm, "AccentColor", D, abgr(base)),
            ("Mac blue accent color", dwm, "ColorizationColor", D, 0xC4000000 | (base[0] << 16) | (base[1] << 8) | base[2]),
            ("Mac blue accent color", DESKTOP, "AutoColorization", D, 0)]


def broadcast_colors():
    """نبلغ ويندوز إن الألوان تغيرت (بدون إعادة تشغيل)."""
    u = ctypes.windll.user32
    res = ctypes.c_size_t()
    for area in ("ImmersiveColorSet", "WindowsThemeElement"):
        u.SendMessageTimeoutW(0xFFFF, 0x001A, 0, area, 0x0002, 1000, ctypes.byref(res))


FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"


def desktop_folder_icons(backup):
    """مجلدات سطح المكتب: ويندوز 11 يرسمها بنفسه بالأيقونات الكبيرة، فنعطي كل مجلد أيقونته (desktop.ini)."""
    import macui
    desk = macui.known_folder(FOLDERID_DESKTOP)
    if not desk:
        return
    icon = system_icons()["folder"]
    done = backup.setdefault("DESKTOP_INI", [])
    known = {d[0] for d in done}
    k32 = ctypes.windll.kernel32
    count = 0
    for folder in Path(desk).iterdir():
        try:
            if not folder.is_dir() or folder.name.startswith(".") or str(folder) in known or                     folder.resolve() == HERE:
                continue
            attrs = k32.GetFileAttributesW(str(folder))
            if attrs == 0xFFFFFFFF or attrs & 0x6:  # مخفي أو نظام
                continue
            ini = folder / "desktop.ini"
            if ini.exists():
                continue
            ini.write_text(f"[.ShellClassInfo]\r\nIconResource={icon},0\r\n", encoding="utf-8")
            k32.SetFileAttributesW(str(ini), 0x2 | 0x4)
            k32.SetFileAttributesW(str(folder), attrs | 0x1)
            done.append([str(folder), bool(attrs & 0x1)])
            count += 1
        except OSError:
            continue
    if count:
        print(f"  ✓ Mac icons for {count} desktop folder(s)")


def undo_desktop_folders(entries):
    k32 = ctypes.windll.kernel32
    for folder, was_readonly in entries:
        ini = Path(folder) / "desktop.ini"
        try:
            if ini.exists() and "IconResource=" in ini.read_text(encoding="utf-8", errors="ignore") and \
                    "MacUI" in ini.read_text(encoding="utf-8", errors="ignore"):
                k32.SetFileAttributesW(str(ini), 0x80)
                ini.unlink()
            if not was_readonly:
                attrs = k32.GetFileAttributesW(folder)
                if attrs != 0xFFFFFFFF:
                    k32.SetFileAttributesW(folder, attrs & ~0x1)
        except OSError:
            pass


def delete_empty_keys(paths):
    """يشيل المفاتيح اللي سويناها وصارت فاضية (الأعمق أول)، عشان ما تخفي إعدادات ويندوز الأصلية."""
    for path in sorted(set(paths), key=lambda x: -x.count("\\")):
        try:
            with winreg.OpenKey(HKCU, path) as k:
                subkeys, values, _ = winreg.QueryInfoKey(k)
            if subkeys == 0 and values == 0:
                winreg.DeleteKey(HKCU, path)
        except OSError:
            pass


def ipc(cmd):
    """أمر من قائمة الزر الأيمن: نبلغ الواجهة (ونشغلها لو مو شغالة)."""
    (HERE / "ipc.txt").write_text(cmd, encoding="utf-8")
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenMutexW.restype = wintypes.HANDLE
    if not k32.OpenMutexW(0x00100000, False, "Local\\MacDesktopUI"):
        subprocess.Popen([pythonw(), str(Path(__file__).resolve()), "desktop"], creationflags=0x00000008)


def system_icons():
    """أيقونات .ico بستايل الماك لسلة المهملات وThis PC والمجلدات."""
    import macui
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for kind in ("trash", "trash_full", "drive", "folder"):
        path = ICON_DIR / f"{kind}.ico"
        if not path.exists():
            macui.save_ico({"icon": kind}, path)
        out[kind] = str(path)
    return out


def refresh_icons():
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    subprocess.run(["ie4uinit.exe", "-show"], capture_output=True)


def run_elevated(commands):
    """يشغّل أوامر reg بصلاحية مدير (يطلع لك تأكيد ويندوز مرة وحدة)."""
    joined = " & ".join(commands)
    ps = f"Start-Process cmd.exe -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList '/c {joined}'"
    return subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True).returncode == 0


def hklm_read(name):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SHELL_ICONS) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def folder_icons():
    """أيقونات المجلدات الزرقاء مثل الماك في كل مستكشف الملفات (يحتاج صلاحية مدير)."""
    icon = system_icons()["folder"]
    backup = load_backup()
    for v in ("3", "4"):
        backup.setdefault(f"HKLM|{SHELL_ICONS}|{v}", hklm_read(v))
    BACKUP.write_text(json.dumps(backup, ensure_ascii=False, indent=1), encoding="utf-8")
    key = "HKLM\\" + SHELL_ICONS
    ok = run_elevated([f'reg add "{key}" /v {v} /t REG_SZ /d "{icon},0" /f' for v in ("3", "4")])
    if ok and hklm_read("3"):
        print("✓ Folder icons now look like the Mac.")
        refresh_icons()
        restart_explorer()
    else:
        print("Not changed (admin permission declined or an error occurred).")


def restore_hklm(backup):
    cmds = []
    for key, orig in list(backup.items()):
        if not key.startswith("HKLM|"):
            continue
        _, path, name = key.split("|", 2)
        if orig is None:
            cmds.append(f'reg delete "HKLM\\{path}" /v {name} /f')
        else:
            cmds.append(f'reg add "HKLM\\{path}" /v {name} /t REG_SZ /d "{orig}" /f')
        del backup[key]
    if cmds:
        print("Restoring folder icons (needs admin permission)...")
        run_elevated(cmds)


def uninstall():
    """يشيل واجهة الماك كلها ويرجع ويندوز مثل ما كان، بدون ما يحذف أي شي من ويندوز نفسه."""
    restore()
    reg_delete(RUN, RUN_NAME)
    ours = ICON_DIR.parent
    if ours.name == "MacUI":  # %LOCALAPPDATA%\MacUI: أيقوناتنا ومؤشراتنا وأصواتنا بس، ولا شي ثاني
        shutil.rmtree(ours, ignore_errors=True)
    print("Mac Interface removed. Windows is back to how it was.")
    print(f"You can delete the project folder yourself whenever you like: {HERE}")


def stop_ui():
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -match 'mac.py.*desktop' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)


def show_taskbar():
    stop_ui()
    restart_explorer()
    print("The Windows taskbar is back.")


def restore():
    stop_ui()
    backup = load_backup()
    if not backup:
        print("No backup found, so nothing was changed.")
    restore_hklm(backup)
    undo_desktop_folders(backup.pop("DESKTOP_INI", []))
    touched = []
    for key, orig in backup.items():
        path, name = key.split("|", 1)
        touched.append(path)
        try:
            if orig is None:
                reg_delete(path, name)
            else:
                reg_write(path, name, orig["type"], decode(orig["data"], orig["type"]))
        except OSError:
            print(f"  - Could not restore {name}")
    reg_delete(RUN, RUN_NAME)
    parents = [t.rsplit("\\", 1)[0] for t in touched if t.startswith((CLASSES, SOUNDS))]
    delete_empty_keys(touched + parents + [MENU + r"\MacEditWidgets", MENU + r"\MacSettings"])
    ctypes.windll.user32.SystemParametersInfoW(0x57, 0, None, 0)
    broadcast_colors()
    if f"{DESKTOP}|WallPaper" in backup:
        cur = reg_read(DESKTOP, "WallPaper")
        buf = ctypes.create_unicode_buffer(cur[0] if cur else "")
        ctypes.windll.user32.SystemParametersInfoW(20, 0, buf, 3)
    if backup:
        BACKUP.rename(BACKUP.with_name(f"mac_backup_restored_{int(time.time())}.json"))
        print("All settings restored.")
        restart_explorer()


# ───────────────────────────── أدوات القائمة ─────────────────────────────

def pythonw():
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def launch_desktop():
    ensure_pillow()
    subprocess.Popen([pythonw(), str(Path(__file__).resolve()), "desktop"],
                     creationflags=0x00000008 | 0x00000200, close_fds=True)
    print("Mac Interface started. Quit it from the logo menu > Quit Mac Interface.")


def toggle_startup():
    if reg_read(RUN, RUN_NAME):
        reg_delete(RUN, RUN_NAME)
        print("Mac Interface will no longer start with Windows.")
    else:
        reg_write(RUN, RUN_NAME, S, f'"{pythonw()}" "{Path(__file__).resolve()}" desktop')
        print("Mac Interface will now start with Windows.")


def clean_temp():
    tmp = Path(os.environ.get("TEMP", ""))
    if not tmp.is_dir():
        return
    cutoff = time.time() - 24 * 3600
    freed = count = 0
    for entry in tmp.iterdir():
        try:
            if entry.stat().st_mtime > cutoff:
                continue
            if entry.is_dir() and not entry.is_symlink():
                size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
                shutil.rmtree(entry)
            else:
                size = entry.stat().st_size
                entry.unlink()
            freed += size
            count += 1
        except OSError:
            pass  # ملف مستخدم حالياً
    print(f"Removed {count} temporary item(s) ({freed / 1048576:.0f} MB).")


def menu():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    actions = {
        "1": ("Apply the Mac look to Windows", apply),
        "2": ("Start Mac Interface (menu bar + Dock)", launch_desktop),
        "3": ("Start with Windows (on/off)", toggle_startup),
        "4": ("Mac folder icons everywhere (asks for admin)", folder_icons),
        "5": ("Clean temporary files (older than a day)", clean_temp),
        "6": ("Startup apps (turn off heavy ones)", lambda: os.startfile("ms-settings:startupapps")),
        "7": ("Show the Windows taskbar (emergency)", show_taskbar),
        "8": ("Restore everything", restore),
        "9": ("Uninstall Mac Interface completely", uninstall),
    }
    while True:
        print("\n══════ Mac Interface for Windows ══════")
        for k, (label, _) in actions.items():
            print(f" {k}) {label}")
        print(" 0) Exit")
        choice = input("\nYour choice: ").strip()
        if choice == "0" or choice == "":
            return
        if choice in actions:
            print()
            actions[choice][1]()


def desktop():
    # نسخة وحدة بس من الواجهة
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.CreateMutexW(None, False, "Local\\MacDesktopUI")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return
    try:
        ensure_pillow()
        import macui
        macui.run()
    except Exception:
        ERROR_LOG.write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "apply":
        apply(dry_run="--dry-run" in sys.argv)
    elif cmd == "restore":
        restore()
    elif cmd == "uninstall":
        uninstall()
    elif cmd == "desktop":
        desktop()
    elif cmd == "ipc" and len(sys.argv) > 2:
        ipc(sys.argv[2])
    else:
        menu()
