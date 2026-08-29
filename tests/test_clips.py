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


def test_кадры_из_вложенной_папки_находятся(tmp_path, global_dir, clean_env):
    """Генератор отдаёт партию архивом, она разворачивается в подпапку.

    Кадры при этом настоящие, а сборка их не видела и собиралась неполной.
    """
    p = проект(tmp_path, ["001-a-wide-empty-snowy-road-disappearing-11.mp4"])
    вложенная = p.dir / "clips" / "1"
    вложенная.mkdir()
    (вложенная / "007_a-cold-hearth-filled-with-grey-ash.png").write_bytes(b"0")

    разбор = clips.сопоставить(clips.файлы_папки(p.dir / "clips"), СЦЕНЫ)

    assert sorted(п["сцена"] for п in разбор["пары"]) == [1, 3]


def test_apply_поднимает_кадры_наверх(tmp_path, global_dir, clean_env):
    p = проект(tmp_path, [])
    вложенная = p.dir / "clips" / "1"
    вложенная.mkdir()
    (вложенная / "007_a-cold-hearth-filled-with-grey-ash.png").write_bytes(b"0")

    прогнать(p, apply=True)

    assert (p.dir / "clips" / "003-a-cold-hearth-filled-with-grey-ash.png").exists()
    assert not (вложенная / "007_a-cold-hearth-filled-with-grey-ash.png").exists()


def test_сборка_не_идёт_мимо_вложенной_папки(tmp_path, global_dir, clean_env):
    """Часть кадров наверху, часть в подпапке — раньше проезжало молча."""
    from vidpipe.validate import check_clips

    p = проект(tmp_path, ["001-a-wide-empty-snowy-road-disappearing-11.mp4"])
    вложенная = p.dir / "clips" / "1"
    вложенная.mkdir()
    (вложенная / "007_a-cold-hearth-filled-with-grey-ash.png").write_bytes(b"0")

    стоп = [и for и in check_clips(p) if и.level == "stop"]

    assert any("вложенных папках" in и.what for и in стоп), [и.what for и in стоп]
    assert any("vidpipe clips --apply" in и.fix for и in стоп)


def test_кадры_от_чужого_выпуска_останавливают_разбор(tmp_path, global_dir,
                                                      clean_env, capsys):
    """Папки соседние, имена похожие — партию легко скачать не туда.

    Раньше это выглядело как обычный разбор с нулевым результатом: команда
    сообщала «не опознаны» и шла дальше, а счётчик показывал ноль видео при
    полусотне файлов, потому что считал совпавшие пары, а не файлы.
    """
    p = проект(tmp_path, ["001-aerial-view-of-a-small-mountain-airport.mp4",
                          "002-two-wide-body-airliner-tails-standing.mp4"])

    with pytest.raises(SystemExit, match="разбирать нечего"):
        прогнать(p)

    вывод = capsys.readouterr().out
    assert "файлов 2: 2 видео, 0 картинок" in вывод      # считаем файлы
    assert "не подошёл к сценам этого выпуска" in вывод
    assert "папка не та" in вывод


def test_при_ничьей_решает_номер_в_имени(tmp_path, global_dir, clean_env):
    """Генератор обрезает имя, и остатка хватает сразу на две сцены.

    Живой случай: «cockpit of a wide-body airliner seen» подошло и
    восемнадцатой сцене, и двадцать четвёртой одинаково. Побеждала меньшая
    по номеру, и кадр садился не на своё место, а соседняя сцена пустела.
    """
    сцены = [
        {"scene": 18, "prompt": "a wide-body airliner with an upper deck "
                                "rolling along a runway seen from the side",
         "kind": "видео"},
        {"scene": 24, "prompt": "cockpit of a wide-body airliner seen from "
                                "behind the crew seats", "kind": "видео"},
    ]
    p = проект(tmp_path, ["024-cockpit-of-a-wide-body-airliner-seen-05171929.mp4"],
               сцены=сцены)

    разбор = clips.сопоставить(clips.файлы_папки(p.dir / "clips"), сцены)

    assert [п["сцена"] for п in разбор["пары"]] == [24]
    assert разбор["нет_клипа"] == [18]


def test_номер_не_перебивает_текст(tmp_path, global_dir, clean_env):
    """Номер решает только при равенстве. Содержание всегда весомее."""
    p = проект(tmp_path, ["001-a-cold-hearth-filled-with-grey-ash.mp4"])

    разбор = clips.сопоставить(clips.файлы_папки(p.dir / "clips"), СЦЕНЫ)

    assert разбор["пары"][0]["сцена"] == 3      # не 1, хотя в имени единица
