from __future__ import annotations

import argparse
import shlex
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_QEMU_RUNTIME_DIR = BASE_DIR / "qemu_runtime"


def build_qemu_command(
    qemu_bin: str,
    disk_image: Path,
    seed_iso: Path,
    host_share: Path,
    memory_mb: int,
    cpus: int,
    ssh_port: int,
) -> list[str]:
    return [
        qemu_bin,
        "-name",
        "ota-lab-qemu",
        "-machine",
        "q35",
        "-accel",
        "hvf",
        "-cpu",
        "host",
        "-smp",
        str(cpus),
        "-m",
        str(memory_mb),
        "-drive",
        f"file={disk_image},if=virtio,format=qcow2",
        "-drive",
        f"file={seed_iso},media=cdrom,if=virtio,readonly=on",
        "-virtfs",
        f"local,path={host_share},mount_tag=hostshare,security_model=none,multidevs=remap",
        "-netdev",
        f"user,id=net0,hostfwd=tcp::{ssh_port}-:22",
        "-device",
        "virtio-net-pci,netdev=net0",
        "-nographic",
        "-serial",
        "mon:stdio",
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run OTA QEMU guest")
    parser.add_argument(
        "--qemu-runtime-dir",
        type=Path,
        default=DEFAULT_QEMU_RUNTIME_DIR,
        help="directory containing ota-guest.qcow2 and seed.iso",
    )
    parser.add_argument(
        "--host-share",
        type=Path,
        default=BASE_DIR,
        help="host directory shared into guest via 9p",
    )
    parser.add_argument("--qemu-bin", default="qemu-system-x86_64", help="qemu executable")
    parser.add_argument("--memory-mb", type=int, default=2048, help="guest memory")
    parser.add_argument("--cpus", type=int, default=2, help="guest vCPU count")
    parser.add_argument("--ssh-port", type=int, default=2222, help="host forwarded ssh port")
    parser.add_argument("--dry-run", action="store_true", help="print qemu command without executing")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    runtime_dir: Path = args.qemu_runtime_dir
    disk_image = runtime_dir / "ota-guest.qcow2"
    seed_iso = runtime_dir / "seed.iso"

    if not disk_image.exists():
        raise FileNotFoundError(f"missing disk image: {disk_image}, run scripts/qemu_prepare.py first")
    if not seed_iso.exists():
        raise FileNotFoundError(f"missing seed iso: {seed_iso}, run scripts/qemu_prepare.py first")
    if not args.host_share.exists():
        raise FileNotFoundError(f"missing host share path: {args.host_share}")

    command = build_qemu_command(
        qemu_bin=args.qemu_bin,
        disk_image=disk_image,
        seed_iso=seed_iso,
        host_share=args.host_share.resolve(),
        memory_mb=args.memory_mb,
        cpus=args.cpus,
        ssh_port=args.ssh_port,
    )
    print(f"[qemu-run] $ {shlex.join(command)}")
    if args.dry_run:
        return 0
    subprocess.run(command, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
