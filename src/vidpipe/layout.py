"""Раскладка клипов по сценам, когда номер в имени не номер сцены.

`clips.py` опознаёт файл по словам промпта в его имени — этого хватает почти
всегда. Не хватает в одном случае, и он встречается постоянно: генератор
ведёт **две независимые нумерации**, видео с единицы и картинки с единицы.
Тогда в папке два файла с номером 001, и оба не про первую сцену.

Живой случай: в немецком выпуске видео шли 001–044, картинки 001–025, а
сцен было 69 — ровно 44 видеосцены и 25 картиночных. Файл `001_A-very-large-
library-reading-room` лежал на первой сцене, хотя его место пятое. Команда
`clips --apply` предлагала переставить 65 файлов из 94 и сломала бы выпуск.

Правило простое и проверено на четырёх выпусках двух каналов: **k-е видео
встаёт на k-ю видеосцену, k-я картинка на k-ю картиночную**. Перед тем как
что-то трогать, каждое имя сверяется со словами своего промпта; при слабом
совпадении не трогается ничего.

Варианты `_a`/`_b` — это два прогона одного кадра. Берётся `_a`, второй
уходит в `_варианты`: он нужен, когда в первом окажется читаемый текст или
чужая эпоха, и менять их приходилось не раз.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .config import read_text
from .frames import ВИДЕО, КАРТИНКИ

СЛУЖЕБНЫЕ = {"_original", "_варианты", "_до правки", "_посторонние",
             "_до снятия знака", "_до правки надписей"}


def слова(текст: str) -> set[str]:
    return {с for с in re.findall(r"[a-zA-Z]{4,}", текст.lower())}


def имя_под_сцену(номер: int, промпт: str, суффикс: str) -> str:
    слаг = "-".join(re.findall(r"[a-zA-Z]+", промпт)[:8])
    return "%03d-%s%s" % (номер, слаг, суффикс)


def _рабочие_файлы(clips: Path) -> list[Path]:
    вых = []
    for x in sorted(clips.rglob("*")):
        if not x.is_file() or x.suffix.lower() not in ВИДЕО | КАРТИНКИ:
            continue
        if any(ч in СЛУЖЕБНЫЕ for ч in x.relative_to(clips).parts[:-1]):
            continue
        вых.append(x)
    return вых


def разобрать(папка: Path) -> dict:
    """Что лежит в clips и как это ложится на сцены. Ничего не меняет."""
    clips = папка / "clips"
    поток = папка / "flow_prompts.json"
    if not clips.is_dir() or not поток.exists():
        return {"годится": False, "почему": "нет clips или flow_prompts.json"}
    сцены = json.loads(read_text(поток)).get("scenes") or []
    сц = {с["scene"]: с for с in сцены}
    видео_сц = [n for n in sorted(сц) if сц[n].get("kind") == "видео"]
    карт_сц = [n for n in sorted(сц) if сц[n].get("kind") != "видео"]

    файлы = _рабочие_файлы(clips)
    видеоф = sorted((x for x in файлы if x.suffix.lower() in ВИДЕО),
                    key=lambda x: x.name)
    карт_a, карт_b, прочие = {}, {}, []
    for x in файлы:
        if x.suffix.lower() in ВИДЕО:
            continue
        m = re.match(r"^(\d{3})[_-].*?_([ab])(?: \(\d+\))?\.\w+$", x.name)
        if m:
            (карт_a if m.group(2) == "a" else карт_b)[int(m.group(1))] = x
        else:
            прочие.append(x)
    if not карт_a and прочие:                       # без вариантов _a/_b
        for x in прочие:
            m = re.match(r"^(\d{3})", x.name)
            if m:
                карт_a[int(m.group(1))] = x

    план, слабо = [], []
    for k, ф in enumerate(видеоф, 1):
        if k > len(видео_сц):
            break
        н = видео_сц[k-1]
        п = сц[н].get("prompt", "")
        о = len(слова(ф.name.replace("-", " ")) & слова(п))
        (слабо if о < 2 else план).append(
            {"файл": ф, "сцена": н, "новое": имя_под_сцену(н, п, ф.suffix.lower()),
             "общих": о})
    for i, k in enumerate(sorted(карт_a), 1):
        if i > len(карт_сц):
            break
        н = карт_сц[i-1]
        п = сц[н].get("prompt", "")
        ф = карт_a[k]
        о = len(слова(ф.name.replace("_", " ").replace("-", " ")) & слова(п))
        (слабо if о < 2 else план).append(
            {"файл": ф, "сцена": н, "новое": имя_под_сцену(н, п, ф.suffix.lower()),
             "общих": о})

    покрыто = {п["сцена"] for п in план}
    return {
        "годится": bool(план) and not слабо,
        "почему": ("слабое совпадение у %d файлов" % len(слабо)) if слабо else "",
        "план": план,
        "слабо": слабо,
        "варианты": list(карт_b.values()),
        "лишние_видео": видеоф[len(видео_сц):],
        "нет_материала": [n for n in sorted(сц) if n not in покрыто],
        "сцен": len(сц),
    }


def разложить(папка: Path, разбор: dict | None = None) -> dict:
    """Переименовать по номерам сцен. Вторые варианты и лишнее — в сторону."""
    р = разбор or разобрать(папка)
    if not р.get("годится"):
        return р
    clips = папка / "clips"
    if р["варианты"]:
        вар = папка / "_варианты"
        вар.mkdir(exist_ok=True)
        for ф in р["варианты"]:
            shutil.move(str(ф), str(вар / ф.name))
    if р["лишние_видео"]:
        чужие = папка / "_посторонние"
        чужие.mkdir(exist_ok=True)
        for ф in р["лишние_видео"]:
            shutil.move(str(ф), str(чужие / ф.name))
    врем = {}
    for п in р["план"]:                              # два прохода: имена
        t = clips / ("__" + п["новое"])              # могут столкнуться
        п["файл"].rename(t)
        врем[t] = clips / п["новое"]
    for t, ц in врем.items():
        t.rename(ц)
    # пустые подпапки генератора больше не нужны
    for d in sorted(clips.rglob("*"), reverse=True):
        if d.is_dir() and d.name not in СЛУЖЕБНЫЕ and not any(d.iterdir()):
            d.rmdir()
    return р
