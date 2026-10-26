# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, copy_metadata

reportlab_datas, reportlab_binaries, reportlab_hiddenimports = collect_all('reportlab')


a = Analysis(
    ['run_app.py'],
    pathex=[],
    binaries=reportlab_binaries,
    datas=[('img', 'img')] + copy_metadata('reportlab') + reportlab_datas,
    hiddenimports=['openpyxl', 'PySide6.QtSvg'] + reportlab_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['streamlit', 'altair', 'matplotlib', 'IPython', 'pytest',
              'PyQt5', 'PyQt6', 'PySide2', 'PySide6.QtWebEngineCore',
              'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# Build no modo "onefile": saida unica dist/novaview_datalogger_v1.exe.
# upx=False e a lista de excludes acima reduzem o tamanho do arquivo e,
# com isso, o tempo de auto-extracao a cada duplo-clique.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='novaview_datalogger_v1.exe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['img/icon.ico'],
)
