"""Общий клиент Anthropic API для шагов, где думает Claude."""
from __future__ import annotations

import json
import re
import time

import requests

from .config import env, env_int

RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}


def _api_url() -> str:
    """Считаем при вызове, а не на импорте: .env подгружается позже импортов."""
    return env("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/") + "/v1/messages"


def complete(system: str, user: str, max_tokens: int = 8000,
             model: str | None = None) -> str:
    key = env("ANTHROPIC_API_KEY", required=True)
    model = model or env("ANTHROPIC_MODEL", "claude-sonnet-5")

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    last = None
    for attempt in range(env_int("LLM_RETRIES", 3)):
        try:
            r = requests.post(_api_url(), headers=headers, json=payload, timeout=600)
            if r.status_code >= 400 and r.status_code not in RETRYABLE:
                # 401/403/400 сами не пройдут — не тратим попытки
                raise SystemExit(f"[llm] HTTP {r.status_code}: {r.text[:300]}")
            r.raise_for_status()
            data = r.json()
            text = "".join(b.get("text", "") for b in data.get("content", [])
                           if b.get("type") == "text").strip()
            if not text:
                raise RuntimeError(f"пустой ответ: {json.dumps(data)[:300]}")
            return text
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
