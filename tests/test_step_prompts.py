"""У каждого шага своя методика в канале, а не одна на всех."""
from __future__ import annotations

import pytest

from vidpipe.config import Project, prompt_body, read_prompt
from vidpipe.steps import research

from conftest import make_channel_dir

ДОКУМЕНТ = """# PACKAGING-ПРОМТ

> Как пользоваться: скопируй блок между `=== ПОЧАТОК ПРОМТА ===` и
> `=== КІНЕЦЬ ПРОМТА ===` в новый чат.

=== ПОЧАТОК ПРОМТА ===

## РОЛЬ

Ты продюсер-упаковщик. Придумай заголовки и обложки.

=== КІНЕЦЬ ПРОМТА ===

Дальше идут пояснения для человека, в модель им нельзя.
"""


def test_берётся_блок_промпта_а_не_весь_документ():
    тело = prompt_body(ДОКУМЕНТ)

    assert тело.startswith("## РОЛЬ")
    assert "продюсер-упаковщик" in тело
    assert "Как пользоваться" not in тело
    assert "пояснения для человека" not in тело


def test_маркеры_в_инструкции_не_сбивают_разбор():
    """Инструкция «скопируй блок между X и Y» сама содержит маркеры.

    Первая найденная пара тогда даёт пустышку в пару символов — берём самый
    длинный блок.
    """
    assert len(prompt_body(ДОКУМЕНТ)) > 40


def test_документ_без_маркеров_идёт_целиком():
    текст = "# МАСТЕР-ПРОМТ v3\n\nТы сценарист канала."

    assert prompt_body(текст) == текст


@pytest.mark.parametrize("начало,конец", [
    ("=== ПОЧАТОК ПРОМТА ===", "=== КІНЕЦЬ ПРОМТА ==="),
    ("=== НАЧАЛО ПРОМТА ===", "=== КОНЕЦ ПРОМТА ==="),
    ("=== START ===", "=== END ==="),
])
def test_понимаются_разные_маркеры(начало, конец):
    текст = f"шапка\n{начало}\nтело промпта достаточной длины\n{конец}\nхвост"

    assert prompt_body(текст) == "тело промпта достаточной длины"


def подготовить(tmp_path, **файлы):
    marker = make_channel_dir(tmp_path / "канал", CHANNEL_NAME="kb")
    for имя, текст in файлы.items():
        (marker / имя.replace("__", ".")).write_text(текст, encoding="utf-8")
    d = tmp_path / "канал" / "выпуск"
    d.mkdir()
    return Project.load(d)


def test_шаг_берёт_свою_методику(tmp_path, global_dir, clean_env):
    project = подготовить(tmp_path,
                          script_engine__md="общая методика",
                          review_engine__md="методика редактора")

    текст, откуда = read_prompt(project, "review_engine.md", "script_engine.md")

    assert текст == "методика редактора"
    assert "канал" in откуда


def test_без_своей_методики_берётся_запасная(tmp_path, global_dir, clean_env):
    """У редактора может не быть отдельного документа — тогда общая методика."""
    project = подготовить(tmp_path, script_engine__md="общая методика")

    текст, _ = read_prompt(project, "review_engine.md", "script_engine.md")

    assert текст == "общая методика"


def test_нет_ни_своей_ни_запасной(tmp_path, global_dir, clean_env):
    """Шаг должен уметь работать на встроенном промпте."""
    project = подготовить(tmp_path)

    текст, откуда = read_prompt(project, "packaging.md")

    assert текст == "" and откуда == ""


def test_ролик_может_переопределить_методику_шага(tmp_path, global_dir, clean_env):
    project = подготовить(tmp_path, packaging__md="канальная упаковка")
    (project.dir / "packaging.md").write_text("своя для этого ролика",
                                              encoding="utf-8")

    текст, откуда = read_prompt(project, "packaging.md")

    assert текст == "своя для этого ролика"
    assert "локальный" in откуда


# --- шаг research -------------------------------------------------------------

def test_research_помечает_досье_как_черновик(tmp_path, global_dir, clean_env,
                                              monkeypatch):
    """Модель отвечает по памяти: выдавать это за источник нельзя."""
    project = подготовить(tmp_path, research__md="промпт исследователя")
    project.prompt.write_text("ТЕМА: пожар в MGM Grand", encoding="utf-8")
    monkeypatch.setattr(research, "complete", lambda s, u, **k: "факт один")

    research.run(project)
    текст = (project.dir / "dossier.md").read_text(encoding="utf-8-sig")

    assert "сверь по первоисточникам" in текст
    assert "факт один" in текст


def test_research_без_темы_объясняет_что_делать(tmp_path, global_dir, clean_env):
    project = подготовить(tmp_path)

    with pytest.raises(SystemExit, match="init --topic"):
        research.run(project)


def test_сценарий_подхватывает_досье(tmp_path, global_dir, clean_env,
                                     monkeypatch):
    from vidpipe.steps import script_gen

    project = подготовить(tmp_path, script_engine__md="методика")
    project.prompt.write_text("ТЕМА: пожар", encoding="utf-8")
    (project.dir / "dossier.md").write_text("ФАКТ: 85 погибших", encoding="utf-8")

    увиденное = {}
    monkeypatch.setattr(script_gen, "complete",
                        lambda s, u, **k: увиденное.setdefault("user", u) and "" or "текст")
    script_gen.run(project)

    assert "ФАКТ: 85 погибших" in увиденное["user"]
