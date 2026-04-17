from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from device_sim.client import (
    OtaError,
    confirm_pending_update,
    fetch_manifest,
    load_current_version,
    rollback_pending_update,
    run_update,
)
from device_sim.runtime_state import boot_path, ensure_runtime_layout, load_boot_state


@dataclass(frozen=True)
class RunnerStatus:
    slot: str
    version: str
    ticks_since_start: int


def load_runner_status(status_path: Path) -> RunnerStatus:
    if not status_path.exists():
        raise FileNotFoundError(f"missing runner status: {status_path}")
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("runner_status.json 必须是 JSON object")

    slot = payload.get("slot")
    if slot not in ("a", "b"):
        raise ValueError(f"runner status slot 无效: {slot!r}")
    version = payload.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"runner status version 无效: {version!r}")
    ticks_since_start = payload.get("ticks_since_start")
    if not isinstance(ticks_since_start, int) or ticks_since_start < 0:
        raise ValueError(f"runner status ticks_since_start 无效: {ticks_since_start!r}")
    return RunnerStatus(slot=slot, version=version, ticks_since_start=ticks_since_start)


def manifest_identity(manifest) -> str:
    # Use full manifest fingerprint to avoid over-blocking by version only.
    return "|".join(
        [
            manifest.version,
            manifest.package,
            manifest.url,
            manifest.sha256,
            manifest.signature,
        ]
    )


def start_runner(runtime_dir: Path, tick_interval: float, slot: str) -> subprocess.Popen[bytes]:
    runner_path = Path(__file__).resolve().parent / "firmware_runner.py"
    command = [
        sys.executable,
        str(runner_path),
        "--runtime-dir",
        str(runtime_dir),
        "--slot",
        slot,
        "--tick-interval",
        str(tick_interval),
    ]
    print(f"[agent] 启动固件进程 slot={slot}", flush=True)
    return subprocess.Popen(command)


def stop_runner(process: subprocess.Popen[bytes], timeout: float = 5.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def restart_runner(
    process: subprocess.Popen[bytes],
    runtime_dir: Path,
    tick_interval: float,
    slot: str,
) -> subprocess.Popen[bytes]:
    print("[agent] OTA 完成，重启固件进程", flush=True)
    stop_runner(process)
    return start_runner(runtime_dir, tick_interval, slot)


def reboot_system(command: str) -> None:
    cmd = shlex.split(command)
    if not cmd:
        raise ValueError("system reboot command 不能为空")
    print(f"[agent] 执行系统重启命令: {command}", flush=True)
    subprocess.run(cmd, check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="device OTA agent")
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
    parser.add_argument("--check-interval", type=float, default=10.0, help="OTA check interval in seconds")
    parser.add_argument("--tick-interval", type=float, default=1.0, help="firmware tick interval in seconds")
    parser.add_argument(
        "--confirm-ticks",
        type=int,
        default=3,
        help="pending 版本至少运行多少个 tick 后确认提交",
    )
    parser.add_argument(
        "--pending-timeout",
        type=float,
        default=30.0,
        help="pending 版本超时秒数，超时后自动回滚",
    )
    parser.add_argument(
        "--restart-mode",
        choices=["runner", "system"],
        default="runner",
        help="OTA 成功后重启策略：runner=仅重启固件进程，system=重启整机",
    )
    parser.add_argument(
        "--system-reboot-command",
        default="systemctl reboot",
        help="restart-mode=system 时执行的系统重启命令",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    runtime_dir: Path = args.runtime_dir
    ensure_runtime_layout(runtime_dir)
    metadata_path = runtime_dir / "metadata.json"
    if not metadata_path.exists():
        print(f"[agent] 缺少设备元数据: {metadata_path}", flush=True)
        return 1

    boot_state = load_boot_state(boot_path(runtime_dir))
    version = load_current_version(metadata_path)
    print(f"[agent] 设备启动，当前版本: {version}, active_slot={boot_state.active_slot}", flush=True)

    runner = start_runner(runtime_dir, args.tick_interval, boot_state.active_slot)
    blocked_manifest: str | None = None
    pending_manifest: str | None = None
    try:
        while True:
            time.sleep(args.check_interval)
            boot_state = load_boot_state(boot_path(runtime_dir))

            if runner.poll() is not None:
                if boot_state.pending_slot is not None:
                    # Pending boot failed; block this exact manifest payload until it changes.
                    blocked_manifest = pending_manifest
                    print(
                        f"[agent] pending 固件启动失败，执行回滚 slot={boot_state.previous_slot}",
                        flush=True,
                    )
                    rollback_pending_update(runtime_dir)
                    pending_manifest = None
                    boot_state = load_boot_state(boot_path(runtime_dir))
                else:
                    print("[agent] 固件进程异常退出，正在拉起", flush=True)
                runner = start_runner(runtime_dir, args.tick_interval, boot_state.active_slot)
                continue

            if boot_state.pending_slot is not None:
                if (
                    boot_state.pending_started_at is not None
                    and time.time() - boot_state.pending_started_at > args.pending_timeout
                ):
                    # Timed out during pending confirmation; rollback and mark current payload blocked.
                    blocked_manifest = pending_manifest
                    print(
                        f"[agent] pending 超时，回滚到 slot={boot_state.previous_slot}",
                        flush=True,
                    )
                    rollback_pending_update(runtime_dir)
                    pending_manifest = None
                    boot_state = load_boot_state(boot_path(runtime_dir))
                    runner = restart_runner(
                        runner,
                        runtime_dir,
                        args.tick_interval,
                        boot_state.active_slot,
                    )
                    continue

                try:
                    status = load_runner_status(runtime_dir / "data" / "runner_status.json")
                except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
                    print(f"[agent] 读取 runner 状态失败: {exc}", flush=True)
                    continue
                if status.slot != boot_state.pending_slot:
                    print(
                        f"[agent] pending 等待中：runner.slot={status.slot}, pending.slot={boot_state.pending_slot}",
                        flush=True,
                    )
                    continue
                if status.ticks_since_start >= args.confirm_ticks:
                    confirm_pending_update(runtime_dir)
                    pending_manifest = None
                    print(
                        f"[agent] pending 版本确认成功：slot={status.slot}, version={status.version}",
                        flush=True,
                    )
                continue

            try:
                manifest = fetch_manifest(f"{args.server.rstrip('/')}/manifest.json", args.timeout)
            except (OtaError, requests.RequestException, ValueError, FileNotFoundError) as exc:
                print(f"[agent] OTA 检查失败: {exc}", flush=True)
                continue

            current_manifest = manifest_identity(manifest)
            if blocked_manifest is not None:
                if current_manifest == blocked_manifest:
                    # Same failed payload keeps being published; skip to avoid reboot loops.
                    print(
                        f"[agent] 跳过已失败发布：version={manifest.version}，等待发布内容变化",
                        flush=True,
                    )
                    continue
                blocked_manifest = None

            try:
                updated = run_update(
                    server_base_url=args.server,
                    runtime_dir=runtime_dir,
                    public_key_path=args.public_key,
                    timeout=args.timeout,
                    defer_confirm=True,
                )
            except (OtaError, requests.RequestException, ValueError, FileNotFoundError) as exc:
                print(f"[agent] OTA 检查失败: {exc}", flush=True)
                continue
            if updated:
                pending_manifest = current_manifest
                boot_state = load_boot_state(boot_path(runtime_dir))
                if args.restart_mode == "system":
                    stop_runner(runner)
                    reboot_system(args.system_reboot_command)
                    return 0
                runner = restart_runner(
                    runner,
                    runtime_dir,
                    args.tick_interval,
                    boot_state.active_slot,
                )
    except KeyboardInterrupt:
        print("[agent] 收到中断信号，停止设备", flush=True)
    finally:
        stop_runner(runner)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
