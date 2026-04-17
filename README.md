# OTA Lab（单机远程更新学习项目）

这个项目在一台电脑上同时模拟：
- **OTA 服务端**：发布 `manifest.json` 和升级包
- **设备端**：检查更新、下载、校验、A/B 切换、启动确认、失败回滚

使用 **uv** 管理环境与依赖。

## 1. 初始化演示数据

在项目根目录执行：

```bash
uv run python scripts/setup_demo.py
```

该命令会：
- 生成签名密钥（`server/keys`）
- 根据 `packages/` 生成升级包（`server/storage/packages`）
- 初始化设备运行态（`device_sim/runtime`）：`slots/a` 为 `1.0.0`，`slots/b` 备用，`boot.json` 激活 `a`

## 2. 启动 OTA 服务端

```bash
uv run python server/app.py
```

默认监听 `http://127.0.0.1:8000`。

如果要给 QEMU 虚拟机使用，请改成：

```bash
uv run python server/app.py --host 0.0.0.0 --port 8000
```

## 3. 启动常驻设备（推荐）

另开一个终端，在项目根目录执行：

```bash
uv run python device_sim/agent.py
```

设备会持续运行固件计数逻辑，并按固定间隔自动检查 OTA 更新。

## 4. 场景一：成功升级（1.0.0 -> 1.1.0）

在第三个终端执行：

```bash
uv run python scripts/publish_release.py --version 1.1.0
```

预期：agent 自动发现新版本，升级写入 inactive slot 并切换 active slot，随后重启固件进程。计数步长从 `+1` 变为 `+2`。

## 5. 场景二：发布故障包并自动回滚（1.1.0 -> 1.2.0）

`packages/1.2.0` 内置坏健康状态（`health.txt=broken`），用于演示回滚。

```bash
uv run python scripts/publish_release.py --version 1.2.0
```

预期：agent 自动尝试升级，新 slot 启动失败后自动回滚到旧 slot，当前版本保持 `1.1.0`，固件继续运行。该失败版本会被临时拉黑，等待发布新版本后再尝试。

## 6. 手动单次 OTA 检查（兼容原流程）

```bash
uv run python device_sim/client.py
```

该命令只执行一次 OTA 检查与安装，不会常驻运行。

## 7. 常用排查

查看设备当前版本：

```bash
cat device_sim/runtime/metadata.json
```

查看 A/B 启动状态：

```bash
cat device_sim/runtime/boot.json
```

查看计数状态：

```bash
cat device_sim/runtime/data/state.json
```

查看 runner 心跳状态：

```bash
cat device_sim/runtime/data/runner_status.json
```

查看当前发布清单：

```bash
cat server/storage/manifest.json
```

## 8. QEMU 真设备模型（WIP，可运行骨架）

1. 准备 QEMU 运行资产（云镜像 + overlay 磁盘 + cloud-init seed）：

```bash
uv run python scripts/qemu_prepare.py
```

2. 启动 QEMU（默认把当前仓库通过 9p 挂载到 guest 的 `/mnt/host`）：

```bash
uv run python scripts/qemu_run.py
```

`qemu_run.py` 会自动选择可用加速器（`hvf/kvm/whpx/tcg`）。如果你要手动指定，可用：

```bash
uv run python scripts/qemu_run.py --accel tcg --cpu-model max
```

3. guest 首次启动后会自动：
   - 执行 `scripts/qemu_guest_init.py` 初始化 `/var/lib/ota-runtime` 为 `1.0.0`
   - 启动 `device_sim/agent.py`（`--restart-mode system`），OTA 成功后触发整机重启

4. 在 host 发布版本触发 OTA：

```bash
uv run python scripts/publish_release.py --version 1.1.0
```

可在 QEMU 控制台观察：新版本拉取 -> 切 slot -> 系统重启 -> 新版本确认。
