"""
arabic.py — Arabic text shaping (joining letters) and right-to-left ordering, with no dependencies.

Pillow on Windows has no text-shaping engine, so we map every letter to its Unicode presentation
form (isolated/initial/medial/final) and reorder the text for display.
"""
import unicodedata

_FORMS, _LIGS = {}, {}


def _build():
    # الأشكال الأساسية (FE70–FEFF) أولاً؛ وبعدها حروف إضافية (فارسية) من FB50 لو ما لها أشكال.
    # لام-ألف بس من FEF5–FEFC لأن الخط ما فيه باقي الربطات (مثل لام-ألف مقصورة).
    for block in (range(0xFE70, 0xFF00), range(0xFB50, 0xFE00)):
        added = {}
        for cp in block:
            ch = chr(cp)
            name = unicodedata.name(ch, "")
            for form in ("ISOLATED", "FINAL", "INITIAL", "MEDIAL"):
                suffix = f" {form} FORM"
                if not name.endswith(suffix):
                    continue
                base = name[:-len(suffix)]
                try:
                    if base.startswith("ARABIC LIGATURE LAM WITH ALEF") and 0xFEF5 <= cp <= 0xFEFC:
                        alef = unicodedata.lookup("ARABIC LETTER " + base[len("ARABIC LIGATURE LAM WITH "):])
                        _LIGS.setdefault(alef, {})[form.lower()] = ch
                    elif base.startswith("ARABIC LETTER "):
                        letter = unicodedata.lookup(base)
                        if letter not in _FORMS or letter in added:
                            added[letter] = True
                            _FORMS.setdefault(letter, {})[form.lower()] = ch
                except KeyError:
                    pass


_build()
LAM, TATWEEL = "ل", "ـ"
MIRROR = str.maketrans("()[]{}<>«»", ")(][}{><»«")


def _transparent(c):
    return unicodedata.category(c) == "Mn"


def _joins_next(c):
    f = _FORMS.get(c)
    return c == TATWEEL or bool(f and ("initial" in f or "medial" in f))


def _joins_prev(c):
    return c == TATWEEL or c in _FORMS


def has_arabic(text):
    return any("؀" <= c <= "ۿ" or "ݐ" <= c <= "ݿ" for c in text)


def shape(text):
    chars, out, i = list(text), [], 0
    n = len(chars)

    def neighbor(idx, step):
        j = idx + step
        while 0 <= j < n and _transparent(chars[j]):
            j += step
        return (chars[j], j) if 0 <= j < n else (None, j)

    while i < n:
        c = chars[i]
        prev, _ = neighbor(i, -1)
        joined_prev = prev is not None and _joins_next(prev) and _joins_prev(c)
        if c == LAM:
            nxt, j = neighbor(i, 1)
            if nxt in _LIGS:
                lig = _LIGS[nxt]
                out.append(lig.get("final" if joined_prev else "isolated", lig.get("isolated", c)))
                out.extend(chars[i + 1:j])  # الحركات بين اللام والألف
                i = j + 1
                continue
        f = _FORMS.get(c)
        if f:
            nxt, _ = neighbor(i, 1)
            joined_next = nxt is not None and _joins_next(c) and _joins_prev(nxt)
            if joined_prev and joined_next and "medial" in f:
                c = f["medial"]
            elif joined_prev and "final" in f:
                c = f["final"]
            elif joined_next and "initial" in f:
                c = f["initial"]
            else:
                c = f.get("isolated", c)
        out.append(c)
        i += 1
    return "".join(out)


def _strong(c):
    b = unicodedata.bidirectional(c)
    if b in ("R", "AL"):
        return "R"
    if b in ("L", "EN", "AN"):
        return "L"  # الأرقام تنقرى من اليسار لليمين
    return None


def visual(text, rtl=None):
    """يرتب النص للعرض. rtl=None: الاتجاه من أول حرف قوي."""
    dirs = [_strong(c) for c in text]
    if "R" not in dirs:
        return text
    base = rtl if rtl is not None else next((d for d in dirs if d), "L") == "R"
    base_d = "R" if base else "L"
    n = len(text)
    resolved = list(dirs)
    for i in range(n):
        if resolved[i] is None:
            before = next((dirs[j] for j in range(i - 1, -1, -1) if dirs[j]), base_d)
            after = next((dirs[j] for j in range(i + 1, n) if dirs[j]), base_d)
            resolved[i] = before if before == after else base_d
    runs, start = [], 0
    for i in range(1, n + 1):
        if i == n or resolved[i] != resolved[start]:
            seg = text[start:i]
            runs.append(seg[::-1].translate(MIRROR) if resolved[start] == "R" else seg)
            start = i
    return "".join(reversed(runs)) if base else "".join(runs)


def ar(text, rtl=None):
    """الدالة الوحيدة اللي يحتاجها الرسم: تشكيل + ترتيب، وتترك الإنجليزي زي ما هو."""
    if not text or not has_arabic(text):
        return text
    # التشكيل (الحركات) ما يتموضع صح بدون محرك خطوط متقدم، فنشيله من نصوص الواجهة
    text = "".join(c for c in text if not ("ً" <= c <= "ٟ" or c == "ٰ"))
    return visual(shape(text), rtl)
