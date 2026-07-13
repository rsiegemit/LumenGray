# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for LumenGray — a double-click desktop build of the web app.

Produces:
  * macOS: dist/LumenGray.app  (windowed, no console)
  * Windows: dist/LumenGray/LumenGray.exe  (built in CI)

Run from the repo root:
    pyinstaller packaging/LumenGray.spec

Why the data/hidden-import gymnastics:
  * The web UI static assets (index.html, app.js, style.css) must ship as data,
    otherwise the server has nothing to serve. We bundle the whole ``lumengray``
    package preserving its directory layout so that the server's
    ``STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")`` resolves
    inside the frozen bundle with NO change to server.py.
  * uvicorn loads its loop/protocol/lifespan/logging implementations by string at
    runtime, so they are invisible to static analysis — we collect them.
  * trimesh and scipy pull in data files and lazily-imported submodules.
"""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

block_cipher = None

# SPECPATH is injected by PyInstaller = dir containing this spec (packaging/).
PACKAGING_DIR = SPECPATH
REPO_ROOT = os.path.abspath(os.path.join(PACKAGING_DIR, ".."))
LAUNCH = os.path.join(PACKAGING_DIR, "launch.py")

datas = []
binaries = []
hiddenimports = []

# Bundle the whole lumengray package (code + web/static) preserving layout.
datas += collect_data_files("lumengray", include_py_files=True)

# Heavy scientific deps with their own data files and lazy submodules.
# certifi ships its CA bundle (cacert.pem) so the in-app update check's HTTPS call
# can verify TLS from inside the frozen bundle.
for pkg in ("trimesh", "scipy", "certifi"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# uvicorn resolves these dynamically by string at runtime.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += [
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.logging",
]

# Form upload handling (FastAPI's UploadFile) needs python-multipart.
hiddenimports += ["multipart", "python_multipart"]

a = Analysis(
    [LAUNCH],
    pathex=[REPO_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LumenGray",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # windowed: no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LumenGray",
)

app = BUNDLE(
    coll,
    name="LumenGray.app",
    icon=None,
    bundle_identifier="com.rsiegemit.lumengray",
    info_plist={
        "CFBundleName": "LumenGray",
        "CFBundleDisplayName": "LumenGray",
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
        # The app starts a local server; declare it as a background-capable agent
        # so macOS doesn't show a dock bounce/console expectation.
        "LSBackgroundOnly": False,
    },
)
