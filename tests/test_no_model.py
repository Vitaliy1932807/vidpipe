"""Конвейер без модели: механика считается, решения остаются человеку."""
from __future__ import annotations

import csv
import json
import os

import pytest

from vidpipe import checks, llm
from vidpipe.config import Project
from vidpipe.steps import flow, shotlist

from conftest import make_channel_dir

СУБТИТРЫ = """1
00:00:00,000 --> 00:00:04,000
Первая реплика диктора.

2
00:00:04,000 --> 00:00:09,000
Вторая реплика диктора.

3
00:00:09,000 --> 00:00:14,000
Третья реплика диктора.
"""

АССЕТЫ = """[STYLE]
cinematic documentary

[ENV]
rural winter

[NEGATIVE]
no text
"""


def проект(tmp_path):
    marker = make_channel_dir(tmp_path / "канал", CHANNEL_NAME="kb")
    (marker / "assets.md").write_text(АССЕТЫ, encoding="utf-8")
    d = tmp_path / "канал" / "выпуск"
    d.mkdir()
    return Project.load(d)


def test_режим_без_модели_распознаётся(clean_env):
    os.environ["LLM_PROVIDER"] = "none"

    assert llm.без_модели()
    assert "не настроена" in llm.readiness()


def test_думающий_шаг_не_притворяется_что_работает(clean_env):
    """Ошибка сети сбивала бы с толку: дело не в связи, а в том, что модели нет."""
    os.environ["LLM_PROVIDER"] = "none"

    with pytest.raises(SystemExit, match="модель не настроена"):
        llm.complete("система", "запрос")


def test_раскадровка_считается_без_модели(tmp_path, global_dir, clean_env, capsys):
    """Сетка сцен это тайминги, а не творчество: она должна получаться всегда."""
    os.environ["LLM_PROVIDER"] = "none"
    p = проект(tmp_path)
    p.srt.write_text(СУБТИТРЫ, encoding="utf-8")

    shotlist.run(p)

    строки = list(csv.DictReader(p.shotlist.read_text(encoding="utf-8-sig").splitlines()))
    assert len(строки) >= 2
    assert строки[0]["start"] and строки[0]["duration"]
    assert строки[0]["narration"].strip()          # реплика на месте
    assert строки[0]["visual"] == ""               # описание кадра за человеком
    assert "заполни" in capsys.readouterr().out


def test_заготовка_промптов_без_модели(tmp_path, global_dir, clean_env):
    os.environ["LLM_PROVIDER"] = "none"
    p = проект(tmp_path)
    p.srt.write_text(СУБТИТРЫ, encoding="utf-8")
    shotlist.run(p)

    flow.run(p)
    данные = json.loads(p.flow.read_text(encoding="utf-8-sig"))

    assert данные["skeleton"] is True
    assert данные["global"]["style"].startswith("cinematic")   # стиль подставлен
    assert len(данные["scenes"]) == len(
        list(csv.DictReader(p.shotlist.read_text(encoding="utf-8-sig").splitlines())))
    assert all(с["prompt"] == "" for с in данные["scenes"])
    assert (p.dir / "flow_prompts.md").exists()


def test_пустая_заготовка_не_останавливает_конвейер(tmp_path, global_dir, clean_env):
    """Заготовка пустой и задумана: ругаться на замысел нельзя."""
    os.environ["LLM_PROVIDER"] = "none"
    p = проект(tmp_path)
    p.srt.write_text(СУБТИТРЫ, encoding="utf-8")
    shotlist.run(p)
    flow.run(p)

    находки = checks.check_flow(p)

    assert not [i for i in находки if i.level == "stop"], [i.what for i in находки]
    assert any("без промпта" in i.what and i.level == "warn" for i in находки)


def test_заполненная_заготовка_проходит_приёмку(tmp_path, global_dir, clean_env):
    os.environ["LLM_PROVIDER"] = "none"
    p = проект(tmp_path)
    p.srt.write_text(СУБТИТРЫ, encoding="utf-8")
    shotlist.run(p)
    flow.run(p)

    данные = json.loads(p.flow.read_text(encoding="utf-8-sig"))
    for с in данные["scenes"]:
        с["prompt"] = "an empty snowy road disappearing into fog"
    p.flow.write_text(json.dumps(данные, ensure_ascii=False), encoding="utf-8")

    assert not [i for i in checks.check_flow(p) if i.level == "stop"]
