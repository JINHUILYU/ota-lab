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

预期：agent 自动尝试升级，新 slot 启动失败后自动回滚到旧 slot，当前版本保持 `1.1.0`，固件继续运行。该失败发布会被临时跳过，直到 manifest 内容变化后再尝试。

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

如果你修改了 `qemu_prepare.py` 或 cloud-init 配置，请重建磁盘触发完整首启流程：

```bash
uv run python scripts/qemu_prepare.py --reset-disk
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

调试登录（仅实验环境）默认账号密码：

```text
ubuntu / ubuntu
```

## 9. QEMU 调试经验（已验证）

1. **看到 cloud-init 完成不代表 OTA 在运行**  
   OTA agent 的实时日志在 systemd journal，不会持续打印在登录界面：

```bash
sudo journalctl -fu ota-device.service --no-pager
```

2. **guest 必须使用 `10.0.2.2` 访问 host OTA 服务**  
   发版时务必指定：

```bash
uv run python scripts/publish_release.py --version 1.1.0 --server-url http://10.0.2.2:8000
```

3. **修改 cloud-init / qemu_prepare 后必须重建磁盘**  
   否则 guest 会继续使用旧 cloud-init 配置：

```bash
uv run python scripts/qemu_prepare.py --reset-disk
```

4. **自动重启不等于升级成功**  
   以 runtime 状态文件为准：

```bash
cat /var/lib/ota-runtime/metadata.json
cat /var/lib/ota-runtime/boot.json
```

升级成功预期：`version=1.1.0`，`pending_slot=null`。

## 10. OTA 流程详解（QEMU 场景）

- `1.0.0` 和 `1.1.0` 都会在虚拟机启动后自动运行（由 `ota-device.service` 拉起 agent，再拉起当前 active slot 的 runner）。
- 两个版本在本项目里的可见业务差异主要是 `app.txt` 里的 `step`：`1.0.0=+1`，`1.1.0=+2`。
- QEMU 运行后，agent 会按间隔自动检测 OTA；发现新版本后执行 A/B 切换并触发系统重启。

### 10.1 启动后“谁在运行”

1. QEMU 启动 -> cloud-init 执行 -> systemd 启动 `ota-device.service`。
2. `ota-device.service` 启动 `device_sim/agent.py`。
3. agent 读取 `/var/lib/ota-runtime/boot.json` 的 `active_slot`，拉起对应 slot 的 `firmware_runner.py`。
4. runner 读取该 slot 内的 `app.txt`（版本、message、step），并持续计数写入 `state.json`。

### 10.2 一次成功 OTA 的完整时序

1. agent 拉取 `manifest.json`。  
2. 比较 `manifest.version` 和本地 `metadata.json.version`。  
3. 新版本可升级时，下载 zip 包并做 SHA256/签名校验。  
4. 解压到 inactive slot（例如当前 `a`，则写入 `b`）。  
5. 更新 `boot.json`：切换 `active_slot` 到新 slot，并标记 `pending_*`。  
6. 由于 QEMU 场景使用 `--restart-mode system`，agent 执行整机重启。  
7. 重启后 runner 从新 slot 启动；agent 观察到 pending 版本稳定运行达到阈值（`confirm-ticks`）后确认提交，清空 `pending_*`。

### 10.3 升级失败时会发生什么

1. 新 slot 启动失败（例如 `health.txt != ok`）或 pending 超时。  
2. agent 回滚：恢复 `active_slot` 和旧版本号。  
3. 为避免抖动，agent 会临时跳过“刚失败的 manifest 内容”（按 manifest 指纹），直到发布内容变化后再尝试。

### 10.4 如何确认“真的升上去了”

```bash
cat /var/lib/ota-runtime/metadata.json
cat /var/lib/ota-runtime/boot.json
cat /var/lib/ota-runtime/data/runner_status.json
```

成功升级到 `1.1.0` 的典型状态：
- `metadata.json.version == "1.1.0"`
- `boot.json.pending_slot == null`
- `runner_status.json.version == "1.1.0"` 且计数步长表现为 `+2`
