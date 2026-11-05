"""Label font for evidence images, found on Linux, Windows or macOS.
Liberation Sans is metric-compatible with Arial, so Arial is the stand-in outside Linux."""
from __future__ import annotations

import os
from pathlib import Path

from PIL import ImageFont

_DIRS = [Path("/usr/share/fonts/truetype/liberation"), Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
         Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental")]
_FILES = {False: ["LiberationSans-Regular.ttf", "arial.ttf", "Arial.ttf"],
          True: ["LiberationSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"]}


def label_font(size: int, bold: bool = False):
    for f in _FILES[bold]:
        for d in _DIRS:
            if (d / f).exists():
                return ImageFont.truetype(str(d / f), size)
    return ImageFont.load_default()
