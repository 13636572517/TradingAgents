#!/usr/bin/env bash
# deploy.sh — 在服务器上运行，拉取最新代码并重启服务（systemd 模式）
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

echo "==> [1/4] 拉取最新代码..."
git pull origin main

echo "==> [2/4] 安装 Python 依赖..."
source venv/bin/activate
pip install -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -q -e .

echo "==> [3/4] 构建前端静态文件..."
cd web && npm ci --prefer-offline --silent && npm run build --silent && cd ..

echo "==> [4/4] 重启 systemd 服务..."
sudo systemctl restart tradingagents-server tradingagents-celery tradingagents-beat
sleep 3
sudo systemctl is-active tradingagents-server tradingagents-celery tradingagents-beat

echo ""
echo "==> 部署完成！访问 https://trading.yusuan.xyz"
echo "==> 查看日志: sudo journalctl -u tradingagents-server -f"
