"""Krita extension + dock-widget registration for TI-99/4A pixel art."""

from __future__ import annotations

from krita import (  # type: ignore[import-not-found]
    DockWidgetFactory,
    DockWidgetFactoryBase,
    Extension,
    Krita,
)

from .widget import TiPixelArtDockWidget


class TiPixelArtExtension(Extension):
    def __init__(self, parent) -> None:
        super().__init__(parent)

    def setup(self) -> None:
        # Nothing to do at startup — the dock widget is the only entry point.
        pass

    def createActions(self, window) -> None:
        # No menu actions for now; the docker carries the whole UI.
        pass


Krita.instance().addExtension(TiPixelArtExtension(Krita.instance()))
Krita.instance().addDockWidgetFactory(
    DockWidgetFactory(
        "ti99PixelArt",
        DockWidgetFactoryBase.DockRight,
        TiPixelArtDockWidget,
    )
)
