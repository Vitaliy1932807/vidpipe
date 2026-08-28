"""Шаг 5: subtitles.srt + script.md -> shotlist.csv

Сцены нарезаются по сетке в 8 секунд — родная длина клипа Veo/Flow, поэтому
раскадровка сразу ложится на генерацию без пересчёта. Текст диктора берётся
из .srt, то есть тайминги реальные, а не расчётные по числу слов.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass

from ..config import env_int, read_text
from ..llm import complete_json

CUE_RE = re.compile(
    r"(\d+)\s*\n(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*\n(.*?)(?=\n\s*\n|\Z)",
    re.S,
)


@dataclass
class Cue:
    start: float
    end: float
    text: str


def _parse_ts(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = re.split(r"[,.]", rest)
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_srt(raw: str) -> list[Cue]:
    cues = []
    for _, start, end, text in CUE_RE.findall(raw):
        clean = " ".join(line.strip() for line in text.strip().splitlines())
        if clean:
            cues.append(Cue(_parse_ts(start), _parse_ts(end), clean))
    if not cues:
        raise SystemExit("[shotlist] не разобрал ни одной реплики из .srt")
    return cues


def build_grid(cues: list[Cue], scene_sec: int) -> list[dict]:
    """Раскладываем реплики по сетке сцен: реплика уходит в ту сцену,
    с которой у неё наибольшее перекрытие по времени."""
    total = cues[-1].end
    n = max(1, int(-(-total // scene_sec)))
    scenes = [{"scene": i + 1, "start": i * scene_sec,
               "end": min((i + 1) * scene_sec, total), "parts": []}
              for i in range(n)]

    for cue in cues:
        best, best_overlap = None, 0.0
        for sc in scenes:
            overlap = min(cue.end, sc["end"]) - max(cue.start, sc["start"])
            if overlap > best_overlap:
                best, best_overlap = sc, overlap
        (best or scenes[-1])["parts"].append(cue.text)

    for sc in scenes:
        sc["narration"] = " ".join(sc.pop("parts")).strip()

    # короткий хвост (меньше половины сцены) склеиваем с предыдущей —
    # иначе Flow получит огрызок на пару секунд
    if len(scenes) > 1 and scenes[-1]["end"] - scenes[-1]["start"] < scene_sec / 2:
        tail = scenes.pop()
        scenes[-1]["end"] = tail["end"]
        scenes[-1]["narration"] = f"{scenes[-1]['narration']} {tail['narration']}".strip()

    return scenes


SYSTEM = """Ты — режиссёр раскадровки документального YouTube-ролика.
На вход получаешь сцены с реальными таймингами и текстом диктора.
Для каждой сцены придумай визуал, который иллюстрирует именно этот кусок
закадрового текста.

Правила:
- Визуал описывай конкретно: что в кадре, где, в какое время суток, что происходит.
- Никакого текста, титров, надписей и логотипов в кадре.
- Никаких узнаваемых реальных людей по именам — описывай через роль и внешность.
- Соседние сцены не должны повторять друг друга: меняй крупность и точку съёмки.
- Если диктор говорит абстракцию — придумай предметный образ, а не иллюстрацию понятия.

Верни JSON-массив, по объекту на каждую сцену, строго в порядке номеров:
[{"scene": 1, "visual": "...", "shot_type": "...", "motion": "...", "mood": "..."}]

shot_type: extreme wide | wide | medium | close-up | macro | aerial | POV | over-the-shoulder
motion: static | slow push-in | slow pull-out | pan left | pan right | tilt up | tilt down | tracking | orbit
mood: 2-4 слова о свете и атмосфере."""


def annotate(scenes: list[dict], batch: int) -> None:
    for i in range(0, len(scenes), batch):
        chunk = scenes[i:i + batch]
        print(f"[shotlist] сцены {chunk[0]['scene']}–{chunk[-1]['scene']}")
        payload = "\n\n".join(
            f"Сцена {s['scene']} ({_fmt(s['start'])}–{_fmt(s['end'])}):\n"
            f"{s['narration'] or '(пауза, диктор молчит)'}"
            for s in chunk
        )
        prev = scenes[i - 1].get("visual") if i else None
        tail = f"\n\nПредыдущая сцена показывала: {prev}\nНе повторяй её." if prev else ""
        result = complete_json(SYSTEM, payload + tail, max_tokens=8000)

        by_id = {int(r["scene"]): r for r in result if "scene" in r}
        for s in chunk:
            r = by_id.get(s["scene"], {})
            s["visual"] = r.get("visual", "")
            s["shot_type"] = r.get("shot_type", "medium")
            s["motion"] = r.get("motion", "static")
            s["mood"] = r.get("mood", "")
            if not s["visual"]:
                print(f"[shotlist]   ! сцена {s['scene']} без визуала")


def run(project, force: bool = False) -> None:
    if not project.srt.exists():
        raise SystemExit(f"[shotlist] нет {project.srt} — сначала шаг srt")
    if project.shotlist.exists() and not force:
        print(f"[shotlist] пропуск, {project.shotlist.name} уже есть")
        return

    scene_sec = env_int("SCENE_SEC", 8)
    cues = parse_srt(read_text(project.srt))
    scenes = build_grid(cues, scene_sec)
    print(f"[shotlist] {len(cues)} реплик -> {len(scenes)} сцен по {scene_sec} с, "
          f"хронометраж {_fmt(scenes[-1]['end'])}")

    from ..llm import без_модели
    if без_модели():
        # Сетка сцен это чистый расчёт по таймингам субтитров, она уже готова.
        # Описание кадра это решение, и его пишет человек.
        for s in scenes:
            s["visual"] = ""
            s["shot_type"] = ""
            s["motion"] = ""
            s["mood"] = ""
        print("[shotlist] модель не настроена: сетка сцен посчитана, "
              "колонку visual заполни сам")
    else:
        annotate(scenes, env_int("SHOTLIST_BATCH", 15))

    with project.shotlist.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["scene", "start", "end", "duration",
                                          "narration", "visual", "shot_type",
                                          "motion", "mood"])
        w.writeheader()
        for s in scenes:
            w.writerow({
                "scene": s["scene"],
                "start": _fmt(s["start"]),
                "end": _fmt(s["end"]),
                "duration": round(s["end"] - s["start"], 1),
                "narration": s["narration"],
                "visual": s["visual"],
                "shot_type": s["shot_type"],
                "motion": s["motion"],
                "mood": s["mood"],
            })
    print(f"[shotlist] {project.shotlist.name}: {len(scenes)} сцен")
