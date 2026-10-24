# 第一次在自己的电脑运行

这份说明适用于 macOS、Linux，以及 Windows 的 WSL2 终端。Windows 用户可使用 Docker Desktop，并在其设置里开启 WSL integration。以下命令不依赖云环境的 `/workspace` 路径。

当前版本可以手动建立场景、经营试算、比较方案和记录现实观察。AI 自动整理想法、Agent 和秒哒发布尚未接入，**现在运行不需要模型 API Key**。

## 1. 准备工具

安装 Git、Python 3.12、[uv](https://docs.astral.sh/uv/getting-started/installation/)、Node.js 24（包含 npm）、Docker Desktop 或 Docker Engine。启动 Docker，确认下面的命令可用：

```bash
git --version
python3 --version
uv --version
node --version
npm --version
docker info
```

Python 应为 3.12，Node 应为 24.x；Docker 必须已经运行。首次安装依赖和 PostgreSQL 镜像需要联网。

## 2. 下载代码

```bash
git clone https://github.com/Han0920-op/before-open.git
cd before-open
```

如果仓库是私有仓库，先在自己的电脑完成 GitHub 登录。不要把 GitHub Token 或数据库口令发到聊天里。

## 3. 启动数据库并安装后端

在仓库根目录运行：

```bash
python3 scripts/dev_db.py
cd backend
uv sync --locked --no-install-project
uv run --no-sync alembic upgrade head
```

数据库脚本会启动本地 PostgreSQL，随机生成开发口令并保存在被 Git 忽略的 `.local/`，无需手动填写数据库密码。重复运行会复用已有容器。不要删除 `.local/` 或 Docker 数据卷来解决报错，以免丢失原来的访问配置或数据。

## 4. 启动后端，保持终端不关闭

仍在 backend 目录：

```bash
uv run --no-sync python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

看到 `Application startup complete` 后，让这个终端继续运行。

## 5. 在第二个终端启动前端

打开另一个终端，进入刚才克隆的仓库中的 frontend 目录：

```bash
cd before-open/frontend
npm ci --no-audit --no-fund
npm run dev
```

`cd` 的路径要按自己的克隆位置调整。npm run dev 会显示本地访问地址，默认端口是 **5173**。在自己电脑的浏览器打开终端显示的地址即可。

后端使用 **8001**、数据库使用 **5432**，前端已经配置好 `/api` 同源代理。初次运行不必修改 `.env`，也不要在前端填写任何服务端密钥。

## 6. 第一次体验

1. 点击“卖冰粉”“做手工饰品”或“接宠物摄影订单”，再点“开始预演”。
2. 查看“演示假设”标签，确认条件后进入沙盒。
3. 修改价格、备货或时间，查看实时试算。
4. 点击“保存为新方案”，再到“比比方案”比较。
5. 在“现实挑战”手动填写任务；实际完成调查后再记录真实观察和局限。

自定义输入不会自动解析成经营数字；当前需要自己填写，或明确选择“用演示条件先试试”。演示数字不是实际成本、销量或调研结论。

## 下次如何启动

不需要重新 clone 或重装依赖。先打开 Docker，在仓库根运行 `python3 scripts/dev_db.py`，然后分别启动第 4、5 步的两个终端。停止前后端时，在各自终端按 Ctrl+C。

项目保存在本地 PostgreSQL，浏览器保存匿名访问凭据；请使用同一个浏览器。清理浏览器数据或更换设备可能无法找回原项目；不要把“清缓存”当作通用排错方式。

## 常见问题

| 现象 | 处理 |
|---|---|
| Docker daemon 无法连接 | 先打开 Docker Desktop 或启动 Docker Engine，再运行数据库脚本 |
| 5432、8001、5173 端口占用 | 检查是否已经启动过本项目；不要终止不认识的服务。默认前端代理指向 8001 |
| 页面能开，业务请求失败 | 确认数据库和后端都在运行，且执行过 `alembic upgrade head` |
| 显示数据库尚未配置 | 本地使用脚本生成配置；已有 `DATABASE_URL` 时会优先使用该绑定，请确认它指向正确开发库，不要公开其值 |
| Node 或 Python 版本不符 | 使用 Node 24、Python 3.12，再执行锁定依赖安装，不使用 force/legacy-peer-deps 绕过问题 |
| 显示旧配置需要恢复 | 保留 `.local/` 与原 Docker 容器，先恢复原容器，避免用空数据库覆盖旧项目 |

普通体验不需要安装 Chromium。只有运行浏览器自动化测试时，才需要额外的系统 Chromium；完整测试和云环境说明见 [前端 README](../frontend/README.md) 与[根 README](../README.md)。
