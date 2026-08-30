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
    assert "WORDS_PER_MIN" in text          # подсказка есть, пусть и закомментированной
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


# --- .env канала не должен перекрывать глобальный конфиг ---------------------

def test_в_env_канала_нет_пустых_присваиваний():
    """`KEY=` в канале не наследует глобальное значение, а затирает его."""
    пустые = []
    for line in cli.channel_env("проба").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if not value.strip():
            пустые.append(key)

    assert not пустые, "пустые присваивания затрут глобальные: " + ", ".join(пустые)


def test_создание_канала_не_меняет_настройки(tmp_path, global_dir, clean_env,
                                             monkeypatch):
    """Канал заводят на пустом месте — до правки его .env всё как было.

    Раньше сюда копировался весь env.example, и создание канала стирало
    VOICER_API_KEY, сбрасывало FW_DEVICE с cuda на cpu и меняло VIDEO_SIZE.
    """
    (global_dir / ".env").write_text("""VOICER_API_KEY=ключ
VOICER_VOICE_ID=ACRfKVNOAnzVitkYerdl
VOICER_SPEED=0.9
FW_DEVICE=cuda
FW_COMPUTE_TYPE=float16
VIDEO_SIZE=1280x720
WHISPER_LANG=hi
WORDS_PER_MIN=147
""", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cli.make_channel("проба")
    video = tmp_path / "выпуск"
    video.mkdir()
    monkeypatch.chdir(video)

    from vidpipe.config import env, load_env
    load_env(video)

    было = {"VOICER_API_KEY": "ключ", "VOICER_VOICE_ID": "ACRfKVNOAnzVitkYerdl",
            "VOICER_SPEED": "0.9", "FW_DEVICE": "cuda",
            "FW_COMPUTE_TYPE": "float16", "VIDEO_SIZE": "1280x720",
            "WHISPER_LANG": "hi", "WORDS_PER_MIN": "147"}
    стало = {k: env(k) for k in было}

    assert стало == было


def test_после_правки_env_канала_настройка_применяется(tmp_path, global_dir,
                                                       clean_env, monkeypatch):
    """Обратная сторона: раскомментировал строку — канал её подставляет."""
    (global_dir / ".env").write_text("WORDS_PER_MIN=147\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cli.make_channel("ru")
    env_file = tmp_path / config.CHANNEL_MARKER / ".env"
    # раскомментировать строку, не цепляясь за само число в подсказке:
    # оно менялось вместе с замерами и ломало тест на ровном месте
    import re
    env_file.write_text(
        re.sub(r"#\s*WORDS_PER_MIN=\d+", "WORDS_PER_MIN=150",
               env_file.read_text(encoding="utf-8-sig")),
        encoding="utf-8")
    video = tmp_path / "выпуск"
    video.mkdir()

    from vidpipe.config import env, load_env
    load_env(video)

    assert env("WORDS_PER_MIN") == "150"


def test_папка_под_кадры_заводится_сразу(tmp_path, global_dir, clean_env, capsys):
    """Каждый выпуск начинался с одного и того же: assemble падал на «нет clips».

    Пустая папка ничего не стоит, а её отсутствие стоит оборванного прогона.
    """
    import argparse
    from vidpipe import cli

    make_channel_dir(tmp_path / "канал", CHANNEL_NAME="kb")
    d = tmp_path / "канал" / "выпуск"

    cli.cmd_init(argparse.Namespace(dir=str(d), topic="тема", force=False,
                                    style=False, channel=None, global_config=False))

    assert (d / "clips").is_dir()
    assert "clips" in capsys.readouterr().out


def test_существующая_папка_кадров_не_трогается(tmp_path, global_dir, clean_env):
    """Повторный init не должен ничего сносить: там уже могут лежать кадры."""
    import argparse
    from vidpipe import cli

    make_channel_dir(tmp_path / "канал", CHANNEL_NAME="kb")
    d = tmp_path / "канал" / "выпуск"
    (d / "clips").mkdir(parents=True)
    (d / "clips" / "001-кадр.mp4").write_bytes(b"0")

    cli.cmd_init(argparse.Namespace(dir=str(d), topic="тема", force=False,
                                    style=False, channel=None, global_config=False))

    assert (d / "clips" / "001-кадр.mp4").exists()
