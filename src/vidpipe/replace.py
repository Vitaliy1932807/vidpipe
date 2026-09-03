"""Замена одной сцены: перегенерировали кадр — поставить его на место.

Отдельная команда, потому что порядок здесь обратный раскладке. При первой
раскладке файлов столько же, сколько сцен, и каждый ищет своё место. При
замене место уже занято: новый файл надо положить **под тем же именем**, что
и старый, иначе видео станет на одно больше, чем видеосцен, и раскладка
уберёт лишнее в `_посторонние`.

Кэш посценных кусков чистится здесь же. Забыть про него легко, а последствие
незаметное: сборка возьмёт старый кусок, фильм выйдет байт в байт прежним, и
по логам это не будет видно. Так уже было.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import json
import re

from .config import Project, read_text
from .frames import ВИДЕО, КАРТИНКИ, длительность, это_выпуск
from .layout import слова


def файл_сцены(clips: Path, номер: int) -> Path | None:
    начало = "%03d-" % номер
    for x in sorted(clips.iterdir()):
        if x.is_file() and x.name.startswith(начало):
            return x
    return None


def угадать_сцену(папка: Path, новый: Path) -> tuple[int | None, list]:
    """Какой сцене принадлежит файл — по словам промпта в его имени.

    Генератор оставляет в имени начало промпта, и этого хватает: имя
    `A-crowd-of-press-photographers` ни на что, кроме своей сцены, не похоже.
    Номер в имени не берётся вовсе — у генератора своя нумерация, к сценам
    отношения не имеющая.
    """
    поток = папка / "flow_prompts.json"
    if not поток.exists():
        return None, []
    сц = {с["scene"]: с for с in json.loads(read_text(поток)).get("scenes") or []}
    имя = слова(новый.stem.replace("_", " ").replace("-", " "))
    оценки = []
    for н, с in сц.items():
        общ = len(имя & слова(с.get("prompt", "")))
        if общ:
            оценки.append((общ, н))
    оценки.sort(reverse=True)
    if not оценки or оценки[0][0] < 3:
        return None, оценки[:3]
    # Мало победить — надо победить с отрывом. Живой случай: клип
    # `the-same-small-amber-indicator-lamp` набрал 4 слова на сцене 14 и
    # 3 на сцене 65, а принадлежал он сцене 64. Перевес в одно слово
    # ничего не значит: лампа в этом выпуске встречается девять раз.
    if len(оценки) > 1 and оценки[0][0] - оценки[1][0] < 2:
        return None, оценки[:3]              # почти ничья — решать человеку
    return оценки[0][1], оценки[:3]


def cmd_replace(args) -> None:
    project = Project.load(args.dir)
    папка = Path(project.dir)
    if not это_выпуск(папка):
        print("это не папка выпуска:", папка, flush=True)
        raise SystemExit(2)
    новый = Path(args.file)
    if not новый.exists():
        raise SystemExit("нет файла: %s" % новый)
    clips = папка / "clips"
    номер = args.scene
    if номер is None:
        номер, близкие = угадать_сцену(папка, новый)
        if номер is None:
            print("не могу понять, какой сцене принадлежит файл:", новый.name,
                  flush=True)
            for общ, н in близкие:
                print("    похоже на сцену %d (общих слов %d)" % (н, общ),
                      flush=True)
            print("  назовите сцену прямо: vidpipe replace НОМЕР файл",
                  flush=True)
            raise SystemExit(2)
        print("сцена определена по имени файла: %d" % номер, flush=True)
    args.scene = номер
    старый = файл_сцены(clips, номер)
    if старый is None:
        raise SystemExit("в clips нет файла сцены %d — заменять нечего"
                         % args.scene)

    вид_с = "видео" if старый.suffix.lower() in ВИДЕО else "картинка"
    вид_н = ("видео" if новый.suffix.lower() in ВИДЕО else
             "картинка" if новый.suffix.lower() in КАРТИНКИ else "неизвестно")
    if вид_н == "неизвестно":
        raise SystemExit("не пойму, что это за файл: %s — ни видео, ни картинка"
                         % новый.name)

    print("сцена %d: %s" % (args.scene, старый.name), flush=True)
    print("  заменяю на: %s" % новый.name, flush=True)
    if вид_с != вид_н:
        print("  ! сцена помечена как %s, а файл %s — сборка возьмёт файл"
              % (вид_с, вид_н), flush=True)
    if вид_н == "видео" and вид_с == "видео":
        a, b = длительность(старый), длительность(новый)
        print("  длина: было %.2f с, стало %.2f с" % (a, b), flush=True)
        if b < a - 0.05:
            print("  ! новый клип короче — сборка дотянет его последним кадром",
                  flush=True)
    if args.проба:
        print("  проба: ничего не меняю", flush=True)
        return

    запас = папка / "_до правки"
    запас.mkdir(exist_ok=True)
    цель = запас / старый.name
    if цель.exists():
        цель = запас / ("прежний-" + старый.name)
    shutil.move(str(старый), str(цель))
    # имя сохраняем прежнее, меняем только расширение под новый файл
    имя = старый.stem + новый.suffix.lower()
    shutil.copy2(str(новый), str(clips / имя))
    print("  поставлен как %s, прежний в _до правки" % имя, flush=True)
    # Исходник, если он лежал в самой clips, надо унести. Иначе он остаётся
    # вторым файлом на ту же сцену: после трёх замен в папке стало 33 видео
    # на 29 видеосцен, раскладка сочла совпадения слабыми и встала, а сборка
    # не пошла вовсе. Копию кладём рядом, но не в clips.
    try:
        внутри = новый.resolve().is_relative_to(clips.resolve())
    except AttributeError:                    # python < 3.9
        внутри = str(clips.resolve()) in str(новый.resolve())
    if внутри:
        вар = папка / "_варианты"
        вар.mkdir(exist_ok=True)
        shutil.move(str(новый), str(вар / новый.name))
        print("  исходник убран в _варианты — в clips он был бы лишним файлом",
              flush=True)

    кэш = папка / ".vidpipe"
    снято = 0
    for f in (кэш / ("seg_%03d.mp4" % args.scene), кэш / "silent.mp4",
              папка / "video.mp4"):
        if f.exists():
            if f.name == "video.mp4":
                куда = запас / "video (до замены).mp4"
                н = 2
                while куда.exists():
                    куда = запас / ("video (до замены %d).mp4" % н)
                    н += 1
                shutil.move(str(f), str(куда))
            else:
                f.unlink()
            снято += 1
    print("  снято из кэша: %d — иначе сборка взяла бы прежний кусок" % снято,
          flush=True)
    print("\nдальше: vidpipe finish   (или vidpipe run -s assemble)", flush=True)
