"""Шаг 1: тема -> prompt.md -> script.md

prompt.md — это ТЗ на ролик (тема, формат, хронометраж, тон, обязательные
факты). Создаётся из --topic, дальше его можно править руками и перегенерить
сценарий с --force, не трогая код.
"""
from __future__ import annotations

from pathlib import Path

from ..config import env, env_int, read_text
from ..llm import complete
from .. import series

PROMPT_TEMPLATE = """# ТЗ на ролик

**ТЕМА:** {topic}

**ФОРМАТ:** {fmt}
**ХРОНОМЕТРАЖ:** {duration} минут
**ЯЗЫК:** {lang}
**ТОН:** {tone}
**АУДИТОРИЯ:** {audience}

**ГЛАВНОЕ ОБЕЩАНИЕ:**
<!-- что зритель должен понять к концу; пусто = определит модель -->

**ОБЯЗАТЕЛЬНЫЕ ФАКТЫ:**
<!-- имена, даты, цифры, которые должны попасть в текст -->

**ОГРАНИЧЕНИЯ:**
<!-- что не упоминать -->

**ПРИЗЫВЫ К ДЕЙСТВИЮ:** нет
"""


def make_prompt(project, topic: str, force: bool = False) -> None:
    if project.prompt.exists() and not force:
        print(f"[brief] пропуск, {project.prompt.name} уже есть")
        return
    project.prompt.write_text(
        PROMPT_TEMPLATE.format(
            topic=topic,
            fmt=env("DEFAULT_FORMAT", "документальная история"),
            duration=env_int("DEFAULT_DURATION_MIN"),
            lang=env("DEFAULT_LANG"),
            tone=env("DEFAULT_TONE", "сдержанный, аналитический"),
            audience=env("DEFAULT_AUDIENCE", "взрослые, интересуются историей"),
        ),
        encoding="utf-8",
    )
    print(f"[brief] {project.prompt.name} создан — проверь и поправь перед генерацией")


def run(project, force: bool = False, topic: str | None = None) -> None:
    if topic:
        make_prompt(project, topic, force=force)
    if not project.prompt.exists():
        raise SystemExit(
            f"[script] нет {project.prompt}. Запусти с --topic \"твоя тема\" "
            f"или создай файл руками"
        )
    if project.script.exists() and not force:
        print(f"[script] пропуск, {project.script.name} уже есть")
        return

    engine = project.resource("script_engine.md")
    print(f"[script] методика: {engine} ({project.resource_source('script_engine.md')})")
    system = read_text(engine)
    brief = read_text(project.prompt)
    duration = env_int("DEFAULT_DURATION_MIN")
    wpm = env_int("WORDS_PER_MIN")

    avoid = series.constraints(project)
    if avoid:
        print(f"[script] в памяти серии есть предыдущие выпуски, повторы запрещены")

    user = (
        f"{brief}\n\n"
        f"{avoid}"
        f"Напиши готовый текст закадрового голоса по этому ТЗ. "
        f"Целевой объём — примерно {duration * wpm} слов "
        f"(~{duration} минут озвучки при {wpm} словах в минуту). "
        f"Выведи только текст диктора: без заголовков, таймкодов, ремарок, "
        f"описаний картинки и комментариев к структуре."
    )

    text = complete(system, user, max_tokens=env_int("SCRIPT_MAX_TOKENS"))
    project.script.write_text(text.strip() + "\n", encoding="utf-8")
    words = len(text.split())
    print(f"[script] {project.script.name}: ~{words} слов, ~{words / wpm:.1f} мин")
    series.record(project, text)
