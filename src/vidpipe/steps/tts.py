"""Шаг 3: voice.txt -> voice.mp3

Озвучка через Voicer (voiceapi.csv666.ru). Вся работа — в voicer.py:
текст уходит одной задачей, сервис сам режет его на чанки.
"""
from __future__ import annotations

from ..config import read_text
from . import voicer


def run(project, force: bool = False) -> None:
    if not project.voice_txt.exists():
        raise SystemExit(f"[tts] нет {project.voice_txt} — сначала шаг clean")
    if project.voice_mp3.exists() and not force:
        print(f"[tts] пропуск, {project.voice_mp3.name} уже есть")
        return

    text = read_text(project.voice_txt)
    voicer.synthesize(project, text)

    mb = project.voice_mp3.stat().st_size / 1024 / 1024
    print(f"[tts] {project.voice_mp3.name}: {mb:.1f} МБ")
