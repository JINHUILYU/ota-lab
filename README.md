# OTA Lab

单机 OTA：使用 Python + Flask + QEMU 模拟真实设备升级流程，覆盖 **A/B 分区切换、签名校验、自动重启、失败回滚**。

## 项目包含什么

- **OTA 服务端**：发布 `manifest.json` 与升级包下载接口。
- **设备端（本地/虚拟机）**：周期检查更新、下载校验、A/B 切换、pending 确认、失败回滚。
- **演示固件版本**：`1.0.0` 与 `1.1.0` 都会自动运行，核心差异是计数步长（`+1` vs `+2`）。

## 环境要求

- Python `>=3.11`
- 使用 `uv` 管理环境与运行命令
- QEMU 演示需安装 `qemu-system-x86_64`、`qemu-img`

## 快速开始（本地进程模型）

1. 初始化演示资产：

```bash
uv run python scripts/setup_demo.py
```

这会生成密钥与升级包，并初始化设备运行态 `device_sim/runtime`（默认 `active_slot=a`，版本 `1.0.0`）。

2. 启动 OTA 服务端：

```bash
uv run python server/app.py
```

3. 启动常驻设备 agent：

```bash
uv run python device_sim/agent.py
```

4. 发布 `1.1.0`：

```bash
uv run python scripts/publish_release.py --version 1.1.0
```

预期：自动升级成功，runner 从 `+1` 变为 `+2`。

5. 发布故障包 `1.2.0`（演示回滚）：

```bash
uv run python scripts/publish_release.py --version 1.2.0
```

预期：新 slot 启动失败后自动回滚，版本保持 `1.1.0`。

## QEMU 真设备演示

先在 **host** 执行一次初始化（不是在 guest 里执行）：

```bash
uv run python scripts/setup_demo.py
```

用途：生成密钥与升级包（`server/storage/packages`），供 QEMU guest 后续 OTA 下载与验证。

### 执行流程与命令作用

```text
Host: setup/publish/server/qemu scripts
  -> Guest: ota-device.service (拉 manifest、下载升级包、A/B 切换、重启确认)
```

| 在哪执行 | 指令 | 目的 |
|---|---|---|
| host | `uv run python scripts/setup_demo.py` | 生成密钥、升级包、初始化演示资产 |
| host | `uv run python server/app.py --host 0.0.0.0 --port 8000` | 启动 OTA 服务端，供 guest 拉取 manifest 与包 |
| host | `uv run python scripts/qemu_prepare.py` | 生成 QEMU 运行资产（overlay/seed/cloud-init） |
| host | `uv run python scripts/qemu_prepare.py --reset-disk` | 强制重建 guest 磁盘，应用新的 cloud-init 配置 |
| host | `uv run python scripts/qemu_run.py` | 启动 QEMU 虚拟机 |
| host | `uv run python scripts/publish_release.py --version <ver> --server-url http://10.0.2.2:8000` | 发布新版本（`10.0.2.2` 为 guest 访问 host 地址） |
| guest | `sudo journalctl -fu ota-device.service --no-pager` | 实时观察 OTA 检测、升级、回滚日志 |

1. 以 host 可访问方式启动 OTA 服务端：

```bash
uv run python server/app.py --host 0.0.0.0 --port 8000
```

2. 准备 QEMU 运行资产：

```bash
uv run python scripts/qemu_prepare.py
```

如修改了 `qemu_prepare.py` 或 cloud-init，必须重建磁盘：

```bash
uv run python scripts/qemu_prepare.py --reset-disk
```

3. 启动 QEMU：

```bash
uv run python scripts/qemu_run.py
```

`qemu_run.py` 会自动选择可用加速器（`hvf/kvm/whpx/tcg`）。如需手动指定：

```bash
uv run python scripts/qemu_run.py --accel tcg --cpu-model max
```

4. 在 host 发版（QEMU 场景必须用 `10.0.2.2`）：

```bash
uv run python scripts/publish_release.py --version 1.1.0 --server-url http://10.0.2.2:8000
```

5. 在 guest 观察 OTA 日志：

```bash
sudo journalctl -fu ota-device.service --no-pager
```

调试登录（仅实验环境）：`ubuntu / ubuntu`

**退出 QEMU：`Ctrl+A`，然后 `x`。**

## OTA 机制（A/B + pending）

1. agent 拉取 manifest 并比较版本。
2. 下载升级包，执行 SHA256 与 Ed25519 验签。
3. 将包解压到 inactive slot（例如 `a -> b`）。
4. 切换 `boot.json.active_slot` 并写入 `pending_*`。
5. 触发重启（本地模型可重启 runner；QEMU 使用 system reboot）。
6. 新 slot 启动后进入 pending 观察期。
7. 达到确认阈值后清空 `pending_*`，升级完成。
8. 若启动失败/超时，回滚到 previous slot，并临时跳过该失败发布（按 manifest 指纹）。

## 验收与排障

### 状态文件

```bash
cat device_sim/runtime/metadata.json
cat device_sim/runtime/boot.json
cat device_sim/runtime/data/runner_status.json
cat device_sim/runtime/data/state.json
cat server/storage/manifest.json
```

QEMU guest 对应路径前缀改为 `/var/lib/ota-runtime/`。

```
cat /var/lib/ota-runtime/metadata.json
cat /var/lib/ota-runtime/boot.json
cat /var/lib/ota-runtime/data/runner_status.json
cat /var/lib/ota-runtime/data/state.json
curl -s http://10.0.2.2:8000/manifest.json
```

### 成功升级到 1.1.0 的判定

- `metadata.json.version == "1.1.0"`
- `boot.json.pending_slot == null`
- `runner_status.json.version == "1.1.0"` 且计数步长表现为 `+2`


```bash
# 重启 OTA 设备服务（修改配置或脚本后常用）
sudo systemctl restart ota-device.service
# 持续跟踪服务日志，观察 OTA 检测/升级/回滚过程
sudo journalctl -fu ota-device.service --no-pager
```

### 常见问题

1. 看到 cloud-init 完成，但没看到 OTA 日志：去看 `journalctl -fu ota-device.service`。
2. 一直升级失败且报连接错误：检查 manifest 中 `url` 是否为 `10.0.2.2`（QEMU 场景）。
3. 修改了 cloud-init 但行为没变：没有 `--reset-disk`，guest 仍在用旧配置。
4. 自动重启但版本不变：查看 `metadata.json` 和 `boot.json`，通常是 pending 失败回滚。  
