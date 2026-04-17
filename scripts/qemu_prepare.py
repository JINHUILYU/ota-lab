from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_QEMU_RUNTIME_DIR = BASE_DIR / "qemu_runtime"
DEFAULT_BASE_IMAGE_URL = "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img"


def run_command(command: list[str], dry_run: bool) -> None:
    print(f"[qemu-prepare] $ {shlex.join(command)}")
    if dry_run:
        return
    subprocess.run(command, check=True)


def ensure_base_image(base_image_path: Path, base_image_url: str, dry_run: bool) -> None:
    base_image_path.parent.mkdir(parents=True, exist_ok=True)
    if base_image_path.exists():
        return
    run_command(["curl", "-L", base_image_url, "-o", str(base_image_path)], dry_run=dry_run)


def build_overlay_disk(base_image: Path, disk_image: Path, disk_size: str, reset_disk: bool, dry_run: bool) -> None:
    disk_image.parent.mkdir(parents=True, exist_ok=True)
    if reset_disk and disk_image.exists():
        if dry_run:
            print(f"[qemu-prepare] dry-run: would remove {disk_image}")
        else:
            disk_image.unlink()
    if disk_image.exists():
        return
    run_command(
        [
            "qemu-img",
            "create",
            "-f",
            "qcow2",
            "-F",
            "qcow2",
            "-b",
            str(base_image),
            str(disk_image),
            disk_size,
        ],
        dry_run=dry_run,
    )


def render_cloud_init_user_data(
    ota_server_url: str,
    guest_runtime_dir: str,
    initial_version: str,
    check_interval: float,
    tick_interval: float,
    confirm_ticks: int,
    pending_timeout: float,
) -> str:
    return f"""#cloud-config
package_update: true
ssh_pwauth: true
chpasswd:
  expire: false
  list: |
    ubuntu:ubuntu
packages:
  - python3
  - python3-requests
  - python3-cryptography
  - kmod
  - util-linux
write_files:
  - path: /etc/systemd/system/ota-device.service
    permissions: '0644'
    content: |
      [Unit]
      Description=OTA Device Agent (QEMU guest)
      After=network-online.target
      Wants=network-online.target

      [Service]
      Type=simple
      # /mnt/host may not exist before ExecStartPre; avoid CHDIR failure.
      WorkingDirectory=/
      ExecStartPre=/bin/mkdir -p /mnt/host
      ExecStartPre=/bin/sh -lc 'modprobe 9pnet_virtio || true'
      ExecStartPre=/bin/sh -lc 'modprobe 9p || true'
      # Retry mount for early-boot races before failing the unit.
      ExecStartPre=/bin/sh -lc 'for i in 1 2 3 4 5; do mountpoint -q /mnt/host && exit 0; mount -t 9p -o trans=virtio,version=9p2000.L hostshare /mnt/host && exit 0; sleep 1; done; exit 1'
      ExecStartPre=/bin/sh -lc 'test -f /mnt/host/device_sim/agent.py'
      ExecStartPre=/usr/bin/python3 /mnt/host/scripts/qemu_guest_init.py --runtime-dir {guest_runtime_dir} --packages-dir /mnt/host/packages --initial-version {initial_version}
      ExecStart=/usr/bin/python3 /mnt/host/device_sim/agent.py --server {ota_server_url} --runtime-dir {guest_runtime_dir} --public-key /mnt/host/server/keys/public.pem --check-interval {check_interval} --tick-interval {tick_interval} --confirm-ticks {confirm_ticks} --pending-timeout {pending_timeout} --restart-mode system --system-reboot-command "systemctl reboot"
      Restart=always
      RestartSec=2

      [Install]
      WantedBy=multi-user.target
runcmd:
  - [systemctl, daemon-reload]
  - [systemctl, enable, '--now', ota-device.service]
"""


def write_seed_files(seed_dir: Path, user_data: str) -> tuple[Path, Path]:
    seed_dir.mkdir(parents=True, exist_ok=True)
    user_data_path = seed_dir / "user-data"
    meta_data_path = seed_dir / "meta-data"
    user_data_path.write_text(user_data, encoding="utf-8")
    meta_data_path.write_text(
        f"instance-id: ota-lab-{uuid.uuid4()}\nlocal-hostname: ota-lab-qemu\n",
        encoding="utf-8",
    )
    return user_data_path, meta_data_path


def build_seed_iso(seed_dir: Path, seed_iso: Path, dry_run: bool) -> None:
    seed_iso.parent.mkdir(parents=True, exist_ok=True)
    if seed_iso.exists():
        if dry_run:
            print(f"[qemu-prepare] dry-run: would remove {seed_iso}")
        else:
            seed_iso.unlink()

    out_path = seed_iso
    run_command(
        [
            "hdiutil",
            "makehybrid",
            "-o",
            str(out_path),
            str(seed_dir),
            "-iso",
            "-joliet",
            "-default-volume-name",
            "cidata",
        ],
        dry_run=dry_run,
    )
    if dry_run:
        return

    cdr_path = Path(f"{seed_iso}.cdr")
    if cdr_path.exists():
        shutil.move(str(cdr_path), str(seed_iso))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare QEMU runtime for OTA demo")
    parser.add_argument(
        "--qemu-runtime-dir",
        type=Path,
        default=DEFAULT_QEMU_RUNTIME_DIR,
        help="directory to store base image, overlay disk, and seed ISO",
    )
    parser.add_argument(
        "--base-image-url",
        default=DEFAULT_BASE_IMAGE_URL,
        help="Ubuntu cloud image URL",
    )
    parser.add_argument(
        "--disk-size",
        default="20G",
        help="overlay disk size",
    )
    parser.add_argument(
        "--ota-server-url",
        default="http://10.0.2.2:8000",
        help="OTA server URL from guest side",
    )
    parser.add_argument(
        "--guest-runtime-dir",
        default="/var/lib/ota-runtime",
        help="runtime directory inside guest",
    )
    parser.add_argument(
        "--initial-version",
        default="1.0.0",
        help="initial firmware version in guest",
    )
    parser.add_argument("--check-interval", type=float, default=5.0, help="agent OTA check interval")
    parser.add_argument("--tick-interval", type=float, default=1.0, help="runner tick interval")
    parser.add_argument("--confirm-ticks", type=int, default=3, help="pending confirm ticks")
    parser.add_argument("--pending-timeout", type=float, default=30.0, help="pending timeout")
    parser.add_argument("--reset-disk", action="store_true", help="recreate overlay disk")
    parser.add_argument("--dry-run", action="store_true", help="print actions without executing")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    runtime_dir: Path = args.qemu_runtime_dir
    base_image = runtime_dir / "base" / Path(args.base_image_url).name
    disk_image = runtime_dir / "ota-guest.qcow2"
    seed_dir = runtime_dir / "seed"
    seed_iso = runtime_dir / "seed.iso"

    ensure_base_image(base_image, args.base_image_url, dry_run=args.dry_run)
    build_overlay_disk(
        base_image=base_image,
        disk_image=disk_image,
        disk_size=args.disk_size,
        reset_disk=args.reset_disk,
        dry_run=args.dry_run,
    )
    user_data = render_cloud_init_user_data(
        ota_server_url=args.ota_server_url,
        guest_runtime_dir=args.guest_runtime_dir,
        initial_version=args.initial_version,
        check_interval=args.check_interval,
        tick_interval=args.tick_interval,
        confirm_ticks=args.confirm_ticks,
        pending_timeout=args.pending_timeout,
    )
    write_seed_files(seed_dir, user_data)
    build_seed_iso(seed_dir, seed_iso, dry_run=args.dry_run)

    print(f"[qemu-prepare] base image: {base_image}")
    print(f"[qemu-prepare] disk image: {disk_image}")
    print(f"[qemu-prepare] seed iso: {seed_iso}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
