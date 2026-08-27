"""Цепочка ресурсов: папка ролика -> канал -> глобальный -> встроенный."""
from __future__ import annotations

import pytest

from vidpipe.config import PACKAGE_ASSETS, Project

from conftest import make_channel_dir

NAME = "script_engine.md"


@pytest.fixture
def video(tmp_path, global_dir):
    """Ролик внутри канала; на каждом уровне лежит своя методика."""
    channel = make_channel_dir(tmp_path / "hindi")
    (channel / NAME).write_text("канал", encoding="utf-8")
    (global_dir / NAME).write_text("глобальный", encoding="utf-8")
    d = tmp_path / "hindi" / "выпуск-01"
    d.mkdir()
    return Project.load(d)


def test_папка_ролика_главнее_канала(video):
    (video.dir / NAME).write_text("ролик", encoding="utf-8")

    assert video.resource(NAME).read_text(encoding="utf-8") == "ролик"
    assert video.resource_source(NAME) == "локальный"


def test_подпапка_prompts_тоже_локальный_уровень(video):
    (video.dir / "prompts").mkdir()
    (video.dir / "prompts" / NAME).write_text("ролик", encoding="utf-8")

    assert video.resource_source(NAME) == "локальный"


def test_канал_главнее_глобального(video):
    assert video.resource(NAME).read_text(encoding="utf-8") == "канал"
    assert video.resource_source(NAME) == "канал"


def test_без_файла_в_канале_берётся_глобальный(video):
    (video.channel / NAME).unlink()

    assert video.resource(NAME).read_text(encoding="utf-8") == "глобальный"
    assert video.resource_source(NAME) == "глобальный"


def test_последний_рубеж_встроенный_в_пакет(video):
    (video.channel / NAME).unlink()
    (video.resource(NAME)).unlink()          # глобальный

    assert video.resource(NAME) == PACKAGE_ASSETS / NAME
    assert video.resource_source(NAME) == "встроенный"


def test_без_канала_цепочка_как_раньше(tmp_path, global_dir):
    """Совместимость: папки роликов, созданные до каналов, не ломаются."""
    (global_dir / NAME).write_text("глобальный", encoding="utf-8")
    project = Project.load(tmp_path / "старый-ролик")

    assert project.channel is None
    assert project.resource_source(NAME) == "глобальный"
    assert project.resource_source("assets.md") == "встроенный"


def test_ненайденный_ресурс_останавливает_работу(tmp_path, global_dir):
    project = Project.load(tmp_path / "ролик")

    with pytest.raises(SystemExit, match="не найден ресурс"):
        project.resource("нет-такого.md")
