"""Общий клиент модели для шагов, где надо думать.

Три провайдера, переключаются переменной LLM_PROVIDER:

    anthropic  — Claude по ключу (по умолчанию)
    ollama     — локальная модель, без ключей и без интернета
    openai     — любой OpenAI-совместимый эндпоинт: LM Studio, vLLM,
                 OpenRouter, DeepSeek и прочие

Шаги про провайдера ничего не знают: они зовут complete() и complete_json().
"""
from __future__ import annotations

import json
import re
import time

import requests

from .config import env, env_int

RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}

# Локальная модель на 12 ГБ видеопамяти отвечает минутами, а не секундами —
# особенно на первом запросе, пока веса грузятся с диска в видеопамять.
TIMEOUT = {"anthropic": 600, "openai": 600, "ollama": 1800}


def provider() -> str:
    return env("LLM_PROVIDER", "anthropic").strip().lower()


def _temperature() -> float:
    try:
        return float(env("LLM_TEMPERATURE", "0.8"))
    except ValueError:
        return 0.8


ОКНА = (4096, 8192, 12288, 16384, 24576, 32768, 49152, 65536)


def context_window(system: str, user: str, max_tokens: int) -> int:
    """Подбираем окно контекста под конкретный запрос.

    Одним числом это не задать. Слишком маленькое окно молча срежет задание;
    слишком большое навсегда отнимает видеопамять, и модель уезжает считать
    на процессор — на 12 ГБ разница между окном 8192 и 16384 это 100% GPU
    против 85%, то есть вдвое дольше на каждом шаге.

    OLLAMA_CTX здесь — потолок, а не значение. OLLAMA_RESERVE — сколько
    токенов заложить под ответ: шаги просят max_tokens с большим запасом,
    и закладывать его целиком значит резервировать пустоту.
    """
    потолок = env_int("OLLAMA_CTX", 16384)
    резерв = env_int("OLLAMA_RESERVE", 4096)
    # кириллица у Qwen — примерно 2.5 символа на токен, берём с запасом
    вход = int((len(system) + len(user)) / 2.5)
    if вход + 512 > потолок:
        print(f"[llm] промпт ~{вход} токенов не помещается в окно {потолок}: "
              f"часть задания модель не увидит. Подними OLLAMA_CTX.")
    нужно = вход + min(max_tokens, резерв) + 512
    for окно in ОКНА:
        if окно >= нужно:
            return min(окно, потолок)
    return потолок


def build(system: str, user: str, max_tokens: int,
          model: str | None = None, name: str | None = None) -> tuple:
    """Собираем запрос под конкретного провайдера: (url, headers, payload).

    Вынесено отдельно от отправки, чтобы это можно было проверить тестами,
    не поднимая ни сети, ни локального сервера.
    """
    name = name or provider()
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]

    if name == "anthropic":
        url = env("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        headers = {
            "x-api-key": env("ANTHROPIC_API_KEY", required=True),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model or env("ANTHROPIC_MODEL", "claude-sonnet-5"),
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        return url, headers, payload

    if name == "ollama":
        url = env("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/api/chat"
        payload = {
            "model": model or env("OLLAMA_MODEL", "qwen2.5:14b-instruct"),
            "messages": messages,
            "stream": False,
            # Сколько модель висит в видеопамяти после ответа. На карте, где
            # тем же местом пользуется whisper на large-v3, дефолтные пять
            # минут означают драку за память на шаге srt.
            "keep_alive": env("OLLAMA_KEEP_ALIVE", "30s"),
            "options": {
                # По умолчанию Ollama даёт 2048 токенов: методика канала
                # туда не влезет и обрежется молча. Считаем окно под запрос.
                "num_ctx": context_window(system, user, max_tokens),
                "num_predict": max_tokens,
                "temperature": _temperature(),
            },
        }
        return url, {"content-type": "application/json"}, payload

    if name == "openai":
        url = env("OPENAI_BASE_URL", "http://localhost:1234/v1").rstrip("/") + "/chat/completions"
        headers = {"content-type": "application/json"}
        key = env("OPENAI_API_KEY")
        if key:                       # локальным серверам ключ не нужен
            headers["Authorization"] = f"Bearer {key}"
        payload = {
            "model": model or env("OPENAI_MODEL", "local-model"),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": _temperature(),
        }
        return url, headers, payload

    raise SystemExit(
        f"[llm] неизвестный LLM_PROVIDER={name!r}. "
        f"Доступны: anthropic, ollama, openai"
    )


def extract(data: dict, name: str | None = None) -> str:
    """Достаём текст ответа: у каждого провайдера своя форма."""
    name = name or provider()
    if name == "anthropic":
        return "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text").strip()
    if name == "ollama":
        return (data.get("message") or {}).get("content", "").strip()
    if name == "openai":
        choices = data.get("choices") or [{}]
        return (choices[0].get("message") or {}).get("content", "").strip()
    return ""


def complete(system: str, user: str, max_tokens: int = 8000,
             model: str | None = None) -> str:
    name = provider()
    url, headers, payload = build(system, user, max_tokens, model, name)

    last = None
    for attempt in range(env_int("LLM_RETRIES", 3)):
        try:
            r = requests.post(url, headers=headers, json=payload,
                              timeout=TIMEOUT.get(name, 600))
            if r.status_code >= 400 and r.status_code not in RETRYABLE:
                # 401/403/400 сами не пройдут — не тратим попытки
                raise SystemExit(f"[llm] HTTP {r.status_code}: {r.text[:300]}")
            r.raise_for_status()
            data = r.json()
            text = extract(data, name)
            if not text:
                raise RuntimeError(f"пустой ответ: {json.dumps(data)[:300]}")
            return text
        except requests.ConnectionError as e:
            if name in ("ollama", "openai"):
                raise SystemExit(
                    f"[llm] {name}: сервер не отвечает на {url}.\n"
                    f"  запусти его (для Ollama: ollama serve) или проверь "
                    f"{'OLLAMA_BASE_URL' if name == 'ollama' else 'OPENAI_BASE_URL'}"
                ) from e
            last = e
            print(f"[llm]   попытка {attempt + 1}: {e}")
            time.sleep(3 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"[llm]   попытка {attempt + 1}: {e}")
            time.sleep(3 * (attempt + 1))
    raise SystemExit(f"[llm] запрос не прошёл: {last}")


def complete_json(system: str, user: str, max_tokens: int = 8000,
                  model: str | None = None):
    """То же, но с разбором JSON. Снимает ```-обёртку, если модель её добавила."""
    raw = complete(system + "\n\nОтвечай ТОЛЬКО валидным JSON, без пояснений "
                          "и без markdown-обёртки.", user, max_tokens, model)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.M)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # запасной вариант: выдернуть самый внешний массив или объект
        m = re.search(r"(\[.*\]|\{.*\})", cleaned, re.S)
        if not m:
            raise SystemExit(f"[llm] ответ не разобрался как JSON:\n{cleaned[:500]}")
        return json.loads(m.group(1))
