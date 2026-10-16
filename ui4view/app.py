"""Read-only menu viewer for the home network.

    python ui4view/app.py          serve on all interfaces (HOST = "0.0.0.0")
    python ui4view/app.py 5051     use another port

Other devices on the same network open http://<this computer's IP>:5050.

This app only shows the current four-week menu and its recipes. It has no
connection to Claude (it does not import the meal_planner package), no write
endpoints, and runs with Flask debug mode off, because the debugger would let
anyone on the network run code on this computer. Planning and editing stay in
the main UI (python app.py), which is restricted to this computer.
"""

import logging
import mimetypes
import socket
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template

from menu_reader import MenuReadError, current_menu

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT.parent / "data"
HOST, PORT = "0.0.0.0", 5050


def create_app(data_dir: Path = DATA_DIR) -> Flask:
    mimetypes.add_type("text/javascript", ".js")  # Windows sometimes maps .js to text/plain
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/menu")
    def menu():
        try:
            return jsonify(current_menu(data_dir))
        except MenuReadError as e:
            app.logger.warning("cannot read menu: %s", e)
            return jsonify(error="菜单文件读取失败", detail=str(e)), 500

    return app


def lan_address() -> str | None:
    """This computer's address on the local network (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 80))  # documentation address; connect() on UDP only picks a route
            return s.getsockname()[0]
        except OSError:
            return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    print(f"Data: {DATA_DIR}")
    print(f"This computer: http://127.0.0.1:{port}")
    if HOST == "0.0.0.0" and (ip := lan_address()):
        print(f"Other devices: http://{ip}:{port}")
    create_app().run(host=HOST, port=port, debug=False, threaded=True)
