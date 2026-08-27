"""Шаг 6: shotlist.csv -> flow_prompts.json + flow_prompts.md

Два уровня. Общее — стиль, окружение, запреты, библия героев — живёт один раз
в блоке global. Сцена несёт только своё: действие, камеру, свет, склейку и
свой запрет. Так 61 сцена не тащит 61 копию одного и того же.

JSON — источник правды для автоматики. Рядом кладётся .md, где каждый кадр
уже собран целиком: его можно копировать в Flow как есть.
"""
from __future__ import annotations

import csv
import json
import re

from ..config import env_int, read_text
from ..llm import complete_json
from . import bible as bible_step

SYSTEM = """Ты собираешь промпты для генератора видео Veo/Flow по готовой раскадровке.

ГЛАВНОЕ ПРАВИЛО — СОХРАНЕНИЕ ТАЙНЫ.
Никогда не показывай визуально то, что диктор намеренно оставляет неизвестным.
Если в реплике «кто-то», «что-то», «голос», «фигура», «оно», «кто-то стоит» —
в кадре этого быть НЕ ДОЛЖНО. Не человек в дверях, не силуэт, не тень фигуры,
не босая нога. Показывай то, что видит рассказчик ДО того, как понял: луч
фонаря, упирающийся в темноту; пустой дверной проём; рельсы позади; снег.
Промпт, который показывает разгадку раньше диктора, убивает удержание — это
худшая ошибка в этом жанре, хуже некрасивого кадра.

БЕЗ ВИЗУАЛЬНЫХ СПОЙЛЕРОВ.
Аномалию показывай следствием, а не причиной: не тот, кто оставил след, а
след; не тот, кто считает, а лицо слушающего; не фигура, а полоса света, за
которой ничего не разобрать.

ГЕРОИ ТОЛЬКО ПО ИДЕНТИФИКАТОРУ.
Тебе дан список постоянных персонажей и предметов. В поле characters укажи
идентификаторы тех, кто есть в кадре. В самом промпте НЕ описывай их
внешность и одежду — описание подставится отдельно и одинаково во всех
сценах. Пиши только действие: "PETR_01 walks along the embankment" — но в
prompt вместо идентификатора ставь нейтральное "the man", описание придёт из
библии. Никогда не выдумывай возраст, лицо и одежду сам.

ПУСТЫЕ КАДРЫ.
Если в сцене нет события, это не чёрный экран. В кадре остаётся предмет,
который зритель уже знает: рельсы, кабина, второе сиденье, дверь, журнал,
следы. Пустота при знакомом предмете держит напряжение, пустота вообще —
не держит ничего.

ПОСЛЕДНИЙ КАДР.
Финал остаётся в мире истории. Никакого тепла, уюта, утреннего света и
посторонних предметов, которых в ролике не было. Пустая зимняя дорога,
уходящие рельсы, тёмное окно — и всё.

Остальные правила:
- Только английский, одно плотное предложение или два коротких.
- Перенеси конкретную деталь из описания кадра — ту, ради которой сцена
  существует. Обобщение убивает сцену.
- Не заменяй названное похожим: наст это crust of snow, а не ice.
- ОДНО непрерывное действие: клип длится 8 секунд, смены сцены внутри нет.
- Ни имён, ни брендов, ни надписей и текста в кадре.
- Ни слова о звуке и музыке в самом промпте: для звука есть отдельное поле.
- Стиль и общие запреты не дублируй, они добавляются отдельно.

Верни JSON-массив строго по номерам сцен:
[{"scene": 1,
  "purpose": "зачем этот кадр в ролике, по-русски, до восьми слов",
  "prompt": "визуальное действие, английский",
  "characters": ["PETR_01"],
  "camera": "static wide shot",
  "lighting": "overcast winter daylight",
  "continuity": "что должно совпасть с соседними кадрами, английский",
  "audio": "звуковая опора кадра, по-русски, до пяти слов",
  "negative": "запреты именно этой сцены, английский, через запятую"}]

negative сцены — это то, что нельзя показать здесь и сейчас: например
"no person in the doorway, no silhouette, no visible figure" для сцены, где
диктор говорит «кто-то стоит». Пусто оставляй только если запрещать нечего."""


def load_assets(project) -> dict[str, str]:
    try:
        path = project.resource("assets.md")
    except SystemExit:
        return {}
    print(f"[flow] стиль: {path} ({project.resource_source('assets.md')})")
    raw = read_text(path)
    blocks = {}
    for m in re.finditer(r"^\[([A-Z]+)\]\s*\n(.*?)(?=^\[[A-Z]+\]|\Z)", raw, re.S | re.M):
        blocks[m.group(1)] = " ".join(m.group(2).split())
    return blocks


def справочник(книга: dict[str, dict[str, str]]) -> str:
    """Список идентификаторов для модели: кто есть в ролике."""
    строки = []
    for блок, подпись in (("CHARACTERS", "ГЕРОИ"), ("OBJECTS", "ПРЕДМЕТЫ И МЕСТА")):
        записи = книга.get(блок) or {}
        if записи:
            строки.append(подпись + ":")
            строки += [f"  {иден} — {опис[:150]}" for иден, опис in записи.items()]
    return "\n".join(строки)


def собрать(сцена: dict, глобальное: dict) -> str:
    """Готовый текст одного кадра для вставки в Flow."""
    книга = глобальное.get("characters", {}) | глобальное.get("objects", {})
    описания = [книга[и] for и in сцена.get("characters", []) if и in книга]

    куски = [сцена.get("prompt", "").rstrip(". ")]
    if описания:
        куски.append(" ".join(описания))
    for поле in ("camera", "lighting", "continuity"):
        if сцена.get(поле):
            куски.append(сцена[поле].rstrip(". "))
    for поле in ("style", "environment"):
        if глобальное.get(поле):
            куски.append(глобальное[поле].rstrip(". "))
    запреты = ", ".join(x for x in (глобальное.get("negative", ""),
                                    сцена.get("negative", "")) if x)
    if запреты:
        куски.append(запреты)
    return ". ".join(к for к in куски if к) + "."


def render_md(project, глобальное: dict, сцены: list[dict]) -> str:
    строки = [f"# Промпты для Flow — {project.name}", ""]
    итого = sum(с["duration"] for с in сцены)
    строки.append(f"{итого:.0f} секунд, {len(сцены)} сцен. "
                  f"Стиль, окружение и запреты уже внутри каждого блока — "
                  f"копируй блок целиком.")
    строки.append("")
    for с in сцены:
        строки.append(f"## {с['scene']} · {с['start']}–{с['end']} "
                      f"({с['duration']:.0f} с) — {с.get('purpose', '')}")
        строки.append("")
        строки.append("```")
        строки.append(собрать(с, глобальное))
        строки.append("```")
        if с.get("audio"):
            строки.append(f"звук: {с['audio']}")
        строки.append("")
    return "\n".join(строки)


# --- страж тайны ---------------------------------------------------------
# Правила в задании модель выполняет через раз: на локальной 14B она всё равно
# рисовала «silhouette of a figure standing inside» там, где диктор говорит
# «в проёме кто-то стоит». Поэтому проверяем результат кодом, а не надеждой.

МАРКЕРЫ_ТАЙНЫ = ("кто-то", "кто то", "что-то", "что то", " оно ", "голос",
                 "фигура", "считают", "считает", "за спиной", "шаги",
                 "по имени", "someone", "something")

# Узкий список: «the man» — это сам рассказчик, его показывать можно.
# Спойлер — появление ВТОРОГО, того, кого диктор не называет.
СПОЙЛЕРЫ = ("figure", "silhouette", "apparition", "ghost", "phantom",
            "barefoot man", "barefoot person", "barefoot figure",
            "another man", "second man", "stranger", "shadowy")


ЛЮДИ = ("man", "person", "figure", "someone", "somebody", "human", "boy",
        "woman", "child")


def спойлер(реплика: str, промпт: str) -> str:
    """Возвращает найденное слово-спойлер или пустую строку."""
    if not any(м in реплика.lower() for м in МАРКЕРЫ_ТАЙНЫ):
        return ""
    низ = промпт.lower()
    for слово in СПОЙЛЕРЫ:
        if слово in низ:
            return слово
    # «barefoot man» и «man stands barefoot» — одно и то же, но подстрокой
    # ловится только первое. Смотрим на соседство слов, а не на порядок.
    if "barefoot" in низ and any(ч in низ for ч in ЛЮДИ):
        return "barefoot"
    return ""


БЕЗОПАСНО = ("The torch beam ends in darkness, nothing resolvable beyond it. "
             "Empty frame, no one visible.")


def без_спойлеров(сцены: list[dict], перегенерить) -> list[str]:
    """Чиним сцены, которые показывают разгадку раньше диктора."""
    остались = []
    for с in сцены:
        слово = спойлер(с.get("narration", ""), с.get("prompt", ""))
        if not слово:
            continue
        новый = перегенерить(с, слово)
        if новый and not спойлер(с.get("narration", ""), новый):
            с["prompt"] = новый
        else:
            с["prompt"] = БЕЗОПАСНО
            остались.append(str(с["scene"]))
        части = [x.strip() for x in
                 (с.get("negative", "") + ", no visible figure, no silhouette, "
                  "no second person, no face").split(",")]
        видели, чистые = set(), []
        for ч in части:                      # без задвоений: модель уже могла
            if ч and ч.lower() not in видели:  # запретить то же самое сама
                видели.add(ч.lower())
                чистые.append(ч)
        с["negative"] = ", ".join(чистые)
    return остались


def финал_без_якоря(сцены: list[dict], глобальное: dict) -> bool:
    """Последний кадр не зацепился ни за что из мира ролика.

    Проверяем не отсутствие нового, а наличие знакомого: «empty rails
    disappear into the snow» — честный финал, хотя слова там другие. А вот
    чашка кофе в тёплой комнате после восьми минут мороза не цепляется ни за
    окружение, ни за предметы, ни за один предыдущий кадр — и выбивает из
    атмосферы сильнее, чем плохо снятый план.
    """
    if len(сцены) < 2:
        return False

    def корни(текст: str) -> set[str]:
        # грубая нормализация: rails и railway должны считаться одним словом
        return {с[:4] for с in re.findall(r"[a-z]{4,}", (текст or "").lower())}

    мир = корни(глобальное.get("environment", "")) | корни(глобальное.get("style", ""))
    for о in (глобальное.get("objects") or {}).values():
        мир |= корни(о)
    for с in сцены[:-1]:
        мир |= корни(с.get("prompt", ""))

    # одно случайное совпадение — не якорь: «wooden table» цепляется за
    # «wooden barracks» из окружения, оставаясь чужой комнатой
    return len(мир & корни(сцены[-1].get("prompt", ""))) < 2


def run(project, force: bool = False) -> None:
    if not project.shotlist.exists():
        raise SystemExit(f"[flow] нет {project.shotlist} — сначала шаг shotlist")
    if project.flow.exists() and not force:
        print(f"[flow] пропуск, {project.flow.name} уже есть")
        return

    with project.shotlist.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("[flow] shotlist.csv пуст")

    # Раскадровка могла приехать из чужого инструмента: колонки другие, и без
    # проверки шаг падал бы посреди работы голым KeyError.
    нужны = {"scene", "duration", "visual"}
    не_хватает = нужны - set(rows[0])
    if не_хватает:
        raise SystemExit(
            f"[flow] в {project.shotlist.name} нет колонок: "
            f"{', '.join(sorted(не_хватает))}\n"
            f"  есть: {', '.join(rows[0])}\n"
            f"  пересобрать: vidpipe run -s shotlist --force"
        )

    assets = load_assets(project)
    книга = bible_step.load(project)
    герои = книга.get("CHARACTERS") or {}
    предметы = книга.get("OBJECTS") or {}
    if not герои:
        print("[flow] ! библии героев нет — генератор нарисует в каждом кадре "
              "нового человека. Сделай её: vidpipe run -s bible")

    print(f"[flow] {len(rows)} сцен, блоки ассетов: {', '.join(assets) or 'нет'}, "
          f"героев {len(герои)}, предметов {len(предметы)}")

    подсказка = справочник(книга)
    prompts: dict[int, dict] = {}
    batch = env_int("FLOW_BATCH", 15)
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        print(f"[flow] сцены {chunk[0]['scene']}–{chunk[-1]['scene']}")
        payload = "\n\n".join(
            f"Сцена {r['scene']} ({r['duration']} с):\n"
            f"Реплика диктора: {r.get('narration', r.get('beat', '—'))}\n"
            f"Визуал: {r['visual']}\n"
            f"Крупность: {r.get('shot_type') or r.get('camera', '—')} | "
            f"Движение: {r.get('motion') or r.get('camera', '—')} | "
            f"Атмосфера: {r.get('mood', '—')}"
            for r in chunk
        )
        if подсказка:
            payload = подсказка + "\n\n" + payload
        for r in complete_json(SYSTEM, payload, max_tokens=8000):
            if "scene" in r:
                prompts[int(r["scene"])] = r

    глобальное = {
        "style": assets.get("STYLE", ""),
        "environment": assets.get("ENV", ""),
        "negative": assets.get("NEGATIVE", ""),
        "characters": герои,
        "objects": предметы,
    }

    out, missing = [], []
    for r in rows:
        n = int(r["scene"])
        gen = prompts.get(n)
        if not gen:
            missing.append(n)
            continue
        известные = set(герои) | set(предметы)
        out.append({
            "scene": n,
            "start": r["start"],
            "end": r["end"],
            "duration": float(r["duration"]),
            "narration": r.get("narration", r.get("beat", "")),
            "purpose": gen.get("purpose", ""),
            "prompt": gen.get("prompt", ""),
            "characters": [и for и in gen.get("characters", []) if и in известные],
            "camera": gen.get("camera", r.get("motion", r.get("camera", ""))),
            "lighting": gen.get("lighting", ""),
            "continuity": gen.get("continuity", ""),
            "audio": gen.get("audio", ""),
            "negative": gen.get("negative", ""),
        })

    if missing:
        print(f"[flow] ! без промпта остались сцены: {missing}")

    def перегенерить(сцена, слово):
        приказ = (
            f"Промпт показывает то, что диктор оставляет неизвестным "
            f"(«{слово}»). Перепиши ТОЛЬКО визуальное действие: покажи то, что "
            f"видит рассказчик, — луч фонаря, пустой проём, рельсы, снег. "
            f"Ни фигуры, ни силуэта, ни второго человека в кадре."
        )
        полезное = (f"Реплика диктора: {сцена.get('narration', '')}\n"
                    f"Плохой промпт: {сцена.get('prompt', '')}")
        try:
            ответ = complete_json(f"{SYSTEM}\n\n{приказ}", полезное,
                                  max_tokens=600)
        except SystemExit:
            return ""
        if isinstance(ответ, list) and ответ:
            ответ = ответ[0]
        return ответ.get("prompt", "") if isinstance(ответ, dict) else ""

    if out and финал_без_якоря(out, глобальное):
        print(f"[flow] ! последний кадр не зацепился ни за что из мира ролика: "
              f"«{out[-1]['prompt'][:70]}»")
        print(f"[flow]   финал должен остаться в кадре, который зритель уже "
              f"знает: рельсы, дверь, пустая дорога. Перепиши сцену "
              f"{out[-1]['scene']} руками.")

    спорные = без_спойлеров(out, перегенерить)
    if спорные:
        print(f"[flow] ! разгадку показывали сцены {', '.join(спорные)} — "
              f"промпт заменён на безопасный, перепиши их руками")

    project.flow.write_text(
        json.dumps({"project": project.name, "scene_count": len(out),
                    "global": глобальное, "scenes": out},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    готовый = project.dir / "flow_prompts.md"
    готовый.write_text(render_md(project, глобальное, out), encoding="utf-8")

    без_героя = [с["scene"] for с in out if not с["characters"]]
    print(f"[flow] {project.flow.name}: {len(out)} промптов, "
          f"{готовый.name}: готовые блоки для вставки")
    if герои and без_героя:
        print(f"[flow]   кадров без людей: {len(без_героя)} — это нормально "
              f"для пустых планов, но проверь глазами")
