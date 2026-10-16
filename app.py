"""Start the local Web UI.

    python app.py            use the real data in ./data
    python app.py --demo     use invented demo data in ./demo_data (created on first run)
    python app.py 5001       use another port

Then open http://127.0.0.1:5000 (only reachable from this computer).

This UI can use Claude on your subscription, so it is for this computer only:
do not change HOST, and the server refuses other devices anyway (ADR-024).
Other devices on the home network use the read-only viewer: python ui4view/app.py
"""

import logging
import sys
from pathlib import Path

from meal_planner.demo import create_demo_data
from meal_planner.web import create_app

ROOT = Path(__file__).resolve().parent
HOST, PORT = "127.0.0.1", 5000  # this computer only

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = sys.argv[1:]
    data_dir = ROOT / "data"
    if "--demo" in args:
        args.remove("--demo")
        data_dir = ROOT / "demo_data"
        create_demo_data(data_dir)
    port = int(args[0]) if args else PORT
    print(f"Data: {data_dir}")
    print(f"Open http://{HOST}:{port}")
    create_app(data_dir).run(host=HOST, port=port, debug=True, threaded=True)
