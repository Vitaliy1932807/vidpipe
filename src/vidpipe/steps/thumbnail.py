"""Шаг 7: script.md -> thumbnail.txt (варианты заголовка + промпт обложки)."""
from __future__ import annotations

from ..config import env_int, read_text
from ..llm import complete

SYSTEM = """Ты придумываешь обложку и заголовок для документального YouTube-ролика.

Выведи ровно в таком виде, без лишних пояснений:

ЗАГОЛОВКИ (5 вариантов, до 60 символов, без кликбейта-обмана):
1. ...

ТЕКСТ НА ОБЛОЖКЕ (3 варианта, 2-4 слова, крупно):
1. ...

ПРОМПТ ОБЛОЖКИ (английский, для Imagen/Midjourney, 16:9, без текста в кадре):
...

ОПИСАНИЕ ПОД РОЛИК (2-3 предложения):
...

ТЕГИ (12 штук через запятую):
..."""


def run(project, force: bool = False) -> None:
    if not project.script.exists():
        raise SystemExit(f"[thumb] нет {project.script} — сначала шаг script")
    if project.thumbnail.exists() and not force:
        print(f"[thumb] пропуск, {project.thumbnail.name} уже есть")
        return

    script = read_text(project.script)
    head = script[:6000]
    user = f"Текст ролика (начало):\n\n{head}"
    project.thumbnail.write_text(
        complete(SYSTEM, user, max_tokens=env_int("THUMB_MAX_TOKENS", 2000)).strip() + "\n",
        encoding="utf-8",
    )
    print(f"[thumb] {project.thumbnail.name} готов")
