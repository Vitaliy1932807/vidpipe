"""Общая обвязка тестов.

Тесты трогают самое хрупкое место конвейера — разрешение путей. Поэтому они
не должны зависеть ни от настоящего ~/.vidpipe, ни от переменных окружения
разработчика: и глобальный конфиг, и os.environ подменяются на время теста.
"""
from __future__ import annotations

import os

import pytest

from vidpipe import config

# префиксы переменных, которые конвейер читает из .env
PREFIXES = ("VIDPIPE_", "CHANNEL_", "SERIES_", "DEFAULT_", "WORDS_",
            "WHISPER_", "FW_", "VOICER_", "ANTHROPIC_", "SCENE_", "CLIPS_")


@pytest.fixture
def clean_env():
    """os.environ до теста и после — один и тот же.

    monkeypatch.setenv тут не поможет: load_dotenv пишет в os.environ напрямую,
    и его записи иначе протекли бы в соседние тесты.
    """
    saved = dict(os.environ)
    for key in list(os.environ):
        if key.startswith(PREFIXES):
            del os.environ[key]
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture
def global_dir(tmp_path, monkeypatch):
    """Подменяем ~/.vidpipe на пустую временную папку."""
    d = tmp_path / "global"
    d.mkdir()
    monkeypatch.setattr(config, "GLOBAL_DIR", d)
    return d


def make_channel_dir(root, **env_values):
    """Готовим канал вручную, без CLI: папка-маркер и .env с настройками."""
    marker = root / config.CHANNEL_MARKER
    marker.mkdir(parents=True, exist_ok=True)
    if env_values:
        lines = [f"{k}={v}" for k, v in env_values.items()]
        (marker / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return marker
