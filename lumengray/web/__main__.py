"""Run the LumenGray web app:  python -m lumengray.web  (or the ``lumengray-web`` script)."""

from __future__ import annotations

import argparse
import webbrowser


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lumengray-web", description="Serve the LumenGray UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = parser.parse_args(argv)

    import uvicorn

    url = f"http://{args.host}:{args.port}"
    print(f"LumenGray -> {url}")
    if not args.no_browser and not args.reload:
        webbrowser.open(url)
    uvicorn.run("lumengray.web.server:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
