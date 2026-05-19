"""Krita dock widget exposing the 'TI99/4A pixel art' tab.

Two-step flow:
  1. 'Generate squares' resamples the active document to the requested dot
     grid, thresholds to 1 bit, and paints the result back onto Krita as a
     new paint layer named 'TI99 squares (CxR dots)'. The bit matrix is
     cached on the widget for step 2.
  2. 'Generate code' takes that cached bit matrix plus the user's character
     code range and produces an Extended BASIC program in the read-only
     text area below.
"""

from __future__ import annotations

from krita import DockWidget, Krita  # type: ignore[import-not-found]
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .converter import (
    DOT_MAX_H,
    DOT_MAX_W,
    PixelatedImage,
    bits_to_basic,
    bits_to_bgra,
    pixelate,
)


_TAB_TITLE = "TI99/4A pixel art"


class _NoDocumentPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        header = QLabel("TI-99/4A pixel art", self)
        header.setStyleSheet("font-size: 12pt; font-weight: bold;")
        body = QLabel(
            "Open or create an image in Krita to convert it into\n"
            "TI Extended BASIC CALL CHAR / CALL HCHAR statements.",
            self,
        )
        body.setWordWrap(True)
        layout.addWidget(header)
        layout.addSpacing(8)
        layout.addWidget(body)
        layout.addStretch()


class _ConverterPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Cached step-1 result, fed to step 2 when the user clicks Generate code.
        self._pixelated: PixelatedImage | None = None

        header = QLabel("TI-99/4A pixel art", self)
        header.setStyleSheet("font-size: 12pt; font-weight: bold;")

        intro = QLabel(
            "Step 1: 'Generate squares' interpolates the active image to the "
            "dot grid below and paints the result onto a new layer so you can "
            "see what the TI will show. Step 2: 'Generate code' turns those "
            "squares into Extended BASIC using character codes in the chosen "
            "range.",
            self,
        )
        intro.setWordWrap(True)

        # --- Dot grid ----------------------------------------------------
        self._cols_edit = QLineEdit(str(DOT_MAX_W), self)
        self._cols_edit.setValidator(QIntValidator(8, DOT_MAX_W, self))
        self._cols_edit.setToolTip(f"Number of TI dots across. Max {DOT_MAX_W}.")

        self._rows_edit = QLineEdit(str(DOT_MAX_H), self)
        self._rows_edit.setValidator(QIntValidator(8, DOT_MAX_H, self))
        self._rows_edit.setToolTip(f"Number of TI dots down. Max {DOT_MAX_H}.")

        # --- Threshold ---------------------------------------------------
        self._threshold_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._threshold_slider.setMinimum(1)
        self._threshold_slider.setMaximum(254)
        self._threshold_slider.setValue(128)
        self._threshold_label = QLabel("128", self)
        self._threshold_label.setMinimumWidth(32)
        self._threshold_slider.valueChanged.connect(
            lambda v: self._threshold_label.setText(str(v))
        )

        # --- Character code range ---------------------------------------
        self._code_start_edit = QLineEdit("32", self)
        self._code_start_edit.setValidator(QIntValidator(32, 255, self))
        self._code_start_edit.setToolTip(
            "First TI character code the plugin may redefine."
        )
        self._code_end_edit = QLineEdit("128", self)
        self._code_end_edit.setValidator(QIntValidator(32, 255, self))
        self._code_end_edit.setToolTip(
            "Last TI character code the plugin may redefine. "
            "Number of unique cells available = end - start + 1."
        )

        # --- Buttons -----------------------------------------------------
        self._generate_squares_button = QPushButton("1. Generate squares", self)
        self._generate_squares_button.setMinimumHeight(28)
        self._generate_squares_button.clicked.connect(self._run_pixelate)

        self._generate_code_button = QPushButton("2. Generate code", self)
        self._generate_code_button.setMinimumHeight(28)
        self._generate_code_button.setEnabled(False)
        self._generate_code_button.clicked.connect(self._run_code)

        self._copy_button = QPushButton("Copy code to clipboard", self)
        self._copy_button.clicked.connect(self._copy_output)

        # --- Status + output --------------------------------------------
        self._status_label = QLabel("", self)
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #d0a040;")

        self._output_edit = QPlainTextEdit(self)
        self._output_edit.setReadOnly(True)
        self._output_edit.setPlaceholderText(
            "Extended BASIC output will appear here after step 2."
        )
        font = self._output_edit.font()
        font.setFamily("Consolas")
        font.setStyleHint(font.Monospace)
        self._output_edit.setFont(font)
        self._output_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # --- Form layout -------------------------------------------------
        form = QGridLayout()
        row = 0
        form.addWidget(QLabel("Dot columns:", self), row, 0)
        form.addWidget(self._cols_edit, row, 1)
        row += 1
        form.addWidget(QLabel("Dot rows:", self), row, 0)
        form.addWidget(self._rows_edit, row, 1)
        row += 1
        form.addWidget(QLabel("Threshold:", self), row, 0)
        threshold_row = QHBoxLayout()
        threshold_row.addWidget(self._threshold_slider, 1)
        threshold_row.addWidget(self._threshold_label, 0)
        form.addLayout(threshold_row, row, 1)
        row += 1
        form.addWidget(QLabel("Char code start:", self), row, 0)
        form.addWidget(self._code_start_edit, row, 1)
        row += 1
        form.addWidget(QLabel("Char code end:", self), row, 0)
        form.addWidget(self._code_end_edit, row, 1)

        buttons_row = QHBoxLayout()
        buttons_row.addWidget(self._generate_squares_button, 1)
        buttons_row.addWidget(self._generate_code_button, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(header)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addLayout(buttons_row)
        layout.addWidget(self._status_label)
        layout.addWidget(self._output_edit, 1)
        layout.addWidget(self._copy_button)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _read_int(self, edit: QLineEdit, name: str) -> int | None:
        try:
            return int(edit.text())
        except ValueError:
            self._status_label.setText(f"{name} must be an integer.")
            return None

    def _require_rgba_u8(self, document) -> bool:
        model = document.colorModel()
        depth = document.colorDepth()
        if model != "RGBA" or depth != "U8":
            self._status_label.setText(
                f"Document must be RGBA/U8 (got {model}/{depth}). "
                "Use Image > Convert Image Color Space."
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Step 1: pixelate + paint preview layer
    # ------------------------------------------------------------------
    def _run_pixelate(self) -> None:
        self._status_label.setText("")
        self._pixelated = None
        self._generate_code_button.setEnabled(False)

        document = Krita.instance().activeDocument()
        if document is None:
            self._status_label.setText("No active document.")
            return
        if not self._require_rgba_u8(document):
            return

        dot_cols = self._read_int(self._cols_edit, "Dot columns")
        dot_rows = self._read_int(self._rows_edit, "Dot rows")
        if dot_cols is None or dot_rows is None:
            return

        width = document.width()
        height = document.height()
        if width <= 0 or height <= 0:
            self._status_label.setText("Active document has zero size.")
            return

        pixels = bytes(document.pixelData(0, 0, width, height))
        try:
            pixelated = pixelate(
                pixels=pixels,
                src_width=width,
                src_height=height,
                dot_cols=dot_cols,
                dot_rows=dot_rows,
                threshold=self._threshold_slider.value(),
            )
        except ValueError as exc:
            self._status_label.setText(str(exc))
            return

        # Paint the squares back onto a new Krita layer covering the canvas.
        bgra = bits_to_bgra(pixelated, out_width=width, out_height=height)
        layer_name = (
            f"TI99 squares ({pixelated.char_cols}x{pixelated.char_rows} chars, "
            f"{pixelated.dot_cols}x{pixelated.dot_rows} dots)"
        )
        node = document.createNode(layer_name, "paintlayer")
        node.setPixelData(bgra, 0, 0, width, height)
        document.rootNode().addChildNode(node, None)
        document.refreshProjection()

        self._pixelated = pixelated
        self._generate_code_button.setEnabled(True)
        self._status_label.setText(
            f"Squares ready: {pixelated.char_cols} x {pixelated.char_rows} "
            f"characters ({pixelated.dot_cols} x {pixelated.dot_rows} dots). "
            "Click 'Generate code' next."
        )

    # ------------------------------------------------------------------
    # Step 2: bits -> BASIC
    # ------------------------------------------------------------------
    def _run_code(self) -> None:
        if self._pixelated is None:
            self._status_label.setText("Run step 1 first.")
            return

        code_start = self._read_int(self._code_start_edit, "Char code start")
        code_end = self._read_int(self._code_end_edit, "Char code end")
        if code_start is None or code_end is None:
            return
        if not (32 <= code_start <= code_end <= 255):
            self._status_label.setText(
                "Character code range must satisfy 32 <= start <= end <= 255."
            )
            return

        try:
            result = bits_to_basic(self._pixelated, code_start, code_end)
        except ValueError as exc:
            self._status_label.setText(str(exc))
            return

        unique = len(result.cells)
        msg = (
            f"{result.char_cols} x {result.char_rows} chars, "
            f"{unique} unique pattern(s) defined "
            f"(codes {code_start}..{code_start + unique - 1 if unique else code_start})."
        )
        if result.skipped_patterns:
            msg += (
                f" {result.skipped_patterns} cell(s) exceeded the code range "
                "and snapped to the nearest pattern — widen the range to keep "
                "more detail."
            )
        self._status_label.setText(msg)
        self._output_edit.setPlainText(result.basic_program)

    # ------------------------------------------------------------------
    def _copy_output(self) -> None:
        text = self._output_edit.toPlainText()
        if not text:
            return
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
            self._status_label.setText("Copied to clipboard.")


class TiPixelArtDockWidget(DockWidget):
    """The dock widget Krita registers as the 'TI99/4A pixel art' tab."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(_TAB_TITLE)

        self._no_document = _NoDocumentPanel()
        self._converter = _ConverterPanel()

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._no_document)
        self._stack.addWidget(self._converter)
        self.setWidget(self._stack)

        self._update_visibility()

    def canvasChanged(self, canvas) -> None:  # type: ignore[override]
        self._update_visibility()

    def _update_visibility(self) -> None:
        if Krita.instance().activeDocument() is not None:
            self._stack.setCurrentWidget(self._converter)
        else:
            self._stack.setCurrentWidget(self._no_document)
