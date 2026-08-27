"""Версия лежит в двух местах — они не должны разъезжаться."""
from __future__ import annotations

import pathlib
import tomllib

import vidpipe

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_версия_совпадает_с_pyproject():
    """`vidpipe check` печатает __version__, а ставится пакет по pyproject.

    Разъедутся — и версия в выводе перестанет означать то, что установлено.
    """
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert vidpipe.__version__ == meta["project"]["version"]
