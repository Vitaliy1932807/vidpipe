"""Остановка после сценария: дальше конвейер идёт только с прочитанным текстом.

Сценарий — единственное место, где ошибка дорожает с каждым шагом. Опечатка
в тексте стоит секунды, пока она в тексте. Дальше её озвучивает платный голос,
она уезжает в субтитры, из субтитров в раскадровку, из раскадровки в промпты,
и всплывает на готовом ролике, когда переделывать нужно всё.

Поэтому шаги после сценария не начинаются, пока человек не сказал, что текст
прочитан. Подтверждение привязано не к факту, а к содержанию: помним отпечаток
текста. Правишь сценарий после проверки — подтверждение слетает само, иначе
оно означало бы «я читал» про текст, которого никто не читал.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from .config import read_text

# Шаги, которым непрочитанный сценарий обходится дороже всего: голос платный,
# а всё остальное считается от него и переделывается целиком.
ПОСЛЕ_СЦЕНАРИЯ = ("clean", "tts", "srt", "bible", "shotlist", "flow",
                  "thumb", "assemble")

ПОДСКАЗКА = "прочитай script.md, потом подтверди: vidpipe ok"


def отпечаток(текст: str) -> str:
    """Короткий отпечаток текста, нечувствительный к переводам строк.

    Файл переезжает между Windows и git, и CRLF против LF не должен выглядеть
    правкой сценария: подтверждение слетало бы на ровном месте.
    """
    ровно = "\n".join(с.rstrip() for с in текст.replace("\r\n", "\n").split("\n"))
    return hashlib.sha256(ровно.strip().encode("utf-8")).hexdigest()[:12]


def файл(project):
    return project.tmp / "принято.json"


def принять(project) -> str:
    """Записываем, что текст прочитан. Возвращаем отпечаток."""
    метка = отпечаток(read_text(project.script))
    файл(project).write_text(
        json.dumps({"сценарий": метка,
                    "когда": datetime.now().isoformat(timespec="seconds")},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return метка


def не_принят(project) -> str:
    """Почему дальше идти нельзя. Пустая строка — можно.

    Нет сценария — не наше дело: об этом скажет своя проверка, а на выпуске,
    который собирают без script.md, это правило молчит.
    """
    if not project.script.exists():
        return ""
    f = файл(project)
    if not f.exists():
        return "сценарий ещё не прочитан"
    try:
        было = json.loads(f.read_text(encoding="utf-8")).get("сценарий")
    except (json.JSONDecodeError, OSError):
        было = None
    if было != отпечаток(read_text(project.script)):
        return "сценарий изменился после проверки"
    return ""


def cmd_ok(args) -> None:
    from .config import Project

    project = Project.load(args.dir)
    if not project.script.exists():
        raise SystemExit(f"[ok] нет {project.script.name} — подтверждать нечего")

    слов = len(read_text(project.script).split())
    метка = принять(project)
    print(f"[ok] сценарий принят: {слов} слов, отпечаток {метка}")
    print("     правка текста снимет подтверждение — так и задумано")
