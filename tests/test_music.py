"""Фоновая музыка в сборке: находится, приглушается и уступает диктору."""
from __future__ import annotations

import os

from vidpipe.config import Project
from vidpipe.steps.assemble import найти_музыку, звуковой_фильтр

from conftest import make_channel_dir


def проект(tmp_path):
    make_channel_dir(tmp_path / "канал", CHANNEL_NAME="kb")
    d = tmp_path / "канал" / "выпуск"
    d.mkdir()
    return Project.load(d)


def test_музыки_нет_если_не_задана(tmp_path, global_dir, clean_env):
    assert найти_музыку(проект(tmp_path)) is None


def test_music_mp3_рядом_с_каналом_подхватывается(tmp_path, global_dir, clean_env):
    """Одна дорожка на канал — обычный случай, ради него не нужен конфиг."""
    p = проект(tmp_path)
    (p.channel_root / "music.mp3").write_bytes(b"0")

    assert найти_музыку(p) == p.channel_root / "music.mp3"


def test_выпуск_перебивает_канал(tmp_path, global_dir, clean_env):
    p = проект(tmp_path)
    (p.channel_root / "music.mp3").write_bytes(b"0")
    (p.dir / "music.mp3").write_bytes(b"0")

    assert найти_музыку(p) == p.dir / "music.mp3"


def test_пустое_значение_снимает_музыку(tmp_path, global_dir, clean_env):
    """Канал включил фон, а этому выпуску он не нужен: тишина это выбор."""
    p = проект(tmp_path)
    (p.channel_root / "music.mp3").write_bytes(b"0")
    os.environ["MUSIC_FILE"] = ""

    assert найти_музыку(p) is None


def test_путь_ищется_относительно_канала(tmp_path, global_dir, clean_env):
    p = проект(tmp_path)
    (p.channel_root / "фонотека").mkdir()
    (p.channel_root / "фонотека" / "тихая.mp3").write_bytes(b"0")
    os.environ["MUSIC_FILE"] = "фонотека/тихая.mp3"

    assert найти_музыку(p) == p.channel_root / "фонотека" / "тихая.mp3"


def test_несуществующий_файл_не_ломает_сборку(tmp_path, global_dir, clean_env):
    """Опечатка в пути не должна ронять шаг: ролик соберётся без музыки."""
    os.environ["MUSIC_FILE"] = "нет-такого.mp3"

    assert найти_музыку(проект(tmp_path)) is None


def test_музыка_уступает_диктору(clean_env):
    """Голос ведёт громкость фона через боковую цепь, а не наоборот."""
    ф = звуковой_фильтр(100.0)

    assert "sidechaincompress" in ф
    assert "[m][1:a]sidechaincompress" in ф      # ключ — дорожка голоса
    assert "amix=inputs=2:normalize=0" in ф      # голос не давится нормировкой


def test_фон_поднимается_и_уходит(clean_env):
    ф = звуковой_фильтр(100.0)

    assert "afade=t=in:st=0:d=3" in ф
    assert "afade=t=out:st=97:d=3" in ф          # уход к самому концу


def test_короткий_ролик_не_ломает_затухание(clean_env):
    """Ролик короче времени затухания: старт ухода не должен уйти в минус."""
    ф = звуковой_фильтр(1.0)

    assert "afade=t=out:st=0:" in ф


def test_громкость_настраивается(clean_env):
    os.environ["MUSIC_GAIN_DB"] = "-14"

    assert "volume=-14dB" in звуковой_фильтр(60.0)
