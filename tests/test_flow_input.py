"""Шаг flow и чужая раскадровка: понятная ошибка вместо KeyError."""
from __future__ import annotations

import csv

import pytest

from vidpipe.config import Project
from vidpipe.steps import flow


def csv_файл(путь, колонки, строки):
    with open(путь, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=колонки)
        w.writeheader()
        for с in строки:
            w.writerow(с)


def test_чужие_колонки_объясняются_словами(tmp_path, global_dir, clean_env):
    """CSV из другого инструмента: раньше шаг падал KeyError посреди работы."""
    project = Project.load(tmp_path / "ролик")
    csv_файл(project.shotlist,
             ["scene", "start", "end", "duration", "beat", "camera"],
             [{"scene": "1", "start": "00:00:00", "end": "00:00:08",
               "duration": "8", "beat": "хук", "camera": "wide"}])

    with pytest.raises(SystemExit) as e:
        flow.run(project)

    текст = str(e.value)
    assert "нет колонок" in текст
    assert "visual" in текст          # какой именно не хватает
    assert "vidpipe run -s shotlist" in текст   # чем чинится


def test_пустой_shotlist_тоже_объясняется(tmp_path, global_dir, clean_env):
    project = Project.load(tmp_path / "ролик")
    csv_файл(project.shotlist, ["scene", "duration", "visual"], [])

    with pytest.raises(SystemExit, match="пуст"):
        flow.run(project)


def test_без_shotlist_шаг_не_начинается(tmp_path, global_dir, clean_env):
    project = Project.load(tmp_path / "ролик")

    with pytest.raises(SystemExit, match="сначала шаг shotlist"):
        flow.run(project)


def test_камера_из_чужого_csv_доходит_до_модели(tmp_path, global_dir, clean_env,
                                                monkeypatch):
    """В раскадровке другого инструмента крупность и движение — одна колонка."""
    project = Project.load(tmp_path / "ролик")
    csv_файл(project.shotlist,
             ["scene", "start", "end", "duration", "beat", "visual", "camera"],
             [{"scene": "1", "start": "00:00:00", "end": "00:00:08",
               "duration": "8", "beat": "хук", "visual": "тёмный коридор",
               "camera": "Wide, slow push-in"}])

    увиденное = {}

    def подмена(system, user, max_tokens=8000, model=None):
        увиденное["payload"] = user
        return [{"scene": 1, "prompt": "a dim corridor", "camera": "wide"}]

    monkeypatch.setattr(flow, "complete_json", подмена)
    flow.run(project)

    assert "Wide, slow push-in" in увиденное["payload"]
    assert "тёмный коридор" in увиденное["payload"]
