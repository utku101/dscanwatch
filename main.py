# main.py
import sys, json, re
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPlainTextEdit, QLabel, QMessageBox,
    QFrame, QComboBox, QSpinBox, QColorDialog, QMenuBar, QAction,
    QSizePolicy, QPushButton, QShortcut, QDialog, QVBoxLayout as QV, QSlider, QDialogButtonBox
)
from PyQt5.QtGui import QFont, QPalette, QColor, QKeySequence
from PyQt5.QtCore import Qt, QPoint, QEvent

APP_TITLE = "EVE D-Scan (Clipboard Auto)"
INDEX_FILES = ["ship_index.json"]

MIN_LINES_FOR_VALIDATION = 3
ID_LINE_RE = re.compile(r"^\s*\d+\b")             # line must start with a numeric id
SPLIT_SPACES_RE = re.compile(r"\s{2,}")           # fallback: 2+ spaces
SYSTEM_TOKEN_RE = re.compile(r"^[A-Z0-9-]{2,}$")

STRUCTURE_TYPES = {
    "Keepstar","Fortizar","Astrahus","Azbel","Sotiyo","Raitaru","Athanor","Tatara",
    "Ihub","TCU","POS","POS Tower","Engineering Complex","Refinery","Citadel"
}

def eve_now_str():
    return datetime.now(timezone.utc).strftime("%m/%d/%Y %H:%M")  # EVE time = UTC

def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def load_ship_index():
    base = app_dir()
    tried = []
    for name in INDEX_FILES:
        p = base / name
        tried.append(str(p))
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                raw = json.load(f)  # {typeName: groupName}
            type_to_group = {k.lower(): v for k, v in raw.items()}
            return (type_to_group,), None
    return None, "Index JSON not found.\nTried:\n" + "\n".join(tried)

def split_columns(line: str):
    if "\t" in line:
        return [part.strip() for part in line.split("\t")]
    return [part.strip() for part in SPLIT_SPACES_RE.split(line)]

def parse_dscan(text: str):
    rows = []
    for ln in text.splitlines():
        raw = ln.rstrip("\r\n")
        if not raw.strip():
            continue
        parts = split_columns(raw)
        _id = parts[0] if len(parts) >= 1 else ""
        name = parts[1] if len(parts) >= 2 else ""
        typ  = parts[2] if len(parts) >= 3 else ""
        dist = parts[3] if len(parts) >= 4 else ""
        if name == "" and typ == "" and len(parts) >= 2:
            _id = ""
            name = parts[0]
            typ  = parts[1] if len(parts) >= 2 else ""
            dist = parts[2] if len(parts) >= 3 else ""
        rows.append({"id": _id, "name": name, "type": typ, "dist": dist, "raw": raw})
    return rows

def extract_system_from_rows(rows):
    for r in rows:
        name = (r["name"] or "").strip()
        typ  = (r["type"] or "").strip()
        if not name or not typ:
            continue
        if typ in STRUCTURE_TYPES or "Complex" in typ or "Refinery" in typ or "Citadel" in typ:
            if " - " in name:
                token = name.split(" - ", 1)[0].strip()
                if SYSTEM_TOKEN_RE.match(token):
                    return token
    return None

def analyze_rows(rows, type_to_group):
    by_type = Counter()
    by_group = Counter()
    matched = 0
    total = len(rows)
    for r in rows:
        typ = (r["type"] or "").strip()
        if not typ:
            by_type["Unknown"] += 1
            by_group["Unknown"] += 1
            continue
        matched += 1
        by_type[typ] += 1
        group = type_to_group.get(typ.lower(), "Unknown")
        by_group[group] += 1
    return by_group, by_type, matched, total

def looks_like_dscan(text: str, type_to_group) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < MIN_LINES_FOR_VALIDATION:
        return False
    # 1) enough lines should start with a numeric ID
    id_lines = [ln for ln in lines if ID_LINE_RE.match(ln)]
    if len(id_lines) / len(lines) < 0.7:
        return False
    # 2) among id_lines, most should have a non-empty Type column (3rd col)
    has_type = 0
    for ln in id_lines:
        parts = split_columns(ln)
        typ = parts[2].strip() if len(parts) >= 3 else ""
        if typ:
            has_type += 1
    if has_type / len(id_lines) < 0.6:
        return False
    return True

def fmt_with_delta(title, curr: Counter, matched, total, prev: Counter,
                   stamp: str, idx: int, total_snaps: int, system_name: str | None):
    all_names = set(curr.keys()) | (set(prev.keys()) if prev else set())
    rows_sorted = sorted(all_names, key=lambda n: (-curr.get(n, 0), n))

    rows = []
    for name in rows_sorted:
        c = curr.get(name, 0)
        p = prev.get(name, 0) if prev else 0
        delta = c - p
        if prev:
            if   delta > 0: rows.append(f"{name}: {c} (+{delta})")
            elif delta < 0: rows.append(f"{name}: {c} ({delta})")
            else:           rows.append(f"{name}: {c}")
        else:
            rows.append(f"{name}: {c}")

    if not rows:
        rows = ["(no ships matched)"]

    # Başlık sade: sadece title ve matched satırı
    head = [f"=== {title} ===", f"Lines matched: {matched}/{total}", ""]

    # Alt bilgi: System / Time / Snapshot (sırayla ve sonda)
    foot = []
    if system_name:
        foot.append(f"System: {system_name}")
    foot.append(f"EVE Time: {stamp}")
    foot.append(f"Snapshot: {idx+1}/{total_snaps}")

    return "\n".join(head + rows + [""] + foot)

from PyQt5.QtCore import Qt, QPoint, QEvent  # make sure QEvent is imported

class OverlayWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._opacity = 0.88
        self.setWindowOpacity(self._opacity)
        self._drag_origin = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setFrameStyle(QPlainTextEdit.NoFrame)
        self.text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.text.setStyleSheet("QPlainTextEdit { background-color: rgba(0,0,0,128); color: white; }")

        # IMPORTANT: install filter on the viewport (it gets the mouse events)
        self.text.viewport().setCursor(Qt.SizeAllCursor)   # visual hint
        self.text.viewport().installEventFilter(self)

        lay.addWidget(self.text)

        self.resize(420, 280)
        self.move(100, 100)

    def eventFilter(self, obj, event):
        # Drag the whole overlay when the mouse is on the text viewport
        if obj is self.text.viewport():
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_origin = event.globalPos() - self.frameGeometry().topLeft()
                return True
            if event.type() == QEvent.MouseMove and (event.buttons() & Qt.LeftButton):
                if self._drag_origin is not None:
                    self.move(event.globalPos() - self._drag_origin)
                    return True
            if event.type() == QEvent.MouseButtonRelease:
                self._drag_origin = None
                return True
        return super().eventFilter(obj, event)

    def set_text(self, s: str):
        self.text.setPlainText(s)

    def apply_style(self, font_size: int, text_color: QColor, bg_color: QColor):
        f = QFont("Consolas"); f.setPointSize(font_size)
        self.text.setFont(f)
        rgba = f"rgba({bg_color.red()},{bg_color.green()},{bg_color.blue()},128)"
        self.text.setStyleSheet(f"QPlainTextEdit {{ background-color: {rgba}; color: {text_color.name()}; }}")

    def set_overlay_opacity(self, frac: float):
        self._opacity = max(0.3, min(1.0, frac))
        self.setWindowOpacity(self._opacity)
    # drag the whole overlay by dragging anywhere
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_origin = e.globalPos() - self.frameGeometry().topLeft()
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_origin is not None and (e.buttons() & Qt.LeftButton):
            self.move(e.globalPos() - self._drag_origin)
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_origin = None
        super().mouseReleaseEvent(e)

class OverlayOpacityDialog(QDialog):
    def __init__(self, current_frac: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Overlay Opacity")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        v = QV(self)
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(30, 100)  # 30% - 100%
        self.slider.setValue(int(current_frac * 100))
        v.addWidget(self.slider)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

    def value_frac(self) -> float:
        return self.slider.value() / 100.0

# ---------- Main Window ----------
class Main(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self._always_on_top = True
        self._apply_always_on_top_flag()

        loaded, err = load_ship_index()
        if err:
            QMessageBox.critical(self, "Error", err)
            self.index = None
        else:
            self.index = loaded  # (type_to_group,)

        self.mode = "By Group"
        self.font_size = 11
        self.text_color = QColor("#EAEAEA")
        self.bg_color = QColor("#1E1E1E")

        self.tracking_enabled = True
        self.snaps = []
        self.view_idx = -1

        self.overlay = None  # created on demand

        root = QVBoxLayout(self)

        # Menus
        menubar = QMenuBar(self)
        menu_view = menubar.addMenu("View")
        menu_app  = menubar.addMenu("Appearance")
        menu_track = menubar.addMenu("Tracking")
        menu_nav = menubar.addMenu("Navigate")

        # Show Input
        self.act_show_input = QAction("Show Input", self, checkable=True)
        self.act_show_input.setChecked(False)
        self.act_show_input.toggled.connect(self.toggle_input_panel)
        menu_view.addAction(self.act_show_input)

        # Always on Top
        self.act_always_on_top = QAction("Always on Top", self, checkable=True)
        self.act_always_on_top.setChecked(True)
        self.act_always_on_top.toggled.connect(self.on_toggle_always_on_top)
        menu_view.addAction(self.act_always_on_top)

        # Transparent Overlay
        self.act_overlay = QAction("Show Transparent Overlay", self, checkable=True)
        self.act_overlay.setChecked(False)
        self.act_overlay.toggled.connect(self.on_toggle_overlay)
        menu_view.addAction(self.act_overlay)

        # Overlay opacity popup
        self.act_overlay_opacity = QAction("Overlay Opacity…", self)
        self.act_overlay_opacity.triggered.connect(self.open_overlay_opacity)
        menu_view.addAction(self.act_overlay_opacity)

        # Ignore non D-Scan
        self.act_ignore_non_dscan = QAction("Ignore non D-Scan format", self, checkable=True)
        self.act_ignore_non_dscan.setChecked(True)
        menu_view.addAction(self.act_ignore_non_dscan)

        # Appearance
        a_txt = QAction("Text Color…", self); a_txt.triggered.connect(self.pick_text_color); menu_app.addAction(a_txt)
        a_bg  = QAction("Background…", self); a_bg.triggered.connect(self.pick_bg_color);  menu_app.addAction(a_bg)

        # Tracking
        self.act_tracking_enable = QAction("Enable Fleet Tracking", self, checkable=True)
        self.act_tracking_enable.setChecked(True)
        self.act_tracking_enable.toggled.connect(lambda v: setattr(self, "tracking_enabled", v))
        menu_track.addAction(self.act_tracking_enable)

        a_reset = QAction("Reset Baseline", self); a_reset.triggered.connect(self.reset_baseline); menu_track.addAction(a_reset)

        # Navigation + shortcuts
        self.act_prev = QAction("Previous Snapshot", self); self.act_prev.setShortcut(QKeySequence(Qt.Key_Left));  self.act_prev.triggered.connect(self.go_prev); menu_nav.addAction(self.act_prev)
        self.act_next = QAction("Next Snapshot", self);     self.act_next.setShortcut(QKeySequence(Qt.Key_Right)); self.act_next.triggered.connect(self.go_next); menu_nav.addAction(self.act_next)
        QShortcut(QKeySequence(Qt.Key_Left),  self, activated=self.go_prev)
        QShortcut(QKeySequence(Qt.Key_Up),    self, activated=self.go_prev)
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=self.go_next)
        QShortcut(QKeySequence(Qt.Key_Down),  self, activated=self.go_next)

        root.setMenuBar(menubar)

        # Controls
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Mode:"))
        self.cmbMode = QComboBox(); self.cmbMode.addItems(["By Group", "By Type"]); self.cmbMode.currentTextChanged.connect(self.on_mode_change)
        controls.addWidget(self.cmbMode)
        controls.addSpacing(8)
        controls.addWidget(QLabel("Font:"))
        self.spinFont = QSpinBox(); self.spinFont.setRange(8, 32); self.spinFont.setValue(self.font_size); self.spinFont.valueChanged.connect(self.on_font_size_change)
        controls.addWidget(self.spinFont)
        controls.addStretch(1)
        btnPrev = QPushButton("◀ Prev"); btnPrev.clicked.connect(self.go_prev); controls.addWidget(btnPrev)
        btnNext = QPushButton("Next ▶"); btnNext.clicked.connect(self.go_next); controls.addWidget(btnNext)
        root.addLayout(controls)

        # Results
        root.addWidget(QLabel("Results:"))
        self.out = QPlainTextEdit(self); self.out.setReadOnly(True)
        self.out.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self.out, stretch=1)

        # Clipboard preview (collapsible)
        self.input_panel = QFrame(self); self.input_panel.setFrameShape(QFrame.NoFrame)
        v_in = QVBoxLayout(self.input_panel)
        v_in.addWidget(QLabel("D-Scan Input (clipboard preview):"))
        self.input = QPlainTextEdit(self); self.input.setReadOnly(True); self.input.setMaximumHeight(100)
        self.input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.input.setPlaceholderText("Copy your D-Scan text (Ctrl+C) anywhere; it will appear here automatically.")
        v_in.addWidget(self.input)
        self.input_panel.setVisible(False)
        root.addWidget(self.input_panel, stretch=0)

        self.apply_result_style()

        # Clipboard watcher
        self.cb = QApplication.clipboard()
        self.cb.dataChanged.connect(self.on_clipboard_changed)
        self.on_clipboard_changed()

        self.resize(520, 380)

    # ----- window flags -----
    def _apply_always_on_top_flag(self):
        flags = self.windowFlags()
        if self._always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    def on_toggle_always_on_top(self, checked: bool):
        self._always_on_top = checked
        self._apply_always_on_top_flag()

    # ----- overlay -----
    def on_toggle_overlay(self, checked: bool):
        if checked:
            if self.overlay is None:
                self.overlay = OverlayWindow(self)
                self.overlay.apply_style(self.font_size, self.text_color, self.bg_color)
            self.overlay.show()
            if self.snaps:
                self.overlay.set_text(self.out.toPlainText())
        else:
            if self.overlay:
                self.overlay.hide()

    def open_overlay_opacity(self):
        if self.overlay is None:
            self.overlay = OverlayWindow(self)
            self.overlay.apply_style(self.font_size, self.text_color, self.bg_color)
        dlg = OverlayOpacityDialog(self.overlay._opacity, self)
        if dlg.exec_() == QDialog.Accepted:
            self.overlay.set_overlay_opacity(dlg.value_frac())

    # ----- tracking / navigation -----
    def reset_baseline(self):
        if self.view_idx >= 0 and self.view_idx < len(self.snaps):
            snap = self.snaps[self.view_idx]
            base = {k: (v.copy() if isinstance(v, Counter) else v) for k, v in snap.items()}
            self.snaps.insert(self.view_idx, base)
            self.view_idx += 1
            self.render_current()

    def go_prev(self):
        if self.view_idx > 0:
            self.view_idx -= 1
            self.render_current()

    def go_next(self):
        if self.view_idx < len(self.snaps) - 1:
            self.view_idx += 1
            self.render_current()

    # ----- ui actions -----
    def on_mode_change(self, txt):
        self.mode = txt
        self.render_current()

    def on_font_size_change(self, val):
        self.font_size = val
        self.apply_result_style()
        if self.overlay and self.overlay.isVisible():
            self.overlay.apply_style(self.font_size, self.text_color, self.bg_color)

    def pick_text_color(self):
        c = QColorDialog.getColor(self.text_color, self, "Select text color")
        if c.isValid():
            self.text_color = c
            self.apply_result_style()
            if self.overlay and self.overlay.isVisible():
                self.overlay.apply_style(self.font_size, self.text_color, self.bg_color)

    def pick_bg_color(self):
        c = QColorDialog.getColor(self.bg_color, self, "Select background color")
        if c.isValid():
            self.bg_color = c
            self.apply_result_style()
            if self.overlay and self.overlay.isVisible():
                self.overlay.apply_style(self.font_size, self.text_color, self.bg_color)

    def apply_result_style(self):
        font = QFont("Consolas"); font.setPointSize(self.font_size)
        self.out.setFont(font)
        pal = self.out.palette(); pal.setColor(QPalette.Base, self.bg_color); pal.setColor(QPalette.Text, self.text_color)
        self.out.setPalette(pal)

    def toggle_input_panel(self, checked: bool):
        self.input_panel.setVisible(checked)
        if checked and self.snaps:
            curr = self.snaps[self.view_idx if self.view_idx >= 0 else len(self.snaps)-1]
            self.input.setPlainText(curr.get("raw", "") or "")

    # ----- clipboard pipeline -----
    def on_clipboard_changed(self):
        if not self.index:
            return
        text = (self.cb.text() or "").strip()
        type_to_group, = self.index

        if self.act_ignore_non_dscan.isChecked():
            if not looks_like_dscan(text, type_to_group):
                return
        if not text:
            return

        rows = parse_dscan(text)
        if not rows:
            return

        by_group, by_type, matched, total = analyze_rows(rows, type_to_group)

        # ignore exact duplicate raw
        if self.snaps and self.snaps[-1]["raw"] == text:
            return

        system_name = extract_system_from_rows(rows)
        snap = {
            "ts": eve_now_str(),
            "by_group": by_group,
            "by_type": by_type,
            "matched": matched,
            "total": total,
            "raw": text,
            "rows": rows,
            "system": system_name
        }
        self.snaps.append(snap)
        self.view_idx = len(self.snaps) - 1

        if self.input_panel.isVisible():
            self.input.setPlainText(text)

        self.render_current()

    # ----- rendering -----
    def render_current(self):
        if not self.snaps:
            self.out.setPlainText("(no snapshots)")
            self.setWindowTitle(APP_TITLE)
            return
        i = max(0, min(self.view_idx, len(self.snaps)-1))
        self.view_idx = i
        curr = self.snaps[i]
        prev = self.snaps[i-1] if i > 0 else None

        title = "BY TYPE" if self.mode == "By Type" else "BY GROUP"
        counter = curr["by_type"] if self.mode == "By Type" else curr["by_group"]
        prev_ctr = (prev["by_type"] if (prev and self.mode == "By Type") else (prev["by_group"] if prev else None))

        block = fmt_with_delta(
            title, counter, curr["matched"], curr["total"],
            prev_ctr, curr["ts"], i, len(self.snaps), curr.get("system"),
        )
        self.out.setPlainText(block)
        syslabel = f" | System: {curr['system']}" if curr.get("system") else ""
        self.setWindowTitle(f"{APP_TITLE}  |  {curr['ts']} (EVE){syslabel}  |  {i+1}/{len(self.snaps)}")

        # keep overlay in sync
        if self.overlay and self.overlay.isVisible():
            self.overlay.set_text(block)

    def closeEvent(self, e):
        if self.overlay:
            self.overlay.close()
        super().closeEvent(e)

def main():
    app = QApplication(sys.argv)
    w = Main()
    w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
