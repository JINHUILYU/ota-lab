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
```

当前仓库未配置自动化测试与 lint（无 `pytest`/`ruff`/`mypy` 等配置和测试目录）。可用下面命令做单场景验证（相当于“单个集成测试”）：

```bash
# 单场景：发布 1.1.0 并执行一次设备升级
uv run python scripts/publish_release.py --version 1.1.0
uv run python device_sim/client.py
```

## 高层架构（跨文件主流程）

这是一个单机 OTA 流程实验项目，包含三条主线：

1. **发布准备**（`scripts/setup_demo.py`）  
   从 `packages/<version>/` 读取固件内容，构建 `server/storage/packages/ota-<version>.zip`；首次生成 `server/keys/{private,public}.pem`；初始化 `device_sim/runtime` 为 `1.0.0`。
2. **服务端分发**（`server/app.py` + `scripts/publish_release.py`）  
   `publish_release.py` 用私钥对 zip 包签名并写入 `server/storage/manifest.json`；`server/app.py` 对外提供 `/manifest.json` 与 `/packages/<file>` 下载接口。
3. **设备端升级与回滚**（`device_sim/client.py`）  
   读取本地 `device_sim/runtime/metadata.json` 当前版本 -> 拉取 manifest -> 比较版本 -> 下载包 -> SHA256 校验 -> 公钥验签 -> 解压到 staged -> 切换 current 并执行健康检查；失败则回滚到 backup 并恢复旧版本号。

## 关键约定（仓库特有）

- Manifest 字段是固定协议：`version`, `package`, `url`, `sha256`, `signature`；设备端会严格校验缺失字段并报错。
- 签名体系为 **Ed25519**：发布端只读 `server/keys/private.pem` 签名，设备端只读 `server/keys/public.pem` 验签。
- 版本比较不是字符串比较，而是 `x.y.z` 拆分后按整数元组比较（`parse_version`）。
- 升级成功条件依赖包内 `health.txt`，且内容必须是 `ok`；`packages/1.2.0/health.txt=broken` 是刻意保留的回滚演示样例。
- 运行态目录约定：`device_sim/runtime/{current,downloads,staged,backup,metadata.json}`。变更升级流程时要保持这些路径语义一致。
- 多处 JSON 文件写入都使用 `ensure_ascii=True, indent=2`，并追加换行；保持同样格式以减少无意义 diff。
- CLI 默认值约定：服务地址 `http://127.0.0.1:8000`，设备 runtime `device_sim/runtime`，公钥路径 `server/keys/public.pem`。
