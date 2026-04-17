from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from device_sim.runtime_state import BootState, boot_path, save_boot_state, slot_path

PACKAGES_SRC_DIR = BASE_DIR / "packages"
KEYS_DIR = BASE_DIR / "server" / "keys"
STORAGE_DIR = BASE_DIR / "server" / "storage"
STORAGE_PACKAGES_DIR = STORAGE_DIR / "packages"
DEVICE_RUNTIME_DIR = BASE_DIR / "device_sim" / "runtime"
VERSIONS = ("1.0.0", "1.1.0", "1.2.0", "1.3.0")


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

# 这个脚本负责生成 OTA 更新的包文件，并初始化设备的运行时目录，模拟设备当前版本为 1.0.0。
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

# 这个脚本负责生成 OTA 更新的包文件，并初始化设备的运行时目录，模拟设备当前版本为 1.0.0。
def init_device(version: str) -> None:
    source_dir = PACKAGES_SRC_DIR / version
    if not source_dir.exists():
        raise FileNotFoundError(f"missing initial package source: {source_dir}")

    if DEVICE_RUNTIME_DIR.exists():
        shutil.rmtree(DEVICE_RUNTIME_DIR)
    slot_a = slot_path(DEVICE_RUNTIME_DIR, "a")
    slot_b = slot_path(DEVICE_RUNTIME_DIR, "b")
    slot_a.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, slot_a)
    slot_b.mkdir(parents=True, exist_ok=True)
    (DEVICE_RUNTIME_DIR / "metadata.json").write_text(
        json.dumps({"version": version}, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    save_boot_state(
        boot_path(DEVICE_RUNTIME_DIR),
        BootState(
            active_slot="a",
            pending_slot=None,
            previous_slot=None,
            pending_version=None,
            previous_version=None,
            pending_started_at=None,
        ),
    )
    (DEVICE_RUNTIME_DIR / "data").mkdir(parents=True, exist_ok=True)
    (DEVICE_RUNTIME_DIR / "data" / "state.json").write_text(
        json.dumps({"counter": 0}, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    ensure_keys() # 确保存在密钥对
    for version in VERSIONS:
        build_package(version)
    init_device("1.0.0") # 初始化设备运行时目录，模拟当前版本为 1.0.0
    print("[setup] demo assets ready")
    print(f"[setup] current versions: 1.0.0")
    print(f"[setup] generated packages: {STORAGE_PACKAGES_DIR}")
    print(f"[setup] device runtime: {DEVICE_RUNTIME_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
