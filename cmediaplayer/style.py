"""The application's Qt stylesheet.

Transparent "frosted glass" theme. Top-level windows are marked with
WA_TranslucentBackground and paint nothing themselves, so the desktop shows
through wherever a widget doesn't draw an opaque background. The video surface
stays opaque (mpv), while the chrome (playlist, transport bars) uses
semi-transparent fills for the see-through look.
"""

ACCENT = "#e0b64a"

STYLE = """
* { font-family: 'Inter', 'Noto Sans', sans-serif; font-size: 13px; color: #eceae6; }
QMainWindow, QWidget#central { background: transparent; }

QWidget#sidePanel { background-color: rgba(18, 20, 28, 0.68); border-left: 1px solid rgba(255,255,255,0.06); }
QWidget#transportBar { background-color: rgba(14, 16, 22, 0.72); border-top: 1px solid rgba(255,255,255,0.05); }

QListWidget { background-color: rgba(255,255,255,0.03); border: none; outline: none; padding: 4px; border-radius: 10px; }
QListWidget::item { padding: 9px 10px; border-radius: 7px; margin: 2px 2px; }
QListWidget::item:selected { background-color: rgba(224,182,74,0.16); color: %(accent)s; }
QListWidget::item:hover:!selected { background-color: rgba(255,255,255,0.06); }

QPushButton { background-color: rgba(255,255,255,0.055); border: 1px solid rgba(255,255,255,0.10);
              border-radius: 9px; padding: 7px 13px; color: #eceae6; }
QPushButton:hover { background-color: rgba(255,255,255,0.12); border-color: rgba(224,182,74,0.65); }
QPushButton:pressed { background-color: rgba(224,182,74,0.22); }
QPushButton#accent { background-color: %(accent)s; color: #14161c; font-weight: 600; border: none; }
QPushButton#accent:hover { background-color: #ecc25a; }

QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,0.18); border-radius: 4px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.30); }
QScrollBar::add-line, QScrollBar::sub-line { height: 0px; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QLabel#title { font-size: 12px; font-weight: 700; letter-spacing: 2px; color: %(accent)s; }
QSplitter::handle { background: transparent; }

/* ---- home / playlists page ---- */
QWidget#home { background-color: rgba(13, 14, 19, 0.88); }
QWidget#homeScroll, QWidget#gridHost { background: transparent; }
QLabel#pageTitle { font-size: 30px; font-weight: 800; color: #f4f2ee; }
QLineEdit#search { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);
                   border-radius: 18px; padding: 8px 15px; color: #eceae6; selection-background-color: rgba(224,182,74,0.35); }
QLineEdit#search:focus { border-color: rgba(224,182,74,0.7); }
QComboBox#sort { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);
                 border-radius: 16px; padding: 6px 14px; color: #eceae6; }
QComboBox#sort:hover { border-color: rgba(224,182,74,0.6); }
QComboBox#sort::drop-down { border: none; width: 22px; }
QComboBox#sort QAbstractItemView { background: #1b1e27; color: #eceae6; border: 1px solid rgba(255,255,255,0.12);
                                   border-radius: 8px; outline: none; selection-background-color: rgba(224,182,74,0.28); }
QFrame#card { background: transparent; border-radius: 12px; }
QFrame#card:hover { background: rgba(255,255,255,0.055); }
QLabel#cardTitle { font-size: 14px; font-weight: 600; color: #f0eee9; }
QLabel#cardSub { font-size: 12px; color: #9aa0ad; }
QLabel#badge { background-color: rgba(0,0,0,0.80); color: #ffffff; font-size: 11px; font-weight: 600;
               padding: 2px 7px; border-radius: 5px; }
QLabel#emptyState { color: #8b8f9c; font-size: 15px; }
""" % {"accent": ACCENT}
