"""Раскладка на уже разложенной папке.

Случай, стоивший выпуска: имена вида `023-Title.jpeg` не имеют `_a`/`_b`,
поэтому попадают в запасной разбор по номеру. Раньше они при этом оставались
и в списке «вариантов», а `разложить` уносила варианты первым делом — 35
картинок уехали в `_варианты`, переименовывать стало нечего, и в clips
остались одни видео с временным префиксом.
"""
import json

from vidpipe.layout import разложить, разобрать


_СЛОВА = ["one", "two", "three", "four", "five", "six"]


def _слово(i):
    return _СЛОВА[i]


def _выпуск(tmp_path, видео=2, картинок=3):
    сцены = []
    н = 1
    for i in range(видео):
        сцены.append({"scene": н, "kind": "видео",
                      "prompt": "A video scene alpha bravo charlie delta echo %s" % _слово(i)})
        н += 1
    for i in range(картинок):
        сцены.append({"scene": н, "kind": "картинка",
                      "prompt": "A picture scene foxtrot golf hotel india juliet %s" % _слово(i)})
        н += 1
    (tmp_path / "flow_prompts.json").write_text(
        json.dumps({"scenes": сцены}), encoding="utf-8")
    (tmp_path / "clips").mkdir()
    return сцены


def _положить(tmp_path, имена):
    for имя in имена:
        (tmp_path / "clips" / имя).write_bytes(b"x")


def test_разложенная_папка_не_разъезжается(tmp_path):
    сцены = _выпуск(tmp_path)
    имена = []
    for с in сцены:
        слаг = "-".join(с["prompt"].split()[:8])
        имена.append("%03d-%s%s" % (с["scene"], слаг,
                                    ".mp4" if с["kind"] == "видео" else ".jpeg"))
    _положить(tmp_path, имена)

    р = разобрать(tmp_path)
    assert р["годится"], р.get("почему")
    assert р["варианты"] == [], "разложенные файлы попали в варианты"
    assert р["нет_материала"] == []

    разложить(tmp_path, р)
    осталось = sorted(x.name for x in (tmp_path / "clips").iterdir())
    assert осталось == sorted(имена)
    assert not (tmp_path / "_варианты").exists()


def test_план_с_пропавшим_файлом_ничего_не_трогает(tmp_path):
    сцены = _выпуск(tmp_path, видео=1, картинок=1)
    имена = []
    for с in сцены:
        слаг = "-".join(с["prompt"].split()[:8])
        имена.append("%03d-%s%s" % (с["scene"], слаг,
                                    ".mp4" if с["kind"] == "видео" else ".jpeg"))
    _положить(tmp_path, имена)
    р = разобрать(tmp_path)
    р["план"][0]["файл"].unlink()             # файл исчез между разбором и правкой
    итог = разложить(tmp_path, р)
    assert not итог["годится"]
    assert "нет на диске" in итог["почему"]
    # уцелевший файл остался на месте, ничего не унесено
    assert (tmp_path / "clips" / имена[1]).exists()
    assert not (tmp_path / "_варианты").exists()
