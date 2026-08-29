"""Переключение провайдера модели: anthropic / openai.

Сеть здесь не нужна: проверяем сборку запроса и разбор ответа.
"""
from __future__ import annotations

import os

import pytest

from vidpipe import llm


def test_по_умолчанию_anthropic(clean_env):
    os.environ["ANTHROPIC_API_KEY"] = "ключ"

    url, headers, payload = llm.build("система", "запрос", 4000)

    assert llm.provider() == "anthropic"
    assert url.endswith("/v1/messages")
    assert headers["x-api-key"] == "ключ"
    assert payload["system"] == "система"
    assert payload["max_tokens"] == 4000


def test_openai_совместимый_без_ключа_и_с_ключом(clean_env):
    os.environ["LLM_PROVIDER"] = "openai"

    _, headers, _ = llm.build("с", "u", 100)
    assert "Authorization" not in headers      # LM Studio, vLLM — ключ не нужен

    os.environ["OPENAI_API_KEY"] = "sk-тест"
    _, headers, _ = llm.build("с", "u", 100)
    assert headers["Authorization"] == "Bearer sk-тест"


def test_неизвестный_провайдер_останавливает_работу(clean_env):
    os.environ["LLM_PROVIDER"] = "gigachat"

    with pytest.raises(SystemExit, match="неизвестный LLM_PROVIDER"):
        llm.build("с", "u", 100)


def test_снятый_провайдер_не_воскресает_молча(clean_env):
    """Ollama убрана. Старый .env не должен уводить шаг в несуществующее."""
    os.environ["LLM_PROVIDER"] = "ollama"

    with pytest.raises(SystemExit, match="неизвестный LLM_PROVIDER"):
        llm.build("с", "u", 100)


@pytest.mark.parametrize("name,ответ", [
    ("anthropic", {"content": [{"type": "text", "text": "готовый сценарий"}]}),
    ("openai", {"choices": [{"message": {"content": "готовый сценарий"}}]}),
])
def test_ответ_разбирается_у_каждого_провайдера(name, ответ, clean_env):
    assert llm.extract(ответ, name) == "готовый сценарий"


def test_смена_провайдера_не_требует_правок_в_шагах(clean_env):
    """Шаги зовут complete(); всё различие провайдеров живёт в llm.py."""
    import inspect

    from vidpipe.steps import flow, script_gen, shotlist, thumbnail

    for модуль in (script_gen, shotlist, flow, thumbnail):
        исходник = inspect.getsource(модуль)
        assert "ANTHROPIC" not in исходник, f"{модуль.__name__} знает про провайдера"
        assert "api.anthropic" not in исходник