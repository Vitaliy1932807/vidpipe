"""CLI: vidpipe. Работает в текущей папке."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .config import (CHANNEL_MARKER, GLOBAL_DIR, PACKAGE_ASSETS, Project,
                     env, ffmpeg_bin, find_channel, find_channels,
                     load_env)
from .steps import (assemble, bible, clean, flow, research, review,
                    script_gen, shotlist, thumbnail, transcribe, tts)
from . import __version__
from .series import cmd_series
from .checks import postflight
from .approve import cmd_ok
from .clips import cmd_clips
from .validate import cmd_doctor, preflight
from .voices import cmd_voices

STEPS = {
    "research": ("тема -> dossier.md: досье фактов",   research.run),
    "script":   ("prompt.md -> script.md",            script_gen.run),
    "review":   ("проверка сценария по методике",     review.run),
    "clean":    ("script.md -> voice.txt",            clean.run),
    "tts":      ("voice.txt -> voice.mp3",            tts.run),
    "srt":      ("voice.mp3 -> subtitles.srt",        transcribe.run),
    "bible":    ("script.md -> bible.md: герои и предметы", bible.run),
    "shotlist": ("srt + script -> shotlist.csv",      shotlist.run),
    "flow":     ("shotlist.csv -> flow_prompts.json", flow.run),
    "thumb":    ("script.md -> thumbnail.txt",        thumbnail.run),
    "assemble": ("clips/ + озвучка -> video.mp4",     assemble.run),
}
ALL = ",".join(STEPS)


def cmd_run(args) -> None:
    project = Project.load(args.dir)
    names = [s.strip() for s in args.steps.split(",") if s.strip()]
    unknown = [n for n in names if n not in STEPS]
    if unknown:
        raise SystemExit(f"неизвестные шаги: {', '.join(unknown)}. Доступны: {ALL}")

    # prompt.md нужен только шагу script — на отдельных шагах не мешаем работать
    if "script" in names and not (project.prompt.exists() or args.topic):
        raise SystemExit(
            f"[vidpipe] в {project.dir} нет prompt.md.\n"
            f"  vidpipe init --topic \"твоя тема\"   — создать ТЗ здесь\n"
            f"  vidpipe run --dir ПУТЬ              — работать в другой папке"
        )

    print(f"=== {project.name} ({project.dir}) ===")

    for name in names:
        desc, fn = STEPS[name]
        print(f"\n--- {name}: {desc} ---")
        preflight(project, name)
        if name == "script":
            fn(project, force=args.force, topic=args.topic)
        elif name == "clean":
            fn(project, force=args.force, expand_numbers=args.expand_numbers)
        else:
            fn(project, force=args.force)
        postflight(project, name, strict=not getattr(args, 'loose', False))

    print(f"\n=== готово: {project.dir} ===")


# Что отличает канал на другом языке. Добавляешь язык — добавляешь строку,
# и больше нигде ничего править не нужно.
ЯЗЫКИ = {
    "ru": {"DEFAULT_LANG": "русский", "WORDS_PER_MIN": "150",
           "WHISPER_LANG": "ru", "FW_MODEL_SIZE": "medium"},
    "en": {"DEFAULT_LANG": "English", "WORDS_PER_MIN": "140",
           "WHISPER_LANG": "en", "FW_MODEL_SIZE": "medium"},
    "hi": {"DEFAULT_LANG": "Hindi", "WORDS_PER_MIN": "147",
           "WHISPER_LANG": "hi", "FW_MODEL_SIZE": "large-v3"},
}


def channel_env(name: str, lang: str | None = None) -> str:
    """Заготовка .env для канала: только то, что отличает канал от других.

    Все настройки закомментированы намеренно. Строка в .env канала перекрывает
    глобальную, а пустое значение перекрывает её пустотой: копия целого шаблона
    стирала бы ключи и сбрасывала настройки whisper и сборки. Поэтому создание
    канала не меняет поведение ничего — его меняет только правка этого файла.
    """
    пресет = ЯЗЫКИ.get((lang or "").lower())
    if пресет:
        строки = [
            f"# --- язык {lang}: подставлено пресетом, правь под канал ---",
            f"DEFAULT_LANG={пресет['DEFAULT_LANG']}",
            f"WORDS_PER_MIN={пресет['WORDS_PER_MIN']}",
            "",
            "# --- субтитры ---",
            f"WHISPER_LANG={пресет['WHISPER_LANG']}",
            f"FW_MODEL_SIZE={пресет['FW_MODEL_SIZE']}",
        ]
    else:
        строки = [
            "# --- язык и темп речи ---",
            "# DEFAULT_LANG=Hindi             # Hindi / русский / English",
            "# WORDS_PER_MIN=147              # 147 хинди, 150 русский, 140 английский",
            "",
            "# --- субтитры ---",
            "# WHISPER_LANG=hi                # ru / hi / en",
            "# FW_MODEL_SIZE=large-v3         # хинди просит large-v3, ru и en — medium",
        ]
    настройки = "\n".join(строки)
    return f"""# ============ Канал: {name} ============
# Здесь только то, что отличает ЭТОТ канал. Ключи API, модель Claude,
# настройки whisper и сборки видео берутся из ~/.vidpipe/.env.
#
# Правило: пустых строк вида KEY= здесь быть не должно. Пустое значение не
# «наследует» глобальное, а затирает его. Не нужна настройка — оставь строку
# закомментированной.
CHANNEL_NAME={name}

{настройки}

# --- голос канала (найти: vidpipe voices --lang ru) ---
# VOICER_VOICE_ID=
# VOICER_PUBLIC_OWNER_ID=        # только для нестандартных голосов
# VOICER_SPEED=1.0               # 0.7-1.2

# --- память серии ---
# SERIES_DEPTH=5                 # сколько прошлых выпусков считать запретом на повтор
"""


def make_channel(name: str, root: str | Path | None = None,
                 force: bool = False, lang: str | None = None) -> None:
    """Создаёт канал в папке `root` (по умолчанию текущей): `.vidpipe-channel`
    с .env и промптами, рядом — пустой series.jsonl. Роликами канала
    становятся его подпапки."""
    root = Path(root).expanduser().resolve() if root else Path.cwd()
    root.mkdir(parents=True, exist_ok=True)

    # канал внутри канала работает (побеждает ближний), но почти всегда это
    # промах — например, команду запустили в папке ролика, а не канала
    outer = find_channel(root)
    if outer and outer.parent != root:
        print(f"[init] ВНИМАНИЕ: {root} уже внутри канала {outer.parent}.")
        print("       Новый канал перекроет его для этой папки и её подпапок,")
        print("       включая журнал серии. Если это не то, чего ты хочешь —")
        print(f"       удали {root / CHANNEL_MARKER} и создай канал уровнем выше.")

    marker = root / CHANNEL_MARKER
    marker.mkdir(parents=True, exist_ok=True)

    target = marker / ".env"
    if target.exists() and not force:
        print(f"[init] {target} уже есть, не трогаю (--force чтобы перезаписать)")
    else:
        target.write_text(channel_env(name, lang), encoding="utf-8")
        print(f"[init] создан {target}")
        print("       раскомментируй в нём язык, темп речи и голос канала —")
        print("       пока строки закомментированы, канал берёт всё глобальное")

    for fname in ("script_engine.md", "assets.md"):
        dst = marker / fname
        if dst.exists() and not force:
            print(f"[init] {dst} уже есть")
        else:
            shutil.copy(PACKAGE_ASSETS / fname, dst)
            print(f"[init] создан {dst}")

    journal = root / "series.jsonl"
    if not journal.exists():
        journal.touch()
        print(f"[init] создан {journal} — журнал серии этого канала")

    print(f"[init] канал «{name}»: {root}")
    print("       ролики канала — подпапки здесь, они подхватят его настройки")


def cmd_init(args) -> None:
    if args.global_config:
        GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
        target = GLOBAL_DIR / ".env"
        if target.exists() and not args.force:
            print(f"[init] {target} уже есть, не трогаю (--force чтобы перезаписать)")
        else:
            shutil.copy(PACKAGE_ASSETS / "env.example", target)
            print(f"[init] создан {target} — впиши ключи, он подхватится из любой папки")
        for name in ("script_engine.md", "assets.md"):
            dst = GLOBAL_DIR / name
            if not dst.exists():
                shutil.copy(PACKAGE_ASSETS / name, dst)
                print(f"[init] создан {dst}")
        return

    if args.channel:
        make_channel(args.channel, root=args.dir, force=args.force,
                     lang=getattr(args, 'lang', None))
        return

    project = Project.load(args.dir)
    script_gen.make_prompt(project, args.topic or "БЕЗ ТЕМЫ — впиши сюда",
                           force=args.force)
    if args.style:
        dst = project.dir / "assets.md"
        if dst.exists() and not args.force:
            print(f"[init] {dst.name} уже есть")
        else:
            shutil.copy(project.resource("assets.md"), dst)
            print(f"[init] создан {dst.name} — правь стиль под этот ролик")


def cmd_channels(args) -> None:
    """Все каналы, которые видит автоматизация."""
    каналы = find_channels()
    if args.json:
        import json
        # ensure_ascii обязателен: вывод читают скрипты, а консоль Windows
        # отдаёт им его в кодировке кодовой страницы. Кириллица в путях тогда
        # приезжает искажённой, и канал «не находится», хотя он есть.
        # Экранированный ASCII переживает любую кодовую страницу.
        print(json.dumps({и: str(п) for и, п in каналы.items()}))
        return

    корни = env("CHANNELS_ROOT")
    if not каналы:
        print("каналов не найдено.")
        print(f"  CHANNELS_ROOT = {корни or 'не задан'}")
        print(f"  впиши в {GLOBAL_DIR / '.env'} строку вида")
        print("  CHANNELS_ROOT=G:\\   (через ; можно несколько корней)")
        print("  и заведи канал: vidpipe init --channel ru --lang ru --dir ПУТЬ")
        return

    print(f"каналы (CHANNELS_ROOT={корни}):")
    print()
    for имя, путь in sorted(каналы.items()):
        выпуски = sorted(d.name for d in путь.iterdir()
                         if d.is_dir() and d.name.isdigit())
        журнал = путь / "series.jsonl"
        строк = 0
        if журнал.exists():
            строк = len([x for x in журнал.read_text(encoding="utf-8-sig")
                        .splitlines() if x.strip()])
        след = str(max((int(x) for x in выпуски), default=0) + 1)
        print(f"  {имя:12} {путь}")
        print(f"  {'':12} выпусков {len(выпуски)}, в журнале {строк}, "
              f"следующий — {след}")


def cmd_check(args) -> None:
    project = Project.load(args.dir)
    print(f"vidpipe {__version__}")
    print(f"папка проекта : {project.dir}")
    if project.channel:
        print(f"канал         : {project.channel_name}  ({project.channel_root})")
    else:
        print("канал         : не найден — работаю на глобальном конфиге")
        print("                (создать: vidpipe init --channel ИМЯ)")
    print(f"глобальный конфиг: {GLOBAL_DIR}"
          f"{'' if GLOBAL_DIR.exists() else '  (нет — vidpipe init --global)'}")

    print("\nресурсы:")
    for name in ("script_engine.md", "assets.md"):
        try:
            path, source = project.resolved(name)
            print(f"  {name:20} {source:10} {path}")
        except SystemExit:
            print(f"  {name:20} НЕ НАЙДЕН")

    print("\nнастройки канала:" if project.channel
          else "\nнастройки (глобальные, канала нет):")
    for key in ("DEFAULT_LANG", "WORDS_PER_MIN", "WHISPER_LANG",
                "FW_MODEL_SIZE", "VOICER_VOICE_ID"):
        # дефолты — те же, что подставят шаги: и они, и check берут их из DEFAULTS
        print(f"  {key:20} {env(key) or 'НЕ ЗАДАН'}")

    print("\nмодель:")
    from .llm import build, provider, без_модели
    name = provider()
    if без_модели():
        print("  провайдер            none: модели нет")
        print("  что это значит       озвучка, субтитры и сетка сцен считаются")
        print("                       кодом, тексты и промпты пишутся руками")
    else:
      try:
        url, _, payload = build("проверка", "проверка", 16)
        print(f"  провайдер            {name}")
        print(f"  модель               {payload.get('model', '?')}")
        print(f"  адрес                {url}")
      except SystemExit as e:
        print(f"  провайдер            {name} — {e}")

    print("\nключи:")
    нужные = ("VOICER_API_KEY",) if name != "anthropic" else ("ANTHROPIC_API_KEY", "VOICER_API_KEY")
    for key in нужные:
        val = env(key)
        print(f"  {key:20} {'есть' if val else 'НЕТ'}")
    if без_модели():
        print("  ANTHROPIC_API_KEY    не нужен: модели нет")
    elif name != "anthropic":
        print("  ANTHROPIC_API_KEY    не нужен: модель локальная")

    if env("VOICER_API_KEY"):
        from .steps.voicer import balance
        try:
            print(f"  баланс озвучки       {balance()}")
        except SystemExit as e:
            print(f"  баланс озвучки       {e}")

    print("\nвнешние программы:")
    try:
        print(f"  ffmpeg               {ffmpeg_bin()}")
    except SystemExit as e:
        print(f"  ffmpeg               НЕ НАЙДЕН\n{e}")
    backend = env("WHISPER_BACKEND", "faster_whisper")
    print(f"  whisper backend      {backend}")
    if backend == "faster_whisper":
        try:
            import faster_whisper  # noqa: F401
            print("  faster-whisper       есть")
        except ImportError:
            print("  faster-whisper       НЕТ — pip install faster-whisper")
    else:
        binary = env("WHISPER_BIN")
        print(f"  whisper.cpp          {'есть' if binary and Path(binary).exists() else 'НЕ НАЙДЕН'}")

    print("\nфайлы проекта:")
    from .config import FILES
    for key, fname in FILES.items():
        p = project.dir / fname
        size = f"{p.stat().st_size / 1024:.0f} КБ" if p.exists() else "—"
        print(f"  {fname:20} {size}")


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="vidpipe",
        description=f"vidpipe {__version__}. Конвейер: тема -> сценарий -> озвучка "
                    f"-> субтитры -> раскадровка -> промпты Flow -> видео.",
    )
    sub = ap.add_subparsers(dest="cmd")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", "-d", help="папка проекта (по умолчанию текущая)")
    common.add_argument("--force", "-f", action="store_true", help="перезаписать выходы")

    r = sub.add_parser("run", parents=[common], help="прогнать конвейер")
    r.add_argument("--topic", "-t", help="тема: создаст prompt.md, если его нет")
    r.add_argument("--steps", "-s", default=ALL, help="через запятую: " + ALL)
    r.add_argument("--loose", action="store_true",
                   help="не останавливать конвейер на браке шага, только показать находки")
    r.add_argument("--expand-numbers", action="store_true",
                   help="разворачивать числа в слова (только именительный падеж)")
    r.set_defaults(func=cmd_run)

    i = sub.add_parser("init", parents=[common],
                   help="создать prompt.md, канал или глобальный конфиг")
    i.add_argument("--topic", "-t", help="тема ролика")
    i.add_argument("--global", dest="global_config", action="store_true",
                   help=f"создать {GLOBAL_DIR} с .env и промптами")
    i.add_argument("--lang", metavar="КОД", choices=sorted(ЯЗЫКИ),
                   help="язык нового канала: " + ", ".join(sorted(ЯЗЫКИ)) +
                        " — подставит темп речи, язык промпта и модель whisper")
    i.add_argument("--channel", metavar="ИМЯ",
                   help=f"создать канал: {CHANNEL_MARKER}/ с .env и промптами "
                        f"в текущей папке (или в --dir)")
    i.add_argument("--style", action="store_true",
                   help="положить копию assets.md в папку проекта")
    i.set_defaults(func=cmd_init)

    ok = sub.add_parser("ok", parents=[common],
                        help="сценарий прочитан, можно дальше")
    ok.set_defaults(func=cmd_ok)

    cl = sub.add_parser("clips", parents=[common],
                        help="разложить файлы из clips по сценам")
    cl.add_argument("--apply", action="store_true",
                    help="переименовать файлы, а не только показать разбор")
    cl.set_defaults(func=cmd_clips)

    ch = sub.add_parser("channels", help="какие каналы видит автоматизация")
    ch.add_argument("--json", action="store_true", help="для скриптов")
    ch.set_defaults(func=cmd_channels)

    c = sub.add_parser("check", parents=[common], help="показать, что откуда берётся")
    c.set_defaults(func=cmd_check)

    d = sub.add_parser("doctor", parents=[common],
                       help="проверить все файлы проекта и назвать проблемы")
    d.set_defaults(func=cmd_doctor)

    ser = sub.add_parser("series", parents=[common],
                         help="журнал серии: какие приёмы уже использованы")
    ser.set_defaults(func=cmd_series)

    v = sub.add_parser("voices", help="найти голос и его voice_id")
    v.add_argument("search", nargs="?", help="что искать: 'russian male narrator'")
    v.add_argument("--library", "-l", default="public",
                   choices=["public", "standard", "alternative"],
                   help="какая библиотека (по умолчанию public)")
    v.add_argument("--voice-id", help="точный поиск по 20-символьному id")
    v.add_argument("--gender", "-g", help="male / female")
    v.add_argument("--lang", help="язык, ISO-код: ru, en")
    v.add_argument("--sort", choices=["name", "newest", "accent", "trending", "popular"])
    v.add_argument("--limit", "-n", type=int, default=15)
    v.set_defaults(func=cmd_voices)

    # голый `vidpipe` в папке с prompt.md = прогнать всё
    argv = sys.argv[1:]
    if not argv or (argv and argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["run"] + argv

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return
    # только теперь известен --dir: канал ищем от папки ролика, а не от текущей
    load_env(getattr(args, "dir", None))
    args.func(args)


if __name__ == "__main__":
    main()
