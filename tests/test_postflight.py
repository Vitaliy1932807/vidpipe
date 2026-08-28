"""Приёмка результата шага: брак не должен уезжать дальше как готовый."""
from __future__ import annotations

import json
import os

import pytest

from vidpipe import checks
from vidpipe.config import Project

from conftest import make_channel_dir

БИБЛИЯ_ЧИСТАЯ = """[CHARACTERS]
PETR_01
Male, 52 years old, grey beard, dark blue railway jacket.

[OBJECTS]
PANELS_01
Amber panels on oak backing, about 55 square metres in total.
"""


def проект(tmp_path, **файлы):
    make_channel_dir(tmp_path / "канал", CHANNEL_NAME="kb")
    d = tmp_path / "канал" / "выпуск"
    d.mkdir()
    p = Project.load(d)
    for имя, текст in файлы.items():
        (d / имя.replace("__", ".")).write_text(текст, encoding="utf-8")
    return p


# --- библия -------------------------------------------------------------------

def test_библия_с_описанной_загадкой_не_проходит(tmp_path, global_dir, clean_env):
    """Описанная сущность перестаёт быть тайной, и это блокирующая находка."""
    p = проект(tmp_path, bible__md="""[CHARACTERS]
SHADOW_01
A tall shadowy figure standing in the doorway, face hidden.
""")

    находки = checks.check_bible(p)

    assert any(i.level == "stop" and "необъяснимое" in i.what for i in находки)


def test_выдуманное_число_в_библии_ловится(tmp_path, global_dir, clean_env):
    """Живой случай: панелям досталось 250 метров вместо пятидесяти пяти."""
    p = проект(tmp_path,
               script__md="Панели площадью около 55 квадратных метров.",
               bible__md="""[OBJECTS]
PANELS_01
Amber panels, 250 square metres in total.
""")

    находки = checks.check_bible(p)

    assert any("250" in i.what for i in находки), [i.what for i in находки]


def test_согласованное_число_не_ругается(tmp_path, global_dir, clean_env):
    p = проект(tmp_path,
               script__md="Панели площадью около 55 квадратных метров.",
               bible__md=БИБЛИЯ_ЧИСТАЯ)

    assert [i for i in checks.check_bible(p) if "нет в сценарии" in i.what] == []


def test_число_словами_в_сценарии_не_вызывает_ложной_тревоги(tmp_path, global_dir,
                                                             clean_env):
    """Перед озвучкой цифры заменяются словами, сверять становится нечем.

    Живой случай: в сценарии стоит «пятьдесят пять квадратных метров», и
    сверка по цифрам подняла ложную тревогу на верной библии.
    """
    p = проект(tmp_path,
               script__md="Панели площадью около пятидесяти пяти квадратных метров.",
               bible__md=БИБЛИЯ_ЧИСТАЯ)

    assert [i for i in checks.check_bible(p) if "нет в сценарии" in i.what] == []


def test_число_сверяется_и_по_тз_а_не_только_по_сценарию(tmp_path, global_dir,
                                                        clean_env):
    p = проект(tmp_path,
               script__md="Панели площадью около пятидесяти пяти метров.",
               prompt__md="Площадь убранства около 55 квадратных метров.",
               bible__md=БИБЛИЯ_ЧИСТАЯ)

    assert [i for i in checks.check_bible(p) if "нет в сценарии" in i.what] == []


def test_идентификаторы_из_примера_блокируют(tmp_path, global_dir, clean_env):
    """Живой случай: в библию для ролика про Тенерифе попал PETR_01 из примера."""
    p = проект(tmp_path, bible__md="""[CHARACTERS]
PLACEHOLDER_01
Male, 52 years old, grey beard.
""")

    находки = checks.check_bible(p)

    assert any(i.level == "stop" and "списаны из примера" in i.what
               for i in находки), [i.what for i in находки]


def test_свои_идентификаторы_проходят(tmp_path, global_dir, clean_env):
    p = проект(tmp_path, bible__md=БИБЛИЯ_ЧИСТАЯ)

    assert not [i for i in checks.check_bible(p) if "списаны" in i.what]


def test_пустая_библия_блокирует(tmp_path, global_dir, clean_env):
    p = проект(tmp_path, bible__md="# библия\n\nтут пусто\n")

    assert any(i.level == "stop" for i in checks.check_bible(p))


# --- промпты Flow -------------------------------------------------------------

def flow_файл(сцены, глоб=None):
    return json.dumps({"project": "т", "scene_count": len(сцены),
                       "global": глоб or {"style": "cinematic", "characters": {},
                                          "objects": {}},
                       "scenes": сцены}, ensure_ascii=False)


def test_спойлер_в_промптах_блокирует(tmp_path, global_dir, clean_env):
    p = проект(tmp_path, flow_prompts__json=flow_файл([
        {"scene": 1, "narration": "В проёме кто-то стоит",
         "prompt": "a silhouette of a figure in the doorway", "characters": []},
    ]))

    находки = checks.check_flow(p)

    assert any(i.level == "stop" and "разгадка" in i.what for i in находки)


def test_пустой_промпт_блокирует(tmp_path, global_dir, clean_env):
    p = проект(tmp_path, flow_prompts__json=flow_файл([
        {"scene": 1, "narration": "текст", "prompt": "", "characters": []},
    ]))

    assert any(i.level == "stop" for i in checks.check_flow(p))


def test_герой_не_из_библии_это_предупреждение(tmp_path, global_dir, clean_env):
    """Не блокируем: кадр рабочий, но описание героя не подставится."""
    p = проект(tmp_path, flow_prompts__json=flow_файл([
        {"scene": 1, "narration": "текст", "prompt": "кадр",
         "characters": ["НЕИЗВЕСТНЫЙ_01"]},
    ]))

    находки = checks.check_flow(p)

    assert any(i.level == "warn" and "не из библии" in i.what for i in находки)
    assert not [i for i in находки if i.level == "stop"]


def test_чистые_промпты_проходят(tmp_path, global_dir, clean_env):
    p = проект(tmp_path, flow_prompts__json=flow_файл([
        {"scene": 1, "narration": "Я шёл по насыпи",
         "prompt": "the man walks along a snowy embankment", "characters": []},
        {"scene": 2, "narration": "Рельсы уходили в снег",
         "prompt": "empty snowy rails disappear into the distance",
         "characters": []},
    ]))

    assert [i for i in checks.check_flow(p) if i.level == "stop"] == []


# --- досье --------------------------------------------------------------------

def test_досье_без_пометки_о_проверке(tmp_path, global_dir, clean_env):
    p = проект(tmp_path, dossier__md="Факт один. " * 100)

    assert any("пометки" in i.what for i in checks.check_dossier(p))


def test_нет_досье_нет_претензий(tmp_path, global_dir, clean_env):
    """Шаг research необязателен."""
    assert checks.check_dossier(проект(tmp_path)) == []


# --- сама приёмка -------------------------------------------------------------

def test_брак_останавливает_конвейер(tmp_path, global_dir, clean_env, capsys):
    p = проект(tmp_path, bible__md="""[CHARACTERS]
GHOST_01
A shadowy figure in the doorway.
""")

    with pytest.raises(SystemExit, match="результат не принят"):
        checks.postflight(p, "bible")

    assert "необъяснимое" in capsys.readouterr().out


def test_loose_показывает_но_не_останавливает(tmp_path, global_dir, clean_env,
                                              capsys):
    p = проект(tmp_path, bible__md="""[CHARACTERS]
GHOST_01
A shadowy figure in the doorway.
""")

    checks.postflight(p, "bible", strict=False)

    assert "необъяснимое" in capsys.readouterr().out


def test_у_каждого_шага_есть_приёмка():
    """Шаг без проверки выхода это дыра, через которую уезжает брак."""
    from vidpipe.cli import STEPS

    без_проверки = sorted(set(STEPS) - set(checks.POSTFLIGHT))

    assert not без_проверки, без_проверки


СТОП = chr(10) + chr(10)
ТИРЕ = chr(8212)
МНОГОТОЧИЕ = chr(8230)

# --- то, что пробовали спрашивать у модели, а проверяет код -------------------

def test_финал_на_вопросе_ловится(tmp_path, global_dir, clean_env):
    """Локальный критик заявил это про текст без единого вопросительного знака."""
    from vidpipe.validate import check_script

    p = проект(tmp_path, script__md="Первый абзац." + СТОП + "А что было дальше?")

    assert any("заканчивается вопросом" in i.what for i in check_script(p))


def test_финал_на_призыве_ловится(tmp_path, global_dir, clean_env):
    from vidpipe.validate import check_script

    p = проект(tmp_path, script__md="Первый абзац." + СТОП +
                                    "Напишите в комментариях, что думаете.")

    assert any("заканчивается призывом" in i.what for i in check_script(p))


def test_честный_финал_не_ругается(tmp_path, global_dir, clean_env):
    """Настоящая концовка Янтарной комнаты: ни вопроса, ни призыва."""
    from vidpipe.validate import check_script

    p = проект(tmp_path, script__md=(
        "Напиши в комментариях, что это было." + СТОП +
        "Её сняли со стены за тридцать шесть часов. "
        "Чтобы её не стало, могло хватить одной ночи."))

    assert not [i for i in check_script(p) if "заканчивается" in i.what]


def test_запрещённые_каналом_знаки(tmp_path, global_dir, clean_env):
    """Методика этого канала запрещает тире: синтез читает его паузой."""
    from vidpipe.validate import check_script

    os.environ["SCRIPT_FORBID"] = ТИРЕ + МНОГОТОЧИЕ
    p = проект(tmp_path, script__md="Текст " + ТИРЕ + " с тире и многоточием" + МНОГОТОЧИЕ)

    assert any("запрещённые каналом знаки" in i.what for i in check_script(p))
