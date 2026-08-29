"""Двухуровневый flow: библия героев, свои запреты сцены, сборка кадра."""
from __future__ import annotations

import csv
import json

import pytest

from vidpipe.config import Project
from vidpipe.steps import bible, flow

from conftest import make_channel_dir

БИБЛИЯ = """# Библия

[CHARACTERS]
PETR_01
Male, 52 years old. Lean face, short grey beard, faded dark-blue railway jacket.

WATCHMAN_01
Male, 60s, heavy sheepskin coat, felt boots.

[OBJECTS]
MOTOVOZ_01
A small narrow-gauge motor trolley, rust and dark green paint.
"""

АССЕТЫ = """# Стиль

[STYLE]
cinematic documentary reenactment, 35mm film

[ENV]
rural northern Russia, winter

[NEGATIVE]
no text, no logos
"""


def подготовить(tmp_path, строки=None):
    make_channel_dir(tmp_path / "канал")
    (tmp_path / "канал" / ".vidpipe-channel" / "assets.md").write_text(
        АССЕТЫ, encoding="utf-8")
    d = tmp_path / "канал" / "выпуск"
    d.mkdir()
    project = Project.load(d)
    project.bible.write_text(БИБЛИЯ, encoding="utf-8")
    строки = строки or [{"scene": "1", "start": "00:00:00", "end": "00:00:08",
                         "duration": "8", "narration": "В проёме кто-то стоит",
                         "visual": "луч фонаря упирается в дверной проём",
                         "shot_type": "medium", "motion": "static", "mood": "тихо"}]
    with open(project.shotlist, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(строки[0]))
        w.writeheader()
        w.writerows(строки)
    return project


def test_библия_разбирается_на_записи():
    книга = bible.parse(БИБЛИЯ)

    assert set(книга["CHARACTERS"]) == {"PETR_01", "WATCHMAN_01"}
    assert книга["CHARACTERS"]["PETR_01"].startswith("Male, 52")
    assert set(книга["OBJECTS"]) == {"MOTOVOZ_01"}


def test_общее_лежит_один_раз_а_не_в_каждой_сцене(tmp_path, global_dir,
                                                  clean_env, monkeypatch):
    """61 сцена не должна тащить 61 копию стиля и запретов."""
    строки = [{"scene": str(n), "start": "00:00:00", "end": "00:00:08",
               "duration": "8", "narration": "текст", "visual": "кадр",
               "shot_type": "wide", "motion": "static", "mood": "тихо"}
              for n in range(1, 6)]
    project = подготовить(tmp_path, строки)
    monkeypatch.setattr(flow, "complete_json", lambda s, u, **k: [
        {"scene": n, "prompt": f"shot {n}", "characters": ["PETR_01"],
         "camera": "static wide", "negative": ""} for n in range(1, 6)])

    flow.run(project)
    данные = json.loads(project.flow.read_text(encoding="utf-8-sig"))

    assert данные["global"]["style"].startswith("cinematic")
    assert данные["global"]["characters"]["PETR_01"].startswith("Male, 52")
    for сцена in данные["scenes"]:
        assert "style" not in сцена and "environment" not in сцена


def test_герой_подставляется_описанием_из_библии(tmp_path, global_dir,
                                                 clean_env, monkeypatch):
    """В промпте — только действие; внешность приходит одна и та же."""
    project = подготовить(tmp_path)
    monkeypatch.setattr(flow, "complete_json", lambda s, u, **k: [
        {"scene": 1, "prompt": "the man raises a torch", "characters": ["PETR_01"],
         "camera": "static medium", "lighting": "torchlight",
         "negative": "no person in the doorway"}])

    flow.run(project)
    данные = json.loads(project.flow.read_text(encoding="utf-8-sig"))
    кадр = flow.собрать(данные["scenes"][0], данные["global"])

    assert "the man raises a torch" in кадр
    assert "faded dark-blue railway jacket" in кадр      # из библии
    assert "no person in the doorway" in кадр            # запрет сцены
    assert "no text, no logos" in кадр                   # общий запрет


def test_неизвестный_идентификатор_отбрасывается(tmp_path, global_dir,
                                                 clean_env, monkeypatch):
    """Модель выдумала героя, которого нет в библии — в файл он не попадёт."""
    project = подготовить(tmp_path)
    monkeypatch.setattr(flow, "complete_json", lambda s, u, **k: [
        {"scene": 1, "prompt": "кадр", "characters": ["PETR_01", "ПРИЗРАК_01"],
         "camera": "static"}])

    flow.run(project)
    сцена = json.loads(project.flow.read_text(encoding="utf-8-sig"))["scenes"][0]

    assert сцена["characters"] == ["PETR_01"]


def test_рядом_кладётся_готовый_к_вставке_файл(tmp_path, global_dir,
                                               clean_env, monkeypatch):
    project = подготовить(tmp_path)
    monkeypatch.setattr(flow, "complete_json", lambda s, u, **k: [
        {"scene": 1, "prompt": "the man raises a torch", "characters": ["PETR_01"],
         "camera": "static medium", "purpose": "пик сцены", "audio": "тишина"}])

    flow.run(project)
    текст = (project.dir / "flow_prompts.md").read_text(encoding="utf-8-sig")

    assert "the man raises a torch" in текст
    assert "faded dark-blue railway jacket" in текст
    assert "пик сцены" in текст
    assert "звук: тишина" in текст


def test_без_библии_шаг_предупреждает(tmp_path, global_dir, clean_env,
                                      monkeypatch, capsys):
    project = подготовить(tmp_path)
    project.bible.unlink()
    monkeypatch.setattr(flow, "complete_json", lambda s, u, **k: [
        {"scene": 1, "prompt": "кадр", "camera": "static"}])

    flow.run(project)

    assert "библии героев нет" in capsys.readouterr().out


def test_правила_тайны_и_спойлеров_в_задании():
    """Эти два правила — причина, по которой шаг переписан."""
    assert "СОХРАНЕНИЕ ТАЙНЫ" in flow.SYSTEM
    assert "БЕЗ ВИЗУАЛЬНЫХ СПОЙЛЕРОВ" in flow.SYSTEM
    assert "не босая нога" in flow.SYSTEM
    assert "ПУСТЫЕ КАДРЫ" in flow.SYSTEM
    assert "ПОСЛЕДНИЙ КАДР" in flow.SYSTEM


def test_библия_не_описывает_необъяснимое():
    assert "ЗАПРЕЩЕНО описывать необъяснимое" in bible.SYSTEM


# --- страж тайны -------------------------------------------------------------

def test_спойлер_ловится_только_при_загадке():
    """«the man» — это рассказчик, его показывать можно."""
    # возвращается первое найденное слово из списка, важен сам факт находки
    assert flow.спойлер("В проёме кто-то стоит",
                        "silhouette of a figure standing inside") == "figure"
    assert flow.спойлер("за спиной считают",
                        "A barefoot man stands on the embankment") == "barefoot man"
    # рассказчик в обычной сцене — не спойлер
    assert flow.спойлер("Я шёл домой по насыпи",
                        "the man walks along the embankment") == ""
    # фигура там, где диктор ничего не скрывает — тоже не наше дело
    assert flow.спойлер("Он показал мне журнал",
                        "a figure hands over a logbook") == ""


def test_спойлер_чинится_перегенерацией():
    сцены = [{"scene": 1, "narration": "В проёме кто-то стоит",
              "prompt": "silhouette of a figure standing inside", "negative": ""}]

    остались = flow.без_спойлеров(
        сцены, lambda с, слово: "the torch beam ends in darkness")

    assert остались == []
    assert сцены[0]["prompt"] == "the torch beam ends in darkness"
    assert "no visible figure" in сцены[0]["negative"]


def test_запреты_не_задваиваются():
    """Модель уже могла запретить то же самое — не повторяем за ней."""
    сцены = [{"scene": 1, "narration": "В проёме кто-то стоит",
              "prompt": "a figure in the doorway",
              "negative": "no visible figure, no face"}]

    flow.без_спойлеров(сцены, lambda с, слово: "empty doorway")

    запреты = сцены[0]["negative"].split(", ")
    assert len(запреты) == len(set(запреты)), сцены[0]["negative"]


def test_один_случайный_совпавший_корень_не_якорь():
    """«wooden table» цепляется за «wooden barracks», оставаясь чужой комнатой."""
    глоб = {"environment": "snow, spruce forest, wooden barracks, railway",
            "style": "documentary", "objects": {}}
    сцены = [{"prompt": "the man walks along the snowy embankment"},
             {"prompt": "a steaming cup of coffee on a wooden coffee table"}]

    assert flow.финал_без_якоря(сцены, глоб) is True


def test_если_перегенерация_не_помогла_ставится_безопасный_кадр():
    """Модель может упереться. Тогда лучше пустой кадр, чем показанная разгадка."""
    сцены = [{"scene": 7, "narration": "за спиной считают",
              "prompt": "a shadowy figure counts sleepers", "negative": ""}]

    остались = flow.без_спойлеров(
        сцены, lambda с, слово: "another shadowy figure appears")

    assert остались == ["7"]
    assert сцены[0]["prompt"] == flow.БЕЗОПАСНО
    assert flow.спойлер(сцены[0]["narration"], сцены[0]["prompt"]) == ""


def test_страж_работает_в_настоящем_прогоне(tmp_path, global_dir, clean_env,
                                            monkeypatch, capsys):
    project = подготовить(tmp_path)
    monkeypatch.setattr(flow, "complete_json", lambda s, u, **k: [
        {"scene": 1, "prompt": "silhouette of a figure in the doorway",
         "characters": ["PETR_01"], "camera": "static medium"}])

    flow.run(project)
    сцена = json.loads(project.flow.read_text(encoding="utf-8-sig"))["scenes"][0]

    assert "silhouette" not in сцена["prompt"].lower()
    assert "no visible figure" in сцена["negative"]
    assert "разгадку показывали" in capsys.readouterr().out


def test_спойлер_ловится_при_любом_порядке_слов():
    """«barefoot man» и «man stands barefoot» — одно и то же."""
    for промпт in ("A barefoot man stands on the embankment",
                   "a man stands barefoot on an icy railway embankment",
                   "the person walking barefoot in the snow"):
        assert flow.спойлер("за спиной считают", промпт), промпт

    # следы босых ног — это улика, а не показанная разгадка
    assert flow.спойлер("за спиной считают",
                        "bare footprints in deep snow, no one around") == ""


ГЛОБ = {"environment": "rural northern Russia, winter, railway",
        "style": "cinematic documentary", "objects": {}}


def test_финал_ушедший_в_уют_ловится():
    """После восьми минут мороза — чашка кофе в тёплой комнате."""
    сцены = [{"prompt": "the man walks along the snowy embankment"},
             {"prompt": "a steaming coffee mug in a cozy living room"}]

    assert flow.финал_без_якоря(сцены, ГЛОБ) is True


def test_финал_в_знакомом_кадре_не_ругается():
    """Слова другие, но мир тот же: rails цепляется за railway, snow за snowy."""
    сцены = [{"prompt": "the man walks along the snowy embankment"},
             {"prompt": "empty rails disappear into the snow"}]

    assert flow.финал_без_якоря(сцены, ГЛОБ) is False


def test_сплошной_запрет_людей_снимается_а_уточнённый_остаётся():
    """«no person» спорит с героем в кадре. «no person in the doorway» нет:
    он про другого человека и держит тайну."""
    глоб = {"style": "", "characters": {"PETR_01": "Male, 52, grey beard"},
            "objects": {}}
    сцена = {"prompt": "the man raises a torch", "characters": ["PETR_01"],
             "negative": "no person, no person in the doorway"}

    кадр = flow.собрать(сцена, глоб)

    assert "grey beard" in кадр
    assert "no person in the doorway" in кадр
    assert "no person," not in кадр


def test_героя_нет_в_кадре_описание_не_подставляется():
    """Модель приписала сцене героя, которого в промпте нет."""
    глоб = {"style": "", "characters": {"PETR_01": "Male, 52, grey beard"},
            "objects": {}}
    сцена = {"prompt": "amber panels glowing on the wall",
             "characters": ["PETR_01"], "negative": "no person in the room"}

    кадр = flow.собрать(сцена, глоб)

    assert "grey beard" not in кадр
    assert "no person in the room" in кадр


def test_профессия_в_промпте_считается_человеком():
    """Живой случай: пилоты, бортинженер и диспетчер не опознавались людьми,
    и описание героя выбрасывалось из кадра."""
    глоб = {"style": "", "characters": {"KAP_01": "Male, 50, navy uniform"},
            "objects": {}}
    for промпт in ("two uniformed pilots at the controls",
                   "a flight engineer turning towards the captain",
                   "a controller at a console in a small tower"):
        кадр = flow.собрать({"prompt": промпт, "characters": ["KAP_01"],
                             "negative": ""}, глоб)
        assert "navy uniform" in кадр, промпт


@pytest.mark.parametrize("запрет, снимается", [
    ("no visible figure", True),        # так протекло на живом выпуске
    ("no person", True),
    ("no people in frame", True),
    ("no one visible", True),
    ("no person in the doorway", False),        # указание места, а не запрет
    ("no people behind the window", False),
    ("no bodies", False),                       # запрет содержания, не людей
    ("", False),
])
def test_запрет_людей_отличает_общее_от_местного(запрет, снимается):
    """Общий запрет спорит с описанием героя, местный — уточняет кадр."""
    assert flow.запрет_людей(запрет) is снимается


def test_описание_героя_не_едет_вместе_с_запретом_фигуры():
    """Живой случай: девять сцен ушли с портретом человека и «no visible figure»."""
    сцена = {"prompt": "a portrait of a man in an office, looking straight ahead",
             "characters": ["RODE"], "negative": "no visible figure, no logos"}
    глоб = {"characters": {"RODE": "Male, early 50s, narrow face, round glasses."}}

    текст = flow.собрать(сцена, глоб)

    assert "narrow face" in текст          # герой описан
    assert "no visible figure" not in текст
    assert "no logos" in текст             # чужие запреты не задеты


@pytest.mark.parametrize("промпт, человек", [
    ("a man raises a torch", True),
    ("two pilots in the cockpit", True),
    ("archaeologists at work", True),
    ("a crowd of people", True),
    ("rows of dials on an instrument panel", False),   # men внутри instrument
    ("a handset vibrating on a desk", False),          # hand внутри handset
    ("a crowded apron seen from above", False),        # crowd внутри crowded
    ("a documentary about steam engines", False),
])
def test_человек_опознаётся_по_слову_целиком(промпт, человек):
    """Список сверялся подстрокой, и instrument открывал ворота как «men».

    Само по себе это молчало, пока в сцене не указан герой. Зато отключало
    проверку «герой указан, а в кадре его нет»: она считала, что человек есть.
    """
    assert flow.есть_люди(промпт) is человек


def test_ложный_человек_не_снимает_запрет_людей():
    """Кадр без людей должен сохранить свой запрет, даже если в слове есть men."""
    сцена = {"prompt": "rows of dials on an instrument panel",
             "characters": ["RODE"], "negative": "no person"}
    глоб = {"characters": {"RODE": "Male, early 50s, round glasses."}}

    кадр = flow.собрать(сцена, глоб)

    assert "no person" in кадр          # запрет на месте
    assert "round glasses" not in кадр  # описывать в этом кадре некого


РАСКЛАД = [
    {"scene": 1, "prompt": "an empty snowy road", "kind": "видео",
     "duration": 8.0, "start": "00:00:00", "end": "00:00:08", "characters": [],
     "camera": "", "lighting": "", "negative": ""},
    {"scene": 2, "prompt": "an amber panel on a table", "kind": "картинка",
     "duration": 8.0, "start": "00:00:08", "end": "00:00:16", "characters": [],
     "camera": "", "lighting": "", "negative": ""},
    {"scene": 3, "prompt": "a cold hearth full of ash", "kind": "картинка",
     "duration": 8.0, "start": "00:00:16", "end": "00:00:24", "characters": [],
     "camera": "", "lighting": "", "negative": ""},
]


def test_промпты_раскладываются_по_виду():
    """Генераторы видео и картинок разные, работать с ними удобнее раздельно."""
    видео = flow.render_txt({}, РАСКЛАД, "видео")
    картинки = flow.render_txt({}, РАСКЛАД, "картинка")

    assert "an empty snowy road" in видео
    assert "an amber panel" not in видео
    блоки = [б for б in картинки.split("\n\n") if б.strip()]
    assert len(блоки) == 2                      # две сцены, каждая отдельным блоком
    assert [б.split("\n")[0] for б in блоки] == ["2", "3"]


def test_в_раскладке_только_номер_и_промпт():
    """Ни заголовков, ни разметки, ни отступов: блок вставляется как есть."""
    текст = flow.render_txt({}, РАСКЛАД, "видео")
    строки = [с for с in текст.split("\n") if с]

    assert строки[0] == "1"
    assert строки[1].startswith("an empty snowy road")
    assert not any(с.startswith((" ", "\t", "#", "`", ">")) for с in строки)


def test_раскладка_ложится_рядом_с_выпуском(tmp_path, global_dir, clean_env):
    from vidpipe.config import Project
    make_channel_dir(tmp_path / "канал", CHANNEL_NAME="kb")
    d = tmp_path / "канал" / "выпуск"
    d.mkdir()
    p = Project.load(d)

    сделано = flow.разложить_по_виду(p, {}, РАСКЛАД)

    assert (p.dir / "промпты-видео.txt").exists()
    assert (p.dir / "промпты-картинки.txt").exists()
    assert сделано["видео"][1] == 1 and сделано["картинка"][1] == 2


@pytest.mark.parametrize("промпт, человек", [
    ("a keyman standing on the track", True),
    ("an old gateman on a bench", True),
    ("a trackman with a hammer", True),
    ("a watchman at the crossing", True),
    ("a specimen in a glass case", False),     # музей, не человек
    ("bitumen spread on the road", False),     # пути, не человек
    ("a lumen of soft light", False),
])
def test_профессии_на_man_считаются_людьми(промпт, человек):
    """Список профессий поимённый не держится: каждый канал приносит свои.

    Индийский выпуск про путевого обходчика принёс keyman и gateman разом, и
    проверка «герой указан, а в кадре его нет» объявила призраками тридцать
    одну сцену из шестидесяти четырёх. Суффикс -man надёжнее списка, но не
    всякое слово на -men человек, и эти встречаются в наших же кадрах.
    """
    assert flow.есть_люди(промпт) is человек


def test_описание_подставляется_профессии_из_другого_канала():
    """Герой-обходчик должен получать описание из библии, как и все прочие."""
    сцена = {"prompt": "a keyman standing alone on the track",
             "characters": ["SHIVNATH"], "negative": "no ghost figure"}
    глоб = {"characters": {"SHIVNATH": "Male, about 45, lean and wiry."}}

    кадр = flow.собрать(сцена, глоб)

    assert "lean and wiry" in кадр
    assert "no ghost figure" in кадр      # запрет не про людей, остаётся
