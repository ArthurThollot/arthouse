#!/usr/bin/env python3
"""Serve output/index.html locally with an in-page Refresh button.

Builds once at startup, then serves output/ as a static site. A POST to
/refresh re-runs the full fetch pipeline and rewrites output/index.html --
the page's "Refresh" button calls it and reloads. Nothing runs on a timer;
data only ever changes when you load the page or click Refresh.

Usage: python serve.py [--config config.yaml] [--port 8765]
"""

import argparse
import http.server
import webbrowser
from pathlib import Path

from build import run_build

ROOT = Path(__file__).parent


def make_handler(config_path: Path):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT / "output"), **kwargs)

        def do_POST(self):
            if self.path != "/refresh":
                self.send_error(404)
                return
            try:
                run_build(config_path)
                body = b"ok"
                status = 200
            except Exception as e:
                body = str(e).encode()
                status = 500
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A002 -- must match base signature
            pass  # quiet -- avoid spamming the terminal on every asset request

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open the page")
    args = parser.parse_args()

    config_path = Path(args.config)
    run_build(config_path)

    handler = make_handler(config_path)
    url = f"http://localhost:{args.port}/"
    with http.server.ThreadingHTTPServer(("localhost", args.port), handler) as httpd:
        print(f"\nServing at {url} -- click Refresh on the page to pull fresh data.")
        print("Press Ctrl+C to stop.")
        if not args.no_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
