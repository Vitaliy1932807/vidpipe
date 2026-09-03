"""Работа с кадрами готового ролика и с клипами: чтение, пробы, склейки.

Общая часть для проверки и для правки. Всё, что связано с вытаскиванием
кадров через ffmpeg и с разбором раскадровки, живёт здесь, чтобы audit.py и
marks.py не повторяли одно и то же.
"""
from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

from .config import ffmpeg_bin, read_text

ВИДЕО = {".mp4", ".mov", ".webm", ".mkv"}
КАРТИНКИ = {".png", ".jpg", ".jpeg", ".webp"}


def _нужен_cv2():
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "нужны opencv-python и numpy: pip install opencv-python numpy"
        ) from e


def ffprobe_bin() -> str:
    b = ffmpeg_bin()
    return b[:-6] + "ffprobe" if b.endswith("ffmpeg") else "ffprobe"


def длительность(путь: Path) -> float:
    о = subprocess.run([ffprobe_bin(), "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", str(путь)],
                       capture_output=True, text=True).stdout.strip()
    try:
        return float(о)
    except ValueError:
        return 0.0


def секунды(t: str) -> float:
    """Разбирает и Ч:М:С, и М:С — в старых выпусках время писалось коротко."""
    ч = [float(z) for z in t.replace(",", ".").split(":")]
    while len(ч) < 3:
        ч.insert(0, 0.0)
    return ч[0]*3600 + ч[1]*60 + ч[2]


def кадр(путь: Path, t: float):
    """Один кадр в момент t. None, если ffmpeg ничего не отдал."""
    import cv2
    import numpy as np
    из = subprocess.run([ffmpeg_bin(), "-v", "error", "-ss", "%.3f" % t,
                         "-i", str(путь), "-frames:v", "1",
                         "-f", "image2pipe", "-vcodec", "png", "-"],
                        capture_output=True).stdout
    if not из:
        return None
    return cv2.imdecode(np.frombuffer(из, np.uint8), cv2.IMREAD_COLOR)


def прочитать_картинку(путь: Path):
    """imread не умеет кириллицу в пути, поэтому через буфер."""
    import cv2
    import numpy as np
    return cv2.imdecode(np.fromfile(str(путь), np.uint8), cv2.IMREAD_COLOR)


def сцены_раскадровки(папка: Path) -> list[dict]:
    ф = папка / "shotlist.csv"
    if not ф.exists():
        return []
    строки = list(csv.DictReader(read_text(ф).splitlines()))
    вых = []
    for x in строки:
        if not x.get("start") or not x.get("end"):
            continue
        вых.append({
            "сцена": str(x.get("scene") or x.get("id") or "?"),
            "начало": секунды(x["start"]),
            "конец": секунды(x["end"]),
            "текст": (x.get("visual") or x.get("narration") or "").strip(),
        })
    return вых


def промпты(папка: Path) -> dict[int, str]:
    """Промпты сцен: из flow_prompts.json, иначе из столбца visual."""
    ф = папка / "flow_prompts.json"
    if ф.exists():
        try:
            д = json.loads(read_text(ф))
            return {с["scene"]: с.get("prompt", "") for с in д.get("scenes", [])}
        except (ValueError, KeyError, TypeError):
            pass
    вых = {}
    for с in сцены_раскадровки(папка):
        if с["сцена"].isdigit() and с["текст"]:
            вых[int(с["сцена"])] = с["текст"]
    return вых


def файлы_клипов(папка: Path) -> list[Path]:
    кл = папка / "clips"
    if not кл.exists():
        return []
    служебные = {"_original", "_варианты", "_до правки", "_посторонние"}
    вых = []
    for x in sorted(кл.rglob("*")):
        if not x.is_file() or x.suffix.lower() not in ВИДЕО | КАРТИНКИ:
            continue
        if any(ч in служебные for ч in x.relative_to(кл).parts[:-1]):
            continue
        вых.append(x)
    return вых


def склейка_внутри(путь: Path, во_сколько_раз: float = 3.5,
                   минимум: float = 12.0, шаг: float = 0.2) -> list[float]:
    """Моменты, где внутри одного клипа кадр меняется рывком.

    Генератор иногда отдаёт под одним именем два разных плана. В собранном
    ролике это выглядит как чужая сцена посреди своей, и по логам сборки не
    видно ничего.

    Абсолютный порог здесь не работает: быстрое движение — вход предмета в
    кадр, проезд камеры — даёт ту же разницу, что и монтажный стык. Разница
    в форме: у стыка это одиночный скачок на спокойном фоне, у движения
    уровень ровно высокий. Поэтому кадр помечается, только если он выше
    своего окружения во_сколько_раз.
    """
    import cv2
    import numpy as np
    дл = длительность(путь)
    if дл <= 0:
        return []
    пред, разницы, времена, t = None, [], [], 0.0
    while t < дл:
        к = кадр(путь, t)
        if к is None:
            break
        м = cv2.resize(cv2.cvtColor(к, cv2.COLOR_BGR2GRAY), (96, 54)).astype(np.float32)
        if пред is not None:
            разницы.append(float(np.abs(м - пред).mean()))
            времена.append(round(t, 2))
        пред = м
        t += шаг
    if len(разницы) < 6:
        return []
    р = np.array(разницы)
    вых = []
    for i, з in enumerate(р):
        if з < минимум:
            continue
        a, b = max(0, i-4), min(len(р), i+5)
        соседи = np.concatenate([р[a:i], р[i+1:b]])
        if len(соседи) and з > max(минимум, float(np.median(соседи))*во_сколько_раз):
            вых.append(времена[i])
    return вых

def это_выпуск(папка: Path) -> bool:
    """Похожа ли папка на выпуск.

    Команда, запущенная не там, раньше буднично печатала «сцен 0, файлов 0»
    — и это читалось как «всё в порядке». Молчать здесь нельзя.
    """
    return any((папка / имя).exists() for имя in
               ("shotlist.csv", "flow_prompts.json", "prompt.md", "script.md",
                "video.mp4", "clips"))
