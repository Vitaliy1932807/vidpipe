"""Журнал серии на уровне канала и команда `vidpipe init --channel`."""
from __future__ import annotations

import os

from vidpipe import cli, config
from vidpipe.config import Project
from vidpipe.series import series_path

from conftest import make_channel_dir


def test_журнал_лежит_рядом_с_маркером_канала(tmp_path, clean_env):
    make_channel_dir(tmp_path / "hindi")
    video = tmp_path / "hindi" / "выпуск-01"
    video.mkdir()

    assert series_path(Project.load(video)) == tmp_path / "hindi" / "series.jsonl"


def test_журнал_канала_а_не_соседняя_папка(tmp_path, clean_env):
    """Ролик лежит глубже корня канала — журнал всё равно один, в корне.

    Именно здесь «на уровень выше папки ролика» и «рядом с .vidpipe-channel»
    расходятся; без этого случая регрессия в series_path пройдёт незаметно.
    """
    make_channel_dir(tmp_path / "hindi")
    video = tmp_path / "hindi" / "2026" / "выпуск-01"
    video.mkdir(parents=True)

    assert series_path(Project.load(video)) == tmp_path / "hindi" / "series.jsonl"


def test_без_канала_журнал_на_уровень_выше(tmp_path, clean_env):
    """Как было до каналов — существующие серии не должны потеряться."""
    video = tmp_path / "старые-ролики" / "ролик"

    assert series_path(Project.load(video)) == tmp_path / "старые-ролики" / "series.jsonl"


def test_у_двух_каналов_разные_журналы(tmp_path, clean_env):
    for name in ("hindi", "ru"):
        make_channel_dir(tmp_path / name)
        (tmp_path / name / "выпуск").mkdir()

    first = series_path(Project.load(tmp_path / "hindi" / "выпуск"))
    second = series_path(Project.load(tmp_path / "ru" / "выпуск"))

    assert first != second


def test_series_file_перекрывает_канал(tmp_path, clean_env):
    make_channel_dir(tmp_path / "hindi")
    video = tmp_path / "hindi" / "выпуск"
    video.mkdir()
    os.environ["SERIES_FILE"] = str(tmp_path / "свой.jsonl")

    assert series_path(Project.load(video)) == tmp_path / "свой.jsonl"


def test_init_channel_создаёт_канал(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    cli.make_channel("hindi-horror")

    marker = tmp_path / config.CHANNEL_MARKER
    assert (marker / ".env").exists()
    assert (marker / "script_engine.md").exists()
    assert (marker / "assets.md").exists()
    # журнал серии — рядом с маркером, а не внутри него
    assert (tmp_path / "series.jsonl").exists()

    text = (marker / ".env").read_text(encoding="utf-8-sig")
    assert "CHANNEL_NAME=hindi-horror" in text
    assert "WORDS_PER_MIN" in text          # шаблон целиком, а не одна строка
    assert "hindi-horror" in capsys.readouterr().out


def test_повторный_init_channel_не_затирает_правки(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cli.make_channel("hindi-horror")
    env_file = tmp_path / config.CHANNEL_MARKER / ".env"
    env_file.write_text("CHANNEL_NAME=hindi-horror\nWORDS_PER_MIN=147\n",
                        encoding="utf-8")
    (tmp_path / "series.jsonl").write_text('{"episode": "выпуск-01"}\n',
                                           encoding="utf-8")

    cli.make_channel("hindi-horror")

    assert "WORDS_PER_MIN=147" in env_file.read_text(encoding="utf-8-sig")
    assert "выпуск-01" in (tmp_path / "series.jsonl").read_text(encoding="utf-8")


def test_force_перезаписывает_env_канала(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cli.make_channel("hindi-horror")
    env_file = tmp_path / config.CHANNEL_MARKER / ".env"
    env_file.write_text("сломано", encoding="utf-8")

    cli.make_channel("hindi-horror", force=True)

    assert "CHANNEL_NAME=hindi-horror" in env_file.read_text(encoding="utf-8-sig")


def test_созданный_канал_находится_роликом(tmp_path, monkeypatch, clean_env):
    """Сквозная проверка: init --channel -> ролик видит канал и его ресурсы."""
    monkeypatch.chdir(tmp_path)
    cli.make_channel("hindi-horror")
    video = tmp_path / "выпуск-01"
    video.mkdir()

    project = Project.load(video)

    assert project.channel == tmp_path / config.CHANNEL_MARKER
    assert project.resource_source("script_engine.md") == "канал"
    assert series_path(project) == tmp_path / "series.jsonl"
