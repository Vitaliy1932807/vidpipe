"""Конфиг: проект = текущая папка, ресурсы ищутся по цепочке приоритетов.

Уровней четыре, ближний перекрывает дальний:

    папка ролика -> канал -> глобальный -> встроенный в пакет

Канал — это папка `.vidpipe-channel`, найденная поиском вверх по дереву от
папки ролика. В ней лежат свои `.env`, `script_engine.md` и `assets.md`: язык,
темп речи, голос и методика у каждого канала свои. Ключи API остаются в
глобальном `.env` — дублировать их по каналам не нужно.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

PACKAGE_ASSETS = Path(__file__).resolve().parent / "assets"
GLOBAL_DIR = Path(
    os.getenv("VIDPIPE_HOME") or (Path.home() / ".vidpipe")
)
CHANNEL_MARKER = ".vidpipe-channel"

FILES = {
    "prompt": "prompt.md",
    "script": "script.md",
    "review": "review.md",
    "voice_txt": "voice.txt",
    "voice_mp3": "voice.mp3",
    "srt": "subtitles.srt",
    "flow": "flow_prompts.json",
    "shotlist": "shotlist.csv",
    "thumbnail": "thumbnail.txt",
    "video": "video.mp4",
}


def find_channel(start: str | Path | None = None) -> Path | None:
    """Ищем канал: от `start` (по умолчанию текущей папки) поднимаемся к корню
    и берём первую найденную подпапку `.vidpipe-channel`.

    Возвращаем саму папку-маркер или None, если канала нет — тогда всё
    работает как раньше, на глобальном конфиге.
    """
    d = Path(start).expanduser().resolve() if start else Path.cwd()
    for candidate in (d, *d.parents):
        marker = candidate / CHANNEL_MARKER
        if marker.is_dir():
            return marker
    return None


def load_env(start: str | Path | None = None) -> None:
    """Глобальный ~/.vidpipe/.env, поверх него .env канала, поверх него
    локальный ./.env. Ближний уровень перекрывает дальний."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(GLOBAL_DIR / ".env", override=False)
    channel = find_channel(start)
    if channel:
        load_dotenv(channel / ".env", override=True)
    load_dotenv(Path.cwd() / ".env", override=True)


@dataclass
class Project:
    """Папка с материалами одного ролика. По умолчанию — текущая."""
    dir: Path
    channel: Path | None = None      # папка .vidpipe-channel, если нашлась

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Project":
        d = Path(path).expanduser().resolve() if path else Path.cwd()
        d.mkdir(parents=True, exist_ok=True)
        # канал ищем от папки ролика, а не от текущей: с `--dir ПУТЬ` ролик
        # может лежать в другом канале, чем тот, из которого запущена команда
        return cls(dir=d, channel=find_channel(d))

    @property
    def name(self) -> str:
        return self.dir.name

    @property
    def channel_root(self) -> Path | None:
        """Папка, в которой лежит маркер канала. Рядом с ней — series.jsonl."""
        return self.channel.parent if self.channel else None

    @property
    def channel_name(self) -> str:
        """Имя из CHANNEL_NAME, иначе имя папки канала."""
        if not self.channel:
            return ""
        return env("CHANNEL_NAME") or self.channel.parent.name

    def __getattr__(self, item: str) -> Path:
        if item in FILES:
            return self.dir / FILES[item]
        raise AttributeError(item)

    @property
    def tmp(self) -> Path:
        p = self.dir / ".vidpipe"
        p.mkdir(exist_ok=True)
        return p

    def resource(self, name: str) -> Path:
        """Ищем ресурс: папка ролика -> канал -> глобальный -> встроенный.

        Так один и тот же скилл работает во всех проектах, канал задаёт свою
        методику и стиль, а конкретный ролик может переопределить и это,
        положив файл рядом с собой.
        """
        chain = [self.dir / name, self.dir / "prompts" / name]
        if self.channel:
            chain.append(self.channel / name)
        chain += [GLOBAL_DIR / name, PACKAGE_ASSETS / name]
        for candidate in chain:
            if candidate.exists():
                return candidate
        raise SystemExit(f"[config] не найден ресурс {name}")

    def resource_source(self, name: str) -> str:
        path = self.resource(name)
        if path.is_relative_to(PACKAGE_ASSETS):
            return "встроенный"
        if self.channel and path.is_relative_to(self.channel):
            return "канал"
        if path.is_relative_to(GLOBAL_DIR):
            return "глобальный"
        return "локальный"


def read_text(path: Path) -> str:
    """Читаем файлы, которые правит человек. PowerShell и Блокнот ставят в
    начало BOM-метку; utf-8-sig снимает её, обычный utf-8 — нет, и она
    ломает разбор JSON и первую строку промпта."""
    return path.read_text(encoding="utf-8-sig")


def env(key: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(key, default)
    # dotenv не срезает комментарий у ПУСТОГО значения: `KEY=   # пояснение`
    # приезжает как "# пояснение". Считаем такое незаполненным.
    if val and val.lstrip().startswith("#"):
        val = default if default is not None else ""
    if required and not val:
        raise SystemExit(
            f"[config] не задана переменная {key}. "
            f"Пропиши её в {GLOBAL_DIR / '.env'}, в .env канала "
            f"({CHANNEL_MARKER}/.env) или в ./.env "
            f"(шаблоны: vidpipe init --global, vidpipe init --channel ИМЯ)"
        )
    return val or ""


def env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, "") or default)
    except ValueError:
        return default


def ffmpeg_bin() -> str:
    """Ищем ffmpeg: FFMPEG_BIN -> PATH -> бинарник из пакета imageio-ffmpeg.

    Последний вариант нужен на Windows без winget/choco: imageio-ffmpeg
    ставится обычным pip и тянет с собой готовый ffmpeg.exe.
    """
    explicit = os.getenv("FFMPEG_BIN")
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise SystemExit(
            "[config] ffmpeg не найден. Варианты:\n"
            "  pip install imageio-ffmpeg          — самый простой\n"
            "  укажи путь в FFMPEG_BIN внутри .env — если ffmpeg уже скачан"
        )
