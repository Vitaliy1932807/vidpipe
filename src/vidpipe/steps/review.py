"""Шаг: script.md -> review.md (+ правка script.md)

Второй вызов Claude в роли редактора. Автор и критик — разные роли: тот, кто
писал текст, склонен оправдывать свои решения, поэтому проверку делает
отдельный агент, которому дают методику и готовый сценарий, но не дают ТЗ.

Объём слов считается кодом и подаётся критику как факт: языковые модели плохо
считают, а требование по хронометражу жёсткое.
"""
from __future__ import annotations

import json

from ..config import read_prompt, env, env_int, read_text
from ..llm import complete, complete_json

CRITIC = """Ты — придирчивый редактор YouTube-канала. Тебе дают методику канала
и готовый сценарий закадрового голоса. Твоя задача — найти нарушения методики,
а не похвалить текст.

Правила проверки:
- Проверяй только то, что написано в методике. Своих вкусов не добавляй.
- Каждое замечание привязывай к конкретному правилу методики.
- Цитата из сценария — не длиннее десяти слов, только чтобы указать место.
- severity: critical — прямое нарушение запрета из методики; major — ослабляет
  удержание; minor — вкусовщина, можно оставить.
- Если сценарий соответствует методике, так и напиши: пустой список issues.
- Не выдумывай нарушений ради заполнения списка.

Верни JSON:
{"verdict": "pass" | "revise",
 "issues": [{"severity": "...", "rule": "какое правило нарушено",
             "where": "короткая цитата", "fix": "что конкретно изменить"}],
 "strengths": ["что работает хорошо"]}

verdict = "revise", только если есть хотя бы одно critical или major замечание."""

REVISER = """Ты — автор сценария. Тебе дают методику канала, свой текст и список
замечаний редактора. Внеси правки.

Правила:
- Исправляй только то, что указано в замечаниях. Остальной текст не переписывай.
- Не сокращай и не удлиняй сценарий больше чем на пять процентов.
- Сохрани язык, тон и голос рассказчика.
- Выведи только исправленный текст сценария целиком, без комментариев,
  заголовков и пояснений о том, что ты изменил."""


def _facts(project, text: str) -> str:
    """Детерминированные измерения — их критик не считает, а получает готовыми."""
    words = len(text.split())
    wpm = env_int("WORDS_PER_MIN")
    target = env_int("DEFAULT_DURATION_MIN")
    minutes = words / wpm
    drift = (minutes - target) / target * 100 if target else 0
    return (f"Измерено автоматически (это факты, пересчитывать не нужно):\n"
            f"- слов в сценарии: {words}\n"
            f"- темп речи: {wpm} слов/мин\n"
            f"- расчётный хронометраж: {minutes:.1f} мин\n"
            f"- целевой хронометраж: {target} мин\n"
            f"- отклонение: {drift:+.0f}%\n")


def critique(methodology: str, text: str, facts: str) -> dict:
    user = (f"МЕТОДИКА КАНАЛА:\n\n{methodology}\n\n"
            f"{'=' * 60}\n\n{facts}\n"
            f"{'=' * 60}\n\nСЦЕНАРИЙ:\n\n{text}")
    return complete_json(CRITIC, user, max_tokens=env_int("REVIEW_MAX_TOKENS", 4000))


def revise(methodology: str, text: str, issues: list[dict]) -> str:
    listed = "\n".join(
        f"- [{i['severity']}] {i.get('rule', '')}\n"
        f"  место: {i.get('where', '')}\n"
        f"  исправить: {i.get('fix', '')}"
        for i in issues
    )
    user = (f"МЕТОДИКА КАНАЛА:\n\n{methodology}\n\n"
            f"{'=' * 60}\n\nЗАМЕЧАНИЯ РЕДАКТОРА:\n\n{listed}\n\n"
            f"{'=' * 60}\n\nТЕКУЩИЙ СЦЕНАРИЙ:\n\n{text}")
    return complete(REVISER, user, max_tokens=env_int("SCRIPT_MAX_TOKENS"))


def _report(passes: list[dict], final: dict) -> str:
    lines = ["# Отчёт редактора\n"]
    for n, res in enumerate(passes, 1):
        issues = res.get("issues", [])
        lines.append(f"## Проход {n} — {res.get('verdict', '?')}, "
                     f"замечаний: {len(issues)}\n")
        for i in issues:
            lines.append(f"**[{i.get('severity')}]** {i.get('rule', '')}")
            if i.get("where"):
                lines.append(f"- место: {i['where']}")
            if i.get("fix"):
                lines.append(f"- исправить: {i['fix']}")
            lines.append("")
        if not issues:
            lines.append("Замечаний нет.\n")

    strengths = final.get("strengths") or []
    if strengths:
        lines.append("## Что работает\n")
        lines += [f"- {s}" for s in strengths]
        lines.append("")

    lines.append(f"## Итог\n\n**{final.get('verdict', '?')}**")
    return "\n".join(lines) + "\n"


def run(project, force: bool = False) -> None:
    if not project.script.exists():
        raise SystemExit(f"[review] нет {project.script} — сначала шаг script")
    if project.review.exists() and not force:
        print(f"[review] пропуск, {project.review.name} уже есть")
        return

    # У редактора может быть своя методика — например разбор удержания,
    # отдельный от методики написания. Нет своей — берём общую.
    methodology, источник = read_prompt(project, "review_engine.md",
                                        "script_engine.md")
    print(f"[review] методика: {источник}")
    text = read_text(project.script)
    max_passes = env_int("REVIEW_PASSES", 2)

    passes: list[dict] = []
    result: dict = {}

    for n in range(1, max_passes + 1):
        result = critique(methodology, text, _facts(project, text))
        passes.append(result)
        issues = [i for i in result.get("issues", [])
                  if i.get("severity") in ("critical", "major")]
        minor = len(result.get("issues", [])) - len(issues)
        print(f"[review] проход {n}: {result.get('verdict')}, "
              f"важных замечаний {len(issues)}, мелких {minor}")

        for i in issues:
            print(f"[review]   [{i.get('severity')}] {i.get('rule', '')[:70]}")

        if result.get("verdict") != "revise" or not issues:
            break
        if n == max_passes:
            print("[review] лимит проходов исчерпан, правки не вносились")
            break

        # бэкап предыдущей версии — вдруг правка окажется хуже оригинала
        (project.tmp / f"script_pass{n}.md").write_text(text, encoding="utf-8")
        text = revise(methodology, text, issues).strip() + "\n"
        project.script.write_text(text, encoding="utf-8")
        print(f"[review]   сценарий переписан, версия {n} сохранена в .vidpipe/")

    project.review.write_text(_report(passes, result), encoding="utf-8")
    print(f"[review] {project.review.name} готов")
