# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('materials', 'materials')]
binaries = []
hiddenimports = ['pyqtgraph.opengl', 'networkx']
# v2.29: filters.py hace `from scipy import signal` (import lazy dentro de
# funciones); lo declaramos explícito para que PyInstaller lo empaquete seguro.
hiddenimports += ['filters', 'scipy.signal']
hiddenimports += collect_submodules('scipy.signal')
hiddenimports += collect_submodules('OpenGL')
tmp_ret = collect_all('pyqtgraph')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('trimesh')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('gmsh')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# v2.29: PyQt5 de CONDA. El hook de PyInstaller busca los DLLs de Qt en el
# layout de pip (PyQt5/Qt5/bin); en Anaconda viven en <prefix>/Library/bin y
# los plugins en <prefix>/Library/plugins, así que NO se colectan solos y el
# exe falla con "DLL load failed while importing QtCore". Los agregamos a mano.
import os as _os, sys as _sys, glob as _glob
_lib_bin = _os.path.join(_sys.prefix, 'Library', 'bin')
_lib_plugins = _os.path.join(_sys.prefix, 'Library', 'plugins')
if _os.path.isdir(_lib_bin):
    # Qt5 + sus deps transitivas de conda (si falta una, QtCore/Gui vuelve a
    # tirar "DLL load failed"). Set generoso a propósito.
    _pats = ['Qt5*.dll', 'icu*.dll', 'libEGL.dll', 'libGLESv2.dll',
             'opengl32sw.dll', 'd3dcompiler_*.dll',
             'pcre2*.dll', 'pcre*.dll', 'zstd*.dll', 'zlib*.dll', 'libzlib*.dll',
             'double-conversion*.dll', 'harfbuzz*.dll', 'freetype*.dll',
             'libpng*.dll', 'jpeg*.dll', 'libjpeg*.dll', 'tiff*.dll',
             'libssl*.dll', 'libcrypto*.dll', 'brotli*.dll', 'bz2*.dll',
             'libbz2*.dll', 'lz4*.dll', 'libwebp*.dll', 'glib*.dll',
             'gio*.dll', 'gobject*.dll', 'intl*.dll', 'iconv*.dll',
             'pcre2-16*.dll', 'ffi*.dll', 'libffi*.dll']
    _seen = set()
    for _p in _pats:
        for _f in _glob.glob(_os.path.join(_lib_bin, _p)):
            if _f not in _seen:
                _seen.add(_f)
                binaries.append((_f, '.'))
# Plugins de Qt bajo PyQt5/Qt5/plugins/* (donde main.py apunta el
# QT_QPA_PLATFORM_PLUGIN_PATH en el frozen: <_internal>/PyQt5/Qt5/plugins).
if _os.path.isdir(_lib_plugins):
    for _sub in ['platforms', 'styles', 'imageformats', 'iconengines']:
        _d = _os.path.join(_lib_plugins, _sub)
        for _f in _glob.glob(_os.path.join(_d, '*.dll')):
            datas.append((_f, _os.path.join('PyQt5', 'Qt5', 'plugins', _sub)))


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt6', 'PySide6', 'PySide2', 'pandas', 'IPython', 'ipykernel', 'jupyter', 'jupyter_client', 'jupyter_core', 'notebook', 'sphinx', 'sphinxcontrib', 'docutils', 'jedi', 'parso', 'pytest', 'black', 'nacl', 'bcrypt', 'cryptography', 'openpyxl', 'pyarrow', 'tables', 'sqlalchemy', 'lxml', 'pygments', 'tkinter', '_tkinter', 'botocore', 'boto3', 'numba', 'llvmlite', 'panel', 'bokeh', 'holoviews', 'datashader'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Prototipo1',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Prototipo1',
)
