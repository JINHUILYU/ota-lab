from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests
from cryptography.hazmat.primitives.serialization import load_pem_public_key


class OtaError(RuntimeError):
    pass


@dataclass(frozen=True)
class Manifest:
    version: str
    package: str
    url: str
    sha256: str
    signature: str

    @staticmethod
    def from_dict(data: dict[str, str]) -> "Manifest":
        required = ("version", "package", "url", "sha256", "signature")
        missing = [key for key in required if key not in data]
        if missing:
            raise OtaError(f"manifest 缺少字段: {', '.join(missing)}")
        return Manifest(
            version=data["version"],
            package=data["package"],
            url=data["url"],
            sha256=data["sha256"],
            signature=data["signature"],
        )


def parse_version(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError as exc:
        raise OtaError(f"非法版本号: {value}") from exc


def load_current_version(metadata_path: Path) -> str:
    if not metadata_path.exists():
        raise OtaError(f"缺少设备元数据: {metadata_path}")
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    version = payload.get("version")
    if not isinstance(version, str) or not version:
        raise OtaError("设备元数据里的 version 无效")
    return version


def save_current_version(metadata_path: Path, version: str) -> None:
    metadata_path.write_text(
        json.dumps({"version": version}, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def fetch_manifest(manifest_url: str, timeout: int) -> Manifest:
    response = requests.get(manifest_url, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise OtaError("manifest 不是 JSON object")
    return Manifest.from_dict(data)


def download_package(url: str, output_path: Path, timeout: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, timeout=timeout, stream=True) as response:
        response.raise_for_status()
        with output_path.open("wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)


def verify_sha256(package_path: Path, expected_sha256: str) -> None:
    actual = hashlib.sha256(package_path.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise OtaError(f"SHA256 校验失败，expected={expected_sha256}, actual={actual}")


def verify_signature(package_path: Path, signature_b64: str, public_key_path: Path) -> None:
    public_key = load_pem_public_key(public_key_path.read_bytes())
    signature = base64.b64decode(signature_b64, validate=True)
    package_bytes = package_path.read_bytes()
    public_key.verify(signature, package_bytes)


def health_check(current_dir: Path) -> None:
    health_file = current_dir / "health.txt"
    if not health_file.exists():
        raise OtaError("升级后健康检查失败：缺少 health.txt")
    state = health_file.read_text(encoding="utf-8").strip()
    if state != "ok":
        raise OtaError(f"升级后健康检查失败：health={state}")


def extract_to_staged(package_path: Path, staged_dir: Path) -> None:
    if staged_dir.exists():
        shutil.rmtree(staged_dir)
    staged_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path, "r") as archive:
        archive.extractall(staged_dir)


def install_with_rollback(runtime_dir: Path, metadata_path: Path, target_version: str) -> None:
    current_dir = runtime_dir / "current"
    backup_dir = runtime_dir / "backup"
    staged_dir = runtime_dir / "staged"
    previous_version = load_current_version(metadata_path)
    if not current_dir.exists():
        raise OtaError(f"缺少 current 目录: {current_dir}")

    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    shutil.copytree(current_dir, backup_dir)

    try:
        shutil.rmtree(current_dir)
        shutil.move(str(staged_dir), str(current_dir))
        health_check(current_dir)
    except (OtaError, OSError, zipfile.BadZipFile) as exc:
        if current_dir.exists():
            shutil.rmtree(current_dir)
        shutil.move(str(backup_dir), str(current_dir))
        save_current_version(metadata_path, previous_version)
        raise OtaError(f"升级失败，已自动回滚到 {previous_version}: {exc}") from exc

    shutil.rmtree(backup_dir)
    save_current_version(metadata_path, target_version)


def run_update(server_base_url: str, runtime_dir: Path, public_key_path: Path, timeout: int) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = runtime_dir / "metadata.json"
    current_version = load_current_version(metadata_path)

    manifest = fetch_manifest(f"{server_base_url.rstrip('/')}/manifest.json", timeout)
    if parse_version(manifest.version) <= parse_version(current_version):
        print(f"[device] 已是最新版本：{current_version}")
        return

    print(f"[device] 发现新版本：{current_version} -> {manifest.version}")
    package_path = runtime_dir / "downloads" / manifest.package
    download_package(manifest.url, package_path, timeout)
    verify_sha256(package_path, manifest.sha256)
    verify_signature(package_path, manifest.signature, public_key_path)
    extract_to_staged(package_path, runtime_dir / "staged")
    install_with_rollback(runtime_dir, metadata_path, manifest.version)
    print(f"[device] 升级成功，当前版本：{manifest.version}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OTA device simulator")
    parser.add_argument("--server", default="http://127.0.0.1:8000", help="OTA server base URL")
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=Path("device_sim/runtime"),
        help="device runtime directory",
    )
    parser.add_argument(
        "--public-key",
        type=Path,
        default=Path("server/keys/public.pem"),
        help="path to OTA public key",
    )
    parser.add_argument("--timeout", type=int, default=10, help="HTTP timeout in seconds")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        run_update(
            server_base_url=args.server,
            runtime_dir=args.runtime_dir,
            public_key_path=args.public_key,
            timeout=args.timeout,
        )
    except (OtaError, requests.RequestException, ValueError) as exc:
        print(f"[device] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
