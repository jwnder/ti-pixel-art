"""TI-99/4A pixel art plugin for Krita.

Exposes a dock widget titled 'TI99/4A pixel art' that turns the current
canvas into a TI Extended BASIC program (CALL CHAR + CALL HCHAR) which
reproduces the image on a real (or emulated) TI-99/4A.
"""

import importlib.util

__version__ = "1.0.0"

# The extension module imports `krita`, so it can only be loaded inside the
# Krita process. The pure-Python `converter` module is always importable so
# the conversion logic can be unit-tested outside Krita.
if importlib.util.find_spec("krita"):
    from .extension import TiPixelArtExtension as TiPixelArtExtension
