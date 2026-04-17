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
