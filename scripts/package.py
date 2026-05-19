"""Build a Krita-installable zip for the TI-99/4A pixel art plugin.

Produces ``ti99-pixel-art-plugin-<version>.zip`` next to the project root,
with the same internal layout the OpenAI Image Generator plugin uses, so
the archive can be extracted directly into Krita's ``pykrita/`` folder:

    ti99_pixel_art.desktop
    ti99_pixel_art/
        __init__.py
        extension.py
        widget.py
        converter.py
        manual.html   (rendered from README.md, if `markdown` is installed)
        LICENSE       (if a LICENSE file exists at the project root)

Run from the project root:

    python scripts/package.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from shutil import copy, copytree, ignore_patterns, make_archive, rmtree

# Make the plugin package importable so we can read __version__ from it.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ti99_pixel_art  # noqa: E402

PLUGIN_NAME = "ti99_pixel_art"
DESKTOP_FILE = f"{PLUGIN_NAME}.desktop"
PACKAGE_DIR = ROOT / "scripts" / ".package"
VERSION = ti99_pixel_art.__version__
ARCHIVE_BASENAME = f"ti99-pixel-art-plugin-{VERSION}"


def _ignore(path: str, names: list[str]):
    return ignore_patterns(".*", "*.pyc", "*.pyo", "__pycache__")(path, names)


def _try_render_manual(plugin_dst: Path) -> None:
    """If README.md and the `markdown` library are present, render manual.html."""
    readme = ROOT / "README.md"
    if not readme.exists():
        return
    try:
        from markdown import markdown  # type: ignore[import-not-found]
    except ImportError:
        # Fall back to copying the raw markdown — Krita's manual viewer
        # will at least show the source text.
        copy(readme, plugin_dst / "manual.md")
        return
    html = markdown(readme.read_text(encoding="utf-8"), extensions=["fenced_code"])
    (plugin_dst / "manual.html").write_text(html, encoding="utf-8")


def build_package() -> Path:
    if PACKAGE_DIR.exists():
        rmtree(PACKAGE_DIR)
    PACKAGE_DIR.mkdir(parents=True)

    desktop_src = ROOT / DESKTOP_FILE
    if not desktop_src.exists():
        raise FileNotFoundError(f"Missing {desktop_src}")
    copy(desktop_src, PACKAGE_DIR / DESKTOP_FILE)

    plugin_src = ROOT / PLUGIN_NAME
    plugin_dst = PACKAGE_DIR / PLUGIN_NAME
    copytree(plugin_src, plugin_dst, ignore=_ignore)

    license_file = ROOT / "LICENSE"
    if license_file.exists():
        copy(license_file, plugin_dst / "LICENSE")
    _try_render_manual(plugin_dst)

    archive_base = ROOT / ARCHIVE_BASENAME
    archive_path = make_archive(str(archive_base), "zip", PACKAGE_DIR)
    rmtree(PACKAGE_DIR)
    return Path(archive_path)


def main() -> int:
    print(f"Building {ARCHIVE_BASENAME}.zip")
    archive = build_package()
    print(f"Built: {archive}")
    print()
    print("To install:")
    print(
        "  1. In Krita: Settings -> Manage Resources -> Open Resource Folder,"
        " then go into pykrita\\"
    )
    print(
        "  2. Extract this zip there so you end up with"
        f" pykrita\\{DESKTOP_FILE} and pykrita\\{PLUGIN_NAME}\\..."
    )
    print(
        "  3. Restart Krita, enable the plugin in the Python Plugin Manager,"
        " then Settings -> Dockers -> TI99/4A pixel art."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
