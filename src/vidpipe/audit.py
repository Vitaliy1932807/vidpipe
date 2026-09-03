"""Аудит готового ролика: короткий текстовый отчёт вместо просмотра кадров.

Проверяет четыре вещи, каждая из которых уже ловила настоящий брак:

  сходимость   видео короче озвучки — значит потерян финал. Так было в
               первом выпуске хинди: раскладка выбросила паузы между
               кадрами, ролик оборвался на шестнадцать секунд раньше и
               потерял всю развязку.

  знак         водяной знак генератора в углу. Виден не на всех кадрах:
               фон под ним меняется, и одна проба даёт 2 там, где на другой
               секунде 103. Поэтому берётся максимум по нескольким пробам.

  склейки      два разных плана под одним именем файла. В девятом выпуске
               такой клип показывал в ролике не то, что лежало в папке, и
               найти это удалось только раскадровкой самого файла.

  попадание    кадр против своего промпта, ранг среди всех промптов ролика.
               Ловит перепутанные и не те кадры: в седьмом выпуске сцена с
               мотоциклом заняла последнее место из семидесяти пяти, и там
               действительно был не мотоцикл.

Отчёт называет только подозрительное. Смотреть глазами предлагается
несколько кадров, а не весь ролик.
"""
from __future__ import annotations

from pathlib import Path

from .config import PACKAGE_ASSETS, Project
from .frames import (ВИДЕО, _нужен_cv2, длительность, кадр, прочитать_картинку, это_выпуск,
                     промпты, сцены_раскадровки, склейка_внутри, файлы_клипов)

ЗНАК_ДОЛИ = (1214/1280, 680/720, 1278/1280, 715/720)
ЗНАК_ПОРОГ = 25.0
ПРОБЫ = (0.06, 0.25, 0.45, 0.65, 0.88)


def _альфа_знака():
    import numpy as np
    ф = PACKAGE_ASSETS / "watermark_alpha.npy"
    return np.load(ф) if ф.exists() else None


def оценка_знака(картинка, альфа) -> float | None:
    """Насколько пиксели под буквами знака светлее соседнего фона."""
    import cv2
    import numpy as np
    if картинка is None or альфа is None:
        return None
    H, W = картинка.shape[:2]
    x0, y0 = int(W*ЗНАК_ДОЛИ[0]), int(H*ЗНАК_ДОЛИ[1])
    x1, y1 = int(W*ЗНАК_ДОЛИ[2]), int(H*ЗНАК_ДОЛИ[3])
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    уч = cv2.resize(картинка[y0:y1, x0:x1], (альфа.shape[1], альфа.shape[0]))
    уч = cv2.cvtColor(уч, cv2.COLOR_BGR2GRAY).astype(np.float32)
    знак, фон = альфа > 0.12, альфа < 0.02
    if знак.sum() < 8 or фон.sum() < 8:
        return None
    return float(уч[знак].mean() - уч[фон].mean())


def знак_по_клипам(папка: Path) -> list[tuple[float, str]]:
    import numpy as np
    альфа = _альфа_знака()
    вых = []
    for ф in файлы_клипов(папка):
        if ф.suffix.lower() in ВИДЕО:
            дл = длительность(ф) or 8.0
            зн = [оценка_знака(кадр(ф, дл*д), альфа) for д in ПРОБЫ]
        else:
            зн = [оценка_знака(прочитать_картинку(ф), альфа)]
        зн = [z for z in зн if z is not None]
        if зн:
            вых.append((max(зн), ф.name))
    вых.sort(reverse=True)
    return вых


def попадание(папка: Path, фильм: Path) -> list[tuple[int, int, str]]:
    """Ранг каждого кадра против своего промпта среди всех промптов ролика."""
    try:
        import torch
        from PIL import Image
        from transformers import CLIPModel, CLIPProcessor
    except ImportError:
        return []
    import cv2
    import numpy as np
    пром = промпты(папка)
    сц = [с for с in сцены_раскадровки(папка)
          if с["сцена"].isdigit() and int(с["сцена"]) in пром]
    if len(сц) < 4:
        return []
    у = "cuda" if torch.cuda.is_available() else "cpu"
    м = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(у).eval()
    пр = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

    def норм(v):
        v = v if torch.is_tensor(v) else v.pooler_output
        return v.float() / v.float().norm(dim=-1, keepdim=True)

    кадры, ном = [], []
    for с in сц:
        к = кадр(фильм, с["начало"] + (с["конец"] - с["начало"])/2)
        if к is None:
            continue
        кадры.append(Image.fromarray(cv2.cvtColor(к, cv2.COLOR_BGR2RGB)))
        ном.append(int(с["сцена"]))
    if len(кадры) < 4:
        return []
    В, Т = [], []
    for i in range(0, len(кадры), 32):
        with torch.no_grad():
            В.append(норм(м.get_image_features(
                **пр(images=кадры[i:i+32], return_tensors="pt").to(у))).cpu())
    for i in range(0, len(ном), 32):
        тек = [пром[н][:300] for н in ном[i:i+32]]
        with torch.no_grad():
            Т.append(норм(м.get_text_features(
                **пр(text=тек, return_tensors="pt", padding=True,
                     truncation=True).to(у))).cpu())
    М = (torch.cat(В) @ torch.cat(Т).T).numpy()
    вых = []
    for i, н in enumerate(ном):
        ранг = int((М[i] > М[i, i]).sum()) + 1
        вых.append((ранг, н, пром[н][:70]))
    вых.sort(reverse=True)
    return вых


def cmd_audit(args) -> None:
    _нужен_cv2()
    project = Project.load(args.dir)
    папка = Path(project.dir)
    фильм, звук = папка / "video.mp4", папка / "voice.mp3"
    if not это_выпуск(папка):
        print("это не папка выпуска:", папка, flush=True)
        print("  нет ни shotlist.csv, ни clips, ни video.mp4", flush=True)
        print("  какие папки знает автоматика — vidpipe channels", flush=True)
        raise SystemExit(2)
    print(f"=== аудит: {папка.name}", flush=True)

    # 1. сходимость
    if фильм.exists() and звук.exists():
        в, з = длительность(фильм), длительность(звук)
        знак = "" if abs(в - з) <= 0.35 else "  <- РАСХОЖДЕНИЕ"
        print("сходимость: видео %.2f с, озвучка %.2f с, разница %+.2f с%s"
              % (в, з, в - з, знак), flush=True)
    elif not фильм.exists():
        print("сходимость: video.mp4 ещё нет", flush=True)

    # 2. покрытие
    сц = сцены_раскадровки(папка)
    кл = файлы_клипов(папка)
    видео = sum(1 for x in кл if x.suffix.lower() in ВИДЕО)
    print("покрытие: сцен %d, файлов %d (%d видео, %d картинок)"
          % (len(сц), len(кл), видео, len(кл) - видео))

    # 3. знак
    зн = знак_по_клипам(папка)
    if зн:
        import numpy as np
        выше = [(о, н) for о, н in зн if о >= ЗНАК_ПОРОГ]
        print("знак генератора: медиана %.1f, максимум %.1f, выше порога %d"
              % (np.median([о for о, _ in зн]), зн[0][0], len(выше)))
        for о, н in выше[:8]:
            print("    %-52s %.0f" % (н[:52], о), flush=True)
        if выше:
            print("    порог грубый: яркий предмет в углу даёт ту же оценку,"
                  " эти кадры надо посмотреть глазами", flush=True)

    # 4. склейки
    if not args.fast:
        print("склейки: разбираю клипы...", flush=True)
        швы = []
        for ф in кл:
            if ф.suffix.lower() in ВИДЕО:
                р = склейка_внутри(ф)
                if р:
                    швы.append((ф.name, р))
        print("склейки внутри клипов: %d" % len(швы), flush=True)
        for н, р in швы[:8]:
            print("    %-52s на %s с" % (н[:52], ", ".join(str(x) for x in р[:4])))

    # 5. попадание кадра в текст
    if фильм.exists() and not args.fast:
        print("попадание: считаю по кадрам...", flush=True)
        п = попадание(папка, фильм)
        if п:
            первые = sum(1 for р, _, _ in п if р == 1)
            print("попадание кадра в свой промпт: на первом месте %d из %d,"
                  " худший ранг %d" % (первые, len(п), п[0][0]))
            for ранг, н, т in п[:6]:
                print("    сц %-3d ранг %2d | %s" % (н, ранг, т), flush=True)
            print("    близкие по смыслу сцены ранжируются низко сами по себе,"
                  " это не брак — смотреть только верх списка", flush=True)
        else:
            print("попадание кадра в текст: пропущено"
                  " (нет transformers/torch или мало сцен)", flush=True)
