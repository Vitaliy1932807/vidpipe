"""Одна команда на выпуск: разложить, снять знак, собрать, проверить.

Порядок не произвольный, он повторяет то, как выпуск ломается на практике:

  1. раскладка   пока файлы лежат под номерами генератора, всё остальное
                 бессмысленно: соберётся не тот фильм, и по логам это не
                 будет видно.
  2. знак        снимать до сборки. После сборки пришлось бы чистить кэш
                 посценных кусков и пересобирать заново — так уже было.
  3. сборка      только если закрыты все сцены. Собирать выпуск с дырами
                 нельзя: молча встанет чужой кадр.
  4. проверка    аудит по готовому фильму.
  5. итог        что осталось человеку: какие сцены сгенерировать, какие
                 кадры посмотреть глазами.

Команда ничего не выдумывает. Недостающие кадры она не рисует — она их
называет и кладёт рядом готовые промпты, чтобы их можно было взять и
отправить в генератор не правя.

Всё, что заменяется, сначала копируется в сторону: `_варианты`,
`_посторонние`, `_до снятия знака`. Ни один исходник не пропадает.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .config import Project, read_text
from .frames import ВИДЕО, _нужен_cv2, длительность, это_выпуск


def _промпты_недостающих(папка: Path, нет: list[int]) -> Path | None:
    """Файл с промптами несделанных сцен — в том же виде, что у генератора."""
    поток = папка / "flow_prompts.json"
    ассеты = папка / "assets.md"
    if not поток.exists() or not нет:
        return None
    сц = {с["scene"]: с for с in json.loads(read_text(поток)).get("scenes") or []}
    блоки = {}
    if ассеты.exists():
        т = read_text(ассеты)
        for имя in ("STYLE", "ENV", "NEGATIVE"):
            m = re.search(r"\[%s\]\n(.*?)(?=\n\[|\Z)" % имя, т, re.S)
            блоки[имя] = m.group(1).strip().replace("\n", " ") if m else ""
    строки = []
    for н in нет:
        с = сц.get(н)
        if not с:
            continue
        части = [с.get("prompt", "").rstrip(". ") + "."]
        for поле in ("camera", "motion", "light"):
            v = с.get(поле)
            if v:
                части.append(str(v).rstrip(". ") + ".")
        for имя in ("STYLE", "ENV", "NEGATIVE"):
            if блоки.get(имя):
                части.append(блоки[имя].rstrip(". ") + ".")
        строки.append("%d\n%s\n" % (н, " ".join(части)))
    if not строки:
        return None
    ф = папка / "промпты-НЕДОСТАЮЩИЕ.txt"
    ф.write_text("\n".join(строки), encoding="utf-8")
    return ф


def _снять_знак(папка: Path, проба: bool) -> tuple[int, int, int]:
    """Снять знак Veo. Возвращает (снято, найдено, всего видео).

    `veo.найти` возвращает кандидата всегда — решает поле `уверенно`. Без
    этой проверки командой можно было бы переписать два десятка чистых
    клипов: на девятом выпуске она бралась «снимать» знак с 21 видео из 27,
    где связь была 0.015 при пороге 0.62.

    После правки результат проверяется `остаток`: если знак остался, клип
    не подменяется. Лучше оставить как было, чем молча испортить.
    """
    from . import veo
    from .marks import записать_клип, читать_клип
    clips = папка / "clips"
    видео = sorted(x for x in clips.glob("*") if x.suffix.lower() in ВИДЕО)
    if not видео:
        return 0, 0, 0
    запас = папка / "_до снятия знака"
    снято = найдено = 0
    for ф in видео:
        if (запас / ф.name).exists():                # уже чистили
            continue
        кадры, фпс = читать_клип(ф)
        if not кадры:
            continue
        место = veo.найти(кадры)
        if not место or not место.get("уверенно"):
            continue
        сила = veo.сила(кадры, место)
        if not сила or сила <= veo.ШУМ:
            continue
        найдено += 1
        if проба:
            continue
        готовые = [veo.снять(к, место, сила) for к in кадры]
        ост = veo.остаток(готовые, место)
        if ост is not None and ост > veo.ОСТАТОК:
            print("    %s: знак не снялся (остаток %.3f), оставляю как было"
                  % (ф.name[:44], ост), flush=True)
            continue
        врем = ф.with_suffix(".новый.mp4")
        записать_клип(готовые, фпс, врем)
        if abs(длительность(ф) - длительность(врем)) > 0.06:
            врем.unlink(missing_ok=True)
            continue
        запас.mkdir(exist_ok=True)
        shutil.copy2(str(ф), str(запас / ф.name))
        врем.replace(ф)
        снято += 1
    return снято, найдено, len(видео)


def cmd_finish(args) -> None:
    _нужен_cv2()
    from .audit import cmd_audit
    from .layout import разложить, разобрать
    from .steps import assemble

    project = Project.load(args.dir)
    папка = Path(project.dir)
    if not это_выпуск(папка):
        print("это не папка выпуска:", папка, flush=True)
        print("  нет ни shotlist.csv, ни clips, ни video.mp4", flush=True)
        print("  какие папки знает автоматика — vidpipe channels", flush=True)
        raise SystemExit(2)
    проба = bool(getattr(args, "проба", False))
    print("=== выпуск: %s%s" % (папка.name, "  (проба, ничего не меняю)" if проба else ""),
          flush=True)

    # 1. раскладка
    р = разобрать(папка)
    if not р.get("годится") and р.get("почему"):
        print("раскладка: не трогаю — %s" % р["почему"], flush=True)
        for с in р.get("слабо", [])[:5]:
            print("    %-46s -> сц %s, общих слов %d"
                  % (с["файл"].name[:46], с["сцена"], с["общих"]), flush=True)
    elif р.get("годится"):
        надо = [п for п in р["план"] if п["файл"].name != п["новое"]]
        if надо or р["варианты"] or р["лишние_видео"]:
            if проба:
                print("раскладка: переименовать %d, вариантов в сторону %d, "
                      "посторонних %d" % (len(надо), len(р["варианты"]),
                                          len(р["лишние_видео"])), flush=True)
            else:
                разложить(папка, р)
                print("раскладка: разложено %d файлов, вариантов убрано %d, "
                      "посторонних %d" % (len(р["план"]), len(р["варианты"]),
                                          len(р["лишние_видео"])), flush=True)
        else:
            print("раскладка: всё уже на своих местах", flush=True)

    нет = р.get("нет_материала") or []

    # 2. знак
    if not args.без_знака:
        print("знак: проверяю клипы...", flush=True)
        снято, найдено, всего = _снять_знак(папка, проба)
        if всего:
            if not найдено:
                print("знак: не найден ни в одном из %d видео" % всего, flush=True)
            elif проба:
                print("знак: нашёлся в %d из %d видео" % (найдено, всего), flush=True)
            else:
                print("знак: снят с %d из %d видео (найден в %d)"
                      % (снято, всего, найдено), flush=True)

    # 3. сборка
    фильм = папка / "video.mp4"
    if нет:
        print("сборка: пропущена — нет материала на %d сцен из %d"
              % (len(нет), р.get("сцен", 0)), flush=True)
        ф = _промпты_недостающих(папка, нет)
        if ф:
            print("    промпты недостающего: %s" % ф.name, flush=True)
    elif проба:
        print("сборка: собралась бы (%s)"
              % ("заново" if фильм.exists() else "впервые"), flush=True)
    else:
        if фильм.exists() and args.force:
            запас = папка / "_до правки"
            запас.mkdir(exist_ok=True)
            shutil.move(str(фильм), str(запас / "video (прежний).mp4"))
            кэш = папка / ".vidpipe"
            for f in list(кэш.glob("seg_*.mp4")) + [кэш / "silent.mp4"]:
                if f.exists():
                    f.unlink()
        if фильм.exists():
            print("сборка: video.mp4 уже есть, для пересборки нужен --force",
                  flush=True)
        else:
            print("сборка: идёт...", flush=True)
            assemble.run(project, force=True)

    # 4. проверка
    if фильм.exists() and not args.без_проверки:
        print("", flush=True)
        cmd_audit(args)

    # 5. итог
    print("\n=== что осталось человеку", flush=True)
    if нет:
        print("  сгенерировать %d сцен: %s" % (len(нет), ", ".join(map(str, нет[:20]))
                                               + (" ..." if len(нет) > 20 else "")),
              flush=True)
    if фильм.exists():
        print("  посмотреть глазами кадры, помеченные аудитом выше", flush=True)
        print("  фильм: %s (%.0f с)" % (фильм, длительность(фильм)), flush=True)
    if not нет and not фильм.exists():
        print("  ничего: материал полный, фильм соберётся следующим запуском",
              flush=True)
