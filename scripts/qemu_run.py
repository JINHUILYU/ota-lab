from __future__ import annotations

import argparse
import shlex
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_QEMU_RUNTIME_DIR = BASE_DIR / "qemu_runtime"


def list_supported_accelerators(qemu_bin: str) -> set[str]:
    result = subprocess.run(
        [qemu_bin, "-accel", "help"],
        check=True,
        capture_output=True,
        text=True,
    )
    supported: set[str] = set()
    for line in result.stdout.splitlines():
        item = line.strip()
        if not item or ":" in item:
            continue
        supported.add(item)
    return supported


def choose_accelerator(qemu_bin: str, requested: str) -> str:
    supported = list_supported_accelerators(qemu_bin)
    if requested != "auto":
        if requested not in supported:
            raise ValueError(f"qemu 不支持加速器 {requested}，可用: {', '.join(sorted(supported))}")
        return requested

    # Prefer hardware acceleration, but always keep tcg as software fallback.
    for candidate in ("hvf", "kvm", "whpx", "tcg"):
        if candidate in supported:
            return candidate
    raise ValueError(f"未找到可用加速器，qemu 支持列表: {', '.join(sorted(supported))}")


def choose_cpu_model(accel: str, requested: str) -> str:
    if requested != "auto":
        return requested
    # "host" is invalid for pure emulation (tcg) on some builds.
    if accel == "tcg":
        return "max"
    return "host"


def build_qemu_command(
    qemu_bin: str,
    accel: str,
    cpu_model: str,
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
        accel,
        "-cpu",
        cpu_model,
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
    parser.add_argument(
        "--accel",
        default="auto",
        help="accelerator to use (auto/hvf/kvm/whpx/tcg)",
    )
    parser.add_argument(
        "--cpu-model",
        default="auto",
        help="CPU model to use (auto means host for hw accel, max for tcg)",
    )
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

    accel = choose_accelerator(args.qemu_bin, args.accel)
    cpu_model = choose_cpu_model(accel, args.cpu_model)

    command = build_qemu_command(
        qemu_bin=args.qemu_bin,
        accel=accel,
        cpu_model=cpu_model,
        disk_image=disk_image,
        seed_iso=seed_iso,
        host_share=args.host_share.resolve(),
        memory_mb=args.memory_mb,
        cpus=args.cpus,
        ssh_port=args.ssh_port,
    )
    print(f"[qemu-run] accelerator={accel}, cpu_model={cpu_model}")
    print(f"[qemu-run] $ {shlex.join(command)}")
    if args.dry_run:
        return 0
    subprocess.run(command, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
