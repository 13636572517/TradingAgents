# Production Deployment Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 TradingAgents 部署到阿里云服务器（47.103.133.232），使用 Docker Compose + Nginx，应用数据库从 SQLite 切换到 MySQL。

**Architecture:** Docker Compose 管理 redis / server / celery 三个容器；Nginx 以 Docker 容器形式运行，监听宿主机 80 端口并反向代理到 uvicorn；前端在 Docker 镜像构建时编译为静态文件，由 FastAPI 托管。systemd 服务确保服务器重启后自动启动。

**Tech Stack:** Docker, Docker Compose v2, Nginx, MySQL 8.x（服务器已有）, pymysql + SQLAlchemy

---

## 服务器信息

| 项目 | 值 |
|------|-----|
| IP | 47.103.133.232 |
| SSH 用户 | admin |
| 操作系统 | Linux（阿里云，待确认具体发行版） |
| MySQL Host | 127.0.0.1:3306 |
| MySQL 用户 | gesp |
| MySQL 数据库 | tradingagents（需新建） |

---

## 文件结构

### 新建文件

| 文件 | 职责 |
|------|------|
| `docker-compose.prod.yml` | 生产环境 Compose（无热重载、无前端开发服务器） |
| `Dockerfile.prod` | 多阶段构建：Node 编译前端 + Python 安装后端 |
| `nginx/default.conf` | Nginx 反向代理配置 |
| `.env.prod.example` | 生产环境变量模板（不含真实密钥） |
| `deploy.sh` | 一键部署脚本（git pull → build → restart） |
| `tradingagents.service` | systemd 服务文件 |

### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `pyproject.toml` | 新增：`pymysql>=1.1.0`、`cryptography>=42.0.0`（pymysql 的 TLS 依赖） |
| `server/database.py` | `connect_args` 逻辑已支持非 SQLite，无需改动 |
| `server/main.py` | CORS `allow_origins` 加入服务器 IP |

---

## MySQL 初始化（部署前在服务器手动执行一次）

```sql
CREATE DATABASE tradingagents CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON tradingagents.* TO 'gesp'@'localhost';
FLUSH PRIVILEGES;
```

---

## 环境变量（.env.prod）

```bash
# 数据库
DATABASE_URL=mysql+pymysql://gesp:mCZ@20260101@127.0.0.1:3306/tradingagents

# Redis（容器内部网络）
REDIS_URL=redis://redis:6379/0

# 认证（32位以上随机字符串，部署时生成）
JWT_SECRET=<用 openssl rand -hex 32 生成>

# LLM（按需填写）
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
QWEN_API_KEY=
```

`.env.prod` 不提交到 git。仅提交 `.env.prod.example`（密钥用占位符）。

---

## Dockerfile.prod（多阶段构建）

```dockerfile
# ── Stage 1: 编译前端 ─────────────────────────────────────────────
FROM node:20-alpine AS frontend
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ── Stage 2: 构建 Python 虚拟环境 ────────────────────────────────
FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /build
COPY . .
RUN pip install --no-cache-dir ".[server]"

# ── Stage 3: 运行时镜像 ───────────────────────────────────────────
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home appuser \
 && install -d -m 0755 -o appuser -g appuser /home/appuser/.tradingagents
USER appuser
WORKDIR /home/appuser/app

COPY --from=builder --chown=appuser:appuser /build .
COPY --from=frontend --chown=appuser:appuser /web/dist ./web/dist

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

注：`[server]` extras 组需在 `pyproject.toml` 中声明（见下节）。

---

## pyproject.toml extras（新增）

```toml
[project.optional-dependencies]
server = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "sqlalchemy>=2.0.0",
    "celery[redis]>=5.4.0",
    "pymysql>=1.1.0",
    "cryptography>=42.0.0",
    "python-jose[cryptography]>=3.3.0",
    "passlib[bcrypt]>=1.7.4",
    "python-multipart>=0.0.9",
]
```

这样 `pip install ".[server]"` 只安装服务器所需依赖，不拉入 CLI/分析所需的大型包。

---

## 端口策略

宿主机已有项目占用端口 80（nginx）和 8000。因此：

- uvicorn 容器在内部跑 8000，**映射到宿主机 `127.0.0.1:8001`**（仅本机可访问）
- 宿主机 nginx 新增一个 server 块，监听外部 **8080** 端口，反向代理到 `127.0.0.1:8001`
- 不在 docker-compose 里跑 nginx 容器，复用宿主机已有的 nginx
- 外部访问地址：`http://47.103.133.232:8080`

---

## docker-compose.prod.yml

```yaml
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

---

## 宿主机 nginx 配置（新增 server 块）

在宿主机 nginx 的 sites-enabled 目录新增文件 `/etc/nginx/sites-enabled/tradingagents.conf`：

```nginx
server {
    listen 8080;
    server_name _;

    client_max_body_size 10m;

    location / {
        proxy_pass         http://127.0.0.1:8001;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # SSE（分析进度流）需要关闭缓冲
    location ~ ^/api/analyses/.*/(stream|stop)$ {
        proxy_pass         http://127.0.0.1:8001;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 600s;
    }
}
```

部署后执行：
```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## deploy.sh

```bash
#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

echo "==> 拉取最新代码..."
git pull origin main

echo "==> 构建 Docker 镜像..."
docker compose -f docker-compose.prod.yml build

echo "==> 重启服务..."
docker compose -f docker-compose.prod.yml up -d

echo "==> 等待服务启动..."
sleep 5
docker compose -f docker-compose.prod.yml ps

echo "==> 部署完成。访问 http://47.103.133.232:8080"
```

---

## systemd 服务（tradingagents.service）

安装路径：`/etc/systemd/system/tradingagents.service`

```ini
[Unit]
Description=TradingAgents Web Application
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/tradingagents
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml down
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
```

启用命令：
```bash
sudo systemctl enable tradingagents
sudo systemctl start tradingagents
```

---

## 首次部署步骤（手动执行，按顺序）

1. 在服务器安装 Docker 和 Docker Compose v2
2. 克隆代码到 `/opt/tradingagents`
3. 在 MySQL 中创建 `tradingagents` 数据库并授权（见上方 SQL）
4. 生成 `.env.prod`（复制 `.env.prod.example` 后填入真实密钥）
5. 生成 JWT_SECRET：`openssl rand -hex 32`
6. 运行 `bash deploy.sh`
7. 创建第一个管理员用户：`python manage_users.py add admin <密码>`
8. 安装并启用 systemd 服务

---

## .dockerignore（新建）

防止敏感文件和无用文件进入 Docker 构建上下文：

```
.env.prod
.env
__pycache__/
*.pyc
.git/
web/node_modules/
*.db
*.sqlite
```

---

## 不在本 spec 范围内

- HTTPS / SSL 证书（未来可加 Certbot + Let's Encrypt）
- CI/CD 自动部署（未来可加 GitHub Actions）
- 数据备份（MySQL 自带 mysqldump，可加 cron）
- 多服务器/负载均衡
