"""Frozen-app entry point for LumenGray.

Double-clicking the packaged app runs this module. It:
  1. Picks a free localhost port (prefers 8000, falls back if busy).
  2. Opens the user's default browser at the right URL shortly after start.
  3. Serves the imported FastAPI ``app`` OBJECT directly with uvicorn
     (no import string, no reload) so it works inside a PyInstaller bundle.

PyInstaller note: when frozen, the bundled ``lumengray`` package (including its
web/static assets) lives under ``sys._MEIPASS``. We add that to ``sys.path`` so
``import lumengray.web.server`` resolves, and the server's
``STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")`` then points at
the bundled static folder without any change to server.py.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser

HOST = "127.0.0.1"
PREFERRED_PORT = 8000


def _meipass_path() -> str | None:
    """Return the PyInstaller extraction dir when frozen, else None."""
    return getattr(sys, "_MEIPASS", None)


def _pick_port() -> int:
    """Use 8000 if free; otherwise let the OS hand us any free port."""
    for candidate in (PREFERRED_PORT,):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((HOST, candidate))
                return candidate
            except OSError:
                pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


def _open_browser_when_up(url: str, host: str, port: int) -> None:
    """Wait until the server accepts connections, then open the browser once."""
    deadline = time.time() + 30
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.25)
            if probe.connect_ex((host, port)) == 0:
                break
        time.sleep(0.1)
    webbrowser.open(url)


def main() -> int:
    meipass = _meipass_path()
    if meipass and meipass not in sys.path:
        # Ensure the bundled lumengray package is importable.
        sys.path.insert(0, meipass)

    # Import after sys.path is set up so it works frozen and unfrozen.
    import uvicorn

    from lumengray.web.server import app

    # Honour an env override (used by automated verification to pin the port);
    # otherwise prefer 8000 and fall back to any free port.
    override = os.environ.get("LUMENGRAY_PORT")
    if override and override.isdigit():
        port = int(override)
    else:
        port = _pick_port()
    url = f"http://{HOST}:{port}"

    # Printed so the verification step (and curious users) can see the URL.
    print(f"LumenGray -> {url}", flush=True)
    print(f"LUMENGRAY_PORT={port}", flush=True)

    threading.Thread(
        target=_open_browser_when_up, args=(url, HOST, port), daemon=True
    ).start()

    # Serve the app OBJECT directly: no import string, no reload (required frozen).
    # log_config=None: skip uvicorn's dictConfig — its default "default"/"access"
    # formatters fail to configure inside a PyInstaller bundle ("Unable to configure
    # formatter 'default'"), which crashed the launcher before the server started.
    uvicorn.run(app, host=HOST, port=port, log_level="info", log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
