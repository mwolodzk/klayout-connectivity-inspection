# SPDX-License-Identifier: GPL-3.0-or-later
"""In-application SDL/Connectivity Inspection user manual."""

from pathlib import Path

import pya


MANUAL_PATH = Path(__file__).with_name("SDLUserManual.html")


class SDLUserManualDialog(pya.QDialog):
    """Non-modal, reusable manual window bundled with the plugin."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SDL / CAS User Manual")
        self.resize(940, 760)

        layout = pya.QVBoxLayout(self)
        self.browser = pya.QTextBrowser(self)
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(MANUAL_PATH.read_text(encoding="utf-8"))
        layout.addWidget(self.browser)

        close_button = pya.QPushButton("Close", self)
        close_button.clicked.connect(self.close)
        button_row = pya.QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

    def show_section(self, anchor="quick-start"):
        self.show()
        self.raise_()
        self.activateWindow()
        self.browser.scrollToAnchor(anchor)
