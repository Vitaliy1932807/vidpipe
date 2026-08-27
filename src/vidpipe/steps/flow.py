"""Шаг 6: shotlist.csv -> flow_prompts.json

Собирает финальные промпты для Flow/Veo. Блоки [STYLE]/[ENV]/[NEGATIVE] из
prompts/assets.md подставляются в каждый кадр — так стиль не плывёт по ролику.
"""
from __future__ import annotations

import csv
import json
import re

from ..config import env_int, read_text
from ..llm import complete_json

SYSTEM = """Ты собираешь промпты для генератора видео Veo/Flow по готовой раскадровке.

На каждую сцену верни один промпт на английском языке. Структура промпта:
субъект и действие -> окружение -> свет и атмосфера -> крупность и движение камеры.

Правила:
- Только английский, одно плотное предложение или два коротких.
- Описывай ОДНО непрерывное действие: клип длится 8 секунд, смены сцены внутри быть не может.
- Никаких имён реальных людей, брендов, надписей и текста в кадре.
- Не пиши в промпте слова о звуке, музыке и закадровом голосе.
- Стиль и негативы не дублируй: они добавляются отдельными блоками.

Верни JSON-массив строго в порядке номеров сцен:
[{"scene": 1, "prompt": "...", "camera": "...", "duration": 8}]

camera — короткая формула движения камеры на английском, например "static wide shot"
или "slow push-in, medium shot"."""


def load_assets(project) -> dict[str, str]:
    try:
        path = project.resource("assets.md")
    except SystemExit:
        return {}
    print(f"[flow] стиль: {path} ({project.resource_source('assets.md')})")
    raw = read_text(path)
    blocks = {}
    for m in re.finditer(r"^\[([A-Z]+)\]\s*\n(.*?)(?=^\[[A-Z]+\]|\Z)", raw, re.S | re.M):
        blocks[m.group(1)] = " ".join(m.group(2).split())
    return blocks


def run(project, force: bool = False) -> None:
    if not project.shotlist.exists():
        raise SystemExit(f"[flow] нет {project.shotlist} — сначала шаг shotlist")
    if project.flow.exists() and not force:
        print(f"[flow] пропуск, {project.flow.name} уже есть")
        return

    with project.shotlist.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("[flow] shotlist.csv пуст")

    assets = load_assets(project)
    print(f"[flow] {len(rows)} сцен, блоки ассетов: {', '.join(assets) or 'нет'}")

    prompts: dict[int, dict] = {}
    batch = env_int("FLOW_BATCH", 15)
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        print(f"[flow] сцены {chunk[0]['scene']}–{chunk[-1]['scene']}")
        payload = "\n\n".join(
            f"Сцена {r['scene']} ({r['duration']} с):\n"
            f"Визуал: {r['visual']}\n"
            f"Крупность: {r['shot_type']} | Движение: {r['motion']} | "
            f"Атмосфера: {r['mood']}"
            for r in chunk
        )
        for r in complete_json(SYSTEM, payload, max_tokens=8000):
            if "scene" in r:
                prompts[int(r["scene"])] = r

    out = []
    missing = []
    for r in rows:
        n = int(r["scene"])
        gen = prompts.get(n)
        if not gen:
            missing.append(n)
            continue
        out.append({
            "scene": n,
            "start": r["start"],
            "end": r["end"],
            "duration": float(r["duration"]),
            "narration": r["narration"],
            "prompt": gen.get("prompt", ""),
            "camera": gen.get("camera", r["motion"]),
            "style": assets.get("STYLE", ""),
            "environment": assets.get("ENV", ""),
            "negative": assets.get("NEGATIVE", ""),
        })

    if missing:
        print(f"[flow] ! без промпта остались сцены: {missing}")

    project.flow.write_text(
        json.dumps({"project": project.name, "scene_count": len(out), "scenes": out},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[flow] {project.flow.name}: {len(out)} промптов")
