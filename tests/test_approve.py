"""Остановка после сценария: дальше идём только с прочитанным текстом."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from vidpipe import approve
from vidpipe.checks import postflight
from vidpipe.config import Project
from vidpipe.validate import preflight

from conftest import make_channel_dir

ТЕКСТ = "Первая строка сценария.\n\nВторая строка, и третья тоже тут.\n"


def проект(tmp_path, текст=ТЕКСТ):
    make_channel_dir(tmp_path / "канал", CHANNEL_NAME="kb")
    d = tmp_path / "канал" / "выпуск"
    d.mkdir()
    p = Project.load(d)
    if текст is not None:
        p.script.write_text(текст, encoding="utf-8")
    return p


def test_непрочитанный_сценарий_не_пускает_дальше(tmp_path, global_dir, clean_env):
    """Голос платный: озвучить непрочитанный текст — самая дорогая опечатка."""
    p = проект(tmp_path)

    with pytest.raises(SystemExit, match="не может начаться"):
        preflight(p, "tts")


def test_после_подтверждения_шаг_идёт(tmp_path, global_dir, clean_env):
    p = проект(tmp_path)

    approve.cmd_ok(SimpleNamespace(dir=str(p.dir)))

    preflight(p, "bible")          # молча, без исключения


def test_правка_текста_снимает_подтверждение(tmp_path, global_dir, clean_env):
    """Иначе «я читал» означало бы текст, которого никто не читал."""
    p = проект(tmp_path)
    approve.cmd_ok(SimpleNamespace(dir=str(p.dir)))

    p.script.write_text(ТЕКСТ + "Дописанный после проверки абзац.\n",
                        encoding="utf-8")

    assert approve.не_принят(p) == "сценарий изменился после проверки"
    with pytest.raises(SystemExit):
        preflight(p, "tts")


def test_перевод_строк_правкой_не_считается(tmp_path, global_dir, clean_env):
    """Файл ездит между Windows и git: CRLF против LF — не правка сценария."""
    p = проект(tmp_path)
    approve.cmd_ok(SimpleNamespace(dir=str(p.dir)))

    p.script.write_bytes(ТЕКСТ.replace("\n", "\r\n").encode("utf-8"))

    assert approve.не_принят(p) == ""


def test_пустая_строка_в_конце_правкой_не_считается(tmp_path, global_dir,
                                                   clean_env):
    """Редакторы дописывают и убирают перевод строки в конце молча."""
    p = проект(tmp_path)
    approve.cmd_ok(SimpleNamespace(dir=str(p.dir)))

    p.script.write_text(ТЕКСТ.rstrip() + "\n\n\n", encoding="utf-8")

    assert approve.не_принят(p) == ""


def test_правило_молчит_там_где_сценария_нет(tmp_path, global_dir, clean_env):
    """Выпуск могут собирать из готовой озвучки — это не наше дело."""
    p = проект(tmp_path, текст=None)

    assert approve.не_принят(p) == ""


def test_все_шаги_после_сценария_под_правилом(tmp_path, global_dir, clean_env):
    p = проект(tmp_path)

    from vidpipe.validate import PREFLIGHT, check_сценарий_прочитан

    # Не через preflight: у tts и clean свои причины остановиться, и тест
    # прошёл бы, даже если правило к ним не подключено.
    for шаг in approve.ПОСЛЕ_СЦЕНАРИЯ:
        assert check_сценарий_прочитан in PREFLIGHT[шаг], шаг
    assert check_сценарий_прочитан not in PREFLIGHT.get("script", [])


def test_после_шага_сценария_напоминание_а_не_стоп(tmp_path, global_dir,
                                                   clean_env, capsys):
    """Написать текст шаг может; читать его — человеку, и его не подгоняют."""
    p = проект(tmp_path, текст=ТЕКСТ * 40)

    postflight(p, "script")        # не останавливает

    assert "vidpipe ok" in capsys.readouterr().out


def test_подтверждать_нечего_без_сценария(tmp_path, global_dir, clean_env):
    p = проект(tmp_path, текст=None)

    with pytest.raises(SystemExit, match="подтверждать нечего"):
        approve.cmd_ok(SimpleNamespace(dir=str(p.dir)))
