"""Inicialização desktop e registro de erros do executável Windows."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import traceback



def _get_log_path():
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NovaView"
    base.mkdir(parents=True, exist_ok=True)
    return base / "run_error.log"


def main():
    log_path = _get_log_path()
    logging.basicConfig(filename=log_path, level=logging.ERROR,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")

    def report_error(exc_type, value, tb):
        logging.error("Erro não tratado", exc_info=(exc_type, value, tb))
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance():
                QMessageBox.critical(None, "novaview_datalogger_v1", f"Ocorreu um erro: {value}\n\nLog: {log_path}")
                return
        except Exception:
            pass
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"Falha ao iniciar: {value}\n\nLog: {log_path}", "novaview_datalogger_v1", 0x10)
        else:
            traceback.print_exception(exc_type, value, tb)

    sys.excepthook = report_error
    try:
        from desktop_app import main as desktop_main
        return desktop_main()
    except Exception:
        report_error(*sys.exc_info())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
