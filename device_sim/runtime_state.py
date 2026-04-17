from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

SlotName = Literal["a", "b"]


@dataclass(frozen=True)
class BootState:
    active_slot: SlotName
    pending_slot: SlotName | None
    previous_slot: SlotName | None
    pending_version: str | None
    previous_version: str | None
    pending_started_at: float | None


def metadata_path(runtime_dir: Path) -> Path:
    return runtime_dir / "metadata.json"


def boot_path(runtime_dir: Path) -> Path:
    return runtime_dir / "boot.json"


def slot_path(runtime_dir: Path, slot: SlotName) -> Path:
    return runtime_dir / "slots" / slot


def other_slot(slot: SlotName) -> SlotName:
    return cast(SlotName, "b" if slot == "a" else "a")


def _parse_slot(value: object, field_name: str) -> SlotName:
    if value not in ("a", "b"):
        raise ValueError(f"boot.{field_name} 无效: {value!r}")
    return cast(SlotName, value)


def _parse_optional_slot(value: object, field_name: str) -> SlotName | None:
    if value is None:
        return None
    return _parse_slot(value, field_name)


def load_boot_state(path: Path) -> BootState:
    if not path.exists():
        raise FileNotFoundError(f"缺少 boot 状态文件: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("boot.json 必须是 JSON object")

    active_slot = _parse_slot(payload.get("active_slot"), "active_slot")
    pending_slot = _parse_optional_slot(payload.get("pending_slot"), "pending_slot")
    previous_slot = _parse_optional_slot(payload.get("previous_slot"), "previous_slot")

    pending_version = payload.get("pending_version")
    if pending_version is not None and not isinstance(pending_version, str):
        raise ValueError("boot.pending_version 必须是字符串或 null")
    previous_version = payload.get("previous_version")
    if previous_version is not None and not isinstance(previous_version, str):
        raise ValueError("boot.previous_version 必须是字符串或 null")

    pending_started_at = payload.get("pending_started_at")
    if pending_started_at is not None and not isinstance(pending_started_at, (int, float)):
        raise ValueError("boot.pending_started_at 必须是数字或 null")

    return BootState(
        active_slot=active_slot,
        pending_slot=pending_slot,
        previous_slot=previous_slot,
        pending_version=pending_version,
        previous_version=previous_version,
        pending_started_at=float(pending_started_at) if pending_started_at is not None else None,
    )


def save_boot_state(path: Path, state: BootState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "active_slot": state.active_slot,
                "pending_slot": state.pending_slot,
                "previous_slot": state.previous_slot,
                "pending_version": state.pending_version,
                "previous_version": state.previous_version,
                "pending_started_at": state.pending_started_at,
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def ensure_runtime_layout(runtime_dir: Path) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    slots_dir = runtime_dir / "slots"
    boot_file = boot_path(runtime_dir)

    if slots_dir.exists() and boot_file.exists():
        return

    legacy_current = runtime_dir / "current"
    if not legacy_current.exists():
        raise FileNotFoundError(
            f"未找到 runtime 布局（缺少 {slots_dir} 和 {legacy_current}），请先运行 scripts/setup_demo.py"
        )

    slot_a = slot_path(runtime_dir, "a")
    slot_b = slot_path(runtime_dir, "b")
    slots_dir.mkdir(parents=True, exist_ok=True)
    if slot_a.exists():
        shutil.rmtree(slot_a)
    shutil.copytree(legacy_current, slot_a)
    if slot_b.exists():
        shutil.rmtree(slot_b)
    slot_b.mkdir(parents=True, exist_ok=True)

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
