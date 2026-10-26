"""Entrada independente para Windows (prévia) e Android (APK)."""
from pathlib import Path
import os
import sys

import PySide6
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from controller import Controller


if sys.platform == 'win32':
    # Ajuda o carregador de plugins QML na prévia Windows. Só altera este processo.
    _qt_directory = str(Path(PySide6.__file__).parent)
    _dll_directory = os.add_dll_directory(_qt_directory)
    os.environ['PATH'] = _qt_directory + os.pathsep + os.environ.get('PATH', '')


def create_engine(visible=True):
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({'visible': visible})
    controller = Controller()
    engine.rootContext().setContextProperty('backend', controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parent / 'ui' / 'Main.qml')))
    if not engine.rootObjects():
        raise RuntimeError('Não foi possível carregar a interface do protótipo.')
    return engine, controller


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName('NovaView Datalogger')
    app.setApplicationVersion('0.2.1')
    app.setOrganizationName('Nova Instruments')
    QQuickStyle.setStyle('Basic')
    engine, controller = create_engine()
    app.aboutToQuit.connect(controller.shutdown)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
