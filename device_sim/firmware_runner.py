from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from device_sim.runtime_state import ensure_runtime_layout, load_boot_state, slot_path


@dataclass(frozen=True)
class FirmwareInfo:
    version: str
    message: str
    step: int


def parse_firmware_info(current_dir: Path) -> FirmwareInfo:
    app_file = current_dir / "app.txt"
    if not app_file.exists():
        raise FileNotFoundError(f"missing firmware file: {app_file}")

    payload: dict[str, str] = {}
    for line in app_file.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        payload[key.strip()] = value.strip()

    version = payload.get("version", "unknown")
    message = payload.get("message", "(no message)")
    step_value = payload.get("step", "1")
    try:
        step = int(step_value)
    except ValueError as exc:
        raise ValueError(f"invalid step value: {step_value}") from exc
    if step < 1:
        raise ValueError(f"step must be >= 1, got: {step}")
    return FirmwareInfo(version=version, message=message, step=step)


def load_counter(state_path: Path) -> int:
    if not state_path.exists():
        return 0
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("state.json 必须是 JSON object")
    counter = payload.get("counter")
    if not isinstance(counter, int) or counter < 0:
        raise ValueError(f"counter 无效: {counter!r}")
    return counter


def save_counter(state_path: Path, counter: int) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"counter": counter}, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def save_runner_status(status_path: Path, slot: str, version: str, counter: int, ticks_since_start: int) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        json.dumps(
            {
                "slot": slot,
                "version": version,
                "counter": counter,
                "ticks_since_start": ticks_since_start,
                "updated_at": time.time(),
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def check_health(firmware_dir: Path) -> None:
    health_file = firmware_dir / "health.txt"
    if not health_file.exists():
        raise RuntimeError(f"missing health file: {health_file}")
    state = health_file.read_text(encoding="utf-8").strip()
    if state != "ok":
        raise RuntimeError(f"health check failed: {state}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="device firmware runner")
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=Path("device_sim/runtime"),
        help="device runtime directory",
    )
    parser.add_argument(
        "--tick-interval",
        type=float,
        default=1.0,
        help="tick interval in seconds",
    )
    parser.add_argument(
        "--slot",
        choices=["a", "b"],
        help="firmware slot to run; default is active slot in boot.json",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=0,
        help="stop after N ticks, 0 means run forever",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    runtime_dir = args.runtime_dir
    try:
        ensure_runtime_layout(runtime_dir)
        slot = args.slot or load_boot_state(runtime_dir / "boot.json").active_slot
        firmware_dir = slot_path(runtime_dir, slot)
        state_path = runtime_dir / "data" / "state.json"
        status_path = runtime_dir / "data" / "runner_status.json"
        check_health(firmware_dir)
        firmware = parse_firmware_info(firmware_dir)
        print(
            f"[runner] 启动固件 slot={slot} version={firmware.version}, step={firmware.step}, message={firmware.message}",
            flush=True,
        )

        counter = load_counter(state_path)
        ticks = 0
        while True:
            counter += firmware.step
            save_counter(state_path, counter)
            ticks += 1
            save_runner_status(status_path, slot, firmware.version, counter, ticks)
            print(
                f"[runner] slot={slot} version={firmware.version} counter={counter} (+{firmware.step})",
                flush=True,
            )
            if args.max_ticks > 0 and ticks >= args.max_ticks:
                return 0
            time.sleep(args.tick_interval)
    except (FileNotFoundError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"[runner] 启动失败: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
