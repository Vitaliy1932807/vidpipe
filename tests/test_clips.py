"""Разбор папки clips: файл находит свою сцену по содержанию, а не по номеру.

Живой случай, ради которого это написано: генератор пронумеровал клипы по
порядку генерации, и файл 037 содержал 56-ю сцену. Собранное видео разошлось
бы с голосом почти целиком, и ни один лог этого бы не показал.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from vidpipe import clips
from vidpipe.config import Project

from conftest import make_channel_dir

СЦЕНЫ = [
    {"scene": 1, "prompt": "a wide empty snowy road disappearing into fog",
     "kind": "видео"},
    {"scene": 2, "prompt": "an amber panel glowing on a workshop table",
     "kind": "картинка"},
    {"scene": 3, "prompt": "a cold hearth filled with grey ash",
     "kind": "картинка"},
    {"scene": 4, "prompt": "a crowd of people walking through a museum hall",
     "kind": "видео"},
]


def проект(tmp_path, файлы, сцены=СЦЕНЫ):
    make_channel_dir(tmp_path / "канал", CHANNEL_NAME="kb")
    d = tmp_path / "канал" / "выпуск"
    (d / "clips").mkdir(parents=True)
    for имя in файлы:
        (d / "clips" / имя).write_bytes(b"0")
    p = Project.load(d)
    p.flow.write_text(json.dumps({"scenes": сцены}, ensure_ascii=False),
                      encoding="utf-8")
    return p


def прогнать(p, apply=False):
    clips.cmd_clips(SimpleNamespace(dir=str(p.dir), apply=apply))


def test_файл_находит_сцену_по_тексту_а_не_по_номеру(tmp_path, global_dir, clean_env):
    """Номер в имени — порядок генерации. Верно только содержание."""
    p = проект(tmp_path, ["001-a-cold-hearth-filled-with-grey-9911.mp4"])

    разбор = clips.сопоставить(clips.файлы_папки(p.dir / "clips"), СЦЕНЫ)

    assert разбор["пары"][0]["сцена"] == 3
    assert разбор["пары"][0]["номер_в_имени"] == 1


def test_одна_сцена_не_достаётся_двум_файлам(tmp_path, global_dir, clean_env):
    """Две копии одного кадра — это брак, а не выбор из двух вариантов."""
    p = проект(tmp_path, ["001-a-cold-hearth-filled-with-grey-11.mp4",
                          "002-a-cold-hearth-filled-with-grey-22.mp4"])

    разбор = клипы = clips.сопоставить(clips.файлы_папки(p.dir / "clips"), СЦЕНЫ)

    assert [п["сцена"] for п in разбор["пары"]] == [3]
    assert len(клипы["без_совпадения"]) == 1


def test_чужой_файл_не_приписывается_наугад(tmp_path, global_dir, clean_env):
    p = проект(tmp_path, ["screenshot-from-my-desktop.png"])

    разбор = clips.сопоставить(clips.файлы_папки(p.dir / "clips"), СЦЕНЫ)

    assert разбор["пары"] == []
    assert разбор["без_совпадения"] == ["screenshot-from-my-desktop.png"]


def test_слабое_совпадение_не_считается_совпадением(tmp_path, global_dir, clean_env):
    """Одно общее слово из пяти — это совпадение случайное.

    Кадр, приписанный не своей сцене, хуже кадра, не приписанного никуда:
    первое уезжает в сборку молча, второе видно в списке.
    """
    p = проект(tmp_path, ["001-a-museum-of-modern-sculpture-in-berlin-11.mp4"])

    разбор = clips.сопоставить(clips.файлы_папки(p.dir / "clips"), СЦЕНЫ)

    assert разбор["пары"] == []          # слово museum есть в сцене 4, но одно
    assert разбор["без_совпадения"] == ["001-a-museum-of-modern-sculpture-in-berlin-11.mp4"]


def test_недостающие_сцены_разделены_на_видео_и_картинки(tmp_path, global_dir,
                                                         clean_env, capsys):
    """Дорисовать картинку и снять видео — разная работа и разные сроки."""
    p = проект(tmp_path, ["001-a-wide-empty-snowy-road-disappearing-11.mp4"])

    прогнать(p)
    вывод = capsys.readouterr().out

    assert "не хватает 3 сцен" in вывод
    assert "картинка  2, 3" in вывод
    assert "видео     4" in вывод


def test_сухой_прогон_ничего_не_трогает(tmp_path, global_dir, clean_env, capsys):
    p = проект(tmp_path, ["001-a-cold-hearth-filled-with-grey-11.mp4"])

    прогнать(p)

    assert (p.dir / "clips" / "001-a-cold-hearth-filled-with-grey-11.mp4").exists()
    assert not (p.dir / "clips" / "карта-переименования.json").exists()
    assert "сухой прогон" in capsys.readouterr().out


def test_apply_переименовывает_и_оставляет_путь_назад(tmp_path, global_dir,
                                                      clean_env):
    """Переименование должно быть обратимым: имена генератора не восстановить."""
    p = проект(tmp_path, ["001-a-cold-hearth-filled-with-grey-11.mp4"])

    прогнать(p, apply=True)

    assert (p.dir / "clips" / "003-a-cold-hearth-filled-with-grey-11.mp4").exists()
    карта = json.loads((p.dir / "clips" / "карта-переименования.json")
                       .read_text(encoding="utf-8"))
    assert карта[0]["было"] == "001-a-cold-hearth-filled-with-grey-11.mp4"
    assert карта[0]["стало"] == "003-a-cold-hearth-filled-with-grey-11.mp4"


def test_повторный_прогон_переименовывать_нечего(tmp_path, global_dir, clean_env,
                                                 capsys):
    p = проект(tmp_path, ["003-a-cold-hearth-filled-with-grey-11.mp4"])

    прогнать(p, apply=True)

    assert "переименовывать нечего" in capsys.readouterr().out


def test_без_раскадровки_шаг_не_гадает(tmp_path, global_dir, clean_env):
    make_channel_dir(tmp_path / "канал", CHANNEL_NAME="kb")
    d = tmp_path / "канал" / "выпуск"
    (d / "clips").mkdir(parents=True)
    (d / "clips" / "001-something.mp4").write_bytes(b"0")

    with pytest.raises(SystemExit, match="шаг flow"):
        прогнать(Project.load(d))


def test_сборка_не_собирает_разъехавшуюся_папку(tmp_path, global_dir, clean_env):
    """Кадр не на своей сцене — это не предупреждение, это испорченный ролик."""
    from vidpipe.validate import check_clips

    p = проект(tmp_path, ["001-a-cold-hearth-filled-with-grey-11.mp4"])

    находки = check_clips(p)

    стоп = [и for и in находки if и.level == "stop" and "не совпадают" in и.what]
    assert стоп, [и.what for и in находки]
    assert "это сцена 3" in стоп[0].what
    assert "vidpipe clips --apply" in стоп[0].fix


def test_правильные_имена_сборку_не_держат(tmp_path, global_dir, clean_env):
    from vidpipe.validate import check_clips

    p = проект(tmp_path, ["003-a-cold-hearth-filled-with-grey-11.mp4"])

    assert not [и for и in check_clips(p) if "не совпадают" in и.what]
