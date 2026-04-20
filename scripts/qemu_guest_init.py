from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from device_sim.runtime_state import BootState, boot_path, save_boot_state, slot_path


def init_runtime(runtime_dir: Path, packages_dir: Path, initial_version: str, force: bool) -> None:
    """初始化 guest 运行态目录与默认固件。"""
    source_dir = packages_dir / initial_version
    if not source_dir.exists():
        raise FileNotFoundError(f"missing initial package source: {source_dir}")

    metadata_file = runtime_dir / "metadata.json"
    boot_file = boot_path(runtime_dir)
    slot_a = slot_path(runtime_dir, "a")
    slot_b = slot_path(runtime_dir, "b")
    state_file = runtime_dir / "data" / "state.json"

    if (
        not force
        and metadata_file.exists()
        and boot_file.exists()
        and slot_a.exists()
        and slot_b.exists()
        and state_file.exists()
    ):
        return

    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    slot_a.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, slot_a)
    slot_b.mkdir(parents=True, exist_ok=True)
    metadata_file.write_text(
        json.dumps({"version": initial_version}, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    save_boot_state(
        boot_file,
        BootState(
            active_slot="a",
            pending_slot=None,
            previous_slot=None,
            pending_version=None,
            previous_version=None,
            pending_started_at=None,
        ),
    )
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({"counter": 0}, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    """构建 guest 初始化 CLI 参数。"""
    parser = argparse.ArgumentParser(description="Initialize guest runtime for OTA QEMU demo")
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=Path("/var/lib/ota-runtime"),
        help="guest runtime directory",
    )
    parser.add_argument(
        "--packages-dir",
        type=Path,
        default=Path("/mnt/host/packages"),
        help="package sources mounted from host",
    )
    parser.add_argument(
        "--initial-version",
        default="1.0.0",
        help="initial firmware version in guest runtime",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="force reset runtime even when initialized",
    )
    return parser


def main() -> int:
    """guest 初始化命令入口。"""
    args = build_parser().parse_args()
    init_runtime(
        runtime_dir=args.runtime_dir,
        packages_dir=args.packages_dir,
        initial_version=args.initial_version,
        force=args.force,
    )
    print(f"[qemu-init] guest runtime ready: {args.runtime_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
