"""ClipWerk – Windows-Programm: Handyvideos rein, fertige Reels raus. Plus: Texte in deiner eigenen Stimme."""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QSpinBox, QStackedWidget, QTextEdit, QVBoxLayout, QWidget)

import engine
import voice

VERSION = "1.0"

# Farben: Scheune bei Abend – dunkles Holz, warmes Lampenlicht, Wiesengrün für "fertig"
QSS = """
* { font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 14px; color: #EDE6DA; }
QMainWindow, #page { background: #1C1915; }
#side { background: #14120F; border-right: 1px solid #2E2923; }
#brand { font-size: 22px; font-weight: 800; color: #F2B544; padding: 18px 18px 2px 18px; }
#brandsub { color: #8C8273; font-size: 12px; padding: 0 18px 16px 18px; }
#nav { text-align: left; padding: 11px 18px; border: none; border-radius: 0; background: transparent; color: #BFB4A3; font-size: 15px; }
#nav:hover { background: #221F1A; color: #FFF; }
#nav:checked { background: #2A251E; color: #F2B544; border-left: 3px solid #F2B544; }
#h1 { font-size: 26px; font-weight: 800; color: #FFF6E6; }
#muted { color: #8C8273; }
#card { background: #24201B; border: 1px solid #332D25; border-radius: 12px; }
QPushButton { background: #2E2923; border: 1px solid #3D362D; border-radius: 8px; padding: 8px 14px; }
QPushButton:hover { background: #3A332A; }
QPushButton:disabled { color: #6B6257; }
#primary { background: #F2B544; color: #1C1915; font-weight: 800; font-size: 16px; border: none; padding: 13px 22px; border-radius: 10px; }
#primary:hover { background: #FFC85C; }
#primary:disabled { background: #5A4A2A; color: #8C8273; }
#chip { padding: 8px 16px; border-radius: 18px; background: #24201B; border: 1px solid #3D362D; }
#chip:checked { background: #F2B544; color: #1C1915; font-weight: 700; border-color: #F2B544; }
QListWidget { background: #24201B; border: 2px dashed #4A4237; border-radius: 12px; padding: 8px; }
QListWidget::item { border-radius: 8px; padding: 4px; color: #D8CFC1; }
QListWidget::item:selected { background: #3A332A; }
QProgressBar { background: #24201B; border: none; border-radius: 6px; height: 12px; text-align: center; color: transparent; }
QProgressBar::chunk { background: #8BC34A; border-radius: 6px; }
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit { background: #24201B; border: 1px solid #3D362D; border-radius: 8px; padding: 7px; selection-background-color: #F2B544; selection-color: #1C1915; }
QCheckBox::indicator { width: 18px; height: 18px; }
QScrollArea { border: none; background: transparent; }
QSlider::groove:horizontal { height: 6px; background: #3D362D; border-radius: 3px; }
QSlider::handle:horizontal { background: #F2B544; width: 16px; margin: -6px 0; border-radius: 8px; }
"""


def label(text, name=None, wrap=True):
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


# ----------------------------------------------------------------------------- Hintergrund-Arbeiter
class Worker(QObject):
    progress = Signal(float, str)
    log = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args

    def run(self):
        try:
            res = self.fn(*self.args, progress=lambda p, m: self.progress.emit(p, m), log=self.log.emit) \
                if self.fn is engine.process else self.fn(*self.args, log=self.log.emit)
            self.done.emit(res)
        except Exception as e:  # noqa: BLE001
            self.log.emit(traceback.format_exc())
            self.failed.emit(str(e))


def start_thread(owner, worker):
    th = QThread(owner)
    worker.moveToThread(th)
    th.started.connect(worker.run)
    worker.done.connect(th.quit)
    worker.failed.connect(th.quit)
    th.finished.connect(th.deleteLater)
    owner._threads = getattr(owner, "_threads", []) + [(th, worker)]
    th.start()


# ----------------------------------------------------------------------------- Ablage für Videos (Drag & Drop)
class DropList(QListWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(150, 150))
        self.setGridSize(QSize(176, 206))
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setMinimumHeight(250)
        self.paths: list[Path] = []

    def dragEnterEvent(self, e):
        e.acceptProposedAction() if e.mimeData().hasUrls() else e.ignore()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dropEvent(self, e):
        self.add([Path(u.toLocalFile()) for u in e.mimeData().urls()])

    def add(self, paths):
        files = []
        for p in paths:
            if p.is_dir():
                files += sorted(x for x in p.rglob("*") if x.suffix.lower() in engine.VIDEO_EXT)
            elif p.suffix.lower() in engine.VIDEO_EXT:
                files.append(p)
        for f in files:
            if f in self.paths:
                continue
            self.paths.append(f)
            thumb = engine.data_dir() / "thumbs" / f"{abs(hash(str(f)))}.jpg"
            try:
                if not thumb.exists():
                    engine.thumbnail(f, thumb, at=0.8, width=300)
                c = engine.probe(f)
                info = f"{int(c.duration // 60)}:{int(c.duration % 60):02d} · {'hoch' if c.vertical else 'quer'}"
            except Exception:  # noqa: BLE001
                info = "?"
            it = QListWidgetItem(QIcon(QPixmap(str(thumb))) if thumb.exists() else QIcon(), f"{f.name[:22]}\n{info}")
            it.setData(Qt.UserRole, str(f))
            it.setToolTip(str(f))
            self.addItem(it)
        self.changed.emit()

    def remove_selected(self):
        for it in self.selectedItems():
            self.paths.remove(Path(it.data(Qt.UserRole)))
            self.takeItem(self.row(it))
        self.changed.emit()

    def clear_all(self):
        self.paths.clear()
        self.clear()
        self.changed.emit()

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.count():
            from PySide6.QtGui import QPainter
            p = QPainter(self.viewport())
            p.setPen(QColor("#8C8273"))
            f = QFont(self.font())
            f.setPointSize(13)
            p.setFont(f)
            p.drawText(self.viewport().rect(), Qt.AlignCenter,
                       "Videos oder ganze Ordner hierher ziehen\n\n(oder unten auf „Videos hinzufügen“ klicken)")


# ----------------------------------------------------------------------------- Seite: Schneiden
class CutPage(QWidget):
    finished = Signal(str)

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setObjectName("page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)
        lay.addWidget(label("Videos schneiden", "h1"))
        lay.addWidget(label("Zieh deine Handyvideos rein – ClipWerk hört zu, wirft Pausen und „ähm“ raus, "
                            "sucht die besten Momente und macht fertige Reels mit Untertiteln.", "muted"))
        # Art des Videos
        row = QHBoxLayout()
        row.addWidget(label("Worum geht's?", wrap=False))
        self.style_group = QButtonGroup(self)
        for key, txt in (("hof", "🚜  Hof && Selbstgemacht"), ("kochen", "🍳  Kochen"), ("allgemein", "📱  Alltag")):
            b = QPushButton(txt)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setProperty("key", key)
            self.style_group.addButton(b)
            row.addWidget(b)
            if key == main.settings.get("style", "hof"):
                b.setChecked(True)
        row.addStretch()
        lay.addLayout(row)
        # Ablage
        self.drop = DropList()
        self.drop.changed.connect(self.update_state)
        lay.addWidget(self.drop, 1)
        row = QHBoxLayout()
        add = QPushButton("＋  Videos hinzufügen")
        add.clicked.connect(self.pick)
        rem = QPushButton("Auswahl entfernen")
        rem.clicked.connect(self.drop.remove_selected)
        clr = QPushButton("Alle entfernen")
        clr.clicked.connect(self.drop.clear_all)
        self.count = label("", "muted", wrap=False)
        for w in (add, rem, clr):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(self.count)
        lay.addLayout(row)
        # Optionen
        card = QFrame()
        card.setObjectName("card")
        g = QGridLayout(card)
        g.setContentsMargins(16, 14, 16, 14)
        g.setHorizontalSpacing(18)
        s = main.settings
        self.n_reels = QSpinBox()
        self.n_reels.setRange(1, 5)
        self.n_reels.setValue(int(s["reels"]))
        self.len_max = QSpinBox()
        self.len_max.setRange(15, 90)
        self.len_max.setSuffix(" s")
        self.len_max.setValue(int(s["reel_max"]))
        self.cb_subs = QCheckBox("Untertitel (Wort für Wort)")
        self.cb_hook = QCheckBox("Hook-Text am Anfang")
        self.cb_music = QCheckBox("Leise Musik darunter")
        self.cb_long = QCheckBox("Zusätzlich lange Fassung")
        for cb, k in ((self.cb_subs, "subtitles"), (self.cb_hook, "hook"), (self.cb_music, "music"), (self.cb_long, "long_version")):
            cb.setChecked(bool(s.get(k, True)))
        g.addWidget(label("Anzahl Reels", wrap=False), 0, 0)
        g.addWidget(self.n_reels, 0, 1)
        g.addWidget(label("Reel-Länge bis", wrap=False), 1, 0)
        g.addWidget(self.len_max, 1, 1)
        g.addWidget(self.cb_subs, 0, 2)
        g.addWidget(self.cb_hook, 1, 2)
        g.addWidget(self.cb_music, 0, 3)
        g.addWidget(self.cb_long, 1, 3)
        g.setColumnStretch(4, 1)
        lay.addWidget(card)
        # Start + Fortschritt
        row = QHBoxLayout()
        self.go = QPushButton("✂   Automatisch schneiden")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self.start)
        row.addWidget(self.go)
        col = QVBoxLayout()
        self.status = label("Bereit.", "muted", wrap=False)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        col.addWidget(self.status)
        col.addWidget(self.bar)
        row.addLayout(col, 1)
        lay.addLayout(row)
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setMaximumHeight(110)
        self.logbox.setPlaceholderText("Protokoll")
        lay.addWidget(self.logbox)
        self.update_state()

    def pick(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Videos auswählen", str(Path.home()),
                                                "Videos (*.mp4 *.mov *.m4v *.mkv *.avi *.3gp *.webm)")
        self.drop.add([Path(f) for f in files])

    def update_state(self):
        n = len(self.drop.paths)
        self.count.setText(f"{n} Video{'s' if n != 1 else ''}" if n else "")
        self.go.setEnabled(n > 0)

    def start(self):
        s = self.main.settings
        s.update(style=self.style_group.checkedButton().property("key") if self.style_group.checkedButton() else "hof",
                 reels=self.n_reels.value(), reel_max=self.len_max.value(), reel_min=max(10, self.len_max.value() - 30),
                 subtitles=self.cb_subs.isChecked(), hook=self.cb_hook.isChecked(), music=self.cb_music.isChecked(),
                 long_version=self.cb_long.isChecked())
        engine.save_settings(s)
        if not s.get("gemini_key"):
            self.logbox.appendPlainText("Hinweis: Ohne Gemini-Schlüssel wählt ClipWerk die Momente nur der Reihe nach aus. "
                                        "Für die beste Auswahl, Hook-Texte und Captions den Schlüssel in den Einstellungen eintragen.")
        out = Path(s["projects_dir"]) / time.strftime(f"%Y-%m-%d_%H%M_{s['style']}")
        self.out = out
        self.go.setEnabled(False)
        self.bar.setValue(0)
        w = Worker(engine.process, list(self.drop.paths), out, dict(s))
        w.progress.connect(lambda p, m: (self.bar.setValue(int(p * 10)), self.status.setText(m)))
        w.log.connect(self.logbox.appendPlainText)
        w.done.connect(self.ok)
        w.failed.connect(self.fail)
        start_thread(self, w)

    def ok(self, res):
        self.go.setEnabled(True)
        self.status.setText(f"Fertig! {len(res['reels'])} Reels erstellt.")
        self.finished.emit(str(self.out))

    def fail(self, msg):
        self.go.setEnabled(True)
        self.status.setText("Abgebrochen.")
        QMessageBox.warning(self, "ClipWerk", f"Das hat leider nicht geklappt:\n\n{msg}")


# ----------------------------------------------------------------------------- Seite: Ergebnisse
class ResultCard(QFrame):
    def __init__(self, folder: Path, item: dict, long=False):
        super().__init__()
        self.setObjectName("card")
        self.setFixedWidth(250)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        img = QLabel()
        pm = QPixmap(str(folder / item.get("thumb", "")))
        if not pm.isNull():
            img.setPixmap(pm.scaled(226, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        img.setAlignment(Qt.AlignCenter)
        img.setMinimumHeight(200)
        v.addWidget(img)
        v.addWidget(label(("Lange Fassung" if long else (item.get("hook") or "Reel")).strip(), wrap=True))
        v.addWidget(label(f"{item['duration']:.0f} s" if item["duration"] < 120 else f"{item['duration'] / 60:.1f} min", "muted"))
        row = QHBoxLayout()
        play = QPushButton("▶ Abspielen")
        play.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder / item["file"]))))
        row.addWidget(play)
        if item.get("caption"):
            cp = QPushButton("Text kopieren")
            cp.setToolTip(item["caption"])

            def copy():
                QApplication.clipboard().setText(item["caption"])
                cp.setText("✓ Kopiert")
            cp.clicked.connect(copy)
            row.addWidget(cp)
        v.addLayout(row)


class ResultsPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setObjectName("page")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        left = QVBoxLayout()
        left.addWidget(label("Ergebnisse", "h1"))
        self.runs = QListWidget()
        self.runs.setStyleSheet("QListWidget{border:1px solid #332D25;border-style:solid;}")
        self.runs.setMaximumWidth(260)
        self.runs.currentItemChanged.connect(self.show_run)
        left.addWidget(self.runs, 1)
        opn = QPushButton("Ordner öffnen")
        opn.clicked.connect(self.open_folder)
        left.addWidget(opn)
        lay.addLayout(left)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        lay.addWidget(self.scroll, 1)
        self.refresh()

    def refresh(self, select: str | None = None):
        self.runs.clear()
        root = Path(self.main.settings["projects_dir"])
        dirs = sorted([d for d in root.glob("*") if (d / "ergebnis.json").exists()], reverse=True) if root.exists() else []
        for d in dirs:
            it = QListWidgetItem(d.name.replace("_", "  ", 1).replace("_", " "))
            it.setData(Qt.UserRole, str(d))
            self.runs.addItem(it)
            if select and str(d) == select:
                self.runs.setCurrentItem(it)
        if self.runs.count() and not self.runs.currentItem():
            self.runs.setCurrentRow(0)
        if not dirs:
            self.scroll.setWidget(label("Noch keine Ergebnisse – schneide zuerst ein paar Videos.", "muted"))

    def show_run(self, it, _=None):
        if not it:
            return
        d = Path(it.data(Qt.UserRole))
        res = json.loads((d / "ergebnis.json").read_text(encoding="utf-8"))
        box = QWidget()
        grid = QGridLayout(box)
        grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        cards = [ResultCard(d, r) for r in res.get("reels", [])]
        if res.get("long"):
            cards.append(ResultCard(d, res["long"], long=True))
        for k, c in enumerate(cards):
            grid.addWidget(c, k // 3, k % 3)
        self.scroll.setWidget(box)

    def open_folder(self):
        it = self.runs.currentItem()
        path = it.data(Qt.UserRole) if it else self.main.settings["projects_dir"]
        Path(path).mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))


# ----------------------------------------------------------------------------- Seite: Stimme
class VoicePage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setObjectName("page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)
        lay.addWidget(label("Meine Stimme", "h1"))
        lay.addWidget(label("Schritt 1: Wähle 3–5 Minuten Aufnahmen von dir (ruhiger Raum, normal gesprochen, keine Musik). "
                            "Schritt 2: Text eintippen – ClipWerk spricht ihn in deiner Stimme. "
                            "Deine Aufnahmen bleiben auf deinem PC; zum Sprechen wird nur eine 25-Sekunden-Probe an deine "
                            "eigene Modal-Cloud geschickt und dort nicht gespeichert.", "muted"))
        c1 = QFrame()
        c1.setObjectName("card")
        v1 = QVBoxLayout(c1)
        v1.addWidget(label("<b>1 · Stimmprobe</b>"))
        self.files = QListWidget()
        self.files.setMaximumHeight(110)
        self.files.setStyleSheet("QListWidget{border:1px solid #332D25;}")
        v1.addWidget(self.files)
        row = QHBoxLayout()
        b = QPushButton("Aufnahmen auswählen")
        b.clicked.connect(self.pick)
        self.mk = QPushButton("Stimme anlegen")
        self.mk.clicked.connect(self.make_ref)
        self.ref_state = label("", "muted", wrap=False)
        row.addWidget(b)
        row.addWidget(self.mk)
        row.addStretch()
        row.addWidget(self.ref_state)
        v1.addLayout(row)
        lay.addWidget(c1)
        c2 = QFrame()
        c2.setObjectName("card")
        v2 = QVBoxLayout(c2)
        v2.addWidget(label("<b>2 · Text sprechen lassen</b>"))
        self.text = QTextEdit()
        self.text.setPlaceholderText("Hier deinen Text eintippen oder einfügen …")
        v2.addWidget(self.text, 1)
        row = QHBoxLayout()
        row.addWidget(label("Ruhig", "muted", wrap=False))
        self.live = QSlider(Qt.Horizontal)
        self.live.setRange(25, 90)
        self.live.setValue(50)
        self.live.setMaximumWidth(200)
        row.addWidget(self.live)
        row.addWidget(label("Lebhaft", "muted", wrap=False))
        self.lang = QComboBox()
        self.lang.addItems(["Deutsch", "Englisch"])
        row.addWidget(self.lang)
        row.addStretch()
        self.say = QPushButton("🎙   In meiner Stimme sprechen")
        self.say.setObjectName("primary")
        self.say.clicked.connect(self.speak)
        row.addWidget(self.say)
        v2.addLayout(row)
        self.vstatus = label("", "muted")
        v2.addWidget(self.vstatus)
        lay.addWidget(c2, 1)
        self.paths = []
        self.update_ref()

    def update_ref(self):
        self.ref_state.setText("✓ Stimmprobe vorhanden" if voice.REF.exists() else "noch keine Stimmprobe")

    def pick(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Aufnahmen auswählen", str(Path.home()),
                                                "Audio/Video (*.wav *.mp3 *.m4a *.aac *.ogg *.flac *.mp4 *.mov)")
        self.paths = [Path(f) for f in files]
        self.files.clear()
        self.files.addItems([p.name for p in self.paths])

    def make_ref(self):
        if not self.paths:
            QMessageBox.information(self, "ClipWerk", "Bitte zuerst Aufnahmen auswählen.")
            return
        self.mk.setEnabled(False)
        w = Worker(voice.build_reference, self.paths)
        w.log.connect(self.vstatus.setText)
        w.done.connect(lambda _: (self.mk.setEnabled(True), self.update_ref()))
        w.failed.connect(lambda m: (self.mk.setEnabled(True), QMessageBox.warning(self, "ClipWerk", m)))
        start_thread(self, w)

    def speak(self):
        txt = self.text.toPlainText().strip()
        if not txt:
            return
        out = Path(self.main.settings["projects_dir"]) / "Stimme" / time.strftime("stimme_%Y-%m-%d_%H%M%S.wav")
        self.say.setEnabled(False)
        self.vstatus.setText("Spreche … (beim ersten Mal ca. 1–2 Minuten)")
        lang = "de" if self.lang.currentIndex() == 0 else "en"
        w = Worker(lambda t, o, s, log: voice.speak(t, o, s, lang, self.live.value() / 100, log),
                   txt, out, dict(self.main.settings))
        w.log.connect(self.vstatus.setText)

        def ok(p):
            self.say.setEnabled(True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
        w.done.connect(ok)
        w.failed.connect(lambda m: (self.say.setEnabled(True), QMessageBox.warning(self, "ClipWerk", m)))
        start_thread(self, w)


# ----------------------------------------------------------------------------- Seite: Einstellungen
class SettingsPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setObjectName("page")
        s = main.settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(12)
        lay.addWidget(label("Einstellungen", "h1"))
        card = QFrame()
        card.setObjectName("card")
        g = QGridLayout(card)
        g.setContentsMargins(18, 16, 18, 16)
        g.setVerticalSpacing(12)
        r = 0

        def row(title, widget, hint=""):
            nonlocal r
            g.addWidget(label(f"<b>{title}</b>", wrap=False), r, 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.addWidget(widget)
            if hint:
                h = label(hint, "muted")
                h.setOpenExternalLinks(True)
                col.addWidget(h)
            g.addLayout(col, r, 1)
            r += 1
        self.gem = QLineEdit(s["gemini_key"])
        self.gem.setEchoMode(QLineEdit.Password)
        row("Gemini-Schlüssel", self.gem, 'Für die beste Auswahl, Hook-Texte und Captions. Kostenlos holen: '
            '<a style="color:#F2B544" href="https://aistudio.google.com/apikey">aistudio.google.com/apikey</a>')
        self.model = QComboBox()
        self.model.addItems(["small", "medium", "large-v3"])
        self.model.setCurrentText(s["whisper_model"])
        row("Spracherkennung", self.model, "small = schnell · medium = genauer · large-v3 = am genauesten, aber langsam")
        self.vis = QCheckBox("Bilder verstehen (beste Bildmomente finden)")
        self.vis.setChecked(bool(s.get("vision", True)))
        row("Bildanalyse", self.vis, "Unscharfes/Wackeliges fliegt immer raus (lokal). Mit Gemini-Schlüssel werden zusätzlich "
            "kleine Standbilder (keine Videos) bewertet: Ergebnis, Vorher/Nachher, Aktion, Essen, Tiere …")
        self.music = QLineEdit(s["music_dir"])
        mb = QPushButton("Ordner wählen")
        mb.clicked.connect(lambda: self.music.setText(QFileDialog.getExistingDirectory(self, "Musikordner") or self.music.text()))
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.music)
        h.addWidget(mb)
        row("Musikordner", w, 'Eigene, lizenzfreie Musik (mp3/wav). Kostenlos z. B. in der '
            '<a style="color:#F2B544" href="https://www.youtube.com/audiolibrary">YouTube-Audiomediathek</a>.')
        self.proj = QLineEdit(s["projects_dir"])
        row("Ergebnis-Ordner", self.proj)
        self.color = QPushButton(s["highlight_color"])
        self.color.setStyleSheet(f"background:{s['highlight_color']};color:#1C1915;font-weight:700;")

        def pick_color():
            c = QColorDialog.getColor(QColor(self.color.text()), self, "Farbe für das aktive Wort")
            if c.isValid():
                self.color.setText(c.name().upper())
                self.color.setStyleSheet(f"background:{c.name()};color:#1C1915;font-weight:700;")
        self.color.clicked.connect(pick_color)
        row("Farbe aktives Wort", self.color)
        self.mid = QLineEdit(s["modal_token_id"])
        self.msec = QLineEdit(s["modal_token_secret"])
        self.msec.setEchoMode(QLineEdit.Password)
        w2 = QWidget()
        h2 = QHBoxLayout(w2)
        h2.setContentsMargins(0, 0, 0, 0)
        self.mid.setPlaceholderText("Token-ID (ak-…)")
        self.msec.setPlaceholderText("Token-Secret (as-…)")
        h2.addWidget(self.mid)
        h2.addWidget(self.msec)
        row("Modal (für Stimme)", w2, 'Neuen Token anlegen: <a style="color:#F2B544" href="https://modal.com/settings/tokens">'
            'modal.com/settings/tokens</a> – bleibt nur auf diesem PC gespeichert.')
        lay.addWidget(card)
        save = QPushButton("Speichern")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        lay.addWidget(save, 0, Qt.AlignLeft)
        lay.addStretch()
        lay.addWidget(label(f"ClipWerk {VERSION} · Einstellungen liegen in {engine.data_dir()}", "muted"))

    def save(self):
        self.main.settings.update(gemini_key=self.gem.text().strip(), whisper_model=self.model.currentText(),
                                  vision=self.vis.isChecked(),
                                  music_dir=self.music.text().strip(), projects_dir=self.proj.text().strip(),
                                  highlight_color=self.color.text(), modal_token_id=self.mid.text().strip(),
                                  modal_token_secret=self.msec.text().strip())
        engine.save_settings(self.main.settings)
        QMessageBox.information(self, "ClipWerk", "Gespeichert.")


# ----------------------------------------------------------------------------- Hauptfenster
class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = engine.load_settings()
        self.setWindowTitle("ClipWerk")
        self.resize(1240, 820)
        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(220)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 12)
        sv.setSpacing(2)
        sv.addWidget(label("ClipWerk", "brand", wrap=False))
        sv.addWidget(label("vom Handy zum Reel", "brandsub", wrap=False))
        self.stack = QStackedWidget()
        self.cut = CutPage(self)
        self.results = ResultsPage(self)
        pages = [("✂   Schneiden", self.cut), ("🎞   Ergebnisse", self.results), ("🎙   Meine Stimme", VoicePage(self)),
                 ("⚙   Einstellungen", SettingsPage(self))]
        grp = QButtonGroup(self)
        for i, (txt, page) in enumerate(pages):
            self.stack.addWidget(page)
            b = QPushButton(txt)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self.go(i))
            grp.addButton(b, i)
            sv.addWidget(b)
            if i == 0:
                b.setChecked(True)
        self.nav = grp
        sv.addStretch()
        h.addWidget(side)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.cut.finished.connect(self.after_cut)

    def go(self, i):
        self.nav.button(i).setChecked(True)
        if self.stack.widget(i) is self.results:
            self.results.refresh()
        self.stack.setCurrentIndex(i)

    def after_cut(self, folder):
        self.results.refresh(select=folder)
        self.go(1)


def main():
    import io
    import os
    if sys.stdout is None:                          # Fenster-Programm ohne Konsole: Ausgaben ins Leere statt Absturz
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    _ = io
    if "--selftest" in sys.argv:                    # für den automatischen Test beim Bauen
        i = sys.argv.index("--selftest")
        vids = [Path(p) for p in sys.argv[i + 1:]]
        s = engine.load_settings()
        s.update(music=False, whisper_model="tiny", language=None)
        logf = open("selftest.log", "w", encoding="utf-8")
        try:
            res = engine.process(vids, Path("selftest_out"), s,
                                 progress=lambda p, m: (logf.write(f"[{p:5.1f}%] {m}\n"), logf.flush()),
                                 log=lambda m: (logf.write(m + "\n"), logf.flush()))
            logf.write(json.dumps(res, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            logf.write(traceback.format_exc())
            raise
        finally:
            logf.close()
        return
    app = QApplication(sys.argv)
    app.setApplicationName("ClipWerk")
    shots = sys.argv[sys.argv.index("--screenshots") + 1] if "--screenshots" in sys.argv else None
    ico = engine.app_dir() / "assets" / "clipwerk.ico"
    if ico.exists():
        app.setWindowIcon(QIcon(str(ico)))
    f = engine.font_file()
    if f:
        QFontDatabase.addApplicationFont(str(f))
    app.setStyleSheet(QSS)
    w = Main()
    w.show()
    if shots:                                       # Bilder aller Seiten für die Vorschau beim Bauen
        Path(shots).mkdir(parents=True, exist_ok=True)
        demo = [Path(p) for p in sys.argv[sys.argv.index("--screenshots") + 2:]]
        if demo:
            w.cut.drop.add(demo)
        for i in range(w.stack.count()):
            w.go(i)
            app.processEvents()
            w.grab().save(str(Path(shots) / f"seite_{i + 1}.png"))
        return
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

_ = (QSizePolicy,)
