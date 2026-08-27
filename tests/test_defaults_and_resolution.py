"""Один источник дефолтов и один обход цепочки ресурсов (находка 6 ревью)."""
from __future__ import annotations

import ast
import pathlib

from vidpipe.config import DEFAULTS, PACKAGE_ASSETS, Project, env, env_int

from conftest import make_channel_dir

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "vidpipe"


def test_env_подставляет_дефолт_из_общего_словаря(clean_env):
    assert env("WORDS_PER_MIN") == "150"
    assert env("WHISPER_LANG") == "ru"
    assert env_int("WORDS_PER_MIN") == 150


def test_явный_дефолт_главнее_словаря(clean_env):
    assert env("WHISPER_LANG", "hi") == "hi"
    assert env_int("WORDS_PER_MIN", 147) == 147


def test_ключ_без_дефолта_остаётся_пустым(clean_env):
    """Поведение для остальных ключей не изменилось."""
    assert env("VOICER_VOICE_ID") == ""


def test_опечатка_в_имени_ключа_падает_громко(clean_env):
    """env_int без дефолта и без записи в DEFAULTS — это опечатка."""
    try:
        env_int("WORDS_PER_MINUTE")
    except KeyError:
        pass
    else:
        raise AssertionError("ожидался KeyError")


def test_дефолты_не_продублированы_в_коде(clean_env):
    """Ни один модуль не должен носить свою копию значения из DEFAULTS.

    Именно так check однажды и начнёт показывать не то, с чем работает шаг:
    кто-то поменяет 150 в одном файле из четырёх.
    """
    дубли = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "config.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("env", "env_int")
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value in DEFAULTS
                    and len(node.args) > 1):
                дубли.append(f"{path.name}:{node.lineno} {node.args[0].value}")

    assert not дубли, "дефолт задан на месте вместо DEFAULTS: " + ", ".join(дубли)


def test_resolved_отдаёт_путь_и_уровень_разом(tmp_path, global_dir):
    channel = make_channel_dir(tmp_path / "hindi")
    (channel / "assets.md").write_text("канал", encoding="utf-8")
    video = tmp_path / "hindi" / "выпуск"
    video.mkdir()
    project = Project.load(video)

    path, source = project.resolved("assets.md")

    assert (path, source) == (channel / "assets.md", "канал")
    # старые вызовы продолжают работать и отвечают то же самое
    assert project.resource("assets.md") == path
    assert project.resource_source("assets.md") == source


def test_resolved_на_всех_уровнях(tmp_path, global_dir):
    make_channel_dir(tmp_path / "hindi")
    video = tmp_path / "hindi" / "выпуск"
    video.mkdir()
    project = Project.load(video)

    assert project.resolved("assets.md")[1] == "встроенный"
    (global_dir / "assets.md").write_text("глобальный", encoding="utf-8")
    assert project.resolved("assets.md")[1] == "глобальный"
    (project.channel / "assets.md").write_text("канал", encoding="utf-8")
    assert project.resolved("assets.md")[1] == "канал"
    (video / "assets.md").write_text("ролик", encoding="utf-8")
    assert project.resolved("assets.md") == (video / "assets.md", "локальный")


def test_встроенный_ресурс_никуда_не_делся():
    assert (PACKAGE_ASSETS / "script_engine.md").exists()
    assert (PACKAGE_ASSETS / "assets.md").exists()
