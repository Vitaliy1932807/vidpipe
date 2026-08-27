"""Переключение провайдера модели: anthropic / ollama / openai.

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


def test_ollama_работает_без_ключей(clean_env):
    """Ключей в окружении нет вообще — локальный провайдер не должен их просить."""
    os.environ["LLM_PROVIDER"] = "ollama"

    url, headers, payload = llm.build("методика", "сценарий", 6000)

    assert url == "http://localhost:11434/api/chat"
    assert "Authorization" not in headers and "x-api-key" not in headers
    assert payload["messages"][0] == {"role": "system", "content": "методика"}
    assert payload["messages"][1] == {"role": "user", "content": "сценарий"}
    assert payload["stream"] is False


def test_ollama_поднимает_окно_контекста(clean_env):
    """2048 токенов по умолчанию не вместят методику — она обрежется молча."""
    os.environ["LLM_PROVIDER"] = "ollama"

    _, _, payload = llm.build("методика", "сценарий", 6000)

    assert payload["options"]["num_ctx"] == 16384
    assert payload["options"]["num_predict"] == 6000

    os.environ["OLLAMA_CTX"] = "32768"
    _, _, payload = llm.build("методика", "сценарий", 6000)
    assert payload["options"]["num_ctx"] == 32768


def test_ollama_модель_и_адрес_настраиваются(clean_env):
    os.environ.update({"LLM_PROVIDER": "ollama",
                       "OLLAMA_BASE_URL": "http://192.168.1.50:11434/",
                       "OLLAMA_MODEL": "qwen2.5:32b"})

    url, _, payload = llm.build("с", "u", 100)

    assert url == "http://192.168.1.50:11434/api/chat"
    assert payload["model"] == "qwen2.5:32b"


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


@pytest.mark.parametrize("name,ответ", [
    ("anthropic", {"content": [{"type": "text", "text": "готовый сценарий"}]}),
    ("ollama", {"message": {"role": "assistant", "content": "готовый сценарий"}}),
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


def test_ollama_выгружает_модель_из_видеопамяти(clean_env):
    """Иначе модель висит пять минут и мешает whisper на шаге srt."""
    os.environ["LLM_PROVIDER"] = "ollama"

    _, _, payload = llm.build("с", "u", 100)
    assert payload["keep_alive"] == "30s"

    os.environ["OLLAMA_KEEP_ALIVE"] = "10m"
    _, _, payload = llm.build("с", "u", 100)
    assert payload["keep_alive"] == "10m"
