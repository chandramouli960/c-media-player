"""Small pure helpers: time formatting and pixmap drawing for the home cards."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPixmap,
)


def fmt_time(seconds):
    if seconds is None:
        return "00:00"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def rounded_pixmap(src, w, h, radius=10):
    """Scale ``src`` to fill w×h and clip it to a rounded rectangle."""
    scaled = src.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(w, h)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0.0, 0.0, float(w), float(h), radius, radius)
    p.setClipPath(path)
    p.drawPixmap((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
    p.end()
    return out


def placeholder_pixmap(name, w, h, radius=10):
    """A gradient tile with the playlist's initial, used before a thumbnail
    exists. The hue is derived from the name so each card looks distinct."""
    out = QPixmap(w, h)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0.0, 0.0, float(w), float(h), radius, radius)
    p.setClipPath(path)
    hue = (sum(ord(c) for c in name) * 37) % 360
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0.0, QColor.fromHsl(hue, 120, 78))
    grad.setColorAt(1.0, QColor.fromHsl((hue + 40) % 360, 130, 42))
    p.fillRect(0, 0, w, h, grad)
    p.setPen(QColor(255, 255, 255, 235))
    f = QFont()
    f.setPointSize(max(12, int(h * 0.30)))
    f.setBold(True)
    p.setFont(f)
    p.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, (name.strip()[:1] or "?").upper())
    p.end()
    return out
