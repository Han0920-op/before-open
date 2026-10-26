# 第一次在自己的电脑运行

Windows 原生环境推荐使用下面的一键启动；后面的手动终端命令适用于 macOS、Linux，以及 Windows 的 WSL2 终端。以下说明不依赖云环境的 `/workspace` 路径。

当前版本提供可点击的易损耗零售摊位与三段营业过程，也保留饰品、预约服务试算、比较方案和现实观察。**普通用户无需配置模型或填写 API Key**。运营方配置默认智能服务后，自定义想法会自动整理；未配置时可用明确标注的演示条件和手动路径。秒哒发布尚未验证。

## Windows 一键启动（推荐）

1. 安装 Windows 版 [uv](https://docs.astral.sh/uv/getting-started/installation/)、Node.js **24.x**（包含 npm）和 Docker Desktop；下载代码可使用 Git 或 GitHub 的 ZIP。
2. 打开 Docker Desktop，等待引擎就绪，并使用 Linux containers。工具安装后重新打开终端或资源管理器，使 PATH 生效。
3. 在仓库根目录双击 **`start.bat`**。也可在 CMD 输入 `start.bat`，或在 PowerShell 输入 `./start.bat`。

脚本会通过 uv 准备 Python 3.12 和锁定的后端依赖；首次或前端依赖文件变化时执行 `npm ci`；启动或复用 PostgreSQL，执行数据库迁移，然后在**同一个终端窗口**启动前后端。首次运行需要联网下载 Python、依赖和数据库镜像，请等待。就绪后自动打开浏览器；若浏览器没有打开，访问终端显示的本机地址即可。

使用期间保留这个窗口，结束时在窗口按 **Ctrl+C**。前后端会一起停止，数据库保留运行和数据。下次仍然只需打开 Docker Desktop 并双击 `start.bat`，无需手动开两个终端。

脚本仅监听本机：前端 5173、后端 8001，Cookie 设置为本地 HTTP 开发模式。如端口被占用会停止并提示，不会强行结束已有服务。报错后窗口会暂停，方便查看原因。若进程环境已设置 `DATABASE_URL`，则跳过 Docker 并迁移该数据库；普通本地使用无需设置它。项目不自动读取 `.env`。

保留 `.local/`、数据库容器和数据卷，勿通过删除它们来排错。Windows 原生与 WSL 的 Python 虚拟环境不同，请在同一份代码中固定使用一种运行方式。该脚本是本地开发入口，不是公网部署脚本。

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

1. 点击“卖冰粉”，再点“开始预演”。
2. 查看摘要中的演示条件，确认后进入小摊场景；可展开调整全部条件。
3. 点击价签定价格、点击备货箱定数量，查看预计本轮支出。
4. 检查三段需求分配，点击“确认条件，开摊”。分段为演示假设，不是真实客流。
5. 点击“下一阶段”或自动播放；可暂停、刷新后继续，也可直接计算至完整结算。
6. 收摊后点击“回到筹备，另试方案”，改备货后重新开摊；旧方案保留，可以比较。
7. 在“现实挑战”准备任务，实际开展后再记录观察与局限。

饰品与预约服务当前继续使用原有参数沙盒，分别显示库存与现金、预约与时间的差异，专属二维过程将在下一批加入。自定义想法在服务可用时自动整理，未知项会追问，草稿须由你确认才保存；服务不可用时不伪装 AI 已工作。

更新到此版本后，Windows 可直接运行 `start.bat`，会自动执行数据库迁移 **0003**。手动启动需先在 backend 执行 `uv sync --locked --no-install-project`、`uv run --no-sync alembic upgrade head`。保留原 `.local/` 和数据库，无需重新建库。

若你负责部署，默认模型只在服务器环境中配置，参见 [Agent 运行说明](AGENT_GUIDE.md)。不要把 Key 发到聊天、写入前端或提交 Git。

## 下次如何启动

Windows 原生：打开 Docker Desktop，双击仓库根目录的 `start.bat`；在其窗口按 Ctrl+C 停止前后端。

macOS / Linux / WSL 手动启动：不需要重新 clone 或重装依赖。先打开 Docker，在仓库根运行 `python3 scripts/dev_db.py`，然后分别启动第 4、5 步的两个终端。停止前后端时，在各自终端按 Ctrl+C。

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
