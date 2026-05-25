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
echo "==> 部署完成！访问 https://trading.yusuan.xyz"
echo "==> 查看日志: docker compose -f docker-compose.prod.yml logs -f server"
