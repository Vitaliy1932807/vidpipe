"""Шаг 4: voice.mp3 -> subtitles.srt

Два бэкенда:
  whisper_cpp     — быстрый, но требует собранный бинарник (VS Build Tools на Windows)
  faster_whisper  — чистый pip, ничего компилировать не надо (по умолчанию в CI)
Выбор: WHISPER_BACKEND в .env.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..config import env, ffmpeg_bin


def to_wav16k(src: Path, dst: Path) -> Path:
    """whisper.cpp жрёт только 16 кГц моно WAV — это самая частая причина падения."""
    subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)],
        check=True,
    )
    return dst


def _fmt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def via_whisper_cpp(wav: Path, out_srt: Path, lang: str) -> None:
    binary = env("WHISPER_BIN", required=True)
    model = env("WHISPER_MODEL", required=True)
    if not Path(binary).exists():
        raise SystemExit(f"[srt] не найден бинарник whisper.cpp: {binary}")
    if not Path(model).exists():
        raise SystemExit(f"[srt] не найдена модель: {model}")

    stem = out_srt.with_suffix("")  # whisper.cpp сам добавит .srt
    subprocess.run(
        [binary, "-m", model, "-f", str(wav), "-l", lang,
         "-osrt", "-of", str(stem), "--max-len", env("SRT_MAX_LEN", "42")],
        check=True,
    )
    if not out_srt.exists():
        raise SystemExit("[srt] whisper.cpp отработал, но .srt не появился")


def via_faster_whisper(audio: Path, out_srt: Path, lang: str) -> None:
    from faster_whisper import WhisperModel

    size = env("FW_MODEL_SIZE", "medium")
    device = env("FW_DEVICE", "cpu")
    compute = env("FW_COMPUTE_TYPE", "int8")
    print(f"[srt] faster-whisper: {size} / {device} / {compute}")

    # Фильтр тишины на неанглийских языках вырезает куски настоящей речи.
    # По умолчанию выключен: лучше лишний сегмент, чем дыра в таймингах.
    vad = env("FW_VAD", "0").lower() in ("1", "true", "yes")

    model = WhisperModel(size, device=device, compute_type=compute)
    segments, info = model.transcribe(
        str(audio), language=lang, vad_filter=vad, beam_size=5,
        # без этого модель зацикливается и повторяет последнюю фразу
        condition_on_previous_text=False,
    )

    lines, cues = [], []
    for i, seg in enumerate(segments, 1):
        cues.append((seg.start, seg.end))
        lines.append(f"{i}\n{_fmt_ts(seg.start)} --> {_fmt_ts(seg.end)}\n"
                     f"{seg.text.strip()}\n")
    out_srt.write_text("\n".join(lines), encoding="utf-8")
    print(f"[srt] распознано {len(lines)} сегментов, длительность {info.duration:.0f} с")

    _check_coverage(cues, info.duration)


def _check_coverage(cues: list[tuple[float, float]], duration: float) -> None:
    """Если распознанная речь сильно короче аудио — часть записи потеряна,
    и раскадровка ляжет мимо. Молча пропускать такое нельзя."""
    if not cues or not duration:
        return
    speech = sum(e - s for s, e in cues)
    covered = speech / duration * 100
    gaps = [(cues[i + 1][0] - cues[i][1], cues[i][1]) for i in range(len(cues) - 1)]
    big = sorted((g for g in gaps if g[0] > 10), reverse=True)

    print(f"[srt] покрытие речью: {covered:.0f}% ({speech:.0f} из {duration:.0f} с)")
    if covered >= 70 and not big:
        return

    print(f"[srt] ! похоже, часть записи не распознана")
    for gap, at in big[:5]:
        print(f"[srt]   провал {gap:.0f} с на отметке {at:.0f} с")
    print("[srt]   тайминги будут неточными, раскадровка ляжет мимо")
    print("[srt]   попробуй: FW_MODEL_SIZE=large-v3, или FW_VAD=0 если он включён")


def run(project, force: bool = False) -> None:
    if not project.voice_mp3.exists():
        raise SystemExit(f"[srt] нет {project.voice_mp3} — сначала шаг tts")
    if project.srt.exists() and not force:
        print(f"[srt] пропуск, {project.srt.name} уже есть")
        return

    lang = env("WHISPER_LANG", "ru")
    backend = env("WHISPER_BACKEND", "faster_whisper")

    if backend == "whisper_cpp":
        wav = to_wav16k(project.voice_mp3, project.tmp / "voice_16k.wav")
        via_whisper_cpp(wav, project.srt, lang)
    elif backend == "faster_whisper":
        via_faster_whisper(project.voice_mp3, project.srt, lang)
    else:
        raise SystemExit(f"[srt] неизвестный WHISPER_BACKEND={backend}")

    print(f"[srt] готово: {project.srt}")
