"""Шаг: clips/ + voice.mp3 + subtitles.srt -> video.mp4

Раскладывает кадры по таймингам из shotlist.csv и склеивает с озвучкой.
Картинки и видео обрабатываются по-разному: статике добавляется медленный
наезд, иначе восемь секунд неподвижного кадра выглядят как заставка.
"""
from __future__ import annotations

import csv
import subprocess
from pathlib import Path

from ..config import env, env_int, ffmpeg_bin, read_text

IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
VIDEOS = {".mp4", ".mov", ".webm", ".mkv"}


def _run(args: list[str]) -> None:
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"[assemble] ffmpeg упал:\n{r.stderr[-800:]}")


def find_clips(folder: Path) -> dict[int, Path]:
    """Кадры сопоставляются по первому числу в имени файла: 01.mp4, scene_7.png,
    12-boundary-stone.jpg — всё подойдёт."""
    import re
    found: dict[int, Path] = {}
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() not in IMAGES | VIDEOS:
            continue
        m = re.search(r"\d+", p.stem)
        if not m:
            continue
        n = int(m.group())
        if n in found:
            print(f"[assemble] ! сцена {n} задана дважды: {found[n].name} и {p.name}")
        found[n] = p
    return found


def _probe(path: Path) -> dict:
    import json
    probe = Path(ffmpeg_bin()).with_name("ffprobe" + Path(ffmpeg_bin()).suffix)
    if not probe.exists():
        return {}
    out = subprocess.run(
        [str(probe), "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=r_frame_rate,nb_frames:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except Exception:  # noqa: BLE001
        return {}


def is_still(path: Path) -> bool:
    """Видеофайл длиной в один кадр — это на самом деле картинка. Flow иногда
    отдаёт такие: контейнер mp4, а внутри единственный кадр."""
    if path.suffix.lower() in IMAGES:
        return True
    info = _probe(path)
    try:
        dur = float(info.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        dur = 0
    frames = info.get("streams", [{}])[0].get("nb_frames")
    try:
        frames = int(frames)
    except (TypeError, ValueError):
        frames = None
    return (frames is not None and frames <= 1) or (0 < dur < 0.5)


def prepare(src: Path, dst: Path, duration: float, size: str, fps: int) -> None:
    ff = ffmpeg_bin()
    w, h = size.split("x")
    fit = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
           f"crop={w}:{h},setsar=1")

    if is_still(src):
        over = float(env("KENBURNS_ZOOM", "1.15"))
        if over <= 1.0:
            vf = fit
        else:
            # Крупная деталь: crop умеет вставать только на целый пиксель, и
            # при медленном движении окно прыгает то на 1, то на 2 пикселя —
            # это и видно как дрожание. Кадрируем на удвоенном масштабе и
            # уменьшаем вдвое: шаг становится дробным, дрожание уходит.
            ss = env_int("KENBURNS_SUPERSAMPLE", 2)
            bw, bh = int(int(w) * over * ss), int(int(h) * over * ss)
            cw2, ch2 = int(w) * ss, int(h) * ss
            vf = (f"scale={bw}:{bh}:force_original_aspect_ratio=increase,"
                  f"crop={cw2}:{ch2}:x='(iw-{cw2})*t/{duration}':"
                  f"y='(ih-{ch2})*t/{duration}',"
                  f"scale={w}:{h}:flags=bicubic,setsar=1")
        # -framerate ОБЯЗАТЕЛЕН: без него зацикленная картинка идёт 25 кадрами,
        # и приведение к 30 дублирует каждый шестой кадр — это видно как рывки.
        if src.suffix.lower() not in IMAGES:
            # Односкадровое видео сначала вытаскиваем в картинку. Зациклить его
            # как поток нельзя: он идёт со своей частотой (обычно 25), и
            # приведение к выходной дублирует каждый пятый-шестой кадр.
            frame = dst.with_name(dst.stem + "_frame.png")
            _run([ff, "-hide_banner", "-loglevel", "error", "-y",
                  "-i", str(src), "-frames:v", "1", str(frame)])
            src = frame
        _run([ff, "-hide_banner", "-loglevel", "error", "-y",
              "-loop", "1", "-framerate", str(fps), "-t", f"{duration}",
              "-i", str(src),
              "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
              "-pix_fmt", "yuv420p", "-r", str(fps), str(dst)])
    else:
        # короткий клип дотягиваем стоп-кадром, длинный обрезаем
        _run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
              "-vf", f"{fit},tpad=stop_mode=clone:stop_duration=10",
              "-t", f"{duration}", "-an",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
              "-pix_fmt", "yuv420p", "-r", str(fps), str(dst)])


def _source_fps(clips: dict[int, Path], rows: list[dict]) -> int | None:
    """Частота кадров берётся у первого же видеофайла. Приводить 24 кадра к 30
    нечем, кроме дублирования кадров, а это на панорамах выглядит как рывки."""
    import json
    for r in rows:
        p = clips.get(int(r["scene"]))
        if not p or p.suffix.lower() not in VIDEOS or is_still(p):
            continue
        probe = Path(ffmpeg_bin()).with_name("ffprobe" + Path(ffmpeg_bin()).suffix)
        if not probe.exists():
            return None
        out = subprocess.run(
            [str(probe), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate", "-of", "json", str(p)],
            capture_output=True, text=True)
        try:
            rate = json.loads(out.stdout)["streams"][0]["r_frame_rate"]
            num, den = rate.split("/")
            val = round(int(num) / int(den))
            print(f"[assemble] частота кадров источника: {val} — беру её")
            return val
        except Exception:  # noqa: BLE001
            return None
    return None


def run(project, force: bool = False) -> None:
    out = project.dir / "video.mp4"
    if out.exists() and not force:
        print(f"[assemble] пропуск, {out.name} уже есть")
        return
    if not project.shotlist.exists():
        raise SystemExit(f"[assemble] нет {project.shotlist.name}")
    if not project.voice_mp3.exists():
        raise SystemExit(f"[assemble] нет {project.voice_mp3.name}")

    folder = project.dir / env("CLIPS_DIR", "clips")
    if not folder.exists():
        raise SystemExit(
            f"[assemble] нет папки {folder}.\n"
            f"  Сложи туда кадры из Flow, назвав по номеру сцены: 1.mp4, 2.mp4 …"
        )

    with project.shotlist.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    clips = find_clips(folder)
    missing = [int(r["scene"]) for r in rows if int(r["scene"]) not in clips]
    if missing:
        raise SystemExit(f"[assemble] не найдены кадры для сцен: {missing}")

    size = env("VIDEO_SIZE", "1920x1080")
    fps = env_int("VIDEO_FPS", 0) or _source_fps(clips, rows) or 30
    print(f"[assemble] {len(rows)} сцен, {size} @ {fps}fps")

    parts = []
    for i, r in enumerate(rows, 1):
        n = int(r["scene"])
        src = clips[n]
        dst = project.tmp / f"seg_{n:03d}.mp4"
        if not dst.exists() or force:
            print(f"[assemble] {i}/{len(rows)} сцена {n}: {src.name}")
            prepare(src, dst, float(r["duration"]), size, fps)
        parts.append(dst)

    listing = project.tmp / "segments.txt"
    listing.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in parts),
                       encoding="utf-8")
    silent = project.tmp / "silent.mp4"
    _run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
          "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(silent)])

    args = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(silent), "-i", str(project.voice_mp3)]

    burn = env("BURN_SUBS", "0").lower() in ("1", "true", "yes")
    if burn and project.srt.exists():
        # ffmpeg на Windows требует экранировать двоеточие диска в пути фильтра
        path = project.srt.resolve().as_posix().replace(":", "\\:")
        style = env("SUB_STYLE", "FontSize=22,Outline=2,MarginV=60")
        args += ["-vf", f"subtitles='{path}':force_style='{style}'",
                 "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p"]
        print("[assemble] субтитры впечатываются в картинку")
    else:
        args += ["-c:v", "copy"]

    args += ["-c:a", "aac", "-b:a", "192k", "-shortest", str(out)]
    _run(args)

    mb = out.stat().st_size / 1024 / 1024
    print(f"[assemble] {out.name}: {mb:.0f} МБ")
