"""Провайдер Voicer (voiceapi.csv666.ru) — асинхронный TTS в три шага.

    POST /tasks              -> task_id
    GET  /tasks/{id}/status  -> ждём статус ending
    GET  /tasks/{id}/result  -> mp3 (или zip с чанками)

Текст уходит ОДНОЙ задачей: жёсткого лимита длины у сервиса нет, он сам режет
на чанки. Дробить самому невыгодно — минимальный заказ 500 символов
списывается за каждую задачу отдельно.
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import time
import zipfile
from pathlib import Path

import requests

from ..config import env, env_int, ffmpeg_bin

RETRYABLE = {429, 500, 502, 503, 504}


def _base() -> str:
    return env("VOICER_BASE_URL", "https://voiceapi.csv666.ru").rstrip("/")


def _headers() -> dict[str, str]:
    return {"X-API-Key": env("VOICER_API_KEY", required=True),
            "Content-Type": "application/json"}


def _fail(r: requests.Response) -> None:
    """У сервиса единый двуязычный конверт ошибки — вытаскиваем русский текст."""
    try:
        data = r.json()
        detail = data.get("detail")
        msg = detail.get("ru") if isinstance(detail, dict) else detail
        code = data.get("error_code", "")
        raise SystemExit(f"[voicer] {r.status_code} {code}: {msg}")
    except (ValueError, AttributeError):
        raise SystemExit(f"[voicer] HTTP {r.status_code}: {r.text[:300]}")


def _get(path: str, **kw) -> requests.Response:
    for attempt in range(4):
        r = requests.get(f"{_base()}{path}", headers=_headers(), timeout=120, **kw)
        if r.status_code in RETRYABLE:
            print(f"[voicer]   {r.status_code}, повтор через {3 * (attempt + 1)} с")
            time.sleep(3 * (attempt + 1))
            continue
        return r
    return r


def build_template() -> dict | None:
    """Инлайн-шаблон собираем только из заданных полей: сервис подставит
    свои значения по умолчанию для остальных."""
    voice_settings = {}
    for key, name in (("VOICER_STABILITY", "stability"),
                      ("VOICER_SIMILARITY", "similarity_boost"),
                      ("VOICER_STYLE", "style"),
                      ("VOICER_SPEED", "speed")):
        raw = env(key)
        if raw:
            voice_settings[name] = float(raw)

    template = {}
    if voice_id := env("VOICER_VOICE_ID"):
        template["voice_id"] = voice_id
    if owner := env("VOICER_PUBLIC_OWNER_ID"):
        template["public_owner_id"] = owner
    if model := env("VOICER_MODEL_ID"):
        template["model_id"] = model
    if engine := env("VOICER_ENGINE"):
        template["voice_engine"] = engine
    if voice_settings:
        template["voice_settings"] = voice_settings
    return template or None


def create_task(text: str) -> int:
    body: dict = {"text": text}

    # template_uuid и template взаимоисключающие — иначе 422
    if uuid := env("VOICER_TEMPLATE_UUID"):
        body["template_uuid"] = uuid
        print("[voicer] настройки: шаблон " + uuid)
    elif template := build_template():
        body["template"] = template
        print(f"[voicer] настройки: голос {template.get('voice_id', 'по умолчанию')}, "
              f"модель {template.get('model_id', 'по умолчанию')}")
    else:
        print("[voicer] настройки: по умолчанию (голос не задан)")

    if chunk := env("VOICER_CHUNK_SIZE"):
        body["chunk_size"] = int(chunk)

    r = requests.post(f"{_base()}/tasks", headers=_headers(), json=body, timeout=120)
    if r.status_code != 200:
        _fail(r)
    data = r.json()
    print(f"[voicer] задача {data['task_id']}: {data.get('message', '')}")
    return int(data["task_id"])


def wait_ready(task_id: int) -> None:
    poll = env_int("VOICER_POLL_SEC", 10)
    deadline = time.time() + env_int("VOICER_TIMEOUT_MIN", 60) * 60
    last = None

    while time.time() < deadline:
        r = _get(f"/tasks/{task_id}/status")
        if r.status_code != 200:
            _fail(r)
        data = r.json()
        status = data.get("status")

        if status != last:
            print(f"[voicer] статус: {data.get('status_label') or status}")
            last = status

        if status in ("ending", "ending_processed"):
            return
        if status in ("error", "error_handled"):
            err = data.get("error") or {}
            raise SystemExit(f"[voicer] задача провалилась "
                             f"[{err.get('code', '')}]: {err.get('ru', 'без деталей')}")
        time.sleep(poll)

    raise SystemExit(f"[voicer] задача {task_id} не завершилась за отведённое время. "
                     f"Она осталась на сервере — запусти шаг tts снова, "
                     f"повторно платить не придётся")


def download(task_id: int, out: Path, tmp: Path) -> None:
    r = _get(f"/tasks/{task_id}/result")
    if r.status_code != 200:
        _fail(r)

    ctype = r.headers.get("Content-Type", "")
    if "zip" in ctype:
        # voice_result_type=chunks отдаёт архив — склеиваем куски по порядку
        parts = []
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            names = sorted(n for n in z.namelist() if n.lower().endswith(".mp3"))
            if not names:
                raise SystemExit("[voicer] в архиве нет mp3")
            for i, name in enumerate(names, 1):
                p = tmp / f"chunk_{i:03d}.mp3"
                p.write_bytes(z.read(name))
                parts.append(p)
        print(f"[voicer] архив: {len(parts)} чанков, склеиваю")
        listing = tmp / "concat.txt"
        listing.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in parts),
                           encoding="utf-8")
        subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-c", "copy", str(out)], check=True)
    else:
        out.write_bytes(r.content)

    if out.stat().st_size < 1024:
        raise SystemExit(f"[voicer] подозрительно маленький файл: {out.stat().st_size} б")


def balance() -> str:
    r = _get("/balance")
    if r.status_code != 200:
        return f"ошибка {r.status_code}"
    d = r.json()
    return d.get("balance_text") or str(d.get("balance", "?"))


def synthesize(project, text: str) -> None:
    """Задача кэшируется по хэшу текста: если прогон оборвался на ожидании,
    повторный запуск дождётся ту же задачу, а не создаст платную копию."""
    cache = project.tmp / "voicer_task.json"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    task_id = None
    if cache.exists():
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if saved.get("hash") == digest:
                task_id = int(saved["task_id"])
                print(f"[voicer] найдена начатая задача {task_id}, продолжаю её")
        except Exception:  # noqa: BLE001
            pass

    if task_id is None:
        print(f"[voicer] текст: {len(text)} символов")
        task_id = create_task(text)
        cache.write_text(json.dumps({"task_id": task_id, "hash": digest}),
                         encoding="utf-8")

    wait_ready(task_id)
    download(task_id, project.voice_mp3, project.tmp)
