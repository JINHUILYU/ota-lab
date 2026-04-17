from __future__ import annotations

import argparse
import json
from pathlib import Path

from flask import Flask, abort, jsonify, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
PACKAGES_DIR = STORAGE_DIR / "packages"
MANIFEST_PATH = STORAGE_DIR / "manifest.json"

app = Flask(__name__)


@app.get("/health")
def health() -> tuple[dict[str, str], int]:
    return {"status": "ok"}, 200


@app.get("/manifest.json")
def get_manifest():
    if not MANIFEST_PATH.exists():
        abort(404, description="manifest.json not found, publish a release first")
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return jsonify(payload)


@app.get("/packages/<path:filename>")
def download_package(filename: str):
    target = PACKAGES_DIR / filename
    if not target.exists():
        abort(404, description=f"package not found: {filename}")
    return send_from_directory(str(PACKAGES_DIR), filename, as_attachment=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OTA server")
    parser.add_argument("--host", default="127.0.0.1", help="listen host")
    parser.add_argument("--port", type=int, default=8000, help="listen port")
    parser.add_argument("--debug", action="store_true", help="enable Flask debug mode")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)
