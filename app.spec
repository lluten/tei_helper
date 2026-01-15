# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Include all FlaskWebGUI submodules dynamically
flaskwebgui_hidden = collect_submodules('flaskwebgui')

a = Analysis(
    ['app.py'],                        # your main script
    pathex=[os.path.abspath('.')],     # project root
    binaries=[],
    datas=[
        ('templates', 'templates'),    # include template folder
        ('static', 'static')           # include static folder
    ],
    hiddenimports=[
        'flaskwebgui',                 # explicit
        *flaskwebgui_hidden,           # include all submodules
        'lxml',
        'bs4'
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data,
          cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='app',               # name of the exe
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,            # windowed
    disable_windowed_traceback=False,
    target_arch=None,
    icon=None                 # add 'icon.ico' here if you want
)
