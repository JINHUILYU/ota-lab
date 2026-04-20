from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from device_sim.runtime_state import (
    BootState,
    boot_path,
    ensure_runtime_layout,
    load_boot_state,
    other_slot,
    save_boot_state,
    slot_path,
)


class OtaError(RuntimeError):
    """OTA 流程中的业务错误。"""

    pass


@dataclass(frozen=True)
class Manifest:
    """OTA 发布清单。"""

    version: str
    package: str
    url: str
    sha256: str
    signature: str

    @staticmethod
    def from_dict(data: dict[str, str]) -> "Manifest":
        """从字典构建并校验 manifest。"""
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
    """将 x.y.z 版本号解析为整数元组用于比较。"""
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError as exc:
        raise OtaError(f"非法版本号: {value}") from exc


def load_current_version(metadata_path: Path) -> str:
    """读取设备当前版本。"""
    if not metadata_path.exists():
        raise OtaError(f"缺少设备元数据: {metadata_path}")
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    version = payload.get("version")
    if not isinstance(version, str) or not version:
        raise OtaError("设备元数据里的 version 无效")
    return version


def save_current_version(metadata_path: Path, version: str) -> None:
    """写入设备当前版本。"""
    metadata_path.write_text(
        json.dumps({"version": version}, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def fetch_manifest(manifest_url: str, timeout: int) -> Manifest:
    """拉取并解析远端 manifest。"""
    response = requests.get(manifest_url, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise OtaError("manifest 不是 JSON object")
    return Manifest.from_dict(data)


def download_package(url: str, output_path: Path, timeout: int) -> None:
    """下载 OTA 包到本地文件。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, timeout=timeout, stream=True) as response:
        response.raise_for_status()
        with output_path.open("wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)


def verify_sha256(package_path: Path, expected_sha256: str) -> None:
    """校验升级包 SHA256。"""
    actual = hashlib.sha256(package_path.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise OtaError(f"SHA256 校验失败，expected={expected_sha256}, actual={actual}")


def verify_signature(package_path: Path, signature_b64: str, public_key_path: Path) -> None:
    """使用设备公钥验签升级包。"""
    public_key = load_pem_public_key(public_key_path.read_bytes())
    if not isinstance(public_key, Ed25519PublicKey):
        raise OtaError("公钥类型无效：需要 Ed25519 公钥")
    signature = base64.b64decode(signature_b64, validate=True)
    package_bytes = package_path.read_bytes()
    public_key.verify(signature, package_bytes)


def health_check(current_dir: Path) -> None:
    """检查升级后健康状态。"""
    health_file = current_dir / "health.txt"
    if not health_file.exists():
        raise OtaError("升级后健康检查失败：缺少 health.txt")
    state = health_file.read_text(encoding="utf-8").strip()
    if state != "ok":
        raise OtaError(f"升级后健康检查失败：health={state}")


def extract_to_slot(package_path: Path, target_slot_dir: Path) -> None:
    """解压升级包到目标 slot。"""
    if target_slot_dir.exists():
        shutil.rmtree(target_slot_dir)
    target_slot_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path, "r") as archive:
        archive.extractall(target_slot_dir)


def mark_pending_update(
    runtime_dir: Path,
    metadata_path: Path,
    current_boot: BootState,
    target_version: str,
    previous_version: str,
) -> None:
    """切换 active slot 并标记 pending 状态。"""
    target_slot = other_slot(current_boot.active_slot)
    save_boot_state(
        boot_path(runtime_dir),
        BootState(
            active_slot=target_slot,
            pending_slot=target_slot,
            previous_slot=current_boot.active_slot,
            pending_version=target_version,
            previous_version=previous_version,
            pending_started_at=time.time(),
        ),
    )
    save_current_version(metadata_path, target_version)


def confirm_pending_update(runtime_dir: Path) -> bool:
    """确认 pending 升级成功并清理 pending 字段。"""
    state = load_boot_state(boot_path(runtime_dir))
    if state.pending_slot is None:
        return False
    save_boot_state(
        boot_path(runtime_dir),
        BootState(
            active_slot=state.active_slot,
            pending_slot=None,
            previous_slot=None,
            pending_version=None,
            previous_version=None,
            pending_started_at=None,
        ),
    )
    return True


def rollback_pending_update(runtime_dir: Path) -> bool:
    """回滚 pending 升级到 previous slot/version。"""
    state = load_boot_state(boot_path(runtime_dir))
    if state.pending_slot is None:
        return False
    if state.previous_slot is None or state.previous_version is None:
        raise OtaError("pending 回滚状态损坏：缺少 previous_slot 或 previous_version")

    save_boot_state(
        boot_path(runtime_dir),
        BootState(
            active_slot=state.previous_slot,
            pending_slot=None,
            previous_slot=None,
            pending_version=None,
            previous_version=None,
            pending_started_at=None,
        ),
    )
    save_current_version(runtime_dir / "metadata.json", state.previous_version)
    return True


def run_update(
    server_base_url: str,
    runtime_dir: Path,
    public_key_path: Path,
    timeout: int,
    defer_confirm: bool = False,
) -> bool:
    """执行一次 OTA 检查与升级流程。"""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    ensure_runtime_layout(runtime_dir)
    metadata_path = runtime_dir / "metadata.json"
    boot_state = load_boot_state(boot_path(runtime_dir))
    if boot_state.pending_slot is not None:
        print(
            f"[device] 存在待确认版本：slot={boot_state.pending_slot}, version={boot_state.pending_version}"
        )
        return False
    current_version = load_current_version(metadata_path)

    manifest = fetch_manifest(f"{server_base_url.rstrip('/')}/manifest.json", timeout)
    if parse_version(manifest.version) <= parse_version(current_version):
        print(f"[device] 已是最新版本：{current_version}")
        return False

    print(f"[device] 发现新版本：{current_version} -> {manifest.version}")
    package_path = runtime_dir / "downloads" / manifest.package
    download_package(manifest.url, package_path, timeout)
    verify_sha256(package_path, manifest.sha256)
    verify_signature(package_path, manifest.signature, public_key_path)
    target_slot = other_slot(boot_state.active_slot)
    extract_to_slot(package_path, slot_path(runtime_dir, target_slot))
    mark_pending_update(
        runtime_dir=runtime_dir,
        metadata_path=metadata_path,
        current_boot=boot_state,
        target_version=manifest.version,
        previous_version=current_version,
    )
    if defer_confirm:
        print(f"[device] 升级包已切换到 slot={target_slot}，等待设备启动确认")
        return True

    try:
        health_check(slot_path(runtime_dir, target_slot))
        confirm_pending_update(runtime_dir)
    except OtaError as exc:
        rollback_pending_update(runtime_dir)
        raise OtaError(f"升级失败，已自动回滚到 {current_version}: {exc}") from exc

    print(f"[device] 升级成功，当前版本：{manifest.version} (slot={target_slot})")
    return True


def build_parser() -> argparse.ArgumentParser:
    """构建设备客户端 CLI 参数。"""
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
    """设备客户端命令入口。"""
    args = build_parser().parse_args()
    try:
        run_update(
            server_base_url=args.server,
            runtime_dir=args.runtime_dir,
            public_key_path=args.public_key,
            timeout=args.timeout,
        )
    except (OtaError, requests.RequestException, ValueError, FileNotFoundError) as exc:
        print(f"[device] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
