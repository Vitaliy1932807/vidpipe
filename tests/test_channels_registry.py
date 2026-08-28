"""Каналы по языкам: автоматизация находит их сама, список нигде не дублируется."""
from __future__ import annotations

import argparse
import os

from vidpipe import cli
from vidpipe.config import find_channels

from conftest import make_channel_dir


def завести(корень, имя, **настройки):
    make_channel_dir(корень, CHANNEL_NAME=имя, **настройки)
    return корень


def test_каналы_находятся_под_общим_корнем(tmp_path, clean_env):
    завести(tmp_path / "Новая История", "hindi", WHISPER_LANG="hi")
    завести(tmp_path / "Русский канал", "ru", WHISPER_LANG="ru")
    завести(tmp_path / "English channel", "en", WHISPER_LANG="en")

    каналы = find_channels(str(tmp_path))

    assert set(каналы) == {"hindi", "ru", "en"}
    assert каналы["en"].name == "English channel"


def test_новый_язык_появляется_без_правки_кода(tmp_path, clean_env):
    """Ради этого всё и делалось: добавить язык — значит завести канал."""
    завести(tmp_path / "ru-канал", "ru")
    assert set(find_channels(str(tmp_path))) == {"ru"}

    завести(tmp_path / "de-канал", "de")

    assert set(find_channels(str(tmp_path))) == {"ru", "de"}


def test_имя_канала_из_его_env_а_не_из_папки(tmp_path, clean_env):
    завести(tmp_path / "папка-с-невнятным-именем", "en")

    assert "en" in find_channels(str(tmp_path))


def test_несколько_корней_через_точку_с_запятой(tmp_path, clean_env):
    первый, второй = tmp_path / "диск1", tmp_path / "диск2"
    завести(первый / "ru-канал", "ru")
    завести(второй / "en-канал", "en")

    каналы = find_channels(f"{первый};{второй}")

    assert set(каналы) == {"ru", "en"}


def test_корень_сам_может_быть_каналом(tmp_path, clean_env):
    завести(tmp_path, "один")

    assert "один" in find_channels(str(tmp_path))


def test_несуществующий_корень_не_ломает_поиск(tmp_path, clean_env):
    завести(tmp_path / "ru-канал", "ru")

    каналы = find_channels(f"{tmp_path};{tmp_path / 'нет-такой-папки'}")

    assert set(каналы) == {"ru"}


def test_без_корней_список_пуст(clean_env):
    assert find_channels("") == {}


# --- языковые пресеты --------------------------------------------------------

def test_пресет_подставляет_настройки_языка():
    текст = cli.channel_env("en", "en")

    assert "DEFAULT_LANG=English" in текст
    assert "WORDS_PER_MIN=140" in текст
    assert "WHISPER_LANG=en" in текст
    assert "FW_MODEL_SIZE=medium" in текст


def test_у_хинди_своя_модель_распознавания():
    """На хинди medium разваливается — нужен large-v3."""
    assert "FW_MODEL_SIZE=large-v3" in cli.channel_env("hindi", "hi")
    assert "WORDS_PER_MIN=147" in cli.channel_env("hindi", "hi")


def test_без_языка_настройки_остаются_закомментированными():
    """Канал без пресета не должен молча менять поведение."""
    текст = cli.channel_env("новый")

    for строка in текст.splitlines():
        if строка.startswith(("DEFAULT_LANG", "WORDS_PER_MIN", "WHISPER_LANG",
                              "FW_MODEL_SIZE")):
            raise AssertionError(f"настройка не закомментирована: {строка}")


def test_у_всех_языков_один_набор_ключей():
    """Добавляя язык, легко забыть строку — тогда канал молча возьмёт чужую."""
    наборы = {tuple(sorted(v)) for v in cli.ЯЗЫКИ.values()}

    assert len(наборы) == 1, cli.ЯЗЫКИ


def test_команда_channels_отдаёт_json(tmp_path, clean_env, capsys):
    завести(tmp_path / "Русский канал", "ru")
    завести(tmp_path / "English channel", "en")
    os.environ["CHANNELS_ROOT"] = str(tmp_path)

    cli.cmd_channels(argparse.Namespace(json=True))

    import json
    данные = json.loads(capsys.readouterr().out)
    assert set(данные) == {"ru", "en"}


def test_команда_channels_подсказывает_когда_пусто(clean_env, capsys):
    os.environ["CHANNELS_ROOT"] = ""

    cli.cmd_channels(argparse.Namespace(json=False))

    вывод = capsys.readouterr().out
    assert "каналов не найдено" in вывод
    assert "CHANNELS_ROOT" in вывод
