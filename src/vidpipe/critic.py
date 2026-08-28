"""Субагент-критик: читает результат шага и методику и говорит, что не так.

Код проверяет то, что можно посчитать: объём, номера сцен, совпадение чисел,
запрещённые слова. Смысл он не проверяет. Критик закрывает именно это: держит
ли сценарий обещание входа, не показывает ли кадр разгадку, не звучит ли
заголовок как сотня других.

Два решения, которые здесь приняты сознательно.

Находки критика всегда warn. Он ошибается чаще кода, и локальная модель,
заблокировавшая верный сценарий, обойдётся дороже пропущенной шероховатости.
Останавливать конвейер разрешено только детерминированным проверкам.

По умолчанию критик выключен. На локальной модели каждый его проход это
минуты, а на длинном сценарии и того больше. Включается по шагам:

    CRITIC_STEPS=script,flow
"""
from __future__ import annotations

import json

from .config import env, env_int, read_prompt, read_text
from .validate import Issue

# что читать критику и какой методикой мерить
МАТЕРИАЛ = {
    "research": ("dossier.md",         "research.md",       None),
    "script":   ("script.md",          "script_engine.md",  None),
    "review":   ("script.md",          "review_engine.md",  "script_engine.md"),
    "thumb":    ("thumbnail.txt",      "packaging.md",      None),
    "shotlist": ("shotlist.csv",       "script_engine.md",  None),
    "flow":     ("flow_prompts.json",  "assets.md",         None),
}

SYSTEM = """Ты приёмщик. Тебе дают методику работы и результат, сделанный по
ней. Твоя задача найти расхождения между ними, а не похвалить и не переписать.

Правила:
- Пиши только то, что видно в самом результате. Не додумывай контекст.
- Каждая находка это конкретное место и конкретная правка, а не общее
  пожелание сделать лучше.
- Если результат соответствует методике, верни пустой список. Это нормальный
  и частый ответ, выдумывать замечания ради их наличия нельзя.
- Не больше пяти находок, самые важные.

Верни JSON-массив:
[{"what": "что не так, коротко", "fix": "что сделать"}]"""


def включённые() -> set[str]:
    строка = env("CRITIC_STEPS", "")
    return {ш.strip() for ш in строка.split(",") if ш.strip()}


def review_output(project, step: str) -> list[Issue]:
    """Находки критика по результату шага. Пустой список, если он выключен."""
    if step not in включённые() or step not in МАТЕРИАЛ:
        return []

    имя, методика, запасная = МАТЕРИАЛ[step]
    файл = project.dir / имя
    if not файл.exists():
        return []

    правила, откуда = read_prompt(project, методика, запасная)
    if not правила:
        return []

    предел = env_int("CRITIC_MAX_CHARS", 12000)
    материал = read_text(файл)[:предел]
    print(f"[критик] {step}: сверяю с {откуда}")

    from .llm import complete_json
    try:
        ответ = complete_json(
            SYSTEM,
            f"МЕТОДИКА:\n\n{правила}\n\nРЕЗУЛЬТАТ ШАГА {step}:\n\n{материал}",
            max_tokens=env_int("CRITIC_MAX_TOKENS", 1500),
        )
    except SystemExit as e:
        print(f"[критик] не сработал: {e}")
        return []

    if isinstance(ответ, dict):
        ответ = ответ.get("issues") or ответ.get("findings") or []
    if not isinstance(ответ, list):
        return []

    находки = []
    for запись in ответ[:5]:
        if not isinstance(запись, dict):
            continue
        что = str(запись.get("what", "")).strip()
        как = str(запись.get("fix", "")).strip()
        if что:
            # всегда warn: критик советует, останавливает только код
            находки.append(Issue("warn", f"критик: {что}", как))
    if not находки:
        print(f"[критик] {step}: замечаний нет")
    return находки
