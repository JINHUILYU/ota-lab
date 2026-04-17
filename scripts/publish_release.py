from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.serialization import load_pem_private_key

BASE_DIR = Path(__file__).resolve().parents[1]
KEYS_DIR = BASE_DIR / "server" / "keys"
STORAGE_DIR = BASE_DIR / "server" / "storage"
PACKAGES_DIR = STORAGE_DIR / "packages"
MANIFEST_PATH = STORAGE_DIR / "manifest.json"


def sign_package(package_bytes: bytes, private_key_path: Path) -> str:
    private_key = load_pem_private_key(private_key_path.read_bytes(), password=None)
    signature = private_key.sign(package_bytes)
    return base64.b64encode(signature).decode("ascii")


def build_manifest(version: str, server_url: str) -> dict[str, str]:
    package_name = f"ota-{version}.zip"
    package_path = PACKAGES_DIR / package_name
    if not package_path.exists():
        raise FileNotFoundError(f"package not found: {package_path}")

    private_key_path = KEYS_DIR / "private.pem"
    if not private_key_path.exists():
        raise FileNotFoundError(f"private key not found: {private_key_path}")

    package_bytes = package_path.read_bytes()
    return {
        "version": version,
        "package": package_name,
        "url": f"{server_url.rstrip('/')}/packages/{package_name}",
        "sha256": hashlib.sha256(package_bytes).hexdigest(),
        "signature": sign_package(package_bytes, private_key_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish OTA manifest for a package version")
    parser.add_argument("--version", required=True, help="target package version, e.g. 1.1.0")
    parser.add_argument("--server-url", default="http://127.0.0.1:8000", help="OTA server URL")
    args = parser.parse_args()

    manifest = build_manifest(args.version, args.server_url)
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[publish] released version {args.version}")
    print(f"[publish] manifest: {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
