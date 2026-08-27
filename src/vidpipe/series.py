"""Память серии.

Методика на одинаковом входе даёт одинаковый выход: модель каждый раз берёт
самый вероятный ход. Поэтому список уже использованных приёмов ведётся вне
модели и подаётся ей как запрет.

Хранится в JSONL на уровне канала, рядом с папками его роликов — по строке
на выпуск. Каждый канал ведёт свой журнал.
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import env, env_int, read_text
from .llm import complete_json

AXES = {
    "profession": "профессия или роль рассказчика",
    "setting": "место действия",
    "time_frame": "время суток и сезон",
    "phenomenon": "как проявляется необъяснимое",
    "trigger": "что герой сделал не так",
    "ending_device": "как финал уходит от называния",
    "anchor": "ради кого или чего герой рискует",
}

EXTRACT = """Тебе дают сценарий. Опиши его приёмы коротко, по-русски,
двумя-четырьмя словами на пункт. Не пересказывай сюжет, а называй приём.

Верни JSON ровно с этими ключами:
{"profession": "...", "setting": "...", "time_frame": "...",
 "phenomenon": "...", "trigger": "...", "ending_device": "...",
 "anchor": "..."}

Примеры значений: profession — "ночной сторож"; phenomenon — "голос зовёт
по имени"; ending_device — "старший отказался назвать"; trigger — "перешёл
границу после заката"; anchor — "долг перед матерью"."""


def series_path(project) -> Path:
    """Журнал канала: рядом с папкой `.vidpipe-channel`. Если канала нет —
    как раньше, на уровень выше папки ролика."""
    custom = env("SERIES_FILE")
    if custom:
        return Path(custom).expanduser()
    root = project.channel_root or project.dir.parent
    return root / "series.jsonl"


def load(project, limit: int) -> list[dict]:
    path = series_path(project)
    if not path.exists():
        return []
    entries = []
    for line in read_text(path).splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries[-limit:] if limit else entries


def constraints(project) -> str:
    """Блок запретов для промпта генерации сценария."""
    depth = env_int("SERIES_DEPTH", 5)
    entries = [e for e in load(project, depth) if e.get("episode") != project.name]
    if not entries:
        return ""

    lines = ["ПРЕДЫДУЩИЕ ВЫПУСКИ ЭТОГО КАНАЛА (не повторять их приёмы):\n"]
    for e in entries:
        used = ", ".join(f"{AXES[k]}: {e[k]}" for k in AXES if e.get(k))
        lines.append(f"- «{e.get('episode', '?')}» — {used}")

    lines.append(
        "\nОбязательно: возьми другую профессию, другой тип места, другой способ "
        "проявления необъяснимого и другой финальный приём. Совпадение хотя бы "
        "по двум пунктам с любым выпуском выше считается браком. "
        "Совпадать могут только эпоха, регион и общий тон — это единство серии."
    )
    return "\n".join(lines) + "\n\n"


def record(project, text: str) -> None:
    """Разбираем готовый сценарий на приёмы и дописываем в журнал серии."""
    try:
        data = complete_json(EXTRACT, text[:12000], max_tokens=1000)
    except SystemExit as e:
        print(f"[series] не удалось разобрать приёмы: {e}")
        return

    entry = {"episode": project.name}
    entry.update({k: data.get(k, "") for k in AXES})

    path = series_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)

    # переписываем строку этого же ролика, если он генерируется повторно
    kept = [line for line in (read_text(path).splitlines()
                              if path.exists() else [])
            if line.strip() and json.loads(line).get("episode") != project.name]
    kept.append(json.dumps(entry, ensure_ascii=False))
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    print(f"[series] записано в {path.name}: "
          f"{entry.get('profession', '')} / {entry.get('phenomenon', '')}")


def cmd_series(args) -> None:
    from .config import Project
    project = Project.load(args.dir)
    path = series_path(project)
    entries = load(project, 0)
    if not entries:
        print(f"[series] журнал пуст: {path}")
        return

    print(f"{path} — выпусков: {len(entries)}\n")
    for e in entries:
        print(f"  {e.get('episode', '?')}")
        for k, label in AXES.items():
            if e.get(k):
                print(f"    {label:34} {e[k]}")
        print()

    # где серия начинает повторяться
    for k, label in AXES.items():
        vals = [e.get(k, "") for e in entries if e.get(k)]
        dupes = {v for v in vals if vals.count(v) > 1}
        if dupes:
            print(f"  ! повтор по оси «{label}»: {', '.join(dupes)}")
