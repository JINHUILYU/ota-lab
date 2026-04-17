# ota-lab Copilot 工作指引

## 构建、运行、测试与检查命令

本仓库使用 `uv` 管理 Python 环境（Python >= 3.11）。

```bash
# 安装依赖
uv sync

# 构建演示资产（生成密钥、打包升级包、初始化设备运行态）
uv run python scripts/setup_demo.py

# 启动 OTA 服务端
uv run python server/app.py

# 启动常驻设备（固件计数 + 周期 OTA 检查）
uv run python device_sim/agent.py
```

当前仓库未配置自动化测试与 lint（无 `pytest`/`ruff`/`mypy` 等配置和测试目录）。可用下面命令做单场景验证（相当于“单个集成测试”）：

```bash
# 单场景：发布 1.1.0 并执行一次设备升级（非常驻）
uv run python scripts/publish_release.py --version 1.1.0
uv run python device_sim/client.py
```

## 高层架构（跨文件主流程）

这是一个单机 OTA 流程实验项目，包含四条主线：

1. **发布准备**（`scripts/setup_demo.py`）  
   从 `packages/<version>/` 读取固件内容，构建 `server/storage/packages/ota-<version>.zip`；首次生成 `server/keys/{private,public}.pem`；初始化 `device_sim/runtime/slots/{a,b}` 与 `boot.json`（默认 active=a）。
2. **服务端分发**（`server/app.py` + `scripts/publish_release.py`）  
   `publish_release.py` 用私钥对 zip 包签名并写入 `server/storage/manifest.json`；`server/app.py` 对外提供 `/manifest.json` 与 `/packages/<file>` 下载接口。
3. **设备端升级与回滚**（`device_sim/client.py`）  
   读取本地 `device_sim/runtime/metadata.json` 当前版本 -> 拉取 manifest -> 比较版本 -> 下载包 -> SHA256 校验 -> 公钥验签 -> 解压到 inactive slot -> 切换 active slot 并标记 pending；可选择立即确认（单次模式）或由 agent 延迟确认（常驻模式）。
4. **设备常驻模型**（`device_sim/agent.py` + `device_sim/firmware_runner.py`）  
   `agent.py` 持续运行并周期执行 OTA 检查；`firmware_runner.py` 模拟设备业务循环（计数）并持久化到 `runtime/data/state.json`。检测到 OTA 成功后，agent 会重启 runner 以模拟设备重启生效。

## 关键约定（仓库特有）

- Manifest 字段是固定协议：`version`, `package`, `url`, `sha256`, `signature`；设备端会严格校验缺失字段并报错。
- 签名体系为 **Ed25519**：发布端只读 `server/keys/private.pem` 签名，设备端只读 `server/keys/public.pem` 验签。
- 版本比较不是字符串比较，而是 `x.y.z` 拆分后按整数元组比较（`parse_version`）。
 - 升级成功条件依赖包内 `health.txt`，且内容必须是 `ok`；`packages/1.2.0/health.txt=broken` 是刻意保留的回滚演示样例。
 - 运行态目录约定：`device_sim/runtime/{slots/{a,b},boot.json,downloads,metadata.json,data/*}`。A/B 切换以 `boot.json.active_slot` 为准。
 - `boot.json` 的 `pending_*` 字段表示“待确认启动”状态；agent 达到确认条件后清空 pending，失败则回滚到 `previous_slot`。
 - agent 会临时跳过“刚刚启动失败”的版本，直到服务端发布了新的 manifest 版本，避免坏版本反复抖动。
- 常驻计数状态存储在 `device_sim/runtime/data/state.json`，runner 每次 tick 都会写回；重启后应从该文件恢复计数。
- `packages/*/app.txt` 约定可包含 `version`/`message`/`step`，其中 `step` 控制 runner 每 tick 增量（默认 1）。
- 多处 JSON 文件写入都使用 `ensure_ascii=True, indent=2`，并追加换行；保持同样格式以减少无意义 diff。
- CLI 默认值约定：服务地址 `http://127.0.0.1:8000`，设备 runtime `device_sim/runtime`，公钥路径 `server/keys/public.pem`。
