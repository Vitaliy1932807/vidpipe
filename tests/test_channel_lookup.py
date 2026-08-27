"""Поиск канала вверх по дереву."""
from __future__ import annotations

from vidpipe.config import CHANNEL_MARKER, Project, find_channel

from conftest import make_channel_dir


def test_канал_находится_из_вложенной_папки(tmp_path):
    channel = make_channel_dir(tmp_path / "каналы" / "hindi")
    deep = tmp_path / "каналы" / "hindi" / "выпуск-01" / "clips"
    deep.mkdir(parents=True)

    assert find_channel(deep) == channel


def test_без_маркера_канала_нет(tmp_path):
    (tmp_path / "старые-ролики" / "ролик").mkdir(parents=True)

    assert find_channel(tmp_path / "старые-ролики" / "ролик") is None


def test_побеждает_ближайший_канал(tmp_path):
    make_channel_dir(tmp_path / "внешний")
    inner = make_channel_dir(tmp_path / "внешний" / "внутренний")
    video = tmp_path / "внешний" / "внутренний" / "выпуск"
    video.mkdir()

    assert find_channel(video) == inner


def test_сама_папка_канала_тоже_считается(tmp_path):
    """Команды, запущенные в корне канала, должны видеть свой канал."""
    channel = make_channel_dir(tmp_path / "hindi")

    assert find_channel(tmp_path / "hindi") == channel


def test_файл_вместо_папки_не_канал(tmp_path):
    """Случайный файл с таким именем не должен притворяться каналом."""
    (tmp_path / CHANNEL_MARKER).write_text("не папка", encoding="utf-8")
    video = tmp_path / "выпуск"
    video.mkdir()

    assert find_channel(video) is None


def test_поиск_от_текущей_папки(tmp_path, monkeypatch):
    channel = make_channel_dir(tmp_path / "hindi")
    video = tmp_path / "hindi" / "выпуск"
    video.mkdir()
    monkeypatch.chdir(video)

    assert find_channel() == channel


def test_project_берёт_канал_от_своей_папки(tmp_path, monkeypatch):
    """`--dir ПУТЬ` из чужого канала: канал берётся от папки ролика."""
    hindi = make_channel_dir(tmp_path / "hindi")
    make_channel_dir(tmp_path / "ru")
    video = tmp_path / "hindi" / "выпуск"
    video.mkdir()
    monkeypatch.chdir(tmp_path / "ru")

    project = Project.load(video)

    assert project.channel == hindi
    assert project.channel_root == tmp_path / "hindi"


def test_project_без_канала(tmp_path):
    project = Project.load(tmp_path / "ролик")

    assert project.channel is None
    assert project.channel_root is None
    assert project.channel_name == ""
