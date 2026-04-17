from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

BASE_DIR = Path(__file__).resolve().parents[1]
PACKAGES_SRC_DIR = BASE_DIR / "packages"
KEYS_DIR = BASE_DIR / "server" / "keys"
STORAGE_DIR = BASE_DIR / "server" / "storage"
STORAGE_PACKAGES_DIR = STORAGE_DIR / "packages"
DEVICE_RUNTIME_DIR = BASE_DIR / "device_sim" / "runtime"
VERSIONS = ("1.0.0", "1.1.0", "1.2.0")


def ensure_keys() -> None:
    private_key_path = KEYS_DIR / "private.pem"
    public_key_path = KEYS_DIR / "public.pem"
    KEYS_DIR.mkdir(parents=True, exist_ok=True)

    if private_key_path.exists() and public_key_path.exists():
        return

    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_key_path.write_bytes(private_pem)
    public_key_path.write_bytes(public_pem)


def build_package(version: str) -> None:
    source_dir = PACKAGES_SRC_DIR / version
    if not source_dir.exists():
        raise FileNotFoundError(f"missing package source: {source_dir}")

    STORAGE_PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
    target_zip = STORAGE_PACKAGES_DIR / f"ota-{version}.zip"
    with zipfile.ZipFile(target_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in source_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir))


def init_device(version: str) -> None:
    source_dir = PACKAGES_SRC_DIR / version
    if not source_dir.exists():
        raise FileNotFoundError(f"missing initial package source: {source_dir}")

    if DEVICE_RUNTIME_DIR.exists():
        shutil.rmtree(DEVICE_RUNTIME_DIR)
    current_dir = DEVICE_RUNTIME_DIR / "current"
    current_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, current_dir)
    (DEVICE_RUNTIME_DIR / "metadata.json").write_text(
        json.dumps({"version": version}, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    ensure_keys()
    for version in VERSIONS:
        build_package(version)
    init_device("1.0.0")
    print("[setup] demo assets ready")
    print(f"[setup] generated packages: {STORAGE_PACKAGES_DIR}")
    print(f"[setup] device runtime: {DEVICE_RUNTIME_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
