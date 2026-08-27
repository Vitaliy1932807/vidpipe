"""Порядок .env: глобальный -> канал -> папка ролика."""
from __future__ import annotations

import os

from vidpipe.config import env, load_env

from conftest import make_channel_dir


def write_env(path, **values):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_канал_перекрывает_глобальный(tmp_path, global_dir, clean_env, monkeypatch):
    write_env(global_dir / ".env", WORDS_PER_MIN="150", WHISPER_LANG="ru",
              ANTHROPIC_API_KEY="ключ-из-глобального")
    channel = make_channel_dir(tmp_path / "hindi",
                               WORDS_PER_MIN="147", WHISPER_LANG="hi")
    video = tmp_path / "hindi" / "выпуск"
    video.mkdir()
    monkeypatch.chdir(video)

    load_env(video)

    assert env("WORDS_PER_MIN") == "147"
    assert env("WHISPER_LANG") == "hi"
    # ключи по каналам не дублируются — приезжают из глобального
    assert env("ANTHROPIC_API_KEY") == "ключ-из-глобального"
    assert channel.exists()


def test_папка_ролика_перекрывает_канал(tmp_path, global_dir, clean_env, monkeypatch):
    write_env(global_dir / ".env", WORDS_PER_MIN="150")
    make_channel_dir(tmp_path / "hindi", WORDS_PER_MIN="147")
    video = tmp_path / "hindi" / "выпуск"
    video.mkdir()
    write_env(video / ".env", WORDS_PER_MIN="120")
    monkeypatch.chdir(video)

    load_env(video)

    assert env("WORDS_PER_MIN") == "120"


def test_два_канала_дают_разные_настройки(tmp_path, global_dir, clean_env,
                                          monkeypatch):
    write_env(global_dir / ".env", DEFAULT_LANG="русский")
    make_channel_dir(tmp_path / "hindi", DEFAULT_LANG="Hindi")
    make_channel_dir(tmp_path / "eng", DEFAULT_LANG="English")
    for name in ("hindi", "eng"):
        (tmp_path / name / "выпуск").mkdir()

    monkeypatch.chdir(tmp_path / "hindi" / "выпуск")
    load_env(tmp_path / "hindi" / "выпуск")
    assert env("DEFAULT_LANG") == "Hindi"

    # второй канал в том же процессе: значение должно смениться
    monkeypatch.chdir(tmp_path / "eng" / "выпуск")
    load_env(tmp_path / "eng" / "выпуск")
    assert env("DEFAULT_LANG") == "English"


def test_без_канала_работает_глобальный(tmp_path, global_dir, clean_env,
                                        monkeypatch):
    write_env(global_dir / ".env", WORDS_PER_MIN="150")
    video = tmp_path / "старый-ролик"
    video.mkdir()
    monkeypatch.chdir(video)

    load_env(video)

    assert env("WORDS_PER_MIN") == "150"


def test_пустое_значение_с_комментарием_считается_незаполненным(clean_env):
    os.environ["VOICER_VOICE_ID"] = "# сюда впиши id"

    assert env("VOICER_VOICE_ID") == ""
    assert env("VOICER_VOICE_ID", "запасной") == "запасной"


def test_имя_канала_из_env_иначе_из_папки(tmp_path, global_dir, clean_env,
                                          monkeypatch):
    from vidpipe.config import Project

    make_channel_dir(tmp_path / "папка-канала", CHANNEL_NAME="hindi-horror")
    video = tmp_path / "папка-канала" / "выпуск"
    video.mkdir()
    monkeypatch.chdir(video)
    load_env(video)

    assert Project.load(video).channel_name == "hindi-horror"

    del os.environ["CHANNEL_NAME"]
    assert Project.load(video).channel_name == "папка-канала"
