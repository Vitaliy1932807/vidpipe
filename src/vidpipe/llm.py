"""Общий клиент модели для шагов, где надо думать.

Два провайдера, переключаются переменной LLM_PROVIDER:

    anthropic  — Claude по ключу (по умолчанию)
    openai     — любой OpenAI-совместимый эндпоинт: LM Studio, vLLM,
                 OpenRouter, DeepSeek и прочие

Локальная модель через Ollama здесь была и убрана. Замер на живом выпуске:
14B писала промпты, которые приходилось переписывать целиком, а приёмку
сценария прошла с пятью находками, верными ноль. Если локальная модель всё же
нужна, её поднимают LM Studio или vLLM и подключают как openai по адресу
OPENAI_BASE_URL: ключ таким серверам не нужен, и отдельный провайдер под это
не требуется.

Шаги про провайдера ничего не знают: они зовут complete() и complete_json().
"""
from __future__ import annotations

import json
import re
import time

import requests

from .config import env, env_int

RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}

# Локальный сервер на своей видеокарте отвечает минутами, а не секундами,
# особенно на первом запросе, пока веса грузятся с диска в видеопамять.
TIMEOUT = {"anthropic": 600, "openai": 600}


def provider() -> str:
    """anthropic, openai или none.

    none означает, что модели нет и не предполагается: шаги, которым нужно
    думать, тогда не падают с ошибкой сети, а честно говорят, что этот текст
    пишет человек, и отдают заготовку под руку.
    """
    return env("LLM_PROVIDER", "anthropic").strip().lower()


НЕТ_МОДЕЛИ = "none"


def без_модели() -> bool:
    return provider() in (НЕТ_МОДЕЛИ, "", "нет")


def _temperature() -> float:
    try:
        return float(env("LLM_TEMPERATURE", "0.8"))
    except ValueError:
        return 0.8


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
        f"Доступны: anthropic, openai, none"
    )


def extract(data: dict, name: str | None = None) -> str:
    """Достаём текст ответа: у каждого провайдера своя форма."""
    name = name or provider()
    if name == "anthropic":
        return "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text").strip()
    if name == "openai":
        choices = data.get("choices") or [{}]
        return (choices[0].get("message") or {}).get("content", "").strip()
    return ""


def readiness() -> str:
    """Пустая строка, если модель доступна, иначе объяснение для человека.

    Нужно автоматизации: упасть до создания папки выпуска дешевле, чем на
    первом шаге конвейера, уже съев номер.
    """
    name = provider()
    if без_модели():
        return "модель не настроена: LLM_PROVIDER=none"
    if name == "anthropic":
        if env("ANTHROPIC_API_KEY"):
            return ""
        return ("не задан ANTHROPIC_API_KEY (или подними свой сервер "
                "и поставь LLM_PROVIDER=openai)")
    url, _, _ = build("проверка", "проверка", 8, name=name)
    корень = url.split("/v1/")[0]
    try:
        requests.get(корень, timeout=5)
        return ""
    except Exception:  # noqa: BLE001
        return f"{name}: сервер не отвечает на {корень} — запусти его"


def complete(system: str, user: str, max_tokens: int = 8000,
             model: str | None = None) -> str:
    name = provider()
    if без_модели():
        raise SystemExit(
            "[llm] модель не настроена (LLM_PROVIDER=none). Этот шаг думает, "
            "а не считает, и его результат пишется руками."
        )
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
            if name == "openai":
                raise SystemExit(
                    f"[llm] {name}: сервер не отвечает на {url}.\n"
                    f"  запусти его или проверь OPENAI_BASE_URL"
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
