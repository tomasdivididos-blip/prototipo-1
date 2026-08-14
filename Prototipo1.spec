# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('materials', 'materials')]
binaries = []
hiddenimports = ['pyqtgraph.opengl', 'networkx']
hiddenimports += collect_submodules('OpenGL')
tmp_ret = collect_all('pyqtgraph')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('trimesh')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('gmsh')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


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
