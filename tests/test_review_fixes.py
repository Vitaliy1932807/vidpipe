"""Находки ревью многоканальности — по тесту на каждую.

Все пять случаев воспроизводились руками на живом CLI и падали до починки.
"""
from __future__ import annotations

import argparse
import os

from vidpipe import cli, config
from vidpipe.config import Project, load_env

from conftest import make_channel_dir


def write_env(path, **values):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- 1. .env посторонней папки не должен перекрывать канал -------------------

def test_env_ролика_главнее_env_текущей_папки(tmp_path, global_dir, clean_env,
                                              monkeypatch):
    """`--dir` из посторонней папки: побеждает .env самого ролика.

    Иначе .env папки, из которой запущена команда, молча переопределял бы
    настройки чужого канала — язык и темп речи уехали бы не туда.
    """
    write_env(global_dir / ".env", WORDS_PER_MIN="150")
    make_channel_dir(tmp_path / "hindi", WORDS_PER_MIN="147")
    video = tmp_path / "hindi" / "выпуск"
    video.mkdir(parents=True)
    write_env(video / ".env", WORDS_PER_MIN="999")

    посторонняя = tmp_path / "посторонняя"
    посторонняя.mkdir()
    write_env(посторонняя / ".env", WORDS_PER_MIN="111")
    monkeypatch.chdir(посторонняя)

    load_env(video)

    assert config.env("WORDS_PER_MIN") == "999"


def test_env_посторонней_папки_не_перекрывает_канал(tmp_path, global_dir,
                                                    clean_env, monkeypatch):
    """У ролика своего .env нет — тогда решает канал, а не чужая папка."""
    write_env(global_dir / ".env", WHISPER_LANG="ru")
    make_channel_dir(tmp_path / "hindi", WHISPER_LANG="hi")
    video = tmp_path / "hindi" / "выпуск"
    video.mkdir(parents=True)

    посторонняя = tmp_path / "посторонняя"
    посторонняя.mkdir()
    write_env(посторонняя / ".env", WHISPER_LANG="en")
    monkeypatch.chdir(посторонняя)

    load_env(video)

    assert config.env("WHISPER_LANG") == "hi"


def test_без_dir_работает_env_текущей_папки(tmp_path, global_dir, clean_env,
                                            monkeypatch):
    """Совместимость: голая команда в папке ролика читает её .env, как раньше."""
    write_env(global_dir / ".env", WORDS_PER_MIN="150")
    video = tmp_path / "ролик"
    video.mkdir()
    write_env(video / ".env", WORDS_PER_MIN="120")
    monkeypatch.chdir(video)

    load_env()

    assert config.env("WORDS_PER_MIN") == "120"


# --- 2. имя канала не наследуется с чужих уровней ----------------------------

def test_имя_канала_не_берётся_из_чужого_env(tmp_path, clean_env):
    """Канал сделан руками, без CHANNEL_NAME. Имя — от папки, не из окружения."""
    make_channel_dir(tmp_path / "канал-без-имени", WORDS_PER_MIN="140")
    video = tmp_path / "канал-без-имени" / "выпуск"
    video.mkdir()
    os.environ["CHANNEL_NAME"] = "совсем-другой-канал"

    assert Project.load(video).channel_name == "канал-без-имени"


def test_имя_канала_из_его_собственного_env(tmp_path, clean_env):
    make_channel_dir(tmp_path / "папка", CHANNEL_NAME="hindi-horror")
    video = tmp_path / "папка" / "выпуск"
    video.mkdir()
    os.environ["CHANNEL_NAME"] = "мимо"

    assert Project.load(video).channel_name == "hindi-horror"


def test_незаполненное_имя_канала_откатывается_к_папке(tmp_path, clean_env):
    """`CHANNEL_NAME=  # впиши имя` — это не имя."""
    marker = make_channel_dir(tmp_path / "папка")
    (marker / ".env").write_text("CHANNEL_NAME=   # впиши имя\n", encoding="utf-8")
    video = tmp_path / "папка" / "выпуск"
    video.mkdir()

    assert Project.load(video).channel_name == "папка"


# --- 3. init --channel уважает --dir ----------------------------------------

def test_init_channel_создаёт_канал_в_dir(tmp_path, monkeypatch, clean_env):
    откуда = tmp_path / "откуда"
    откуда.mkdir()
    monkeypatch.chdir(откуда)

    cli.make_channel("hindi", root=tmp_path / "цель")

    assert (tmp_path / "цель" / config.CHANNEL_MARKER / ".env").exists()
    assert (tmp_path / "цель" / "series.jsonl").exists()
    assert not (откуда / config.CHANNEL_MARKER).exists()


def test_cmd_init_прокидывает_dir_в_канал(tmp_path, monkeypatch, clean_env):
    """Проверяем именно склейку CLI: --channel вместе с --dir."""
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(global_config=False, channel="hindi",
                              dir=str(tmp_path / "цель"), force=False,
                              topic=None, style=False)

    cli.cmd_init(args)

    assert (tmp_path / "цель" / config.CHANNEL_MARKER).is_dir()
    assert not (tmp_path / config.CHANNEL_MARKER).exists()


# --- 4. предупреждение о канале внутри канала --------------------------------

def test_канал_внутри_канала_предупреждает(tmp_path, monkeypatch, capsys):
    make_channel_dir(tmp_path / "внешний")
    видео = tmp_path / "внешний" / "выпуск"
    видео.mkdir()
    monkeypatch.chdir(видео)

    cli.make_channel("вложенный")

    out = capsys.readouterr().out
    assert "ВНИМАНИЕ" in out
    assert str(tmp_path / "внешний") in out
    # канал всё же создаётся: запрещать не за что, ближний просто победит
    assert (видео / config.CHANNEL_MARKER).is_dir()


def test_повторный_init_того_же_канала_молчит(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cli.make_channel("hindi")
    capsys.readouterr()

    cli.make_channel("hindi")

    assert "ВНИМАНИЕ" not in capsys.readouterr().out


# --- 5. check не называет глобальные настройки настройками канала ------------

def check_output(video, monkeypatch, capsys, global_dir):
    monkeypatch.setattr(cli, "GLOBAL_DIR", global_dir)
    monkeypatch.chdir(video)
    load_env(video)
    cli.cmd_check(argparse.Namespace(dir=str(video)))
    return capsys.readouterr().out


def test_без_канала_заголовок_говорит_что_настройки_глобальные(
        tmp_path, global_dir, clean_env, monkeypatch, capsys):
    video = tmp_path / "ничей-ролик"
    video.mkdir()

    out = check_output(video, monkeypatch, capsys, global_dir)

    assert "канал         : не найден" in out
    assert "настройки (глобальные, канала нет):" in out
    assert "настройки канала:" not in out


def test_с_каналом_заголовок_прежний(tmp_path, global_dir, clean_env,
                                     monkeypatch, capsys):
    make_channel_dir(tmp_path / "hindi", CHANNEL_NAME="hindi-horror",
                     WHISPER_LANG="hi")
    video = tmp_path / "hindi" / "выпуск"
    video.mkdir()

    out = check_output(video, monkeypatch, capsys, global_dir)

    assert "настройки канала:" in out
    assert "hindi-horror" in out
    assert "hi" in out
