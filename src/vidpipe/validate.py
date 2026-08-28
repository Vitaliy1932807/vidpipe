"""Проверки состояния проекта.

Каждая находка — это не просто «что-то не так», а конкретная команда, которой
это чинится. Проверки запускаются перед шагом (успеет ли он вообще отработать)
и после (получилось ли то, что ожидалось).
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import env, env_int, ffmpeg_bin, read_text

IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
VIDEOS = {".mp4", ".mov", ".webm", ".mkv"}


@dataclass
class Issue:
    level: str          # stop — шаг не пойдёт; warn — пойдёт, но результат пострадает
    what: str
    fix: str = ""

    def show(self) -> str:
        mark = "СТОП" if self.level == "stop" else "!"
        line = f"  [{mark}] {self.what}"
        return f"{line}\n        {self.fix}" if self.fix else line


def media_duration(path: Path) -> float | None:
    probe = Path(ffmpeg_bin()).with_name("ffprobe" + Path(ffmpeg_bin()).suffix)
    if not probe.exists():
        return None
    r = subprocess.run([str(probe), "-v", "error", "-show_entries",
                        "format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True)
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:  # noqa: BLE001
        return None


def parse_srt(raw: str) -> list[tuple[float, float, str]]:
    cue = re.compile(r"(\d+)\s*\n(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
                     r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*\n(.*?)(?=\n\s*\n|\Z)", re.S)

    def ts(s: str) -> float:
        h, m, rest = s.split(":")
        sec, ms = re.split(r"[,.]", rest)
        return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000

    return [(ts(a), ts(b), " ".join(t.split())) for _, a, b, t in cue.findall(raw)]


# --- проверки по артефактам -------------------------------------------------

def check_script(project) -> list[Issue]:
    if not project.script.exists():
        return [Issue("stop", "нет script.md",
                      'vidpipe -s script   (или положи сценарий руками)')]
    text = read_text(project.script)
    out: list[Issue] = []
    words = len(text.split())
    wpm = env_int("WORDS_PER_MIN")
    target = env_int("DEFAULT_DURATION_MIN")
    minutes = words / wpm
    if abs(minutes - target) / target > 0.25:
        out.append(Issue("warn", f"объём {words} слов ≈ {minutes:.1f} мин, "
                                 f"а цель {target} мин",
                         "поправь DEFAULT_DURATION_MIN или объём сценария"))
    if re.search(r"^\s*#{1,6}\s+", text, re.M) or "**" in text:
        out.append(Issue("warn", "в сценарии осталась разметка — диктор её прочитает",
                         "шаг clean её снимет, но лучше почистить исходник"))

    # Дальше три вещи, которые критик-модель проверяет плохо, а код точно.
    абзацы = [a.strip() for a in text.strip().splitlines() if a.strip()]
    if абзацы:
        последний = абзацы[-1]
        if последний.rstrip().endswith("?"):
            out.append(Issue("warn", "ролик заканчивается вопросом",
                             "вопрос в финале отдаёт зрителя чужому ролику; "
                             "закончи утверждением"))
        if re.search(r"комментар|подпиш|подпис", последний, re.I):
            out.append(Issue("warn", "ролик заканчивается призывом",
                             "перенеси призыв выше: последняя строка должна "
                             "быть содержательной"))

    запрещённые = env("SCRIPT_FORBID", "")
    найдены = sorted({з for з in запрещённые if з in text})
    if найдены:
        сколько = ", ".join(f"{з} ({text.count(з)})" for з in найдены)
        out.append(Issue("warn", f"запрещённые каналом знаки: {сколько}",
                         "их читает синтез речи и ломает интонацию"))
    return out


def check_voice_txt(project) -> list[Issue]:
    if not project.voice_txt.exists():
        return [Issue("stop", "нет voice.txt", "vidpipe -s clean")]
    text = read_text(project.voice_txt)
    out = []
    if len(text.strip()) < 500:
        out.append(Issue("stop", f"voice.txt слишком короткий ({len(text)} симв.)",
                         "проверь script.md, потом vidpipe -s clean -f"))
    for bad, name in (("[", "квадратные скобки"), ("**", "жирный шрифт"),
                      ("#", "заголовки")):
        if bad in text:
            out.append(Issue("warn", f"в тексте для озвучки остались {name}",
                             "vidpipe -s clean -f"))
    return out


def check_voice_mp3(project) -> list[Issue]:
    if not project.voice_mp3.exists():
        return [Issue("stop", "нет voice.mp3", "vidpipe -s tts")]
    out = []
    size = project.voice_mp3.stat().st_size
    if size < 100_000:
        return [Issue("stop", f"voice.mp3 подозрительно мал ({size} б)",
                      "del voice.mp3 && vidpipe -s tts")]
    dur = media_duration(project.voice_mp3)
    if dur and project.voice_txt.exists():
        words = len(read_text(project.voice_txt).split())
        real = words / (dur / 60)
        setting = env_int("WORDS_PER_MIN")
        if abs(real - setting) / setting > 0.15:
            out.append(Issue("warn",
                             f"реальный темп {real:.0f} слов/мин, "
                             f"а в настройках {setting}",
                             f"поставь WORDS_PER_MIN={real:.0f} — "
                             f"следующие сценарии выйдут нужной длины"))
    return out


def check_srt(project) -> list[Issue]:
    if not project.srt.exists():
        return [Issue("stop", "нет subtitles.srt", "vidpipe -s srt")]
    cues = parse_srt(read_text(project.srt))
    if not cues:
        return [Issue("stop", "subtitles.srt не разбирается",
                      "del subtitles.srt && vidpipe -s srt")]
    out = []
    dur = media_duration(project.voice_mp3) if project.voice_mp3.exists() else None
    if dur:
        speech = sum(e - s for s, e, _ in cues)
        covered = speech / dur * 100
        if covered < 90:
            out.append(Issue("warn",
                             f"речью покрыто {covered:.0f}% записи — часть не распознана",
                             "FW_MODEL_SIZE=large-v3, потом del subtitles.srt "
                             "&& vidpipe -s srt"))
        if abs(cues[-1][1] - dur) > 5:
            out.append(Issue("warn",
                             f"субтитры кончаются на {cues[-1][1]:.0f} с, "
                             f"а запись длится {dur:.0f} с",
                             "хвост записи не распознан"))
    return out


def check_shotlist(project) -> list[Issue]:
    if not project.shotlist.exists():
        return [Issue("stop", "нет shotlist.csv", "vidpipe -s shotlist")]
    with project.shotlist.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return [Issue("stop", "shotlist.csv пуст", "vidpipe -s shotlist -f")]
    out = []
    nums = [int(r["scene"]) for r in rows]
    if nums != list(range(1, len(nums) + 1)):
        out.append(Issue("warn", "номера сцен идут не подряд",
                         "проверь shotlist.csv в Excel"))
    if project.srt.exists():
        cues = parse_srt(read_text(project.srt))
        if cues:
            total = sum(float(r["duration"]) for r in rows)
            if abs(total - cues[-1][1]) > 10:
                out.append(Issue("warn",
                                 f"раскадровка на {total:.0f} с, "
                                 f"а озвучка на {cues[-1][1]:.0f} с",
                                 "картинка разъедется с голосом; "
                                 "vidpipe -s shotlist -f"))
    return out


def check_clips(project) -> list[Issue]:
    folder = project.dir / env("CLIPS_DIR", "clips")
    if not folder.exists():
        return [Issue("stop", f"нет папки {folder.name}",
                      f"mkdir {folder.name}  и сложи туда кадры из Flow")]

    out = []
    nested = [p for p in folder.iterdir() if p.is_dir()]
    flat = [p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGES | VIDEOS]
    if nested and not flat:
        out.append(Issue("stop", f"кадры лежат во вложенных папках ({len(nested)} шт.)",
                         f"cd {folder.name}; Get-ChildItem -Recurse -File | "
                         f"Move-Item -Destination . -Force; "
                         f"Get-ChildItem -Directory | Remove-Item -Recurse -Force"))
        return out

    found: dict[int, list[Path]] = {}
    for p in flat:
        m = re.search(r"\d+", p.stem)
        if m:
            found.setdefault(int(m.group()), []).append(p)

    unnamed = [p.name for p in flat if not re.search(r"\d+", p.stem)]
    if unnamed:
        out.append(Issue("warn", f"без номера в имени: {', '.join(unnamed[:3])}",
                         "переименуй по номеру сцены"))

    dupes = {n: [p.name for p in ps] for n, ps in found.items() if len(ps) > 1}
    if dupes:
        first = next(iter(dupes.items()))
        out.append(Issue("warn", f"на сцену {first[0]} несколько файлов: "
                                 f"{', '.join(first[1][:2])}",
                         "оставь по одному файлу на сцену"))

    if project.shotlist.exists():
        with project.shotlist.open(encoding="utf-8-sig") as f:
            need = [int(r["scene"]) for r in csv.DictReader(f)]
        missing = [n for n in need if n not in found]
        extra = [n for n in found if n not in need]
        if missing:
            shown = ", ".join(map(str, missing[:10]))
            more = f" и ещё {len(missing) - 10}" if len(missing) > 10 else ""
            out.append(Issue("stop", f"нет кадров для сцен: {shown}{more}",
                             "догенерь их в Flow"))
        if extra:
            out.append(Issue("warn", f"лишние файлы с номерами: "
                                     f"{', '.join(map(str, extra[:5]))}",
                             "они не попадут в сборку"))
    return out


def check_video(project) -> list[Issue]:
    if not project.video.exists():
        return [Issue("stop", "нет video.mp4", "vidpipe -s assemble")]
    out = []
    vd = media_duration(project.video)
    ad = media_duration(project.voice_mp3) if project.voice_mp3.exists() else None
    if vd and ad and abs(vd - ad) > 3:
        out.append(Issue("warn",
                         f"видео {vd:.0f} с, озвучка {ad:.0f} с — расходятся",
                         "Remove-Item .vidpipe -Recurse -Force; del video.mp4; "
                         "vidpipe -s assemble"))
    return out


ARTIFACTS = [
    ("script.md", check_script),
    ("voice.txt", check_voice_txt),
    ("voice.mp3", check_voice_mp3),
    ("subtitles.srt", check_srt),
    ("shotlist.csv", check_shotlist),
    ("clips/", check_clips),
    ("video.mp4", check_video),
]

# что нужно шагу до запуска
PREFLIGHT = {
    "clean": [check_script],
    "tts": [check_voice_txt],
    "srt": [check_voice_mp3],
    "shotlist": [check_srt],
    "flow": [check_shotlist],
    "assemble": [check_shotlist, check_clips],
}


def preflight(project, step: str) -> None:
    """Останавливаем шаг до работы, если он всё равно не сможет отработать."""
    issues: list[Issue] = []
    for fn in PREFLIGHT.get(step, []):
        issues += fn(project)
    stoppers = [i for i in issues if i.level == "stop"]
    for i in issues:
        print(i.show())
    if stoppers:
        raise SystemExit(f"[{step}] шаг не может начаться — сначала исправь верхнее")


def cmd_doctor(args) -> None:
    from .config import Project
    project = Project.load(args.dir)
    print(f"проект: {project.dir}")
    print(f"канал : {project.channel_name} ({project.channel_root})"
          if project.channel else "канал : нет — глобальные настройки")
    print()

    total_stop = 0
    for name, fn in ARTIFACTS:
        issues = fn(project)
        stop = [i for i in issues if i.level == "stop"]
        total_stop += len(stop)
        if not issues:
            print(f"{name:16} готово")
        elif stop and len(stop) == len(issues) and "нет " in stop[0].what:
            print(f"{name:16} ещё нет")
            print(stop[0].show())
        else:
            print(f"{name:16} есть замечания")
            for i in issues:
                print(i.show())

    print()
    print("всё готово к сборке" if total_stop == 0
          else f"блокирующих проблем: {total_stop}")
