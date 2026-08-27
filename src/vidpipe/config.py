"""Конфиг: проект = текущая папка, ресурсы ищутся по цепочке приоритетов."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

PACKAGE_ASSETS = Path(__file__).resolve().parent / "assets"
GLOBAL_DIR = Path(
    os.getenv("VIDPIPE_HOME") or (Path.home() / ".vidpipe")
)

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


def load_env() -> None:
    """Сначала глобальный ~/.vidpipe/.env, потом локальный ./.env — локальный
    перекрывает. Уже заданные переменные окружения главнее обоих."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(GLOBAL_DIR / ".env", override=False)
    load_dotenv(Path.cwd() / ".env", override=True)


@dataclass
class Project:
    """Папка с материалами одного ролика. По умолчанию — текущая."""
    dir: Path

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Project":
        d = Path(path).expanduser().resolve() if path else Path.cwd()
        d.mkdir(parents=True, exist_ok=True)
        return cls(dir=d)

    @property
    def name(self) -> str:
        return self.dir.name

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
        """Ищем ресурс: папка проекта -> глобальный конфиг -> встроенный в пакет.

        Так один и тот же скилл работает во всех проектах, но конкретный ролик
        может переопределить его, положив файл рядом с собой.
        """
        for candidate in (self.dir / name,
                          self.dir / "prompts" / name,
                          GLOBAL_DIR / name,
                          PACKAGE_ASSETS / name):
            if candidate.exists():
                return candidate
        raise SystemExit(f"[config] не найден ресурс {name}")

    def resource_source(self, name: str) -> str:
        path = self.resource(name)
        if path.is_relative_to(PACKAGE_ASSETS):
            return "встроенный"
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
            f"Пропиши её в {GLOBAL_DIR / '.env'} или в ./.env "
            f"(шаблон: vidpipe init --global)"
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
