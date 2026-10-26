"""Deriva os recursos de interface da marca fornecida, preservando o original."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtCore import QRect, QRectF, Qt


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    assets = Path(__file__).resolve().parents[1] / 'assets'
    original = QImage(str(assets / 'logo.png'))
    if original.isNull():
        raise RuntimeError('Logo original ausente.')
    factor = original.width() / 1774
    def crop(x, y, width, height):
        return original.copy(QRect(round(x*factor), round(y*factor), round(width*factor), round(height*factor)))
    crop(65, 235, 1650, 310).save(str(assets / 'logo_header.png'))
    mark = crop(65, 235, 550, 310)
    icon = QImage(512, 512, QImage.Format.Format_ARGB32)
    icon.fill(Qt.GlobalColor.white)
    painter = QPainter(icon)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(QRectF(42, 135, 428, 241), mark)
    painter.end()
    icon.save(str(assets / 'icon.png'))
    print('Recursos da marca preparados a partir do logo original.')


if __name__ == '__main__':
    main()
