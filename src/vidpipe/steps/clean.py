"""Шаг 2: script.md -> voice.txt

Снимает всё, что диктор читать не должен: разметку, ремарки, таймкоды,
служебные блоки. Опционально разворачивает числа и сокращения в слова.
"""
from __future__ import annotations

import re

from num2words import num2words

from ..config import env_int, read_text

# --- блоки, которые вырезаем целиком ---------------------------------------
BLOCK_PATTERNS = [
    re.compile(r"^```.*?^```", re.S | re.M),          # код-блоки
    re.compile(r"^>.*$", re.M),                        # цитаты/заметки
    re.compile(r"^\s*[-*_]{3,}\s*$", re.M),            # горизонтальные линии
    re.compile(r"^\s*#{1,6}\s+.*$", re.M),             # заголовки
    re.compile(r"^\s*\[?(?:СЦЕНА|SCENE|B-ROLL|BROLL|ВИЗУАЛ|VISUAL|"
               r"ТАЙМКОД|TIMECODE|ХУК|HOOK|CTA)\b.*$", re.M | re.I),
]

# --- инлайновая зачистка ----------------------------------------------------
INLINE = [
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),                   # картинки
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),               # ссылки -> текст
    (re.compile(r"\[[^\]]{0,120}?\]"), ""),                      # [ремарки]
    (re.compile(r"\((?:пауза|pause|смех|вздох|музыка|sfx|звук)[^)]*\)", re.I), ""),
    (re.compile(r"\*\*|__|\*|_|`"), ""),                          # bold/italic/code
    (re.compile(r"^\s*\d{1,2}:\d{2}(?::\d{2})?\s*[-–—]?\s*", re.M), ""),  # тайминги
    (re.compile(r"^\s*[-*+]\s+", re.M), ""),                      # маркеры списка
    (re.compile(r"[«»\"\u201c\u201d]"), ""),                      # кавычки (TTS их спотыкает)
    (re.compile(r"[ \t]+"), " "),
    (re.compile(r"\n{3,}"), "\n\n"),
]

# Единицы измерения выносим отдельно: их падеж зависит от числа,
# поэтому разворачиваем только вместе с числами (--expand-numbers).
UNITS = {
    r"\bкм\b": "километров",
    r"\bкг\b": "килограммов",
    r"\bм/с\b": "метров в секунду",
    r"\bкм/ч\b": "километров в час",
}

ABBR = {
    r"\bт\.\s*е\.": "то есть",
    r"\bт\.\s*д\.": "так далее",
    r"\bт\.\s*п\.": "тому подобное",
    r"\bт\.\s*к\.": "так как",
    r"\bи\.\s*о\.": "исполняющий обязанности",
    r"\bг\.\s*р\.": "года рождения",
    r"\bдо н\.\s*э\.": "до нашей эры",
    r"\bн\.\s*э\.": "нашей эры",
    r"\bтыс\.": "тысяч",
    r"\bмлн\b\.?": "миллионов",
    r"\bмлрд\b\.?": "миллиардов",
    r"\bвв\.": "века",
    r"\bв\.\s*(?=[А-ЯЁ0-9])": "века ",
    r"%": " процентов",
    r"№": "номер ",
    r"\bг\.\s*(?=[А-ЯЁ])": "город ",
}


def _expand_numbers(text: str) -> str:
    """Числа -> слова. Годы (4 цифры) оставляем цифрами: падежи TTS обычно
    угадывает лучше, чем num2words в именительном."""
    def repl(m: re.Match) -> str:
        raw = m.group(0)
        digits = raw.replace(" ", "").replace("\u00a0", "")
        if len(digits) == 4 and digits.isdigit() and 1000 <= int(digits) <= 2100:
            return raw  # год — не трогаем
        try:
            words = num2words(int(digits), lang="ru")
        except Exception:
            return raw
        return re.sub(r"^одна тысяча", "тысяча", words)

    return re.sub(r"\b\d[\d \u00a0]*\d\b|\b\d\b", repl, text)


def clean(text: str, expand_numbers: bool = False) -> str:
    for pat in BLOCK_PATTERNS:
        text = pat.sub("", text)
    for pat, rep in INLINE:
        text = pat.sub(rep, text)
    for pat, rep in ABBR.items():
        text = re.sub(pat, rep, text)
    if expand_numbers:
        for pat, rep in UNITS.items():
            text = re.sub(pat, rep, text)
        text = _expand_numbers(text)

    # финальная нормализация
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    paragraphs = [p.strip() for p in text.split("\n\n")]
    return "\n\n".join(p for p in paragraphs if p) + "\n"


def run(project, force: bool = False, expand_numbers: bool = False) -> None:
    if not project.script.exists():
        raise SystemExit(f"[clean] нет {project.script} — сначала положи сценарий")
    if project.voice_txt.exists() and not force:
        print(f"[clean] пропуск, {project.voice_txt.name} уже есть (--force чтобы перезаписать)")
        return

    src = read_text(project.script)
    out = clean(src, expand_numbers=expand_numbers)
    project.voice_txt.write_text(out, encoding="utf-8")
    words = len(out.split())
    wpm = env_int("WORDS_PER_MIN", 150)
    print(f"[clean] {project.voice_txt.name}: {len(out)} симв., ~{words} слов, "
          f"~{words / wpm:.1f} мин озвучки")
