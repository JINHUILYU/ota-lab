# OTA Lab（单机远程更新学习项目）

这个项目在一台电脑上同时模拟：
- **OTA 服务端**：发布 `manifest.json` 和升级包
- **设备端**：检查更新、下载、校验、切换版本、失败回滚

使用 **uv** 管理环境与依赖。

## 1. 初始化演示数据

在项目根目录执行：

```bash
uv run python scripts/setup_demo.py
```

该命令会：
- 生成签名密钥（`server/keys`）
- 根据 `packages/` 生成升级包（`server/storage/packages`）
- 初始化设备当前版本为 `1.0.0`（`device_sim/runtime`）

## 2. 启动 OTA 服务端

```bash
uv run python server/app.py
```

默认监听 `http://127.0.0.1:8000`。

## 3. 场景一：成功升级（1.0.0 -> 1.1.0）

另开一个终端，在项目根目录执行：

```bash
uv run python scripts/publish_release.py --version 1.1.0
uv run python device_sim/client.py
```

预期：设备升级成功，当前版本变为 `1.1.0`。

## 4. 场景二：发布故障包并自动回滚（1.1.0 -> 1.2.0）

`packages/1.2.0` 内置坏健康状态（`health.txt=broken`），用于演示回滚。

```bash
uv run python scripts/publish_release.py --version 1.2.0
uv run python device_sim/client.py
```

预期：升级失败并自动回滚，当前版本保持 `1.1.0`。

## 5. 常用排查

查看设备当前版本：

```bash
cat device_sim/runtime/metadata.json
```

查看当前发布清单：

```bash
cat server/storage/manifest.json
```
