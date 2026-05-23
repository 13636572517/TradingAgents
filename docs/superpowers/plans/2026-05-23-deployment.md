# Production Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 TradingAgents 部署到阿里云服务器（47.103.133.232），使用 Docker Compose 托管后端，宿主机 Nginx 代理到端口 8080，应用数据库从 SQLite 切换到 MySQL。

**Architecture:** 本地完成所有代码改动并推送到 git；服务器上 `git pull` + `docker compose build` + `up -d`；Redis / uvicorn / Celery 三个容器通过内部网络通信；uvicorn 绑定到宿主机 `127.0.0.1:8001`；宿主机 Nginx 新增 server 块监听 8080 反向代理到 8001；systemd 服务确保重启后自动启动。

**Tech Stack:** Docker, Docker Compose v2, Nginx（宿主机）, MySQL（宿主机已有）, pymysql

**前置条件:** 认证系统计划（`2026-05-23-auth-system.md`）已执行完毕，`python-jose`、`passlib` 等依赖已添加到 `pyproject.toml`。

---

## 文件结构

| 操作 | 文件 |
|------|------|
| 修改 | `pyproject.toml`（追加 pymysql, cryptography） |
| 修改 | `server/main.py`（CORS 加服务器 IP） |
| **新建** | `.dockerignore` |
| **新建** | `Dockerfile.prod` |
| **新建** | `docker-compose.prod.yml` |
| **新建** | `.env.prod.example` |
| **新建** | `nginx/tradingagents.conf` |
| **新建** | `deploy.sh` |
| **新建** | `tradingagents.service` |

---

### Task 1: 添加 MySQL 依赖到 pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 在 `[project.dependencies]` 末尾追加两个包**

打开 `pyproject.toml`，在 dependencies 列表末尾（`python-multipart` 行之后，即认证计划已添加的包后面）追加：

```toml
    "pymysql>=1.1.0",
    "cryptography>=42.0.0",
```

dependencies 列表结尾应为：

```toml
    "python-jose[cryptography]>=3.3.0",
    "passlib[bcrypt]>=1.7.4",
    "python-multipart>=0.0.9",
    "pymysql>=1.1.0",
    "cryptography>=42.0.0",
]
```

（若认证计划尚未执行，则一并在此时添加 `python-jose`, `passlib`, `python-multipart`。）

- [ ] **Step 2: 本地安装并验证**

```bash
pip install "pymysql>=1.1.0" "cryptography>=42.0.0"
python -c "import pymysql; print('pymysql OK')"
```

预期输出：`pymysql OK`

- [ ] **Step 3: 验证 SQLAlchemy 可以用 pymysql 连接（需要有 MySQL 环境才能真正连接，此处只验证驱动注册）**

```bash
python -c "from sqlalchemy import create_engine; e = create_engine('mysql+pymysql://user:pw@localhost/db'); print('engine created OK')"
```

预期输出：`engine created OK`（不会实际连接，只验证驱动加载）

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat(deploy): add pymysql and cryptography dependencies"
```

---

### Task 2: 更新 CORS（server/main.py）

**Files:**
- Modify: `server/main.py`

- [ ] **Step 1: 在 `allow_origins` 列表里加入服务器地址**

找到 `server/main.py` 中的 `CORSMiddleware` 配置：

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    ...
)
```

改为：

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://47.103.133.232:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "Authorization"],
)
```

- [ ] **Step 2: 确认文件保存后 Python 语法无误**

```bash
python -c "import server.main; print('OK')"
```

预期：`OK`（或 startup 相关日志，无报错）

- [ ] **Step 3: Commit**

```bash
git add server/main.py
git commit -m "feat(deploy): add production server IP to CORS allow_origins"
```

---

### Task 3: 创建 .dockerignore

**Files:**
- Create: `.dockerignore`

- [ ] **Step 1: 创建 `.dockerignore`**

```
.env
.env.prod
.env.prod.example
__pycache__/
**/__pycache__/
*.pyc
*.pyo
.git/
.github/
web/node_modules/
*.db
*.sqlite
tradingagents.db
.pytest_cache/
tests/
docs/
*.md
!README.md
```

- [ ] **Step 2: 验证文件内容合理（确认 .env.prod 不会进镜像）**

```bash
cat .dockerignore | grep env
```

预期输出包含：`.env` 和 `.env.prod`

- [ ] **Step 3: Commit**

```bash
git add .dockerignore
git commit -m "feat(deploy): add .dockerignore to exclude secrets and dev files"
```

---

### Task 4: 创建 Dockerfile.prod（多阶段构建）

**Files:**
- Create: `Dockerfile.prod`

- [ ] **Step 1: 创建 `Dockerfile.prod`**

```dockerfile
# ── Stage 1: 编译 React 前端 ──────────────────────────────────────────────────
FROM node:20-alpine AS frontend
WORKDIR /web
COPY web/package*.json ./
RUN npm ci --silent
COPY web/ ./
RUN npm run build
# 产物在 /web/dist

# ── Stage 2: 构建 Python 虚拟环境 ────────────────────────────────────────────
FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /build
COPY pyproject.toml ./
COPY tradingagents/ ./tradingagents/
COPY cli/ ./cli/
COPY server/ ./server/
RUN pip install .

# ── Stage 3: 最终运行时镜像 ──────────────────────────────────────────────────
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home appuser \
 && install -d -m 0755 -o appuser -g appuser /home/appuser/.tradingagents

USER appuser
WORKDIR /home/appuser/app

# 复制源码（server、tradingagents、cli、manage_users.py）
COPY --chown=appuser:appuser pyproject.toml ./
COPY --chown=appuser:appuser server/ ./server/
COPY --chown=appuser:appuser tradingagents/ ./tradingagents/
COPY --chown=appuser:appuser cli/ ./cli/
COPY --chown=appuser:appuser manage_users.py ./

# 复制前端编译产物
COPY --from=frontend --chown=appuser:appuser /web/dist ./web/dist

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

- [ ] **Step 2: 本地验证 Dockerfile.prod 能构建（可选，镜像较大，需要 Docker 环境）**

```bash
docker build -f Dockerfile.prod -t tradingagents:test . 2>&1 | tail -5
```

预期最后一行：`Successfully built <hash>` 或 `=> exporting to image` (BuildKit)

若没有本地 Docker 可跳过，服务器上 build 时再验证。

- [ ] **Step 3: Commit**

```bash
git add Dockerfile.prod
git commit -m "feat(deploy): add multi-stage Dockerfile.prod with frontend build"
```

---

### Task 5: 创建 docker-compose.prod.yml

**Files:**
- Create: `docker-compose.prod.yml`

- [ ] **Step 1: 创建 `docker-compose.prod.yml`**

```yaml
# docker-compose.prod.yml — 生产环境，不含前端开发服务器
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis_data:/data

  server:
    build:
      context: .
      dockerfile: Dockerfile.prod
    restart: unless-stopped
    ports:
      - "127.0.0.1:8001:8000"   # 只绑定本机，由宿主 nginx 代理
    env_file: .env.prod
    volumes:
      - tradingagents_data:/home/appuser/.tradingagents
    depends_on:
      - redis

  celery:
    build:
      context: .
      dockerfile: Dockerfile.prod
    command: celery -A server.celery_app worker --loglevel=info --concurrency=2
    restart: unless-stopped
    env_file: .env.prod
    volumes:
      - tradingagents_data:/home/appuser/.tradingagents
    depends_on:
      - redis

volumes:
  tradingagents_data:
  redis_data:
```

- [ ] **Step 2: 验证 YAML 格式无误**

```bash
python -c "import yaml, sys; yaml.safe_load(open('docker-compose.prod.yml')); print('YAML valid')"
```

预期：`YAML valid`

- [ ] **Step 3: Commit**

```bash
git add docker-compose.prod.yml
git commit -m "feat(deploy): add production docker-compose.prod.yml"
```

---

### Task 6: 创建 .env.prod.example

**Files:**
- Create: `.env.prod.example`

- [ ] **Step 1: 创建 `.env.prod.example`**

```bash
# .env.prod.example — 复制为 .env.prod 并填入真实值
# 不要把 .env.prod 提交到 git！

# ── 数据库 ─────────────────────────────────────────────────────────────────────
# MySQL 连接字符串（格式：mysql+pymysql://<user>:<password>@<host>/<db>）
DATABASE_URL=mysql+pymysql://YOUR_DB_USER:YOUR_DB_PASSWORD@127.0.0.1:3306/tradingagents

# ── Redis（Docker 内部网络，容器名即 hostname）────────────────────────────────
REDIS_URL=redis://redis:6379/0

# ── 认证（必须设置！用 openssl rand -hex 32 生成）──────────────────────────────
JWT_SECRET=CHANGE_ME_GENERATE_WITH_openssl_rand_hex_32

# ── LLM API Keys（按需填写，至少填一个）─────────────────────────────────────────
DASHSCOPE_API_KEY=
DASHSCOPE_CN_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
ZHIPU_API_KEY=
ZHIPU_CN_API_KEY=
MINIMAX_API_KEY=
MINIMAX_CN_API_KEY=
DEEPSEEK_API_KEY=
```

- [ ] **Step 2: 确认 .env.prod.example 被 git 追踪但 .env.prod 被忽略**

检查 `.gitignore` 里是否有 `.env.prod`（不含 example）。若没有：

```bash
echo ".env.prod" >> .gitignore
git add .gitignore
```

- [ ] **Step 3: Commit**

```bash
git add .env.prod.example .gitignore
git commit -m "feat(deploy): add .env.prod.example template and gitignore .env.prod"
```

---

### Task 7: 创建宿主机 Nginx 配置

**Files:**
- Create: `nginx/tradingagents.conf`

这个文件**不**在 Docker 里使用，而是部署时复制到服务器的 Nginx `sites-enabled` 目录。

- [ ] **Step 1: 创建目录和配置文件**

```bash
mkdir -p nginx
```

创建 `nginx/tradingagents.conf`：

```nginx
# /etc/nginx/sites-enabled/tradingagents.conf
# TradingAgents 反向代理配置
# 监听 8080 端口，代理到 Docker 容器的 uvicorn（127.0.0.1:8001）

server {
    listen 8080;
    server_name _;

    client_max_body_size 10m;

    # 普通 API 和静态文件
    location / {
        proxy_pass         http://127.0.0.1:8001;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # SSE（Server-Sent Events）：分析进度流，需要关闭缓冲
    location ~ ^/api/analyses/[^/]+/stream$ {
        proxy_pass         http://127.0.0.1:8001;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        # SSE 必须禁用 gzip
        gzip               off;
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add nginx/tradingagents.conf
git commit -m "feat(deploy): add nginx reverse proxy config for port 8080"
```

---

### Task 8: 创建 deploy.sh

**Files:**
- Create: `deploy.sh`

- [ ] **Step 1: 创建 `deploy.sh`**

```bash
#!/usr/bin/env bash
# deploy.sh — 在服务器上运行，拉取最新代码并重启服务
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

echo "==> [1/4] 拉取最新代码..."
git pull origin main

echo "==> [2/4] 构建 Docker 镜像（首次较慢，约 5-10 分钟）..."
docker compose -f docker-compose.prod.yml build

echo "==> [3/4] 重启服务容器..."
docker compose -f docker-compose.prod.yml up -d

echo "==> [4/4] 等待服务启动..."
sleep 8
docker compose -f docker-compose.prod.yml ps

echo ""
echo "==> 部署完成！访问 http://47.103.133.232:8080"
echo "==> 查看日志: docker compose -f docker-compose.prod.yml logs -f server"
```

- [ ] **Step 2: 确保脚本有执行权限（在 git 里记录）**

```bash
chmod +x deploy.sh
git update-index --chmod=+x deploy.sh
```

- [ ] **Step 3: Commit**

```bash
git add deploy.sh
git commit -m "feat(deploy): add deploy.sh for one-command deployment"
```

---

### Task 9: 创建 systemd 服务文件

**Files:**
- Create: `tradingagents.service`

这个文件**不**由 git 直接部署，而是部署时手动复制到服务器的 `/etc/systemd/system/`。

- [ ] **Step 1: 创建 `tradingagents.service`**

```ini
[Unit]
Description=TradingAgents Web Application
Documentation=https://github.com/your-org/TradingAgents
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/tradingagents
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml down
TimeoutStartSec=180
TimeoutStopSec=60
Restart=no

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Commit**

```bash
git add tradingagents.service
git commit -m "feat(deploy): add systemd service file for auto-start on boot"
```

---

### Task 10: 推送代码到远程仓库

**Files:** （无本地文件改动）

- [ ] **Step 1: 确认所有改动都已提交**

```bash
git status
```

预期：`nothing to commit, working tree clean`

- [ ] **Step 2: 推送到远程**

```bash
git push origin main
```

预期：代码成功推送

---

### Task 11: 服务器环境准备（SSH 到服务器手动执行）

以下所有命令在服务器上执行。SSH 登录：

```bash
ssh admin@47.103.133.232
# 密码：mCZ123456
```

- [ ] **Step 1: 检查操作系统**

```bash
cat /etc/os-release | head -5
```

记录输出，确认是 Ubuntu 还是 AlmaLinux/CentOS。

- [ ] **Step 2: 安装 Docker（Ubuntu 版本）**

```bash
# 安装 Docker
curl -fsSL https://get.docker.com | sh

# 将当前用户加入 docker 组（避免每次 sudo）
sudo usermod -aG docker $USER

# 立即切换组（或重新 SSH 登录）
newgrp docker

# 验证
docker --version
docker compose version
```

预期：
```
Docker version 26.x.x, build ...
Docker Compose version v2.x.x
```

> **如果是 CentOS/AlmaLinux：**
> ```bash
> sudo yum install -y yum-utils
> sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
> sudo yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
> sudo systemctl enable --now docker
> sudo usermod -aG docker $USER
> newgrp docker
> ```

- [ ] **Step 3: 在 MySQL 中创建 tradingagents 数据库**

```bash
mysql -u gesp -p'mCZ@20260101' -h 127.0.0.1 -P 3306 <<'EOF'
CREATE DATABASE IF NOT EXISTS tradingagents CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON tradingagents.* TO 'gesp'@'localhost';
GRANT ALL PRIVILEGES ON tradingagents.* TO 'gesp'@'127.0.0.1';
FLUSH PRIVILEGES;
SHOW DATABASES LIKE 'tradingagents';
EOF
```

预期输出：包含 `tradingagents` 的结果行。

- [ ] **Step 4: 克隆代码仓库**

```bash
sudo mkdir -p /opt/tradingagents
sudo chown $USER:$USER /opt/tradingagents
git clone <your-repo-url> /opt/tradingagents
cd /opt/tradingagents
```

（将 `<your-repo-url>` 替换为实际 git remote URL，如 `https://github.com/你的账号/TradingAgents.git`）

- [ ] **Step 5: 创建 .env.prod**

```bash
cd /opt/tradingagents
cp .env.prod.example .env.prod

# 生成随机 JWT_SECRET
JWT_SECRET=$(openssl rand -hex 32)
echo "生成的 JWT_SECRET: $JWT_SECRET"

# 用 sed 替换占位符
sed -i "s|CHANGE_ME_GENERATE_WITH_openssl_rand_hex_32|$JWT_SECRET|" .env.prod
sed -i "s|mysql+pymysql://YOUR_DB_USER:YOUR_DB_PASSWORD@127.0.0.1:3306/tradingagents|mysql+pymysql://gesp:mCZ@20260101@127.0.0.1:3306/tradingagents|" .env.prod

# 填入你的 LLM API Key（根据需要填写）
nano .env.prod
```

- [ ] **Step 6: 验证 .env.prod 内容**

```bash
grep -v "^#" .env.prod | grep -v "^$"
```

预期看到：
- `DATABASE_URL=mysql+pymysql://gesp:...@127.0.0.1:3306/tradingagents`
- `REDIS_URL=redis://redis:6379/0`
- `JWT_SECRET=<64位十六进制字符串>`

确认 `JWT_SECRET` 不是占位符。

---

### Task 12: 首次部署

- [ ] **Step 1: 运行 deploy.sh**

```bash
cd /opt/tradingagents
bash deploy.sh
```

预期输出（约 5-10 分钟后）：
```
==> [1/4] 拉取最新代码...
Already up to date.
==> [2/4] 构建 Docker 镜像（首次较慢，约 5-10 分钟）...
...（大量 Docker build 输出）...
==> [3/4] 重启服务容器...
...
==> [4/4] 等待服务启动...
NAME                   IMAGE   COMMAND   SERVICE   STATUS    PORTS
tradingagents-redis-1  ...              redis     running
tradingagents-server-1 ...              server    running   127.0.0.1:8001->8000/tcp
tradingagents-celery-1 ...              celery    running

==> 部署完成！访问 http://47.103.133.232:8080
```

若 STATUS 不是 `running`，查看日志：
```bash
docker compose -f docker-compose.prod.yml logs server --tail=50
```

- [ ] **Step 2: 创建第一个管理员用户**

```bash
cd /opt/tradingagents
docker compose -f docker-compose.prod.yml exec server python manage_users.py add admin YourPassword123
```

预期：`Created user 'admin'`

- [ ] **Step 3: 验证 API 直接可访问（绕过 nginx）**

```bash
curl -s http://127.0.0.1:8001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"YourPassword123"}' | python3 -m json.tool
```

预期：
```json
{
    "access_token": "eyJ...",
    "token_type": "bearer"
}
```

---

### Task 13: 配置宿主机 Nginx

- [ ] **Step 1: 复制 nginx 配置到 sites-enabled**

```bash
sudo cp /opt/tradingagents/nginx/tradingagents.conf /etc/nginx/sites-enabled/tradingagents.conf
```

若服务器 nginx 用 `conf.d` 而非 `sites-enabled`（CentOS 常见）：

```bash
sudo cp /opt/tradingagents/nginx/tradingagents.conf /etc/nginx/conf.d/tradingagents.conf
```

- [ ] **Step 2: 测试 nginx 配置语法**

```bash
sudo nginx -t
```

预期：
```
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

若报错 `bind() to 0.0.0.0:8080 failed (98: Address already in use)`，说明 8080 已被占用：
```bash
sudo ss -tlnp | grep 8080
```
找到占用进程后更换端口（如 8090），同时更新 `nginx/tradingagents.conf` 里的 `listen 8080;`。

- [ ] **Step 3: 重新加载 nginx**

```bash
sudo systemctl reload nginx
```

- [ ] **Step 4: 完整端到端验证**

```bash
# 通过 nginx（8080）访问登录 API
TOKEN=$(curl -s http://127.0.0.1:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"YourPassword123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "Token 获取成功：${TOKEN:0:20}..."

# 用 token 访问受保护接口
curl -s http://127.0.0.1:8080/api/analyses \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | head -5
```

预期：token 非空，analyses 接口返回 `{"items": [], "total": 0}`（或已有数据）

- [ ] **Step 5: 从外网访问**

在**本地浏览器**访问：`http://47.103.133.232:8080`

预期：显示 TradingAgents 登录页面

---

### Task 14: 配置 systemd 自启动

- [ ] **Step 1: 复制 systemd 服务文件**

```bash
sudo cp /opt/tradingagents/tradingagents.service /etc/systemd/system/tradingagents.service
```

- [ ] **Step 2: 重新加载 systemd 并启用服务**

```bash
sudo systemctl daemon-reload
sudo systemctl enable tradingagents
sudo systemctl status tradingagents
```

预期 status 显示：`active (exited)` 或 `active (running)`

- [ ] **Step 3: 测试服务器重启后自动启动（可选但推荐）**

```bash
# 停止服务
sudo systemctl stop tradingagents
docker compose -f /opt/tradingagents/docker-compose.prod.yml ps
# 此时容器应全部停止

# 重新启动
sudo systemctl start tradingagents
sleep 10
docker compose -f /opt/tradingagents/docker-compose.prod.yml ps
```

预期：容器重新运行。

- [ ] **Step 4: 最终验证**

```bash
curl -s http://47.103.133.232:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"YourPassword123"}' \
  | python3 -m json.tool
```

预期：返回 `access_token`。

---

## 日常更新部署

本地修改代码后：

```bash
# 本地
git add . && git commit -m "..." && git push origin main

# 服务器
ssh admin@47.103.133.232
cd /opt/tradingagents
bash deploy.sh
```

---

## 自检：Spec 覆盖确认

| Spec 需求 | 对应 Task |
|-----------|-----------|
| pymysql 依赖 | Task 1 |
| CORS 加服务器 IP | Task 2 |
| .dockerignore | Task 3 |
| Dockerfile.prod 多阶段（Node + Python）| Task 4 |
| docker-compose.prod.yml（redis/server/celery）| Task 5 |
| server 容器绑定 127.0.0.1:8001 | Task 5 |
| .env.prod.example 模板 | Task 6 |
| nginx 配置（port 8080，SSE 无缓冲）| Task 7 |
| deploy.sh | Task 8 |
| systemd 服务文件 | Task 9 |
| MySQL 创建 tradingagents 数据库 | Task 11 |
| .env.prod 生成（含 JWT_SECRET）| Task 11 |
| 首次构建和启动 | Task 12 |
| 创建第一个管理员用户 | Task 12 |
| 宿主机 nginx 配置 | Task 13 |
| 端到端验证（浏览器可访问）| Task 13 |
| systemd 自启动 | Task 14 |
