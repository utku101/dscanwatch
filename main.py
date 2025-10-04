# eve_dscan_clipboard_watcher.py
# Always-on-top PyQt5 app that:
# - Watches clipboard text and auto-fills "D-Scan Input"
# - Auto-analyzes on clipboard change
# - Shows results in two side-by-side boxes: "By Group" and "By Type"
# Requires: ship_index.json (same directory)

import sys
import json
from pathlib import Path
from collections import Counter
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPlainTextEdit, QLabel, QMessageBox
)
from PyQt5.QtCore import Qt

APP_TITLE = "EVE D-Scan (Clipboard Auto)"
INDEX_FILE = "ship_index.json"
INPUT_HINT = "Clipboard-driven: copy your D-Scan text (Ctrl+C) anywhere; it will appear here."
RESULTS_HINT_G = "By Group results will appear here."
RESULTS_HINT_T = "By Type results will appear here."

def load_ship_index(base: Path):
    p = base / INDEX_FILE
    if not p.exists():
        return None, f"ERROR: {INDEX_FILE} not found next to the script."
    try:
        with p.open("r", encoding="utf-8") as f:
            raw = json.load(f)  # {typeName: groupName}
        # Case-insensitive lookup; prefer longest names first to avoid partial collisions
        norm = {k.lower(): (k, v) for k, v in raw.items()}
        keys = sorted(norm.keys(), key=len, reverse=True)
        return (norm, keys), None
    except Exception as e:
        return None, f"ERROR: failed to load {INDEX_FILE}: {e}"

def analyze(text: str, norm_index, sorted_keys):
    """For each non-empty line: longest-first substring match to a known ship name."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    by_group = Counter()
    by_type = Counter()
    matched = 0

    for ln in lines:
        low = ln.lower()
        for key in sorted_keys:
            if key in low:
                type_name, group_name = norm_index[key]
                by_group[group_name] += 1
                by_type[type_name] += 1
                matched += 1
                break  # move to next line
    return by_group, by_type, matched, len(lines)

def format_by_group(by_group, matched, total):
    lines = []
    lines.append("=== BY GROUP ===")
    lines.append(f"Lines matched: {matched}/{total}")
    lines.append("")
    if by_group:
        for g, c in sorted(by_group.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"{g}: {c}")
    else:
        lines.append("(no ship lines matched)")
    return "\n".join(lines)

def format_by_type(by_type, matched, total):
    lines = []
    lines.append("=== BY TYPE ===")
    lines.append(f"Lines matched: {matched}/{total}")
    lines.append("")
    if by_type:
        for t, c in sorted(by_type.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"{t}: {c}")
    else:
        lines.append("(no ship lines matched)")
    return "\n".join(lines)

class Main(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        # Load ship index
        base = Path(__file__).resolve().parent
        loaded, err = load_ship_index(base)
        if err:
            QMessageBox.critical(self, "Error", err)
            self.index = None
        else:
            self.index = loaded  # (norm_index, sorted_keys)

        # UI
        root = QVBoxLayout(self)

        # Input (read-only; clipboard-driven)
        root.addWidget(QLabel("D-Scan Input:", self))
        self.input = QPlainTextEdit(self)
        self.input.setReadOnly(True)
        self.input.setPlaceholderText(INPUT_HINT)
        self.input.setMaximumHeight(140)
        root.addWidget(self.input)

        # Results side-by-side
        row = QHBoxLayout()
        # Left: By Group
        left_col = QVBoxLayout()
        left_col.addWidget(QLabel("By Group:", self))
        self.out_group = QPlainTextEdit(self)
        self.out_group.setReadOnly(True)
        self.out_group.setPlaceholderText(RESULTS_HINT_G)
        left_col.addWidget(self.out_group)
        row.addLayout(left_col)

        # Right: By Type
        right_col = QVBoxLayout()
        right_col.addWidget(QLabel("By Type:", self))
        self.out_type = QPlainTextEdit(self)
        self.out_type.setReadOnly(True)
        self.out_type.setPlaceholderText(RESULTS_HINT_T)
        right_col.addWidget(self.out_type)
        row.addLayout(right_col)

        root.addLayout(row)

        # Clipboard watcher
        self.cb = QApplication.clipboard()
        self.cb.dataChanged.connect(self.on_clipboard_changed)

        # Initial prime (if clipboard already has text)
        self.on_clipboard_changed()

    def on_clipboard_changed(self):
        if not self.index:
            return
        text = self.cb.text().strip()
        self.input.setPlainText(text if text else "")
        if not text:
            self.out_group.setPlainText("(no input)")
            self.out_type.setPlainText("(no input)")
            return

        norm_index, sorted_keys = self.index
        by_group, by_type, matched, total = analyze(text, norm_index, sorted_keys)
        self.out_group.setPlainText(format_by_group(by_group, matched, total))
        self.out_type.setPlainText(format_by_type(by_type, matched, total))

def main():
    app = QApplication(sys.argv)
    w = Main()
    w.resize(900, 600)
    w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
