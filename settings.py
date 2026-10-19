"""
settings.py — user settings (language, glass, Dock size, hot corners…) and the EN/AR translations.
"""
import json
import time
from pathlib import Path

from arabic import ar

HERE = Path(__file__).resolve().parent
FILE = HERE / "settings.json"


DEFAULTS = {"language": "en", "glass": 0.45, "dock_size": 54, "magnify": True, "widgets": True,
            "hot_corners": {"tl": "", "tr": "", "bl": "mission", "br": "desktop"}}

CORNER_ACTIONS = ["", "mission", "desktop", "spotlight", "apps", "lock"]
CORNER_NAMES = {"": ("—", "—"), "mission": ("Mission Control", "Mission Control"), "desktop": ("Desktop", "سطح المكتب"),
                "spotlight": ("Spotlight", "Spotlight"), "apps": ("Apps", "التطبيقات"), "lock": ("Lock Screen", "قفل الشاشة")}
CORNER_LABELS = {"tl": ("Top Left", "الزاوية العلوية اليسرى"), "tr": ("Top Right", "الزاوية العلوية اليمنى"),
                 "bl": ("Bottom Left", "الزاوية السفلية اليسرى"), "br": ("Bottom Right", "الزاوية السفلية اليمنى")}


class Settings(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        self.stamp = 0
        self.reload()

    def reload(self):
        try:
            self.update(json.loads(FILE.read_text(encoding="utf-8")))
            self.stamp = FILE.stat().st_mtime
        except (OSError, ValueError):
            pass

    def changed(self):
        try:
            return FILE.stat().st_mtime != self.stamp
        except OSError:
            return False

    def save(self):
        FILE.write_text(json.dumps(dict(self), ensure_ascii=False, indent=1), encoding="utf-8")
        self.stamp = FILE.stat().st_mtime


S = Settings()


def rtl():
    return S.get("language") == "ar"


# (English, العربية)
STRINGS = {
    "File": ("File", "ملف"), "Edit": ("Edit", "تحرير"), "View": ("View", "عرض"), "Window": ("Window", "نافذة"),
    "Help": ("Help", "مساعدة"),
    "about": ("About This PC", "حول هذا الكمبيوتر"), "sys_settings": ("System Settings…", "إعدادات النظام…"),
    "app_store": ("App Store…", "App Store…"), "mac_settings": ("Mac Interface Settings…", "إعدادات واجهة ماك…"),
    "start": ("Start Menu", "قائمة ابدأ"), "mission": ("Mission Control", "Mission Control"),
    "show_desktop": ("Show Desktop", "إظهار سطح المكتب"), "win_widgets": ("Windows Widgets", "أدوات ويندوز"),
    "edit_widgets": ("Edit Widgets…", "تعديل الأدوات…"), "hide_widgets": ("Hide Desktop Widgets", "إخفاء أدوات سطح المكتب"),
    "show_widgets": ("Show Desktop Widgets", "إظهار أدوات سطح المكتب"), "taskbar": ("Windows Taskbar…", "شريط مهام ويندوز…"),
    "force_quit": ("Force Quit…", "إنهاء إجباري…"), "lock": ("Lock Screen", "قفل الشاشة"),
    "restart": ("Restart…", "إعادة التشغيل…"), "shutdown": ("Shut Down…", "إيقاف التشغيل…"),
    "quit_ui": ("Quit Mac Interface", "إنهاء واجهة ماك"),
    "show": ("Show", "إظهار"), "quit": ("Quit", "إنهاء"), "open": ("Open", "فتح"),
    "remove_dock": ("Remove from Dock", "إزالة من Dock"), "keep_dock": ("Keep in Dock", "إبقاء في Dock"),
    "add_app": ("Add App to Dock…", "إضافة تطبيق إلى Dock…"), "edit_dock": ("Edit Dock Apps…", "تعديل تطبيقات Dock…"),
    "reload_dock": ("Reload Dock", "إعادة تحميل Dock"),
    "wifi": ("Wi-Fi", "Wi-Fi"), "bt": ("Bluetooth", "بلوتوث"), "mirroring": ("Screen Mirroring", "انعكاس الشاشة"),
    "display": ("Display", "شاشة العرض"), "sound": ("Sound", "الصوت"), "now_playing": ("Now Playing", "قيد التشغيل"),
    "not_connected": ("Not Connected", "غير متصل"), "settings": ("Settings", "الإعدادات"),
    "display_settings": ("Display Settings", "إعدادات العرض"), "other_networks": ("Other Networks", "شبكات أخرى"),
    "wifi_settings": ("Wi-Fi Settings…", "إعدادات Wi-Fi…"), "battery": ("Battery", "البطارية"),
    "power_source": ("Power Source:", "مصدر الطاقة:"), "adapter": ("Power Adapter", "محوّل الطاقة"),
    "battery_settings": ("Battery Settings…", "إعدادات البطارية…"), "power": ("Power", "الطاقة"),
    "spotlight": ("Spotlight Search", "بحث Spotlight"), "application": ("Application", "تطبيق"),
    "calculator": ("Calculator", "الآلة الحاسبة"), "web": ("Web", "الويب"),
    "search_web": ("Search the web for", "البحث في الويب عن"), "apps": ("Apps", "التطبيقات"),
    "search": ("Search", "بحث"), "add": ("Add", "إضافة"), "done": ("Done", "تم"),
    "remove_widget": ("Remove Widget", "إزالة الأداة"), "small": ("Small", "صغير"), "medium": ("Medium", "متوسط"),
    "large": ("Large", "كبير"), "reset_widgets": ("Reset Widgets", "إعادة ضبط الأدوات"),
    "edit_widget": ("Edit Widget…", "تعديل الأداة…"),
    "no_events": ("No events today", "لا توجد أحداث اليوم"), "loading": ("Loading…", "جارٍ التحميل…"),
    "no_connection": ("No connection", "لا يوجد اتصال"), "charging": ("Charging", "قيد الشحن"),
    "on_battery": ("Battery", "البطارية"), "this_pc": ("This PC", "هذا الكمبيوتر"),
    "cpu": ("CPU", "المعالج"), "memory": ("Memory", "الذاكرة"), "disk": ("Disk C:", "القرص C:"),
    "notes": ("Notes", "الملاحظات"), "photos": ("Photos", "الصور"), "world_clock": ("World Clock", "الساعة العالمية"),
    "countdown": ("Countdown", "العد التنازلي"), "days": ("days", "يوم"), "clock": ("Clock", "الساعة"),
    "calendar": ("Calendar", "التقويم"), "weather": ("Weather", "الطقس"), "system": ("System", "النظام"),
    "shortcuts": ("Apps", "التطبيقات"), "custom": ("Custom", "مخصص"),
    "widget_gallery": ("Widgets", "الأدوات"), "add_your_own": ("Add your own widget…", "أضف أداة خاصة فيك…"),
    "language": ("Language", "اللغة"), "glass": ("Liquid Glass", "الزجاج السائل"), "clear": ("Clear", "شفاف"),
    "tinted": ("Tinted", "ملوّن"), "dock_size": ("Dock Size", "حجم Dock"), "magnification": ("Magnification", "التكبير"),
    "start_with_windows": ("Open at Login", "التشغيل مع ويندوز"), "appearance": ("Appearance", "المظهر"),
    "desktop_dock": ("Desktop & Dock", "سطح المكتب و Dock"), "general": ("General", "عام"),
    "about_mac": ("About This Mac", "حول هذا الماك"), "more_info": ("More Info…", "مزيد من المعلومات…"),
    "processor": ("Processor", "المعالج"), "graphics": ("Graphics", "الرسومات"), "serial": ("Windows", "ويندوز"),
    "Finder": ("Finder", "Finder"), "Apps": ("Apps", "التطبيقات"), "Terminal": ("Terminal", "Terminal"),
    "Photos": ("Photos", "الصور"), "Notes": ("Notes", "الملاحظات"), "Calculator": ("Calculator", "الآلة الحاسبة"),
    "App Store": ("App Store", "App Store"), "System Settings": ("System Settings", "إعدادات النظام"),
    "Downloads": ("Downloads", "التنزيلات"), "Trash": ("Trash", "سلة المهملات"),
    "opt_win_key": ("Windows key opens Apps", "زر ويندوز يفتح التطبيقات"),
    "opt_switcher": ("Mac app switcher (Alt+Tab)", "مبدّل تطبيقات الماك (Alt+Tab)"),
    "opt_volume": ("Mac volume indicator", "مؤشر الصوت بستايل الماك"),
    "opt_quicklook": ("Quick Look (Space in File Explorer)", "Quick Look (مسافة في مستكشف الملفات)"),
    "fq_title": ("Force Quit Applications", "إنهاء التطبيقات إجبارياً"),
    "fq_hint": ("If an app doesn’t respond for a while, select its name and click Force Quit.",
                "إذا تطبيق ما يستجيب لفترة، اختر اسمه واضغط «إنهاء إجباري»."),
    "fq_button": ("Force Quit", "إنهاء إجباري"), "relaunch": ("Relaunch", "إعادة التشغيل"),
    "fq_confirm": ("Do you want to force quit “{}”? You will lose any unsaved changes.",
                   "تبي تنهي «{}» إجبارياً؟ أي تغييرات ما انحفظت بتضيع."),
}

DAYS = {"en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "ar": ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]}
DAYS_SHORT = {"en": "MTWTFSS", "ar": ["ن", "ث", "ر", "خ", "ج", "س", "ح"]}
MONTHS = {"en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                 "November", "December"],
          "ar": ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر",
                 "نوفمبر", "ديسمبر"]}


def lang():
    return "ar" if rtl() else "en"


def tr(key):
    """نص مترجم وجاهز للرسم (موصول ومرتب)."""
    pair = STRINGS.get(key)
    if not pair:
        return ar(key)
    return ar(pair[1]) if rtl() else pair[0]


def day_name(t=None):
    t = t or time.localtime()
    return DAYS[lang()][t.tm_wday]


def month_name(t=None):
    t = t or time.localtime()
    return MONTHS[lang()][t.tm_mon - 1]


def clock_text(t=None):
    t = t or time.localtime()
    h = t.tm_hour % 12 or 12
    if rtl():
        return ar(f"{day_name(t)} {t.tm_mday} {month_name(t)}  {h}:{t.tm_min:02d} {'ص' if t.tm_hour < 12 else 'م'}")
    return f"{day_name(t)[:3]} {t.tm_mday} {month_name(t)[:3]}  {h}:{t.tm_min:02d} {'AM' if t.tm_hour < 12 else 'PM'}"


def app_name(spec):
    """اسم التطبيق بلغة الواجهة."""
    name = spec.get("name", "")
    if rtl():
        if spec.get("name_ar"):
            return ar(spec["name_ar"])
        if name in STRINGS:
            return ar(STRINGS[name][1])
    return ar(name)
