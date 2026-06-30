# TradingAgents：Docker → systemd 迁移计划

> 目标：去掉 Docker，改用 systemd + venv，对标 GESP 的部署方式。  
> 预计工时：3-4 小时（含测试）  
> 风险：低（MySQL/Futu 已在宿主机，nginx 不用改）

---

## 前置确认

- [ ] backfill 任务已完成，数据库数据完整
- [ ] 通知用户：迁移期间服务会中断约 5-10 分钟

---

## Step 1：安装 Python 3.12（宿主机当前是 3.10）

```bash
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev
python3.12 --version   # 确认 3.12.x
```

---

## Step 2：创建 venv 并安装依赖

```bash
cd /opt/tradingagents
python3.12 -m venv venv
source venv/bin/activate
pip install -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -e .
```

---

## Step 3：构建前端静态文件

```bash
# 服务器上需要 Node.js（如未安装）
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

cd /opt/tradingagents/web
npm config set registry https://registry.npmmirror.com
npm ci
npm run build
# 产物在 web/dist/，FastAPI 会直接 serve
```

---

## Step 4：更新 .env.prod

修改两处（Docker 内网地址 → localhost）：

```bash
# 改前
DATABASE_URL=mysql+pymysql://gesp:...@host.docker.internal:3306/tradingagents
REDIS_URL=redis://redis:6379/0

# 改后
DATABASE_URL=mysql+pymysql://gesp:...@127.0.0.1:3306/tradingagents
REDIS_URL=redis://127.0.0.1:6379/0
```

> 注：宿主机 Redis 是 6.0，Docker 是 7。Celery 基本用法兼容，无问题。

---

## Step 5：创建 systemd service 文件（参考 gesp.service）

### tradingagents.service（uvicorn server）

```ini
# /etc/systemd/system/tradingagents.service
[Unit]
Description=TradingAgents uvicorn server
After=network.target mysql.service redis-server.service

[Service]
User=admin
WorkingDirectory=/opt/tradingagents
EnvironmentFile=/opt/tradingagents/.env.prod
ExecStart=/opt/tradingagents/venv/bin/uvicorn server.main:app \
    --host 127.0.0.1 \
    --port 8001 \
    --workers 2
Restart=always
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### tradingagents-celery.service

```ini
# /etc/systemd/system/tradingagents-celery.service
[Unit]
Description=TradingAgents Celery Worker
After=network.target redis-server.service

[Service]
User=admin
WorkingDirectory=/opt/tradingagents
EnvironmentFile=/opt/tradingagents/.env.prod
ExecStart=/opt/tradingagents/venv/bin/celery \
    -A server.celery_app worker \
    --loglevel=info \
    --concurrency=2
Restart=always
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### tradingagents-celery-beat.service

```ini
# /etc/systemd/system/tradingagents-celery-beat.service
[Unit]
Description=TradingAgents Celery Beat Scheduler
After=network.target redis-server.service

[Service]
User=admin
WorkingDirectory=/opt/tradingagents
EnvironmentFile=/opt/tradingagents/.env.prod
ExecStart=/opt/tradingagents/venv/bin/celery \
    -A server.celery_app beat \
    --loglevel=info
Restart=always
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

---

## Step 6：启动并验证

```bash
sudo systemctl daemon-reload
sudo systemctl enable tradingagents tradingagents-celery tradingagents-celery-beat
sudo systemctl start tradingagents tradingagents-celery tradingagents-celery-beat

# 检查状态
sudo systemctl status tradingagents
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8001/api/health
```

---

## Step 7：停止并移除 Docker 容器

```bash
cd /opt/tradingagents
docker compose -f docker-compose.prod.yml down

# 确认 nginx 仍正常（端口 8001 已由 systemd 接管）
curl -s -o /dev/null -w "%{http_code}" https://trading.yusuan.xyz/api/health
```

---

## Step 8：（可选）卸载 Docker

```bash
# 先确认 GESP 系统不依赖 Docker
docker ps -a   # 应为空

sudo apt remove docker-ce docker-ce-cli containerd.io docker-compose-plugin -y
sudo rm -rf /var/lib/docker
```

---

## 新 deploy 流程（迁移后）

```bash
# 全量部署（约 30 秒）
cd /opt/tradingagents
git pull origin main
source venv/bin/activate && pip install -i https://mirrors.aliyun.com/pypi/simple/ --no-deps -e .
cd web && npm ci && npm run build && cd ..
sudo systemctl restart tradingagents tradingagents-celery tradingagents-celery-beat

# 纯 Python 改动（约 5 秒）
git pull && sudo systemctl restart tradingagents tradingagents-celery
```

---

## 回滚方案

如果 systemd 启动失败，Docker 还没删时可立即回退：

```bash
docker compose -f docker-compose.prod.yml up -d
sudo systemctl stop tradingagents tradingagents-celery tradingagents-celery-beat
```

---

## nginx 改动

**不需要改**。nginx 已配置代理到 `127.0.0.1:8001`，systemd uvicorn 监听同一端口，无缝切换。
