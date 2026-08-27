"""Поиск голосов через GET /api/voices.

Отдаёт voice_id и public_owner_id — ровно то, что нужно вписать в .env.
"""
from __future__ import annotations

from .config import env
from .steps.voicer import _base, _headers, _fail

import requests


def search(query: str | None = None, library: str = "public",
           voice_id: str | None = None, gender: str | None = None,
           language: str | None = None, sort: str | None = None,
           limit: int = 15) -> list[dict]:
    params: dict[str, str | int] = {"library": library, "page_size": limit}
    if voice_id:
        params["voice_id"] = voice_id
    elif query:
        params["search"] = query
    for key, val in (("gender", gender), ("required_languages", language),
                     ("sort", sort)):
        if val:
            params[key] = val

    r = requests.get(f"{_base()}/api/voices", headers=_headers(),
                     params=params, timeout=60)
    if r.status_code != 200:
        _fail(r)
    return r.json().get("voices", [])


def _row(v: dict) -> str:
    name = (v.get("name") or "—")[:22]
    vid = v.get("voice_id") or v.get("id") or "—"
    owner = v.get("public_owner_id")
    meta = " / ".join(str(v[k]) for k in ("gender", "accent", "age", "category")
                      if v.get(k))
    tail = f"  owner: {owner}" if owner else ""
    return f"  {name:<22} {vid:<24} {meta}{tail}"


def cmd_voices(args) -> None:
    if not env("VOICER_API_KEY"):
        raise SystemExit("[voices] не задан VOICER_API_KEY — впиши его в .env")

    voices = search(query=args.search, library=args.library,
                    voice_id=args.voice_id, gender=args.gender,
                    language=args.lang, sort=args.sort, limit=args.limit)
    if not voices:
        print("[voices] ничего не найдено. Попробуй другой запрос "
              "или --library standard")
        return

    print(f"библиотека: {args.library}, найдено: {len(voices)}\n")
    print(f"  {'ИМЯ':<22} {'VOICE_ID':<24} ПАРАМЕТРЫ")
    for v in voices:
        print(_row(v))

    first = voices[0]
    vid = first.get("voice_id") or first.get("id")
    owner = first.get("public_owner_id")
    print(f"\nчтобы использовать первый — впиши в .env:")
    print(f"  VOICER_VOICE_ID={vid}")
    if owner:
        print(f"  VOICER_PUBLIC_OWNER_ID={owner}")
    else:
        print(f"  VOICER_PUBLIC_OWNER_ID=          # голос штатный, поле не нужно")
    print("\nНайденный public_owner_id сохрани в .env и не ищи этот голос "
          "повторно — сервис просит не злоупотреблять поиском.")
