"""Приёмка результата шага перед передачей дальше.

В конвейере уже была проверка ВХОДА: preflight не пускает шаг, если ему нечем
работать. Но выход шага никто не смотрел, и брак ехал дальше как готовый
материал. Именно так в живом прогоне уехали 250 квадратных метров в библии
вместо пятидесяти пяти и промпт, показывающий фигуру в дверях там, где диктор
говорит «кто-то стоит».

Проверяет только код: считает, сверяет, сравнивает с соседними файлами. Он
либо прав, либо нет, и ему можно доверить остановку конвейера.

Смысловую приёмку моделью здесь пробовали и убрали. Замер на готовом сценарии
в 1263 слова: локальная 14B думала 6 минут и выдала пять находок, верных ноль.
Она заявила, что нет психологического разворота, хотя он есть и он лучшее
место текста, и что финал заканчивается вопросом, хотя вопросительных знаков
в тексте ноль. Уверенные ложные находки хуже молчания: они приучают не читать
приёмку. Всё, что вообще поддаётся счёту, проверяет код ниже; смысл остаётся
за человеком.
"""
from __future__ import annotations

import json
import re

from .config import read_text
from .validate import (Issue, check_clips, check_script, check_shotlist,
                       check_srt, check_video, check_voice_mp3,
                       check_voice_txt)


def перечислить(значения) -> str:
    """Список для сообщения: первые пять и сколько ещё."""
    значения = [str(з) for з in значения]
    хвост = f" и ещё {len(значения) - 5}" if len(значения) > 5 else ""
    return ", ".join(значения[:5]) + хвост


def check_dossier(project) -> list[Issue]:
    """Досье собрано моделью по памяти: без пометки его примут за источник."""
    досье = project.dir / "dossier.md"
    if not досье.exists():
        return []                       # шаг research необязателен
    текст = read_text(досье)
    out: list[Issue] = []
    if "первоисточник" not in текст.lower():
        out.append(Issue("warn", "в досье нет пометки о проверке фактов",
                         "vidpipe -s research -f, шапка ставится сама"))
    if len(текст.split()) < 150:
        out.append(Issue("warn", f"досье короткое: {len(текст.split())} слов",
                         "vidpipe -s research -f"))
    return out


# Модель охотно описывает то, что по замыслу должно остаться неизвестным.
# Слова "figure" в списке нет намеренно: по-английски это ещё и телосложение,
# и запись вида "lean figure" в описании живого героя законна.
ЗАПРЕТНОЕ_В_БИБЛИИ = ("shadowy", "silhouette", "apparition", "ghost",
                      "phantom", "faceless", "face hidden", "the entity",
                      "unseen presence", "призрак", "силуэт", "фигура в")


def check_bible(project) -> list[Issue]:
    """Библия: формат идентификаторов, описанная загадка, выдуманные числа."""
    if not project.bible.exists():
        return []
    from .steps.bible import ID, parse

    книга = parse(read_text(project.bible))
    герои = книга.get("CHARACTERS") or {}
    предметы = книга.get("OBJECTS") or {}
    if not герои and not предметы:
        return [Issue("stop", "библия пуста: ни героев, ни предметов",
                      "vidpipe -s bible -f")]

    out: list[Issue] = []
    плохие = [и for и in list(герои) + list(предметы) if not ID.match(и)]
    if плохие:
        out.append(Issue("warn",
                         f"идентификаторы не по формату: {перечислить(плохие)}",
                         "заглавными латиницей с подчёркиванием: PETR_01"))

    for иден, опис in {**герои, **предметы}.items():
        низ = опис.lower()
        найдено = next((с for с in ЗАПРЕТНОЕ_В_БИБЛИИ if с in низ), "")
        if найдено:
            out.append(Issue("stop", f"{иден} описывает необъяснимое: {найдено}",
                             "убери описание руками: названная загадка "
                             "перестаёт быть загадкой"))

    # Числа модель выдумывает: в живом прогоне панелям досталось 250
    # квадратных метров вместо пятидесяти пяти, что прямо спорит со сценарием.
    #
    # Сверяем по всем текстам ролика сразу. И молчим, если цифр в них нет
    # вовсе: перед озвучкой числа заменяются словами, и тогда сверять нечем.
    # Кричать в этом случае значит приучить человека не читать находки.
    источники = [f for f in (project.script, project.prompt,
                             project.dir / "dossier.md") if f.exists()]
    известное = "".join(read_text(f) for f in источники).replace(" ", "")
    if re.search(r"\d", известное):
        for иден, опис in предметы.items():
            for число in re.findall(r"(\d[\d\s]{0,6}\d|\d+)\s*(?:square met|метр)",
                                    опис):
                ч = число.replace(" ", "")
                if ч not in известное:
                    out.append(Issue("warn",
                                     f"{иден}: числа {ч} нет в сценарии",
                                     "сверь с текстом, модель путает величины"))
    return out


def check_flow(project) -> list[Issue]:
    """Промпты Flow: пустоты, спойлеры, чужие герои, финал вне мира ролика."""
    if not project.flow.exists():
        return [Issue("stop", "нет flow_prompts.json", "vidpipe -s flow")]
    from .steps import flow as шаг

    try:
        данные = json.loads(read_text(project.flow))
    except json.JSONDecodeError:
        return [Issue("stop", "flow_prompts.json не читается",
                      "vidpipe -s flow -f")]

    сцены = данные.get("scenes") or []
    глоб = данные.get("global") or {}
    if not сцены:
        return [Issue("stop", "в flow_prompts.json нет сцен", "vidpipe -s flow -f")]

    out: list[Issue] = []
    пустые = [с.get("scene") for с in сцены if not (с.get("prompt") or "").strip()]
    if пустые:
        out.append(Issue("stop", f"без промпта остались сцены: {перечислить(пустые)}",
                         "vidpipe -s flow -f"))

    спойлеры = [с.get("scene") for с in сцены
                if шаг.спойлер(с.get("narration", ""), с.get("prompt", ""))]
    if спойлеры:
        out.append(Issue("stop",
                         f"разгадка показана раньше диктора: {перечислить(спойлеры)}",
                         "перепиши промпт руками или vidpipe -s flow -f"))

    известные = set(глоб.get("characters") or {}) | set(глоб.get("objects") or {})
    чужие = sorted({и for с in сцены for и in (с.get("characters") or [])
                    if и not in известные})
    if чужие:
        out.append(Issue("warn", f"герои не из библии: {перечислить(чужие)}",
                         "vidpipe -s bible, потом vidpipe -s flow -f"))

    # Модель приписывает сцене героя, которого в самом промпте нет. Сборка
    # такое описание выбрасывает, но исходные данные стоит поправить.
    призраки = [с.get("scene") for с in сцены
                if с.get("characters")
                and not any(ч in (с.get("prompt") or "").lower()
                            for ч in шаг.ЛЮДИ_В_ПРОМПТЕ)]
    if призраки:
        out.append(Issue("warn",
                         f"герой указан, а в кадре его нет: {перечислить(призраки)}",
                         "описание в промпт не попадёт; убери героя из сцены "
                         "или впиши человека в само действие"))

    if шаг.финал_без_якоря(сцены, глоб):
        out.append(Issue("warn", "последний кадр не цепляется за мир ролика",
                         f"перепиши сцену {сцены[-1].get('scene')} руками"))

    if not глоб.get("style"):
        out.append(Issue("warn", "нет блока стиля: кадры будут разнобойными",
                         "заполни assets.md в канале"))
    return out


def check_thumbnail(project) -> list[Issue]:
    if not project.thumbnail.exists():
        return []
    if len(read_text(project.thumbnail).split()) < 30:
        return [Issue("warn", "упаковка подозрительно короткая",
                      "vidpipe -s thumb -f")]
    return []


# Что проверять ПОСЛЕ шага, до передачи дальше.
POSTFLIGHT = {
    "research": [check_dossier],
    "script":   [check_script],
    "review":   [check_script],
    "clean":    [check_voice_txt],
    "tts":      [check_voice_mp3],
    "srt":      [check_srt],
    "bible":    [check_bible],
    "shotlist": [check_shotlist],
    "flow":     [check_flow],
    "thumb":    [check_thumbnail],
    "assemble": [check_video],
}


def postflight(project, step: str, strict: bool = True) -> None:
    """Смотрим, что шаг отдал, до того как это уедет дальше.

    strict=False снимает остановку: полезно, когда конвейер гонят целиком и
    человек всё равно будет вычитывать результат сам.
    """
    issues: list[Issue] = []
    for fn in POSTFLIGHT.get(step, []):
        issues += fn(project)
    for i in issues:
        print(i.show())

    if [i for i in issues if i.level == "stop"] and strict:
        raise SystemExit(
            f"[{step}] результат не принят — дальше он поедет как готовый.\n"
            f"  исправь верхнее или запусти с --loose, если знаешь, что делаешь"
        )
